"""Full-wrap cover geometry per KDP's formula.

Cover width  = bleed + back width + spine + front width + bleed
Cover height = bleed + trim height + bleed
Spine        = pages x per-page factor for the paper type
All rectangles are in inches with the origin at the top-left of the canvas.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import specs


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h

    def px(self, dpi: int = specs.DPI) -> tuple[int, int, int, int]:
        return specs.px(self.x, dpi), specs.px(self.y, dpi), specs.px(self.x1, dpi), specs.px(self.y1, dpi)


@dataclass(frozen=True)
class CoverGeometry:
    trim: specs.Trim
    pages: int
    paper: str
    bleed_in: float
    spine_in: float
    width_in: float
    height_in: float
    back: Rect
    spine: Rect
    front: Rect
    back_bleed: Rect
    front_bleed: Rect
    barcode: Rect
    spine_text_allowed: bool

    @property
    def width_px(self) -> int:
        return specs.px(self.width_in)

    @property
    def height_px(self) -> int:
        return specs.px(self.height_in)

    @property
    def size_pt(self) -> tuple[float, float]:
        return specs.pt(self.width_in), specs.pt(self.height_in)

    def as_dict(self) -> dict:
        return {
            "trim": self.trim.key,
            "pages": self.pages,
            "paper": self.paper,
            "spine_in": round(self.spine_in, 4),
            "width_in": round(self.width_in, 4),
            "height_in": round(self.height_in, 4),
            "width_px": self.width_px,
            "height_px": self.height_px,
            "spine_text_allowed": self.spine_text_allowed,
            "barcode_box_in": [round(v, 3) for v in (self.barcode.x, self.barcode.y, self.barcode.w, self.barcode.h)],
        }


def cover_geometry(trim_key: str, pages: int, paper: str, bleed_in: float = specs.BLEED_IN) -> CoverGeometry:
    trim = specs.get_trim(trim_key)
    lo, hi = specs.page_range(trim_key, paper)
    if not (lo <= pages <= hi):
        raise ValueError(f"{pages} pages is outside the {lo}-{hi} range for {trim_key}/{paper}")
    spine = specs.spine_width_in(pages, paper)
    width = bleed_in * 2 + trim.width_in * 2 + spine
    height = bleed_in * 2 + trim.height_in

    back = Rect(bleed_in, bleed_in, trim.width_in, trim.height_in)
    spine_rect = Rect(back.x1, bleed_in, spine, trim.height_in)
    front = Rect(spine_rect.x1, bleed_in, trim.width_in, trim.height_in)
    back_bleed = Rect(0.0, 0.0, bleed_in + trim.width_in, height)
    front_bleed = Rect(front.x, 0.0, trim.width_in + bleed_in, height)

    bw, bh = specs.BARCODE_BOX_IN
    m = specs.BARCODE_MARGIN_IN
    barcode = Rect(back.x1 - m - bw, back.y1 - m - bh, bw, bh)

    return CoverGeometry(
        trim=trim,
        pages=pages,
        paper=paper,
        bleed_in=bleed_in,
        spine_in=spine,
        width_in=width,
        height_in=height,
        back=back,
        spine=spine_rect,
        front=front,
        back_bleed=back_bleed,
        front_bleed=front_bleed,
        barcode=barcode,
        spine_text_allowed=pages >= specs.SPINE_TEXT_MIN_PAGES,
    )
