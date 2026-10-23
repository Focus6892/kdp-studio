"""Turn any source image into print-ready coloring line art.

Steps: grayscale -> autocontrast -> invert if the background is dark ->
despeckle (median) -> threshold -> resize into the art box -> re-threshold ->
thicken strokes until they are at least `min_line_px` wide (KDP minimum line
weight is 0.75 pt = 3.1 px at 300 DPI) -> paste onto a white page.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from ..schema import CleanupOptions


def _lut(threshold: int) -> list[int]:
    return [0] * threshold + [255] * (256 - threshold)


def binarize(img: Image.Image, threshold: int = 128) -> Image.Image:
    return img.convert("L").point(_lut(threshold))


def border_mean(g: Image.Image, frac: float = 0.03) -> float:
    a = np.asarray(g, dtype=np.float32)
    h, w = a.shape
    bh, bw = max(1, int(h * frac)), max(1, int(w * frac))
    parts = [a[:bh, :], a[-bh:, :], a[:, :bw], a[:, -bw:]]
    return float(np.mean([p.mean() for p in parts]))


def to_grayscale_clean(src: Image.Image, opts: CleanupOptions) -> Image.Image:
    g = src.convert("L")
    if opts.autocontrast:
        g = ImageOps.autocontrast(g, cutoff=1)
    if border_mean(g) < 128:
        g = ImageOps.invert(g)
    if opts.despeckle > 0:
        g = g.filter(ImageFilter.MedianFilter(2 * opts.despeckle + 1))
    return g.point(_lut(opts.threshold))


def contain_resize(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    bw, bh = box
    w, h = img.size
    scale = min(bw / w, bh / h)
    new = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return img.resize(new, Image.LANCZOS)


def ink_ratio(b: Image.Image) -> float:
    a = np.asarray(b)
    return float((a < 128).mean()) if a.size else 0.0


def estimate_stroke_px(b: Image.Image) -> float:
    """Approximate stroke width as 2*area/perimeter of the ink mask."""
    a = np.asarray(b) < 128
    if not a.any():
        return 0.0
    inner = a.copy()
    inner[1:, :] &= a[:-1, :]
    inner[:-1, :] &= a[1:, :]
    inner[:, 1:] &= a[:, :-1]
    inner[:, :-1] &= a[:, 1:]
    perimeter = int((a & ~inner).sum())
    if perimeter == 0:
        return float(min(a.shape))
    return 2.0 * float(a.sum()) / perimeter


def thicken(b: Image.Image, min_line_px: int, max_iters: int = 5) -> Image.Image:
    for _ in range(max_iters):
        if estimate_stroke_px(b) >= min_line_px:
            break
        b = b.filter(ImageFilter.MinFilter(3))
    return b


def prepare_art(src: Image.Image, box_px: tuple[int, int], opts: CleanupOptions) -> Image.Image:
    g = to_grayscale_clean(src, opts)
    g = contain_resize(g, box_px)
    b = binarize(g, 128)
    return thicken(b, opts.min_line_px)


def place_on_page(art: Image.Image, page_px: tuple[int, int], art_box_px: tuple[int, int, int, int]) -> Image.Image:
    page = Image.new("L", page_px, 255)
    x0, y0, x1, y1 = art_box_px
    bw, bh = x1 - x0, y1 - y0
    if art.width > bw or art.height > bh:
        art = contain_resize(art, (bw, bh))
        art = binarize(art, 128)
    ox = x0 + (bw - art.width) // 2
    oy = y0 + (bh - art.height) // 2
    page.paste(art, (ox, oy))
    return page
