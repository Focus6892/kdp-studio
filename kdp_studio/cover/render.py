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
from ..interior.generate import API_PROVIDERS, draw_line_art, make_provider
from ..interior.layout import register_font
from ..schema import Book, ColoringInterior, Palette
from .colorize import colorize_line_art, make_sticker
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


THEMES: dict[str, dict] = {
    # the two looks that dominate the coloring-book best-seller lists: vivid art on black, or pastel with an outlined title
    "midnight": dict(background="#0B0B0D", accent="#F28C28", text="#F2F2F2", title_text="#FFFFFF", subtitle="#F28C28", author="#FFFFFF", title_outline=None, card="#FFFFFF", back="#0B0B0D"),
    "pastel": dict(background="#CFE9F7", accent="#E8588A", text="#1E2A44", title_text="#FFFFFF", subtitle="#1E2A44", author="#1E2A44", title_outline="#1E2A44", card="#FFFFFF", back="#CFE9F7"),
    "cream": dict(background="#FBF3E4", accent="#C94C4C", text="#2B2B2B", title_text="#2B2B2B", subtitle="#C94C4C", author="#C94C4C", title_outline=None, card="#FFFFFF", back="#FBF3E4"),
}


def effective_palette(book: Book) -> Palette:
    """The theme preset with whatever `cover.palette` sets explicitly on top."""
    pal = book.cover.palette
    preset = THEMES.get(book.cover.theme)
    if preset is None:
        return pal
    return Palette(**{**preset, **{k: getattr(pal, k) for k in pal.model_fields_set}})


def interior_art_pages(book: Book) -> list[Path]:
    d = book.build_dir / "art"
    return sorted(d.glob("*.png")) if d.is_dir() else []


def _size_px(spec: str) -> tuple[int, int]:
    w, h = spec.lower().split("x")
    return int(w), int(h)


def load_art(book: Book, size: tuple[int, int], out_dir: Path) -> Image.Image:
    """The cover artwork on a white page, without text: a file, one of the book's own pages filled with flat colours,
    a generated illustration, or the placeholder. The layout turns it into a sticker afterwards."""
    art = book.cover.art
    if art.provider == "file":
        assert art.path is not None
        with Image.open(book.resolve(art.path)) as im:
            return im.convert("RGB")
    if art.provider == "colorize":
        pages = interior_art_pages(book)
        if pages:
            pick = pages[art.page % len(pages)] if art.page is not None else pages[0]
            log.info("cover art: colouring interior page %s", pick.name)
            with Image.open(pick) as im:
                return colorize_line_art(im, art.colors, seed=art.seed)
        log.warning("cover art 'colorize' needs a built interior (build/art/*.png); using the placeholder art")
    elif art.provider in API_PROVIDERS or art.provider == "auto":
        theme = book.interior.theme if isinstance(book.interior, ColoringInterior) else book.metadata.title
        prompt = art.prompt or (
            f"a single beautiful {theme} arrangement centered on a plain white background, vibrant fully colored flat illustration "
            "with thick black outlines, sticker style, soft shading, lots of empty white space around it, no text, no letters, no watermark"
        )
        provider = make_provider(art, book.book_dir, negative_prompt="text, letters, watermark, logo, signature, frame, border")
        path = provider.generate(prompt, 0, 0, ensure_dir(out_dir) / "cover_art_raw.png", _size_px(art.size))
        with Image.open(path) as im:
            return im.convert("RGB")
    rng = random.Random(f"cover:{book.id}:{art.seed}")
    pal = effective_palette(book)
    return placeholder_cover_art(rng, size, pal.accent, "#FFFFFF")


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
def _draw_centered(d: ImageDraw.ImageDraw, lines: list[str], font, cx: float, y: float, fill, spacing: float = 1.0, stroke=None, stroke_w: int = 0) -> float:
    for line in lines:
        x = cx - font.getlength(line) / 2
        d.text((x, y), line, font=font, fill=fill, stroke_width=stroke_w if stroke else 0, stroke_fill=stroke)
        y += line_height(font) * spacing
    return y


def _draw_badge(d: ImageDraw.ImageDraw, text: str, center: tuple[int, int], radius: int, fill, text_rgb, font_path: Path) -> None:
    cx, cy = center
    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)
    font, lines = fit_text(text.upper(), font_path, radius * 1.6, radius * 1.3, max_size=int(radius * 0.7), min_size=int(radius * 0.25), max_lines=2, spacing=0.95)
    total = line_height(font) * 0.95 * len(lines)
    _draw_centered(d, lines, font, cx, cy - total / 2, text_rgb, spacing=0.95)


def compose_front(book: Book, size: tuple[int, int], art: Image.Image) -> Image.Image:
    """Front cover for both the print front (with bleed) and the eBook cover. Poster layout: the art as a sticker on a
    plain background in the upper two thirds, then a big display title, a condensed subtitle in the accent colour and
    the author in a script face - the structure shared by the top-selling coloring books."""
    if book.cover.layout == "band":
        return _compose_front_band(book, size, art)
    w, h = size
    pal = effective_palette(book)
    bg = hex_to_rgb(pal.background)
    img = Image.new("RGB", size, bg)
    zone_top, zone_bottom, zone_w = int(h * 0.05), int(h * 0.63), int(w * 0.88)
    piece = make_sticker(art, pal.background, book.cover.art.halo, halo_px=max(4, int(w * 0.012))) if book.cover.art.sticker else art.convert("RGB")
    scale = min(zone_w / piece.width, (zone_bottom - zone_top) / piece.height)
    piece = piece.resize((max(1, int(piece.width * scale)), max(1, int(piece.height * scale))), Image.LANCZOS)
    img.paste(piece, ((w - piece.width) // 2, zone_top + (zone_bottom - zone_top - piece.height) // 2))
    d = ImageDraw.Draw(img)
    inner_w = int(w * 0.88)
    outline = hex_to_rgb(pal.title_outline) if pal.title_outline else None
    t_font, t_lines = fit_text(book.metadata.title, find_font(book.cover.title_font, "display"), inner_w, int(h * 0.165), max_size=int(w * 0.17), min_size=int(w * 0.06), max_lines=2, spacing=0.95)
    y = _draw_centered(d, t_lines, t_font, w / 2, int(h * 0.655), hex_to_rgb(pal.title_text), spacing=0.95, stroke=outline, stroke_w=max(2, int(w * 0.006)))
    if book.metadata.subtitle:
        s_font, s_lines = fit_text(book.metadata.subtitle.upper(), find_font(book.cover.subtitle_font, "condensed"), inner_w, int(h * 0.06), max_size=int(w * 0.07), min_size=int(w * 0.028), max_lines=1)
        y = _draw_centered(d, s_lines, s_font, w / 2, y + int(h * 0.012), hex_to_rgb(pal.subtitle or pal.accent))
    a_font, a_lines = fit_text(book.metadata.author, find_font(book.cover.author_font, "script"), inner_w, int(h * 0.075), max_size=int(w * 0.085), min_size=int(w * 0.035), max_lines=1)
    _draw_centered(d, a_lines, a_font, w / 2, max(y + int(h * 0.012), int(h * 0.895)), hex_to_rgb(pal.author or pal.title_text))
    if book.cover.badge:
        _draw_badge(d, book.cover.badge, (int(w * 0.85), int(h * 0.105)), int(w * 0.085), hex_to_rgb(pal.accent), hex_to_rgb(pal.title_text), find_font(None, "condensed"))
    return img


def _compose_front_band(book: Book, size: tuple[int, int], art: Image.Image) -> Image.Image:
    """The older layout: art filling the cover under a colour band with the title and an author band at the foot."""
    w, h = size
    pal = effective_palette(book)
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


def _compose_back_poster(book: Book, canvas: Image.Image, geo: CoverGeometry, pal: Palette) -> None:
    """Back cover for the poster layout: title, blurb, a row of sample pages in white cards, bullets, barcode box."""
    d = ImageDraw.Draw(canvas)
    tx0, ty0, tx1, ty1 = geo.back.px()
    inset = specs.px(0.55)
    x0, x1 = tx0 + inset, tx1 - inset
    y = ty0 + inset
    display = find_font(book.cover.title_font, "display")
    body = find_font(book.cover.body_font, "regular")
    bold = find_font(None, "bold")
    text_rgb = hex_to_rgb(pal.text)
    head_font, head_lines = fit_text(book.metadata.title, display, x1 - x0, specs.px(1.2), max_size=specs.px(0.42), min_size=specs.px(0.18), max_lines=2)
    y = draw_lines_centered(d, head_lines, head_font, (x0 + x1) / 2, y, hex_to_rgb(pal.title_text)) + specs.px(0.22)
    blurb = book.cover.back_blurb or book.metadata.subtitle or ""
    if blurb:
        bf = load_font(body, specs.px(0.15))
        y = draw_lines_left(d, wrap(blurb, bf, x1 - x0), bf, x0, y, text_rgb) + specs.px(0.28)
    pages = interior_art_pages(book)
    n = min(book.cover.sample_pages, len(pages))
    if n:
        chosen = [pages[round(k * (len(pages) - 1) / max(1, n - 1))] for k in range(n)] if n > 1 else pages[:1]
        gap = specs.px(0.18)
        card_w = (x1 - x0 - gap * (n - 1)) // n
        card_h = int(card_w * 1.28)
        pad = specs.px(0.07)
        for k, p in enumerate(chosen):
            cx0 = x0 + k * (card_w + gap)
            d.rounded_rectangle((int(cx0), int(y), int(cx0 + card_w), int(y + card_h)), radius=specs.px(0.08), fill=hex_to_rgb(pal.card))
            with Image.open(p) as im:
                thumb = im.convert("RGB")
                thumb.thumbnail((card_w - 2 * pad, card_h - 2 * pad), Image.LANCZOS)
            canvas.paste(thumb, (int(cx0 + (card_w - thumb.width) // 2), int(y + (card_h - thumb.height) // 2)))
        y += card_h + specs.px(0.28)
    barcode_top = geo.barcode.px()[1] if book.cover.barcode_box else ty1 - inset
    if book.cover.back_bullets:
        bf = load_font(bold, specs.px(0.14))
        for item in book.cover.back_bullets:
            if y + line_height(bf) * 1.3 > barcode_top - specs.px(0.3):
                break
            d.ellipse((x0, y + line_height(bf) * 0.35, x0 + specs.px(0.1), y + line_height(bf) * 0.35 + specs.px(0.1)), fill=hex_to_rgb(pal.accent))
            y = draw_lines_left(d, wrap(item, bf, x1 - x0 - specs.px(0.3)), bf, x0 + specs.px(0.3), y, text_rgb)
    if book.cover.barcode_box:
        d.rectangle(geo.barcode.px(), fill=(255, 255, 255))


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
    pal = effective_palette(book)
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
    if book.cover.layout == "poster":
        _compose_back_poster(book, canvas, geo, pal)
    else:
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
    spine_fill = hex_to_rgb(pal.spine) if pal.spine else (bg if book.cover.layout == "poster" else accent)
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
