"""competitor-watch orchestration."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from .models import Snapshot, Watchlist, load_watchlist
from .report import WatchReport, build_report, write_report
from .sources import make_watch_source
from .store import WatchStore


def take_snapshot(watchlist_path: Path, source: str, db_path: Path, *, csv_path: Path | None = None, day: int = 0, seed: int = 1, now: dt.datetime | None = None) -> list[Snapshot]:
    wl = load_watchlist(watchlist_path)
    if not wl.items and source != "csv":
        raise ValueError(f"Watchlist {watchlist_path} has no items; add some with `kdp watch add`")
    src = make_watch_source(source, csv_path=csv_path, day=day, seed=seed, now=now)
    snaps = src.fetch(wl)
    store = WatchStore(db_path)
    try:
        store.add(snaps)
    finally:
        store.close()
    return snaps


def make_report(watchlist_path: Path, db_path: Path, out_dir: Path, now: dt.datetime | None = None) -> tuple[WatchReport, dict[str, Path]]:
    wl: Watchlist = load_watchlist(watchlist_path)
    store = WatchStore(db_path)
    try:
        rep = build_report(store, wl, now)
    finally:
        store.close()
    return rep, write_report(rep, out_dir)
