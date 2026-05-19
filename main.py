"""
AI YouTube Shorts Pipeline — 主調度模組

用法：
  新建影片：
    python main.py --topic "The 2008 Financial Crisis" --profile finance
    python main.py --topic "..." --profile comedy --details "額外背景資料"

  強制重新跑（忽略所有快取）：
    python main.py --topic "..." --profile ... --fresh

  恢復中斷的 run（跳過已完成的 stage）：
    python main.py --resume run_20260519_211046
"""
import asyncio
import argparse
import json
import yaml
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from core import state_manager
from text_generator.llm_router import ScriptRequest, VideoScript, generate_script_router
from image_generator.image_router import generate_images_router
from audio_generator.audio_router import generate_audio_router
from video_renderer.engine import render_video


# =====================================================================
# CLI 參數
# =====================================================================

def _parse_args():
    parser = argparse.ArgumentParser(description="AI YouTube Shorts Pipeline")
    parser.add_argument("--topic",    type=str, default=None, help="影片核心主題")
    parser.add_argument("--details",  type=str, default="",   help="額外背景資料")
    parser.add_argument("--profile",  type=str, default="general", help="風格名稱（profiles/ 資料夾下的 YAML 名稱）")
    parser.add_argument("--provider", type=str, default="gemini",  help="LLM 供應商")
    parser.add_argument("--fresh",    action="store_true", help="強制建立新 run，忽略所有快取")
    parser.add_argument("--resume",   type=str, default=None, help="指定要恢復的 run_id")
    parser.add_argument("--job",      type=str, default=None, help="Job YAML 檔案路徑（含 topic / profile / details）")
    return parser.parse_args()


# =====================================================================
# Stage 輔助函數
# =====================================================================

async def _run_image_stage(run_id: str, script: VideoScript) -> None:
    image_dir = state_manager.get_image_dir(run_id)
    state_manager.mark_stage(run_id, "images", "in_progress")
    results = await generate_images_router(script.scenes, output_dir=image_dir)
    (image_dir / "image_results.json").write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state_manager.mark_stage(run_id, "images", "completed")
    print(f"  ✅ [Images] {len(results)} 張圖片完成")


async def _run_audio_stage(run_id: str, script: VideoScript) -> None:
    audio_dir = state_manager.get_audio_dir(run_id)
    state_manager.mark_stage(run_id, "audio", "in_progress")
    results = await generate_audio_router(script.scenes, output_dir=audio_dir)
    (audio_dir / "audio_results.json").write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state_manager.mark_stage(run_id, "audio", "completed")
    print(f"  ✅ [Audio] {len(results)} 個音檔完成")


# =====================================================================
# 主流程
# =====================================================================

async def run_pipeline(args) -> None:

    # ── Job YAML 載入（蓋掉 CLI 預設值，CLI 明確傳入時 CLI 優先）────────
    if args.job:
        job_path = Path(args.job)
        if not job_path.exists():
            print(f"❌ [Main] 找不到 job 檔案：{args.job}")
            return
        job = yaml.safe_load(job_path.read_text(encoding="utf-8"))
        args.topic    = job.get("topic")    or args.topic
        args.details  = job.get("details")  or args.details
        args.profile  = job.get("profile")  or args.profile
        args.provider = job.get("provider") or args.provider
        print(f"\n📋 [Main] 載入 job 檔案：{args.job}")

    # ── 決定 run_id ──────────────────────────────────────────────────
    if args.resume:
        run_id = args.resume
        print(f"\n📂 [Main] 恢復 run: {run_id}")

    elif not args.fresh and not args.topic and (latest := state_manager.get_latest_run_id()):
        all_stages = ["text", "images", "audio", "video"]
        all_done = all(
            state_manager.get_stage_status(latest, s) == "completed"
            for s in all_stages
        )
        if all_done:
            print(f"✅ [Main] run '{latest}' 已全部完成。")
            print("   加上 --fresh 可強制建立新的 run。")
            return
        run_id = latest
        print(f"\n📂 [Main] 恢復未完成的 run: {run_id}")

    else:
        if not args.topic:
            print("❌ [Main] 建立新 run 需要提供 --topic。")
            return
        run_id = None   # 待 text stage 後再建立

    # ── Stage 1：文字生成 ─────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("📝  Stage 1 / 3：文字生成")
    print("─" * 50)

    if run_id and state_manager.get_stage_status(run_id, "text") == "completed":
        print("⚡ 從快取載入劇本")
        script = state_manager.load_script(run_id, VideoScript)
    else:
        if not args.topic:
            print("❌ 恢復的 run 缺少劇本，且未提供 --topic。")
            return
        request = ScriptRequest(
            topic=args.topic,
            details=args.details,
            profile_name=args.profile,
            provider=args.provider,
        )
        script = await generate_script_router(request)

        if run_id is None:
            run_id = state_manager.create_run(args.topic, args.profile)

        state_manager.save_script(run_id, script)
        state_manager.mark_stage(run_id, "text", "completed")

    print(f"✅ 劇本：{script.title}（{len(script.scenes)} 個場景）")

    # ── Stage 2：圖片 + 音訊（平行） ─────────────────────────────────
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

    # ── Stage 3：影片渲染 ─────────────────────────────────────────────
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

    # ── 完成 ──────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print(f"🎉  Pipeline 完成！")
    print(f"    run_id : {run_id}")
    print(f"    影片   : workspace/{run_id}/video/output.mp4")
    print("=" * 50)


# =====================================================================
# Entry Point
# =====================================================================

if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(run_pipeline(args))
