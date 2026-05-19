from pathlib import Path
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep

client = genai.Client()


def _log_retry(retry_state):
    print(f"⚠️  [Imagen] 第 {retry_state.attempt_number} 次失敗，{retry_state.next_action.sleep:.1f}s 後重試...")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
    before_sleep=_log_retry,
)
async def generate_image_with_gemini(
    prompt: str,
    output_path: Path,
    model_name: str = "gemini-2.5-flash-image",
    aspect_ratio: str = "16:9",
) -> Path:
    """
    對單一 prompt 呼叫 Gemini 原生圖片生成，將圖片儲存至 output_path。
    失敗時由 tenacity 自動重試最多 3 次（指數退避：2s → 4s → 8s）。
    回傳存檔後的 Path。
    """
    response = await client.aio.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
            ),
        ),
    )

    image_bytes = None
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            image_bytes = part.inline_data.data
            break

    if image_bytes is None:
        raise ValueError("[Gemini Image] 錯誤：模型回傳成功，但未包含任何圖片資料。")

    output_path.write_bytes(image_bytes)
    return output_path
