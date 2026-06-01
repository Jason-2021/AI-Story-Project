"""
job_builder.py — Generate an anthology job YAML from the topic bank.

Picks 8 topics (by tag) from the DB and writes a ready-to-run job YAML.

Usage:
  python tools/job_builder.py --tag psychology --profile evergreen
  python tools/job_builder.py --tag history    --profile education --n 8
  python tools/job_builder.py --tag science    --profile science   --n 6
  python tools/job_builder.py --stats

Workflow:
  1. Prefers topics with status='selected' (from topic_browser --confirm)
  2. Falls back to status='unused' if not enough selected topics
  3. Outputs jobs/daily/YYYY-MM-DD_{tag}_{profile}.yaml
"""

import argparse
import json
import time
import yaml
import requests
from datetime import date
from pathlib import Path
from urllib.parse import quote

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.topic_bank import (
    count_by_tag_and_status,
    get_stats,
    mark_status_by_title,
    query_by_tag,
    query_selected,
)

JOBS_DIR = Path(__file__).parent.parent / "jobs" / "daily"

# ── Sensitive topic filter ─────────────────────────────────────────────────

_SENSITIVE_KEYWORDS = [
    # criminal/legal
    "indicted", "arrested", "charged with", "convicted", "conspiracy to",
    "kidnap", "kidnapping", "assassination", "assassinated",
    "war crime", "war crimes", "genocide", "sentenced to", "imprisoned",
    "executed for", "bomb plot", "terror plot", "murder of",
    # personal harm
    "rape", "sexual assault", "child abuse",
]


def _is_sensitive(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in _SENSITIVE_KEYWORDS)


# ── Wikipedia context fetcher ─────────────────────────────────────────────

def _fetch_wiki_context(source_url: str) -> str:
    """Wikipedia REST API で記事の intro paragraph を取得（~200 words）。"""
    if not source_url.startswith("https://en.wikipedia.org/wiki/"):
        return ""
    article_path = source_url.replace("https://en.wikipedia.org/wiki/", "")
    api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(article_path)}"
    try:
        r = requests.get(
            api_url,
            headers={"User-Agent": "AI-Story-Project/1.0"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("extract", "")[:800]
    except Exception:
        pass
    return ""


# ── Title templates per category tag ──────────────────────────────────────

TITLE_TEMPLATES: dict[str, list[str]] = {
    "psychology":  [
        "Psychology Facts That Will Change How You See Yourself",
        "The Hidden Psychology Behind Everyday Decisions",
        "8 Mind-Bending Psychology Facts Most People Don't Know",
    ],
    "history":     [
        "History Facts Your Textbook Never Taught You",
        "8 Historical Events That Changed Everything",
        "The Hidden Side of History Nobody Talks About",
    ],
    "science":     [
        "Science Facts That Will Completely Rewire Your Brain",
        "8 Scientific Discoveries That Shocked the World",
        "The Counterintuitive Science Behind Everyday Life",
    ],
    "business":    [
        "Business Decisions That Made — and Destroyed — Empires",
        "8 Corporate Stories You Won't Believe Are True",
        "The Brutal Reality Behind Famous Business Collapses",
    ],
    "nature":      [
        "Nature Facts That Prove the World Is Stranger Than Fiction",
        "8 Animal Behaviors That Will Blow Your Mind",
        "The Hidden Wonders of the Natural World",
    ],
    "law":         [
        "Laws So Bizarre You Won't Believe They're Real",
        "8 Legal Cases That Changed How We Live",
        "The Strange Side of Law Nobody Tells You About",
    ],
    "geography":   [
        "Geography Facts That Will Change How You See the World",
        "8 Places and Borders That Defy All Logic",
        "The Hidden Geography Behind Global Events",
    ],
    "technology":  [
        "Tech Inventions That Changed Everything — and Almost Didn't Happen",
        "8 Technology Facts That Rewrote History",
        "The Untold Origins of the Technology You Use Every Day",
    ],
    "medicine":    [
        "Medical Facts That Will Change How You Think About Your Body",
        "8 Medical Breakthroughs That Saved Millions",
        "The Dark and Surprising History of Modern Medicine",
    ],
    "language":    [
        "Language Facts That Reveal How We Really Think",
        "8 Word Origins That Will Completely Surprise You",
        "The Hidden Linguistics Behind Everyday Communication",
    ],
    "general":     [
        "8 Incredible Facts You Won't Believe Are True",
        "Mind-Blowing Facts That Will Leave You Speechless",
        "Things That Actually Happened That Sound Completely Made Up",
    ],
}

_title_cycle: dict[str, int] = {}


def _pick_title(tag: str) -> str:
    templates = TITLE_TEMPLATES.get(tag, TITLE_TEMPLATES["general"])
    idx = _title_cycle.get(tag, 0) % len(templates)
    _title_cycle[tag] = idx + 1
    return templates[idx]


# ── Core logic ─────────────────────────────────────────────────────────────

def build_job(tag: str, profile: str, n: int, output_path: Path) -> None:
    # 1. Prefer selected topics for this tag
    selected = query_selected(category_tag=tag, limit=n)
    topics = selected[:]

    # 2. Fill remaining from unused
    if len(topics) < n:
        needed = n - len(topics)
        selected_titles = {t["title"] for t in topics}
        fallback = query_by_tag(tag, status="unused", limit=needed * 3)
        for t in fallback:
            if t["title"] not in selected_titles:
                topics.append(t)
            if len(topics) >= n:
                break

    # Filter sensitive topics before processing
    before = len(topics)
    topics = [t for t in topics if not _is_sensitive(t["title"])]
    removed = before - len(topics)
    if removed:
        print(f"[FILTER] {removed} topic(s) removed (sensitive keyword match).")

    if not topics:
        print(f"[ERROR] No topics found for tag='{tag}'. Run the scraper first:")
        print(f"   python tools/topic_scraper.py --source reddit:todayilearned --n 300")
        return

    if len(topics) < n:
        print(f"[WARN] Only {len(topics)}/{n} topics available for tag='{tag}'.")
        print(f"   Proceeding with {len(topics)} episodes.")
        n = len(topics)
        topics = topics[:n]

    title = _pick_title(tag)

    # 對有 Wikipedia source_url 的題目抓 intro context
    topic_contexts = {}
    wiki_topics = [t for t in topics if t.get("source_url", "").startswith("https://en.wikipedia.org/wiki/")]
    if wiki_topics:
        print(f"   抓取 {len(wiki_topics)} 筆 Wikipedia context...")
        for t in wiki_topics:
            ctx = _fetch_wiki_context(t["source_url"])
            if ctx:
                topic_contexts[t["title"]] = ctx
            time.sleep(0.3)

    job_data = {
        "mode":    "anthology",
        "title":   title,
        "profile": profile,
        "topics":  [t["title"] for t in topics],
    }
    if topic_contexts:
        job_data["topic_contexts"] = topic_contexts

    yaml_content = yaml.dump(job_data, allow_unicode=True, default_flow_style=False, sort_keys=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_content, encoding="utf-8")

    print(f"\n[OK] Job YAML written -> {output_path}")
    print(f"   Title   : {title}")
    print(f"   Profile : {profile}")
    print(f"   Episodes: {len(topics)}")
    for i, t in enumerate(topics, 1):
        src = t.get("source_type", "?")
        print(f"   {i:2d}. [{src}] {t['title'][:70]}")

    print(f"\nNext step:")
    print(f"   python main.py --job \"{output_path}\"")

    # Mark as 'used' (placeholder — anthology_id filled by pipeline)
    for t in topics:
        mark_status_by_title(t["title"], "used", used_in="pending")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an anthology job YAML from the topic bank.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--tag", default="",
                        help="Category tag to select topics from (e.g. psychology)")
    parser.add_argument("--profile", default="evergreen",
                        help="Profile name (default: evergreen)")
    parser.add_argument("--n", type=int, default=8,
                        help="Number of episodes (default: 8)")
    parser.add_argument("--out", default="",
                        help="Custom output path (default: jobs/daily/YYYY-MM-DD_tag_profile.yaml)")
    parser.add_argument("--stats", action="store_true",
                        help="Show DB statistics and available tags")

    args = parser.parse_args()

    if args.stats:
        stats = get_stats()
        print("\n[Stats] Topic Bank")
        print(f"  Total  : {stats['total']}")
        print(f"  Unused : {stats.get('unused', 0)}  (~{stats.get('unused', 0) // 8} anthology days)")
        print(f"  Used   : {stats.get('used', 0)}")
        print()
        for tag in ["psychology", "history", "science", "business", "nature",
                    "law", "geography", "technology", "medicine", "language", "general"]:
            count = count_by_tag_and_status(tag, "unused")
            bar = "█" * min(count // 10, 40)
            print(f"  {tag:<14} {count:>5} unused  {bar}")
        return

    if not args.tag:
        parser.print_help()
        return

    today = date.today().isoformat()
    out_path = Path(args.out) if args.out else (
        JOBS_DIR / f"{today}_{args.tag}_{args.profile}.yaml"
    )
    build_job(args.tag, args.profile, args.n, out_path)


if __name__ == "__main__":
    main()
