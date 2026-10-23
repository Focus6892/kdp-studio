"""Command line interface.

Book (Phase 0):   kdp validate | build | preflight | price | cover-size
Niche (Phase 1):  kdp niche run | expand | trends | concepts
Metadata (Ph. 1): kdp metadata generate | apply
"""

from __future__ import annotations

import argparse
import json
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


# --------------------------------------------------------------------------- book commands
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
            print("Only coloring interiors are implemented so far (story interiors come in Phase 2).")
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


# --------------------------------------------------------------------------- niche commands
def cmd_niche_run(args) -> int:
    from .niche.pipeline import ScoutOptions, run_scout
    from .niche.report import summary_table

    opts = ScoutOptions(
        topics=args.topic or [],
        source=args.source,
        book_type=args.book_type,
        max_books=args.max_books,
        expand=args.expand,
        use_autocomplete=args.autocomplete,
        use_claude=not args.no_claude,
        concepts_for_top=args.concepts,
        concepts_n=args.concepts_n,
        out_dir=Path(args.out),
        db_path=Path(args.db) if args.db else None,
        csv_path=Path(args.csv) if args.csv else None,
        default_keyword=args.keyword,
        max_keywords=args.max_keywords,
        seed=args.seed,
    )
    run, paths = run_scout(opts)
    print(f"Scored {len(run.summaries)} keyword(s) from source '{run.source}' (run id {run.run_id}).\n")
    print(summary_table(run.ranked()))
    for kw, cards in run.concepts.items():
        print(f"Concept cards for '{kw}':")
        for i, c in enumerate(cards, start=1):
            print(f"  {i}. {c.title_idea} — {c.angle} ({c.audience})")
    print(f"\nReport: {paths['latest']}\nCSV: {paths['csv']}\nDB: {paths['db']}")
    return 0


def cmd_niche_expand(args) -> int:
    from .niche.keywords import expand_keywords

    kws = expand_keywords(args.topic, args.book_type, use_autocomplete=args.autocomplete, use_claude=not args.no_claude, max_total=args.max)
    for k in kws:
        print(k)
    return 0


def cmd_niche_trends(args) -> int:
    from .niche.report import trends_markdown
    from .niche.store import NicheStore

    store = NicheStore(Path(args.db))
    try:
        md = trends_markdown(store.trends())
    finally:
        store.close()
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    return 0


def cmd_niche_concepts(args) -> int:
    from .niche.concepts import concept_cards
    from .niche.scoring import summarize
    from .niche.sources import make_source
    from .niche.store import NicheStore

    summary = None
    db = Path(args.db)
    if db.is_file():
        store = NicheStore(db)
        try:
            summary = store.latest_summary(args.keyword)
        finally:
            store.close()
    if summary is None:
        source = make_source(args.source)
        books = source.search(args.keyword, args.max_books)
        if not books:
            print(f"No data for '{args.keyword}' in {db} or from source {args.source}")
            return 1
        summary = summarize(args.keyword, books, source.name)
    cards = concept_cards(summary, args.book_type, args.n, use_claude=not args.no_claude)
    for i, c in enumerate(cards, start=1):
        print(f"{i}. {c.title_idea}\n   angle: {c.angle}\n   audience: {c.audience}\n   differentiation: {c.differentiation}\n   why it can rank: {c.why_it_can_rank}\n   risks: {c.risks}\n   keywords: {', '.join(c.keywords)}\n")
    if args.out:
        Path(args.out).write_text(json.dumps([c.model_dump() for c in cards], indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


# --------------------------------------------------------------------------- metadata commands
def cmd_metadata_generate(args) -> int:
    from .metadata.brief import load_brief
    from .metadata.generate import generate_candidates
    from .metadata.report import write_candidates

    brief_path = Path(args.brief)
    brief = load_brief(brief_path)
    scored = generate_candidates(brief, n=args.n, use_claude=not args.no_claude, repair=not args.no_repair, model=args.model)
    out_dir = Path(args.out) if args.out else brief_path.parent / "metadata"
    paths = write_candidates(scored, brief, out_dir)
    print(f"{len(scored)} candidate(s) for '{brief.niche_keyword}' -> {paths['markdown']}\n")
    for i, sc in enumerate(scored, start=1):
        c = sc.candidate
        print(f"{i}. [{sc.score:.0f}] {c.title} — {c.subtitle or ''}  ({len(sc.findings.errors)} err, {len(sc.findings.warnings)} warn)")
    best = scored[0] if scored else None
    return 0 if best and not best.findings.errors else 1


def cmd_metadata_apply(args) -> int:
    from .metadata.apply import apply_candidate
    from .metadata.generate import MetadataCandidate

    data = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    items = data["candidates"] if isinstance(data, dict) else data
    if not 1 <= args.pick <= len(items):
        print(f"--pick must be between 1 and {len(items)}")
        return 2
    cand = MetadataCandidate.model_validate(items[args.pick - 1]["candidate"] if "candidate" in items[args.pick - 1] else items[args.pick - 1])
    backup = apply_candidate(Path(args.book), cand, author=args.author, backup=not args.no_backup)
    book = load_book(args.book)
    findings = validate_book_metadata(book)
    print(f"Applied candidate {args.pick} to {args.book}" + (f" (backup: {backup})" if backup else ""))
    print(f"Title: {book.metadata.full_title}")
    print(f"Metadata check: {len(findings.errors)} error(s), {len(findings.warnings)} warning(s)")
    _print_findings(findings)
    return 0 if not findings.errors else 1


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kdp", description="kdp-studio: niche research, metadata and KDP-ready files from book.yaml")
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

    niche = sub.add_parser("niche", help="niche research (niche-scout)")
    nsub = niche.add_subparsers(dest="niche_cmd", required=True)

    p = nsub.add_parser("run", help="score keywords from a data source and write a report")
    p.add_argument("--topic", action="append", help="seed topic/keyword (repeatable)")
    p.add_argument("--source", default="fixture", choices=["fixture", "csv", "apify", "creators"])
    p.add_argument("--csv", help="CSV/JSON export for --source csv")
    p.add_argument("--keyword", help="keyword to assign when the CSV has no keyword column")
    p.add_argument("--book-type", default="coloring", choices=["coloring", "story"])
    p.add_argument("--max-books", type=int, default=24)
    p.add_argument("--expand", action="store_true", help="expand topics into more keywords before scoring")
    p.add_argument("--autocomplete", action="store_true", help="use Amazon search suggestions during expansion")
    p.add_argument("--no-claude", action="store_true", help="never call Claude (keyword expansion, concept cards)")
    p.add_argument("--concepts", type=int, default=3, help="concept cards for the top N niches (0 = none)")
    p.add_argument("--concepts-n", type=int, default=10)
    p.add_argument("--max-keywords", type=int, default=40)
    p.add_argument("--seed", type=int, default=1, help="fixture source seed")
    p.add_argument("--out", default="niches")
    p.add_argument("--db", help="SQLite path (default <out>/niche_scout.sqlite)")
    p.set_defaults(func=cmd_niche_run)

    p = nsub.add_parser("expand", help="print candidate keywords for seed topics")
    p.add_argument("--topic", action="append", required=True)
    p.add_argument("--book-type", default="coloring", choices=["coloring", "story"])
    p.add_argument("--autocomplete", action="store_true")
    p.add_argument("--no-claude", action="store_true")
    p.add_argument("--max", type=int, default=60)
    p.set_defaults(func=cmd_niche_expand)

    p = nsub.add_parser("trends", help="compare the latest two runs per keyword")
    p.add_argument("--db", default="niches/niche_scout.sqlite")
    p.add_argument("--out", help="write the markdown table to this file")
    p.set_defaults(func=cmd_niche_trends)

    p = nsub.add_parser("concepts", help="concept cards for one keyword")
    p.add_argument("--keyword", required=True)
    p.add_argument("--db", default="niches/niche_scout.sqlite")
    p.add_argument("--source", default="fixture", choices=["fixture", "apify", "creators"], help="used when the keyword is not in the DB")
    p.add_argument("--max-books", type=int, default=24)
    p.add_argument("--book-type", default="coloring", choices=["coloring", "story"])
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--no-claude", action="store_true")
    p.add_argument("--out", help="write cards as JSON")
    p.set_defaults(func=cmd_niche_concepts)

    meta = sub.add_parser("metadata", help="title / subtitle / description / keywords / categories (metadata-writer)")
    msub = meta.add_subparsers(dest="metadata_cmd", required=True)

    p = msub.add_parser("generate", help="generate and score candidates from a brief.yaml")
    p.add_argument("--brief", required=True)
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--no-claude", action="store_true")
    p.add_argument("--no-repair", action="store_true", help="skip the Claude repair pass for candidates with findings")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--out", help="output directory (default <brief dir>/metadata)")
    p.set_defaults(func=cmd_metadata_generate)

    p = msub.add_parser("apply", help="write a chosen candidate into book.yaml")
    p.add_argument("--book", required=True)
    p.add_argument("--candidates", required=True, help="candidates.json from `metadata generate`")
    p.add_argument("--pick", type=int, default=1, help="1-based candidate number")
    p.add_argument("--author", help="override the author/pen name")
    p.add_argument("--no-backup", action="store_true")
    p.set_defaults(func=cmd_metadata_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
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
