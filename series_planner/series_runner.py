"""
Series and Anthology mode orchestrators.

run_series_mode  — Plans arc, runs N connected episodes, optionally merges to long-form.
run_anthology_mode — Runs N independent episodes with the same profile.
"""
import json
import yaml
from pathlib import Path
from typing import Optional

from core import series_state_manager
from series_planner.arc_planner import (
    plan_series_arc, SeriesArc,
    generate_anthology_plan, generate_metadata_for_topics, AnthologyPlan,
)
from series_planner.episode_runner import run_episode
from series_planner.merger import merge_episodes
from video_renderer.engine import mix_bgm

CONFIG_DIR = Path(__file__).parent.parent / "configs"


async def _generate_bumper_assets(series_id: str, arc: SeriesArc) -> None:
    """Arc 規劃完成後，為長影音 intro/outro 生成圖片和 TTS 音訊。"""
    import asyncio
    from text_generator.llm_router import Scene
    from image_generator.image_router import generate_images_router
    from audio_generator.audio_router import generate_audio_router

    ws = series_state_manager.WORKSPACE_DIR
    bumpers = []
    if arc.intro_scenes:
        bumpers.append(("intro", arc.intro_scenes))
    if arc.outro_scenes:
        bumpers.append(("outro", arc.outro_scenes))

    for folder_name, bumper_list in bumpers:
        bumper_dir = ws / series_id / folder_name
        bumper_dir.mkdir(parents=True, exist_ok=True)
        scenes = [
            Scene(scene_id=i, narration=bs.narration, image_prompt=bs.image_prompt)
            for i, bs in enumerate(bumper_list)
        ]
        img_results, audio_results = await asyncio.gather(
            generate_images_router(scenes, output_dir=bumper_dir),
            generate_audio_router(scenes, output_dir=bumper_dir),
        )
        (bumper_dir / "audio_results.json").write_text(
            json.dumps([r.model_dump() for r in audio_results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  ✅ [{folder_name}] 素材完成（{len(scenes)} 個場景）")


async def run_series_mode(
    job: dict,
    resume_series_id: Optional[str] = None,
    arc_only: bool = False,
    episodes_filter: Optional[list] = None,
    provider_override: Optional[str] = None,
    text_only: bool = False,
    fresh: bool = False,
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
    long_form_intro_outro = job.get("long_form_intro_outro", False)

    base_cfg = yaml.safe_load((CONFIG_DIR / "base_config.yaml").read_text(encoding="utf-8"))
    bgm_cfg = base_cfg.get("bgm_settings", {})
    bgm_enabled = bgm_cfg.get("enabled", False) and Path(bgm_cfg.get("path", "")).exists()

    # ── Arc Planning ─────────────────────────────────────────────────
    if not fresh and not resume_series_id:
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

        if arc.thumbnail_prompt and not text_only:
            print("\n🖼️  [Series] 生成長影音縮圖...")
            from image_generator.image_router import generate_images_router
            from text_generator.llm_router import Scene
            thumb_dir = series_state_manager.WORKSPACE_DIR / series_id / "long_form"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            await generate_images_router(
                [Scene(scene_id=1, narration="", image_prompt=arc.thumbnail_prompt)],
                output_dir=thumb_dir,
            )
            generated = thumb_dir / "scene_001.png"
            if generated.exists():
                generated.rename(thumb_dir / "thumbnail.png")
                print(f"  ✅ 縮圖已存：long_form/thumbnail.png")

    if long_form_intro_outro and not resume_series_id:
        print("\n🎬 [Series] 生成長影音 Intro/Outro 素材...")
        await _generate_bumper_assets(series_id, arc)

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

            lf_dir = series_state_manager.WORKSPACE_DIR / series_id / "long_form"
            lf_dir.mkdir(parents=True, exist_ok=True)
            (lf_dir / "description.txt").write_text(arc.long_form_description or "", encoding="utf-8")
            (lf_dir / "hashtags.txt").write_text("\n".join(arc.long_form_hashtags or []), encoding="utf-8")

            from video_renderer.subtitle_writer import generate_longform_subtitles
            generate_longform_subtitles(
                series_id=series_id,
                ep_run_ids=ep_run_ids,
                add_title_cards=add_title_cards,
                output_dir=lf_dir,
                workspace=series_state_manager.WORKSPACE_DIR,
            )
            print("  ✅ 字幕已生成：long_form/subtitles.srt / .vtt")
    elif combine_long_form and episodes_filter is not None:
        print("\n⚠️  [Series] 使用了 --episodes 篩選，跳過長影片合併（需全集完成才能合併）。")

    # ── BGM 批次混音 ──────────────────────────────────────────────────
    if not text_only and bgm_enabled:
        print("\n🎵 [BGM] 批次混入短影音配樂...")
        ws = series_state_manager.WORKSPACE_DIR
        for i in range(n_episodes):
            ep_run_id  = series_state_manager.get_episode_run_id(series_id, i + 1)
            video_path = ws / ep_run_id / "video" / "output.mp4"
            out_bgm    = video_path.with_stem("output_bgm")
            if out_bgm.exists():
                print(f"  ⚡ ep{i+1:02d} BGM 已存在，跳過")
            elif video_path.exists():
                mix_bgm(video_path, bgm_cfg)
                print(f"  ✅ ep{i+1:02d} BGM 完成")

        if combine_long_form and episodes_filter is None:
            lf_video = ws / series_id / "long_form" / "output.mp4"
            lf_bgm   = lf_video.with_stem("output_bgm")
            if lf_bgm.exists():
                print("  ⚡ 長影片 BGM 已存在，跳過")
            elif lf_video.exists():
                out = mix_bgm(lf_video, bgm_cfg)
                print(f"  ✅ 長影片 BGM 完成：{out}")

    # ── Done ──────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("🎉  Series Pipeline 完成！")
    print(f"    series_id : {series_id}")
    print(f"    集數影片  : workspace/{series_id}/ep*/video/output.mp4")
    if combine_long_form and episodes_filter is None:
        print(f"    長影片    : workspace/{series_id}/long_form/output.mp4")
    print("=" * 50)


def run_bgm_only(series_id: str) -> None:
    """掃描 series workspace，對缺少 output_bgm.mp4 的影片套用 BGM。"""
    base_cfg = yaml.safe_load((CONFIG_DIR / "base_config.yaml").read_text(encoding="utf-8"))
    bgm_cfg  = base_cfg.get("bgm_settings", {})

    if not bgm_cfg.get("enabled", False):
        print("⚠️  [BGM] base_config.yaml 的 bgm_settings.enabled 為 false，跳過。")
        return
    if not Path(bgm_cfg.get("path", "")).exists():
        print(f"❌ [BGM] 找不到 BGM 檔案：{bgm_cfg.get('path')}")
        return

    manifest = series_state_manager.load_manifest(series_id)
    if not manifest:
        print(f"❌ [BGM] 找不到 series：{series_id}")
        return

    n_episodes = manifest.get("n_episodes", 0)
    ws = series_state_manager.WORKSPACE_DIR

    print(f"\n🎵 [BGM-Only] series: {series_id}（{n_episodes} 集）")

    for i in range(1, n_episodes + 1):
        ep_run_id  = series_state_manager.get_episode_run_id(series_id, i)
        video_path = ws / ep_run_id / "video" / "output.mp4"
        out_bgm    = video_path.with_stem("output_bgm")
        if out_bgm.exists():
            print(f"  ⚡ ep{i:02d} BGM 已存在，跳過")
        elif video_path.exists():
            mix_bgm(video_path, bgm_cfg)
            print(f"  ✅ ep{i:02d} BGM 完成")
        else:
            print(f"  ⚠️  ep{i:02d} 尚無影片，跳過")

    lf_video = ws / series_id / "long_form" / "output.mp4"
    lf_bgm   = lf_video.with_stem("output_bgm")
    if lf_bgm.exists():
        print("  ⚡ 長影片 BGM 已存在，跳過")
    elif lf_video.exists():
        out = mix_bgm(lf_video, bgm_cfg)
        print(f"  ✅ 長影片 BGM 完成：{out}")
    else:
        print("  ⚠️  長影片尚未生成，跳過")

    print("\n✅ BGM-Only 完成")


async def run_anthology_mode(
    job: dict,
    text_only: bool = False,
    provider_override: Optional[str] = None,
    resume_anthology_id: Optional[str] = None,
) -> None:
    """
    Anthology pipeline: N independent episodes with the same profile.

    Stage 0: generate_anthology_plan() produces per-episode hook_angle/key_reveal/loop_anchor.
    Stage 1-3: per-episode pipeline (shared with series mode via run_episode).
    Stage 4: optional long-form merge.
    """
    profile  = job.get("profile", "general")
    provider = provider_override or job.get("provider", "gemini")
    combine_long_form = job.get("combine_long_form", True)
    add_title_cards   = job.get("add_title_cards", True)

    base_cfg = yaml.safe_load((CONFIG_DIR / "base_config.yaml").read_text(encoding="utf-8"))
    bgm_cfg  = base_cfg.get("bgm_settings", {})
    bgm_enabled = bgm_cfg.get("enabled", False) and Path(bgm_cfg.get("path", "")).exists()

    # ── Stage 0: Plan ─────────────────────────────────────────────
    title       = (job.get("title") or job.get("topic", "")).strip()
    arc_details = job.get("arc_details", "")
    topics_list: list[str] = job.get("topics", [])
    n_episodes  = int(job.get("n_episodes", len(topics_list) if topics_list else 8))

    if resume_anthology_id:
        plan = series_state_manager.load_series_arc(resume_anthology_id, AnthologyPlan)
        if plan is not None:
            anthology_id = resume_anthology_id
            print(f"\n📂 [Anthology] 繼續 anthology: {anthology_id}")
        else:
            print(f"⚠️  [Anthology] 找不到 {resume_anthology_id}/series_arc.json，重新規劃")
            resume_anthology_id = None

    if not resume_anthology_id:
        if topics_list:
            # Path B: specific topics from topic bank — LLM only adds metadata
            if not title:
                title = "Incredible Facts You Need to Know"
            plan = await generate_metadata_for_topics(
                topics=topics_list,
                title=title,
                profile_name=profile,
                provider=provider,
                topic_contexts=job.get("topic_contexts"),
            )
        else:
            # Path A: LLM generates its own topic angles from a title
            if not title:
                print("❌ [Anthology] job YAML must have either 'title' or 'topics'")
                return
            plan = await generate_anthology_plan(title, arc_details, profile, n_episodes, provider)

        anthology_id = series_state_manager.create_anthology(plan.title, profile, plan.total_episodes)
        series_state_manager.save_series_arc(anthology_id, plan)

        if plan.thumbnail_prompt and not text_only:
            print("\n🖼️  [Anthology] 生成長影音縮圖...")
            from image_generator.image_router import generate_images_router
            from text_generator.llm_router import Scene
            thumb_dir = series_state_manager.WORKSPACE_DIR / anthology_id / "long_form"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            await generate_images_router(
                [Scene(scene_id=1, narration="", image_prompt=plan.thumbnail_prompt)],
                output_dir=thumb_dir,
            )
            generated = thumb_dir / "scene_001.png"
            if generated.exists():
                generated.rename(thumb_dir / "thumbnail.png")
                print(f"  ✅ 縮圖已存：long_form/thumbnail.png")

    print(f"\n📚 [Anthology] 批次生成 {plan.total_episodes} 部獨立影片 | 風格: {profile}")

    # ── Episode Pipeline ──────────────────────────────────────────
    for ep_outline in plan.episodes:
        ep_num    = ep_outline.episode_number
        ep_run_id = series_state_manager.get_episode_run_id(anthology_id, ep_num)

        if series_state_manager.get_episode_status(anthology_id, ep_num) == "completed":
            print(f"\n⚡ [Anthology] Episode {ep_num} 已完成，跳過")
            continue

        print(f"\n{'=' * 50}")
        print(f"📹 [{ep_num} / {plan.total_episodes}] {ep_outline.episode_title}")
        print("=" * 50)

        series_state_manager.mark_episode_status(anthology_id, ep_num, "in_progress")
        await run_episode(
            run_id=ep_run_id,
            topic=ep_outline.focus,
            profile=profile,
            provider=provider,
            episode_outline=ep_outline,
            anthology_plan=plan,
            text_only=text_only,
        )
        if not text_only:
            series_state_manager.mark_episode_status(anthology_id, ep_num, "completed")

    # ── Long-Form Merge ───────────────────────────────────────────
    if text_only:
        print("\n⚠️  [Anthology] text-only 模式，跳過長影片合併。")
    elif combine_long_form:
        all_done = all(
            series_state_manager.get_episode_status(anthology_id, i + 1) == "completed"
            for i in range(plan.total_episodes)
        )
        if not all_done:
            print("\n⚠️  [Anthology] 部分集數未完成，跳過長影片合併。")
        else:
            ep_run_ids = [
                series_state_manager.get_episode_run_id(anthology_id, i + 1)
                for i in range(plan.total_episodes)
            ]
            merge_episodes(anthology_id, ep_run_ids, add_title_cards)

            lf_dir = series_state_manager.WORKSPACE_DIR / anthology_id / "long_form"
            lf_dir.mkdir(parents=True, exist_ok=True)
            (lf_dir / "description.txt").write_text(plan.long_form_description or "", encoding="utf-8")
            (lf_dir / "hashtags.txt").write_text("\n".join(plan.long_form_hashtags or []), encoding="utf-8")

            from video_renderer.subtitle_writer import generate_longform_subtitles
            generate_longform_subtitles(
                series_id=anthology_id,
                ep_run_ids=ep_run_ids,
                add_title_cards=add_title_cards,
                output_dir=lf_dir,
                workspace=series_state_manager.WORKSPACE_DIR,
            )
            print("  ✅ 字幕已生成：long_form/subtitles.srt / .vtt")

    # ── BGM ───────────────────────────────────────────────────────
    if not text_only and bgm_enabled:
        print("\n🎵 [BGM] 批次混入短影音配樂...")
        ws = series_state_manager.WORKSPACE_DIR
        for i in range(plan.total_episodes):
            ep_run_id  = series_state_manager.get_episode_run_id(anthology_id, i + 1)
            video_path = ws / ep_run_id / "video" / "output.mp4"
            out_bgm    = video_path.with_stem("output_bgm")
            if out_bgm.exists():
                print(f"  ⚡ ep{i+1:02d} BGM 已存在，跳過")
            elif video_path.exists():
                mix_bgm(video_path, bgm_cfg)
                print(f"  ✅ ep{i+1:02d} BGM 完成")

    print("\n" + "=" * 50)
    print(f"🎉  Anthology 完成！{plan.total_episodes} 部影片已生成")
    print(f"    anthology_id : {anthology_id}")
    print(f"    集數影片     : workspace/{anthology_id}/ep*/video/output.mp4")
    if combine_long_form and not text_only:
        print(f"    長影片       : workspace/{anthology_id}/long_form/output.mp4")
    print("=" * 50)
