"""Story interior pipeline: manuscript -> print PDF + EPUB (+ checks, manifest)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..findings import FindingList
from ..schema import Book, StoryInterior
from ..util import ensure_dir, write_json
from .epub import build_epub, validate_epub
from .kindle_previewer import run_kindle_previewer
from .manuscript import Manuscript, load_manuscript
from .print_pdf import PrintResult, build_print_pdf

log = logging.getLogger(__name__)


@dataclass
class StoryResult:
    manuscript: Manuscript
    print_result: PrintResult | None
    epub_path: Path | None
    pages: int | None
    words: int
    findings: FindingList = field(default_factory=FindingList)
    manifest_path: Path | None = None

    @property
    def pdf_path(self) -> Path | None:
        return self.print_result.pdf_path if self.print_result else None


def story_findings(book: Book, ms: Manuscript, pr: PrintResult | None) -> FindingList:
    interior = book.interior
    assert isinstance(interior, StoryInterior)
    f = FindingList()
    if interior.min_words and ms.words < interior.min_words:
        f.warning("story.short", f"Manuscript has {ms.words:,} words; target minimum is {interior.min_words:,}.", "interior.min_words")
    if ms.words < 2000:
        f.info("story.very_short", f"{ms.words:,} words is a very short read; KDP removes content that is 'too short' for its price and description.", "manuscript")
    if pr and pr.padded_pages:
        f.info("story.padded", f"{pr.padded_pages} blank page(s) appended so the print interior has {pr.pages} pages (even, >= 24).", pr.pdf_path.name)
    if pr and pr.inside_margin_in > interior.margins.inside + 1e-9:
        f.info("story.gutter_raised", f"Inside margin raised to {pr.inside_margin_in:.3f} in to meet KDP's gutter for {pr.pages} pages.", pr.pdf_path.name)
    return f


def write_story_manifest(book: Book, res: StoryResult) -> Path:
    build = ensure_dir(book.build_dir)
    pr = res.print_result
    data = {
        "book_id": book.id,
        "words": res.words,
        "chapters": [{"number": c.number, "title": c.title, "words": c.words, "file": c.source.name if c.source else None} for c in res.manuscript.chapters],
        "epub": str(res.epub_path) if res.epub_path else None,
        "print_pdf": str(pr.pdf_path) if pr else None,
        "pages": res.pages,
        "content_pages": pr.content_pages if pr else None,
        "padded_pages": pr.padded_pages if pr else None,
        "chapter_pages": pr.chapter_pages if pr else None,
        "blank_pages": pr.blank_pages if pr else None,
        "inside_margin_in": pr.inside_margin_in if pr else None,
        "fonts": pr.fonts if pr else None,
        "findings": [x.as_dict() for x in res.findings],
        "ai_disclosure": book.ai_disclosure(),
    }
    path = build / "story_manifest.json"
    write_json(path, data)
    return path


def build_story(book: Book, cover_jpg: Path | None = None, build_pdf: bool = True, build_ebook: bool = True, run_previewer: bool | None = None) -> StoryResult:
    interior = book.interior
    if not isinstance(interior, StoryInterior):
        raise TypeError("build_story needs a story interior")
    build = ensure_dir(book.build_dir)
    ms = load_manuscript(book)
    log.info("manuscript: %d chapters, %d words", len(ms.chapters), ms.words)

    pr = build_print_pdf(book, ms, build / "interior.pdf") if build_pdf else None
    epub_path = None
    findings = FindingList()
    if build_ebook:
        cover = cover_jpg if cover_jpg else (build / "cover_ebook.jpg" if (build / "cover_ebook.jpg").is_file() else None)
        epub_path = build_epub(book, ms, build / f"{book.id}.epub", cover)
        findings.extend(validate_epub(epub_path))
        if run_previewer if run_previewer is not None else interior.kindle_previewer:
            findings.extend(run_kindle_previewer(epub_path, build / "kindle_previewer"))
    findings.extend(story_findings(book, ms, pr))

    res = StoryResult(ms, pr, epub_path, pr.pages if pr else None, ms.words, findings)
    res.manifest_path = write_story_manifest(book, res)
    return res


def rebuild_epub(book: Book, res: StoryResult, cover_jpg: Path | None, run_previewer: bool | None = None) -> StoryResult:
    """Re-package the EPUB (e.g. once the eBook cover exists) and refresh its checks."""
    interior = book.interior
    assert isinstance(interior, StoryInterior)
    build = ensure_dir(book.build_dir)
    epub_path = build_epub(book, res.manuscript, build / f"{book.id}.epub", cover_jpg)
    kept = FindingList()
    kept.items = [x for x in res.findings if not x.code.startswith(("epub.", "kindle_previewer."))]
    kept.extend(validate_epub(epub_path))
    if run_previewer if run_previewer is not None else interior.kindle_previewer:
        kept.extend(run_kindle_previewer(epub_path, build / "kindle_previewer"))
    res.epub_path = epub_path
    res.findings = kept
    res.manifest_path = write_story_manifest(book, res)
    return res
