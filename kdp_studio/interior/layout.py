"""Lay out the interior PDF with reportlab: text pages with embedded TrueType
fonts plus full-page coloring images at exactly the KDP page size."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from reportlab import rl_config
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

# Embed image streams as binary instead of ASCII85 text (about 25% smaller files).
rl_config.useA85 = 0

from .. import specs
from ..fonts import find_font
from ..schema import Book, ColoringInterior
from .pagegeom import PageGeometry, page_geometry

_registered: dict[Path, str] = {}


def register_font(path: Path) -> str:
    if path in _registered:
        return _registered[path]
    name = "KDP_" + re.sub(r"\W+", "_", path.stem)
    pdfmetrics.registerFont(TTFont(name, str(path)))
    _registered[path] = name
    return name


@dataclass
class PageSpec:
    kind: str  # title | copyright | belongs_to | test_colors | blank | thank_you | image
    image_index: int | None = None
    image_path: Path | None = None


@dataclass
class InteriorResult:
    pdf_path: Path
    total_pages: int
    image_pages: int
    page_map: list[dict] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    requested_images: int | None = None
    rejected_images: int = 0


def build_page_sequence(interior: ColoringInterior, image_count: int, trim_key: str, paper: str) -> list[PageSpec]:
    seq: list[PageSpec] = [PageSpec(k) for k in interior.front_matter]
    for i in range(image_count):
        seq.append(PageSpec("image", image_index=i))
        if interior.single_sided:
            seq.append(PageSpec(interior.back_page))
    seq.extend(PageSpec(k) for k in interior.back_matter)
    while len(seq) < specs.MIN_PAGES or len(seq) % 2 == 1:
        seq.append(PageSpec("blank"))
    lo, hi = specs.page_range(trim_key, paper)
    if len(seq) > hi:
        raise ValueError(f"{len(seq)} pages exceeds the KDP maximum of {hi} for {trim_key}/{paper}")
    return seq


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if pdfmetrics.stringWidth(trial, font, size) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _fit_size(text: str, font: str, max_width: float, max_size: float, min_size: float = 14.0) -> float:
    size = max_size
    while size > min_size:
        if all(pdfmetrics.stringWidth(line, font, size) <= max_width for line in _wrap(text, font, size, max_width)) and len(_wrap(text, font, size, max_width)) <= 3:
            return size
        size -= 2
    return min_size


def _draw_block(c, lines: list[str], font: str, size: float, x_center: float, y_top: float, leading: float | None = None) -> float:
    leading = leading or size * 1.25
    c.setFont(font, size)
    y = y_top
    for line in lines:
        c.drawCentredString(x_center, y, line)
        y -= leading
    return y


def _safe_rect_pt(geo: PageGeometry) -> tuple[float, float, float, float]:
    """Safe box as (x, y_bottom, width, height) in PDF points (origin bottom-left)."""
    x0, y0, x1, y1 = geo.safe_box_in
    return specs.pt(x0), specs.pt(geo.page_h_in - y1), specs.pt(x1 - x0), specs.pt(y1 - y0)


def render_interior(book: Book, sequence: list[PageSpec], out_pdf: Path) -> InteriorResult:
    assert isinstance(book.interior, ColoringInterior)
    interior = book.interior
    trim = book.print_.trim_size
    bleed = book.print_.bleed
    total = len(sequence)

    display_font = register_font(find_font(book.cover.title_font, "display"))
    body_font = register_font(find_font(book.cover.body_font, "regular"))
    bold_font = register_font(find_font(None, "bold"))
    script_font = register_font(find_font(book.cover.author_font, "script"))
    condensed_font = register_font(find_font(book.cover.subtitle_font, "condensed"))

    geo0 = page_geometry(trim, bleed, total, recto=True, art_margin_in=interior.cleanup.art_margin_in)
    # initialFontName replaces reportlab's default Helvetica (a non-embedded base-14 font
    # that would otherwise be referenced on every page and flagged by KDP).
    c = rl_canvas.Canvas(str(out_pdf), pagesize=geo0.page_pt, initialFontName=body_font)
    c.setPageCompression(1)
    c.setTitle(book.metadata.full_title)
    c.setAuthor(book.metadata.author)

    page_map: list[dict] = []
    year = dt.date.today().year
    for idx, spec in enumerate(sequence, start=1):
        recto = idx % 2 == 1
        geo = page_geometry(trim, bleed, total, recto=recto, art_margin_in=interior.cleanup.art_margin_in)
        sx, sy, sw, sh = _safe_rect_pt(geo)
        cx = sx + sw / 2
        entry = {"page": idx, "kind": spec.kind, "recto": recto}

        if spec.kind == "image":
            assert spec.image_path is not None
            w_pt, h_pt = geo.page_pt
            c.drawImage(ImageReader(str(spec.image_path)), 0, 0, width=w_pt, height=h_pt)
            entry["image"] = str(spec.image_path.name)
            entry["image_index"] = spec.image_index
        elif spec.kind == "title":
            # a thin rounded frame, the title in the display face, the subtitle in condensed caps, the author in script
            c.setLineWidth(2.0)
            c.roundRect(sx + sw * 0.06, sy + sh * 0.08, sw * 0.88, sh * 0.84, 18, stroke=1, fill=0)
            c.setLineWidth(0.8)
            c.roundRect(sx + sw * 0.075, sy + sh * 0.095, sw * 0.85, sh * 0.81, 14, stroke=1, fill=0)
            size = _fit_size(book.metadata.title, display_font, sw * 0.78, 72)
            lines = _wrap(book.metadata.title, display_font, size, sw * 0.78)
            y = sy + sh * 0.66 + (len(lines) - 1) * size * 0.55
            y = _draw_block(c, lines, display_font, size, cx, y, leading=size * 1.0)
            if book.metadata.subtitle:
                sub_size = _fit_size(book.metadata.subtitle.upper(), condensed_font, sw * 0.74, 26, 14)
                sub_lines = _wrap(book.metadata.subtitle.upper(), condensed_font, sub_size, sw * 0.74)
                y = _draw_block(c, sub_lines, condensed_font, sub_size, cx, y - 14)
            c.setLineWidth(1.2)
            c.line(cx - sw * 0.12, sy + sh * 0.31, cx + sw * 0.12, sy + sh * 0.31)
            c.setFont(script_font, 26)
            c.drawCentredString(cx, sy + sh * 0.24, book.metadata.author)
        elif spec.kind == "copyright":
            notice = interior.copyright_notice or (
                "All rights reserved. No part of this publication may be reproduced, distributed, or "
                "transmitted in any form or by any means without the prior written permission of the publisher, "
                "except for brief quotations in reviews and certain other noncommercial uses permitted by copyright law."
            )
            text = f"{book.metadata.full_title}\n\nCopyright © {year} {book.metadata.author}\n\n{notice}"
            size = 9.5
            lines = _wrap(text, body_font, size, sw * 0.8)
            _draw_block(c, lines, body_font, size, cx, sy + sh * 0.28 + len(lines) * size * 1.3 / 2)
        elif spec.kind == "belongs_to":
            c.setLineWidth(2.0)
            c.roundRect(sx + sw * 0.12, sy + sh * 0.40, sw * 0.76, sh * 0.26, 16, stroke=1, fill=0)
            c.setFont(display_font, 34)
            c.drawCentredString(cx, sy + sh * 0.57, "This book belongs to")
            c.setLineWidth(1.5)
            c.line(sx + sw * 0.22, sy + sh * 0.47, sx + sw * 0.78, sy + sh * 0.47)
        elif spec.kind == "test_colors":
            c.setFont(display_font, 30)
            c.drawCentredString(cx, sy + sh * 0.9, "Test your colors")
            cols, rows = 5, 7
            ax0, ay0, ax1, ay1 = geo.art_box_in
            gx0, gy_top = specs.pt(ax0), specs.pt(geo.page_h_in - ay0) - 60
            gw, gh = specs.pt(ax1 - ax0), specs.pt(ay1 - ay0) - 60
            r = min(gw / cols, gh / rows) * 0.34
            c.setLineWidth(2.2)
            for ri in range(rows):
                for ci in range(cols):
                    ccx = gx0 + gw * (ci + 0.5) / cols
                    ccy = gy_top - gh * (ri + 0.5) / rows
                    c.circle(ccx, ccy, r, stroke=1, fill=0)
        elif spec.kind == "thank_you":
            c.setFont(display_font, 32)
            c.drawCentredString(cx, sy + sh * 0.6, "Thank you for coloring with us!")
            lines = _wrap(
                "We hope these pages brought you a calm, happy hour. If you enjoyed this book, an honest review helps other colorists find it.",
                body_font, 13, sw * 0.7,
            )
            _draw_block(c, lines, body_font, 13, cx, sy + sh * 0.5)
        elif spec.kind == "blank":
            pass
        else:
            raise ValueError(f"Unknown page kind {spec.kind}")

        c.showPage()
        page_map.append(entry)

    c.save()
    return InteriorResult(
        pdf_path=out_pdf,
        total_pages=total,
        image_pages=sum(1 for s in sequence if s.kind == "image"),
        page_map=page_map,
        fonts=[display_font, body_font, bold_font, script_font, condensed_font],
    )
