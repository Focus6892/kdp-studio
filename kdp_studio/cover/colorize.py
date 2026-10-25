"""Cover art from the book's own pages: flat-colour fills of a line-art page, and "sticker" compositing
(cut the drawing out of its white background, add a white halo and a soft shadow) so any artwork sits on a
plain cover background the way the best-selling coloring-book covers do."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

from ..util import hex_to_rgb

FOUR = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
FLORAL = ["#F0617F", "#F8A5C2", "#FFB347", "#FFD93D", "#F4A6C8", "#FF8A65", "#B388EB", "#FFC857", "#F06292", "#FFAB91"]  # blossoms
LEAVES = ["#8BC34A", "#43A047", "#AED581", "#2E7D32"]  # elongated regions: leaves, stems, grass


def colorize_line_art(art: Image.Image, colors: list[str] | None = None, seed: int = 11, min_region_px: int = 40, leaf_colors: list[str] | None = None) -> Image.Image:
    """Fill every enclosed white region of a black-and-white page with a flat colour; the outer background stays white
    and the ink stays black. Colours are chosen per neighbourhood cell rather than per region, so a flower head made of
    many petal regions reads as one or two hues instead of a patchwork, and elongated regions (leaves, stems) take the
    leaf palette. Regions are 4-connected so a one-pixel line still separates two regions. Deterministic per seed."""
    palette = np.array([hex_to_rgb(c) for c in (colors or FLORAL)], dtype=np.int16)
    leaves = np.array([hex_to_rgb(c) for c in (leaf_colors or LEAVES)], dtype=np.int16)
    ink = np.asarray(art.convert("L")) < 128
    labels, n = ndimage.label(~ink, structure=FOUR)
    if n == 0:
        return art.convert("RGB")
    areas = np.bincount(labels.ravel())
    border = np.unique(np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]]))
    idx = np.arange(1, n + 1)
    cy, cx = np.array(ndimage.center_of_mass(~ink, labels, idx)).T  # region centroids
    objs = ndimage.find_objects(labels)
    h, w = ink.shape
    cell = max(24, int(w * 0.11))
    rng = np.random.default_rng(seed)
    salt = rng.integers(0, 1 << 30)
    fill = np.zeros((n + 1, 3), dtype=np.int16)
    for i, sl in zip(idx, objs):
        if sl is None:
            continue
        bh, bw = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        elongated = max(bh, bw) >= 2.4 * max(1, min(bh, bw)) and areas[i] < 0.08 * ink.size
        key = (int(cy[i - 1]) // cell) * 7919 + (int(cx[i - 1]) // cell) * 104729 + salt
        if elongated:
            base = leaves[key % len(leaves)]
        else:
            base = palette[key % len(palette)]
        tint = 1.0 + ((i * 2654435761 + salt) % 17 - 8) * 0.012  # a little per-region variation so neighbours are not flat identical
        fill[i] = np.clip(base * tint, 0, 255)
    out = fill[labels]
    keep_white = np.isin(labels, border) | (areas[labels] < min_region_px)
    out[keep_white] = 255
    out[ink] = 0
    return Image.fromarray(out.astype(np.uint8), "RGB")


def foreground_mask(img: Image.Image, white_threshold: int = 235, tolerance: int = 48) -> np.ndarray:
    """True where the artwork is, with interior holes filled. The background colour is read from the image border
    (models asked for white sometimes deliver black or cream); pixels further than `tolerance` from it are artwork."""
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    h, w, _ = rgb.shape
    b = max(2, min(h, w) // 40)
    border = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3), rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    mask = np.abs(rgb - bg).max(axis=2) > tolerance
    if bg.mean() >= white_threshold:  # the usual white page: anything darker than near-white counts too
        mask |= np.asarray(img.convert("L")) < white_threshold
    mask = ndimage.binary_fill_holes(mask)
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 3), dtype=bool))
    return mask


def make_sticker(img: Image.Image, background: str, halo: str = "#FFFFFF", halo_px: int = 12, shadow: bool = True) -> Image.Image:
    """Composite `img` (artwork on a white page) onto a solid `background` colour as a sticker: a white halo of
    `halo_px` around the drawing and, on light backgrounds, a soft drop shadow underneath."""
    bg = hex_to_rgb(background)
    rgb = img.convert("RGB")
    mask = foreground_mask(rgb)
    if not mask.any():
        return Image.new("RGB", rgb.size, bg)
    h, w = mask.shape
    pad = halo_px * 3
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), bg)
    halo_mask = ndimage.distance_transform_edt(~mask) <= halo_px
    halo_img = Image.fromarray((halo_mask * 255).astype(np.uint8), "L")
    if shadow and sum(bg) > 300:  # a shadow only reads on light backgrounds
        sh = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        sh.paste(halo_img, (pad + halo_px, pad + halo_px * 2))
        sh = sh.filter(ImageFilter.GaussianBlur(halo_px * 1.5))
        shadow_layer = Image.new("RGB", canvas.size, tuple(max(0, c - 70) for c in bg))
        canvas.paste(shadow_layer, (0, 0), sh.point(lambda v: int(v * 0.45)))
    canvas.paste(Image.new("RGB", (w, h), hex_to_rgb(halo)), (pad, pad), halo_img)
    canvas.paste(rgb, (pad, pad), Image.fromarray((mask * 255).astype(np.uint8), "L"))
    ys, xs = np.where(halo_mask)
    box = (max(0, xs.min() + pad - halo_px), max(0, ys.min() + pad - halo_px), min(canvas.width, xs.max() + pad + halo_px * 2), min(canvas.height, ys.max() + pad + halo_px * 3))
    return canvas.crop(box)
