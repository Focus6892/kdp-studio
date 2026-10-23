"""Interior page geometry: page size, trim box, KDP safe box and the art box.

All boxes are (x0, y0, x1, y1) in inches with the origin at the top-left of
the PDF page. Right-hand pages (recto, odd page numbers) have their gutter
on the left; left-hand pages (verso) have it on the right. Full-bleed pages
carry the extra 0.125" bleed on the outer edge plus top and bottom.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import specs

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class PageGeometry:
    trim: specs.Trim
    bleed: bool
    recto: bool
    pages: int
    page_w_in: float
    page_h_in: float
    trim_box_in: Box
    safe_box_in: Box
    art_box_in: Box

    @property
    def page_px(self) -> tuple[int, int]:
        return specs.px(self.page_w_in), specs.px(self.page_h_in)

    @property
    def page_pt(self) -> tuple[float, float]:
        return specs.pt(self.page_w_in), specs.pt(self.page_h_in)

    def box_px(self, box: Box) -> tuple[int, int, int, int]:
        return tuple(specs.px(v) for v in box)  # type: ignore[return-value]

    @property
    def art_box_px(self) -> tuple[int, int, int, int]:
        return self.box_px(self.art_box_in)

    @property
    def art_size_px(self) -> tuple[int, int]:
        x0, y0, x1, y1 = self.art_box_px
        return x1 - x0, y1 - y0


def page_geometry(trim: specs.Trim, bleed: bool, pages: int, recto: bool, art_margin_in: float = 0.5) -> PageGeometry:
    page_w, page_h = specs.page_size_in(trim, bleed)
    b = specs.BLEED_IN if bleed else 0.0
    if recto:
        trim_box = (0.0, b, trim.width_in, b + trim.height_in)
    else:
        trim_box = (b, b, b + trim.width_in, b + trim.height_in)

    gutter = specs.gutter_in(pages)
    outer = specs.outside_margin_in(bleed)
    x0, y0, x1, y1 = trim_box
    if recto:
        safe = (x0 + gutter, y0 + outer, x1 - outer, y1 - outer)
    else:
        safe = (x0 + outer, y0 + outer, x1 - gutter, y1 - outer)

    m = art_margin_in
    if recto:
        art = (x0 + max(gutter, m), y0 + max(outer, m), x1 - max(outer, m), y1 - max(outer, m))
    else:
        art = (x0 + max(outer, m), y0 + max(outer, m), x1 - max(gutter, m), y1 - max(outer, m))

    return PageGeometry(
        trim=trim,
        bleed=bleed,
        recto=recto,
        pages=pages,
        page_w_in=page_w,
        page_h_in=page_h,
        trim_box_in=trim_box,
        safe_box_in=safe,
        art_box_in=art,
    )
