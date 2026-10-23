"""SQLite history of niche runs so week-over-week trends can be compared."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from .models import BookObservation, NicheRun, NicheSummary

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  source TEXT NOT NULL,
  book_type TEXT NOT NULL,
  topics TEXT NOT NULL,
  keywords TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
  run_id INTEGER NOT NULL REFERENCES runs(id),
  keyword TEXT NOT NULL,
  opportunity REAL, demand REAL, competition REAL, monetization REAL, confidence REAL, label TEXT,
  median_bsr REAL, median_price REAL, median_rating_count REAL, n_books INTEGER,
  json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
  run_id INTEGER NOT NULL REFERENCES runs(id),
  keyword TEXT NOT NULL,
  asin TEXT NOT NULL,
  title TEXT, bsr INTEGER, price REAL, rating_count INTEGER, pub_date TEXT, publisher TEXT, position INTEGER,
  json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_summaries_keyword ON summaries(keyword, run_id);
CREATE INDEX IF NOT EXISTS idx_observations_asin ON observations(asin, run_id);
"""


class NicheStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def save_run(self, run: NicheRun, observations: dict[str, list[BookObservation]]) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO runs (ts, source, book_type, topics, keywords) VALUES (?, ?, ?, ?, ?)",
            (run.ts.isoformat(), run.source, run.book_type, json.dumps(run.topics), json.dumps(run.keywords)),
        )
        run_id = int(cur.lastrowid)
        for s in run.summaries:
            cur.execute(
                "INSERT INTO summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, s.keyword, s.scores.opportunity, s.scores.demand, s.scores.competition, s.scores.monetization,
                    s.scores.confidence, s.scores.label, s.median_bsr, s.median_price, s.median_rating_count, s.n_books,
                    s.model_dump_json(),
                ),
            )
        for keyword, books in observations.items():
            for b in books:
                cur.execute(
                    "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, keyword, b.asin, b.title, b.bsr, b.price, b.rating_count, b.pub_date.isoformat() if b.pub_date else None, b.publisher, b.position, b.model_dump_json()),
                )
        self.conn.commit()
        run.run_id = run_id
        return run_id

    def runs(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM runs ORDER BY id"))

    def latest_summaries(self) -> list[NicheSummary]:
        rows = self.conn.execute(
            "SELECT s.json FROM summaries s JOIN (SELECT keyword, MAX(run_id) AS run_id FROM summaries GROUP BY keyword) m "
            "ON s.keyword = m.keyword AND s.run_id = m.run_id ORDER BY s.opportunity DESC"
        )
        return [NicheSummary.model_validate_json(r["json"]) for r in rows]

    def latest_summary(self, keyword: str) -> NicheSummary | None:
        row = self.conn.execute("SELECT json FROM summaries WHERE keyword = ? ORDER BY run_id DESC LIMIT 1", (keyword,)).fetchone()
        return NicheSummary.model_validate_json(row["json"]) if row else None

    def history(self, keyword: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT r.ts, s.opportunity, s.median_bsr, s.median_price, s.median_rating_count, s.n_books "
            "FROM summaries s JOIN runs r ON r.id = s.run_id WHERE s.keyword = ? ORDER BY r.id",
            (keyword,),
        )
        return [dict(r) for r in rows]

    def trends(self) -> list[dict]:
        """Latest vs previous run for every keyword that has at least two observations."""
        out = []
        keywords = [r["keyword"] for r in self.conn.execute("SELECT DISTINCT keyword FROM summaries")]
        for k in keywords:
            h = self.history(k)
            if len(h) < 2:
                continue
            prev, last = h[-2], h[-1]
            out.append({
                "keyword": k,
                "runs": len(h),
                "opportunity": last["opportunity"],
                "delta_opportunity": round((last["opportunity"] or 0) - (prev["opportunity"] or 0), 1),
                "median_bsr": last["median_bsr"],
                "delta_median_bsr": (last["median_bsr"] - prev["median_bsr"]) if last["median_bsr"] and prev["median_bsr"] else None,
                "median_price": last["median_price"],
                "last_ts": last["ts"],
            })
        return sorted(out, key=lambda d: -(d["delta_opportunity"] or 0))

    def asin_history(self, asin: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT r.ts, o.keyword, o.bsr, o.price, o.rating_count, o.position FROM observations o JOIN runs r ON r.id = o.run_id WHERE o.asin = ? ORDER BY r.id",
            (asin,),
        )
        return [dict(r) for r in rows]


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)
