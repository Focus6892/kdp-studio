"""SQLite store for ASIN snapshots."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from .models import Snapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  asin TEXT NOT NULL,
  source TEXT NOT NULL,
  label TEXT, title TEXT, price REAL, bsr INTEGER, bsr_store TEXT, rating REAL, rating_count INTEGER, review_count INTEGER,
  json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_asin_ts ON snapshots(asin, ts);
"""


class WatchStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def add(self, snaps: list[Snapshot]) -> int:
        cur = self.conn.cursor()
        for s in snaps:
            cur.execute(
                "INSERT INTO snapshots (ts, asin, source, label, title, price, bsr, bsr_store, rating, rating_count, review_count, json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (s.ts.isoformat(), s.asin, s.source, s.label, s.title, s.price, s.bsr, s.bsr_store, s.rating, s.rating_count, s.review_count, s.model_dump_json()),
            )
        self.conn.commit()
        return len(snaps)

    def history(self, asin: str) -> list[Snapshot]:
        rows = self.conn.execute("SELECT json FROM snapshots WHERE asin = ? ORDER BY ts", (asin,))
        return [Snapshot.model_validate_json(r["json"]) for r in rows]

    def asins(self) -> list[str]:
        return [r["asin"] for r in self.conn.execute("SELECT DISTINCT asin FROM snapshots ORDER BY asin")]

    def latest(self, asin: str) -> Snapshot | None:
        row = self.conn.execute("SELECT json FROM snapshots WHERE asin = ? ORDER BY ts DESC LIMIT 1", (asin,)).fetchone()
        return Snapshot.model_validate_json(row["json"]) if row else None

    def at_or_before(self, asin: str, when: dt.datetime) -> Snapshot | None:
        row = self.conn.execute("SELECT json FROM snapshots WHERE asin = ? AND ts <= ? ORDER BY ts DESC LIMIT 1", (asin, when.isoformat())).fetchone()
        return Snapshot.model_validate_json(row["json"]) if row else None

    def earliest(self, asin: str) -> Snapshot | None:
        row = self.conn.execute("SELECT json FROM snapshots WHERE asin = ? ORDER BY ts ASC LIMIT 1", (asin,)).fetchone()
        return Snapshot.model_validate_json(row["json"]) if row else None
