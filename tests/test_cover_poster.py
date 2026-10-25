"""Cover v2: colorized interior art, sticker compositing, theme palettes and the poster layout."""

from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw

from kdp_studio.cover.colorize import colorize_line_art, foreground_mask, make_sticker
from kdp_studio.cover.render import compose_front, effective_palette, render_cover
from kdp_studio.fonts import ASSET_FONT_DIR, find_font
from kdp_studio.schema import Book, load_book

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "bold-easy-flowers" / "book.yaml"


def _line_art() -> Image.Image:
    im = Image.new("L", (400, 600), 255)
    d = ImageDraw.Draw(im)
    d.ellipse((60, 100, 340, 380), outline=0, width=6)  # a big shape ...
    d.ellipse((150, 190, 250, 290), outline=0, width=6)  # ... with a region inside it
    d.rectangle((80, 430, 320, 540), outline=0, width=6)
    return im


def test_bundled_fonts_resolve_by_short_name_and_role():
    assert find_font("anton", "display").name == "Anton-Regular.ttf" and find_font(None, "script").name == "Pacifico-Regular.ttf"
    assert find_font(None, "condensed").name == "BebasNeue-Regular.ttf" and find_font(None, "bold").name == "Poppins-Bold.ttf"
    assert (ASSET_FONT_DIR / "LICENSE-anton.txt").is_file() and (ASSET_FONT_DIR / "LICENSE-poppins.txt").is_file()


def test_colorize_fills_enclosed_regions_only():
    out = colorize_line_art(_line_art(), ["#FF0000", "#00FF00", "#0000FF"], seed=3)
    a = np.asarray(out)
    assert tuple(a[20, 20]) == (255, 255, 255), "outer background stays white"
    def saturated(px):
        return int(px.max()) - int(px.min()) > 150
    assert saturated(a[240, 200]), "the inner circle is filled with a palette colour"
    assert saturated(a[150, 200]), "the ring between the circles is filled"
    assert saturated(a[485, 200]), "the rectangle is filled"
    assert tuple(a[102, 200]) == (0, 0, 0), "ink stays black"
    assert np.array_equal(np.asarray(colorize_line_art(_line_art(), ["#FF0000", "#00FF00", "#0000FF"], seed=3)), a), "deterministic"


def test_sticker_adds_a_white_halo_on_a_dark_background():
    art = colorize_line_art(_line_art(), ["#FF0000", "#00FF00"], seed=1)
    mask = foreground_mask(art)
    assert mask[240, 200] and not mask[20, 20]
    st = make_sticker(art, "#0B0B0D", "#FFFFFF", halo_px=10)
    a = np.asarray(st)
    assert a.shape[0] < art.height + 80 and a.shape[1] < art.width + 80  # cropped to the sticker plus halo
    assert (a == 255).all(axis=2).sum() > 2000, "a white halo surrounds the drawing"
    assert tuple(a[2, 2]) == (11, 11, 13), "outside the halo the cover background shows"


def test_theme_presets_are_overridden_by_explicit_palette_fields():
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["cover"] = {"theme": "midnight", "palette": {"accent": "#123456"}}
    book = Book.model_validate(data)
    pal = effective_palette(book)
    assert pal.background == "#0B0B0D" and pal.accent == "#123456" and pal.subtitle == "#F28C28"
    data["cover"] = {"theme": "pastel"}
    assert effective_palette(Book.model_validate(data)).title_outline == "#1E2A44"
    data["cover"] = {"theme": "custom", "palette": {"background": "#ABCDEF"}}
    assert effective_palette(Book.model_validate(data)).background == "#ABCDEF"


def test_poster_front_and_wrap_render(tmp_path):
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["cover"] = {"art": {"provider": "placeholder", "seed": 2}, "layout": "poster", "theme": "pastel", "badge": "30 designs", "back_bullets": ["30 pages", "Bold lines"]}
    data["output_dir"] = str(tmp_path / "build")
    book = Book.model_validate(data)
    book.source_path = EXAMPLE
    front = compose_front(book, (800, 1280), _line_art().convert("RGB"))
    a = np.asarray(front)
    assert tuple(a[5, 5]) == (0xCF, 0xE9, 0xF7), "pastel background"
    assert (a[int(1280 * 0.66):int(1280 * 0.82)] == 255).all(axis=2).sum() > 500, "white title letters in the title band"
    res = render_cover(book, 66, tmp_path / "build")
    assert res.pdf_path.is_file() and res.ebook_jpg.is_file() and Image.open(res.ebook_jpg).size == (1600, 2560)
    data["cover"]["layout"] = "band"
    band = compose_front(Book.model_validate(data), (800, 1280), _line_art().convert("RGB"))
    assert tuple(np.asarray(band)[5, 5]) == (0xE8, 0x58, 0x8A), "the band layout still paints its colour band"


def test_colorize_provider_uses_a_built_page_or_falls_back(tmp_path, caplog):
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["cover"] = {"art": {"provider": "colorize", "page": 1}, "layout": "poster", "theme": "midnight"}
    data["output_dir"] = str(tmp_path / "build")
    book = Book.model_validate(data)
    book.source_path = EXAMPLE
    res = render_cover(book, 66, tmp_path / "build")  # no interior yet: placeholder art, but a cover all the same
    assert res.preview_jpg.is_file()
    (tmp_path / "build" / "art").mkdir()
    _line_art().save(tmp_path / "build" / "art" / "000.png")
    _line_art().save(tmp_path / "build" / "art" / "001.png")
    res = render_cover(book, 66, tmp_path / "build")
    eb = np.asarray(Image.open(res.ebook_jpg))
    assert tuple(eb[5, 5]) <= (20, 20, 25), "midnight background"
    sat = eb.max(axis=2).astype(int) - eb.min(axis=2).astype(int)
    assert (sat > 80).sum() > 500, "flat palette colours from the colorized page appear on the cover"
