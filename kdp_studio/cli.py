"""Command line interface: kdp validate | build | preflight | price | cover-size."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pypdf import PdfReader

from . import specs
from .cover.geometry import cover_geometry
from .cover.render import render_cover
from .interior.pipeline import build_coloring_interior
from .metadata_rules import validate_book_metadata
from .preflight.run import run_preflight
from .pricing import price_report
from .schema import ColoringInterior, load_book

log = logging.getLogger("kdp")


def _print_findings(findings) -> None:
    for x in findings:
        print(f"  [{x.level.upper():7}] {x.code}: {x.message}")


def cmd_validate(args) -> int:
    book = load_book(args.book)
    print(f"Book: {book.id} ({book.type}) — {book.metadata.full_title}")
    pages = book.interior.planned_pages() if isinstance(book.interior, ColoringInterior) else None
    if pages:
        geo = cover_geometry(book.print_.trim, pages, book.print_.paper)
        print(f"Planned pages: {pages} | trim {book.print_.trim} | paper {book.print_.paper} | bleed {book.print_.bleed}")
        print(f"Cover wrap: {geo.width_in:.4f} x {geo.height_in:.4f} in ({geo.width_px}x{geo.height_px}px), spine {geo.spine_in:.4f} in, spine text {'allowed' if geo.spine_text_allowed else 'NOT allowed (<79 pages)'}")
        rep = price_report(book.print_.trim, book.print_.paper, pages, book.pricing.list_price)
        print(f"Printing cost ${rep.printing_cost:.2f} | list ${rep.list_price:.2f} @ {int(rep.royalty_rate * 100)}% -> royalty ${rep.royalty_per_copy:.2f}/copy | min price ${rep.min_list_price:.2f} | at ${rep.threshold_price:.2f}: ${rep.royalty_at_threshold:.2f}")
    print("AI disclosure:")
    for k, v in book.ai_disclosure().items():
        print(f"  - {k}: {v}")
    findings = validate_book_metadata(book)
    print(f"Metadata: {len(findings.errors)} error(s), {len(findings.warnings)} warning(s)")
    _print_findings(findings)
    return 1 if findings.errors else 0


def _pdf_pages(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def cmd_build(args) -> int:
    book = load_book(args.book)
    build = book.build_dir
    build.mkdir(parents=True, exist_ok=True)
    pages = args.pages

    interior_pdf = build / "interior.pdf"
    if not args.skip_interior:
        if not isinstance(book.interior, ColoringInterior):
            print("Only coloring interiors are implemented in Phase 0 (story interiors come in Phase 2).")
            return 2
        result = build_coloring_interior(book, image_limit=args.images)
        pages = result.total_pages
        print(f"Interior: {result.pdf_path} — {result.total_pages} pages, {result.image_pages} coloring pages")
        if result.rejected_images:
            print(f"  WARNING: {result.rejected_images} of {result.requested_images} requested pages rejected (QA/dedupe); see {build / 'interior_manifest.json'}")
    elif interior_pdf.is_file() and pages is None:
        pages = _pdf_pages(interior_pdf)
    if pages is None:
        print("Need a page count: build the interior or pass --pages N")
        return 2

    cover_pdf = build / "cover_wrap.pdf"
    ebook_jpg = build / "cover_ebook.jpg"
    if not args.skip_cover:
        cov = render_cover(book, pages)
        cover_pdf, ebook_jpg = cov.pdf_path, cov.ebook_jpg
        print(f"Cover: {cov.pdf_path} — {cov.geometry.width_in:.4f} x {cov.geometry.height_in:.4f} in, spine {cov.geometry.spine_in:.4f} in, spine text {'drawn' if cov.spine_text_drawn else 'omitted'}")
        print(f"Preview: {cov.preview_jpg} | eBook cover: {cov.ebook_jpg}")

    report = run_preflight(
        book,
        pages,
        interior_pdf if interior_pdf.is_file() else None,
        cover_pdf if cover_pdf.is_file() else None,
        ebook_jpg if ebook_jpg.is_file() else None,
    )
    print(f"Preflight: {'PASS' if report.ok else 'FAIL'} — {len(report.findings.errors)} error(s), {len(report.findings.warnings)} warning(s) -> {build / 'preflight.md'}")
    _print_findings(report.findings)
    return 0 if report.ok else 1


def cmd_preflight(args) -> int:
    book = load_book(args.book)
    build = book.build_dir
    interior_pdf = build / "interior.pdf"
    pages = args.pages or (_pdf_pages(interior_pdf) if interior_pdf.is_file() else None)
    report = run_preflight(
        book,
        pages,
        interior_pdf if interior_pdf.is_file() else None,
        build / "cover_wrap.pdf" if (build / "cover_wrap.pdf").is_file() else None,
        build / "cover_ebook.jpg" if (build / "cover_ebook.jpg").is_file() else None,
    )
    print(f"Preflight: {'PASS' if report.ok else 'FAIL'} — {len(report.findings.errors)} error(s), {len(report.findings.warnings)} warning(s)")
    _print_findings(report.findings)
    return 0 if report.ok else 1


def cmd_price(args) -> int:
    rep = price_report(args.trim, args.paper, args.pages, args.price)
    for k, v in rep.as_dict().items():
        print(f"{k:22}: {v}")
    return 0


def cmd_cover_size(args) -> int:
    geo = cover_geometry(args.trim, args.pages, args.paper)
    for k, v in geo.as_dict().items():
        print(f"{k:20}: {v}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kdp", description="kdp-studio: build KDP-ready coloring books from book.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="validate book.yaml, show plan, pricing and AI disclosure")
    p.add_argument("book")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("build", help="build interior + cover and run preflight")
    p.add_argument("book")
    p.add_argument("--images", type=int, help="limit the number of coloring pages (quick test builds)")
    p.add_argument("--skip-interior", action="store_true")
    p.add_argument("--skip-cover", action="store_true")
    p.add_argument("--pages", type=int, help="page count when skipping the interior")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("preflight", help="re-run checks on an existing build/")
    p.add_argument("book")
    p.add_argument("--pages", type=int)
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("price", help="printing cost / royalty for a trim, paper, page count and list price")
    p.add_argument("--trim", default="8.5x11")
    p.add_argument("--paper", default="white_bw", choices=specs.PAPER_TYPES)
    p.add_argument("--pages", type=int, required=True)
    p.add_argument("--price", type=float, required=True)
    p.set_defaults(func=cmd_price)

    p = sub.add_parser("cover-size", help="full-wrap cover dimensions and spine width")
    p.add_argument("--trim", default="8.5x11")
    p.add_argument("--paper", default="white_bw", choices=specs.PAPER_TYPES)
    p.add_argument("--pages", type=int, required=True)
    p.set_defaults(func=cmd_cover_size)

    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
