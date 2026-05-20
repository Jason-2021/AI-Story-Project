import yaml
import asyncio
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()

from .gemini_api import generate_with_gemini

# =====================================================================
# 1. Schema 定義 (資料合約)
# =====================================================================

class Scene(BaseModel):
    scene_id: int = Field(description="The chronological sequence number of the scene.")
    narration: str = Field(description="The spoken voiceover script text for this scene.")
    image_prompt: str = Field(description="The visual description prompt for Flux image generation.")

class VideoScript(BaseModel):
    title: str = Field(description="Engaging YouTube Shorts title.")
    description: str = Field(description="YouTube video description with hashtags.")
    tags: List[str] = Field(description="List of SEO tags.")
    scenes: List[Scene] = Field(
        min_length=4,
        max_length=5,
        description="The ordered list of video scenes.",
    )

class ScriptRequest(BaseModel):
    topic: str = Field(description="影片核心主題")
    details: Optional[str] = Field(default="", description="外部背景資料。若無則留空。")
    profile_name: str = Field(description="風格名稱，如 'gaming', 'finance'")
    provider: str = Field(default="gemini", description="指定代工廠：'gemini' 或 'openai'")

# =====================================================================
# 2. 內部輔助函數
# =====================================================================

CONFIG_DIR = Path(__file__).parent.parent / "configs"

def _load_yaml(file_path: Path) -> dict:
    if not file_path.exists():
        raise FileNotFoundError(f"[Router 錯誤] 找不到設定檔: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _read_text_file(file_path: Path) -> str:
    if not file_path.exists():
        raise FileNotFoundError(f"[Router 錯誤] 找不到提示詞模板: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def _build_system_prompt(profile_name: str) -> str:
    base_config = _load_yaml(CONFIG_DIR / "base_config.yaml")
    profile_config = _load_yaml(CONFIG_DIR / "profiles" / f"{profile_name}.yaml")
    template = _read_text_file(CONFIG_DIR / "system_prompt.txt")

    global_forbidden = base_config.get("global_forbidden_phrases", [])
    specific_forbidden = profile_config.get("script", {}).get("specific_forbidden_phrases", [])
    merged_forbidden = global_forbidden + specific_forbidden

    hooks = profile_config.get("script", {}).get("hooks", [])
    ctas = profile_config.get("script", {}).get("cta_variants", [])

    try:
        return template.format(
            profile_name=profile_config.get("display_name", profile_name),
            profile_tone=profile_config.get("script", {}).get("tone", ""),
            base_word_count=base_config.get("video_settings", {}).get("target_word_count", "135 to 145"),
            base_max_scenes=base_config.get("video_settings", {}).get("max_scenes", 5),
            script_structure=base_config.get("video_settings", {}).get("script_structure", "Context, Escalation, Climax"),
            global_forbidden=", ".join(f"'{p}'" for p in merged_forbidden),
            profile_hooks=" | ".join(hooks) if hooks else "None",
            profile_ctas=" or ".join(ctas) if ctas else "None",
            profile_prompt_suffix=profile_config.get("visuals", {}).get("prompt_suffix", "")
        )
    except KeyError as e:
        raise KeyError(f"[Router 錯誤] system_prompt.txt 裡有未對應的變數佔位符: {e}")

def _build_user_prompt(topic: str, details: str) -> str:
    prompt = f"Topic: {topic}\n"
    if details and details.strip():
        prompt += f"Details: {details}\n"
    else:
        prompt += "Details: (No additional details provided. Use your global knowledge.)\n"
    return prompt

def _get_llm_settings() -> dict:
    base_config = _load_yaml(CONFIG_DIR / "base_config.yaml")
    return base_config.get("llm_settings", {})

# =====================================================================
# 3. 核心路由器
# =====================================================================

async def generate_script_router(request: ScriptRequest) -> VideoScript:
    """
    接收標準 Request，組裝 Prompt 後，根據 provider 派發任務。
    回傳的必為 100% 完美的 VideoScript 物件。
    """
    print(f"\n🚀 [Router] 啟動劇本生成任務 | 風格: {request.profile_name} | 引擎: {request.provider}")

    print("⏳ [Router] 正在合併 YAML 設定與提示詞模板...")
    system_msg = _build_system_prompt(request.profile_name)
    user_msg = _build_user_prompt(request.topic, request.details)

    llm_settings = _get_llm_settings()
    model_name = llm_settings.get("model_name", "gemini-2.5-flash")
    temperature = llm_settings.get("temperature", 0.7)

    provider = request.provider.lower()
    print(f"📡 [Router] 任務交接給代工廠 -> {provider}.py ...")

    if provider == "gemini":
        return await generate_with_gemini(
            system_msg, user_msg,
            response_schema=VideoScript,
            model_name=model_name,
            temperature=temperature,
        )

    elif provider == "openai":
        # 開發階段的 Mock 回傳
        print("✅ [OpenAI API Mock] 成功生成並解析 JSON")
        return VideoScript(title="OpenAI Test", description="Test", tags=[], scenes=[])

    elif provider == "prompt":
        print(system_msg)
        print(user_msg)
        return VideoScript(title="Prompt Test", description="Test", tags=[], scenes=[])

    else:
        raise ValueError(f"❌ [Router 錯誤] 不支援的 LLM 供應商: '{provider}'。請選擇 'gemini' 或 'openai'。")


# =====================================================================
# 4. 測試區塊（從專案根目錄執行：python -m text_generator.llm_router）
# =====================================================================
if __name__ == "__main__":
    async def run_test():
        from core import state_manager

        req = ScriptRequest(
            topic="Poland's Upside-Down House: An Architectural Protest Against Communism",
            details="Built in Szymbark, this disorienting house subverts gravity with ceilings as floors and dangling furniture. It was created not as a gimmick, but as a bold artistic statement mocking the backwardness and propaganda of the Soviet era, leaving visitors and builders alike physically dizzy.",
            profile_name="comedy",
            provider="gemini"
        )

        # 有快取就直接載入，跳過 API 呼叫
        run_id = state_manager.get_latest_run_id()
        if run_id and state_manager.get_stage_status(run_id, "text") == "completed":
            result = state_manager.load_script(run_id, VideoScript)
            print(f"\n⚡ [快取] 直接使用上輪劇本: {result.title}")
        else:
            try:
                result = await generate_script_router(req)
                run_id = state_manager.create_run(req.topic, req.profile_name)
                state_manager.save_script(run_id, result)
                state_manager.mark_stage(run_id, "text", "completed")
                print(f"\n🎉 [結果] 成功拿到劇本物件: {result.title}")
            except (FileNotFoundError, KeyError) as e:
                print(f"\n⚠️ 錯誤: {e}")
                return

        print(f"\nDescription: {result.description}\n")
        print(f"tags: {result.tags}\n")
        print(f"scenes: {result.scenes}\n")

    asyncio.run(run_test())
