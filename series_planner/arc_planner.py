"""
Series Arc Planner — Stage 0 for Series Mode.

Makes one LLM call to design the full narrative arc across N episodes,
generating EpisodeOutline objects that drive per-episode script generation.
"""
import yaml
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from text_generator.llm_router import call_llm, get_llm_settings

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
    loop_anchor: Optional[str] = Field(
        default=None,
        description="A 4-8 word phrase distilled from hook_angle. The episode's loop_scene must echo this phrase to create a seamless short-form loop. E.g. hook_angle 'This city hides a secret no map shows' → loop_anchor 'this city's hidden secret'."
    )
    connects_to_next: Optional[str] = Field(
        default=None,
        description="A teaser hint bridging to the next episode. Null for the final episode."
    )


class BumperScene(BaseModel):
    narration: str = Field(description="Spoken narration text for this intro/outro scene.")
    image_prompt: str = Field(description="Image generation prompt for this intro/outro scene.")


class SeriesArc(BaseModel):
    series_title: str = Field(description="The overall series title.")
    total_episodes: int = Field(description="Total number of episodes in the series.")
    overall_theme: str = Field(description="The big-picture narrative arc of the entire series.")
    series_lens: Optional[str] = Field(
        default=None,
        description="One sentence capturing the central insight that ALL episodes illustrate with different evidence. Defines the unifying perspective of the series."
    )
    episodes: List[EpisodeOutline] = Field(description="Ordered list of episode outlines, one per episode.")
    series_payoff: str = Field(description="What the whole series builds toward — the ultimate takeaway for viewers who watch all episodes.")
    intro_scenes: Optional[List[BumperScene]] = Field(
        default=None,
        description="1-2 scenes for the long-form series intro. Warm welcome, topic overview, preview of what viewers will learn across all episodes.",
    )
    outro_scenes: Optional[List[BumperScene]] = Field(
        default=None,
        description="1-2 scenes for the long-form series outro. Thank viewers, recap the journey, end with a subscribe/comment CTA.",
    )


class AnthologyPlan(BaseModel):
    title: str = Field(description="The anthology title or theme.")
    total_episodes: int = Field(description="Total number of episodes.")
    episodes: List[EpisodeOutline] = Field(
        description="Ordered list of episode outlines. connects_to_next must be null for all episodes."
    )


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


def _build_anthology_system_prompt(profile_name: str, n_topics: int) -> str:
    template_path = CONFIG_DIR / "anthology_topics_prompt.txt"
    if not template_path.exists():
        raise FileNotFoundError(f"[ArcPlanner] 找不到 anthology_topics_prompt.txt: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    profile_config = _load_yaml(CONFIG_DIR / "profiles" / f"{profile_name}.yaml")
    return template.format(
        n_topics=n_topics,
        profile_name=profile_config.get("display_name", profile_name),
        profile_tone=profile_config.get("script", {}).get("tone", "engaging, informative"),
    )


def _build_anthology_user_prompt(title: str, arc_details: str, n_topics: int) -> str:
    prompt = f"Series Title / Theme: {title}\n"
    prompt += f"Number of Topics: {n_topics}\n"
    if arc_details and arc_details.strip():
        prompt += f"Context / Focus Notes: {arc_details}\n"
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

    system_msg = _build_arc_system_prompt(profile_name, n_episodes)
    user_msg = _build_arc_user_prompt(topic, arc_details, n_episodes)

    llm_cfg = get_llm_settings(provider)
    model_name  = llm_cfg.get("model_name", "gemini-2.5-flash")
    temperature = llm_cfg.get("temperature", 0.8)

    arc = await call_llm(
        system_msg, user_msg,
        response_schema=SeriesArc,
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        mock_factory=lambda: SeriesArc(
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
                    loop_anchor=f"mock loop anchor episode {i}",
                    connects_to_next=None if i == n_episodes else f"Mock bridge to episode {i + 1}",
                )
                for i in range(1, n_episodes + 1)
            ],
            series_payoff="Mock series payoff.",
        ),
    )

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


async def generate_metadata_for_topics(
    topics: list[str],
    title: str,
    profile_name: str,
    provider: str = "gemini",
) -> AnthologyPlan:
    """
    Given a list of specific factual topic strings (from the topic bank),
    call the LLM to enrich each with hook_angle, key_reveal, and loop_anchor.
    The LLM does NOT invent new topics — it only wraps the provided facts.
    """
    n_topics = len(topics)
    print(f"\n🎯 [ArcPlanner] 豐富化 {n_topics} 個指定主題 | {title[:50]}")

    template_path = CONFIG_DIR / "episode_enrich_prompt.txt"
    if not template_path.exists():
        raise FileNotFoundError(f"[ArcPlanner] 找不到 episode_enrich_prompt.txt: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    profile_config = _load_yaml(CONFIG_DIR / "profiles" / f"{profile_name}.yaml")
    system_msg = template.format(
        n_topics=n_topics,
        profile_name=profile_config.get("display_name", profile_name),
        profile_tone=profile_config.get("script", {}).get("tone", "engaging, informative"),
    )

    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(topics))
    user_msg = (
        f"Anthology Title: {title}\n"
        f"Number of Episodes: {n_topics}\n\n"
        f"Topic List (preserve these facts exactly):\n{numbered}\n"
    )

    llm_cfg = get_llm_settings(provider)
    model_name  = llm_cfg.get("model_name", "gemini-2.5-flash")
    temperature = llm_cfg.get("temperature", 0.7)

    result = await call_llm(
        system_msg, user_msg,
        response_schema=AnthologyPlan,
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        mock_factory=lambda: AnthologyPlan(
            title=title,
            total_episodes=n_topics,
            episodes=[
                EpisodeOutline(
                    episode_number=i + 1,
                    episode_title=f"[MOCK] {topics[i][:60]}",
                    focus=topics[i],
                    key_reveal=f"[MOCK] Key reveal for: {topics[i][:50]}",
                    hook_angle=f"[MOCK] Hook angle {i + 1}",
                    loop_anchor=f"mock anchor {i + 1}",
                    connects_to_next=None,
                )
                for i in range(n_topics)
            ],
        ),
    )

    if len(result.episodes) != n_topics:
        raise ValueError(
            f"[ArcPlanner] LLM 回傳了 {len(result.episodes)} 集，預期 {n_topics} 集。"
        )

    print(f"✅ [ArcPlanner] 主題豐富化完成：")
    for ep in result.episodes:
        print(f"   Ep{ep.episode_number}: {ep.episode_title}")

    return result


async def generate_anthology_plan(
    title: str,
    arc_details: str,
    profile_name: str,
    n_topics: int,
    provider: str = "gemini",
) -> AnthologyPlan:
    print(f"\n📋 [ArcPlanner] 規劃 {n_topics} 集獨立主題 | 標題: {title[:50]}")

    system_msg = _build_anthology_system_prompt(profile_name, n_topics)
    user_msg = _build_anthology_user_prompt(title, arc_details, n_topics)

    llm_cfg = get_llm_settings(provider)
    model_name  = llm_cfg.get("model_name", "gemini-2.5-flash")
    temperature = llm_cfg.get("temperature", 0.8)

    result = await call_llm(
        system_msg, user_msg,
        response_schema=AnthologyPlan,
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        mock_factory=lambda: AnthologyPlan(
            title=title,
            total_episodes=n_topics,
            episodes=[
                EpisodeOutline(
                    episode_number=i,
                    episode_title=f"[MOCK] {title} #{i}",
                    focus=f"Mock focus {i}",
                    key_reveal=f"Mock key reveal {i}",
                    hook_angle=f"Mock hook angle {i}",
                    loop_anchor=f"mock loop anchor {i}",
                    connects_to_next=None,
                )
                for i in range(1, n_topics + 1)
            ],
        ),
    )

    if len(result.episodes) != n_topics:
        raise ValueError(
            f"[ArcPlanner] LLM 回傳了 {len(result.episodes)} 集，預期 {n_topics} 集。"
        )

    print(f"✅ [ArcPlanner] Anthology 規劃完成：")
    for ep in result.episodes:
        print(f"   Ep{ep.episode_number}: {ep.episode_title}")

    return result
