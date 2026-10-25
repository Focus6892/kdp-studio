"""Turn any source image into print-ready coloring line art.

Steps: grayscale -> autocontrast -> invert if the background is dark -> upscale the *grayscale* into the art box
(Lanczos) -> light Gaussian smoothing -> threshold -> close hairline gaps -> drop specks (connected components below a
few source pixels) -> hollow large solid regions (big connected cores only, so dots and small fills stay solid) ->
normalise the strokes (thin every stroke to its centreline, drop short isolated marks such as hatching, prune spurs,
bridge open stroke ends so regions close, then redraw every line at one fixed weight) -> round off.

Thresholding happens after the upscale on purpose: binarizing at the model's 512 px and scaling that up gave staircase
edges, and a 3x3 median at 512 px erased every one-pixel line (broken strokes). Anti-aliased grayscale scales smoothly.
The stroke normalisation is what makes a dense model drawing read like the "bold and easy" books on Amazon: one
uniform outline weight (about 2 pt), no shading strokes, closed shapes with room to colour.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps

from ..schema import CleanupOptions

try:  # connected components / distance transforms for specks, cores, strokes and QA; scipy ships with the package
    from scipy import ndimage as _ndimage
except ImportError:  # pragma: no cover - exercised only without scipy
    _ndimage = None

EIGHT = np.ones((3, 3), dtype=bool)
_K8 = np.ones((3, 3), dtype=np.int32)
_K8[1, 1] = 0


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


# ---------------------------------------------------------------- stroke normalisation (skeleton -> uniform weight)
def _zhang_suen_luts() -> tuple[np.ndarray, np.ndarray]:
    """Deletion decision of the two Zhang-Suen sub-iterations for every 8-neighbourhood code (bit i = p(2+i), clockwise from north)."""
    luts = []
    for step in (0, 1):
        lut = np.zeros(256, dtype=bool)
        for code in range(256):
            p = [(code >> i) & 1 for i in range(8)]
            b = sum(p)
            seq = p + [p[0]]
            a = sum(1 for i in range(8) if seq[i] == 0 and seq[i + 1] == 1)
            p2, _p3, p4, _p5, p6, _p7, p8, _p9 = p
            cond = (p2 * p4 * p6 == 0 and p4 * p6 * p8 == 0) if step == 0 else (p2 * p4 * p8 == 0 and p2 * p6 * p8 == 0)
            lut[code] = 2 <= b <= 6 and a == 1 and cond
        luts.append(lut)
    return luts[0], luts[1]


_LUTS = _zhang_suen_luts()


def _codes(img: np.ndarray) -> np.ndarray:
    p = np.pad(img, 1)
    return (p[:-2, 1:-1] | (p[:-2, 2:] << 1) | (p[1:-1, 2:] << 2) | (p[2:, 2:] << 3) | (p[2:, 1:-1] << 4) | (p[2:, :-2] << 5) | (p[1:-1, :-2] << 6) | (p[:-2, :-2] << 7))


def thin(ink: np.ndarray, max_iter: int = 40) -> np.ndarray:
    """Zhang-Suen thinning (vectorised, lookup-table) of a boolean ink mask to its one-pixel centreline."""
    img = ink.astype(np.uint8)
    for _ in range(max_iter):
        changed = False
        for lut in _LUTS:
            m = lut[_codes(img)] & (img == 1)
            if m.any():
                img[m] = 0
                changed = True
        if not changed:
            break
    return img.astype(bool)


def thin_fast(ink: np.ndarray) -> np.ndarray:
    """Thinning for page-sized masks: run Zhang-Suen at half resolution (4x fewer pixels), lift the skeleton back up
    and finish with a few full-resolution passes. The centreline lands within about half a pixel of the full-resolution
    result on a 2000 px page (measured mean 0.56 px) in a quarter of the time."""
    h, w = ink.shape
    if min(h, w) < 1200 or _ndimage is None:
        return thin(ink)
    small = np.asarray(Image.fromarray(np.where(ink, 0, 255).astype(np.uint8), "L").resize((w // 2, h // 2), Image.BOX)) < 160  # biased to ink so 3 px lines survive
    up = np.kron(thin(small), np.ones((2, 2), dtype=bool))[:h, :w]
    inside = _ndimage.binary_dilation(ink, structure=EIGHT, iterations=2)
    return thin(up & inside, max_iter=4)


def _neighbours(sk: np.ndarray) -> np.ndarray:
    return _ndimage.convolve(sk.astype(np.int32), _K8, mode="constant")


def prune_spurs(sk: np.ndarray, length: int) -> np.ndarray:
    """Remove skeleton branches shorter than `length` that hang off a junction (thinning artefacts along rough edges):
    strip end pixels `length` times, then grow the surviving ends back along the original skeleton."""
    if length < 1 or not sk.any():
        return sk
    cur = sk.copy()
    for _ in range(length):
        ends = cur & (_neighbours(cur) == 1)
        if not ends.any():
            break
        cur &= ~ends
    grow = cur & (_neighbours(cur) == 1)
    for _ in range(length):
        grow = _ndimage.binary_dilation(grow, structure=EIGHT) & sk & ~cur
        if not grow.any():
            break
        cur |= grow
    return cur


def drop_short_strokes(sk: np.ndarray, min_px: int) -> np.ndarray:
    """Remove isolated skeleton pieces shorter than `min_px` pixels: hatching, shading ticks, texture marks."""
    if min_px <= 1:
        return sk
    lab = _label(sk)
    if lab is None:  # pragma: no cover
        return sk
    labels, n = lab
    if n == 0:
        return sk
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_px
    keep[0] = False
    return keep[labels]


def bridge_ends(sk: np.ndarray, max_gap: int, cone_deg: int = 35) -> tuple[np.ndarray, int, int]:
    """Join open stroke ends: from each endpoint, look ahead along the stroke's own direction (within a cone) for
    other ink up to `max_gap` pixels away and draw the connection. Returns (skeleton, endpoints before, joins)."""
    if max_gap < 2 or not sk.any():
        return sk, 0, 0
    sk = sk.copy()
    h, w = sk.shape
    ends = np.argwhere(sk & (_neighbours(sk) == 1))
    angles = np.deg2rad(np.arange(-cone_deg, cone_deg + 1, 5))
    joined = 0
    for y, x in ends:
        path = [(int(y), int(x))]
        prev, cur = None, (int(y), int(x))
        for _ in range(10):  # walk back along the branch to get its direction
            cy, cx = cur
            nxt = None
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if (dy or dx) and 0 <= cy + dy < h and 0 <= cx + dx < w and sk[cy + dy, cx + dx]:
                        cand = (cy + dy, cx + dx)
                        if cand != prev and cand not in path:
                            nxt = cand
                            break
                if nxt:
                    break
            if not nxt:
                break
            prev, cur = cur, nxt
            path.append(cur)
        if len(path) < 4:
            continue
        base = math.atan2(y - path[-1][0], x - path[-1][1])
        own = set(path)
        hit = None
        for r in range(3, max_gap + 1):
            for a in angles:
                ny, nx = int(round(y + r * math.sin(base + a))), int(round(x + r * math.cos(base + a)))
                if 0 <= ny < h and 0 <= nx < w and sk[ny, nx] and (ny, nx) not in own:
                    hit = (ny, nx)
                    break
            if hit:
                break
        if hit:
            steps = max_gap * 2
            rr = np.round(np.linspace(y, hit[0], steps)).astype(int)
            cc = np.round(np.linspace(x, hit[1], steps)).astype(int)
            sk[rr, cc] = True
            joined += 1
    return sk, int(len(ends)), joined


def normalize_strokes(b: Image.Image, min_w: int, max_w: int, target_ink: float, bridge_px: int, min_stroke_px: int) -> tuple[Image.Image, int]:
    """Redraw the line art at one stroke weight: centreline (thinning) -> drop short isolated marks -> prune spurs ->
    bridge open ends -> dilate to a weight chosen from the drawing's density: a sparse drawing gets bold lines, a dense
    one thinner lines, so that ink covers about `target_ink` of the page (clamped to [min_w, max_w]). Solid features
    thicker than 1.5x the stroke (flower centres, eyes, small fills) are kept as drawn. Returns (image, weight px)."""
    if _ndimage is None or max_w < 1:  # pragma: no cover
        return b, 0
    ink = np.asarray(b) < 128
    if not ink.any():
        return b, 0
    sk = thin_fast(ink)
    sk = drop_short_strokes(sk, min_stroke_px)
    sk = prune_spurs(sk, max(2, round(0.5 * min_w)))
    sk, _ends, _joined = bridge_ends(sk, bridge_px)
    length = int(sk.sum())
    w = int(np.clip(round(target_ink * sk.size / max(length, 1)), min_w, max_w))
    out = _ndimage.distance_transform_edt(~sk) <= w / 2
    out |= _solid_features(ink, w)
    return Image.fromarray(np.where(out, 0, 255).astype(np.uint8), "L"), w


def _solid_features(ink: np.ndarray, w: int) -> np.ndarray:
    """Compact solid shapes (flower centres, eyes, dots) to keep as drawn: the deep cores of the ink that are roundish and
    small, grown back to their outline. Fat lines also have deep cores, but theirs are long and thin, so they are left to
    the normalisation."""
    r = max(1, round(0.75 * w))
    core = _ndimage.distance_transform_edt(ink) > r
    if not core.any():
        return np.zeros_like(ink)
    labels, n = _ndimage.label(core, structure=EIGHT)
    keep = np.zeros(n + 1, dtype=bool)
    for i, sl in enumerate(_ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        bh, bw = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        area = int((labels[sl] == i).sum())
        if max(bh, bw) <= max(12 * w, 120) and area >= 0.5 * bh * bw:  # compact (roundish) and small: a flower centre, not a long fat stroke
            keep[i] = True
    kept = keep[labels]
    if not kept.any():
        return np.zeros_like(ink)
    return _ndimage.distance_transform_edt(~kept) <= r


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
    if opts.line_weight_frac > 0:
        b, _w = normalize_strokes(b, min_w=max(opts.min_line_px, round(opts.min_weight_frac * box_px[0])), max_w=round(opts.line_weight_frac * box_px[0]),
                                  target_ink=opts.target_ink, bridge_px=round(opts.bridge_frac * box_px[0]), min_stroke_px=round(opts.min_stroke_frac * box_px[0]))
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
