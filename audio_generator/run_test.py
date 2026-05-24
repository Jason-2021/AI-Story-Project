"""
audio_generator/run_test.py — 獨立測試腳本：音訊生成

用法（從專案根目錄執行）：
  # 單集
  python audio_generator/run_test.py --input-dir workspace/test_001/ep01

  # 所有集數
  python audio_generator/run_test.py --input-dir workspace/test_001

  # 指定集數
  python audio_generator/run_test.py --input-dir workspace/test_001 --episodes 1-3
  python audio_generator/run_test.py --input-dir workspace/test_001 --episodes 1,3
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import argparse
import json
from dotenv import load_dotenv
load_dotenv()


def _parse_args():
    p = argparse.ArgumentParser(description="Audio Generator Standalone Test")
    p.add_argument("--input-dir", type=str, required=True, dest="input_dir",
                   help="含 script.json 的單集資料夾，或含 ep*/ 子資料夾的系列根目錄")
    p.add_argument("--episodes",  type=str, default=None,
                   help="指定集數：'1-3'（範圍）或 '1,3'（指定），僅在系列模式有效")
    p.add_argument("--provider",  type=str, default="gemini", help="TTS 供應商")
    return p.parse_args()


def _parse_episodes(ep_str):
    if not ep_str:
        return None
    if "-" in ep_str:
        parts = ep_str.split("-", 1)
        return list(range(int(parts[0]), int(parts[1]) + 1))
    return [int(x.strip()) for x in ep_str.split(",")]


async def _process_ep(ep_dir: Path, provider: str):
    from text_generator.llm_router import VideoScript
    from audio_generator.audio_router import generate_audio_router

    script_path = ep_dir / "script.json"
    if not script_path.exists():
        print(f"  ⚠️  找不到 {script_path}，跳過")
        return

    script = VideoScript.model_validate_json(script_path.read_text(encoding="utf-8"))
    all_scenes = list(script.scenes)
    if script.loop_scene:
        script.loop_scene.scene_id = 0
        all_scenes = [script.loop_scene] + all_scenes

    audio_dir = ep_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    results = await generate_audio_router(all_scenes, output_dir=audio_dir, provider=provider)
    (audio_dir / "audio_results.json").write_text(
        json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    total_dur = sum(r.duration for r in results)
    print(f"  ✅ {ep_dir.name}: {len(results)} 個音檔，總時長 {total_dur:.1f}s → {audio_dir}")


async def main():
    args = _parse_args()
    input_dir = Path(args.input_dir).resolve()
    episodes_filter = _parse_episodes(args.episodes)

    if not input_dir.exists():
        print(f"❌ 找不到：{input_dir}")
        return

    if (input_dir / "script.json").exists():
        # 單集模式
        print(f"\n🔊 [AudioTest] 單集模式：{input_dir.name}")
        await _process_ep(input_dir, args.provider)
    else:
        # 系列模式
        ep_dirs = sorted(d for d in input_dir.iterdir() if d.is_dir() and d.name.startswith("ep"))
        if episodes_filter is not None:
            ep_dirs = [d for d in ep_dirs if int(d.name[2:]) in episodes_filter]
        if not ep_dirs:
            print("❌ 找不到任何 ep*/ 資料夾，請確認 --input-dir 正確")
            return
        print(f"\n🔊 [AudioTest] 系列模式：處理 {len(ep_dirs)} 集")
        for ep_dir in ep_dirs:
            await _process_ep(ep_dir, args.provider)

    print(f"\n🎉 [AudioTest] 完成！")


if __name__ == "__main__":
    asyncio.run(main())
