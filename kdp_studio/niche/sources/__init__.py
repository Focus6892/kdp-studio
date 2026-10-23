"""Book data sources: fixture (offline), csv (tool exports), apify (scraper actor), creators (Amazon Creators API)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import BookObservation


class BookSource(Protocol):
    name: str

    def search(self, keyword: str, max_books: int) -> list[BookObservation]: ...


def make_source(name: str, *, csv_path: Path | None = None, base_dir: Path | None = None, **options) -> BookSource:
    if name == "fixture":
        from .fixture import FixtureSource

        return FixtureSource(seed=int(options.get("seed", 1)))
    if name == "csv":
        from .csv_source import CsvSource

        if csv_path is None:
            raise ValueError("--csv PATH is required for the csv source")
        return CsvSource(csv_path if csv_path.is_absolute() else (base_dir or Path.cwd()) / csv_path, default_keyword=options.get("default_keyword"))
    if name == "apify":
        from .apify import ApifySource

        return ApifySource(token=options.get("token"), store=options.get("store", "Kindle Store"))
    if name == "creators":
        from .creators import CreatorsSource

        return CreatorsSource(search_index=options.get("search_index", "Books"), marketplace=options.get("marketplace", "www.amazon.com"))
    raise ValueError(f"Unknown source '{name}' (fixture | csv | apify | creators)")
