import os
from typing import Type
from pydantic import BaseModel
from google import genai
from google.genai import types

# =====================================================================
# 初始化 Client
# (SDK 預設會自動去系統環境變數尋找 "GEMINI_API_KEY")
# =====================================================================
client = genai.Client()

async def generate_with_gemini(
    system_msg: str, 
    user_msg: str, 
    response_schema: Type[BaseModel]
) -> BaseModel:
    """
    純粹的 Gemini API 代工廠。
    只負責將文字與 Schema 打包送出，並接回 100% 完美的 Pydantic 物件。
    
    :param system_msg: 由 Router 組裝好的大腦守則 (包含 Tone, 禁語等)
    :param user_msg: 使用者的實際輸入內容 (Topic, Details)
    :param response_schema: Pydantic 類別 (如 VideoScript)，用來鎖死輸出格式
    :return: 已經被驗證並實例化的 Pydantic 物件
    """
    
    # 選擇適合量產、速度極快且支援結構化輸出的模型
    # (目前主流推薦使用 flash 版本)
    model_name = "gemini-2.5-flash"
    
    # 建立模型配置 (Config)
    config = types.GenerateContentConfig(
        # 1. 隔離 System Prompt：將導演守則獨立放入系統層級
        system_instruction=system_msg,
        
        # 2. 開啟 JSON 模式
        response_mime_type="application/json",
        
        # 3. 綁定硬性結構：將 VideoScript 模具交給 Gemini
        response_schema=response_schema,
        
        # 4. 溫度設定：0.7 可以讓劇本保有創意，同時因為有 schema 鎖住，不用擔心格式跑掉
        temperature=0.7, 
    )

    try:
        # ⚡ 核心：使用 client.aio 進行非同步呼叫，確保 Python 主執行緒不卡死
        # google-genai SDK 非常聰明，contents 參數可以直接吃純字串，它會自動視為 user role
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=user_msg,
            config=config,
        )
        
        # 🌟 神級功能：SDK 底層已經幫我們做完 json.loads() 並灌入 Pydantic 了！
        # 直接回傳 response.parsed 即可拿到物件
        if response.parsed is not None:
            return response.parsed
        else:
            # 萬一 API 抽風沒有吐出解析物件，手動拋出錯誤讓 Router 的重試機制接手
            raise ValueError("[Gemini API] 錯誤：模型回傳成功，但未產生預期的 JSON 結構。")
            
    except Exception as e:
        print(f"❌ [Gemini API 連線/生成錯誤]: {e}")
        raise e