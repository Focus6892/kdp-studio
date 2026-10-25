"""Command line interface.

Book:      kdp validate | build | preflight | price | cover-size
Niche:     kdp niche run | expand | trends | concepts
Metadata:  kdp metadata generate | apply
Story:     kdp story draft | check
Watch:     kdp watch add | snapshot | report | insights | covers
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
from .paths import data_path
from .preflight.run import run_preflight
from .pricing import price_report
from .schema import ColoringInterior, StoryInterior, load_book

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
    elif isinstance(book.interior, StoryInterior):
        from .story.manuscript import load_manuscript

        try:
            ms = load_manuscript(book)
            print(f"Manuscript: {len(ms.chapters)} chapters, {ms.words:,} words | trim {book.print_.trim} | paper {book.print_.paper}")
        except FileNotFoundError as exc:
            print(f"Manuscript: {exc}")
    print("AI disclosure:")
    for k, v in book.ai_disclosure().items():
        print(f"  - {k}: {v}")
    findings = validate_book_metadata(book)
    print(f"Metadata: {len(findings.errors)} error(s), {len(findings.warnings)} warning(s)")
    _print_findings(findings)
    return 1 if findings.errors else 0


def _pdf_pages(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def cmd_keys(args) -> int:
    from . import keys as keymod

    if args.set:
        updates = dict(kv.split("=", 1) for kv in args.set if "=" in kv)
        written = keymod.save_env(updates)
        print("saved to .env: " + (", ".join(written) or "nothing (unknown names or empty values)"))
    from .interior.failover import ProviderState, default_chain

    for p in keymod.status_table():
        if not p["vars"]:
            print(f"  {p['id']:14} no key needed")
            continue
        for pr in p["profiles"]:  # account 1 always; backup accounts (_2, _3 ...) when any of their variables is set
            state = ", ".join(f"{pr['vars'][v]}={'set' if ok else 'missing'}" for v, ok in pr["present"].items())
            line = f"  {pr['id']:14} {state}"
            if args.check and (args.check == "all" or args.check == p["id"]):
                res = keymod.check(p["id"], pr["n"])
                line += f"  -> {'OK' if res['ok'] else 'FAIL'}: {res['detail']}"
            print(line)
    print("Chain for provider auto: " + (" -> ".join(default_chain()) or "(nothing configured)"))
    for s in ProviderState().summary():
        if not s["available"]:
            print(f"  blocked: {s['id']} until {s['until']} ({s['reason']})")
    print("Keys: environment first, then .env in the project folder (never committed). Backup accounts: NAME_2, NAME_3 ... Get them: kdp ui -> Cài đặt.")
    return 0


def cmd_image_test(args) -> int:
    """Generate a few pages with the configured image provider and show raw vs cleaned side by side."""
    from PIL import Image

    from .interior.cleanup import prepare_art
    from .interior.generate import API_PROVIDERS, APPROX_COST_USD, ProviderError, make_provider
    from .interior.pipeline import _parse_size
    from .interior.prompts import build_prompts
    from .interior.qa import content_qa, heuristic_qa
    from .util import write_json

    book = load_book(args.book)
    interior = book.interior
    if not isinstance(interior, ColoringInterior):
        print("image-test works on coloring books (interior.type: coloring)")
        return 2
    overrides = {k: v for k, v in {"provider": args.provider, "model": args.model, "lora": args.lora}.items() if v}
    if args.provider and args.provider != interior.source.provider and not args.model:
        overrides["model"] = None  # the book's model id belongs to another provider; use the new provider's default
    source = interior.source.model_copy(update=overrides)
    out = Path(args.out) if args.out else book.build_dir / "image-test"
    out.mkdir(parents=True, exist_ok=True)
    try:
        provider = make_provider(source, book.book_dir, negative_prompt=interior.negative_prompt)
    except ProviderError as exc:
        print(f"error: {exc}")
        return 1
    prompts = build_prompts(interior, args.n)
    size = _parse_size(source.size)
    print(f"Provider {provider.name} ({getattr(provider, 'model', '')}), {len(prompts)} page(s), size {source.size} -> {out}")
    rows, ok_count = [], 0
    import time

    for p in prompts:
        raw = out / f"{p.index:02d}_raw.png"
        t0 = time.time()
        try:
            provider.generate(p.prompt, p.index, 0, raw, size)
        except ProviderError as exc:
            print(f"page {p.index}: {exc}")
            return 1
        seconds = time.time() - t0
        with Image.open(raw) as im:
            art = prepare_art(im, size, interior.cleanup)
        clean = out / f"{p.index:02d}_clean.png"
        art.save(clean)
        qa = heuristic_qa(art, interior.qa)
        if qa.ok and (interior.qa.reject_people or interior.qa.reject_text) and provider.name in API_PROVIDERS:  # same people/nudity/text screen as a real build
            cq = content_qa(raw, interior.qa)
            if cq is not None and not cq.ok:
                qa = cq
        ok_count += qa.ok
        rows.append({"index": p.index, "subject": p.subject, "prompt": p.prompt, "raw": raw.name, "clean": clean.name, "qa": qa.as_dict()})
        rows[-1]["seconds"] = round(seconds, 1)
        print(f"page {p.index}: {'OK    ' if qa.ok else 'REJECT'} ink={qa.ink_ratio:.3f} {seconds:5.1f}s {'; '.join(qa.reasons)} | {p.subject}")
    thumb_w = 420
    tiles = []
    for r in rows:
        pair = []
        for name in (r["raw"], r["clean"]):
            with Image.open(out / name) as im:
                im = im.convert("RGB")
                h = max(1, round(im.height * thumb_w / im.width))
                pair.append(im.resize((thumb_w, h)))
        tiles.append(pair)
    row_h = max(max(a.height, b.height) for a, b in tiles)
    sheet = Image.new("RGB", (thumb_w * 2 + 30, (row_h + 10) * len(tiles) + 10), "white")
    for i, (a, b) in enumerate(tiles):
        sheet.paste(a, (10, 10 + i * (row_h + 10)))
        sheet.paste(b, (thumb_w + 20, 10 + i * (row_h + 10)))
    sheet_path = out / "contact_sheet.png"
    sheet.save(sheet_path)
    write_json(out / "image_test.json", {"provider": provider.name, "model": getattr(provider, "model", None), "size": source.size, "pages": rows})
    cost = APPROX_COST_USD.get(provider.name, 0.0) * len(rows)
    print(f"\n{ok_count}/{len(rows)} pass the heuristic QA; approx cost ${cost:.2f}; raw | cleaned sheet: {sheet_path}")
    return 0


def cmd_local_setup(args) -> int:
    """Install the local image stack (CUDA PyTorch + diffusers) and pre-download the model and LoRA."""
    import subprocess

    if not args.skip_install:
        for cmd in ([sys.executable, "-m", "pip", "install", "--user", "--index-url", f"https://download.pytorch.org/whl/{args.cuda}", "torch"],
                    [sys.executable, "-m", "pip", "install", "--user", "diffusers", "transformers", "accelerate", "safetensors", "peft", "scipy"]):
            print("+", " ".join(cmd))
            if subprocess.call(cmd) != 0:
                print("install failed; see the pip output above")
                return 1
    try:
        import torch
    except ImportError:
        print("torch is not importable after the install")
        return 1
    print(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}" + (f" ({torch.cuda.get_device_name(0)})" if torch.cuda.is_available() else ""))
    from huggingface_hub import hf_hub_download, snapshot_download  # comes with diffusers

    if args.model and not Path(args.model).exists():
        print(f"downloading {args.model} ...")
        snapshot_download(args.model, allow_patterns=["*.json", "*.txt", "*.safetensors"], ignore_patterns=["*.bin", "*.ckpt", "*.msgpack", "*.h5", "*.onnx"])
    if args.lora and not Path(args.lora).exists():
        repo, _, fname = args.lora.partition(":")
        print(f"downloading LoRA {repo} ...")
        hf_hub_download(repo, fname) if fname else snapshot_download(repo, allow_patterns=["*.safetensors", "*.json"])
    print("Local stack ready. In book.yaml set interior.source.provider: local (plus model / lora), then: kdp image-test <book.yaml> --provider local")
    return 0


def cmd_license(args) -> int:
    from . import license as lic

    if args.license_cmd == "machine-id":
        print(lic.machine_id())
        return 0
    if args.license_cmd == "keygen":
        priv, pub = lic.keygen(Path(args.out))
        print(f"private key: {priv}  (keep it outside the repo and back it up; anyone holding it can issue keys)")
        print(f"public key embedded in: {pub}  (commit this file; builds containing it require a license)")
        return 0
    if args.license_cmd == "issue":
        token = lic.issue(Path(args.key), args.to, args.machine, days=(None if args.days == 0 else args.days), features=args.feature or None)
        print(token)
        return 0
    if args.license_cmd == "activate":
        token = args.token if args.token != "-" else sys.stdin.read()
        payload = lic.activate(token)
        print(f"License active for {payload['licensee']} on {payload['machine']} until {payload.get('expires') or 'no expiry'}")
        return 0
    s = lic.status()
    print(f"machine id : {s['machine']}")
    print(f"enforced   : {s['enforced']}")
    print(f"valid      : {s['valid']}" + (f"  ({s.get('licensee')}, expires {s.get('expires') or 'never'})" if s["valid"] else f"  - {s.get('reason')}"))
    return 0 if s["valid"] or not s["enforced"] else 1


def cmd_ui(args) -> int:
    """Local web interface: books, builds, image tests, the publish queue, runs, quota, keys and license."""
    try:
        from .ui.app import serve
    except ImportError as exc:
        print(f"the web UI needs Flask: python -m pip install --user flask ({exc})")
        return 1
    return serve(host=args.host, port=args.port, book_dirs=[Path(d) for d in (args.books or [])], open_browser=not args.no_browser)


def cmd_draw_preview(args) -> int:
    """Render every drawing spec in a folder to PNG (plus a contact sheet) so the designs can be reviewed."""
    from PIL import Image

    from .interior.vector import load_specs, render_spec, validate_spec

    folder = Path(args.folder)
    out = Path(args.out) if args.out else folder / "_preview"
    out.mkdir(parents=True, exist_ok=True)
    w, h = (int(x) for x in args.size.lower().split("x"))
    thumbs = []
    bad = 0
    for path, spec in load_specs(folder):
        problems = validate_spec(spec)
        if problems:
            bad += 1
            print(f"  {path.name}: INVALID - " + "; ".join(problems))
            continue
        img = render_spec(spec, (w, h))
        img.save(out / (path.stem + ".png"))
        ink = 1.0 - (sum(img.histogram()[200:]) / (w * h))
        print(f"  {path.name}: ok  ink={ink:.3f}  {spec.get('title', '')}")
        thumbs.append(img.convert("RGB").resize((300, int(300 * h / w))))
    if thumbs:
        cols = min(4, len(thumbs))
        rows = (len(thumbs) + cols - 1) // cols
        th, tw = thumbs[0].height, 300
        sheet = Image.new("RGB", (cols * (tw + 10) + 10, rows * (th + 10) + 10), "white")
        for i, t in enumerate(thumbs):
            sheet.paste(t, (10 + (i % cols) * (tw + 10), 10 + (i // cols) * (th + 10)))
        sheet.save(out / "contact_sheet.png")
        print(f"{len(thumbs)} drawing(s) rendered to {out} (contact_sheet.png)" + (f"; {bad} invalid" if bad else ""))
    return 1 if bad else 0


def cmd_build(args) -> int:
    book = load_book(args.book)
    build = book.build_dir
    build.mkdir(parents=True, exist_ok=True)
    pages = args.pages
    interior_pdf = build / "interior.pdf"
    story_res = None
    run_previewer = not getattr(args, "no_previewer", False)

    if not args.skip_interior:
        if isinstance(book.interior, ColoringInterior):
            result = build_coloring_interior(book, image_limit=args.images, reuse_raw=getattr(args, 'reuse_raw', False))
            pages = result.total_pages
            print(f"Interior: {result.pdf_path} — {result.total_pages} pages, {result.image_pages} coloring pages")
            if result.rejected_images:
                print(f"  WARNING: {result.rejected_images} of {result.requested_images} requested pages rejected (QA/dedupe); see {build / 'interior_manifest.json'}")
        else:
            from .story.pipeline import build_story

            story_res = build_story(book, run_previewer=run_previewer)
            pages = story_res.pages
            pr = story_res.print_result
            print(f"Interior: {story_res.pdf_path} — {pages} pages ({pr.content_pages} content + {pr.padded_pages} blank), {story_res.words:,} words, {len(story_res.manuscript.chapters)} chapters, inside margin {pr.inside_margin_in:.3f} in")
            print(f"EPUB: {story_res.epub_path}")
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
        if story_res is not None:
            from .story.pipeline import rebuild_epub

            story_res = rebuild_epub(book, story_res, cov.ebook_jpg, run_previewer=run_previewer)
            print(f"EPUB repackaged with the cover: {story_res.epub_path}")

    epub_path = story_res.epub_path if story_res else (next(iter(sorted(build.glob("*.epub"))), None) if book.type == "story" else None)
    report = run_preflight(
        book,
        pages,
        interior_pdf if interior_pdf.is_file() else None,
        cover_pdf if cover_pdf.is_file() else None,
        ebook_jpg if ebook_jpg.is_file() else None,
        epub_path=epub_path,
        extra=story_res.findings if story_res else None,
    )
    print(f"Preflight: {'PASS' if report.ok else 'FAIL'} — {len(report.findings.errors)} error(s), {len(report.findings.warnings)} warning(s) -> {build / 'preflight.md'}")
    _print_findings(report.findings)
    return 0 if report.ok else 1


def cmd_preflight(args) -> int:
    book = load_book(args.book)
    build = book.build_dir
    interior_pdf = build / "interior.pdf"
    pages = args.pages or (_pdf_pages(interior_pdf) if interior_pdf.is_file() else None)
    epub_path = next(iter(sorted(build.glob("*.epub"))), None) if book.type == "story" else None
    report = run_preflight(
        book,
        pages,
        interior_pdf if interior_pdf.is_file() else None,
        build / "cover_wrap.pdf" if (build / "cover_wrap.pdf").is_file() else None,
        build / "cover_ebook.jpg" if (build / "cover_ebook.jpg").is_file() else None,
        epub_path=epub_path,
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

    for k in expand_keywords(args.topic, args.book_type, use_autocomplete=args.autocomplete, use_claude=not args.no_claude, max_total=args.max):
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
    raw = items[args.pick - 1]
    cand = MetadataCandidate.model_validate(raw["candidate"] if "candidate" in raw else raw)
    backup = apply_candidate(Path(args.book), cand, author=args.author, backup=not args.no_backup)
    book = load_book(args.book)
    findings = validate_book_metadata(book)
    print(f"Applied candidate {args.pick} to {args.book}" + (f" (backup: {backup})" if backup else ""))
    print(f"Title: {book.metadata.full_title}")
    print(f"Metadata check: {len(findings.errors)} error(s), {len(findings.warnings)} warning(s)")
    _print_findings(findings)
    return 0 if not findings.errors else 1


# --------------------------------------------------------------------------- story commands
def cmd_story_draft(args) -> int:
    from .story.draft import draft_story, load_story_brief

    brief_path = Path(args.brief)
    brief = load_story_brief(brief_path)
    out_dir = Path(args.out) if args.out else brief_path.parent / "manuscript"
    res = draft_story(brief, out_dir, model=args.model, polish=args.polish, progress=print)
    print(f"\nDrafted {len(res.chapter_files)} chapter(s), {res.words:,} words -> {res.out_dir}")
    print(f"Bible: {res.bible_path} | Outline: {res.outline_path}")
    print("Remember: this text is AI-generated for KDP purposes (provenance.text: ai_generated).")
    return 0


def cmd_story_check(args) -> int:
    from .story.epub import validate_epub
    from .story.kindle_previewer import run_kindle_previewer

    book = load_book(args.book)
    build = book.build_dir
    epub_path = Path(args.epub) if args.epub else next(iter(sorted(build.glob("*.epub"))), None)
    if epub_path is None or not epub_path.is_file():
        print(f"No EPUB found in {build}; run `kdp build` first or pass --epub")
        return 2
    findings = validate_epub(epub_path)
    if not args.no_previewer:
        findings.extend(run_kindle_previewer(epub_path, build / "kindle_previewer"))
    print(f"EPUB check: {'PASS' if findings.ok else 'FAIL'} — {len(findings.errors)} error(s), {len(findings.warnings)} warning(s) for {epub_path.name}")
    _print_findings(findings)
    return 0 if findings.ok else 1


# --------------------------------------------------------------------------- watch commands
def cmd_watch_add(args) -> int:
    from .watch.models import WatchItem, load_watchlist, save_watchlist

    path = Path(args.watchlist)
    wl = load_watchlist(path)
    added = wl.add(WatchItem(asin=args.asin.strip().upper(), label=args.label, niche=args.niche, ours=args.ours, notes=args.notes))
    save_watchlist(path, wl)
    print(("Added" if added else "Already present:") + f" {args.asin} -> {path} ({len(wl.items)} item(s))")
    return 0


def cmd_watch_snapshot(args) -> int:
    from .watch.pipeline import take_snapshot

    snaps = take_snapshot(Path(args.watchlist), args.source, Path(args.db), csv_path=Path(args.csv) if args.csv else None, day=args.day, seed=args.seed)
    print(f"Stored {len(snaps)} snapshot(s) from '{args.source}' in {args.db}")
    for s in snaps:
        print(f"  {s.asin} {s.label or ''}: BSR {s.bsr if s.bsr is not None else '–'}, price {s.price if s.price is not None else '–'}, ratings {s.rating_count if s.rating_count is not None else '–'}")
    return 0


def cmd_watch_report(args) -> int:
    from .watch.pipeline import make_report
    from .watch.report import report_markdown

    rep, paths = make_report(Path(args.watchlist), Path(args.db), Path(args.out))
    print(report_markdown(rep))
    print(f"Report: {paths['latest']} | CSV: {paths['csv']}")
    return 0


def cmd_watch_insights(args) -> int:
    from .watch.insights import insights_markdown, load_reviews, mine_reviews

    reviews = load_reviews(Path(args.reviews))
    if not reviews:
        print("No reviews found in the file")
        return 2
    ins = mine_reviews(reviews, use_claude=not args.no_claude, product_context=args.context or "")
    md = insights_markdown(ins)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    return 0


def cmd_watch_covers(args) -> int:
    from .watch.covers import analyze_covers, covers_markdown

    paths: list[Path] = []
    for p in args.images:
        pp = Path(p)
        if pp.is_dir():
            paths += sorted(x for x in pp.iterdir() if x.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
        elif pp.is_file():
            paths.append(pp)
    if not paths:
        print("No images found")
        return 2
    results = analyze_covers(paths, use_claude=not args.no_claude)
    print(covers_markdown(results))
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


# --------------------------------------------------------------------------- publish commands
def _publish_store(args):
    from .publish.store import PublishStore

    return PublishStore(Path(args.db))


def cmd_publish_checklist(args) -> int:
    from .publish.checklist import build_checklist
    from .publish.quota import quota_status

    book = load_book(args.book)
    store = _publish_store(args)
    try:
        quota = quota_status(store)[args.format]
    finally:
        store.close()
    text = build_checklist(book, args.format, quota)
    out = Path(args.out) if args.out else book.build_dir / f"publish_checklist_{args.format}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Saved: {out}")
    return 0


def cmd_publish_quota(args) -> int:
    from .publish.quota import quota_markdown, quota_status, record_external, record_kdp_limit

    store = _publish_store(args)
    try:
        if args.add_created:
            record_external(store, args.add_created, created=1, note=args.note)
            print(f"Recorded 1 {args.add_created} title created on KDP outside the tool.")
        if args.add_submitted:
            record_external(store, args.add_submitted, submitted=1, note=args.note)
            print(f"Recorded 1 {args.add_submitted} title submitted on KDP outside the tool.")
        if args.limit_reached:
            record_kdp_limit(store, args.limit_reached, note=args.note)
            print(f"Recorded KDP's 'Title creation limit reached' for {args.limit_reached}: runs that create a title are blocked until the window resets.")
        print(quota_markdown(quota_status(store)))
    finally:
        store.close()
    return 0


def cmd_publish_queue(args) -> int:
    store = _publish_store(args)
    try:
        if args.queue_cmd == "add":
            book = load_book(args.book)
            qid = store.queue_add(str(Path(args.book).resolve()), args.format, priority=args.priority, book_id=book.id)
            print(f"Queued #{qid}: {book.id} ({args.format}), priority {args.priority}")
        elif args.queue_cmd == "remove":
            print("Removed" if store.queue_remove(args.id) else "Not found")
        else:
            items = store.queue_list(None if args.all else "queued")
            if not items:
                print("Queue is empty")
            for it in items:
                print(f"#{it['id']:<4} {it['status']:<8} p{it['priority']} {it['fmt']:<9} {it['book_id'] or '':<28} {it['book_path']}")
    finally:
        store.close()
    return 0


def _run_publish_cli(book_path: Path, fmt: str, args) -> int:
    from .publish.flow import ConsoleApprover
    from .publish.pipeline import PublishOptions, run_publish

    defaults = PublishOptions()
    opts = PublishOptions(
        fmt=fmt,
        profile_dir=Path(args.profile) if args.profile else defaults.profile_dir,
        selectors_path=Path(args.selectors) if args.selectors else None,
        store_path=Path(args.db),
        runs_dir=Path(args.runs),
        require_preflight=not args.no_preflight,
        headless_local=args.headless_local,
        start_url=args.start_url or args.resume_url,
        resume=bool(args.resume_url),
    )
    print(f"Assisted publish: {book_path} ({fmt}) | browser profile: {opts.profile_dir}")
    print("Rules: the browser stays visible, you sign in yourself, every KDP step waits for your review, the tool never clicks Publish.")
    result, findings, run_dir = run_publish(book_path, opts, ConsoleApprover())
    _print_findings(findings)
    print(f"Run folder: {run_dir} (checklist.md, screenshots/, flow.json)")
    if result is None:
        print("Preconditions failed; the browser was not opened.")
        return 1
    print(f"Result: {result.status} | filled {len(result.filled)} field(s), {len(result.unfilled)} to enter by hand")
    for fld, val in result.unfilled:
        print(f"  - {fld}: {val}")
    if result.status in ("error", "aborted", "blocked", "stopped_before_publish"):
        for note in result.notes[-3:]:
            print(f"  ! {note}")
        print("  (details in flow.json; re-run with -v for the full traceback)")
    return 0 if result.status in ("submitted", "draft") else 1


def cmd_publish_run(args) -> int:
    return _run_publish_cli(Path(args.book), args.format, args)


def cmd_publish_next(args) -> int:
    from .publish.quota import quota_status

    store = _publish_store(args)
    try:
        allowed = {f for f, s in quota_status(store).items() if s.can_start}
        if args.format:
            allowed &= {args.format}
        item = store.queue_next(allowed)
        if item is None:
            print("Nothing runnable in the queue (empty, or the weekly quota is exhausted for the queued formats).")
            return 1
        store.queue_update(item["id"], "running")
    finally:
        store.close()
    rc = _run_publish_cli(Path(item["book_path"]), item["fmt"], args)
    store = _publish_store(args)
    try:
        store.queue_update(item["id"], "done" if rc == 0 else "failed")
    finally:
        store.close()
    return rc


def cmd_publish_mark(args) -> int:
    from .monitor.status import mark_title

    book = load_book(args.book)
    store = _publish_store(args)
    try:
        row = mark_title(store, book.id, args.format, args.status, asin=args.asin, title=book.metadata.full_title, watchlist_path=Path(args.watchlist) if args.watchlist else None, book_path=str(Path(args.book).resolve()))
    finally:
        store.close()
    print(f"{book.id} ({args.format}) -> {row['status']}" + (f", ASIN {row['asin']}" if row.get("asin") else ""))
    if args.status == "live" and args.asin and args.watchlist:
        print(f"Added {args.asin} to {args.watchlist} as one of yours (run `kdp watch snapshot` to start tracking).")
    return 0


def cmd_publish_probe(args) -> int:
    """Report which selectors match the live KDP page and dump its form structure (ids, names,
    labels, option texts - never typed values) so the selector map can be corrected precisely."""
    import datetime as dt

    from .publish.browser import BrowserSession, inventory_markdown
    from .publish.flow import ConsoleApprover
    from .publish.pipeline import default_profile_dir
    from .publish.selectors import load_selectors
    from .util import write_json

    import time

    sel = load_selectors(Path(args.selectors) if args.selectors else None)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ask = ConsoleApprover().ask
    dumps: list[Path] = []
    with BrowserSession(Path(args.profile) if args.profile else default_profile_dir(), start_url=args.url) as s:
        s.goto(args.url or sel["bookshelf_url"])
        if args.auto:
            # one-shot: wait for the page, optionally click a step/link by its text, dump, leave
            time.sleep(args.wait)
            if args.follow:
                if s.click([f"a:has-text('{args.follow}')", f"text={args.follow}", f"button:has-text('{args.follow}')"]):
                    time.sleep(args.wait)
                else:
                    print(f"Could not find anything to click with text {args.follow!r}; dumping the current page.")
        else:
            print("Sign in if asked, then open the KDP page to probe (Bookshelf, Details, Content or Pricing).")
        round_no = 0
        while True:
            if args.auto and round_no >= 1:
                break
            if not args.auto:
                try:
                    ans = ask("Press Enter to probe the current page, or type q to finish:").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    break
                if ans in ("q", "quit", "exit"):
                    break
            round_no += 1
            try:  # one failing page must never end the probe session
                inv = s.inventory()
                total = sum(len(sc["elements"]) for sc in inv["scopes"])
                print(f"\nPage: {inv.get('title')!r} — {inv.get('url')}\nFrames: {len(inv['frames'])}, form controls found: {total}")
                if total == 0:
                    errs = "; ".join(f.get("error", "") for f in inv["frames"] if f.get("error"))
                    print(f"Nothing readable on this page yet ({errs or 'no form controls'}). Let it finish loading, then press Enter again - no dump written.")
                    continue
                for group in ("details", "ai", "content", "pricing"):
                    m = s.matches(sel[group], args.format)
                    hits = sum(1 for v in m.values() if v)
                    print(f"[{group}] {hits}/{len(m)} selector(s) match")
                    for fld, match in m.items():
                        print(f"  {fld:26} {match or 'NO MATCH'}")
                print("[page]")
                for name in ("create_button", "signin_markers", "captcha_markers"):
                    print(f"  {name:26} {s._first_match(sel[name]) or 'no match'}")
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                js = out_dir / f"probe_{stamp}_{round_no}.json"
                md = out_dir / f"probe_{stamp}_{round_no}.md"
                write_json(js, inv)
                md.write_text(inventory_markdown(inv), encoding="utf-8")
                dumps += [js, md]
                ids = [e["id"] for sc in inv["scopes"] for e in sc["elements"] if e.get("id")]
                print(f"\nDump written: {md.resolve()}\n  ({total} controls; ids seen: {', '.join(ids[:12])}{' ...' if len(ids) > 12 else ''})")
            except Exception as exc:  # noqa: BLE001
                print(f"\nProbe of this page failed ({type(exc).__name__}: {str(exc).splitlines()[0][:200]}). Wait for the page to finish loading and press Enter to retry.")
                continue
            if not args.auto:
                print("Navigate to the next tab (Details -> Content -> Pricing) and press Enter again, or q to finish.")
    if dumps:
        print(f"\n{len(dumps) // 2} page dump(s) in {out_dir}. Share the .md files to get the selector map corrected.")
    return 0


def cmd_publish_diagnose_cover(args) -> int:
    from .publish.diagnose import explain_cover_size_error

    book = load_book(args.book) if args.book else None
    if args.message:
        res = explain_cover_size_error(args.message, pages=args.pages, book=book)
    else:
        if not (args.expected and args.submitted):
            print("Give --message '<KDP error text>' or both --expected WxH and --submitted WxH")
            return 2
        res = explain_cover_size_error(args.expected, args.submitted, pages=args.pages, book=book)
    for line in res["lines"]:
        print(line)
    print()
    for a in res["advice"]:
        print(f"- {a}")
    return 0


def cmd_publish_selectors(args) -> int:
    from .publish.selectors import dump_default_yaml

    text = dump_default_yaml()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}; edit it and pass --selectors to publish run/probe")
    else:
        print(text)
    return 0


# --------------------------------------------------------------------------- monitor commands
def _break_even_for(book_path: str | None) -> float | None:
    if not book_path:
        return None
    from .monitor.ads import break_even_acos
    from .publish.checklist import pdf_pages

    book = load_book(book_path)
    pages = pdf_pages(book.build_dir / "interior.pdf")
    if pages:
        rep = price_report(book.print_.trim, book.print_.paper, pages, book.pricing.list_price)
        return break_even_acos(rep.royalty_per_copy, rep.list_price)
    return None


def cmd_monitor_check(args) -> int:
    from .monitor.status import status_markdown, title_rows

    store = _publish_store(args)
    try:
        print(status_markdown(title_rows(store)))
    finally:
        store.close()
    return 0


def cmd_monitor_ads(args) -> int:
    from .monitor.ads import ads_markdown, load_ads_csv, summarize_ads

    rows = load_ads_csv(Path(args.csv))
    summary = summarize_ads(rows, target_acos=args.target_acos, break_even=_break_even_for(args.book))
    text = ads_markdown(summary)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


def cmd_monitor_sales(args) -> int:
    import datetime as dt

    from .monitor.sales import load_sales, sales_markdown, summarize_sales

    rows = load_sales(Path(args.file))
    since = dt.date.fromisoformat(args.since) if args.since else None
    text = sales_markdown(summarize_sales(rows, since))
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


def cmd_monitor_report(args) -> int:
    import datetime as dt

    from .monitor.report import monitor_markdown, own_asin_rows, write_monitor_report

    ads_summary = sales_summary = None
    if args.ads:
        from .monitor.ads import load_ads_csv, summarize_ads

        ads_summary = summarize_ads(load_ads_csv(Path(args.ads)), target_acos=args.target_acos, break_even=_break_even_for(args.book))
    if args.sales:
        from .monitor.sales import load_sales, summarize_sales

        sales_summary = summarize_sales(load_sales(Path(args.sales)), dt.date.fromisoformat(args.since) if args.since else None)
    store = _publish_store(args)
    try:
        text = monitor_markdown(store, own_rows=own_asin_rows(Path(args.watch_db), Path(args.watchlist)), ads_summary=ads_summary, sales_summary=sales_summary)
    finally:
        store.close()
    paths = write_monitor_report(text, Path(args.out))
    print(text)
    print(f"Report: {paths['latest']}")
    return 0


# Runtime data defaults live inside the project folder, whatever the current directory is.
PUB_DB = str(data_path("publishing", "publish.sqlite"))
PUB_RUNS = str(data_path("publishing", "runs"))
PUB_PROBE = str(data_path("publishing", "probe"))
WATCHLIST = str(data_path("watch", "watchlist.yaml"))
WATCH_DB = str(data_path("watch", "watch.sqlite"))
WATCH_DIR = str(data_path("watch"))
NICHE_DB = str(data_path("niches", "niche_scout.sqlite"))
NICHE_DIR = str(data_path("niches"))
MONITOR_DIR = str(data_path("monitor"))


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kdp", description="kdp-studio: niche research, metadata, manuscripts and KDP-ready files from book.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="validate book.yaml, show plan, pricing and AI disclosure")
    p.add_argument("book")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("keys", help="which image/LLM API keys are available (names only); --check calls each platform; --set NAME=VALUE writes .env")
    p.add_argument("--check", nargs="?", const="all", help="live-check one provider id or all")
    p.add_argument("--set", action="append", help="NAME=VALUE to store in .env (repeatable)")
    p.set_defaults(func=cmd_keys)
    p = sub.add_parser("image-test", help="generate a few coloring pages with the real image provider and compare raw vs cleaned")
    p.add_argument("book")
    p.add_argument("--n", type=int, default=3, help="number of pages (default 3)")
    p.add_argument("--provider", choices=["placeholder", "folder", "spec", "local", "openai", "google", "stability", "pollinations", "cloudflare"], help="override interior.source.provider")
    p.add_argument("--model", help="override interior.source.model (e.g. gpt-image-1, imagen-4.0-generate-001, core, @cf/lykon/dreamshaper-8-lcm, Lykon/dreamshaper-8)")
    p.add_argument("--lora", help="local provider: LoRA repo id or repo:file.safetensors (add its trigger word to interior.style_prompt)")
    p.add_argument("--out", help="output folder (default build/image-test)")
    p.set_defaults(func=cmd_image_test)
    p = sub.add_parser("license", help="license keys: machine-id | activate | status (owner: keygen, issue)")
    lsub = p.add_subparsers(dest="license_cmd", required=True)
    lsub.add_parser("machine-id", help="print this computer's id (send it to the owner to get a key)")
    lsub.add_parser("status", help="is a valid license active here?")
    q = lsub.add_parser("activate", help="store a license key after verifying it")
    q.add_argument("token", help="the key, or - to read it from stdin")
    q = lsub.add_parser("keygen", help="owner: create the signing key pair and embed the public key in the package")
    q.add_argument("--out", required=True, help="folder for license_private.pem (outside the repo)")
    q = lsub.add_parser("issue", help="owner: sign a key for one machine")
    q.add_argument("--key", required=True, help="path to license_private.pem")
    q.add_argument("--to", required=True, help="licensee name")
    q.add_argument("--machine", required=True, help="the licensee's machine id, or * for any machine")
    q.add_argument("--days", type=int, default=365, help="validity in days (0 = no expiry)")
    q.add_argument("--feature", action="append", help="feature tags (default: all)")
    p.set_defaults(func=cmd_license)
    p = sub.add_parser("ui", help="open the local web interface (books, build, image-test, publish queue, runs, quota, license)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--books", action="append", help="folder holding <book>/book.yaml projects (repeatable; default: examples/ and books/ in the project)")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_ui)
    p = sub.add_parser("local-setup", help="install CUDA PyTorch + diffusers for the free local image provider and pre-download a model / LoRA")
    p.add_argument("--cuda", default="cu126", help="PyTorch wheel index matching your driver (cu126 for CUDA 12.6; cpu without a GPU)")
    p.add_argument("--model", default="Lykon/dreamshaper-8", help="Hugging Face repo id of an SD 1.5-family checkpoint to pre-download ('' to skip)")
    p.add_argument("--lora", help="Hugging Face repo id (or repo:file.safetensors) of a coloring-book LoRA to pre-download")
    p.add_argument("--skip-install", action="store_true", help="only download the models")
    p.set_defaults(func=cmd_local_setup)
    p = sub.add_parser("draw-preview", help="render vector drawing specs (JSON) to PNG line art for review")
    p.add_argument("folder")
    p.add_argument("--size", default="1000x1500", help="pixel size, e.g. 2550x3300 for 8.5x11 at 300 DPI (default 1000x1500)")
    p.add_argument("--out", help="output folder (default <folder>/_preview)")
    p.set_defaults(func=cmd_draw_preview)
    p = sub.add_parser("build", help="build interior (+ EPUB for story books) + cover and run preflight")
    p.add_argument("book")
    p.add_argument("--images", type=int, help="limit the number of coloring pages (quick test builds)")
    p.add_argument("--reuse-raw", action="store_true", help="coloring books: keep build/raw and only re-clean, re-QA and re-lay-out (no GPU/API unless a page needs a new attempt)")
    p.add_argument("--skip-interior", action="store_true")
    p.add_argument("--skip-cover", action="store_true")
    p.add_argument("--pages", type=int, help="page count when skipping the interior")
    p.add_argument("--no-previewer", action="store_true", help="story books: skip the Kindle Previewer conversion check")
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
    p.add_argument("--out", default=NICHE_DIR)
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
    p.add_argument("--db", default=NICHE_DB)
    p.add_argument("--out", help="write the markdown table to this file")
    p.set_defaults(func=cmd_niche_trends)
    p = nsub.add_parser("concepts", help="concept cards for one keyword")
    p.add_argument("--keyword", required=True)
    p.add_argument("--db", default=NICHE_DB)
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

    story = sub.add_parser("story", help="text books: draft with Claude, check the EPUB")
    ssub = story.add_subparsers(dest="story_cmd", required=True)
    p = ssub.add_parser("draft", help="draft a manuscript from story_brief.yaml with Claude (bible -> outline -> chapters)")
    p.add_argument("--brief", required=True)
    p.add_argument("--out", help="manuscript directory (default <brief dir>/manuscript)")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--polish", action="store_true", help="second editing pass per chapter")
    p.set_defaults(func=cmd_story_draft)
    p = ssub.add_parser("check", help="validate the built EPUB and run Kindle Previewer if installed")
    p.add_argument("book")
    p.add_argument("--epub", help="EPUB path (default: the one in build/)")
    p.add_argument("--no-previewer", action="store_true")
    p.set_defaults(func=cmd_story_check)

    watch = sub.add_parser("watch", help="competitor-watch: track ASINs, mine reviews, compare covers")
    wsub = watch.add_subparsers(dest="watch_cmd", required=True)
    p = wsub.add_parser("add", help="add an ASIN to the watchlist")
    p.add_argument("--watchlist", default=WATCHLIST)
    p.add_argument("--asin", required=True)
    p.add_argument("--label")
    p.add_argument("--niche")
    p.add_argument("--ours", action="store_true", help="mark as one of your own titles")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_watch_add)
    p = wsub.add_parser("snapshot", help="record current BSR/price/ratings for every watched ASIN")
    p.add_argument("--watchlist", default=WATCHLIST)
    p.add_argument("--source", default="fixture", choices=["fixture", "csv", "creators", "apify"])
    p.add_argument("--csv", help="CSV/JSON export for --source csv")
    p.add_argument("--db", default=WATCH_DB)
    p.add_argument("--day", type=int, default=0, help="fixture source: simulated day offset")
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(func=cmd_watch_snapshot)
    p = wsub.add_parser("report", help="latest vs 7/30 days ago with alerts")
    p.add_argument("--watchlist", default=WATCHLIST)
    p.add_argument("--db", default=WATCH_DB)
    p.add_argument("--out", default=WATCH_DIR)
    p.set_defaults(func=cmd_watch_report)
    p = wsub.add_parser("insights", help="mine a reviews export into a differentiation brief")
    p.add_argument("--reviews", required=True, help="text (blank-line separated), JSON or JSONL file")
    p.add_argument("--context", help="what the reviewed books are, for Claude")
    p.add_argument("--no-claude", action="store_true")
    p.add_argument("--out", help="write markdown to this file")
    p.set_defaults(func=cmd_watch_insights)
    p = wsub.add_parser("covers", help="palette and (with Claude) style review of competitor cover images")
    p.add_argument("images", nargs="+", help="image files or a directory")
    p.add_argument("--no-claude", action="store_true")
    p.add_argument("--out", help="write JSON results to this file")
    p.set_defaults(func=cmd_watch_covers)

    fmt_choices = ["ebook", "paperback", "hardcover"]
    publish = sub.add_parser("publish", help="assisted KDP title setup (human-in-the-loop), queue and weekly quota")
    psub = publish.add_subparsers(dest="publish_cmd", required=True)

    def _run_args(pp):
        pp.add_argument("--profile", help="persistent browser profile folder (default: %%LOCALAPPDATA%%/kdp-studio/browser-profile)")
        pp.add_argument("--selectors", help="YAML overriding the default KDP selectors")
        pp.add_argument("--db", default=PUB_DB)
        pp.add_argument("--runs", default=PUB_RUNS, help="folder for checklists, screenshots and flow logs")
        pp.add_argument("--no-preflight", action="store_true", help="skip the preflight re-check of the build files")
        pp.add_argument("--resume-url", help="continue an existing KDP draft instead of creating one: its Details tab URL (https://kdp.amazon.com/en_US/title-setup/<format>/<ID>/details); uses no creation quota")
        pp.add_argument("--start-url", help="testing only: open this URL (a local mock page) instead of the KDP bookshelf")
        pp.add_argument("--headless-local", action="store_true", help="testing only: headless browser, accepted for file:// or localhost start URLs")

    p = psub.add_parser("checklist", help="write the manual-entry sheet for one format")
    p.add_argument("book")
    p.add_argument("--format", default="paperback", choices=fmt_choices)
    p.add_argument("--db", default=PUB_DB)
    p.add_argument("--out")
    p.set_defaults(func=cmd_publish_checklist)
    p = psub.add_parser("quota", help="this week's KDP creation/submission counts per format")
    p.add_argument("--db", default=PUB_DB)
    p.add_argument("--add-created", choices=["ebook", "paperback", "hardcover"], help="record a title you created on KDP by hand this week (drafts count)")
    p.add_argument("--add-submitted", choices=["ebook", "paperback", "hardcover"], help="record a title you submitted on KDP by hand this week")
    p.add_argument("--limit-reached", choices=["ebook", "paperback", "hardcover"], help="record that KDP showed 'Title creation limit reached' for this format")
    p.add_argument("--note", help="free text stored with the record")
    p.set_defaults(func=cmd_publish_quota)
    p = psub.add_parser("queue", help="submission queue")
    qsub = p.add_subparsers(dest="queue_cmd", required=True)
    pa = qsub.add_parser("add")
    pa.add_argument("book")
    pa.add_argument("--format", default="paperback", choices=fmt_choices)
    pa.add_argument("--priority", type=int, default=5, help="1 = first")
    pa.add_argument("--db", default=PUB_DB)
    pa.set_defaults(func=cmd_publish_queue)
    pl = qsub.add_parser("list")
    pl.add_argument("--all", action="store_true", help="include finished items")
    pl.add_argument("--db", default=PUB_DB)
    pl.set_defaults(func=cmd_publish_queue)
    pr = qsub.add_parser("remove")
    pr.add_argument("id", type=int)
    pr.add_argument("--db", default=PUB_DB)
    pr.set_defaults(func=cmd_publish_queue)
    p = psub.add_parser("run", help="open KDP in your browser and fill the title setup for one book")
    p.add_argument("book")
    p.add_argument("--format", default="paperback", choices=fmt_choices)
    _run_args(p)
    p.set_defaults(func=cmd_publish_run)
    p = psub.add_parser("next", help="run the next queued title whose format still has weekly quota")
    p.add_argument("--format", choices=fmt_choices)
    _run_args(p)
    p.set_defaults(func=cmd_publish_next)
    p = psub.add_parser("mark", help="record a title's status/ASIN (live titles are added to competitor-watch as yours)")
    p.add_argument("book")
    p.add_argument("--format", default="paperback", choices=fmt_choices)
    p.add_argument("--status", required=True, choices=["draft", "in_review", "live", "blocked", "unpublished"])
    p.add_argument("--asin")
    p.add_argument("--watchlist", default=WATCHLIST)
    p.add_argument("--db", default=PUB_DB)
    p.set_defaults(func=cmd_publish_mark)
    p = psub.add_parser("probe", help="open KDP, report which selectors match each page you navigate to and dump the form structure")
    p.add_argument("--url")
    p.add_argument("--format", default="paperback", choices=fmt_choices)
    p.add_argument("--profile")
    p.add_argument("--selectors")
    p.add_argument("--out", default=PUB_PROBE, help="folder for the page dumps (.json + .md)")
    p.add_argument("--auto", action="store_true", help="no prompts: open --url, wait, optionally --follow a link, dump once and exit")
    p.add_argument("--follow", help="with --auto: click the link/step with this text before dumping (e.g. 'Rights & Pricing')")
    p.add_argument("--wait", type=float, default=6.0, help="with --auto: seconds to wait for the page (default 6)")
    p.set_defaults(func=cmd_publish_probe)
    p = psub.add_parser("diagnose-cover", help="decode KDP's 'expected cover size X but submitted Y' error into trim/paper/spine")
    p.add_argument("--message", help="the full KDP error text")
    p.add_argument("--expected", help="e.g. 12.313x9.250")
    p.add_argument("--submitted", help="e.g. 10.320x8.250")
    p.add_argument("--pages", type=int, help="interior page count (sharpens the paper-type guess)")
    p.add_argument("--book", help="book.yaml to compare against")
    p.set_defaults(func=cmd_publish_diagnose_cover)
    p = psub.add_parser("selectors", help="print (or write) the default selector map as YAML")
    p.add_argument("--out")
    p.set_defaults(func=cmd_publish_selectors)

    monitor = sub.add_parser("monitor", help="post-publish: title status, your ASINs, Amazon Ads and KDP sales")
    msub2 = monitor.add_subparsers(dest="monitor_cmd", required=True)
    p = msub2.add_parser("check", help="status of every recorded title against KDP timelines")
    p.add_argument("--db", default=PUB_DB)
    p.set_defaults(func=cmd_monitor_check)
    p = msub2.add_parser("ads", help="analyze an Amazon Ads campaign CSV export")
    p.add_argument("--csv", required=True)
    p.add_argument("--target-acos", type=float, default=0.30)
    p.add_argument("--book", help="book.yaml to derive the break-even ACOS from its royalty")
    p.add_argument("--out")
    p.set_defaults(func=cmd_monitor_ads)
    p = msub2.add_parser("sales", help="summarize a KDP royalties/orders report (CSV, or XLSX with openpyxl)")
    p.add_argument("--file", required=True)
    p.add_argument("--since", help="YYYY-MM-DD")
    p.add_argument("--out")
    p.set_defaults(func=cmd_monitor_sales)
    p = msub2.add_parser("report", help="combined report: titles, quota, your ASINs, ads, sales")
    p.add_argument("--db", default=PUB_DB)
    p.add_argument("--watch-db", default=WATCH_DB)
    p.add_argument("--watchlist", default=WATCHLIST)
    p.add_argument("--ads", help="Amazon Ads CSV")
    p.add_argument("--sales", help="KDP royalties CSV/XLSX")
    p.add_argument("--since", help="YYYY-MM-DD for the sales summary")
    p.add_argument("--target-acos", type=float, default=0.30)
    p.add_argument("--book", help="book.yaml for the break-even ACOS")
    p.add_argument("--out", default=MONITOR_DIR)
    p.set_defaults(func=cmd_monitor_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from .env import load_dotenv

    load_dotenv()  # API keys from the project's .env (gitignored); shell variables win
    if getattr(args, "cmd", None) != "license":
        from .license import LicenseError, require_license

        try:
            require_license()  # only bites in builds that embed a public key (kdp license keygen)
        except LicenseError as exc:
            print(f"license: {exc}", file=sys.stderr)
            return 3
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if getattr(args, "book", None):  # relative book paths are looked up in the project folder when CWD has none
        from .paths import project_root, resolve_input

        resolved = resolve_input(args.book)
        if not resolved.exists():
            print(f"error: book file not found: {args.book} (looked in {Path.cwd()} and {project_root()})", file=sys.stderr)
            return 2
        if str(resolved) != str(args.book):
            print(f"note: using {resolved} (relative to the project folder)")
        args.book = str(resolved)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - e.g. Playwright errors; keep the message readable, -v shows the traceback
        if args.verbose:
            raise
        print(f"error: {type(exc).__name__}: {str(exc).splitlines()[0][:300]} (re-run with -v for the traceback)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
