from typing import Type
from pydantic import BaseModel
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep

client = genai.Client()


def _log_retry(retry_state):
    print(f"⚠️  [Gemini] 第 {retry_state.attempt_number} 次失敗，{retry_state.next_action.sleep:.1f}s 後重試...")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    reraise=True,
    before_sleep=_log_retry,
)
async def generate_with_gemini(
    system_msg: str,
    user_msg: str,
    response_schema: Type[BaseModel],
    model_name: str = "gemini-2.5-flash",
    temperature: float = 0.7,
) -> BaseModel:
    """
    純粹的 Gemini API 代工廠。
    只負責將文字與 Schema 打包送出，並接回 100% 完美的 Pydantic 物件。
    失敗時由 tenacity 自動重試最多 3 次（指數退避：2s → 4s → 8s）。
    """
    config = types.GenerateContentConfig(
        system_instruction=system_msg,
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=temperature,
    )

    response = await client.aio.models.generate_content(
        model=model_name,
        contents=user_msg,
        config=config,
    )

    if response.parsed is not None:
        return response.parsed

    raise ValueError("[Gemini API] 錯誤：模型回傳成功，但未產生預期的 JSON 結構。")
