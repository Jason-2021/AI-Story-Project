"""
topic_bank.py — SQLite wrapper for the topic bank database.

Schema:
  topics(id, title, description, source_type, source_url, source_score,
         scraped_at, tags, status, used_in, used_at)

status lifecycle: unused → selected → used
                  unused → skipped
                  unused → rejected
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "topics_bank" / "topics.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS topics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    description  TEXT,
    source_type  TEXT    NOT NULL,
    source_url   TEXT,
    source_score INTEGER,
    scraped_at   TEXT    NOT NULL,
    tags         TEXT    NOT NULL DEFAULT '[]',
    status       TEXT    NOT NULL DEFAULT 'unused',
    used_in      TEXT,
    used_at      TEXT,
    event_date   TEXT
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_status_tags ON topics(status, tags);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(_CREATE_TABLE)
    conn.execute(_CREATE_INDEX)
    conn.commit()
    return conn


# ── Write ──────────────────────────────────────────────────────────────────

def insert_topic(
    title: str,
    source_type: str,
    tags: list[str],
    description: str = "",
    source_url: str = "",
    source_score: Optional[int] = None,
) -> Optional[int]:
    """
    Insert a topic. Returns new row id, or None if deduplicated.
    Dedup key: source_url (non-empty) or title hash.
    """
    with _connect() as conn:
        if source_url:
            row = conn.execute(
                "SELECT id FROM topics WHERE source_url = ?", (source_url,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM topics WHERE title = ? AND source_type = ?",
                (title, source_type),
            ).fetchone()

        if row:
            return None  # duplicate

        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """INSERT INTO topics
               (title, description, source_type, source_url, source_score, scraped_at, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title, description, source_type, source_url, source_score, now,
             json.dumps(tags)),
        )
        return cur.lastrowid


def bulk_insert_topics(items: list[dict]) -> tuple[int, int]:
    """
    批次寫入。先一筆一筆 SELECT 檢查 duplicate（讀取不需 commit，速度快），
    收集所有非重複項，最後一次 transaction INSERT 全部。
    Returns (inserted, duped).

    每個 item dict 須有：title, source_type, tags（list）
    可選：description, source_url, source_score, event_date
    """
    if not items:
        return 0, 0

    now = datetime.now(timezone.utc).isoformat()
    to_insert = []
    duped = 0

    with _connect() as conn:
        # Step 1: 一筆一筆 SELECT 檢查（讀取，無 fsync 成本）
        for item in items:
            source_url = item.get("source_url", "")
            title      = item.get("title", "")
            source_type = item.get("source_type", "")

            if source_url:
                row = conn.execute(
                    "SELECT id FROM topics WHERE source_url = ?", (source_url,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM topics WHERE title = ? AND source_type = ?",
                    (title, source_type),
                ).fetchone()

            if row:
                duped += 1
            else:
                to_insert.append((
                    title,
                    item.get("description", ""),
                    source_type,
                    source_url,
                    item.get("source_score"),
                    now,
                    json.dumps(item.get("tags", [])),
                    item.get("event_date"),
                ))

        # Step 2: 一次 INSERT 全部（單一 transaction，一次 fsync）
        if to_insert:
            conn.executemany(
                """INSERT INTO topics
                   (title, description, source_type, source_url, source_score, scraped_at, tags, event_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                to_insert,
            )

    return len(to_insert), duped


def mark_status(topic_id: int, status: str, used_in: str = "") -> None:
    """Update status. For 'used', also set used_in and used_at."""
    with _connect() as conn:
        if status == "used":
            conn.execute(
                "UPDATE topics SET status=?, used_in=?, used_at=? WHERE id=?",
                (status, used_in, datetime.now(timezone.utc).date().isoformat(), topic_id),
            )
        else:
            conn.execute("UPDATE topics SET status=? WHERE id=?", (status, topic_id))


def mark_status_by_title(title: str, status: str, used_in: str = "") -> None:
    """Convenience: update status by exact title match."""
    with _connect() as conn:
        row = conn.execute("SELECT id FROM topics WHERE title = ?", (title,)).fetchone()
        if row:
            mark_status(row["id"], status, used_in)


# ── Read ───────────────────────────────────────────────────────────────────

def query_by_tag(
    category_tag: str,
    status: str = "unused",
    limit: int = 20,
    style_tags: Optional[list[str]] = None,
) -> list[dict]:
    """
    Return up to `limit` topics matching category_tag and status.
    Optionally filter by style_tags (all must be present).
    Results ordered by source_score DESC (Reddit), then scraped_at DESC.
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM topics
               WHERE status = ?
                 AND tags LIKE ?
               ORDER BY COALESCE(source_score, 0) DESC, scraped_at DESC
               LIMIT ?""",
            (status, f'%"{category_tag}"%', limit * 4),  # over-fetch for style filter
        ).fetchall()

        results = [dict(r) for r in rows]

        if style_tags:
            filtered = []
            for r in results:
                t = set(json.loads(r["tags"]))
                if all(s in t for s in style_tags):
                    filtered.append(r)
            results = filtered

        return results[:limit]


def query_by_event_date(month: int, day: int, limit: int = 20) -> list[dict]:
    """
    撈 wiki:onthisday 類型：event_date 格式為 "MM-DD"。
    例如 query_by_event_date(2, 18) 撈 2/18 的歷史事件。
    """
    pattern = f"{month:02d}-{day:02d}"
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM topics
               WHERE status = 'unused' AND event_date = ?
               ORDER BY scraped_at DESC
               LIMIT ?""",
            (pattern, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def query_selected(category_tag: str = "", limit: int = 8) -> list[dict]:
    """Return topics with status='selected', optionally filtered by category_tag."""
    with _connect() as conn:
        if category_tag:
            rows = conn.execute(
                """SELECT * FROM topics
                   WHERE status = 'selected' AND tags LIKE ?
                   ORDER BY id LIMIT ?""",
                (f'%"{category_tag}"%', limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM topics WHERE status = 'selected' ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def count_by_status(status: str = "unused") -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM topics WHERE status = ?", (status,)
        ).fetchone()
        return row["n"]


def count_by_tag_and_status(category_tag: str, status: str = "unused") -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM topics WHERE status = ? AND tags LIKE ?",
            (status, f'%"{category_tag}"%'),
        ).fetchone()
        return row["n"]


def get_stats() -> dict:
    """Return counts per status."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM topics GROUP BY status"
        ).fetchall()
        stats = {r["status"]: r["n"] for r in rows}
        stats.setdefault("unused", 0)
        stats.setdefault("selected", 0)
        stats.setdefault("used", 0)
        stats["total"] = sum(stats.values())
        return stats
