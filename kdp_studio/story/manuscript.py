"""Load a Markdown manuscript: chapters/*.md plus optional front/back matter files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import markdown

from ..schema import Book, StoryInterior

# Smarty normally emits HTML entities (&ldquo;) which are invalid in EPUB3 XHTML; use real characters.
# Both "--" and "---" become an em dash, the convention in US fiction manuscripts.
SMARTY_SUBSTITUTIONS = {
    "left-single-quote": "‘",
    "right-single-quote": "’",
    "left-double-quote": "“",
    "right-double-quote": "”",
    "left-angle-quote": "«",
    "right-angle-quote": "»",
    "ellipsis": "…",
    "ndash": "—",
    "mdash": "—",
}

EXTRA_FILES = {
    "dedication": ("dedication.md",),
    "epigraph": ("epigraph.md",),
    "about_author": ("about-author.md", "about_author.md", "about-the-author.md"),
    "also_by": ("also-by.md", "also_by.md"),
    "review_cta": ("review-cta.md", "review_cta.md"),
}

LANGUAGE_CODES = {
    "english": "en", "vietnamese": "vi", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "portuguese": "pt", "dutch": "nl", "japanese": "ja", "polish": "pl", "swedish": "sv",
}


def language_code(name: str) -> str:
    n = name.strip().lower()
    if len(n) in (2, 5) and (len(n) == 2 or n[2] in "-_"):
        return n.replace("_", "-")
    return LANGUAGE_CODES.get(n, "en")


def md_to_html(text: str, smart_quotes: bool = True) -> str:
    exts = ["sane_lists"]
    cfg: dict = {}
    if smart_quotes:
        exts.append("smarty")
        cfg["smarty"] = {"substitutions": SMARTY_SUBSTITUTIONS, "smart_angled_quotes": False}
    md = markdown.Markdown(extensions=exts, extension_configs=cfg, output_format="xhtml")
    return md.convert(text).strip()


def split_title(text: str) -> tuple[str | None, str]:
    """Take the first '# Heading' line as the chapter title; return (title, rest)."""
    lines = text.lstrip("﻿").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if m:
            return m.group(1).strip(), "\n".join(lines[i + 1 :]).strip()
        break
    return None, text.strip()


def title_from_filename(path: Path) -> str:
    stem = re.sub(r"^\d+[-_.\s]*", "", path.stem)
    return " ".join(w.capitalize() for w in re.split(r"[-_\s]+", stem) if w) or path.stem


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "chapter"


def count_words(text: str) -> int:
    plain = re.sub(r"<[^>]+>", " ", text)
    return len(re.findall(r"[\w'’-]+", plain))


@dataclass
class Chapter:
    number: int
    title: str
    markdown: str
    html: str
    words: int
    slug: str
    source: Path | None = None


@dataclass
class Manuscript:
    chapters: list[Chapter]
    extras: dict[str, str] = field(default_factory=dict)  # html by kind (dedication, epigraph, about_author, ...)
    extras_md: dict[str, str] = field(default_factory=dict)

    @property
    def words(self) -> int:
        return sum(c.words for c in self.chapters)


def load_manuscript(book: Book) -> Manuscript:
    interior = book.interior
    if not isinstance(interior, StoryInterior):
        raise TypeError("load_manuscript needs a story interior")
    root = book.resolve(interior.manuscript_dir)
    files = sorted(root.glob(interior.chapters_glob))
    if not files:
        raise FileNotFoundError(f"No chapter files matching {interior.chapters_glob} under {root}")
    chapters: list[Chapter] = []
    for n, path in enumerate(files, start=1):
        text = path.read_text(encoding="utf-8")
        title, body = split_title(text)
        title = title or title_from_filename(path)
        html = md_to_html(body, interior.smart_quotes)
        chapters.append(Chapter(n, title, body, html, count_words(html), slugify(title), path))

    extras_md: dict[str, str] = {}
    inline = {
        "dedication": interior.dedication,
        "epigraph": interior.epigraph,
        "about_author": interior.about_author,
        "review_cta": interior.review_cta,
        "also_by": "\n".join(f"- {t}" for t in interior.also_by) if interior.also_by else None,
    }
    for kind, names in EXTRA_FILES.items():
        if inline.get(kind):
            extras_md[kind] = inline[kind]  # type: ignore[assignment]
            continue
        for name in names:
            p = root / name
            if p.is_file():
                extras_md[kind] = split_title(p.read_text(encoding="utf-8"))[1]
                break
    extras = {k: md_to_html(v, interior.smart_quotes) for k, v in extras_md.items()}
    return Manuscript(chapters, extras, extras_md)
