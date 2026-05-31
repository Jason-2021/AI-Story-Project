# Topic Scraper — Available Sources

All sources are accessed via `tools/topic_scraper.py --source <key>`.

Run `python tools/topic_scraper.py --list-sources` to see this list in the terminal.

---

## reddit:todayilearned

- **Description**: Reddit r/TodayILearned — top posts of all time (score ≥ 5000)
- **Estimated max**: ~800–1000 unique posts
- **Extra params**: `--recent` (fetch top/month only, for weekly supplement)
- **Requires**: `pip install praw` + Reddit API credentials (see `tools/REDDIT_APP_SETUP.md`)
- **Notes**: Rate limit (100 req/min) handled automatically by PRAW.
- **Usage**:
  ```bash
  python tools/topic_scraper.py --source reddit:todayilearned --n 800
  ```

---

## reddit:history

- **Description**: Reddit r/history — top posts of all time (score ≥ 5000)
- **Estimated max**: ~400–600 unique posts
- **Extra params**: `--recent`
- **Requires**: `pip install praw` + Reddit API credentials (see `tools/REDDIT_APP_SETUP.md`)
- **Usage**:
  ```bash
  python tools/topic_scraper.py --source reddit:history --n 400
  ```

---

## reddit:science

- **Description**: Reddit r/science — top posts of all time (score ≥ 5000)
- **Estimated max**: ~500–700 unique posts
- **Extra params**: `--recent`
- **Requires**: `pip install praw` + Reddit API credentials (see `tools/REDDIT_APP_SETUP.md`)
- **Usage**:
  ```bash
  python tools/topic_scraper.py --source reddit:science --n 500
  ```

---

## reddit:psychology

- **Description**: Reddit r/psychology — top posts of all time (score ≥ 5000)
- **Estimated max**: ~200–350 unique posts
- **Extra params**: `--recent`
- **Requires**: `pip install praw` + Reddit API credentials (see `tools/REDDIT_APP_SETUP.md`)
- **Usage**:
  ```bash
  python tools/topic_scraper.py --source reddit:psychology --n 200
  ```

---

## reddit:business

- **Description**: Reddit r/business — top posts of all time (score ≥ 5000)
- **Estimated max**: ~200–300 unique posts
- **Extra params**: `--recent`
- **Requires**: `pip install praw` + Reddit API credentials (see `tools/REDDIT_APP_SETUP.md`)
- **Usage**:
  ```bash
  python tools/topic_scraper.py --source reddit:business --n 200
  ```

---

## reddit:worldnews

- **Description**: Reddit r/worldnews — top posts of all time (score ≥ 5000)
- **Estimated max**: ~400–600 unique posts
- **Extra params**: `--recent`
- **Requires**: `pip install praw` + Reddit API credentials (see `tools/REDDIT_APP_SETUP.md`)
- **Notes**: Topics tend to be event-based and geography/politics-heavy. Good for `history` and `geography` tags.
- **Usage**:
  ```bash
  python tools/topic_scraper.py --source reddit:worldnews --n 400
  ```

---

## reddit:space

- **Description**: Reddit r/space — top posts of all time (score ≥ 5000)
- **Estimated max**: ~300–500 unique posts
- **Extra params**: `--recent`
- **Requires**: `pip install praw` + Reddit API credentials (see `tools/REDDIT_APP_SETUP.md`)
- **Notes**: Strongest source for `science` + `technology` tags.
- **Usage**:
  ```bash
  python tools/topic_scraper.py --source reddit:space --n 300
  ```

---

## wiki:onthisday

- **Description**: Wikipedia "On This Day" — historical events for each calendar date
- **Estimated max**: ~3,200 total (365 days × ~9 events/day average)
- **Extra params**:
  - `--date YYYY-MM-DD` — fetch only events for this date
  - `--date-range MM-DD:MM-DD` — fetch events across a calendar range (e.g. `01-01:12-31` for the full year)
  - *(no date flag)* — randomly sample dates until `--n` is reached
- **Notes**: Uses the official Wikimedia REST API. Free, no key required. Rate-limited to ~0.3 req/sec.
- **Usage**:
  ```bash
  # Full year sweep (recommended for initial bulk load)
  python tools/topic_scraper.py --source wiki:onthisday --date-range 01-01:12-31 --n 4000

  # Single date
  python tools/topic_scraper.py --source wiki:onthisday --date 2026-05-29

  # Random 100 dates
  python tools/topic_scraper.py --source wiki:onthisday --n 100
  ```

---

## wiki:dyk

- **Description**: Wikipedia "Did You Know" — monthly archive of community-curated interesting facts (2004–present)
- **Estimated max**: ~4,000 total (~260 monthly archive pages × 15–20 facts/page)
- **Extra params**: none (automatically crawls from most recent month backwards)
- **Requires**: `pip install beautifulsoup4`
- **Notes**: HTML scraping. Slower than API-based sources (~0.5 req/sec). Highest quality — all facts are peer-reviewed by the Wikipedia community.
- **Usage**:
  ```bash
  # Full archive (takes ~30–60 min)
  python tools/topic_scraper.py --source wiki:dyk --n 4000

  # Partial (recent 6 months)
  python tools/topic_scraper.py --source wiki:dyk --n 100
  ```

---

## wiki:unusual

- **Description**: Wikipedia "Unusual Articles" — curated list of Wikipedia's most bizarre and fascinating topics
- **Estimated max**: ~350–450 entries
- **Extra params**: none (single-page scrape)
- **Requires**: `pip install beautifulsoup4`
- **Notes**: One-time scrape. Re-running is safe (DB deduplication). Topics tend to be `counterintuitive` + `humorous`.
- **Usage**:
  ```bash
  python tools/topic_scraper.py --source wiki:unusual --n 400
  ```

---

## Bulk Initial Load (破萬目標)

Run all sources sequentially to populate the full database (~10,000+ topics):

```bash
# Reddit (all 7 subreddits) — ~2,700 topics
python tools/topic_scraper.py --source reddit:todayilearned --n 800
python tools/topic_scraper.py --source reddit:history       --n 500
python tools/topic_scraper.py --source reddit:science       --n 500
python tools/topic_scraper.py --source reddit:psychology    --n 300
python tools/topic_scraper.py --source reddit:business      --n 300
python tools/topic_scraper.py --source reddit:worldnews     --n 400
python tools/topic_scraper.py --source reddit:space         --n 300

# Wikipedia — ~7,000 topics
python tools/topic_scraper.py --source wiki:onthisday --date-range 01-01:12-31
python tools/topic_scraper.py --source wiki:dyk       --n 4000
python tools/topic_scraper.py --source wiki:unusual   --n 400
```

Expected total after dedup: **~9,500–11,000 topics**

---

## Adding a New Source

1. Open `tools/topic_scraper.py`
2. Create a class that inherits `BaseScraper`:
   ```python
   class MyNewScraper(BaseScraper):
       source_key  = "mysite:category"
       description = "Description shown in --list-sources"
       supports_date = False

       def fetch_batch(self, n: int, **kwargs) -> list[dict]:
           # fetch data, return list of dicts with at minimum: {"title": "..."}
           ...
   ```
3. Register it in `SCRAPER_REGISTRY`:
   ```python
   SCRAPER_REGISTRY["mysite:category"] = MyNewScraper()
   ```
4. Add an entry to this file.
