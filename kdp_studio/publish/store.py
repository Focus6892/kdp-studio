"""SQLite log of publishing events, per-title status and the submission queue."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  book_id TEXT NOT NULL,
  book_path TEXT,
  fmt TEXT NOT NULL,
  event TEXT NOT NULL,
  notes TEXT,
  asin TEXT
);
CREATE TABLE IF NOT EXISTS titles (
  book_id TEXT NOT NULL,
  fmt TEXT NOT NULL,
  title TEXT,
  status TEXT NOT NULL,
  asin TEXT,
  created_ts TEXT,
  submitted_ts TEXT,
  live_ts TEXT,
  notes TEXT,
  PRIMARY KEY (book_id, fmt)
);
CREATE TABLE IF NOT EXISTS queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_path TEXT NOT NULL,
  book_id TEXT,
  fmt TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 5,
  status TEXT NOT NULL DEFAULT 'queued',
  added_ts TEXT NOT NULL,
  started_ts TEXT,
  done_ts TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_fmt_ts ON events(fmt, event, ts);
"""

STATUSES = ("draft", "in_review", "live", "blocked", "unpublished")


def _iso(ts: dt.datetime | None) -> str:
    return (ts or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat()


class PublishStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- events
    def add_event(self, book_id: str, fmt: str, event: str, *, book_path: str | None = None, notes: str | None = None, asin: str | None = None, ts: dt.datetime | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO events (ts, book_id, book_path, fmt, event, notes, asin) VALUES (?,?,?,?,?,?,?)",
            (_iso(ts), book_id, book_path, fmt, event, notes, asin),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def count_events(self, event: str, fmt: str, start: dt.datetime, end: dt.datetime) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event = ? AND fmt = ? AND ts >= ? AND ts < ?",
            (event, fmt, _iso(start), _iso(end)),
        ).fetchone()
        return int(row["n"])

    def events(self, book_id: str | None = None) -> list[dict]:
        if book_id:
            rows = self.conn.execute("SELECT * FROM events WHERE book_id = ? ORDER BY id", (book_id,))
        else:
            rows = self.conn.execute("SELECT * FROM events ORDER BY id")
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- titles
    def upsert_title(self, book_id: str, fmt: str, status: str, *, title: str | None = None, asin: str | None = None, notes: str | None = None, ts: dt.datetime | None = None) -> dict:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        now = _iso(ts)
        cur = self.get_title(book_id, fmt) or {}
        created = cur.get("created_ts") or now
        submitted = cur.get("submitted_ts")
        live = cur.get("live_ts")
        if status == "in_review" and not submitted:
            submitted = now
        if status == "live" and not live:
            live = now
        self.conn.execute(
            "INSERT INTO titles (book_id, fmt, title, status, asin, created_ts, submitted_ts, live_ts, notes) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(book_id, fmt) DO UPDATE SET title=COALESCE(excluded.title, titles.title), status=excluded.status, asin=COALESCE(excluded.asin, titles.asin), "
            "submitted_ts=excluded.submitted_ts, live_ts=excluded.live_ts, notes=COALESCE(excluded.notes, titles.notes)",
            (book_id, fmt, title, status, asin, created, submitted, live, notes),
        )
        self.conn.commit()
        return self.get_title(book_id, fmt) or {}

    def get_title(self, book_id: str, fmt: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM titles WHERE book_id = ? AND fmt = ?", (book_id, fmt)).fetchone()
        return dict(row) if row else None

    def titles(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM titles ORDER BY created_ts")]

    # ---------------------------------------------------------------- queue
    def queue_add(self, book_path: str, fmt: str, priority: int = 5, book_id: str | None = None, notes: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO queue (book_path, book_id, fmt, priority, status, added_ts, notes) VALUES (?,?,?,?,'queued',?,?)",
            (book_path, book_id, fmt, priority, _iso(None), notes),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def queue_list(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute("SELECT * FROM queue WHERE status = ? ORDER BY priority, added_ts, id", (status,))
        else:
            rows = self.conn.execute("SELECT * FROM queue ORDER BY status, priority, added_ts, id")
        return [dict(r) for r in rows]

    def queue_next(self, allowed_formats: set[str]) -> dict | None:
        for item in self.queue_list("queued"):
            if item["fmt"] in allowed_formats:
                return item
        return None

    def queue_update(self, item_id: int, status: str, notes: str | None = None) -> None:
        col = "started_ts" if status == "running" else ("done_ts" if status in ("done", "failed", "skipped") else None)
        if col:
            self.conn.execute(f"UPDATE queue SET status = ?, notes = COALESCE(?, notes), {col} = ? WHERE id = ?", (status, notes, _iso(None), item_id))
        else:
            self.conn.execute("UPDATE queue SET status = ?, notes = COALESCE(?, notes) WHERE id = ?", (status, notes, item_id))
        self.conn.commit()

    def queue_remove(self, item_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM queue WHERE id = ?", (item_id,))
        self.conn.commit()
        return cur.rowcount > 0
