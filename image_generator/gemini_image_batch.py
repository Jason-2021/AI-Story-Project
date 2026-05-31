"""
Gemini Batch API adapter for image generation.

submit_image_batch() — 建立 batch job，回傳 batch job name
collect_image_batch() — 查詢結果，回傳 (status, successes, failures)

NOTE: Gemini batch request 的 dict 格式直接對應 REST API schema（snake_case）。
      image_config / speech_config 等欄位需實測確認 SDK 接受的格式。
"""

from google import genai

client = genai.Client()

# Gemini batch job states
_PENDING_STATES = {"JOB_STATE_PENDING", "JOB_STATE_RUNNING"}
_FAILED_STATES  = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED"}


def submit_image_batch(scenes_map: dict, model_name: str) -> str:
    """
    scenes_map: {custom_id: {"prompt": str, "aspect_ratio": str}}
    Returns batch job name (e.g. "batches/12345").
    """
    inline_requests = [
        {
            "key": custom_id,
            "request": {
                "contents": [{"role": "user", "parts": [{"text": info["prompt"]}]}],
                "generation_config": {
                    "response_modalities": ["IMAGE"],
                    "image_config": {"aspect_ratio": info["aspect_ratio"]},
                },
            },
        }
        for custom_id, info in scenes_map.items()
    ]
    batch_job = client.batches.create(
        model=model_name,
        src=inline_requests,
        config={"display_name": f"img-batch-{len(inline_requests)}sc"},
    )
    return batch_job.name


def collect_image_batch(batch_job_name: str) -> tuple[str, dict, dict]:
    """
    Returns (status, successes, failures).
      status:   "pending" | "completed" | "partial" | "failed" | "expired"
      successes: {custom_id: image_bytes}
      failures:  {custom_id: error_str}
    """
    batch_job = client.batches.get(name=batch_job_name)
    state = batch_job.state.name

    if state in _PENDING_STATES:
        return "pending", {}, {}
    if state == "JOB_STATE_EXPIRED":
        return "expired", {}, {}
    if state in _FAILED_STATES:
        return "failed", {}, {}

    # JOB_STATE_SUCCEEDED — extract per-item results
    successes: dict = {}
    failures: dict = {}
    for item in (batch_job.dest.inlined_responses or []):
        key = item.key
        try:
            parts = item.response.candidates[0].content.parts
            for part in parts:
                if part.inline_data and part.inline_data.data:
                    successes[key] = part.inline_data.data
                    break
            else:
                failures[key] = "no image data in response"
        except Exception as e:
            failures[key] = str(e)

    status = "partial" if failures else "completed"
    return status, successes, failures
