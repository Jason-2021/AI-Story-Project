"""
Gemini Batch API adapter for TTS (text-to-speech).

回傳的是原始 PCM bytes（16-bit mono）；由 batch_collector 負責
呼叫 _write_wav() 轉成標準 WAV 並存檔。

NOTE: speech_config 在 batch request dict 的格式需實測確認。
      目前使用 REST API snake_case 格式。
"""

from google import genai

client = genai.Client()

_PENDING_STATES = {"JOB_STATE_PENDING", "JOB_STATE_RUNNING"}
_FAILED_STATES  = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED"}


def submit_tts_batch(scenes_map: dict, model_name: str, voice_name: str) -> str:
    """
    scenes_map: {key: narration_text}
    Returns batch job name (e.g. "batches/12345").
    """
    inline_requests = [
        {
            "key": key,
            "request": {
                "contents": [{"role": "user", "parts": [{"text": narration}]}],
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": voice_name,
                            }
                        }
                    },
                },
            },
        }
        for key, narration in scenes_map.items()
    ]
    batch_job = client.batches.create(
        model=model_name,
        src=inline_requests,
        config={"display_name": f"tts-batch-{len(inline_requests)}sc"},
    )
    return batch_job.name


def collect_tts_batch(batch_job_name: str) -> tuple[str, dict, dict]:
    """
    Returns (status, successes, failures).
      status:   "pending" | "completed" | "partial" | "failed" | "expired"
      successes: {key: pcm_bytes}  — raw 16-bit mono PCM, NOT WAV
      failures:  {key: error_str}
    """
    batch_job = client.batches.get(name=batch_job_name)
    state = batch_job.state.name

    if state in _PENDING_STATES:
        return "pending", {}, {}
    if state == "JOB_STATE_EXPIRED":
        return "expired", {}, {}
    if state in _FAILED_STATES:
        return "failed", {}, {}

    successes: dict = {}
    failures: dict = {}
    for item in (batch_job.dest.inlined_responses or []):
        key = item.key
        try:
            parts = item.response.candidates[0].content.parts
            if parts and parts[0].inline_data and parts[0].inline_data.data:
                successes[key] = parts[0].inline_data.data
            else:
                failures[key] = "no audio data in response"
        except Exception as e:
            failures[key] = str(e)

    status = "partial" if failures else "completed"
    return status, successes, failures
