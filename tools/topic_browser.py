"""
topic_browser.py — Browse and select topics from the topic bank.

Usage:
  # View unused topics tagged 'psychology' and export for review
  python tools/topic_browser.py --tag psychology --n 20

  # After marking [x] in the exported .md file, confirm selection
  python tools/topic_browser.py --confirm topics_bank/exports/2026-05-29_psychology.md

  # View topics with multiple tag filters
  python tools/topic_browser.py --tag history --style counterintuitive --n 15

  # Show overall DB stats
  python tools/topic_browser.py --stats
"""

import argparse
import json
import re
from datetime import date
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.topic_bank import (
    count_by_status,
    count_by_tag_and_status,
    get_stats,
    mark_status_by_title,
    query_by_tag,
)

EXPORTS_DIR = Path(__file__).parent.parent / "topics_bank" / "exports"


def _export_for_review(topics: list[dict], tag: str, style: str = "") -> Path:
    """Write a markdown review file with [ ] checkboxes."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    suffix = f"_{style}" if style else ""
    path = EXPORTS_DIR / f"{today}_{tag}{suffix}.md"

    lines = [
        f"# Topic Review — {tag}{(' · ' + style) if style else ''} — {today}",
        "",
        "Mark topics you want to use with **[x]** then run:",
        f"```",
        f"python tools/topic_browser.py --confirm {path}",
        f"```",
        "",
        "---",
        "",
    ]

    for i, t in enumerate(topics, 1):
        score_str = f"  score={t['source_score']}" if t.get("source_score") else ""
        tags_str = ", ".join(json.loads(t.get("tags", "[]")))
        lines.append(f"### {i}. [ ] {t['title']}")
        lines.append(f"*source: {t['source_type']}{score_str} | tags: {tags_str}*")
        if t.get("description"):
            lines.append(f"> {t['description'][:200]}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def cmd_browse(tag: str, n: int, style: str = "") -> None:
    style_tags = [style] if style else None
    topics = query_by_tag(tag, status="unused", limit=n, style_tags=style_tags)

    if not topics:
        total = count_by_tag_and_status(tag, "unused")
        print(f"[WARN] No unused topics found for tag='{tag}'{' style=' + style if style else ''}.")
        print(f"   Total unused with tag '{tag}': {total}")
        return

    path = _export_for_review(topics, tag, style)
    print(f"\n[OK] {len(topics)} topics exported -> {path}")
    print(f"   Mark [x] next to topics you want, then run:")
    print(f"   python tools/topic_browser.py --confirm \"{path}\"")


def cmd_confirm(filepath: str) -> None:
    path = Path(filepath)
    if not path.exists():
        print(f"[ERROR] File not found: {filepath}")
        return

    text = path.read_text(encoding="utf-8")
    # Match lines like: ### N. [x] <title>
    pattern = re.compile(r"###\s+\d+\.\s+\[x\]\s+(.+)", re.IGNORECASE)
    selected_titles = [m.group(1).strip() for m in pattern.finditer(text)]

    if not selected_titles:
        print("[WARN] No [x] selections found. Mark items like: ### 1. [x] title")
        return

    updated = 0
    for title in selected_titles:
        mark_status_by_title(title, "selected")
        updated += 1
        print(f"  [+] selected: {title[:80]}")

    print(f"\n[OK] {updated} topics marked as 'selected' in the DB.")
    print(f"   Next step: python tools/job_builder.py --n 8 --profile evergreen")


def cmd_stats() -> None:
    stats = get_stats()
    print("\n[Stats] Topic Bank")
    print(f"  Total     : {stats['total']}")
    print(f"  Unused    : {stats.get('unused', 0)}")
    print(f"  Selected  : {stats.get('selected', 0)}")
    print(f"  Used      : {stats.get('used', 0)}")
    print(f"  Skipped   : {stats.get('skipped', 0)}")
    print(f"  Rejected  : {stats.get('rejected', 0)}")
    days_left = stats.get("unused", 0) // 8
    print(f"\n  Days of daily content remaining: ~{days_left} days")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Browse and select topics from the topic bank.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--tag", default="", help="Category tag to filter (e.g. psychology)")
    parser.add_argument("--style", default="", help="Style tag to additionally filter (e.g. counterintuitive)")
    parser.add_argument("--n", type=int, default=20, help="Number of topics to show (default: 20)")
    parser.add_argument("--confirm", default="", metavar="PATH",
                        help="Path to a reviewed .md file — mark [x] selections as 'selected' in DB")
    parser.add_argument("--stats", action="store_true", help="Show DB statistics and exit")

    args = parser.parse_args()

    if args.stats:
        cmd_stats()
        return

    if args.confirm:
        cmd_confirm(args.confirm)
        return

    if not args.tag:
        parser.print_help()
        print("\nAvailable category tags: psychology, history, science, business, nature,")
        print("                         law, geography, technology, medicine, language, general")
        return

    cmd_browse(args.tag, args.n, args.style)


if __name__ == "__main__":
    main()
