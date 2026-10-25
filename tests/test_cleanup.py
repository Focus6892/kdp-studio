"""Line cleanup (smooth upscale, gap closing, specks, hollow cores) and the busy-page QA checks."""

import numpy as np
from PIL import Image, ImageDraw

from kdp_studio.interior.cleanup import estimate_stroke_px, prepare_art
from kdp_studio.interior.qa import heuristic_qa, tiny_white_share
from kdp_studio.schema import CleanupOptions, QAOptions

S = 2000 / 512  # upscale factor from the model's 512 px to the 2000 px art box


def _source() -> Image.Image:
    im = Image.new("L", (512, 768), 255)
    d = ImageDraw.Draw(im)
    d.line((50, 100, 450, 100), fill=0, width=1)  # a hairline ...
    for x in range(120, 400, 60):
        d.point((x, 100), fill=255)  # ... with one-pixel breaks
    d.ellipse((150, 300, 350, 500), outline=0, width=4)
    d.rectangle((100, 600, 300, 760), fill=0)  # a big solid block: should become an outline
    d.ellipse((400, 600, 416, 616), fill=0)  # a small dot: should stay solid
    for x, y in ((30, 30), (480, 740), (250, 200)):
        d.point((x, y), fill=0)  # specks
    return im


def test_prepare_art_bridges_gaps_drops_specks_and_hollows_only_big_fills():
    art = prepare_art(_source(), (2000, 3000), CleanupOptions())
    a = np.asarray(art) < 128
    cols = a[int(90 * S):int(110 * S), int(60 * S):int(440 * S)].any(axis=0)
    assert cols.all(), "the hairline must be continuous after cleanup"
    assert not a[int(20 * S):int(40 * S), int(20 * S):int(40 * S)].any(), "a one-pixel speck must disappear"
    assert not a[int(680 * S), int(200 * S)] and a[int(601 * S), int(200 * S)], "the big block becomes a ring: white centre, ink border"
    widths = [int((a[y, int(140 * S):int(160 * S)]).sum()) for y in range(int(396 * S), int(404 * S), 4)]  # the circle's left edge, crossed horizontally: one weight
    assert all(5 <= w_ <= 13 for w_ in widths), widths  # normalised to about 8 px (line_weight_frac 0.004 of 2000)
    assert a[int(608 * S), int(408 * S)], "a small dot stays solid instead of turning into a tiny ring"
    assert estimate_stroke_px(art) >= 3


def test_prepare_art_edges_are_smooth_not_stepped():
    # a diagonal line drawn at 512 px has pixel steps; after the grayscale upscale and smoothing its edge should not
    # show 4-pixel staircase jumps: the ink boundary moves by at most 2 px between neighbouring rows
    im = Image.new("L", (512, 768), 255)
    ImageDraw.Draw(im).line((60, 100, 450, 500), fill=0, width=3)
    art = prepare_art(im, (2000, 3000), CleanupOptions(hollow_fills=False, despeckle=0))
    a = np.asarray(art) < 128
    rows = range(int(150 * S), int(450 * S), 7)
    left_edges = [int(np.argmax(a[y])) for y in rows if a[y].any()]
    jumps = np.abs(np.diff(left_edges))
    assert len(left_edges) > 100 and jumps.max() <= 2 * 7 and np.median(jumps) >= 5  # steady slope, no plateaus-and-cliffs


def test_heuristic_qa_flags_busy_and_too_detailed_pages():
    opts = QAOptions()
    simple = Image.new("L", (2000, 3000), 255)
    d = ImageDraw.Draw(simple)
    d.ellipse((400, 600, 1600, 2400), outline=0, width=12)
    d.line((1000, 600, 1000, 2400), fill=0, width=12)
    assert heuristic_qa(simple, opts).ok
    rng = np.random.default_rng(0)
    noise = Image.fromarray(np.where(rng.random((3000, 2000)) < 0.03, 0, 255).astype(np.uint8), "L")
    r = heuristic_qa(noise, opts)
    assert not r.ok and any("too busy" in x for x in r.reasons)
    grid = Image.new("L", (2000, 3000), 255)
    d = ImageDraw.Draw(grid)
    for x in range(0, 2000, 40):
        d.line((x, 0, x, 3000), fill=0, width=6)
    for y in range(0, 3000, 40):
        d.line((0, y, 2000, y), fill=0, width=6)
    assert tiny_white_share(grid) > 0.5
    r = heuristic_qa(grid, opts)
    assert not r.ok and any("too detailed" in x for x in r.reasons)
