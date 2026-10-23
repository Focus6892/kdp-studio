"""Where each submitted title stands against KDP's published timelines."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from ..publish.store import PublishStore
from ..watch.models import WatchItem, load_watchlist, save_watchlist

REVIEW_HOURS = 72          # "about 3 business days"
EDIT_WINDOW_HOURS = 72     # title/author edits only within 72h of going live
LOOK_INSIDE_DAYS = 10      # Read Sample appears in 9-10 business days


def _parse(ts: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(ts) if ts else None


def title_rows(store: PublishStore, now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = []
    for t in store.titles():
        submitted = _parse(t.get("submitted_ts"))
        live = _parse(t.get("live_ts"))
        flags: list[str] = []
        hours_in_review = None
        if t["status"] == "in_review" and submitted:
            hours_in_review = (now - submitted).total_seconds() / 3600
            if hours_in_review > REVIEW_HOURS * 1.5:
                flags.append(f"in review for {hours_in_review / 24:.1f} days (expected ~3 business days) — check the Bookshelf / KDP support")
        if t["status"] == "live":
            if not t.get("asin"):
                flags.append("live but no ASIN recorded — run `kdp publish mark ... --asin`")
            if live:
                edit_left = EDIT_WINDOW_HOURS - (now - live).total_seconds() / 3600
                if 0 < edit_left:
                    flags.append(f"title/author still editable for {edit_left:.0f}h")
                if (now - live).days < LOOK_INSIDE_DAYS:
                    flags.append("Look Inside / Read Sample may still be pending")
        if t["status"] == "draft":
            flags.append("draft in KDP — not submitted")
        rows.append({**t, "hours_in_review": round(hours_in_review, 1) if hours_in_review is not None else None, "flags": flags})
    return rows


def mark_title(store: PublishStore, book_id: str, fmt: str, status: str, *, asin: str | None = None, title: str | None = None, watchlist_path: Path | None = None, book_path: str | None = None, now: dt.datetime | None = None) -> dict:
    row = store.upsert_title(book_id, fmt, status, title=title, asin=asin, ts=now)
    store.add_event(book_id, fmt, f"marked_{status}", book_path=book_path, asin=asin, ts=now)
    # A title marked draft/in_review/live exists on KDP even when the human finished it by hand,
    # so make sure the weekly quota counts it (one 'created' / 'submitted' event per title and format).
    have = {e["event"] for e in store.events(book_id) if e["fmt"] == fmt}
    if status in ("draft", "in_review", "live") and "created" not in have:
        store.add_event(book_id, fmt, "created", book_path=book_path, notes="recorded via publish mark", ts=now)
    if status in ("in_review", "live") and "submitted" not in have:
        store.add_event(book_id, fmt, "submitted", book_path=book_path, notes="recorded via publish mark", ts=now)
    if status == "live" and asin and watchlist_path is not None:
        wl = load_watchlist(watchlist_path)
        if wl.add(WatchItem(asin=asin.upper(), label=f"{title or book_id} ({fmt})", ours=True, notes=f"book {book_id}")):
            save_watchlist(watchlist_path, wl)
    return row


def status_markdown(rows: list[dict]) -> str:
    if not rows:
        return "No titles recorded yet (run `kdp publish run` or `kdp publish mark`).\n"
    lines = ["| Book | Format | Status | ASIN | Created | Submitted | Live | Notes |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['book_id']} | {r['fmt']} | {r['status']} | {r.get('asin') or '–'} | {(r.get('created_ts') or '')[:10]} | {(r.get('submitted_ts') or '')[:10]} | {(r.get('live_ts') or '')[:10]} | {'; '.join(r['flags']) or '–'} |"
        )
    return "\n".join(lines) + "\n"
