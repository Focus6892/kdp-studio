"""Render the paperback wrap cover (PDF, CMYK JPEG inside, 300 DPI) and the eBook cover.

Art is generated or loaded without any text; all typography is drawn by code so
titles are always crisp, spell-checked and easy to A/B test.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
from reportlab.pdfgen import canvas as rl_canvas

from .. import specs
from ..fonts import find_font
from ..interior.generate import OpenAIImagesProvider, draw_line_art
from ..interior.layout import register_font
from ..schema import Book, ColoringInterior
from ..util import ensure_dir, hex_to_rgb
from .geometry import CoverGeometry, cover_geometry
from .text import draw_lines_centered, draw_lines_left, fit_text, line_height, load_font, wrap

log = logging.getLogger(__name__)


@dataclass
class CoverResult:
    pdf_path: Path
    cmyk_jpg: Path
    preview_jpg: Path
    ebook_jpg: Path
    geometry: CoverGeometry
    spine_text_drawn: bool
    guides_png: Path | None = None


# --------------------------------------------------------------------------- art
def _tint(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor + (255 * (1 - factor) if factor < 1 else 0)))) for c in rgb)  # type: ignore[return-value]


def placeholder_cover_art(rng: random.Random, size: tuple[int, int], accent: str, background: str) -> Image.Image:
    """A colored-in version of the placeholder line art: soft color blobs under black outlines."""
    w, h = size
    acc = hex_to_rgb(accent)
    bg = hex_to_rgb(background)
    base = Image.new("RGB", size, _tint(bg, 0.96))
    d = ImageDraw.Draw(base)
    palette = [_tint(acc, 0.55), _tint(acc, 0.75), acc, _tint(acc, 1.25), (acc[1], acc[2], acc[0]), _tint((acc[2], acc[0], acc[1]), 0.8)]
    for _ in range(26):
        r = rng.uniform(0.06, 0.22) * min(w, h)
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        d.ellipse((x - r, y - r, x + r, y + r), fill=rng.choice(palette))
    lines = draw_line_art(rng, size)
    ink = ImageOps.invert(lines)  # white where ink was
    base.paste((28, 24, 24), mask=ink)
    return base


def load_art(book: Book, size: tuple[int, int], out_dir: Path) -> Image.Image:
    art = book.cover.art
    if art.provider == "file":
        assert art.path is not None
        with Image.open(book.resolve(art.path)) as im:
            return im.convert("RGB")
    if art.provider == "placeholder":
        rng = random.Random(f"cover:{book.id}:{art.seed}")
        return placeholder_cover_art(rng, size, book.cover.palette.accent, book.cover.palette.background)
    if art.provider == "openai":
        theme = book.interior.theme if isinstance(book.interior, ColoringInterior) else book.metadata.title
        prompt = art.prompt or (
            f"Book cover illustration for a coloring book about {theme}: vibrant fully colored artwork, "
            "clean composition with calm empty space in the upper third, no text, no letters, no watermark"
        )
        provider = OpenAIImagesProvider(model=art.model, size=art.size)
        path = provider.generate(prompt, 0, 0, ensure_dir(out_dir) / "cover_art_raw.png", size)
        with Image.open(path) as im:
            return im.convert("RGB")
    raise ValueError(f"Unknown cover art provider {art.provider}")


def cover_fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize + center-crop so the image fills `size` completely."""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    new = (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale))))
    im = img.resize(new, Image.LANCZOS)
    left = (im.width - tw) // 2
    top = (im.height - th) // 2
    return im.crop((left, top, left + tw, top + th))


# --------------------------------------------------------------------------- composition
def compose_front(book: Book, size: tuple[int, int], art: Image.Image) -> Image.Image:
    """Front cover composition used for both the print front (with bleed) and the eBook cover."""
    w, h = size
    pal = book.cover.palette
    accent = hex_to_rgb(pal.accent)
    title_rgb = hex_to_rgb(pal.title_text)
    bg = hex_to_rgb(pal.background)
    display = find_font(book.cover.title_font, "display")
    body = find_font(book.cover.body_font, "regular")
    bold = find_font(None, "bold")

    img = cover_fit(art, size)
    d = ImageDraw.Draw(img)

    band_h = int(h * 0.30)
    d.rectangle((0, 0, w, band_h), fill=accent)
    d.rectangle((0, band_h, w, band_h + int(h * 0.012)), fill=bg)

    margin_x = int(w * 0.06)
    inner_w = w - 2 * margin_x
    title_font, title_lines = fit_text(book.metadata.title, display, inner_w, band_h * 0.52, max_size=int(w * 0.16), min_size=int(w * 0.05), max_lines=3)
    y = int(band_h * 0.08)
    y = draw_lines_centered(d, title_lines, title_font, w / 2, y, title_rgb, spacing=1.0)
    if book.metadata.subtitle:
        remaining = band_h - y - int(band_h * 0.08)
        if remaining > h * 0.03:
            sub_font, sub_lines = fit_text(book.metadata.subtitle, bold, inner_w, remaining, max_size=int(w * 0.045), min_size=int(w * 0.022), max_lines=3)
            draw_lines_centered(d, sub_lines, sub_font, w / 2, y + int(band_h * 0.03), title_rgb, spacing=1.05)

    author_band = int(h * 0.085)
    d.rectangle((0, h - author_band, w, h), fill=accent)
    a_font, a_lines = fit_text(book.metadata.author, bold, inner_w, author_band * 0.7, max_size=int(w * 0.055), min_size=int(w * 0.025), max_lines=1)
    lh = line_height(a_font)
    draw_lines_centered(d, a_lines, a_font, w / 2, h - author_band + (author_band - lh) / 2, title_rgb)
    return img


def _spine_text_image(text: str, font_path: Path, spine_px: int, length_px: int, fill, bg) -> Image.Image | None:
    inset = specs.px(specs.SPINE_TEXT_INSET_IN)
    max_h = spine_px - 2 * inset
    max_w = length_px - specs.px(1.0)
    if max_h < 18:
        return None
    size = max_h
    while size >= 12:
        font = load_font(font_path, size)
        if line_height(font) <= max_h and font.getlength(text) <= max_w:
            break
        size -= 2
    else:
        return None
    font = load_font(font_path, size)
    tw = int(font.getlength(text)) + 4
    th = line_height(font)
    strip = Image.new("RGB", (tw, th), bg)
    ImageDraw.Draw(strip).text((2, 0), text, font=font, fill=fill)
    return strip.rotate(-90, expand=True)  # reads top-to-bottom when the book stands upright


def render_cover(book: Book, pages: int, out_dir: Path | None = None) -> CoverResult:
    out_dir = ensure_dir(out_dir or book.build_dir)
    geo = cover_geometry(book.print_.trim, pages, book.print_.paper)
    pal = book.cover.palette
    bg = hex_to_rgb(pal.background)
    accent = hex_to_rgb(pal.accent)
    text_rgb = hex_to_rgb(pal.text)
    title_rgb = hex_to_rgb(pal.title_text)
    body_font = find_font(book.cover.body_font, "regular")
    bold_font = find_font(None, "bold")
    display_font = find_font(book.cover.title_font, "display")

    W, H = geo.width_px, geo.height_px
    canvas = Image.new("RGB", (W, H), bg)

    # Front (with bleed on right/top/bottom)
    fx0, fy0, fx1, fy1 = geo.front_bleed.px()
    front_size = (W - fx0, H)
    art = load_art(book, front_size, out_dir)
    canvas.paste(compose_front(book, front_size, art), (fx0, 0))

    # Back
    d = ImageDraw.Draw(canvas)
    bx0, by0, bx1, by1 = geo.back_bleed.px()
    d.rectangle((bx0, by0, bx1, by1), fill=hex_to_rgb(pal.back) if pal.back else bg)
    tb = geo.back  # trim box of the back cover
    inset = specs.px(0.6)
    tx0, ty0, tx1, ty1 = tb.px()
    text_x0, text_x1 = tx0 + inset, tx1 - inset
    y = ty0 + inset
    head_font, head_lines = fit_text(book.metadata.title, display_font, text_x1 - text_x0, specs.px(1.6), max_size=specs.px(0.45), min_size=specs.px(0.2), max_lines=2)
    y = draw_lines_centered(d, head_lines, head_font, (text_x0 + text_x1) / 2, y, accent) + specs.px(0.25)
    barcode_top = geo.barcode.px()[1] if book.cover.barcode_box else ty1 - inset
    blurb = book.cover.back_blurb or (book.metadata.subtitle or "")
    if blurb:
        bf = load_font(body_font, specs.px(0.16))
        lines = wrap(blurb, bf, text_x1 - text_x0)
        y = draw_lines_left(d, lines, bf, text_x0, y, text_rgb) + specs.px(0.2)
    if book.cover.back_bullets:
        bf = load_font(bold_font, specs.px(0.15))
        for item in book.cover.back_bullets:
            if y + line_height(bf) * 1.3 > barcode_top - specs.px(0.3):
                break
            lines = wrap(item, bf, text_x1 - text_x0 - specs.px(0.3))
            d.ellipse((text_x0, y + line_height(bf) * 0.35, text_x0 + specs.px(0.1), y + line_height(bf) * 0.35 + specs.px(0.1)), fill=accent)
            y = draw_lines_left(d, lines, bf, text_x0 + specs.px(0.3), y, text_rgb)
    if book.cover.barcode_box:
        d.rectangle(geo.barcode.px(), fill=(255, 255, 255))

    # Spine
    sx0, sy0, sx1, sy1 = geo.spine.px()
    spine_fill = hex_to_rgb(pal.spine) if pal.spine else accent
    d.rectangle((sx0, 0, sx1, H), fill=spine_fill)
    want_spine_text = book.cover.spine_text if book.cover.spine_text is not None else True
    spine_text_drawn = False
    if want_spine_text and geo.spine_text_allowed:
        strip = _spine_text_image(f"{book.metadata.title}   •   {book.metadata.author}", bold_font, sx1 - sx0, sy1 - sy0, title_rgb, spine_fill)
        if strip is not None:
            canvas.paste(strip, (sx0 + (sx1 - sx0 - strip.width) // 2, sy0 + (sy1 - sy0 - strip.height) // 2))
            spine_text_drawn = True
    elif want_spine_text and book.cover.spine_text is True:
        log.warning("Spine text requested but KDP only allows it from %d pages (book has %d)", specs.SPINE_TEXT_MIN_PAGES, pages)

    # Outputs
    preview = canvas.copy()
    preview.thumbnail((1800, 1800), Image.LANCZOS)
    preview_jpg = out_dir / "cover_preview.jpg"
    preview.save(preview_jpg, "JPEG", quality=88)

    guides_png = None
    if book.cover.debug_guides:
        g = canvas.copy()
        gd = ImageDraw.Draw(g)
        for rect, color in ((geo.back, (255, 0, 0)), (geo.front, (255, 0, 0)), (geo.spine, (0, 0, 255)), (geo.barcode, (0, 160, 0))):
            gd.rectangle(rect.px(), outline=color, width=6)
        safe = specs.COVER_TEXT_SAFE_IN
        for rect in (geo.back, geo.front):
            gd.rectangle((specs.px(rect.x + safe), specs.px(rect.y + safe), specs.px(rect.x1 - safe), specs.px(rect.y1 - safe)), outline=(255, 140, 0), width=4)
        g.thumbnail((2400, 2400), Image.LANCZOS)
        guides_png = out_dir / "cover_guides.png"
        g.save(guides_png, "PNG")

    cmyk_jpg = out_dir / "cover_cmyk.jpg"
    canvas.convert("CMYK").save(cmyk_jpg, "JPEG", quality=95, dpi=(specs.DPI, specs.DPI), subsampling=0)

    pdf_path = out_dir / "cover_wrap.pdf"
    w_pt, h_pt = geo.size_pt
    # The cover is a single flattened CMYK JPEG; initialFontName keeps reportlab from
    # referencing its non-embedded default Helvetica in the page resources.
    c = rl_canvas.Canvas(str(pdf_path), pagesize=(w_pt, h_pt), initialFontName=register_font(body_font))
    c.setTitle(f"{book.metadata.full_title} - cover")
    c.setAuthor(book.metadata.author)
    c.drawImage(str(cmyk_jpg), 0, 0, width=w_pt, height=h_pt)
    c.showPage()
    c.save()

    ebook_jpg = out_dir / "cover_ebook.jpg"
    compose_front(book, specs.EBOOK_COVER_IDEAL, art).save(ebook_jpg, "JPEG", quality=92, dpi=(specs.DPI, specs.DPI))

    return CoverResult(pdf_path, cmyk_jpg, preview_jpg, ebook_jpg, geo, spine_text_drawn, guides_png)
