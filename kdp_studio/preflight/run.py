"""Run every preflight check and write preflight.json / preflight.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .. import specs
from ..findings import FindingList
from ..metadata_rules import validate_book_metadata
from ..pricing import price_report, royalty
from ..schema import Book
from ..util import write_json
from .pdf_checks import check_cover_pdf, check_ebook_cover, check_interior_pdf


@dataclass
class PreflightReport:
    book_id: str
    pages: int | None
    findings: FindingList
    summary: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.findings.ok

    def to_dict(self) -> dict:
        return {
            "book_id": self.book_id,
            "pages": self.pages,
            "ok": self.ok,
            "errors": len(self.findings.errors),
            "warnings": len(self.findings.warnings),
            "summary": self.summary,
            "findings": [x.as_dict() for x in self.findings],
        }

    def to_markdown(self) -> str:
        lines = [f"# Preflight — {self.book_id}", ""]
        lines.append(f"**Result:** {'PASS' if self.ok else 'FAIL'} — {len(self.findings.errors)} error(s), {len(self.findings.warnings)} warning(s)")
        lines.append("")
        if self.summary:
            lines.append("## Summary")
            for k, v in self.summary.items():
                if isinstance(v, dict):
                    lines.append(f"- **{k}**")
                    for kk, vv in v.items():
                        lines.append(f"  - {kk}: {vv}")
                else:
                    lines.append(f"- **{k}:** {v}")
            lines.append("")
        lines.append("## Findings")
        if not len(self.findings):
            lines.append("- none")
        for x in self.findings:
            lines.append(f"- `{x.level.upper()}` **{x.code}** — {x.message}" + (f" _({x.where})_" if x.where else ""))
        return "\n".join(lines) + "\n"


def check_print_spec(book: Book, pages: int | None) -> FindingList:
    f = FindingList()
    trim = book.print_.trim_size
    try:
        lo, hi = specs.page_range(book.print_.trim, book.print_.paper)
    except ValueError as exc:
        f.error("print.paper_unavailable", str(exc), "print.paper")
        return f
    if pages is not None:
        if pages < lo or pages > hi:
            f.error("print.page_range", f"{pages} pages is outside {lo}-{hi} for {trim.key}/{book.print_.paper}.", "print")
        if pages % 2:
            f.warning("print.odd_pages", f"{pages} pages is odd; KDP will add a blank page.", "print")
    if "hardcover" in book.formats:
        if trim.key not in specs.HARDCOVER_TRIMS:
            f.error("hardcover.trim", f"Trim {trim.key} is not offered for hardcover ({', '.join(specs.HARDCOVER_TRIMS)}).", "formats")
        if pages is not None and not (specs.HARDCOVER_PAGE_RANGE[0] <= pages <= specs.HARDCOVER_PAGE_RANGE[1]):
            f.error("hardcover.pages", f"Hardcover needs {specs.HARDCOVER_PAGE_RANGE[0]}-{specs.HARDCOVER_PAGE_RANGE[1]} pages.", "formats")
        f.info("hardcover.not_rendered", "Hardcover cover rendering is not implemented in Phase 0; use KDP's cover calculator for the case-laminate wrap.", "formats")
    if book.print_.isbn == "own" and not book.print_.isbn_number:
        f.error("isbn.missing", "print.isbn is 'own' but no isbn_number given.", "print.isbn")
    if book.type == "coloring" and book.print_.paper in ("standard_color", "premium_color"):
        f.info("print.color_paper", "Color paper on a coloring book multiplies printing cost; black ink on white paper is the usual choice.", "print.paper")
    return f


def check_pricing(book: Book, pages: int | None) -> tuple[FindingList, dict]:
    f = FindingList()
    if pages is None:
        f.info("pricing.skipped", "Page count unknown; pricing check skipped.", "pricing")
        return f, {}
    try:
        rep = price_report(book.print_.trim, book.print_.paper, pages, book.pricing.list_price, book.pricing.marketplace)
    except ValueError as exc:
        f.error("pricing.error", str(exc), "pricing")
        return f, {}
    if book.pricing.list_price < rep.min_list_price:
        f.error("pricing.below_min", f"List price ${book.pricing.list_price:.2f} is below KDP's minimum ${rep.min_list_price:.2f} (royalty would be negative).", "pricing.list_price")
    if book.pricing.list_price < rep.threshold_price:
        gain = rep.royalty_at_threshold - rep.royalty_per_copy
        f.warning(
            "pricing.low_tier",
            f"${book.pricing.list_price:.2f} earns 50%; pricing at ${rep.threshold_price:.2f} earns 60% and ${gain:.2f} more per copy (${rep.royalty_at_threshold:.2f} vs ${rep.royalty_per_copy:.2f}).",
            "pricing.list_price",
        )
    return f, rep.as_dict()


def run_preflight(
    book: Book,
    pages: int | None,
    interior_pdf: Path | None = None,
    cover_pdf: Path | None = None,
    ebook_cover: Path | None = None,
    out_dir: Path | None = None,
) -> PreflightReport:
    findings = FindingList()
    summary: dict = {}

    findings.extend(validate_book_metadata(book))
    findings.extend(check_print_spec(book, pages))
    pf, price = check_pricing(book, pages)
    findings.extend(pf)
    if price:
        summary["pricing"] = {
            "printing_cost": f"${price['printing_cost']:.2f}",
            "list_price": f"${price['list_price']:.2f}",
            "royalty_rate": f"{int(price['royalty_rate'] * 100)}%",
            "royalty_per_copy": f"${price['royalty_per_copy']:.2f}",
            "min_list_price": f"${price['min_list_price']:.2f}",
        }
    if book.pricing.ebook_list_price and "ebook" in book.formats:
        from ..pricing import ebook_royalty

        summary["ebook_royalty_per_sale"] = f"${ebook_royalty(book.pricing.ebook_list_price):.2f}"

    if interior_pdf is not None:
        inf, info = check_interior_pdf(interior_pdf, book)
        findings.extend(inf)
        if info:
            summary["interior"] = {"file": interior_pdf.name, "pages": len(info.pages), "size_mb": round(info.file_mb, 2)}
    if cover_pdf is not None and pages is not None:
        cf, cinfo = check_cover_pdf(cover_pdf, book, pages)
        findings.extend(cf)
        if cinfo and cinfo.pages:
            p = cinfo.pages[0]
            summary["cover"] = {"file": cover_pdf.name, "size_in": f"{p.width_pt / 72:.4f} x {p.height_pt / 72:.4f}", "size_mb": round(cinfo.file_mb, 2)}
    if ebook_cover is not None:
        findings.extend(check_ebook_cover(ebook_cover))

    summary["ai_disclosure"] = book.ai_disclosure()
    summary["weekly_limit"] = f"KDP allows {specs.WEEKLY_NEW_TITLES_PER_FORMAT} new titles per format per week (resets Sunday 00:00 UTC)."
    findings.info("kdp.weekly_limit", summary["weekly_limit"], "publishing")
    if any(v.startswith("AI-generated") for v in summary["ai_disclosure"].values()):
        findings.info("kdp.ai_disclosure", "Answer YES to the AI-generated content question and declare: " + ", ".join(k for k, v in summary["ai_disclosure"].items() if v.startswith("AI-generated")), "publishing")

    report = PreflightReport(book.id, pages, findings, summary)
    out_dir = out_dir or book.build_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "preflight.json", report.to_dict())
    (out_dir / "preflight.md").write_text(report.to_markdown(), encoding="utf-8")
    return report
