import random

import numpy as np
from PIL import Image, ImageDraw

from kdp_studio.interior.cleanup import estimate_stroke_px, prepare_art, place_on_page
from kdp_studio.interior.dedupe import Descriptor, HashEntry, HashLibrary, correlation, describe, duplicates_within, hamming, is_duplicate
from kdp_studio.interior.generate import draw_line_art
from kdp_studio.interior.pagegeom import page_geometry
from kdp_studio.interior.qa import heuristic_qa
from kdp_studio.schema import CleanupOptions, QAOptions
from kdp_studio import specs


def test_prepare_art_is_binary_and_thick_enough():
    src = Image.new("L", (400, 600), 235)  # off-white paper
    d = ImageDraw.Draw(src)
    d.line((20, 20, 380, 580), fill=40, width=1)
    d.ellipse((100, 100, 300, 300), outline=60, width=1)
    out = prepare_art(src, (1000, 1500), CleanupOptions(min_line_px=4, despeckle=0))
    vals = np.unique(np.asarray(out))
    assert set(vals.tolist()) <= {0, 255}
    assert estimate_stroke_px(out) >= 4


def test_dark_background_is_inverted():
    src = Image.new("L", (300, 300), 10)
    ImageDraw.Draw(src).rectangle((50, 50, 250, 250), outline=240, width=6)
    out = prepare_art(src, (300, 300), CleanupOptions())
    a = np.asarray(out)
    assert a[0, 0] == 255  # background is now white
    assert (a < 128).mean() < 0.5


def test_place_on_page_keeps_art_inside_art_box():
    geo = page_geometry(specs.get_trim("8.5x11"), True, 66, recto=True, art_margin_in=0.5)
    art = Image.new("L", geo.art_size_px, 0)  # fully black block the size of the art box
    page = place_on_page(art, geo.page_px, geo.art_box_px)
    a = np.asarray(page) < 128
    ys, xs = np.where(a)
    x0, y0, x1, y1 = geo.art_box_px
    assert xs.min() >= x0 and xs.max() < x1 and ys.min() >= y0 and ys.max() < y1
    # gutter side (left on recto) must be at least the KDP gutter for 66 pages (0.375")
    assert xs.min() >= specs.px(0.375)


def test_duplicate_rule_and_library_roundtrip(tmp_path):
    a = draw_line_art(random.Random(1), (600, 800))
    b = draw_line_art(random.Random(2), (600, 800))
    same = a.copy()
    shifted = Image.new("L", a.size, 255)
    shifted.paste(a, (9, 6))
    da, db, ds, dsh = describe(a), describe(b), describe(same), describe(shifted)
    assert hamming(da.phash, ds.phash) == 0 and correlation(da, ds) > 0.999
    assert is_duplicate(da, ds, 6, 0.985)[0]
    assert is_duplicate(da, dsh, 6, 0.985)[0]          # bbox crop normalizes the shift
    assert not is_duplicate(da, db, 6, 0.985)[0]
    pairs = duplicates_within([da, ds, db], 6, 0.985)
    assert [(i, j) for i, j, _, _ in pairs] == [(0, 1)]

    lib = HashLibrary(tmp_path / "lib.json")
    lib.replace_book("book-a", [HashEntry("book-a", 0, da, "test")])
    lib.save()
    lib2 = HashLibrary.load(tmp_path / "lib.json")
    assert lib2.find_near(ds, 6, 0.985)                      # found in another book
    assert not lib2.find_near(ds, 6, 0.985, exclude_book="book-a")
    assert not lib2.find_near(db, 6, 0.985)
    assert isinstance(lib2.entries[0].descriptor, Descriptor)


def test_heuristic_qa_flags_black_blocks_and_empty_pages():
    opts = QAOptions()
    empty = Image.new("L", (800, 1000), 255)
    assert not heuristic_qa(empty, opts).ok
    block = Image.new("L", (800, 1000), 255)
    ImageDraw.Draw(block).rectangle((100, 100, 500, 600), fill=0)
    res = heuristic_qa(block, opts)
    assert not res.ok and any("solid black" in r for r in res.reasons)
    good = prepare_art(draw_line_art(random.Random(3), (800, 1000)), (800, 1000), CleanupOptions())
    assert heuristic_qa(good, opts).ok
