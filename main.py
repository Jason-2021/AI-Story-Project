"""
AI YouTube Shorts Pipeline — 主調度模組

用法：
  單集影片：
    python main.py --topic "The 2008 Financial Crisis" --profile finance
    python main.py --topic "..." --profile comedy --details "額外背景資料"
    python main.py --job jobs/nv.yaml

  強制重新跑（忽略所有快取）：
    python main.py --topic "..." --profile ... --fresh

  恢復中斷的單集 run：
    python main.py --resume run_20260519_211046

  Series Mode（job YAML 中 mode: series）：
    python main.py --job jobs/example_series.yaml
    python main.py --job jobs/example_series.yaml --arc-only
    python main.py --job jobs/example_series.yaml --episodes 1-2
    python main.py --job jobs/example_series.yaml --resume-series series_20260520_210913

  Anthology Mode（job YAML 中 mode: anthology）：
    python main.py --job jobs/example_anthology.yaml
"""
import asyncio
import argparse
import yaml
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

from core import state_manager
from series_planner.episode_runner import run_episode
from series_planner.series_runner import run_series_mode, run_anthology_mode


# =====================================================================
# CLI 參數
# =====================================================================

def _parse_args():
    parser = argparse.ArgumentParser(description="AI YouTube Shorts Pipeline")
    parser.add_argument("--topic",          type=str, default=None,    help="影片核心主題（單集模式）")
    parser.add_argument("--details",        type=str, default="",      help="額外背景資料")
    parser.add_argument("--profile",        type=str, default="general", help="風格名稱")
    parser.add_argument("--provider",       type=str, default="gemini",  help="LLM 供應商")
    parser.add_argument("--fresh",          action="store_true",       help="強制建立新 run，忽略快取")
    parser.add_argument("--resume",         type=str, default=None,    help="恢復指定的單集 run_id")
    parser.add_argument("--job",            type=str, default=None,    help="Job YAML 檔案路徑")
    parser.add_argument("--resume-series",  type=str, default=None,    help="恢復指定的 series_run_id")
    parser.add_argument("--text-only",       action="store_true",       help="只跑 Stage 1（文字生成），不生成圖片/音訊/影片")
    parser.add_argument("--arc-only",       action="store_true",       help="Series: 只規劃 arc，不生成影片")
    parser.add_argument("--episodes",       type=str, default=None,    help="Series: 只跑指定集數，如 '1-2' 或 '1,3'")
    return parser.parse_args()


def _parse_episodes_filter(episodes_str: Optional[str]) -> Optional[list]:
    """Parse '1-2' → [1, 2] or '1,3' → [1, 3] or None → None."""
    if not episodes_str:
        return None
    if "-" in episodes_str:
        parts = episodes_str.split("-", 1)
        return list(range(int(parts[0]), int(parts[1]) + 1))
    return [int(x.strip()) for x in episodes_str.split(",")]


# =====================================================================
# Solo Mode
# =====================================================================

async def run_solo_mode(args, job: dict = None) -> None:
    """Existing single-video pipeline behavior."""
    topic   = args.topic
    details = args.details
    profile = args.profile
    provider = args.provider
    cta_enabled = (job or {}).get("cta_enabled", True)

    # Determine run_id
    if args.resume:
        run_id = args.resume
        print(f"\n📂 [Main] 恢復 run: {run_id}")

    elif not args.fresh and not topic and (latest := state_manager.get_latest_run_id()):
        all_stages = ["text", "images", "audio", "video"]
        all_done = all(state_manager.get_stage_status(latest, s) == "completed" for s in all_stages)
        if all_done:
            print(f"✅ [Main] run '{latest}' 已全部完成。加上 --fresh 可強制建立新的 run。")
            return
        run_id = latest
        print(f"\n📂 [Main] 恢復未完成的 run: {run_id}")

    else:
        if not topic:
            print("❌ [Main] 建立新 run 需要提供 --topic 或 --job。")
            return
        run_id = None

    completed_id = await run_episode(
        run_id=run_id,
        topic=topic or "",
        profile=profile,
        provider=provider,
        details=details,
        fresh=args.fresh,
        cta_enabled=cta_enabled,
        text_only=args.text_only,
    )

    print("\n" + "=" * 50)
    print("🎉  Pipeline 完成！")
    print(f"    run_id : {completed_id}")
    print(f"    影片   : workspace/{completed_id}/video/output.mp4")
    print("=" * 50)


# =====================================================================
# Entry Point
# =====================================================================

if __name__ == "__main__":
    args = _parse_args()

    job = None
    if args.job:
        job_path = Path(args.job)
        if not job_path.exists():
            print(f"❌ [Main] 找不到 job 檔案：{args.job}")
            raise SystemExit(1)
        job = yaml.safe_load(job_path.read_text(encoding="utf-8"))
        print(f"\n📋 [Main] 載入 job 檔案：{args.job}")

        # Apply job values (CLI explicit values take precedence over job defaults)
        if not args.topic:              args.topic    = job.get("topic") or job.get("title")
        if not args.details:            args.details  = job.get("details", "")
        if args.profile == "general":   args.profile  = job.get("profile", "general")
        if args.provider == "gemini":   args.provider = job.get("provider", "gemini")

    mode = (job.get("mode", "solo") if job else "solo").lower()

    if mode == "series":
        episodes_filter = _parse_episodes_filter(args.episodes)
        asyncio.run(run_series_mode(
            job=job,
            resume_series_id=args.resume_series,
            arc_only=args.arc_only,
            episodes_filter=episodes_filter,
            provider_override=args.provider if args.provider != "gemini" else None,
            text_only=args.text_only,
        ))

    elif mode == "anthology":
        asyncio.run(run_anthology_mode(job=job, text_only=args.text_only))

    else:
        asyncio.run(run_solo_mode(args, job))
