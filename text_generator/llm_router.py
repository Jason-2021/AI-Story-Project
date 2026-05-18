import os
import yaml
import asyncio
from typing import List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()

from gemini_api import generate_with_gemini

# =====================================================================
# 1. Schema 定義 (資料合約)
#    負責防呆與定義最終 API 回傳的形狀
# =====================================================================

class Scene(BaseModel):
    scene_id: int = Field(description="The chronological sequence number of the scene.")
    narration: str = Field(description="The spoken voiceover script text for this scene.")
    image_prompt: str = Field(description="The visual description prompt for Flux image generation.")

class VideoScript(BaseModel):
    title: str = Field(description="Engaging YouTube Shorts title.")
    description: str = Field(description="YouTube video description with hashtags.")
    tags: List[str] = Field(description="List of SEO tags.")
    scenes: List[Scene] = Field(description="The ordered list of video scenes.")

class ScriptRequest(BaseModel):
    topic: str = Field(description="影片核心主題")
    details: Optional[str] = Field(default="", description="外部背景資料。若無則留空。")
    profile_name: str = Field(description="風格名稱，如 'gaming', 'finance'")
    provider: str = Field(default="openai", description="指定代工廠：'openai' 或 'gemini'")

# =====================================================================
# 2. 內部輔助函數 (Helper Functions)
#    負責讀取硬碟中的設定檔，並將資料攪拌均勻
# =====================================================================

CONFIG_DIR = r"C:\Users\ASUS\Documents\MasCourseCode\AI-Story-Project\configs"

def _load_yaml(file_path: str) -> dict:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"[Router 錯誤] 找不到設定檔: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _read_text_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"[Router 錯誤] 找不到提示詞模板: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def _build_system_prompt(profile_name: str) -> str:
    """載入 YAML 與 TXT，並將變數注入，產出終極的 System Prompt"""
    base_config = _load_yaml(os.path.join(CONFIG_DIR, "base_config.yaml"))
    profile_config = _load_yaml(os.path.join(CONFIG_DIR, "profiles", f"{profile_name}.yaml"))
    template = _read_text_file(os.path.join(CONFIG_DIR, "system_prompt.txt"))

    # 合併禁語陣列 (DRY 原則)
    global_forbidden = base_config.get("global_forbidden_phrases", [])
    specific_forbidden = profile_config.get("script", {}).get("specific_forbidden_phrases", [])
    merged_forbidden = global_forbidden + specific_forbidden

    # 安全地讀取陣列並轉換為字串，供 Prompt 使用
    hooks = profile_config.get("script", {}).get("hooks", [])
    ctas = profile_config.get("script", {}).get("cta_variants", [])
    
    # 注入變數 (使用 f-string 機制替換佔位符)
    try:
        final_prompt = template.format(
            profile_name=profile_config.get("display_name", profile_name),
            profile_tone=profile_config.get("script", {}).get("tone", ""),
            base_word_count=base_config.get("video_settings", {}).get("target_word_count", "135 to 145"),
            base_max_scenes=base_config.get("video_settings", {}).get("max_scenes", 5),
            global_forbidden=", ".join(f"'{p}'" for p in merged_forbidden),
            profile_hooks=" | ".join(hooks) if hooks else "None",
            profile_ctas=" or ".join(ctas) if ctas else "None",
            profile_prompt_suffix=profile_config.get("visuals", {}).get("prompt_suffix", "")
        )
        return final_prompt
    except KeyError as e:
        raise KeyError(f"[Router 錯誤] 你的 system_prompt.txt 裡面有未對應的變數佔位符: {e}")

def _build_user_prompt(topic: str, details: str) -> str:
    """處理外部傳入的彈性內容"""
    prompt = f"Topic: {topic}\n"
    if details and details.strip():
        prompt += f"Details: {details}\n"
    else:
        prompt += "Details: (No additional details provided. Use your global knowledge.)\n"
    return prompt

# =====================================================================
# 3. 核心路由器 (The Main Router)
#    暴露給外層 main.py 的唯一接口
# =====================================================================

# 引入底層純 API 代工函數 (假設你在同一層資料夾有這兩支檔案)
# from .openai_api import generate_with_openai
# from .gemini_api import generate_with_gemini

async def generate_script_router(request: ScriptRequest) -> VideoScript:
    """
    接收標準 Request，組裝 Prompt 後，根據 provider 派發任務。
    回傳的必為 100% 完美的 VideoScript 物件。
    """
    print(f"\n🚀 [Router] 啟動劇本生成任務 | 風格: {request.profile_name} | 引擎: {request.provider}")

    # 步驟 1：大腦組裝 (Data Assembly)
    print("⏳ [Router] 正在合併 YAML 設定與提示詞模板...")
    system_msg = _build_system_prompt(request.profile_name)
    user_msg = _build_user_prompt(request.topic, request.details)

    # 步驟 2：接線生分流 (Task Routing)
    provider = request.provider.lower()
    
    print(f"📡 [Router] 任務交接給代工廠 -> {provider}.py ...")
    
    if provider == "openai":
        # 呼叫 OpenAI 代工廠 (並把 VideoScript 這個 Pydantic Class 傳進去讓它綁定)
        # return await generate_with_openai(system_msg, user_msg, response_schema=VideoScript)
        
        # 開發階段的 Mock 回傳
        print("✅ [OpenAI API Mock] 成功生成並解析 JSON")
        return VideoScript(title="OpenAI Test", description="Test", tags=[], scenes=[])
        
    elif provider == "gemini":
        # 呼叫 Gemini 代工廠
        return await generate_with_gemini(system_msg, user_msg, response_schema=VideoScript)
        
        
    elif provider == "prompt":
        print(system_msg)
        print(user_msg)
        return VideoScript(title="Prompt Test", description="Test", tags=[], scenes=[])
    else:
        raise ValueError(f"❌ [Router 錯誤] 不支援的 LLM 供應商: '{provider}'。請選擇 'openai' 或 'gemini'。")


# =====================================================================
# 4. 測試區塊
# =====================================================================
if __name__ == "__main__":
    async def run_test():
        # 模擬一份外層進來的完美 Request
        req = ScriptRequest(
            topic="The 2008 Financial Crisis",
            details="Focus on Wall Street CDOs.",
            profile_name="finance",
            provider="gemini"  # 切換這裡就可以完美轉發！
        )
        
        # 呼叫 Router
        try:
            result = await generate_script_router(req)
            print(f"\n🎉 [結果] 成功拿到劇本物件: {result.title}\n")
            print(f"Description: {result.description}\n")
            print(f"tags: {result.tags}\n")
            print(f"scenes: {result.scenes}\n")
        except FileNotFoundError as e:
            print(f"\n⚠️ 提示: 你需要先把 configs/ 資料夾與 YAML/TXT 檔案建立好才能真實運行。\n錯誤訊息: {e}")

    asyncio.run(run_test())