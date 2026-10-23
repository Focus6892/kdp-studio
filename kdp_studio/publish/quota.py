"""KDP weekly title limits: 2 new titles created and 2 submitted per format per week,
window resets Sunday 00:00 UTC (KDP Help 'Create a Book', 2026-10)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .. import specs

FORMATS = ("ebook", "paperback", "hardcover")
WEEKLY_LIMIT = specs.WEEKLY_NEW_TITLES_PER_FORMAT


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def week_window(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    now = (now or utcnow()).astimezone(dt.timezone.utc)
    days_since_sunday = (now.weekday() + 1) % 7  # Monday=0 ... Sunday=6 -> 0
    start = (now - dt.timedelta(days=days_since_sunday)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + dt.timedelta(days=7)


@dataclass
class QuotaStatus:
    fmt: str
    window_start: dt.datetime
    window_end: dt.datetime
    created: int
    submitted: int
    limit: int = WEEKLY_LIMIT
    kdp_blocked: bool = False  # KDP itself showed 'Title creation limit reached' in this window

    @property
    def remaining_created(self) -> int:
        return max(0, self.limit - self.created)

    @property
    def remaining_submitted(self) -> int:
        return max(0, self.limit - self.submitted)

    @property
    def can_start(self) -> bool:
        return self.remaining_created > 0 and self.remaining_submitted > 0

    def as_dict(self) -> dict:
        return {
            "format": self.fmt,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "created": self.created,
            "submitted": self.submitted,
            "limit": self.limit,
            "remaining_created": self.remaining_created,
            "remaining_submitted": self.remaining_submitted,
            "kdp_blocked": self.kdp_blocked,
        }


def quota_status(store, now: dt.datetime | None = None) -> dict[str, QuotaStatus]:
    start, end = week_window(now)
    out: dict[str, QuotaStatus] = {}
    for fmt in FORMATS:
        created = store.count_events("created", fmt, start, end)
        submitted = store.count_events("submitted", fmt, start, end)
        blocked = store.count_events("kdp_limit", fmt, start, end) > 0  # KDP's own dialog was seen: pinned at the limit
        if blocked:
            created = max(created, WEEKLY_LIMIT)
        out[fmt] = QuotaStatus(fmt, start, end, created, submitted, kdp_blocked=blocked)
    return out


def record_external(store, fmt: str, *, created: int = 0, submitted: int = 0, note: str | None = None, now: dt.datetime | None = None) -> None:
    """Titles created or submitted on KDP outside this tool (by hand, or by a run that died) still use the quota."""
    for _ in range(created):
        store.add_event("external", fmt, "created", notes=note or "created on KDP outside kdp-studio", ts=now)
    for _ in range(submitted):
        store.add_event("external", fmt, "submitted", notes=note or "submitted on KDP outside kdp-studio", ts=now)


def record_kdp_limit(store, fmt: str, *, note: str | None = None, now: dt.datetime | None = None) -> None:
    store.add_event("external", fmt, "kdp_limit", notes=note or "KDP dialog: Title creation limit reached", ts=now)


def quota_markdown(statuses: dict[str, QuotaStatus]) -> str:
    any_s = next(iter(statuses.values()))
    lines = [f"KDP weekly window: {any_s.window_start:%Y-%m-%d %H:%M} -> {any_s.window_end:%Y-%m-%d %H:%M} UTC (limit {any_s.limit} per format)", ""]
    lines.append("| Format | Created | Submitted | Remaining (create / submit) |")
    lines.append("|---|---|---|---|")
    for fmt, s in statuses.items():
        lines.append(f"| {fmt} | {s.created} | {s.submitted} | {s.remaining_created} / {s.remaining_submitted} |")
    for fmt, s in statuses.items():
        if s.kdp_blocked:
            lines.append(f"\n{fmt}: KDP reported 'Title creation limit reached' this window - counted as {s.limit}/{s.limit} created until {s.window_end:%Y-%m-%d %H:%M} UTC.")
    lines.append("\nKDP counts every title you create (drafts included). Record ones made by hand with `kdp publish quota --add-created <format>`.")
    return "\n".join(lines) + "\n"
