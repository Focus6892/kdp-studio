"""Pillow text helpers: wrapping, auto-fit and centered drawing."""

from __future__ import annotations

from pathlib import Path

from PIL import ImageDraw, ImageFont

_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    key = (str(path), int(size))
    if key not in _cache:
        _cache[key] = ImageFont.truetype(str(path), int(size))
    return _cache[key]


def line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if font.getlength(trial) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def fit_text(
    text: str,
    font_path: Path,
    max_w: float,
    max_h: float,
    max_size: int,
    min_size: int = 16,
    max_lines: int = 4,
    spacing: float = 1.08,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = max(max_size, min_size)
    while size >= min_size:
        font = load_font(font_path, size)
        lines = wrap(text, font, max_w)
        lh = line_height(font) * spacing
        if len(lines) <= max_lines and lh * len(lines) <= max_h and all(font.getlength(l) <= max_w for l in lines):
            return font, lines
        size = int(size * 0.92) if size > 24 else size - 1
    font = load_font(font_path, min_size)
    return font, wrap(text, font, max_w)


def draw_lines_centered(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    cx: float,
    y_top: float,
    fill,
    spacing: float = 1.08,
) -> float:
    lh = line_height(font) * spacing
    y = y_top
    for line in lines:
        w = font.getlength(line)
        draw.text((cx - w / 2, y), line, font=font, fill=fill)
        y += lh
    return y


def draw_lines_left(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    x: float,
    y_top: float,
    fill,
    spacing: float = 1.2,
) -> float:
    lh = line_height(font) * spacing
    y = y_top
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += lh
    return y
