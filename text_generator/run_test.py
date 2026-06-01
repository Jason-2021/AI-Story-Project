"""
text_generator/run_test.py — 獨立測試腳本：文字生成

用法（從專案根目錄執行）：
  # arc + 所有集數（從 job YAML 讀取）
  python text_generator/run_test.py --job jobs/example_series.yaml --out-dir workspace/test_001

  # arc + 所有集數（CLI 參數）
  python text_generator/run_test.py --topic "Ancient Rome" --profile history --n-episodes 3 --out-dir workspace/test_001

  # 單集（無 arc）
  python text_generator/run_test.py --topic "Ancient Rome" --profile history --out-dir workspace/test_001

  # 不呼叫 API，僅印出 prompt
  python text_generator/run_test.py --job jobs/example_series.yaml --out-dir workspace/test_001 --llm-provider prompt
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import argparse
import yaml
from dotenv import load_dotenv
load_dotenv()


def _parse_args():
    p = argparse.ArgumentParser(description="Text Generator Standalone Test")
    p.add_argument("--job",        type=str, default=None,      help="job YAML 路徑（可代替 CLI 參數）")
    p.add_argument("--topic",      type=str, default=None,      help="系列/單集主題")
    p.add_argument("--profile",    type=str, default="general", help="風格名稱")
    p.add_argument("--llm-provider", type=str, default="gemini", dest="llm_provider", help="LLM 供應商 (gemini | openai | prompt)")
    p.add_argument("--n-episodes", type=int, default=0,         dest="n_episodes",
                   help="集數（>1 啟動系列模式並規劃 arc；0 或 1 = 單集）")
    p.add_argument("--out-dir",    type=str, required=True,     dest="out_dir", help="輸出資料夾")
    p.add_argument("--details",    type=str, default="",        help="額外背景資料（CLI 優先於 job）")
    return p.parse_args()


def _apply_job(args):
    """從 job YAML 補填 CLI 未指定的參數（CLI 顯式值優先）。"""
    if not args.job:
        return
    job = yaml.safe_load(Path(args.job).read_text(encoding="utf-8"))
    if not args.topic:
        args.topic = job.get("topic") or job.get("title")
    if not args.details:
        args.details = job.get("arc_details") or job.get("details", "")
    if args.profile == "general":
        args.profile = job.get("profile", "general")
    if args.llm_provider == "gemini":
        args.llm_provider = job.get("provider", "gemini")
    if args.n_episodes == 0:
        args.n_episodes = int(job.get("n_episodes", 0))


async def _run_series(args, out_dir: Path):
    from series_planner.arc_planner import plan_series_arc
    from text_generator.llm_router import ScriptRequest, generate_script_router

    print(f"\n📚 [TextTest] 系列模式：{args.n_episodes} 集 | 主題: {args.topic}")
    arc = await plan_series_arc(
        topic=args.topic,
        arc_details=args.details,
        profile_name=args.profile,
        n_episodes=args.n_episodes,
        provider=args.llm_provider,
    )
    (out_dir / "series_arc.json").write_text(
        arc.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"  💾 Arc 已存：{out_dir}/series_arc.json\n")

    for ep_outline in arc.episodes:
        ep_num = ep_outline.episode_number
        ep_dir = out_dir / f"ep{ep_num:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)

        previously_covered = [
            e.focus for e in arc.episodes
            if e.episode_number < ep_outline.episode_number
        ]
        episode_context = {
            "episode_number":     ep_outline.episode_number,
            "episode_title":      ep_outline.episode_title,
            "focus":              ep_outline.focus,
            "key_reveal":         ep_outline.key_reveal,
            "hook_angle":         ep_outline.hook_angle,
            "loop_anchor":        ep_outline.loop_anchor,
            "connects_to_next":   ep_outline.connects_to_next,
            "series_title":       arc.series_title,
            "total_episodes":     arc.total_episodes,
            "series_payoff":      arc.series_payoff,
            "previously_covered": previously_covered,
        }

        print(f"{'─'*50}")
        print(f"📝 Ep{ep_num}: {ep_outline.episode_title}")
        req = ScriptRequest(
            topic=ep_outline.focus,
            details=args.details,
            profile_name=args.profile,
            provider=args.llm_provider,
            episode_context=episode_context,
        )
        script = await generate_script_router(req)
        (ep_dir / "script.json").write_text(
            script.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"  ✅ title     : {script.title}")
        print(f"     scenes   : {len(script.scenes)}")
        print(f"     loop_scene: {'有 — ' + (script.loop_scene.narration[:40] + '...') if script.loop_scene else '無'}")


async def _run_solo(args, out_dir: Path):
    from text_generator.llm_router import ScriptRequest, generate_script_router

    print(f"\n📝 [TextTest] 單集模式 | 主題: {args.topic}")
    req = ScriptRequest(
        topic=args.topic,
        details=args.details,
        profile_name=args.profile,
        provider=args.llm_provider,
    )
    script = await generate_script_router(req)
    (out_dir / "script.json").write_text(
        script.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"  ✅ title     : {script.title}")
    print(f"     scenes   : {len(script.scenes)}")
    print(f"     loop_scene: {'有' if script.loop_scene else '無'}")
    print(f"  💾 劇本已存：{out_dir}/script.json")


async def main():
    args = _parse_args()
    _apply_job(args)

    if not args.topic:
        print("❌ 請提供 --topic 或 --job（含 title/topic 欄位）")
        return

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.n_episodes > 1:
        await _run_series(args, out_dir)
    else:
        await _run_solo(args, out_dir)

    print(f"\n🎉 [TextTest] 完成！輸出：{out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
