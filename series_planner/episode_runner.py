"""
Single-episode pipeline runner.

Extracted from main.py so both solo mode (main.py) and series mode
(series_runner.py) can call the same 3-stage pipeline logic.
"""
import asyncio
import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from core import state_manager
from text_generator.llm_router import ScriptRequest, VideoScript, generate_script_router
from image_generator.image_router import generate_images_router
from audio_generator.audio_router import generate_audio_router
from video_renderer.engine import render_video

if TYPE_CHECKING:
    from series_planner.arc_planner import EpisodeOutline, SeriesArc


# =====================================================================
# Stage helpers
# =====================================================================

async def _run_image_stage(run_id: str, script: VideoScript) -> None:
    image_dir = state_manager.get_image_dir(run_id)
    state_manager.mark_stage(run_id, "images", "in_progress")
    all_scenes = list(script.scenes)
    if script.loop_scene:
        script.loop_scene.scene_id = 0
        all_scenes = [script.loop_scene] + all_scenes
    results = await generate_images_router(all_scenes, output_dir=image_dir)
    (image_dir / "image_results.json").write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state_manager.mark_stage(run_id, "images", "completed")
    print(f"  ✅ [Images] {len(results)} 張圖片完成")


async def _run_audio_stage(run_id: str, script: VideoScript) -> None:
    audio_dir = state_manager.get_audio_dir(run_id)
    state_manager.mark_stage(run_id, "audio", "in_progress")
    all_scenes = list(script.scenes)
    if script.loop_scene:
        script.loop_scene.scene_id = 0
        all_scenes = [script.loop_scene] + all_scenes
    results = await generate_audio_router(all_scenes, output_dir=audio_dir)
    (audio_dir / "audio_results.json").write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state_manager.mark_stage(run_id, "audio", "completed")
    print(f"  ✅ [Audio] {len(results)} 個音檔完成")


# =====================================================================
# Main episode runner
# =====================================================================

async def run_episode(
    run_id: Optional[str],
    topic: str,
    profile: str,
    provider: str = "gemini",
    details: str = "",
    episode_outline: "Optional[EpisodeOutline]" = None,
    series_arc: "Optional[SeriesArc]" = None,
    fresh: bool = False,
    text_only: bool = False,
) -> str:
    """
    Runs the full 3-stage pipeline for a single video/episode.

    If run_id is None, a new run directory is created via state_manager.
    For series episodes, run_id is pre-created by series_state_manager
    (format: 'series_YYYYMMDD_HHMMSS/ep01').

    Returns the run_id on completion.
    """
    # Build series context dict for system prompt injection (series mode only)
    episode_context: Optional[dict] = None
    if episode_outline is not None and series_arc is not None:
        previously_covered = [
            e.focus for e in series_arc.episodes
            if e.episode_number < episode_outline.episode_number
        ]
        episode_context = {
            "episode_number":    episode_outline.episode_number,
            "episode_title":     episode_outline.episode_title,
            "focus":             episode_outline.focus,
            "key_reveal":        episode_outline.key_reveal,
            "hook_angle":        episode_outline.hook_angle,
            "loop_anchor":       episode_outline.loop_anchor,
            "connects_to_next":  episode_outline.connects_to_next,
            "series_title":      series_arc.series_title,
            "total_episodes":    series_arc.total_episodes,
            "series_payoff":     series_arc.series_payoff,
            "previously_covered": previously_covered,
        }

    # ── Stage 1: Text ────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("📝  Stage 1 / 3：文字生成")
    print("─" * 50)

    text_cached = (
        run_id is not None
        and not fresh
        and state_manager.get_stage_status(run_id, "text") == "completed"
    )

    if text_cached:
        print("⚡ 從快取載入劇本")
        script = state_manager.load_script(run_id, VideoScript)
    else:
        request = ScriptRequest(
            topic=topic,
            details=details,
            profile_name=profile,
            provider=provider,
            episode_context=episode_context,
        )
        script = await generate_script_router(request)

        if run_id is None:
            run_id = state_manager.create_run(topic, profile)

        state_manager.save_script(run_id, script)
        state_manager.mark_stage(run_id, "text", "completed")

    print(f"✅ 劇本：{script.title}（{len(script.scenes)} 個場景）")

    if provider == "prompt" or text_only:
        tag = "Prompt mode" if provider == "prompt" else "Text-only mode"
        print(f"\n[{tag}] 跳過圖片/音訊/影片生成。")
        if text_only and run_id:
            print(f"    劇本已儲存：workspace/{run_id}/script.json")
            print(f"    繼續生成：python main.py --resume {run_id}")
        return run_id or "prompt-test"

    # ── Stage 2: Images + Audio (parallel) ───────────────────────────
    print("\n" + "─" * 50)
    print("🎨  Stage 2 / 3：圖片 + 音訊（平行生成）")
    print("─" * 50)

    image_done = state_manager.get_stage_status(run_id, "images") == "completed"
    audio_done = state_manager.get_stage_status(run_id, "audio") == "completed"

    if image_done and audio_done:
        print("⚡ 圖片與音訊皆已完成，從快取載入")
    else:
        tasks = []
        if not image_done:
            tasks.append(_run_image_stage(run_id, script))
        else:
            print("⚡ 圖片已完成，跳過")

        if not audio_done:
            tasks.append(_run_audio_stage(run_id, script))
        else:
            print("⚡ 音訊已完成，跳過")

        await asyncio.gather(*tasks)

    # ── Stage 3: Video ────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("🎬  Stage 3 / 3：影片渲染")
    print("─" * 50)

    if state_manager.get_stage_status(run_id, "video") == "completed":
        video_path = state_manager.get_video_dir(run_id) / "output.mp4"
        print(f"⚡ 影片已完成：{video_path}")
    else:
        state_manager.mark_stage(run_id, "video", "in_progress")
        output = render_video(run_id)
        state_manager.mark_stage(run_id, "video", "completed")
        print(f"✅ 影片輸出：{output}")

    return run_id
