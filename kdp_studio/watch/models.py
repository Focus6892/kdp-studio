"""Watchlist and snapshot models."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class WatchItem(BaseModel):
    asin: str = Field(min_length=10, max_length=10)
    label: str | None = None
    niche: str | None = None
    ours: bool = False
    notes: str | None = None


class Watchlist(BaseModel):
    marketplace: str = "amazon.com"
    items: list[WatchItem] = Field(default_factory=list)

    def get(self, asin: str) -> WatchItem | None:
        return next((i for i in self.items if i.asin == asin), None)

    def add(self, item: WatchItem) -> bool:
        if self.get(item.asin):
            return False
        self.items.append(item)
        return True


def load_watchlist(path: Path) -> Watchlist:
    if not path.is_file():
        return Watchlist()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Watchlist.model_validate(data)


def save_watchlist(path: Path, wl: Watchlist) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(wl.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")


class Snapshot(BaseModel):
    ts: dt.datetime
    asin: str
    source: str
    label: str | None = None
    title: str | None = None
    price: float | None = None
    bsr: int | None = None
    bsr_store: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    review_count: int | None = None
    cover_url: str | None = None
    url: str | None = None
