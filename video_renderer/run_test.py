"""
video_renderer/run_test.py — 獨立測試腳本：影片渲染

用法（從專案根目錄執行）：
  # 單集短影音
  python video_renderer/run_test.py --input-dir workspace/test_001/ep01

  # 所有集數短影音（各自輸出）
  python video_renderer/run_test.py --input-dir workspace/test_001

  # 指定集數短影音
  python video_renderer/run_test.py --input-dir workspace/test_001 --episodes 1-2

  # 長影音 merge（需先完成所有集數的圖片+音訊）
  python video_renderer/run_test.py --input-dir workspace/test_001 --long-form
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from dotenv import load_dotenv
load_dotenv()


def _parse_args():
    p = argparse.ArgumentParser(description="Video Renderer Standalone Test")
    p.add_argument("--input-dir", type=str, required=True, dest="input_dir",
                   help="單集 ep 資料夾，或系列根目錄（含 ep*/ 子資料夾）")
    p.add_argument("--episodes",  type=str, default=None,
                   help="指定集數：'1-2'（範圍）或 '1,3'（指定），僅系列模式有效")
    p.add_argument("--long-form", action="store_true", dest="long_form",
                   help="渲染長影音 merge（系列模式專用）")
    return p.parse_args()


def _parse_episodes(ep_str):
    if not ep_str:
        return None
    if "-" in ep_str:
        parts = ep_str.split("-", 1)
        return list(range(int(parts[0]), int(parts[1]) + 1))
    return [int(x.strip()) for x in ep_str.split(",")]


def _render_short(ep_dir: Path):
    from video_renderer.engine import render_video
    # workspace_override = ep_dir.parent, run_id = ep_dir.name
    # engine: ep_dir_resolved = workspace_override / run_id = ep_dir
    print(f"\n🎬 [VideoTest] 短影音渲染：{ep_dir.name}")
    out = render_video(run_id=ep_dir.name, workspace_override=ep_dir.parent)
    print(f"  ✅ 輸出：{out}")


def _render_longform(input_dir: Path, episodes_filter):
    from video_renderer.engine import render_longform
    ep_dirs = sorted(d for d in input_dir.iterdir() if d.is_dir() and d.name.startswith("ep"))
    if episodes_filter is not None:
        ep_dirs = [d for d in ep_dirs if int(d.name[2:]) in episodes_filter]
    if not ep_dirs:
        print("❌ 找不到任何 ep*/ 資料夾")
        return

    # workspace_override = input_dir.parent, series_id = input_dir.name
    # ep_run_ids = ["{series_id}/{ep_name}", ...]
    # engine: series_dir = workspace_override / series_id = input_dir ✓
    # engine: ep_dir     = workspace_override / ep_run_id  = input_dir/ep01 ✓
    series_id = input_dir.name
    ep_run_ids = [f"{series_id}/{d.name}" for d in ep_dirs]

    print(f"\n🎞️  [VideoTest] 長影音 merge：{len(ep_dirs)} 集")
    out = render_longform(
        series_id=series_id,
        ep_run_ids=ep_run_ids,
        add_title_cards=True,
        workspace_override=input_dir.parent,
    )
    print(f"  ✅ 輸出：{out}")


def main():
    args = _parse_args()
    input_dir = Path(args.input_dir).resolve()
    episodes_filter = _parse_episodes(args.episodes)

    if not input_dir.exists():
        print(f"❌ 找不到：{input_dir}")
        return

    if args.long_form:
        # 長影音模式：input_dir 必須是系列根目錄
        _render_longform(input_dir, episodes_filter)

    elif (input_dir / "script.json").exists():
        # 單集模式
        _render_short(input_dir)

    else:
        # 系列模式：逐集渲染短影音
        ep_dirs = sorted(d for d in input_dir.iterdir() if d.is_dir() and d.name.startswith("ep"))
        if episodes_filter is not None:
            ep_dirs = [d for d in ep_dirs if int(d.name[2:]) in episodes_filter]
        if not ep_dirs:
            print("❌ 找不到任何 ep*/ 資料夾，請確認 --input-dir 正確")
            return
        print(f"\n🎬 [VideoTest] 系列短影音渲染：{len(ep_dirs)} 集")
        for ep_dir in ep_dirs:
            _render_short(ep_dir)

    print(f"\n🎉 [VideoTest] 完成！")


if __name__ == "__main__":
    main()
