"""
Series and Anthology mode orchestrators.

run_series_mode  — Plans arc, runs N connected episodes, optionally merges to long-form.
run_anthology_mode — Runs N independent episodes with the same profile.
"""
import json
from typing import Optional

from core import series_state_manager
from series_planner.arc_planner import plan_series_arc, SeriesArc
from series_planner.episode_runner import run_episode
from series_planner.merger import merge_episodes


async def run_series_mode(
    job: dict,
    resume_series_id: Optional[str] = None,
    arc_only: bool = False,
    episodes_filter: Optional[list] = None,
    provider_override: Optional[str] = None,
    text_only: bool = False,
) -> None:
    """
    Full series pipeline:
      Stage 0: Arc planning (one LLM call → N EpisodeOutlines)
      Stage 1-3: Per-episode pipeline (text → images+audio → video)
      Stage 4: Long-form merge (optional)

    episodes_filter: if set, only run episodes with those numbers (e.g. [1, 2]).
    """
    topic = job.get("title") or job.get("topic", "")
    profile = job.get("profile", "general")
    provider = provider_override or job.get("provider", "gemini")
    n_episodes = int(job.get("n_episodes", 8))
    arc_details = job.get("arc_details", "")
    combine_long_form = job.get("combine_long_form", True)
    add_title_cards = job.get("add_title_cards", True)
    cta_enabled = job.get("cta_enabled", True)

    # ── Arc Planning ─────────────────────────────────────────────────
    if not resume_series_id:
        resume_series_id = series_state_manager.get_latest_series_id()

    if resume_series_id:
        arc = series_state_manager.load_series_arc(resume_series_id, SeriesArc)
        if arc is not None:
            series_id = resume_series_id
            print(f"\n📂 [Series] 繼續 series: {series_id}")
        else:
            print(f"⚠️  [Series] 找不到 {resume_series_id}/series_arc.json，重新建立新 series")
            resume_series_id = None

    if not resume_series_id:
        series_id = series_state_manager.create_series(topic, profile, n_episodes)
        arc = await plan_series_arc(topic, arc_details, profile, n_episodes, provider)
        series_state_manager.save_series_arc(series_id, arc)

    if arc_only:
        print("\n" + "=" * 50)
        print("🗺️  Series Arc（--arc-only 模式，僅規劃不生成影片）")
        print("=" * 50)
        print(json.dumps(arc.model_dump(), ensure_ascii=False, indent=2))
        print(f"\n📁 Arc 已儲存至：workspace/{series_id}/series_arc.json")
        return

    # ── Episode Pipeline ─────────────────────────────────────────────
    for ep_outline in arc.episodes:
        ep_num = ep_outline.episode_number

        if episodes_filter is not None and ep_num not in episodes_filter:
            continue

        ep_run_id = series_state_manager.get_episode_run_id(series_id, ep_num)

        if series_state_manager.get_episode_status(series_id, ep_num) == "completed":
            print(f"\n⚡ [Series] Episode {ep_num} 已完成，跳過")
            continue

        print(f"\n{'=' * 50}")
        print(f"🎬  Episode {ep_num} / {arc.total_episodes}：{ep_outline.episode_title}")
        print("=" * 50)

        series_state_manager.mark_episode_status(series_id, ep_num, "in_progress")
        await run_episode(
            run_id=ep_run_id,
            topic=ep_outline.focus,
            profile=profile,
            provider=provider,
            episode_outline=ep_outline,
            series_arc=arc,
            cta_enabled=cta_enabled,
            text_only=text_only,
        )
        if not text_only:
            series_state_manager.mark_episode_status(series_id, ep_num, "completed")

    # ── Long-Form Merge ───────────────────────────────────────────────
    if text_only:
        print("\n⚠️  [Series] text-only 模式，跳過長影片合併。")
    elif combine_long_form and episodes_filter is None:
        all_done = all(
            series_state_manager.get_episode_status(series_id, i + 1) == "completed"
            for i in range(n_episodes)
        )
        if not all_done:
            print("\n⚠️  [Series] 部分集數未完成，跳過長影片合併。")
        else:
            ep_run_ids = [
                series_state_manager.get_episode_run_id(series_id, i + 1)
                for i in range(n_episodes)
            ]
            merge_episodes(series_id, ep_run_ids, add_title_cards)
    elif combine_long_form and episodes_filter is not None:
        print("\n⚠️  [Series] 使用了 --episodes 篩選，跳過長影片合併（需全集完成才能合併）。")

    # ── Done ──────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("🎉  Series Pipeline 完成！")
    print(f"    series_id : {series_id}")
    print(f"    集數影片  : workspace/{series_id}/ep*/video/output.mp4")
    if combine_long_form and episodes_filter is None:
        print(f"    長影片    : workspace/{series_id}/long_form/output.mp4")
    print("=" * 50)


async def run_anthology_mode(job: dict, text_only: bool = False) -> None:
    """
    Anthology pipeline: N independent episodes with the same profile.
    No arc planning. Each topic runs through the standard pipeline.
    """
    topics: list = job.get("topics", [])
    profile = job.get("profile", "general")
    provider = job.get("provider", "gemini")
    cta_enabled = job.get("cta_enabled", True)

    if not topics:
        print("❌ [Anthology] job YAML 缺少 'topics' 清單")
        return

    print(f"\n📚 [Anthology] 批次生成 {len(topics)} 部獨立影片 | 風格: {profile}")

    for i, topic in enumerate(topics, 1):
        print(f"\n{'=' * 50}")
        print(f"📹 [{i} / {len(topics)}] {topic}")
        print("=" * 50)
        await run_episode(
            run_id=None,
            topic=topic,
            profile=profile,
            provider=provider,
            cta_enabled=cta_enabled,
            text_only=text_only,
        )

    print("\n" + "=" * 50)
    print(f"🎉  Anthology 完成！{len(topics)} 部影片已生成")
    print("=" * 50)
