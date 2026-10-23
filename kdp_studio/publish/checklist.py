"""A manual-entry sheet with every KDP field for one title/format, in KDP's own order.
Useful on its own (copy/paste into the dashboard) and printed by the assisted flow."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from ..pricing import ebook_royalty, price_report
from ..schema import Book
from ..util import file_mb
from .quota import QuotaStatus

PAPER_LABELS = {
    "white_bw": "Black & white interior with white paper",
    "cream_bw": "Black & white interior with cream paper",
    "groundwood_bw": "Black & white interior with groundwood paper",
    "standard_color": "Standard color interior with white paper",
    "premium_color": "Premium color interior with white paper",
}


def split_author(name: str) -> tuple[str, str]:
    parts = name.strip().split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def artifacts_for(book: Book, fmt: str) -> dict[str, Path | None]:
    b = book.build_dir
    epub = next(iter(sorted(b.glob("*.epub"))), None)
    if fmt == "ebook":
        return {"manuscript": epub, "cover": b / "cover_ebook.jpg" if (b / "cover_ebook.jpg").is_file() else None}
    return {"manuscript": b / "interior.pdf" if (b / "interior.pdf").is_file() else None, "cover": b / "cover_wrap.pdf" if (b / "cover_wrap.pdf").is_file() else None}


def pdf_pages(path: Path | None) -> int | None:
    if path and path.is_file() and path.suffix.lower() == ".pdf":
        try:
            return len(PdfReader(str(path)).pages)
        except Exception:  # noqa: BLE001 - a broken PDF is reported by preflight
            return None
    return None


def build_checklist(book: Book, fmt: str, quota: QuotaStatus | None = None) -> str:
    md = book.metadata
    first, last = split_author(md.author)
    art = artifacts_for(book, fmt)
    pages = pdf_pages(art["manuscript"]) if fmt != "ebook" else None
    disclosure = book.ai_disclosure()
    lines = [f"# KDP checklist — {md.full_title} ({fmt})", ""]
    if quota:
        lines.append(f"Weekly quota for {fmt}: {quota.remaining_created} creation(s) and {quota.remaining_submitted} submission(s) left until {quota.window_end:%Y-%m-%d %H:%M} UTC.")
        lines.append("")

    lines += ["## 1. Details", "", f"- Language: {md.language}", f"- Book title: {md.title}", f"- Subtitle: {md.subtitle or '(none)'}"]
    if md.series:
        lines.append(f"- Series: {md.series.name}" + (f" #{md.series.number}" if md.series.number else ""))
    lines.append(f"- Edition: {md.edition or '(none)'}")
    lines.append(f"- Primary author: first name '{first}' / last name '{last}'")
    if md.contributors:
        lines.append(f"- Contributors: {', '.join(md.contributors)}")
    lines += ["- Description (HTML):", "", "```html", md.description_html.strip(), "```", ""]
    lines.append("- Publishing rights: I own the copyright and hold the necessary publishing rights")
    lines.append(f"- Primary audience: sexually explicit = {'Yes' if md.sexually_explicit else 'No'}; reading age = " + (f"{md.reading_age.min}-{md.reading_age.max}" if md.reading_age else "(not set)"))
    lines.append("- AI-generated content:")
    for k, v in disclosure.items():
        lines.append(f"  - {k}: {v}")
    lines.append("- Keywords (7 fields):")
    lines += [f"  {i + 1}. {k}" for i, k in enumerate(md.keywords)]
    lines.append("- Categories (choose in the picker, up to 3):")
    lines += [f"  - {c}" for c in md.categories]
    lines.append(f"- Low-content book: {'YES — tick the box' if md.low_content else 'No — leave unticked (coloring/activity and text books are not low-content)'}")
    lines.append(f"- Large-print book (text 16 pt or larger): {'YES — tick the box' if md.large_print else 'No'}")
    lines.append("")

    lines += ["## 2. Content", ""]
    if fmt == "ebook":
        lines.append("- Manuscript: " + (f"{art['manuscript'].name} ({file_mb(art['manuscript']):.1f} MB)" if art["manuscript"] else "MISSING — build the EPUB first"))
        lines.append("- Cover: upload your own — " + (f"{art['cover'].name}" if art["cover"] else "MISSING — build the cover first"))
        lines.append("- Launch Previewer and check the table of contents, chapter breaks and images.")
    else:
        isbn = {"kdp_free": "Get a free KDP ISBN", "own": f"Use my own ISBN ({book.print_.isbn_number or 'number missing'})", "none": "Publish without an ISBN (low-content only)"}[book.print_.isbn]
        lines.append(f"- ISBN: {isbn}")
        lines.append(f"- Ink and paper: {PAPER_LABELS[book.print_.paper]}")
        lines.append(f"- Trim size: {book.print_.trim.replace('x', ' x ')} in")
        lines.append(f"- Bleed: {'Bleed (PDF only)' if book.print_.bleed else 'No bleed'}")
        lines.append(f"- Cover finish: {book.print_.cover_finish.capitalize()}")
        lines.append("- Manuscript: " + (f"{art['manuscript'].name} ({pages} pages, {file_mb(art['manuscript']):.1f} MB)" if art["manuscript"] else "MISSING — run kdp build"))
        lines.append("- Cover: upload a cover you already have — " + (f"{art['cover'].name} ({file_mb(art['cover']):.1f} MB)" if art["cover"] else "MISSING — run kdp build"))
        lines.append("- Launch Previewer: approve every page (bleed, margins, spine text) before continuing.")
    lines.append("")

    lines += ["## 3. Pricing", "", "- Territories: All territories (worldwide rights)"]
    if fmt == "ebook":
        price = book.pricing.ebook_list_price or 2.99
        lines.append(f"- KDP Select: {'enroll' if book.pricing.kdp_select else 'do not enroll'} (90-day Kindle exclusivity)")
        lines.append(f"- List price (amazon.com): ${price:.2f} -> estimated royalty ${ebook_royalty(price):.2f} per sale ({'70%' if 2.99 <= price <= 9.99 else '35%'} tier)")
    else:
        if pages:
            rep = price_report(book.print_.trim, book.print_.paper, pages, book.pricing.list_price)
            lines.append(f"- List price (amazon.com): ${rep.list_price:.2f} -> printing ${rep.printing_cost:.2f}, royalty {int(rep.royalty_rate * 100)}% = ${rep.royalty_per_copy:.2f} per copy (minimum price ${rep.min_list_price:.2f})")
        else:
            lines.append(f"- List price (amazon.com): ${book.pricing.list_price:.2f} (royalty estimate needs the page count)")
        lines.append(f"- Expanded Distribution: {'yes' if book.pricing.expanded_distribution else 'no'}")
    lines.append("")
    lines += ["## 4. After Publish", "", "- Review usually takes about 3 business days; title and author can only be edited within 72 hours of going live.",
              "- Record the ASIN: `kdp publish mark <book.yaml> --format {fmt} --status live --asin B0...` (adds it to competitor-watch as yours).".replace("{fmt}", fmt),
              "- Weekly limit: 2 new titles per format; this submission counts toward the current window.", ""]
    return "\n".join(lines)
