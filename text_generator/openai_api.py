from typing import Type
from pydantic import BaseModel
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep

client = AsyncOpenAI()


def _log_retry(retry_state):
    print(f"⚠️  [OpenAI] 第 {retry_state.attempt_number} 次失敗，{retry_state.next_action.sleep:.1f}s 後重試...")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    reraise=True,
    before_sleep=_log_retry,
)
async def generate_with_openai(
    system_msg: str,
    user_msg: str,
    response_schema: Type[BaseModel],
    model_name: str = "gpt-4o",
    temperature: float = 0.7,
) -> BaseModel:
    """
    純粹的 OpenAI Responses API 代工廠。
    使用 responses.parse() 直接回傳 Pydantic 物件。
    """
    response = await client.responses.parse(
        model=model_name,
        input=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        text_format=response_schema,
        temperature=temperature,
    )

    if response.output_parsed is None:
        raise ValueError("[OpenAI API] 錯誤：模型回傳成功，但未產生預期的 JSON 結構。")

    return response.output_parsed
