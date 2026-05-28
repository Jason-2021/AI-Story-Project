"""
topic_scraper.py -Bulk topic scraper for the AI Story Project topic bank.

Usage:
  python tools/topic_scraper.py --list-sources
  python tools/topic_scraper.py --source reddit:todayilearned --n 300
  python tools/topic_scraper.py --source wiki:onthisday --date-range 01-01:12-31
  python tools/topic_scraper.py --source wiki:onthisday --date 2026-05-29
  python tools/topic_scraper.py --source wiki:dyk --n 2000
  python tools/topic_scraper.py --source all --n 10000
  python tools/topic_scraper.py --source reddit:todayilearned --n 50 --dry-run

To add a new source:
  1. Subclass BaseScraper, set source_key / description, implement fetch_batch()
  2. Add an instance to SCRAPER_REGISTRY at the bottom of this file
"""

import argparse
import json
import random
import time
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Optional

import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.topic_bank import insert_topic

# ── Auto-tagger ────────────────────────────────────────────────────────────

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "psychology":  ["bias", "brain", "decision", "memory", "fear", "emotion",
                    "psychology", "cognitive", "behavior", "anxiety", "trauma",
                    "perception", "mental", "phobia", "habit"],
    "history":     ["war", "empire", "century", "ancient", "revolution", "kingdom",
                    "historical", "battle", "dynasty", "civilization", "treaty",
                    "uprising", "medieval", "colonial", "wwi", "wwii", "world war"],
    "science":     ["discover", "physics", "biology", "dna", "experiment", "atom",
                    "nasa", "species", "quantum", "evolution", "fossil", "radiation",
                    "molecule", "genome", "astronaut", "telescope"],
    "business":    ["company", "billion", "ceo", "startup", "bankrupt", "market",
                    "corporation", "stock", "investor", "profit", "brand", "merger",
                    "entrepreneur", "revenue", "executive"],
    "nature":      ["animal", "species", "ocean", "evolution", "plant", "habitat",
                    "wildlife", "ecosystem", "mammal", "insect", "reptile", "marine",
                    "jungle", "predator", "migration", "bird", "fish", "whale"],
    "law":         ["illegal", "law", "court", "crime", "prison", "trial",
                    "legal", "statute", "lawsuit", "banned", "criminal", "verdict",
                    "prosecution", "judge", "regulation"],
    "geography":   ["country", "city", "island", "border", "territory", "continent",
                    "capital", "ocean", "mountain", "river", "population", "nation",
                    "latitude", "region", "timezone"],
    "technology":  ["internet", "computer", "software", "patent", "robot", "ai",
                    "invention", "digital", "programming", "satellite", "chip",
                    "algorithm", "engineer", "device", "wireless"],
    "medicine":    ["disease", "virus", "cure", "surgery", "drug", "hospital",
                    "vaccine", "symptom", "diagnosis", "antibiotic", "epidemic",
                    "immune", "cancer", "genetic", "pharmaceutical"],
    "language":    ["word", "language", "translation", "dialect", "etymology",
                    "grammar", "alphabet", "linguistic", "phrase", "etymology",
                    "slang", "pronunciation", "vocabulary"],
}

STYLE_KEYWORDS: dict[str, list[str]] = {
    "counterintuitive": ["actually", "contrary", "opposite", "wrong", "myth",
                         "misconception", "surprising", "unexpected", "despite"],
    "record-breaking":  ["largest", "smallest", "fastest", "oldest", "first",
                         "record", "ever", "most", "least", "never before"],
    "biographical":     ["person", "man", "woman", "he", "she", "his", "her",
                         "born", "died", "invented", "discovered", "founded"],
    "statistics":       ["%", "percent", "million", "billion", "times", "ratio",
                         "majority", "half", "study", "research", "found that"],
    "mystery":          ["unknown", "unsolved", "mystery", "disappear", "strange",
                         "unexplained", "secret", "hidden", "conspiracy"],
    "dark-history":     ["massacre", "genocide", "slavery", "atrocity", "torture",
                         "execution", "banned", "prohibited", "war crime"],
    "event-based":      ["happened", "occurred", "event", "incident", "attack",
                         "explosion", "disaster", "accident", "crisis"],
}

EMOTION_KEYWORDS: dict[str, list[str]] = {
    "surprising":    ["surprisingly", "shocking", "unbelievable", "incredible",
                      "amazing", "astonishing", "remarkably"],
    "humorous":      ["ridiculous", "absurd", "funny", "ironic", "irony",
                      "hilarious", "joke", "satirical", "weird"],
    "inspirational": ["survived", "overcame", "achieved", "success", "triumph",
                      "courage", "despite", "heroic", "saved"],
    "unsettling":    ["dark", "disturbing", "horrifying", "terrifying", "grim",
                      "sinister", "haunting", "chilling", "brutal"],
}


def auto_tag(text: str) -> list[str]:
    """Assign category (exactly one), style (0+), and emotion (0+) tags."""
    lower = text.lower()
    tags: list[str] = []

    # Category: first match wins (ordered by specificity)
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in lower for k in keywords):
            tags.append(cat)
            break
    if not tags:
        tags.append("general")

    # Style tags (multiple)
    for style, keywords in STYLE_KEYWORDS.items():
        if any(k in lower for k in keywords):
            tags.append(style)

    # Emotion tags (multiple)
    for emotion, keywords in EMOTION_KEYWORDS.items():
        if any(k in lower for k in keywords):
            tags.append(emotion)

    return tags


# ── Base class ─────────────────────────────────────────────────────────────

class SourceExhaustedException(Exception):
    pass


class BaseScraper(ABC):
    """
    Base class for all topic scrapers.

    To add a new source:
    1. Subclass BaseScraper, set source_key, description, and supports_date
    2. Implement fetch_batch(n, **kwargs) → list[dict]
       Each dict: {title, description, source_url, source_score, tags}
    3. Register an instance in SCRAPER_REGISTRY at the bottom of this file
    """

    source_key: str = ""
    description: str = ""
    supports_date: bool = False  # set True to enable --date / --date-range

    @abstractmethod
    def fetch_batch(self, n: int, **kwargs) -> list[dict]:
        """
        Fetch up to n topics. May return fewer if source is exhausted.
        Raise SourceExhaustedException if the source has no more data.
        Each returned dict must have at minimum: title (str).
        Optional keys: description, source_url, source_score.
        tags will be auto-assigned if not provided.
        """

    def _get(self, url: str, params: dict = None, retries: int = 3) -> dict:
        headers = {"User-Agent": "AI-Story-Project/1.0 topic-scraper"}
        for attempt in range(retries):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=15)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)


# ── Reddit scraper ─────────────────────────────────────────────────────────

class RedditScraper(BaseScraper):
    MIN_SCORE = 5000
    MIN_UPVOTE_RATIO = 0.85

    def __init__(self, subreddit: str):
        self.subreddit = subreddit
        self.source_key = f"reddit:{subreddit}"
        self.description = f"Reddit r/{subreddit} - top posts all time (score >= {self.MIN_SCORE})"

    def fetch_batch(self, n: int, **kwargs) -> list[dict]:
        results: list[dict] = []
        after: Optional[str] = None
        seen: set[str] = set()

        # Scrape top/all first, then top/year for more unique posts
        for time_filter in ("all", "year"):
            after = None
            while len(results) < n:
                params = {"limit": 100, "t": time_filter, "raw_json": 1}
                if after:
                    params["after"] = after

                url = f"https://www.reddit.com/r/{self.subreddit}/top.json"
                try:
                    data = self._get(url, params)
                except Exception as e:
                    print(f"  [WARN] Reddit fetch error: {e}")
                    break

                children = data.get("data", {}).get("children", [])
                if not children:
                    break

                for child in children:
                    post = child.get("data", {})
                    url_id = post.get("url", "")
                    if url_id in seen:
                        continue
                    seen.add(url_id)

                    score = post.get("score", 0)
                    ratio = post.get("upvote_ratio", 0)
                    title = post.get("title", "").strip()

                    if score < self.MIN_SCORE or ratio < self.MIN_UPVOTE_RATIO:
                        continue
                    if not title or len(title) < 20:
                        continue

                    results.append({
                        "title": title,
                        "description": post.get("selftext", "")[:300],
                        "source_url": f"https://reddit.com{post.get('permalink', '')}",
                        "source_score": score,
                    })
                    if len(results) >= n:
                        break

                after = data.get("data", {}).get("after")
                if not after:
                    break
                time.sleep(1)  # Reddit rate limit

        if not results:
            raise SourceExhaustedException(
                f"r/{self.subreddit}: no posts found matching score ≥ {self.MIN_SCORE}"
            )
        return results[:n]


# ── Wikipedia On This Day ──────────────────────────────────────────────────

class WikiOTDScraper(BaseScraper):
    source_key = "wiki:onthisday"
    description = "Wikipedia On This Day - historical events per calendar date (~3200 total)"
    supports_date = True

    def fetch_batch(self, n: int, **kwargs) -> list[dict]:
        """
        kwargs:
          date (str): "YYYY-MM-DD" -fetch events for this specific date
          date_range (str): "MM-DD:MM-DD" -fetch events across date range
          If neither provided, randomly sample dates until n events collected.
        """
        specific_date: Optional[str] = kwargs.get("date")
        date_range: Optional[str] = kwargs.get("date_range")

        # Build list of (month, day) tuples to fetch
        if specific_date:
            d = date.fromisoformat(specific_date)
            dates = [(d.month, d.day)]
        elif date_range:
            start_str, end_str = date_range.split(":")
            sm, sd = int(start_str[:2]), int(start_str[3:])
            em, ed = int(end_str[:2]), int(end_str[3:])
            start = date(2000, sm, sd)
            end = date(2000, em, ed)
            if end < start:
                end = date(2001, em, ed)
            dates = []
            cur = start
            while cur <= end:
                dates.append((cur.month, cur.day))
                cur += timedelta(days=1)
        else:
            # Random sampling
            all_days = [(m, d) for m in range(1, 13)
                        for d in range(1, 29)]  # safe: skip 29-31
            random.shuffle(all_days)
            dates = all_days

        results: list[dict] = []
        for month, day in dates:
            if len(results) >= n:
                break
            url = f"https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{month}/{day}"
            try:
                data = self._get(url)
            except Exception as e:
                print(f"  [WARN] Wiki OTD {month}/{day}: {e}")
                time.sleep(1)
                continue

            for event in data.get("events", []):
                year = event.get("year", "")
                text = event.get("text", "").strip()
                if not text:
                    continue
                title = f"On this day in {year}: {text}" if year else text
                results.append({
                    "title": title[:300],
                    "description": "",
                    "source_url": "",
                    "source_score": None,
                })
                if len(results) >= n:
                    break
            time.sleep(0.3)

        if not results:
            raise SourceExhaustedException("wiki:onthisday: no events fetched")
        return results[:n]


# ── Wikipedia Did You Know ─────────────────────────────────────────────────

class WikiDYKScraper(BaseScraper):
    source_key = "wiki:dyk"
    description = "Wikipedia Did You Know - community-curated facts archive (2004-present, ~4000 total)"

    _MONTHS = ["January","February","March","April","May","June",
               "July","August","September","October","November","December"]

    def fetch_batch(self, n: int, **kwargs) -> list[dict]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError(
                "beautifulsoup4 is required for wiki:dyk. "
                "Install with: pip install beautifulsoup4"
            )

        results: list[dict] = []
        current_year = date.today().year

        for year in range(current_year, 2003, -1):
            for month in reversed(self._MONTHS):
                if len(results) >= n:
                    break
                url = f"https://en.wikipedia.org/wiki/Wikipedia:Recent_additions/{year}/{month}"
                try:
                    r = requests.get(
                        url,
                        headers={"User-Agent": "AI-Story-Project/1.0"},
                        timeout=15
                    )
                    if r.status_code == 404:
                        continue
                    r.raise_for_status()
                except Exception as e:
                    print(f"  [WARN] Wiki DYK {year}/{month}: {e}")
                    time.sleep(1)
                    continue

                soup = BeautifulSoup(r.text, "html.parser")
                # DYK entries are typically in <li> tags starting with "... that"
                for li in soup.find_all("li"):
                    text = li.get_text(separator=" ", strip=True)
                    if "... that" in text.lower() or text.startswith("..."):
                        clean = text.replace("... that", "Did you know that").strip()
                        if len(clean) > 30:
                            results.append({
                                "title": clean[:300],
                                "description": "",
                                "source_url": url,
                                "source_score": None,
                            })
                    if len(results) >= n:
                        break
                time.sleep(0.5)

        if not results:
            raise SourceExhaustedException("wiki:dyk: no entries fetched (beautifulsoup4 required)")
        return results[:n]


# ── Wikipedia Unusual Articles ─────────────────────────────────────────────

class WikiUnusualScraper(BaseScraper):
    source_key = "wiki:unusual"
    description = "Wikipedia Unusual Articles - curated list of fascinating/bizarre topics (~400 total)"

    def fetch_batch(self, n: int, **kwargs) -> list[dict]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError(
                "beautifulsoup4 is required for wiki:unusual. "
                "Install with: pip install beautifulsoup4"
            )

        url = "https://en.wikipedia.org/wiki/Wikipedia:Unusual_articles"
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "AI-Story-Project/1.0"},
                timeout=20
            )
            r.raise_for_status()
        except Exception as e:
            raise SourceExhaustedException(f"wiki:unusual fetch failed: {e}")

        soup = BeautifulSoup(r.text, "html.parser")
        results: list[dict] = []

        for li in soup.find_all("li"):
            a = li.find("a")
            if not a:
                continue
            article_title = a.get("title", "").strip()
            desc = li.get_text(separator=" ", strip=True)
            if not article_title or len(desc) < 20:
                continue
            results.append({
                "title": article_title,
                "description": desc[:300],
                "source_url": f"https://en.wikipedia.org/wiki/{article_title.replace(' ', '_')}",
                "source_score": None,
            })
            if len(results) >= n:
                break

        if not results:
            raise SourceExhaustedException("wiki:unusual: no articles parsed")
        return results[:n]


# ── Registry ───────────────────────────────────────────────────────────────

SCRAPER_REGISTRY: dict[str, BaseScraper] = {
    "reddit:todayilearned": RedditScraper("todayilearned"),
    "reddit:history":       RedditScraper("history"),
    "reddit:science":       RedditScraper("science"),
    "reddit:psychology":    RedditScraper("psychology"),
    "reddit:business":      RedditScraper("business"),
    "reddit:worldnews":     RedditScraper("worldnews"),
    "reddit:space":         RedditScraper("space"),
    "wiki:onthisday":       WikiOTDScraper(),
    "wiki:dyk":             WikiDYKScraper(),
    "wiki:unusual":         WikiUnusualScraper(),
}


# ── Core run logic ─────────────────────────────────────────────────────────

def run_scraper(
    source_key: str,
    n: int,
    dry_run: bool = False,
    date_arg: Optional[str] = None,
    date_range: Optional[str] = None,
) -> None:
    scraper = SCRAPER_REGISTRY.get(source_key)
    if not scraper:
        print(f"[ERROR] Unknown source: '{source_key}'. Run --list-sources to see options.")
        return

    print(f"\n[Scraper] [{source_key}] target: {n}  {'(dry-run)' if dry_run else ''}")

    kwargs = {}
    if date_arg:
        kwargs["date"] = date_arg
    if date_range:
        kwargs["date_range"] = date_range

    try:
        raw = scraper.fetch_batch(n, **kwargs)
    except SourceExhaustedException as e:
        print(f"[WARN] [{source_key}] source exhausted: {e}")
        print(f"   Tip: lower --n or pick another source (--list-sources)")
        raw = []
    except ImportError as e:
        print(f"[ERROR] [{source_key}] missing dependency: {e}")
        return

    if not raw:
        print(f"   collected 0 items, skipping.")
        return

    print(f"   fetched {len(raw)} raw items, deduping + writing...")
    inserted = 0
    duped = 0

    for item in raw:
        title = item.get("title", "").strip()
        if not title:
            continue
        tags = item.get("tags") or auto_tag(title + " " + item.get("description", ""))

        if dry_run:
            print(f"   [DRY] {title[:80]}  tags={tags}")
            inserted += 1
            continue

        result = insert_topic(
            title=title,
            source_type=scraper.source_key.split(":")[0],
            tags=tags,
            description=item.get("description", ""),
            source_url=item.get("source_url", ""),
            source_score=item.get("source_score"),
        )
        if result is None:
            duped += 1
        else:
            inserted += 1

    print(f"[OK] [{source_key}] inserted {inserted}, skipped {duped} duplicates")
    if len(raw) < n:
        print(f"[WARN] [{source_key}] only got {len(raw)}/{n} items (source may be near exhaustion)")


# ── CLI ────────────────────────────────────────────────────────────────────

def _print_sources() -> None:
    print("\nAvailable sources:\n")
    for key, scraper in SCRAPER_REGISTRY.items():
        date_note = "  [supports: --date, --date-range]" if scraper.supports_date else ""
        print(f"  {key:<30} {scraper.description}{date_note}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk topic scraper for AI Story Project topic bank.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source", default="",
                        help="Source key (e.g. reddit:todayilearned) or 'all'")
    parser.add_argument("--n", type=int, default=200,
                        help="Target number of topics to collect (default: 200)")
    parser.add_argument("--date", default="",
                        help="[wiki:onthisday] Specific date: YYYY-MM-DD")
    parser.add_argument("--date-range", default="",
                        help="[wiki:onthisday] Date range: MM-DD:MM-DD (e.g. 01-01:12-31)")
    parser.add_argument("--list-sources", action="store_true",
                        help="Print all available sources and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be scraped without writing to DB")

    args = parser.parse_args()

    if args.list_sources:
        _print_sources()
        return

    if not args.source:
        parser.print_help()
        return

    if args.source == "all":
        for key in SCRAPER_REGISTRY:
            run_scraper(key, args.n, dry_run=args.dry_run,
                        date_arg=args.date or None,
                        date_range=args.date_range or None)
    else:
        run_scraper(args.source, args.n, dry_run=args.dry_run,
                    date_arg=args.date or None,
                    date_range=args.date_range or None)


if __name__ == "__main__":
    main()
