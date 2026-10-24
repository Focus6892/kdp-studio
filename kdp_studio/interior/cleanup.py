"""Turn any source image into print-ready coloring line art.

Steps: grayscale -> autocontrast -> invert if the background is dark -> upscale the *grayscale* into the art box
(Lanczos) -> light Gaussian smoothing -> threshold -> close hairline gaps -> drop specks (connected components below a
few source pixels) -> hollow large solid regions (big connected cores only, so dots and small fills stay solid) ->
thicken strokes to `min_line_px` (KDP minimum line weight is 0.75 pt = 3.1 px at 300 DPI) -> round off the corners.

Thresholding happens after the upscale on purpose: binarizing at the model's 512 px and scaling that up gave staircase
edges, and a 3x3 median at 512 px erased every one-pixel line (broken strokes). Anti-aliased grayscale scales smoothly.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps

from ..schema import CleanupOptions

try:  # connected components for specks / cores / QA; scipy ships with the package but stays optional
    from scipy import ndimage as _ndimage
except ImportError:  # pragma: no cover - exercised only without scipy
    _ndimage = None

EIGHT = np.ones((3, 3), dtype=bool)


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


def to_grayscale(src: Image.Image, opts: CleanupOptions) -> Image.Image:
    """Grayscale, contrast-stretched, ink dark on a light background - still anti-aliased, not yet thresholded."""
    g = src.convert("L")
    if opts.autocontrast:
        g = ImageOps.autocontrast(g, cutoff=1)
    if border_mean(g) < 128:
        g = ImageOps.invert(g)
    return g


def to_grayscale_clean(src: Image.Image, opts: CleanupOptions) -> Image.Image:
    """The pre-2026-10-25 source-resolution binarization (median despeckle, then threshold). Kept for callers that
    want a quick look at the model output; prepare_art no longer uses it."""
    g = to_grayscale(src, opts)
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


def _label(mask: np.ndarray):
    """8-connected components of a boolean mask -> (labels, count), or None when scipy is missing."""
    if _ndimage is None:
        return None
    labels, n = _ndimage.label(mask, structure=EIGHT)
    return labels, int(n)


def component_areas(mask: np.ndarray) -> np.ndarray | None:
    lab = _label(mask)
    if lab is None:
        return None
    labels, n = lab
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    return np.bincount(labels.ravel())[1:]


def close_gaps(b: Image.Image, px: int) -> Image.Image:
    """Morphological closing of the ink: bridges breaks narrower than `px` so strokes read as continuous lines."""
    if px < 1:
        return b
    k = 2 * px + 1
    ink = ImageOps.invert(b)
    return ImageOps.invert(ink.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k)))


def remove_specks(b: Image.Image, min_area: int) -> Image.Image:
    """Drop ink components smaller than `min_area` pixels (model noise, stipple texture). Falls back to a median filter
    when scipy is not installed."""
    if min_area <= 1:
        return b
    ink = np.asarray(b) < 128
    lab = _label(ink)
    if lab is None:  # pragma: no cover
        return b.filter(ImageFilter.MedianFilter(5))
    labels, n = lab
    if n == 0:
        return b
    areas = np.bincount(labels.ravel())
    keep = areas >= min_area
    keep[0] = False
    cleaned = keep[labels]
    return Image.fromarray(np.where(cleaned, 0, 255).astype(np.uint8), "L")


def hollow_fills(b: Image.Image, border_px: int, min_core_area: int = 0) -> Image.Image:
    """Turn large solid black regions into outlines: a region thicker than 2*border_px keeps only a border of border_px,
    so filled gates, dark hair or black backgrounds become colorable shapes. Only cores of at least `min_core_area`
    pixels are hollowed, so dots, small fills and texture blobs stay solid instead of turning into tiny rings.
    `b` is a binary 'L' image with ink = 0."""
    if border_px < 1:
        return b
    ink = ImageOps.invert(b)  # ink = 255
    if _ndimage is not None:  # separable minimum filter: a 25 px erosion of a 6 Mpx page takes 0.2 s instead of several seconds
        core = Image.fromarray(_ndimage.minimum_filter(np.asarray(ink), size=2 * border_px + 1, mode="constant", cval=0), "L")
    else:  # pragma: no cover
        core = ink.filter(ImageFilter.MinFilter(2 * border_px + 1))  # survives only deep inside solid regions
    if min_core_area > 1:
        core_mask = np.asarray(core) > 128
        lab = _label(core_mask)
        if lab is not None:
            labels, n = lab
            if n:
                areas = np.bincount(labels.ravel())
                big = areas >= min_core_area
                big[0] = False
                core = Image.fromarray(np.where(big[labels], 255, 0).astype(np.uint8), "L")
    hollow = ImageChops.subtract(ink, core)
    return ImageOps.invert(hollow)


def smooth_edges(b: Image.Image, radius: float) -> Image.Image:
    """Blur-and-rethreshold: rounds the square corners left by the box kernels without moving edges."""
    if radius <= 0:
        return b
    return b.filter(ImageFilter.GaussianBlur(radius)).point(_lut(128))


def prepare_art(src: Image.Image, box_px: tuple[int, int], opts: CleanupOptions) -> Image.Image:
    g = to_grayscale(src, opts)
    scale = min(box_px[0] / g.width, box_px[1] / g.height)
    g = contain_resize(g, box_px)  # upscale the anti-aliased grayscale, not a bitmap
    if scale > 1.2:
        g = g.filter(ImageFilter.GaussianBlur(0.35 * scale))  # the source's own pixel staircase, smoothed away
    b = g.point(_lut(opts.threshold))
    if opts.close_gaps:
        b = close_gaps(b, max(1, round(0.75 * scale)))  # breaks up to about 1.5 source pixels wide (a one-pixel gap widens a little in the blur)
    if opts.despeckle > 0:
        b = remove_specks(b, round((3 * opts.despeckle * max(scale, 1.0)) ** 2))  # blobs under ~3 source px per despeckle step
    if opts.hollow_fills:
        border = max(opts.min_line_px, round(box_px[0] * opts.hollow_border_frac))
        b = hollow_fills(b, border, min_core_area=(border * opts.hollow_min_core) ** 2)
    b = thicken(b, opts.min_line_px)
    b = smooth_edges(b, max(1.0, 0.35 * scale))  # rounds the remaining one-source-pixel steps without thinning 3 px lines
    return close_gaps(b, 1) if opts.close_gaps else b  # the smoothing can nick a freshly bridged joint by a pixel: seal it again


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
