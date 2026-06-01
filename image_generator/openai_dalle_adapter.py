import base64
from pathlib import Path
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep

client = AsyncOpenAI()

_ASPECT_TO_SIZE = {
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "1:1":  "1024x1024",
}


def _log_retry(retry_state):
    print(f"⚠️  [OpenAI Image] 第 {retry_state.attempt_number} 次失敗，{retry_state.next_action.sleep:.1f}s 後重試...")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    reraise=True,
    before_sleep=_log_retry,
)
async def generate_image_with_openai(
    prompt: str,
    output_path: Path,
    model_name: str = "gpt-image-2",
    aspect_ratio: str = "16:9",
    quality: str = "low",
) -> Path:
    size = _ASPECT_TO_SIZE.get(aspect_ratio, "1024x1024")
    response = await client.images.generate(
        model=model_name,
        prompt=prompt,
        size=size,
        quality=quality,
        n=1,
    )
    image_bytes = base64.b64decode(response.data[0].b64_json)
    output_path.write_bytes(image_bytes)
    return output_path
