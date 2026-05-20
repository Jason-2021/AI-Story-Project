import wave
from pathlib import Path
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep

client = genai.Client()


def _log_retry(retry_state):
    print(f"⚠️  [TTS] 第 {retry_state.attempt_number} 次失敗，{retry_state.next_action.sleep:.1f}s 後重試...")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    reraise=True,
    before_sleep=_log_retry,
)
async def generate_tts_with_gemini(
    text: str,
    output_path: Path,
    model_name: str = "gemini-2.5-flash-preview-tts",
    voice_name: str = "Pax",
    sample_rate: int = 24000,
) -> Path:
    """
    將文字轉換為語音並存成 WAV 檔。
    Gemini TTS 回傳原始 PCM（16-bit mono），由此函數包裝成標準 WAV。
    失敗時由 tenacity 自動重試最多 3 次。
    回傳存檔後的 Path。
    """
    response = await client.aio.models.generate_content(
        model=model_name,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        ),
    )

    pcm_bytes = response.candidates[0].content.parts[0].inline_data.data

    if not pcm_bytes:
        raise ValueError("[Gemini TTS] 錯誤：模型回傳成功，但未包含任何音訊資料。")

    _write_wav(pcm_bytes, output_path, sample_rate)
    return output_path


def _write_wav(pcm_bytes: bytes, output_path: Path, sample_rate: int) -> None:
    """將 raw PCM（16-bit, mono）包裝成標準 WAV 檔。"""
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)    # mono
        wf.setsampwidth(2)    # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
