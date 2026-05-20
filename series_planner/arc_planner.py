"""
Series Arc Planner — Stage 0 for Series Mode.

Makes one LLM call to design the full narrative arc across N episodes,
generating EpisodeOutline objects that drive per-episode script generation.
"""
import yaml
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from text_generator.gemini_api import generate_with_gemini

CONFIG_DIR = Path(__file__).parent.parent / "configs"


# =====================================================================
# Schemas
# =====================================================================

class EpisodeOutline(BaseModel):
    episode_number: int = Field(description="Episode number, starting from 1.")
    episode_title: str = Field(description="YouTube-ready title: 'Series Name #N: Specific Subtopic'")
    focus: str = Field(description="The core question this episode answers.")
    key_reveal: str = Field(description="The 'aha moment' — the key insight viewers walk away with.")
    hook_angle: str = Field(
        description="A unique, specific hook angle for this episode. Must differ in both content and rhetorical style from all other episodes."
    )
    connects_to_next: Optional[str] = Field(
        default=None,
        description="A teaser hint bridging to the next episode. Null for the final episode."
    )


class SeriesArc(BaseModel):
    series_title: str = Field(description="The overall series title.")
    total_episodes: int = Field(description="Total number of episodes in the series.")
    overall_theme: str = Field(description="The big-picture narrative arc of the entire series.")
    episodes: List[EpisodeOutline] = Field(description="Ordered list of episode outlines, one per episode.")
    series_payoff: str = Field(description="What the whole series builds toward — the ultimate takeaway for viewers who watch all episodes.")


# =====================================================================
# Helpers
# =====================================================================

def _load_yaml(file_path: Path) -> dict:
    if not file_path.exists():
        raise FileNotFoundError(f"[ArcPlanner] 找不到設定檔: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_arc_system_prompt(profile_name: str, n_episodes: int) -> str:
    template_path = CONFIG_DIR / "series_arc_prompt.txt"
    if not template_path.exists():
        raise FileNotFoundError(f"[ArcPlanner] 找不到 series_arc_prompt.txt: {template_path}")
    template = template_path.read_text(encoding="utf-8")

    profile_config = _load_yaml(CONFIG_DIR / "profiles" / f"{profile_name}.yaml")
    return template.format(
        n_episodes=n_episodes,
        profile_name=profile_config.get("display_name", profile_name),
        profile_tone=profile_config.get("script", {}).get("tone", "engaging, informative"),
    )


def _build_arc_user_prompt(topic: str, arc_details: str, n_episodes: int) -> str:
    prompt = f"Series Topic: {topic}\n"
    prompt += f"Number of Episodes: {n_episodes}\n"
    if arc_details and arc_details.strip():
        prompt += f"Arc Details: {arc_details}\n"
    return prompt


# =====================================================================
# Main Entry
# =====================================================================

async def plan_series_arc(
    topic: str,
    arc_details: str,
    profile_name: str,
    n_episodes: int,
    provider: str = "gemini",
) -> SeriesArc:
    print(f"\n🗺️  [ArcPlanner] 規劃 {n_episodes} 集系列弧度 | 主題: {topic[:50]}")

    base_config = _load_yaml(CONFIG_DIR / "base_config.yaml")
    model_name = base_config.get("llm_settings", {}).get("model_name", "gemini-2.5-flash")

    system_msg = _build_arc_system_prompt(profile_name, n_episodes)
    user_msg = _build_arc_user_prompt(topic, arc_details, n_episodes)

    if provider.lower() == "gemini":
        arc = await generate_with_gemini(
            system_msg, user_msg,
            response_schema=SeriesArc,
            model_name=model_name,
            temperature=0.8,
        )
    elif provider.lower() == "prompt":
        print(system_msg)
        print(user_msg)
        arc = SeriesArc(
            series_title=f"[MOCK] {topic}",
            total_episodes=n_episodes,
            overall_theme="Mock arc for prompt-mode testing.",
            episodes=[
                EpisodeOutline(
                    episode_number=i,
                    episode_title=f"[MOCK] {topic} #{i}",
                    focus=f"Mock focus for episode {i}",
                    key_reveal=f"Mock key reveal for episode {i}",
                    hook_angle=f"Mock hook angle {i}",
                    connects_to_next=None if i == n_episodes else f"Mock bridge to episode {i + 1}",
                )
                for i in range(1, n_episodes + 1)
            ],
            series_payoff="Mock series payoff.",
        )
    else:
        raise ValueError(f"[ArcPlanner] 不支援的 provider: '{provider}'")

    if len(arc.episodes) != n_episodes:
        raise ValueError(
            f"[ArcPlanner] LLM 回傳了 {len(arc.episodes)} 集，預期 {n_episodes} 集。"
        )

    hook_angles = [ep.hook_angle for ep in arc.episodes]
    if len(set(hook_angles)) < len(hook_angles):
        print("⚠️  [ArcPlanner] 警告：部分集數的 hook_angle 相似，建議確認 arc 品質。")

    print(f"✅ [ArcPlanner] Arc 規劃完成：{arc.series_title}")
    for ep in arc.episodes:
        print(f"   Ep{ep.episode_number}: {ep.episode_title}")

    return arc
