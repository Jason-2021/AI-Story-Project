"""
Batch collect orchestrator.

讀取 batch_jobs.json → 查詢 API 狀態 → 依狀態決定行為：
  PENDING/RUNNING → 印出進度，EXIT 0（下次再跑）
  EXPIRED        → 清除 job ID，印警告，EXIT
  FAILED         → 印錯誤，EXIT non-zero
  PARTIAL        → collect 成功 scene，realtime fallback 補失敗 scene
  COMPLETED      → collect 所有 scene

collect 完成後：
  - image bytes 存為 PNG
  - audio bytes (PCM) 轉 WAV，跑 Whisper 取字幕時間軸
  - 執行 Stage 3 (render_video) for each episode
  - series/anthology: merge long-form
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

from core import state_manager, series_state_manager
from audio_generator.gemini_tts_adapter import _write_wav
from audio_generator.audio_router import _run_whisper, AudioResult, WordTimestamp

WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"


# ── Batch status query ─────────────────────────────────────────────────────

def _query_image_status(image_info: dict) -> tuple[str, dict, dict]:
    provider = image_info["provider"]
    batch_id = image_info["batch_id"]
    if provider == "gemini":
        from image_generator.gemini_image_batch import collect_image_batch
        return collect_image_batch(batch_id)
    else:
        from image_generator.openai_image_batch import collect_image_batch
        return collect_image_batch(batch_id)


def _query_audio_status(audio_info: dict) -> tuple[str, dict, dict]:
    from audio_generator.gemini_tts_batch import collect_tts_batch
    return collect_tts_batch(audio_info["batch_id"])


# ── Save collected results ─────────────────────────────────────────────────

def _save_image(run_id: str, scene_id: int, image_bytes: bytes) -> None:
    img_dir = WORKSPACE_DIR / run_id / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / f"scene_{scene_id:02d}.png").write_bytes(image_bytes)


async def _save_audio_and_whisper(
    run_id: str, scene_id: int, pcm_bytes: bytes, sample_rate: int
) -> AudioResult:
    audio_dir = WORKSPACE_DIR / run_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav_path = audio_dir / f"scene_{scene_id:02d}.wav"
    _write_wav(pcm_bytes, wav_path, sample_rate)
    timestamps, duration = await asyncio.to_thread(_run_whisper, wav_path)
    return AudioResult(
        scene_id=scene_id,
        file_path=str(wav_path),
        duration=duration,
        timestamps=timestamps,
    )


# ── Realtime fallback ──────────────────────────────────────────────────────

async def _fallback_image(meta: dict, provider: str) -> None:
    """Regenerate a single failed image via realtime API."""
    from image_generator.image_router import _get_gemini_image_settings, _get_openai_image_settings
    run_id   = meta["run_id"]
    scene_id = meta["scene_id"]
    prompt   = meta["prompt"]
    ratio    = meta["aspect_ratio"]
    img_dir  = WORKSPACE_DIR / run_id / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    out_path = img_dir / f"scene_{scene_id:02d}.png"

    print(f"  ↩️  [Fallback] image scene {scene_id} via realtime {provider}...")
    if provider == "gemini":
        from image_generator.gemini_imagen_adapter import generate_image_with_gemini
        settings = _get_gemini_image_settings()
        await generate_image_with_gemini(prompt, out_path, settings.get("model_name"), ratio)
    else:
        from image_generator.openai_dalle_adapter import generate_image_with_openai
        from image_generator.openai_image_batch import _ASPECT_TO_SIZE
        settings = _get_openai_image_settings()
        await generate_image_with_openai(
            prompt, out_path, settings.get("model_name"), ratio, settings.get("quality", "low")
        )
    print(f"     ✅ fallback 完成: {out_path.name}")


async def _fallback_audio(meta: dict, sample_rate: int) -> AudioResult:
    """Regenerate a single failed audio via realtime TTS."""
    from audio_generator.gemini_tts_adapter import generate_tts_with_gemini
    from audio_generator.audio_router import _get_tts_settings
    run_id    = meta["run_id"]
    scene_id  = meta["scene_id"]
    narration = meta["narration"]
    audio_dir = WORKSPACE_DIR / run_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav_path  = audio_dir / f"scene_{scene_id:02d}.wav"
    settings  = _get_tts_settings()

    print(f"  ↩️  [Fallback] audio scene {scene_id} via realtime TTS...")
    await generate_tts_with_gemini(
        narration, wav_path,
        settings.get("model_name"), settings.get("voice_name", "charon"), sample_rate,
    )
    timestamps, duration = await asyncio.to_thread(_run_whisper, wav_path)
    print(f"     ✅ fallback 完成: {wav_path.name}")
    return AudioResult(scene_id=scene_id, file_path=str(wav_path), duration=duration, timestamps=timestamps)


# ── Distribute results ─────────────────────────────────────────────────────

async def _distribute_images(
    img_successes: dict, img_failures: dict,
    img_scenes_meta: list, image_provider: str,
) -> None:
    for meta in img_scenes_meta:
        cid      = meta["custom_id"]
        run_id   = meta["run_id"]
        scene_id = meta["scene_id"]
        if cid in img_successes:
            _save_image(run_id, scene_id, img_successes[cid])
        elif cid in img_failures:
            await _fallback_image(meta, image_provider)
        else:
            print(f"  ⚠️  [Image] {cid} 既無成功也無失敗記錄，跳過")


async def _distribute_audio(
    aud_successes: dict, aud_failures: dict,
    aud_scenes_meta: list, sample_rate: int,
) -> dict[str, list[AudioResult]]:
    """Returns {run_id: [AudioResult, ...]}"""
    run_audio: dict[str, list] = {}
    tasks = []

    for meta in aud_scenes_meta:
        key      = meta["key"]
        run_id   = meta["run_id"]
        scene_id = meta["scene_id"]
        run_audio.setdefault(run_id, [])

        if key in aud_successes:
            tasks.append((run_id, scene_id, "batch", aud_successes[key]))
        elif key in aud_failures:
            tasks.append((run_id, scene_id, "fallback", meta))
        else:
            print(f"  ⚠️  [Audio] {key} 既無成功也無失敗記錄，跳過")

    for run_id, scene_id, source, payload in tasks:
        if source == "batch":
            result = await _save_audio_and_whisper(run_id, scene_id, payload, sample_rate)
        else:
            result = await _fallback_audio(payload, sample_rate)
        run_audio[run_id].append(result)

    return run_audio


def _write_audio_results(run_id: str, results: list[AudioResult]) -> None:
    audio_dir = WORKSPACE_DIR / run_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "audio_results.json").write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Video rendering ────────────────────────────────────────────────────────

def _render_episode(run_id: str) -> None:
    from video_renderer.engine import render_video
    state_manager.mark_stage(run_id, "video", "in_progress")
    out = render_video(run_id)
    state_manager.mark_stage(run_id, "video", "completed")
    print(f"  ✅ 影片輸出：{out}")


# ── Main entry point ───────────────────────────────────────────────────────

async def run_batch_collect(batch_id: str) -> None:
    """
    batch_id: run_id（solo）或 series_id / anthology_id（multi）
    """
    batch_path = WORKSPACE_DIR / batch_id / "batch_jobs.json"
    if not batch_path.exists():
        print(f"❌ [BatchCollect] 找不到 batch_jobs.json：{batch_path}")
        raise SystemExit(1)

    batch_data = json.loads(batch_path.read_text(encoding="utf-8"))

    if batch_data.get("collected"):
        print(f"✅ [BatchCollect] {batch_id} 已 collect 過，影片應已生成。")
        return

    mode        = batch_data["mode"]
    image_info  = batch_data["image"]
    audio_info  = batch_data["audio"]
    sample_rate = batch_data.get("tts_sample_rate", 24000)
    render_cfg  = batch_data.get("render_config", {})

    # ── 1. Query status ──────────────────────────────────────────────
    print(f"\n🔍  [BatchCollect] 查詢 batch 狀態：{batch_id}")
    img_status,  img_ok,  img_err  = _query_image_status(image_info)
    aud_status,  aud_ok,  aud_err  = _query_audio_status(audio_info)

    print(f"  📸 Image batch ({image_info['provider']}): {img_status.upper()}"
          f"  ✓{len(img_ok)} ✗{len(img_err)}")
    print(f"  🎙️  Audio batch (gemini): {aud_status.upper()}"
          f"  ✓{len(aud_ok)} ✗{len(aud_err)}")

    # Handle expired
    if img_status == "expired" or aud_status == "expired":
        print("\n⚠️  [BatchCollect] 一個或多個 batch job 已過期（Gemini 48h 限制）。")
        if img_status == "expired":
            batch_data["image"]["batch_id"] = ""
            print("   image batch 已清除，請重新 submit。")
        if aud_status == "expired":
            batch_data["audio"]["batch_id"] = ""
            print("   audio batch 已清除，請重新 submit。")
        batch_path.write_text(json.dumps(batch_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("   執行：python main.py --batch [原本的參數] --fresh")
        raise SystemExit(1)

    # Handle fully failed
    if img_status == "failed" and aud_status == "failed":
        print("\n❌ [BatchCollect] 兩個 batch job 皆失敗，請重新 submit。")
        raise SystemExit(1)

    # Handle still pending (either one)
    if img_status == "pending" or aud_status == "pending":
        print("\n⏳ [BatchCollect] Batch 尚未完成，請稍後再試。")
        raise SystemExit(0)

    # ── 2. Distribute image results ──────────────────────────────────
    print("\n📥  [BatchCollect] 下載並儲存圖片...")
    if img_status in ("completed", "partial"):
        await _distribute_images(img_ok, img_err, image_info["scenes"], image_info["provider"])
    elif img_status == "failed":
        # Fallback all image scenes via realtime
        print("  ⚠️  image batch 整體失敗，realtime fallback 所有場景...")
        for meta in image_info["scenes"]:
            await _fallback_image(meta, image_info["provider"])

    # ── 3. Distribute audio results + Whisper ────────────────────────
    print("\n📥  [BatchCollect] 下載音訊並執行 Whisper...")
    if aud_status in ("completed", "partial"):
        run_audio = await _distribute_audio(aud_ok, aud_err, audio_info["scenes"], sample_rate)
    else:
        # Fallback all audio scenes
        print("  ⚠️  audio batch 整體失敗，realtime fallback 所有場景...")
        run_audio = {}
        for meta in audio_info["scenes"]:
            run_id = meta["run_id"]
            run_audio.setdefault(run_id, [])
            result = await _fallback_audio(meta, sample_rate)
            run_audio[run_id].append(result)

    # Write audio_results.json per run_id and mark stages
    unique_run_ids = list({m["run_id"] for m in image_info["scenes"]})
    for run_id in unique_run_ids:
        results = sorted(run_audio.get(run_id, []), key=lambda r: r.scene_id)
        _write_audio_results(run_id, results)
        state_manager.mark_stage(run_id, "images", "completed")
        state_manager.mark_stage(run_id, "audio",  "completed")

    # ── 4. Video rendering ───────────────────────────────────────────
    print("\n🎬  [BatchCollect] Stage 3：影片渲染")
    for run_id in unique_run_ids:
        print(f"\n  🎥 渲染：{run_id}")
        _render_episode(run_id)

    # ── 5. Merge (series / anthology) ────────────────────────────────
    if mode in ("series", "anthology") and render_cfg.get("combine_long_form"):
        series_id  = batch_data["series_or_run_id"]
        n_episodes = batch_data["n_episodes"]
        ep_run_ids = [
            series_state_manager.get_episode_run_id(series_id, i + 1)
            for i in range(n_episodes)
        ]
        from series_planner.merger import merge_episodes
        print("\n🎞️   [BatchCollect] 合併長影片...")
        merge_episodes(series_id, ep_run_ids, render_cfg.get("add_title_cards", True))

    # ── 6. Mark as collected ─────────────────────────────────────────
    batch_data["collected"] = True
    batch_path.write_text(json.dumps(batch_data, ensure_ascii=False, indent=2), encoding="utf-8")

    if mode == "series" or mode == "anthology":
        series_id = batch_data["series_or_run_id"]
        n_eps     = batch_data["n_episodes"]
        for i in range(n_eps):
            series_state_manager.mark_episode_status(series_id, i + 1, "completed")

    print("\n" + "=" * 50)
    print("🎉  Batch collect 完成！")
    if mode == "solo":
        rid = batch_data["series_or_run_id"]
        print(f"    影片：workspace/{rid}/video/output.mp4")
    else:
        sid = batch_data["series_or_run_id"]
        print(f"    集數：workspace/{sid}/ep*/video/output.mp4")
        if render_cfg.get("combine_long_form"):
            print(f"    長片：workspace/{sid}/long_form/output.mp4")
    print("=" * 50)
