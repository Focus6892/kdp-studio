"""Write candidates.json and candidates.md for human review."""

from __future__ import annotations

from pathlib import Path

from ..util import write_json
from .brief import Brief
from .score import ScoredCandidate


def candidates_markdown(scored: list[ScoredCandidate], brief: Brief) -> str:
    lines = [f"# Metadata candidates — {brief.niche_keyword}", ""]
    lines.append(f"Audience: {brief.audience} · book type: {brief.book_type} · {len(scored)} candidates, best first.")
    lines.append("")
    lines.append("| # | Score | Errors | Warnings | Title | Subtitle |")
    lines.append("|---|---|---|---|---|---|")
    for i, sc in enumerate(scored, start=1):
        lines.append(f"| {i} | **{sc.score:.0f}** | {len(sc.findings.errors)} | {len(sc.findings.warnings)} | {sc.candidate.title} | {sc.candidate.subtitle or ''} |")
    lines.append("")
    for i, sc in enumerate(scored, start=1):
        c = sc.candidate
        lines.append(f"## {i}. {c.title} — score {sc.score:.0f}")
        lines.append("")
        lines.append(f"**Subtitle:** {c.subtitle or '—'}  ")
        lines.append(f"**Title+subtitle length:** {len(c.title) + (len(c.subtitle) + 2 if c.subtitle else 0)} / 200  ")
        lines.append(f"**Keywords ({len(c.keywords)}):** " + " · ".join(c.keywords) + "  ")
        lines.append(f"**Categories:** " + " | ".join(c.categories) + "  ")
        if c.reading_age:
            lines.append(f"**Reading age:** {c.reading_age.min}-{c.reading_age.max}  ")
        if c.series_name:
            lines.append(f"**Series:** {c.series_name}  ")
        lines.append("")
        lines.append("**Description (HTML):**")
        lines.append("")
        lines.append("```html")
        lines.append(c.description_html.strip())
        lines.append("```")
        if c.a_plus_headline or c.a_plus_body:
            lines.append("")
            lines.append(f"**A+ content:** {c.a_plus_headline or ''} — {c.a_plus_body or ''}")
        lines.append("")
        lines.append(f"**Rationale:** {c.rationale}")
        lines.append("")
        lines.append("**Rubric:** " + ", ".join(f"{k} {v:.0f}" for k, v in sc.breakdown.items()))
        if len(sc.findings):
            lines.append("")
            lines.append("**Checks:**")
            for f in sc.findings:
                lines.append(f"- `{f.level.upper()}` {f.code}: {f.message}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_candidates(scored: list[ScoredCandidate], brief: Brief, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    js = out_dir / "candidates.json"
    write_json(js, {"brief": brief.model_dump(mode="json"), "candidates": [sc.to_dict() for sc in scored]})
    md = out_dir / "candidates.md"
    md.write_text(candidates_markdown(scored, brief), encoding="utf-8")
    return {"json": js, "markdown": md}
