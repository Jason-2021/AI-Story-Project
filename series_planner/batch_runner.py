"""
Batch submit orchestrator.

執行 Stage 0（arc planning，series/anthology only）和 Stage 1（text generation），
然後將所有集數的圖片 + TTS 打包成一個 image batch job 和一個 audio batch job 送出。
結果的 job ID 和 scene 對應表存入 batch_jobs.json，之後由 batch_collector 收取。

不動 realtime flow（episode_runner / series_runner）。
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core import state_manager, series_state_manager
from text_generator.llm_router import (
    ScriptRequest, VideoScript, generate_script_router, Scene,
)
from image_generator.image_router import (
    _get_image_settings, _get_gemini_image_settings,
    _get_openai_image_settings, _get_scene_ratios,
)
from audio_generator.audio_router import _get_tts_settings
from image_generator.gemini_image_batch import submit_image_batch as gemini_img_submit
from image_generator.openai_image_batch import submit_image_batch as openai_img_submit
from audio_generator.gemini_tts_batch import submit_tts_batch

WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"
CONFIG_DIR    = Path(__file__).parent.parent / "configs"


# ── Provider validation ────────────────────────────────────────────────────

def _validate_providers(image_provider: str) -> None:
    supported_image = {"gemini", "openai"}
    if image_provider not in supported_image:
        raise ValueError(
            f"❌ [Batch] image provider '{image_provider}' 不支援 batch 模式。"
            f"  支援的 image providers: {supported_image}"
        )
    # Audio 永遠走 Gemini batch（OpenAI 不支援 TTS batch），不需驗證


# ── Scene helpers ──────────────────────────────────────────────────────────

def _get_all_scenes(script: VideoScript) -> list[Scene]:
    """回傳含 loop_scene（scene_id=0）的完整 scene 列表，同 episode_runner 邏輯。"""
    all_scenes = list(script.scenes)
    if script.loop_scene:
        script.loop_scene.scene_id = 0
        all_scenes = [script.loop_scene] + all_scenes
    return all_scenes


def _build_scenes_maps(
    ep_prefix: str,
    run_id: str,
    all_scenes: list[Scene],
    ratios: list[str],
) -> tuple[dict, dict, list, list]:
    """
    回傳 (image_scenes_map, audio_scenes_map, img_meta_list, audio_meta_list)。
    img_meta_list / audio_meta_list 是存入 batch_jobs.json 的 scene 記錄。
    ep_prefix: "" for solo, "ep01_" for series episode 1
    """
    image_map: dict = {}
    audio_map: dict = {}
    img_meta:  list = []
    audio_meta: list = []

    for i, scene in enumerate(all_scenes):
        cid = f"{ep_prefix}scene_{scene.scene_id:02d}"
        image_map[cid] = {"prompt": scene.image_prompt, "aspect_ratio": ratios[i]}
        audio_map[cid] = scene.narration
        img_meta.append({
            "custom_id": cid, "run_id": run_id,
            "scene_id": scene.scene_id, "aspect_ratio": ratios[i],
            "prompt": scene.image_prompt,
        })
        audio_meta.append({
            "key": cid, "run_id": run_id,
            "scene_id": scene.scene_id, "narration": scene.narration,
        })

    return image_map, audio_map, img_meta, audio_meta


# ── Batch submit ───────────────────────────────────────────────────────────

def _submit_image(provider: str, scenes_map: dict) -> str:
    if provider == "gemini":
        settings = _get_gemini_image_settings()
        model_name = settings.get("model_name", "gemini-2.5-flash-image")
        return gemini_img_submit(scenes_map, model_name)
    else:  # openai
        settings = _get_openai_image_settings()
        model_name = settings.get("model_name", "gpt-image-2")
        quality    = settings.get("quality", "low")
        return openai_img_submit(scenes_map, model_name, quality)


def _submit_audio(scenes_map: dict) -> str:
    settings   = _get_tts_settings()
    model_name = settings.get("model_name", "gemini-2.5-flash-preview-tts")
    voice_name = settings.get("voice_name", "charon")
    return submit_tts_batch(scenes_map, model_name, voice_name)


# ── Solo mode ──────────────────────────────────────────────────────────────

async def _run_batch_solo(args, job: Optional[dict]) -> None:
    topic    = args.topic or (job or {}).get("topic") or (job or {}).get("title") or ""
    details  = args.details or (job or {}).get("details", "")
    profile  = args.profile
    provider = args.provider

    image_settings = _get_image_settings()
    image_provider = image_settings.get("provider", "gemini")
    _validate_providers(image_provider)

    # Stage 1: Text generation
    print("\n" + "─" * 50)
    print("📝  [Batch] Stage 1：文字生成")
    print("─" * 50)
    request = ScriptRequest(topic=topic, details=details, profile_name=profile, provider=provider)
    script  = await generate_script_router(request)
    run_id  = state_manager.create_run(topic, profile)
    state_manager.save_script(run_id, script)
    state_manager.mark_stage(run_id, "text", "completed")
    print(f"✅ 劇本：{script.title}（{len(script.scenes)} 個場景）")

    # Build scenes maps
    all_scenes = _get_all_scenes(script)
    mode    = image_settings.get("scene_ratio_mode", "all_16_9")
    ratios  = _get_scene_ratios(mode, len(all_scenes))
    image_map, audio_map, img_meta, audio_meta = _build_scenes_maps("", run_id, all_scenes, ratios)

    # Submit
    print("\n" + "─" * 50)
    print(f"🚀  [Batch] 送出 image batch（{image_provider}）...")
    image_batch_id = _submit_image(image_provider, image_map)
    print(f"   ✅ Image batch: {image_batch_id}")

    print(f"🚀  [Batch] 送出 TTS batch（gemini）...")
    audio_batch_id = _submit_audio(audio_map)
    print(f"   ✅ Audio batch: {audio_batch_id}")

    # Save state
    tts_settings = _get_tts_settings()
    batch_data = {
        "mode": "solo",
        "series_or_run_id": run_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "collected": False,
        "solo_args": {
            "topic": topic,
            "profile": profile,
            "provider": provider,
            "details": details,
        },
        "tts_sample_rate": tts_settings.get("sample_rate", 24000),
        "image": {
            "provider": image_provider,
            "batch_id": image_batch_id,
            "scenes": img_meta,
        },
        "audio": {
            "provider": "gemini",
            "batch_id": audio_batch_id,
            "scenes": audio_meta,
        },
    }
    state_manager.save_batch_jobs(run_id, batch_data)
    state_manager.mark_stage(run_id, "images", "batch_submitted")
    state_manager.mark_stage(run_id, "audio",  "batch_submitted")

    print("\n" + "=" * 50)
    print("📬  Batch 已送出！")
    print(f"    run_id     : {run_id}")
    print(f"    Image job  : {image_batch_id}")
    print(f"    Audio job  : {audio_batch_id}")
    print(f"\n    電腦重開後執行：")
    print(f"    python main.py --batch-check {run_id}")
    print("=" * 50)


# ── Series / Anthology mode ────────────────────────────────────────────────

async def _run_batch_multi(args, job: dict, mode: str) -> None:
    """Shared logic for series and anthology batch submit."""
    from series_planner.arc_planner import (
        plan_series_arc, SeriesArc,
        generate_anthology_plan, generate_metadata_for_topics, AnthologyPlan,
    )

    profile     = job.get("profile", "general")
    provider    = args.provider if args.provider != "gemini" else job.get("provider", "gemini")
    n_episodes  = int(job.get("n_episodes", 8))
    topic       = (job.get("title") or job.get("topic", "")).strip()
    arc_details = job.get("arc_details", "")

    image_settings = _get_image_settings()
    image_provider = image_settings.get("provider", "gemini")
    _validate_providers(image_provider)

    tts_settings = _get_tts_settings()

    # Stage 0: Arc / Anthology planning
    print("\n" + "─" * 50)
    print(f"🗺️   [Batch] Stage 0：{'Series Arc' if mode == 'series' else 'Anthology'} 規劃")
    print("─" * 50)

    if mode == "series":
        series_id = series_state_manager.create_series(topic, profile, n_episodes)
        arc       = await plan_series_arc(topic, arc_details, profile, n_episodes, provider)
        series_state_manager.save_series_arc(series_id, arc)
        episodes  = arc.episodes
    else:  # anthology
        topics_list: list[str] = job.get("topics", [])
        n_episodes = int(job.get("n_episodes", len(topics_list) if topics_list else 8))
        if topics_list:
            plan = await generate_metadata_for_topics(topics_list, topic or "Anthology", profile, provider)
        else:
            plan = await generate_anthology_plan(topic, arc_details, profile, n_episodes, provider)
        series_id = series_state_manager.create_anthology(plan.title, profile, plan.total_episodes)
        series_state_manager.save_series_arc(series_id, plan)
        episodes  = plan.episodes
        n_episodes = plan.total_episodes

    print(f"✅ 規劃完成，共 {n_episodes} 集")

    # Stage 1: Text generation for ALL episodes
    print("\n" + "─" * 50)
    print("📝  [Batch] Stage 1：所有集數文字生成")
    print("─" * 50)

    all_image_map: dict = {}
    all_audio_map: dict = {}
    all_img_meta:  list = []
    all_audio_meta: list = []

    image_mode = image_settings.get("scene_ratio_mode", "all_16_9")

    for ep_outline in episodes:
        ep_num    = ep_outline.episode_number
        ep_run_id = series_state_manager.get_episode_run_id(series_id, ep_num)
        ep_prefix = f"ep{ep_num:02d}_"
        print(f"\n  📝 Episode {ep_num}：{ep_outline.focus}")

        if mode == "series":
            request = ScriptRequest(
                topic=ep_outline.focus, profile_name=profile,
                provider=provider,
                episode_context={
                    "episode_number": ep_outline.episode_number,
                    "episode_title":  ep_outline.episode_title,
                    "focus":          ep_outline.focus,
                    "key_reveal":     ep_outline.key_reveal,
                    "hook_angle":     ep_outline.hook_angle,
                    "loop_anchor":    ep_outline.loop_anchor,
                    "connects_to_next": ep_outline.connects_to_next,
                    "series_title":   arc.series_title,
                    "series_lens":    arc.series_lens,
                    "total_episodes": arc.total_episodes,
                    "series_payoff":  arc.series_payoff,
                    "previously_covered": [
                        e.focus for e in arc.episodes
                        if e.episode_number < ep_outline.episode_number
                    ],
                },
            )
        else:
            request = ScriptRequest(
                topic=ep_outline.focus, profile_name=profile,
                provider=provider,
                episode_context={
                    "episode_number": ep_outline.episode_number,
                    "focus":          ep_outline.focus,
                    "key_reveal":     ep_outline.key_reveal,
                    "hook_angle":     ep_outline.hook_angle,
                    "loop_anchor":    ep_outline.loop_anchor,
                    "connects_to_next": None,
                    "series_title":   plan.title,
                    "total_episodes": plan.total_episodes,
                    "is_anthology":   True,
                },
            )

        script = await generate_script_router(request)
        state_manager.save_script(ep_run_id, script)
        state_manager.mark_stage(ep_run_id, "text", "completed")
        print(f"     ✅ 劇本：{script.title}（{len(script.scenes)} 個場景）")

        all_scenes = _get_all_scenes(script)
        ratios = _get_scene_ratios(image_mode, len(all_scenes))
        img_map, aud_map, img_meta, aud_meta = _build_scenes_maps(
            ep_prefix, ep_run_id, all_scenes, ratios
        )
        all_image_map.update(img_map)
        all_audio_map.update(aud_map)
        all_img_meta.extend(img_meta)
        all_audio_meta.extend(aud_meta)

    # Submit ONE image batch + ONE audio batch
    print("\n" + "─" * 50)
    print(f"🚀  [Batch] 送出 image batch（{image_provider}，共 {len(all_image_map)} scenes）...")
    image_batch_id = _submit_image(image_provider, all_image_map)
    print(f"   ✅ Image batch: {image_batch_id}")

    print(f"🚀  [Batch] 送出 TTS batch（gemini，共 {len(all_audio_map)} scenes）...")
    audio_batch_id = _submit_audio(all_audio_map)
    print(f"   ✅ Audio batch: {audio_batch_id}")

    # Save batch_jobs.json at series level
    batch_data = {
        "mode": mode,
        "series_or_run_id": series_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "collected": False,
        "job": job,
        "provider_override": provider if provider != job.get("provider", "gemini") else None,
        "tts_sample_rate": tts_settings.get("sample_rate", 24000),
        "image": {
            "provider": image_provider,
            "batch_id": image_batch_id,
            "scenes": all_img_meta,
        },
        "audio": {
            "provider": "gemini",
            "batch_id": audio_batch_id,
            "scenes": all_audio_meta,
        },
    }
    batch_path = WORKSPACE_DIR / series_id / "batch_jobs.json"
    batch_path.write_text(json.dumps(batch_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Mark all episodes' image/audio as batch_submitted
    for ep in episodes:
        ep_run_id = series_state_manager.get_episode_run_id(series_id, ep.episode_number)
        state_manager.mark_stage(ep_run_id, "images", "batch_submitted")
        state_manager.mark_stage(ep_run_id, "audio",  "batch_submitted")

    print("\n" + "=" * 50)
    print("📬  Batch 已送出！")
    print(f"    series_id  : {series_id}")
    print(f"    Image job  : {image_batch_id}")
    print(f"    Audio job  : {audio_batch_id}")
    print(f"\n    電腦重開後執行：")
    print(f"    python main.py --batch-check {series_id}")
    print("=" * 50)


# ── Public entry point ─────────────────────────────────────────────────────

async def run_batch_submit(args, job: Optional[dict] = None) -> None:
    mode = (job.get("mode", "solo") if job else "solo").lower()
    if mode in ("series", "anthology"):
        await _run_batch_multi(args, job, mode)
    else:
        await _run_batch_solo(args, job)
