"""
Standalone batch status viewer.

掃描 workspace 下所有 batch_jobs.json（collected=False），
查詢 API 狀態並列表顯示。方便找 batch ID 和確認進度。

Usage:
  python tools/batch_status.py
  python tools/batch_status.py --collect <batch_id>
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"


def _check_status_quick(batch_jobs: dict) -> tuple[str, str]:
    """Return (img_status_label, aud_status_label) without downloading results."""
    img_info = batch_jobs.get("image", {})
    aud_info = batch_jobs.get("audio", {})

    def _img_status(info: dict) -> str:
        bid = info.get("batch_id", "")
        if not bid:
            return "CLEARED"
        provider = info.get("provider", "gemini")
        try:
            if provider == "gemini":
                from image_generator.gemini_image_batch import collect_image_batch
                status, ok, err = collect_image_batch(bid)
            else:
                from image_generator.openai_image_batch import collect_image_batch
                status, ok, err = collect_image_batch(bid)
            if status == "pending":
                return "IN_PROGRESS"
            return status.upper()
        except Exception as e:
            return f"ERROR({e})"

    def _aud_status(info: dict) -> str:
        bid = info.get("batch_id", "")
        if not bid:
            return "CLEARED"
        try:
            from audio_generator.gemini_tts_batch import collect_tts_batch
            status, ok, err = collect_tts_batch(bid)
            if status == "pending":
                return "IN_PROGRESS"
            return status.upper()
        except Exception as e:
            return f"ERROR({e})"

    return _img_status(img_info), _aud_status(aud_info)


def list_pending() -> None:
    pending = []
    for batch_path in sorted(WORKSPACE_DIR.glob("*/batch_jobs.json")):
        data = json.loads(batch_path.read_text(encoding="utf-8"))
        if data.get("collected"):
            continue
        parent_id = batch_path.parent.name
        pending.append((parent_id, data))

    if not pending:
        print("✅ 沒有待收取的 batch job。")
        return

    print(f"\n{'ID':<40} {'Mode':<12} {'Image':<16} {'Audio':<16} {'Submitted'}")
    print("-" * 100)
    for pid, data in pending:
        mode    = data.get("mode", "?")
        submitted = data.get("submitted_at", "")[:19]
        print(f"{pid:<40} {mode:<12}", end="  ", flush=True)
        img_s, aud_s = _check_status_quick(data)
        print(f"{img_s:<16} {aud_s:<16} {submitted}")

    print()
    print("若 batch 完成，執行：python main.py --batch-check <ID>")


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch status viewer")
    parser.add_argument("--collect", type=str, default=None,
                        help="直接對指定 ID 執行 collect（等同 main.py --batch-check）")
    args = parser.parse_args()

    if args.collect:
        from series_planner.batch_collector import run_batch_collect
        asyncio.run(run_batch_collect(args.collect))
    else:
        list_pending()


if __name__ == "__main__":
    main()
