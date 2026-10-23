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
        }


def quota_status(store, now: dt.datetime | None = None) -> dict[str, QuotaStatus]:
    start, end = week_window(now)
    return {
        fmt: QuotaStatus(fmt, start, end, store.count_events("created", fmt, start, end), store.count_events("submitted", fmt, start, end))
        for fmt in FORMATS
    }


def quota_markdown(statuses: dict[str, QuotaStatus]) -> str:
    any_s = next(iter(statuses.values()))
    lines = [f"KDP weekly window: {any_s.window_start:%Y-%m-%d %H:%M} -> {any_s.window_end:%Y-%m-%d %H:%M} UTC (limit {any_s.limit} per format)", ""]
    lines.append("| Format | Created | Submitted | Remaining (create / submit) |")
    lines.append("|---|---|---|---|")
    for fmt, s in statuses.items():
        lines.append(f"| {fmt} | {s.created} | {s.submitted} | {s.remaining_created} / {s.remaining_submitted} |")
    return "\n".join(lines) + "\n"
