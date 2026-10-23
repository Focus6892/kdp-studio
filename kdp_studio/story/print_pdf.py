"""Print interior for text books with reportlab Platypus.

- page size = trim (no bleed; text-only books never need it)
- mirrored margins: gutter on the inside, raised to KDP's minimum for the final page count
- chapters start on right-hand pages (a blank verso is inserted when needed)
- running heads (author verso / title recto) and centred page numbers, none on
  front matter, chapter openers or blank pages
- every font is an embedded TrueType subset; reportlab's default Helvetica is replaced
- final page count is made even (and >= 24 when pad_to_min_pages) with blank pages

Layout is computed in up to four passes: a pass measures where each section lands,
then blanks/gutter are adjusted until the result is stable.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab import rl_config
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer

from .. import specs
from ..fonts import find_font_family
from ..schema import Book, StoryInterior
from .manuscript import Manuscript

log = logging.getLogger(__name__)

rl_config.useA85 = 0
_registered: dict[Path, str] = {}


def _register(path: Path) -> str:
    if path in _registered:
        return _registered[path]
    name = "KDP_" + re.sub(r"\W+", "_", path.stem)
    pdfmetrics.registerFont(TTFont(name, str(path)))
    _registered[path] = name
    return name


def register_body_family(preferred: str | None) -> dict[str, str]:
    fam = find_font_family(preferred)
    names = {k: _register(p) for k, p in fam.items()}
    pdfmetrics.registerFontFamily(names["regular"], normal=names["regular"], bold=names["bold"], italic=names["italic"], boldItalic=names["bolditalic"])
    return names


# --------------------------------------------------------------------------- HTML -> flowables
INLINE_MAP = {"em": "i", "strong": "b", "i": "i", "b": "b"}


def inline_markup(el: ET.Element) -> str:
    """Serialize an element's children into reportlab Paragraph mini-HTML."""
    parts: list[str] = [escape(el.text or "")]
    for child in el:
        tag = child.tag.split("}")[-1]
        inner = inline_markup(child)
        if tag in INLINE_MAP:
            parts.append(f"<{INLINE_MAP[tag]}>{inner}</{INLINE_MAP[tag]}>")
        elif tag == "br":
            parts.append("<br/>")
        else:  # a, span, code, sup... -> plain text
            parts.append(inner)
        parts.append(escape(child.tail or ""))
    return "".join(parts)


@dataclass
class Styles:
    body: ParagraphStyle
    body_first: ParagraphStyle
    scene: ParagraphStyle
    quote: ParagraphStyle
    subhead: ParagraphStyle
    chapter_num: ParagraphStyle
    chapter_title: ParagraphStyle
    title: ParagraphStyle
    subtitle: ParagraphStyle
    author: ParagraphStyle
    small: ParagraphStyle
    centered_italic: ParagraphStyle
    plain_heading: ParagraphStyle


def make_styles(interior: StoryInterior, fonts: dict[str, str]) -> Styles:
    size = interior.font_size_pt
    lead = size * interior.leading
    body = ParagraphStyle("body", fontName=fonts["regular"], fontSize=size, leading=lead, alignment=TA_JUSTIFY, firstLineIndent=interior.paragraph_indent_in * inch, allowWidows=0, allowOrphans=0)
    return Styles(
        body=body,
        body_first=ParagraphStyle("body_first", parent=body, firstLineIndent=0),
        scene=ParagraphStyle("scene", parent=body, alignment=TA_CENTER, firstLineIndent=0, spaceBefore=lead * 0.6, spaceAfter=lead * 0.6),
        quote=ParagraphStyle("quote", parent=body, fontName=fonts["italic"], firstLineIndent=0, leftIndent=0.4 * inch, rightIndent=0.4 * inch, spaceBefore=lead * 0.4, spaceAfter=lead * 0.4),
        subhead=ParagraphStyle("subhead", parent=body, fontName=fonts["bold"], firstLineIndent=0, alignment=TA_LEFT, spaceBefore=lead, spaceAfter=lead * 0.4, keepWithNext=1),
        chapter_num=ParagraphStyle("chapter_num", fontName=fonts["regular"], fontSize=size * 0.95, leading=size * 1.3, alignment=TA_CENTER, textTransform="uppercase", spaceAfter=size * 0.8),
        chapter_title=ParagraphStyle("chapter_title", fontName=fonts["bold"], fontSize=size * 1.9, leading=size * 2.3, alignment=TA_CENTER, spaceAfter=lead * 2.2),
        title=ParagraphStyle("title", fontName=fonts["bold"], fontSize=size * 2.6, leading=size * 3.0, alignment=TA_CENTER, spaceAfter=size),
        subtitle=ParagraphStyle("subtitle", fontName=fonts["italic"], fontSize=size * 1.25, leading=size * 1.6, alignment=TA_CENTER, spaceAfter=size * 3),
        author=ParagraphStyle("author", fontName=fonts["regular"], fontSize=size * 1.3, leading=size * 1.7, alignment=TA_CENTER),
        small=ParagraphStyle("small", fontName=fonts["regular"], fontSize=max(specs.MIN_FONT_PT, size * 0.8), leading=max(specs.MIN_FONT_PT, size * 0.8) * 1.35, alignment=TA_LEFT, spaceAfter=size * 0.6),
        centered_italic=ParagraphStyle("centered_italic", fontName=fonts["italic"], fontSize=size * 1.05, leading=lead, alignment=TA_CENTER, spaceAfter=lead * 0.5),
        plain_heading=ParagraphStyle("plain_heading", fontName=fonts["bold"], fontSize=size * 1.5, leading=size * 1.9, alignment=TA_CENTER, spaceAfter=lead * 1.5),
    )


def html_to_flowables(html: str, st: Styles) -> list[Flowable]:
    root = ET.fromstring(f"<root>{html}</root>")
    out: list[Flowable] = []
    first = True
    for el in root:
        tag = el.tag.split("}")[-1]
        if tag == "p":
            text = inline_markup(el).strip()
            if not text:
                continue
            out.append(Paragraph(text, st.body_first if first else st.body))
            first = False
        elif tag == "hr":
            out.append(Paragraph("* * *", st.scene))
            first = True
        elif tag in ("h1", "h2", "h3", "h4"):
            out.append(Paragraph(inline_markup(el), st.subhead))
            first = True
        elif tag == "blockquote":
            for p in el.iter():
                if p.tag.split("}")[-1] == "p":
                    out.append(Paragraph(inline_markup(p), st.quote))
            first = True
        elif tag in ("ul", "ol"):
            for i, li in enumerate([c for c in el if c.tag.split("}")[-1] == "li"], start=1):
                bullet = f"{i}." if tag == "ol" else "•"
                out.append(Paragraph(f"{bullet} {inline_markup(li)}", st.body_first))
            first = True
        else:
            text = inline_markup(el).strip()
            if text:
                out.append(Paragraph(text, st.body_first))
    return out


# --------------------------------------------------------------------------- doc template
class MarkPage(Flowable):
    """Zero-height flowable that records the page it lands on."""

    def __init__(self, kind: str, index: int | None = None):
        super().__init__()
        self.kind, self.index = kind, index

    def wrap(self, aw, ah):
        return (0, 0)

    def draw(self):
        doc = getattr(self.canv, "_doctemplate", None)
        if doc is not None and hasattr(doc, "record_mark"):
            doc.record_mark(self.kind, self.index, self.canv.getPageNumber())


class StoryDoc(BaseDocTemplate):
    def __init__(self, filename: str, *, page_size: tuple[float, float], margins: tuple[float, float, float, float], head_font: str, head_size: float, title: str, author: str, running_heads: bool, page_numbers: bool, blank_pages: set[int], n_front: int = 0, **kw):
        super().__init__(filename, pagesize=page_size, title=title, author=author, **kw)
        self.marks: dict[str, set[int]] = {}
        self.section_pages: dict[int, int] = {}
        self.blank_pages = blank_pages
        self.n_front = n_front
        self.head_font, self.head_size = head_font, head_size
        self.book_title, self.book_author = title, author
        self.running_heads, self.page_numbers = running_heads, page_numbers
        w, h = page_size
        inside, outside, top, bottom = margins
        self._top, self._bottom = top, bottom
        recto = Frame(inside, bottom, w - inside - outside, h - top - bottom, id="recto", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        verso = Frame(outside, bottom, w - inside - outside, h - top - bottom, id="verso", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="recto", frames=[recto], onPageEnd=self._furniture, autoNextPageTemplate="verso"),
            PageTemplate(id="verso", frames=[verso], onPageEnd=self._furniture, autoNextPageTemplate="recto"),
        ])

    def record_mark(self, kind: str, index: int | None, page: int) -> None:
        self.marks.setdefault(kind, set()).add(page)
        if kind == "section" and index is not None:
            self.section_pages[index] = page

    def _furniture(self, canv, doc) -> None:
        page = doc.page
        if page in self.blank_pages:
            return
        # The section whose opener is the latest one at or before this page; marks for the
        # current page are recorded while it is drawn, so they are known here (onPageEnd).
        started = [idx for idx, p in self.section_pages.items() if p <= page]
        if not started or max(started) < self.n_front:
            return  # front matter carries neither running heads nor page numbers
        opener = page in self.marks.get("section", set())
        w, h = self.pagesize
        canv.saveState()
        canv.setFont(self.head_font, self.head_size)
        if self.running_heads and not opener:
            text = self.book_author if page % 2 == 0 else self.book_title
            canv.drawCentredString(w / 2, h - self._top + 0.32 * inch, text.upper())
        if self.page_numbers:
            canv.drawCentredString(w / 2, self._bottom - 0.4 * inch, str(page))
        canv.restoreState()


# --------------------------------------------------------------------------- content plan
@dataclass
class Section:
    kind: str  # title | copyright | dedication | epigraph | chapter | about_author | also_by | review_cta
    flowables_factory: object  # callable(Styles) -> list[Flowable]
    recto: bool = True


@dataclass
class PrintResult:
    pdf_path: Path
    pages: int
    content_pages: int
    padded_pages: int
    gutter_in: float
    inside_margin_in: float
    fonts: dict[str, str]
    section_pages: dict[int, int] = field(default_factory=dict)
    chapter_pages: list[int] = field(default_factory=list)
    blank_pages: list[int] = field(default_factory=list)


def build_sections(book: Book, ms: Manuscript) -> tuple[list[Section], int]:
    """Ordered sections and the number of leading front-matter sections."""
    interior = book.interior
    assert isinstance(interior, StoryInterior)
    md = book.metadata
    year = dt.date.today().year
    sections: list[Section] = []
    trim = book.print_.trim_size
    avail = (trim.height_in - interior.margins.top - interior.margins.bottom) * inch  # usable frame height

    if "title" in interior.front_matter:
        def title_page(st: Styles):
            items = [Spacer(1, avail * 0.28), Paragraph(escape(md.title), st.title)]
            if md.subtitle:
                items.append(Paragraph(escape(md.subtitle), st.subtitle))
            else:
                items.append(Spacer(1, avail * 0.12))
            items.append(Paragraph(escape(md.author), st.author))
            return items
        sections.append(Section("title", title_page, recto=True))
    if "copyright" in interior.front_matter:
        notice = interior.copyright_notice or (
            "All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any "
            "means without the prior written permission of the author, except for brief quotations in reviews."
        )
        def copyright_page(st: Styles):
            return [
                Spacer(1, avail * 0.5),
                Paragraph(escape(md.full_title), st.small),
                Paragraph(f"Copyright © {year} {escape(md.author)}", st.small),
                Paragraph(escape(notice), st.small),
                Paragraph("This is a work of fiction. Names, characters, places and incidents are products of the author’s imagination or are used fictitiously.", st.small),
            ]
        sections.append(Section("copyright", copyright_page, recto=False))
    if "dedication" in interior.front_matter and ms.extras.get("dedication"):
        sections.append(Section("dedication", lambda st: [Spacer(1, avail * 0.38), *[Paragraph(inline_markup(e), st.centered_italic) for e in ET.fromstring(f"<r>{ms.extras['dedication']}</r>")]], recto=True))
    if "epigraph" in interior.front_matter and ms.extras.get("epigraph"):
        def epigraph(st: Styles):
            items = [Spacer(1, avail * 0.38), *[Paragraph(inline_markup(e), st.centered_italic) for e in ET.fromstring(f"<r>{ms.extras['epigraph']}</r>")]]
            if interior.epigraph_source:
                items.append(Paragraph("— " + escape(interior.epigraph_source), st.author))
            return items
        sections.append(Section("epigraph", epigraph, recto=True))
    n_front = len(sections)

    for ch in ms.chapters:
        def chapter(st: Styles, ch=ch):
            head: list[Flowable] = [Spacer(1, avail * 0.18)]
            if interior.numbered_chapters and interior.chapter_label:
                head.append(Paragraph(f"{escape(interior.chapter_label)} {ch.number}", st.chapter_num))
            head.append(Paragraph(escape(ch.title), st.chapter_title))
            body = html_to_flowables(ch.html, st)
            return [KeepTogether(head + body[:1]), *body[1:]]
        sections.append(Section("chapter", chapter, recto=interior.chapter_start_recto))

    back_titles = {"about_author": "About the Author", "also_by": f"Also by {md.author}", "review_cta": "A Note from the Author"}
    for kind in interior.back_matter:
        html = ms.extras.get(kind)
        if not html:
            continue
        def back(st: Styles, kind=kind, html=html):
            return [Spacer(1, avail * 0.18), Paragraph(escape(back_titles[kind]), st.plain_heading), *html_to_flowables(html, st)]
        sections.append(Section(kind, back, recto=True))
    return sections, n_front


def _story_flowables(sections: list[Section], n_front: int, st: Styles, blanks_before: set[int]) -> list[Flowable]:
    flow: list[Flowable] = []
    for idx, sec in enumerate(sections):
        if idx > 0:
            flow.append(PageBreak())
            if idx in blanks_before:
                flow.append(PageBreak())  # a second break leaves one blank page
        flow.append(MarkPage("section", idx))
        flow.extend(sec.flowables_factory(st))
        if idx == n_front - 1:
            flow.append(MarkPage("front_end"))
    return flow


def _build_once(book: Book, ms: Manuscript, out_path: Path, fonts: dict[str, str], inside_in: float, blanks_before: set[int], blank_pages: set[int]) -> StoryDoc:
    interior = book.interior
    assert isinstance(interior, StoryInterior)
    trim = book.print_.trim_size
    page_size = (trim.width_in * inch, trim.height_in * inch)
    m = interior.margins
    st = make_styles(interior, fonts)
    sections, n_front = build_sections(book, ms)
    doc = StoryDoc(
        str(out_path),
        page_size=page_size,
        margins=(inside_in * inch, m.outside * inch, m.top * inch, m.bottom * inch),
        head_font=fonts["regular"],
        head_size=max(specs.MIN_FONT_PT, interior.font_size_pt * 0.78),
        title=book.metadata.title,
        author=book.metadata.author,
        running_heads=interior.running_heads,
        page_numbers=interior.page_numbers,
        blank_pages=blank_pages,
        n_front=n_front,
    )
    old = rl_config.canvas_basefontname
    rl_config.canvas_basefontname = fonts["regular"]  # replaces the non-embedded Helvetica default
    try:
        doc.build(_story_flowables(sections, n_front, st, blanks_before))
    finally:
        rl_config.canvas_basefontname = old
    return doc


def _plan_blanks(section_pages: dict[int, int], recto_flags: list[bool]) -> tuple[set[int], set[int]]:
    """Which sections need a blank page before them so they open on an odd page, and which pages become blank."""
    blanks_before: set[int] = set()
    blank_pages: set[int] = set()
    offset = 0
    for idx in sorted(section_pages):
        page = section_pages[idx] + offset
        if recto_flags[idx] and idx > 0 and page % 2 == 0:
            blanks_before.add(idx)
            blank_pages.add(page)
            offset += 1
    return blanks_before, blank_pages


def build_print_pdf(book: Book, ms: Manuscript, out_path: Path) -> PrintResult:
    interior = book.interior
    assert isinstance(interior, StoryInterior)
    if book.print_.bleed:
        log.warning("Text-only interiors are built without bleed; ignoring print.bleed=true")
        book.print_.bleed = False
    fonts = register_body_family(interior.body_font)
    sections, _ = build_sections(book, ms)
    recto_flags = [s.recto for s in sections]

    # 1) measuring passes without blank pages: find where sections land and which gutter
    #    the final page count requires (a wider gutter reflows text, so re-measure);
    # 2) one final pass with the planned blank pages.
    inside = max(interior.margins.inside, specs.gutter_in(specs.MIN_PAGES))
    blanks_before: set[int] = set()
    blank_pages: set[int] = set()
    for _ in range(4):
        measure = _build_once(book, ms, out_path, fonts, inside, set(), set())
        blanks_before, blank_pages = _plan_blanks(measure.section_pages, recto_flags)
        est = measure.page + len(blank_pages)
        est_total = est + est % 2
        if interior.pad_to_min_pages:
            est_total = max(est_total, specs.MIN_PAGES)
        required = specs.gutter_in(min(est_total, 828))
        if required > inside + 1e-9:
            inside = required
            continue
        break
    doc = _build_once(book, ms, out_path, fonts, inside, blanks_before, blank_pages)
    content_pages = doc.page

    # Make the page count even (and at least 24) with trailing blank pages.
    total = content_pages
    target = total + (total % 2)
    if interior.pad_to_min_pages:
        target = max(target, specs.MIN_PAGES)
    padded = target - total
    if padded:
        reader = PdfReader(str(out_path))
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        w, h = float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)
        for _ in range(padded):
            writer.add_blank_page(width=w, height=h)
        writer.add_metadata({"/Title": book.metadata.title, "/Author": book.metadata.author})
        with out_path.open("wb") as fh:
            writer.write(fh)
        total = target

    chapter_pages = sorted(p for i, p in doc.section_pages.items() if sections[i].kind == "chapter")
    return PrintResult(
        pdf_path=out_path,
        pages=total,
        content_pages=content_pages,
        padded_pages=padded,
        gutter_in=specs.gutter_in(total),
        inside_margin_in=inside,
        fonts=fonts,
        section_pages=dict(doc.section_pages),
        chapter_pages=chapter_pages,
        blank_pages=sorted(blank_pages),
    )
