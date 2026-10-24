"""Coloring-book interior pipeline: prompts -> generate -> clean -> QA -> dedupe -> pages -> PDF."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..schema import Book, ColoringInterior
from ..util import ensure_dir, write_json
from .cleanup import place_on_page, prepare_art
from .dedupe import Descriptor, HashEntry, HashLibrary, describe, is_duplicate
from .generate import API_PROVIDERS, ProviderError, ProviderExhausted, make_provider
from .layout import InteriorResult, PageSpec, build_page_sequence, render_interior
from .pagegeom import page_geometry
from .prompts import build_prompts
from .qa import claude_qa, heuristic_qa, content_qa

log = logging.getLogger(__name__)


@dataclass
class AcceptedPage:
    index: int
    prompt: str
    art_path: Path
    descriptor: Descriptor
    attempts: int
    qa: list[dict] = field(default_factory=list)


@dataclass
class RejectedPage:
    index: int
    prompt: str
    reasons: list[str]


def _parse_size(size: str) -> tuple[int, int]:
    w, h = size.lower().split("x")
    return int(w), int(h)


def build_coloring_interior(book: Book, image_limit: int | None = None) -> InteriorResult:
    interior = book.interior
    if not isinstance(interior, ColoringInterior):
        raise TypeError("build_coloring_interior needs a coloring interior")

    build = ensure_dir(book.build_dir)
    raw_dir = ensure_dir(build / "raw")
    art_dir = ensure_dir(build / "art")
    pages_dir = ensure_dir(build / "pages")
    for d in (raw_dir, art_dir, pages_dir):  # leftovers from an earlier build would be mistaken for this one's pages
        for old_file in d.glob("*.png"):
            old_file.unlink()

    n = min(interior.images, image_limit) if image_limit else interior.images
    prompts = build_prompts(interior, n)
    write_json(build / "prompts.json", [p.model_dump() for p in prompts])

    provider = make_provider(interior.source, book.book_dir, negative_prompt=interior.negative_prompt)
    gen_size = _parse_size(interior.source.size)

    planned_total = interior.planned_pages(n)
    trim = book.print_.trim_size
    geo_recto = page_geometry(trim, book.print_.bleed, planned_total, recto=True, art_margin_in=interior.cleanup.art_margin_in)
    art_box = geo_recto.art_size_px

    library_path = Path(interior.dedupe.library)
    library = HashLibrary.load(library_path) if interior.dedupe.enabled else None

    accepted: list[AcceptedPage] = []
    rejected: list[RejectedPage] = []
    for p in prompts:
        reasons_all: list[str] = []
        qa_log: list[dict] = []
        done = False
        for attempt in range(interior.qa.max_retries + 1):
            raw_path = raw_dir / f"{p.index:03d}_{attempt}.png"
            try:
                provider.generate(p.prompt, p.index, attempt, raw_path, gen_size)
            except ProviderExhausted as exc:
                reasons_all.append(str(exc))
                break
            except ProviderError as exc:  # one refused/failed request (moderation, 5xx after retries) costs one attempt, not the book
                log.warning("page %d attempt %d: %s", p.index, attempt, str(exc).splitlines()[0][:200])
                reasons_all.append(f"attempt {attempt}: provider error: {str(exc).splitlines()[0][:160]}")
                continue
            with Image.open(raw_path) as src:
                art = prepare_art(src, art_box, interior.cleanup)

            reasons: list[str] = []
            if interior.qa.heuristic:
                h = heuristic_qa(art, interior.qa)
                qa_log.append({"attempt": attempt, **h.as_dict()})
                reasons.extend(h.reasons)

            if interior.qa.reject_people and not reasons and provider.name in API_PROVIDERS:
                cq = content_qa(raw_path, interior.qa)  # the colour original tells people/nudity apart far better than the thresholded art
                if cq is not None:
                    qa_log.append({"attempt": attempt, **cq.as_dict()})
                    reasons.extend(cq.reasons)

            desc = describe(art)
            if interior.dedupe.enabled and not reasons:
                dd = interior.dedupe
                for a in accepted:
                    dup, d, c = is_duplicate(desc, a.descriptor, dd.max_distance, dd.min_correlation)
                    if dup:
                        reasons.append(f"near-duplicate of page {a.index} in this book (distance {d}, correlation {c:.3f})")
                        break
                if library is not None and not reasons:
                    near = library.find_near(desc, dd.max_distance, dd.min_correlation, exclude_book=book.id)
                    if near:
                        m = near[0]
                        reasons.append(f"near-duplicate of {m.entry.book_id} page {m.entry.page} (distance {m.distance}, correlation {m.correlation:.3f})")

            if interior.qa.claude and not reasons:
                cq = claude_qa(art, interior.qa, interior.audience)
                if cq is not None:
                    qa_log.append({"attempt": attempt, **cq.as_dict()})
                    reasons.extend(cq.reasons)

            if reasons:
                log.info("page %d attempt %d rejected: %s", p.index, attempt, "; ".join(reasons))
                reasons_all.extend(f"attempt {attempt}: {r}" for r in reasons)
                continue

            art_path = art_dir / f"{p.index:03d}.png"
            art.save(art_path, "PNG")
            accepted.append(AcceptedPage(p.index, p.prompt, art_path, desc, attempt + 1, qa_log))
            done = True
            break
        if not done:
            rejected.append(RejectedPage(p.index, p.prompt, reasons_all))

    if not accepted:
        raise RuntimeError("No page passed QA/dedupe; nothing to lay out")

    sequence = build_page_sequence(interior, len(accepted), book.print_.trim, book.print_.paper)
    total = len(sequence)
    for pos, spec in enumerate(sequence, start=1):
        if spec.kind != "image":
            continue
        a = accepted[spec.image_index]
        geo = page_geometry(trim, book.print_.bleed, total, recto=(pos % 2 == 1), art_margin_in=interior.cleanup.art_margin_in)
        with Image.open(a.art_path) as art:
            page = place_on_page(art, geo.page_px, geo.art_box_px)
        page_path = pages_dir / f"page_{pos:03d}.png"
        page.save(page_path, "PNG", dpi=(300, 300))
        spec.image_path = page_path

    result = render_interior(book, sequence, build / "interior.pdf")
    result.requested_images = n
    result.rejected_images = len(rejected)
    if rejected:
        log.warning("%d of %d requested pages were rejected after retries; see interior_manifest.json", len(rejected), n)

    if library is not None:
        library.replace_book(book.id, [HashEntry(book.id, a.index, a.descriptor, provider.name) for a in accepted])
        library.save()

    manifest = {
        "book_id": book.id,
        "pdf": str(result.pdf_path),
        "total_pages": result.total_pages,
        "image_pages": result.image_pages,
        "requested_images": n,
        "rejected": [{"index": r.index, "prompt": r.prompt, "reasons": r.reasons} for r in rejected],
        "accepted": [
            {"index": a.index, "prompt": a.prompt, "art": a.art_path.name, "phash": f"{a.descriptor.phash:016x}", "attempts": a.attempts, "qa": a.qa}
            for a in accepted
        ],
        "page_map": result.page_map,
        "fonts": result.fonts,
        "ai_disclosure": book.ai_disclosure(),
    }
    write_json(build / "interior_manifest.json", manifest)
    return result
