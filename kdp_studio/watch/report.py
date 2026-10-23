"""Competitor report: latest snapshot vs 7/30 days ago, alerts, markdown + CSV."""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from ..niche.scoring import est_daily_sales
from .models import Snapshot, Watchlist
from .store import WatchStore

PRICE_DROP_ALERT = 0.15
BSR_IMPROVE_ALERT = 0.30
REVIEW_VELOCITY_ALERT = 3.0  # ratings per day


@dataclass
class WatchRow:
    asin: str
    label: str | None
    ours: bool
    title: str | None
    latest: Snapshot
    week_ago: Snapshot | None
    month_ago: Snapshot | None
    snapshots: int
    first_ts: dt.datetime
    alerts: list[str] = field(default_factory=list)

    @property
    def bsr_delta_week(self) -> float | None:
        if self.latest.bsr and self.week_ago and self.week_ago.bsr:
            return (self.latest.bsr - self.week_ago.bsr) / self.week_ago.bsr
        return None

    @property
    def price_delta_week(self) -> float | None:
        if self.latest.price and self.week_ago and self.week_ago.price:
            return (self.latest.price - self.week_ago.price) / self.week_ago.price
        return None

    @property
    def review_velocity(self) -> float | None:
        ref = self.week_ago or self.month_ago
        if ref is None or ref.rating_count is None or self.latest.rating_count is None:
            return None
        days = max((self.latest.ts - ref.ts).total_seconds() / 86400, 1.0)
        return (self.latest.rating_count - ref.rating_count) / days

    @property
    def est_sales_day(self) -> float | None:
        return est_daily_sales(self.latest.bsr, self.latest.bsr_store or "Books")


@dataclass
class WatchReport:
    generated: dt.datetime
    rows: list[WatchRow]

    @property
    def alerts(self) -> list[str]:
        return [f"{r.label or r.asin}: {a}" for r in self.rows for a in r.alerts]


def build_report(store: WatchStore, wl: Watchlist, now: dt.datetime | None = None) -> WatchReport:
    now = now or dt.datetime.now(dt.timezone.utc)
    rows: list[WatchRow] = []
    asins = [i.asin for i in wl.items] or store.asins()
    for asin in asins:
        latest = store.latest(asin)
        if latest is None:
            continue
        ref = latest.ts
        week = store.at_or_before(asin, ref - dt.timedelta(days=7))
        month = store.at_or_before(asin, ref - dt.timedelta(days=30))
        first = store.earliest(asin)
        hist = store.history(asin)
        if week is None and len(hist) > 1:
            week = hist[0] if hist[0].ts < latest.ts else None  # fall back to the earliest snapshot
        item = wl.get(asin)
        row = WatchRow(asin, (item.label if item else latest.label), bool(item and item.ours), latest.title, latest, week, month, len(hist), first.ts if first else latest.ts)
        pd = row.price_delta_week
        if pd is not None and pd <= -PRICE_DROP_ALERT:
            row.alerts.append(f"price cut {pd:.0%} (${week.price:.2f} -> ${latest.price:.2f})")  # type: ignore[union-attr]
        bd = row.bsr_delta_week
        if bd is not None and bd <= -BSR_IMPROVE_ALERT:
            row.alerts.append(f"BSR improved {abs(bd):.0%} ({week.bsr:,} -> {latest.bsr:,})")  # type: ignore[union-attr]
        if bd is not None and bd >= 0.5:
            row.alerts.append(f"BSR worsened {bd:.0%} ({week.bsr:,} -> {latest.bsr:,})")  # type: ignore[union-attr]
        rv = row.review_velocity
        if rv is not None and rv >= REVIEW_VELOCITY_ALERT:
            row.alerts.append(f"gaining {rv:.1f} ratings/day")
        rows.append(row)
    rows.sort(key=lambda r: (r.latest.bsr or 10**9))
    return WatchReport(now, rows)


def _fmt(v, nd=0, pct=False, money=False):
    if v is None:
        return "–"
    if pct:
        return f"{v:+.0%}"
    if money:
        return f"${v:,.2f}"
    return f"{v:,.{nd}f}"


def report_markdown(rep: WatchReport) -> str:
    lines = [f"# Competitor watch — {rep.generated:%Y-%m-%d %H:%M} UTC", ""]
    if rep.alerts:
        lines.append("## Alerts")
        lines.extend(f"- {a}" for a in rep.alerts)
        lines.append("")
    lines.append("| ASIN | Label | BSR | Δ BSR 7d | Est. sales/day* | Price | Δ price 7d | Ratings | +/day | Snapshots | Since |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rep.rows:
        s = r.latest
        label = (r.label or "") + (" (ours)" if r.ours else "")
        lines.append(
            f"| {r.asin} | {label} | {_fmt(s.bsr)} | {_fmt(r.bsr_delta_week, pct=True)} | {_fmt(r.est_sales_day, 1)} | {_fmt(s.price, money=True)} | "
            f"{_fmt(r.price_delta_week, pct=True)} | {_fmt(s.rating_count)} | {_fmt(r.review_velocity, 1)} | {r.snapshots} | {r.first_ts:%Y-%m-%d} |"
        )
    lines.append("")
    lines.append("*Relative estimate from BSR; public estimators disagree by several times. Use it to compare rows, not as revenue.")
    lines.append("")
    for r in rep.rows:
        lines.append(f"## {r.label or r.asin} — {r.asin}")
        lines.append("")
        if r.title:
            lines.append(f"- Title: {r.title}")
        lines.append(f"- Latest ({r.latest.ts:%Y-%m-%d}): BSR {_fmt(r.latest.bsr)} ({r.latest.bsr_store or 'n/a'}), price {_fmt(r.latest.price, money=True)}, rating {_fmt(r.latest.rating, 1)} ({_fmt(r.latest.rating_count)} ratings)")
        if r.week_ago:
            lines.append(f"- 7 days ago ({r.week_ago.ts:%Y-%m-%d}): BSR {_fmt(r.week_ago.bsr)}, price {_fmt(r.week_ago.price, money=True)}, {_fmt(r.week_ago.rating_count)} ratings")
        if r.month_ago:
            lines.append(f"- 30 days ago ({r.month_ago.ts:%Y-%m-%d}): BSR {_fmt(r.month_ago.bsr)}, price {_fmt(r.month_ago.price, money=True)}, {_fmt(r.month_ago.rating_count)} ratings")
        if r.alerts:
            lines.append("- Alerts: " + "; ".join(r.alerts))
        lines.append("")
    return "\n".join(lines) + "\n"


def write_report(rep: WatchReport, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = rep.generated.strftime("%Y%m%d-%H%M%S")
    md = out_dir / f"watch_report_{stamp}.md"
    md.write_text(report_markdown(rep), encoding="utf-8")
    latest = out_dir / "watch_report_latest.md"
    latest.write_text(report_markdown(rep), encoding="utf-8")
    csv_path = out_dir / f"watch_{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["asin", "label", "ours", "ts", "bsr", "bsr_delta_7d", "est_sales_day", "price", "price_delta_7d", "rating", "rating_count", "review_velocity", "alerts"])
        for r in rep.rows:
            s = r.latest
            w.writerow([r.asin, r.label, r.ours, s.ts.isoformat(), s.bsr, r.bsr_delta_week, r.est_sales_day, s.price, r.price_delta_week, s.rating, s.rating_count, r.review_velocity, "; ".join(r.alerts)])
    return {"markdown": md, "latest": latest, "csv": csv_path}
