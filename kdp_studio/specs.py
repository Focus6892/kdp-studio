"""KDP paperback / eBook specifications encoded as data.

Sources (KDP Help, fetched 2026-10-23):
- Paperback Submission Guidelines (trim sizes, page ranges, margins, DPI):
  https://kdp.amazon.com/help/topic/G201834560
- Create a Paperback Cover (bleed, spine factors, safe zones, CMYK):
  https://kdp.amazon.com/help/topic/G201953020
- Low-Content Books (barcode box 2" x 1.2"):
  https://kdp.amazon.com/en_US/help/topic/GGE5T76TWKA85DJM
- eBook cover requirements:
  https://kdp.amazon.com/en_US/help/topic/G200645690
- Hardcover trim sizes / page range:
  https://kdp.amazon.com/help/topic/A2BXOVPUCZ09J8
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DPI = 300
BLEED_IN = 0.125
PT_PER_IN = 72.0
MM_PER_IN = 25.4

PaperType = Literal["white_bw", "cream_bw", "groundwood_bw", "standard_color", "premium_color"]
PAPER_TYPES: tuple[str, ...] = ("white_bw", "cream_bw", "groundwood_bw", "standard_color", "premium_color")

# Spine width per page (inches). KDP publishes no factor for groundwood paper;
# use KDP's cover calculator for that stock.
SPINE_IN_PER_PAGE: dict[str, float] = {
    "white_bw": 0.002252,
    "cream_bw": 0.0025,
    "standard_color": 0.002252,
    "premium_color": 0.002347,
}


@dataclass(frozen=True)
class Trim:
    key: str
    width_in: float
    height_in: float

    @property
    def is_large(self) -> bool:
        """KDP: a large trim is wider than 6.12" or taller than 9"."""
        return self.width_in > 6.12 or self.height_in > 9.0

    @property
    def size_class(self) -> str:
        return "large" if self.is_large else "regular"


_TRIM_LIST = [
    ("5x8", 5.0, 8.0),
    ("5.06x7.81", 5.06, 7.81),
    ("5.25x8", 5.25, 8.0),
    ("5.5x8.5", 5.5, 8.5),
    ("6x9", 6.0, 9.0),
    ("6.14x9.21", 6.14, 9.21),
    ("6.69x9.61", 6.69, 9.61),
    ("7x10", 7.0, 10.0),
    ("7.44x9.69", 7.44, 9.69),
    ("7.5x9.25", 7.5, 9.25),
    ("8x10", 8.0, 10.0),
    ("8.25x6", 8.25, 6.0),
    ("8.25x8.25", 8.25, 8.25),
    ("8.27x11.69", 8.27, 11.69),
    ("8.5x8.5", 8.5, 8.5),
    ("8.5x11", 8.5, 11.0),
]
TRIMS: dict[str, Trim] = {k: Trim(k, w, h) for k, w, h in _TRIM_LIST}

# (min_pages, max_pages) per paper type. None = combination not offered.
_STD_RANGE: dict[str, tuple[int, int] | None] = {
    "white_bw": (24, 828),
    "cream_bw": (24, 776),
    "groundwood_bw": (24, 812),
    "standard_color": (72, 600),
    "premium_color": (24, 828),
}
_RANGE_800: dict[str, tuple[int, int] | None] = {
    "white_bw": (24, 800),
    "cream_bw": (24, 750),
    "groundwood_bw": (24, 784),
    "standard_color": (72, 600),
    "premium_color": (24, 800),
}
_RANGE_A4: dict[str, tuple[int, int] | None] = {
    "white_bw": (24, 780),
    "cream_bw": (24, 730),
    "groundwood_bw": (24, 764),
    "standard_color": None,
    "premium_color": (24, 590),
}
_RANGE_590: dict[str, tuple[int, int] | None] = {
    "white_bw": (24, 590),
    "cream_bw": (24, 550),
    "groundwood_bw": (24, 578),
    "standard_color": (72, 600),
    "premium_color": (24, 590),
}
PAGE_RANGES: dict[str, dict[str, tuple[int, int] | None]] = {k: _STD_RANGE for k in TRIMS}
PAGE_RANGES["8.25x6"] = _RANGE_800
PAGE_RANGES["8.25x8.25"] = _RANGE_800
PAGE_RANGES["8.27x11.69"] = _RANGE_A4
PAGE_RANGES["8.5x8.5"] = _RANGE_590
PAGE_RANGES["8.5x11"] = _RANGE_590

MIN_PAGES = 24
MIN_FONT_PT = 7.0
MIN_LINE_PT = 0.75
MAX_FILE_MB = 650
RECOMMENDED_COVER_MB = 40

# Interior margins (inches)
GUTTER_BY_PAGES: list[tuple[int, int, float]] = [
    (24, 150, 0.375),
    (151, 300, 0.5),
    (301, 500, 0.625),
    (501, 700, 0.75),
    (701, 828, 0.875),
]
OUTSIDE_MARGIN_NO_BLEED_IN = 0.25
OUTSIDE_MARGIN_BLEED_IN = 0.375

# Cover rules (inches)
SPINE_TEXT_MIN_PAGES = 79
SPINE_TEXT_INSET_IN = 0.0625
COVER_TEXT_SAFE_IN = 0.125
COVER_BORDER_SAFE_IN = 0.25
BARCODE_BOX_IN = (2.0, 1.2)
BARCODE_MARGIN_IN = 0.25

# eBook cover (pixels)
EBOOK_COVER_IDEAL = (1600, 2560)  # width, height
EBOOK_COVER_MIN = (625, 1000)
EBOOK_COVER_MAX_SIDE = 10000
EBOOK_COVER_MIN_RATIO = 1.6
EBOOK_COVER_MAX_MB = 50

# Hardcover (reference only; rendering is out of scope for Phase 0)
HARDCOVER_TRIMS = ("5.5x8.5", "6x9", "6.14x9.21", "7x10", "8.25x11")
HARDCOVER_PAGE_RANGE = (75, 550)

# Publishing limits (KDP Help "Create a Book", 2026-10)
WEEKLY_NEW_TITLES_PER_FORMAT = 2


def get_trim(key: str) -> Trim:
    try:
        return TRIMS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown trim size '{key}'. Known: {', '.join(TRIMS)}") from exc


def page_range(trim_key: str, paper: str) -> tuple[int, int]:
    if paper not in PAPER_TYPES:
        raise ValueError(f"Unknown paper type '{paper}'. Known: {', '.join(PAPER_TYPES)}")
    rng = PAGE_RANGES[get_trim(trim_key).key].get(paper)
    if rng is None:
        raise ValueError(f"Paper '{paper}' is not offered for trim {trim_key}")
    return rng


def gutter_in(pages: int) -> float:
    for lo, hi, g in GUTTER_BY_PAGES:
        if lo <= pages <= hi:
            return g
    raise ValueError(f"Page count {pages} outside KDP range 24-828")


def outside_margin_in(bleed: bool) -> float:
    return OUTSIDE_MARGIN_BLEED_IN if bleed else OUTSIDE_MARGIN_NO_BLEED_IN


def page_size_in(trim: Trim, bleed: bool) -> tuple[float, float]:
    """Interior PDF page size. Full-bleed pages are 0.125" wider and 0.25" taller."""
    if bleed:
        return (trim.width_in + BLEED_IN, trim.height_in + 2 * BLEED_IN)
    return (trim.width_in, trim.height_in)


def spine_width_in(pages: int, paper: str) -> float:
    try:
        return pages * SPINE_IN_PER_PAGE[paper]
    except KeyError as exc:
        raise ValueError(
            f"No published spine factor for paper '{paper}'. Use the KDP cover calculator."
        ) from exc


def px(inches: float, dpi: int = DPI) -> int:
    return int(round(inches * dpi))


def pt(inches: float) -> float:
    return inches * PT_PER_IN
