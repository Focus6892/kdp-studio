"""Write niche_report.md, niches.csv and run.json for a NicheRun."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from ..util import write_json
from .models import NicheRun, NicheSummary


def _fmt(v, nd: int = 0, pct: bool = False) -> str:
    if v is None:
        return "–"
    if pct:
        return f"{v:.0%}"
    return f"{v:,.{nd}f}"


def summary_table(summaries: list[NicheSummary]) -> str:
    head = "| # | Keyword | Opp. | Label | Demand | Comp. | Money | Conf. | Median BSR | Median price | Median ratings | Indie | <1y | n |\n"
    head += "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    rows = []
    for i, s in enumerate(summaries, start=1):
        sc = s.scores
        rows.append(
            f"| {i} | {s.keyword} | **{sc.opportunity:.0f}** | {sc.label} | {sc.demand:.0f} | {sc.competition:.0f} | {sc.monetization:.0f} | {sc.confidence:.0f} "
            f"| {_fmt(s.median_bsr)} | {('$' + _fmt(s.median_price, 2)) if s.median_price is not None else '–'} | {_fmt(s.median_rating_count)} "
            f"| {_fmt(s.share_indie, pct=True)} | {_fmt(s.share_fresh_365, pct=True)} | {s.n_books} |"
        )
    return head + "\n".join(rows) + "\n"


def run_markdown(run: NicheRun) -> str:
    ranked = run.ranked()
    lines = [f"# Niche report — {run.ts:%Y-%m-%d %H:%M} UTC", ""]
    lines.append(f"Source: **{run.source}** · book type: **{run.book_type}** · topics: {', '.join(run.topics)} · keywords scored: {len(ranked)}")
    lines.append("")
    lines.append("Scores compare niches with each other (demand 0–40 from median BSR of the top 10, competition ease 0–40, monetization 0–20). BSR→sales figures are relative estimates only.")
    lines.append("")
    lines.append(summary_table(ranked))
    for s in ranked:
        lines.append(f"## {s.keyword} — {s.scores.opportunity:.0f} ({s.scores.label})")
        lines.append("")
        lines.append(f"- Books: {s.n_books} ({s.n_with_bsr} with BSR, store: {s.bsr_store or 'n/a'}) · best BSR {_fmt(s.best_bsr)} · median pages {_fmt(s.median_pages)}")
        lines.append(f"- Price: median ${_fmt(s.median_price, 2)} · {_fmt(s.share_price_ge_threshold, pct=True)} priced at/above $9.99")
        lines.append(f"- Reviews: median {_fmt(s.median_rating_count)} · {_fmt(s.share_heavy_reviews, pct=True)} with 1000+ · {_fmt(s.share_low_reviews, pct=True)} with ≤20")
        lines.append(f"- Market: {_fmt(s.share_indie, pct=True)} independent publishers · {_fmt(s.share_fresh_365, pct=True)} published in the last 12 months · top-3 concentration {_fmt(s.concentration_top3, pct=True)}")
        if s.flags:
            lines.append("- Flags: " + "; ".join(s.flags))
        if s.top_phrases:
            lines.append("- Common title phrases: " + ", ".join(f"{p} ({c})" for p, c in s.top_phrases[:12]))
        if s.top_titles:
            lines.append("- Top titles:")
            lines.extend(f"  - {t}" for t in s.top_titles[:8])
        cards = run.concepts.get(s.keyword) or []
        if cards:
            lines.append("")
            lines.append("**Concept cards**")
            lines.append("")
            for i, c in enumerate(cards, start=1):
                lines.append(f"{i}. **{c.title_idea}** — {c.angle}. Audience: {c.audience}. Differentiation: {c.differentiation} Why it can rank: {c.why_it_can_rank} Risks: {c.risks} Keywords: {', '.join(c.keywords)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_run(run: NicheRun, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = run.ts.strftime("%Y%m%d-%H%M%S")
    md = out_dir / f"niche_report_{stamp}.md"
    md.write_text(run_markdown(run), encoding="utf-8")
    (out_dir / "niche_report_latest.md").write_text(run_markdown(run), encoding="utf-8")
    js = out_dir / f"run_{stamp}.json"
    write_json(js, run.model_dump(mode="json"))
    csv_path = out_dir / f"niches_{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["keyword", "opportunity", "label", "demand", "competition", "monetization", "confidence", "median_bsr", "median_price", "median_rating_count", "share_indie", "share_fresh_365", "n_books", "flags"])
        for s in run.ranked():
            w.writerow([s.keyword, s.scores.opportunity, s.scores.label, s.scores.demand, s.scores.competition, s.scores.monetization, s.scores.confidence, s.median_bsr, s.median_price, s.median_rating_count, s.share_indie, s.share_fresh_365, s.n_books, "; ".join(s.flags)])
    return {"markdown": md, "json": js, "csv": csv_path, "latest": out_dir / "niche_report_latest.md"}


def trends_markdown(trends: list[dict]) -> str:
    if not trends:
        return "No keyword has two or more runs yet.\n"
    lines = ["| Keyword | Runs | Opp. | Δ opp. | Median BSR | Δ BSR | Median price | Last run |", "|---|---|---|---|---|---|---|---|"]
    for t in trends:
        d_bsr = t["delta_median_bsr"]
        delta_bsr = f"{d_bsr:+,.0f}" if d_bsr is not None else "–"
        price = ("$" + _fmt(t["median_price"], 2)) if t["median_price"] else "–"
        lines.append(
            f"| {t['keyword']} | {t['runs']} | {_fmt(t['opportunity'])} | {t['delta_opportunity']:+.1f} | {_fmt(t['median_bsr'])} | "
            f"{delta_bsr} | {price} | {t['last_ts'][:16]} |"
        )
    return "\n".join(lines) + "\n"


def today_dir(base: Path) -> Path:
    return base / dt.date.today().isoformat()
