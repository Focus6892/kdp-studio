"""Snapshot sources for the watchlist: fixture (offline drift), csv, creators (GetItems), apify (bookUrls)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import random
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

from ..niche.sources.apify import ACTOR_ID, API as APIFY_API, record_to_observation
from ..niche.sources.csv_source import load_rows, rows_to_observations
from .models import Snapshot, Watchlist


class SnapshotSource(Protocol):
    name: str

    def fetch(self, wl: Watchlist) -> list[Snapshot]: ...


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class FixtureWatchSource:
    """Deterministic daily drift per ASIN so reports and alerts can be tested offline."""

    name = "fixture"

    def __init__(self, day: int = 0, seed: int = 1, now: dt.datetime | None = None):
        self.day, self.seed = day, seed
        self.now = now or _now()

    def fetch(self, wl: Watchlist) -> list[Snapshot]:
        out = []
        for item in wl.items:
            rng = random.Random(hashlib.sha256(f"{self.seed}:{item.asin}".encode()).hexdigest())
            base_bsr = int(10 ** rng.uniform(3.8, 5.3))
            trend = rng.choice([-0.06, -0.03, 0.0, 0.02, 0.05])  # daily BSR drift (negative = improving)
            base_price = rng.choice([6.99, 7.99, 8.99, 9.99, 12.99])
            price = base_price - (2.0 if (self.day >= 2 and rng.random() < 0.5) else 0.0)
            base_rc = int(10 ** rng.uniform(1.2, 3.0))
            velocity = rng.choice([0.2, 0.8, 2.0, 5.0])
            out.append(
                Snapshot(
                    ts=self.now + dt.timedelta(days=self.day),
                    asin=item.asin,
                    source=self.name,
                    label=item.label,
                    title=f"{item.label or item.asin} (fixture)",
                    price=round(price, 2),
                    bsr=max(1, int(base_bsr * math.exp(trend * self.day))),
                    bsr_store="Books",
                    rating=round(rng.uniform(4.2, 4.8), 1),
                    rating_count=int(base_rc + velocity * self.day),
                    review_count=int((base_rc + velocity * self.day) * 0.3),
                )
            )
        return out


class CsvWatchSource:
    name = "csv"

    def __init__(self, path: Path):
        self.path = path

    def fetch(self, wl: Watchlist) -> list[Snapshot]:
        obs = rows_to_observations(load_rows(self.path), source="csv", default_keyword="watch")
        now = _now()
        labels = {i.asin: i.label for i in wl.items}
        return [
            Snapshot(ts=o.observed_at or now, asin=o.asin, source="csv", label=labels.get(o.asin), title=o.title, price=o.price, bsr=o.bsr, bsr_store=o.bsr_store, rating=o.rating, rating_count=o.rating_count, review_count=o.review_count, cover_url=o.cover_url, url=o.url)
            for o in obs
            if not wl.items or o.asin in labels
        ]


class CreatorsWatchSource:
    """Amazon Creators API getItems, 10 ASINs per call (no rating counts available)."""

    name = "creators"

    def __init__(self, client=None, marketplace: str = "www.amazon.com"):
        from ..niche.sources.creators import CreatorsClient

        self.client = client or CreatorsClient(marketplace=marketplace)

    def fetch(self, wl: Watchlist) -> list[Snapshot]:
        from ..niche.sources.creators import item_to_observation

        now = _now()
        labels = {i.asin: i.label for i in wl.items}
        asins = [i.asin for i in wl.items]
        out: list[Snapshot] = []
        for i in range(0, len(asins), 10):
            data = self.client.get_items(asins[i : i + 10])
            for item in (data.get("itemsResult") or {}).get("items") or []:
                o = item_to_observation(item, "watch", 0)
                if o:
                    out.append(Snapshot(ts=now, asin=o.asin, source=self.name, label=labels.get(o.asin), title=o.title, price=o.price, bsr=o.bsr, bsr_store=o.bsr_store, cover_url=o.cover_url, url=o.url))
        return out


class ApifyWatchSource:
    """Apify kdp-book-niche-analyzer with bookUrls (Kindle Store data incl. rating counts)."""

    name = "apify"

    def __init__(self, token: str | None = None, timeout_s: int = 600):
        self.token = token or os.environ.get("APIFY_TOKEN")
        if not self.token:
            raise RuntimeError("APIFY_TOKEN is not set")
        self.timeout_s = timeout_s

    def fetch(self, wl: Watchlist) -> list[Snapshot]:
        now = _now()
        labels = {i.asin: i.label for i in wl.items}
        body = {
            "keywords": [],
            "bookUrls": [f"https://www.{wl.marketplace}/dp/{i.asin}" for i in wl.items],
            "includeAutocompleteSuggestions": False,
            "analyzeAutocompleteSuggestions": False,
            "maxBooksPerKeyword": 1,
            "includeNicheRows": False,
            "monitorChanges": False,
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyCountry": "US"},
        }
        q = urllib.parse.urlencode({"token": self.token, "timeout": self.timeout_s, "format": "json", "clean": "true"})
        req = urllib.request.Request(f"{APIFY_API}/acts/{ACTOR_ID}/run-sync-get-dataset-items?{q}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s + 30) as resp:  # noqa: S310 - fixed https endpoint
            items = json.load(resp)
        out: list[Snapshot] = []
        for rec in items:
            o = record_to_observation(rec)
            if o and o.asin in labels:
                out.append(Snapshot(ts=now, asin=o.asin, source=self.name, label=labels.get(o.asin), title=o.title, price=o.price, bsr=o.bsr, bsr_store=o.bsr_store, rating=o.rating, rating_count=o.rating_count, review_count=o.review_count, cover_url=o.cover_url, url=o.url))
        return out


def make_watch_source(name: str, *, csv_path: Path | None = None, day: int = 0, seed: int = 1, now: dt.datetime | None = None) -> SnapshotSource:
    if name == "fixture":
        return FixtureWatchSource(day=day, seed=seed, now=now)
    if name == "csv":
        if csv_path is None:
            raise ValueError("--csv PATH is required for the csv source")
        return CsvWatchSource(csv_path)
    if name == "creators":
        return CreatorsWatchSource()
    if name == "apify":
        return ApifyWatchSource()
    raise ValueError(f"Unknown watch source '{name}' (fixture | csv | creators | apify)")
