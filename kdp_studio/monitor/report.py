"""Combined post-publish report: title status + own ASINs from competitor-watch + ads + sales."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from ..publish.quota import quota_markdown, quota_status
from ..publish.store import PublishStore
from .ads import ads_markdown
from .sales import sales_markdown
from .status import status_markdown, title_rows


def own_asin_rows(watch_db: Path | None, watchlist_path: Path | None, now: dt.datetime | None = None) -> list[dict]:
    if not watch_db or not watch_db.is_file() or not watchlist_path or not watchlist_path.is_file():
        return []
    from ..watch.models import load_watchlist
    from ..watch.report import build_report
    from ..watch.store import WatchStore

    wl = load_watchlist(watchlist_path)
    ours = [i for i in wl.items if i.ours]
    if not ours:
        return []
    store = WatchStore(watch_db)
    try:
        rep = build_report(store, wl, now)
    finally:
        store.close()
    out = []
    for r in rep.rows:
        if not r.ours:
            continue
        out.append({"asin": r.asin, "label": r.label, "bsr": r.latest.bsr, "bsr_delta_7d": r.bsr_delta_week, "price": r.latest.price, "rating": r.latest.rating, "rating_count": r.latest.rating_count, "review_velocity": r.review_velocity, "alerts": r.alerts, "ts": r.latest.ts.isoformat()})
    return out


def monitor_markdown(store: PublishStore, *, own_rows: list[dict] | None = None, ads_summary: dict | None = None, sales_summary: dict | None = None, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    lines = [f"# Post-publish monitor — {now:%Y-%m-%d %H:%M} UTC", ""]
    lines.append("## Titles")
    lines.append("")
    lines.append(status_markdown(title_rows(store, now)))
    lines.append("## Weekly quota")
    lines.append("")
    lines.append(quota_markdown(quota_status(store, now)))
    if own_rows:
        lines.append("## Our ASINs (from competitor-watch)")
        lines.append("")
        lines.append("| ASIN | Label | BSR | Δ 7d | Price | Rating | Ratings | +/day | Alerts |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in own_rows:
            d = f"{r['bsr_delta_7d']:+.0%}" if r["bsr_delta_7d"] is not None else "–"
            lines.append(f"| {r['asin']} | {r['label'] or ''} | {r['bsr'] or '–'} | {d} | {('$' + format(r['price'], '.2f')) if r['price'] else '–'} | {r['rating'] or '–'} | {r['rating_count'] or '–'} | {format(r['review_velocity'], '.1f') if r['review_velocity'] is not None else '–'} | {'; '.join(r['alerts']) or '–'} |")
        lines.append("")
    if ads_summary:
        lines.append(ads_markdown(ads_summary))
    if sales_summary:
        lines.append(sales_markdown(sales_summary))
    return "\n".join(lines)


def write_monitor_report(text: str, out_dir: Path, now: dt.datetime | None = None) -> dict[str, Path]:
    now = now or dt.datetime.now(dt.timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = out_dir / f"monitor_report_{now:%Y%m%d-%H%M%S}.md"
    stamped.write_text(text, encoding="utf-8")
    latest = out_dir / "monitor_report_latest.md"
    latest.write_text(text, encoding="utf-8")
    return {"markdown": stamped, "latest": latest}
