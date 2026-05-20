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
    episode_context: Optional[dict] = Field(
        default=None,
        description="Series mode only: episode outline + arc metadata for system prompt injection."
    )
    cta_enabled: bool = Field(
        default=True,
        description="若為 False，結尾不加 CTA，以自然收尾取代。"
    )

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

def _build_system_prompt(profile_name: str, episode_context: Optional[dict] = None, cta_enabled: bool = True) -> str:
    base_config = _load_yaml(CONFIG_DIR / "base_config.yaml")
    profile_config = _load_yaml(CONFIG_DIR / "profiles" / f"{profile_name}.yaml")
    template = _read_text_file(CONFIG_DIR / "system_prompt.txt")

    global_forbidden = base_config.get("global_forbidden_phrases", [])
    specific_forbidden = profile_config.get("script", {}).get("specific_forbidden_phrases", [])
    merged_forbidden = global_forbidden + specific_forbidden

    hooks = profile_config.get("script", {}).get("hooks", [])
    ctas = profile_config.get("script", {}).get("cta_variants", [])

    aspect = base_config.get("image_settings", {}).get("aspect_ratio", "9:16")
    if aspect == "16:9":
        composition_style = (
            "PANORAMIC COMPOSITION: Images are displayed with horizontal panning (Ken Burns effect). "
            "Compose every scene as a WIDE PANORAMIC environment. Place the key subject at the left "
            "or right third of the frame — never dead center. Every horizontal slice of the image "
            "must be visually interesting on its own."
        )
    else:
        composition_style = (
            "PORTRAIT COMPOSITION: Images are displayed with a center zoom effect. "
            "Place the KEY SUBJECT centered in the frame, filling roughly 60-80% of the vertical space. "
            "Avoid placing important elements near the edges of the frame."
        )

    series_context = _build_series_context(episode_context) if episode_context else ""

    if cta_enabled:
        cta_rule = f"End with a strong hook for engagement, such as: {' or '.join(ctas) if ctas else 'a compelling question or takeaway'}."
    else:
        cta_rule = "End naturally with the episode's key takeaway. No follow requests, subscribe prompts, or references to future episodes."

    try:
        return template.format(
            profile_name=profile_config.get("display_name", profile_name),
            profile_tone=profile_config.get("script", {}).get("tone", ""),
            base_word_count=base_config.get("video_settings", {}).get("target_word_count", "135 to 145"),
            base_max_scenes=base_config.get("video_settings", {}).get("max_scenes", 5),
            script_structure=base_config.get("video_settings", {}).get("script_structure", "Context, Escalation, Climax"),
            global_forbidden=", ".join(f"'{p}'" for p in merged_forbidden),
            profile_hooks=" | ".join(hooks) if hooks else "None",
            profile_prompt_suffix=profile_config.get("visuals", {}).get("prompt_suffix", ""),
            image_composition_style=composition_style,
            series_context=series_context,
            cta_rule=cta_rule,
        )
    except KeyError as e:
        raise KeyError(f"[Router 錯誤] system_prompt.txt 裡有未對應的變數佔位符: {e}")

def _build_series_context(ctx: dict) -> str:
    ep_num = ctx["episode_number"]
    total = ctx["total_episodes"]
    prev = ctx.get("previously_covered", [])
    prev_str = (
        ", ".join(f'"{f}"' for f in prev)
        if prev else "nothing yet — this is the first episode"
    )
    connects = ctx.get("connects_to_next")
    cta_hint = (
        f"Tease the next episode with this bridge: {connects}"
        if connects
        else f"Final episode — end with the series payoff: {ctx.get('series_payoff', '')}"
    )
    return (
        "\n=========================================\n"
        "📺 SERIES CONTEXT\n"
        "=========================================\n"
        f"This is Episode {ep_num} of {total} in the series: \"{ctx['series_title']}\"\n"
        f"This episode's focus: {ctx['focus']}\n"
        f"Key reveal for this episode: {ctx['key_reveal']}\n"
        f"Hook angle — you MUST open with this specific angle: {ctx['hook_angle']}\n"
        f"CTA guidance: {cta_hint}\n"
        f"Previously covered in this series: {prev_str}\n"
        "\nSERIES SCRIPTWRITING RULES:\n"
        "- The opening hook MUST use the hook angle specified above.\n"
        "- Do NOT recap previous episodes — one brief sentence of context max.\n"
        "- This episode must stand alone for a first-time viewer.\n"
        "- The CTA must reference the series (next episode or the whole series).\n"
    )


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
    system_msg = _build_system_prompt(request.profile_name, request.episode_context, request.cta_enabled)
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
        return VideoScript(
            title="Prompt Test", description="Test", tags=[],
            scenes=[Scene(scene_id=i, narration="mock", image_prompt="mock") for i in range(1, 5)],
        )

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
