"""Image providers for interior pages and cover art.

- PlaceholderProvider: deterministic procedural line art (offline; lets the whole
  pipeline run and be tested without any API key).
- FolderProvider: use images you already have (e.g. exported from ComfyUI/Midjourney).
- OpenAIImagesProvider: OpenAI Images API (requires OPENAI_API_KEY). Untested here;
  treat as a starting point and verify the current model name/size options.

Any provider's output counts as AI-generated for KDP disclosure purposes except
FolderProvider, whose provenance you declare yourself in book.yaml.
"""

from __future__ import annotations

import base64
import json
import math
import os
import random
import urllib.request
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw

from ..schema import ArtSource, ImageSource

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class ProviderExhausted(RuntimeError):
    """Raised when a folder provider has no image left for the requested index."""


class ImageProvider(Protocol):
    name: str

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path: ...


# --------------------------------------------------------------------------- placeholder art
def _petal(cx: float, cy: float, r_inner: float, length: float, width: float, angle: float, steps: int = 28) -> list[tuple[float, float]]:
    ux, uy = math.cos(angle), math.sin(angle)
    pts = []
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        ex = (length / 2) * (1 + math.cos(t))
        ey = (width / 2) * math.sin(t)
        pts.append((cx + ux * (r_inner + ex) - uy * ey, cy + uy * (r_inner + ex) + ux * ey))
    return pts


def _flower(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, cy: float, radius: float, stroke: int) -> None:
    petals = rng.randint(5, 12)
    core = radius * rng.uniform(0.18, 0.3)
    length = radius - core
    width = (2 * math.pi * (core + length / 2) / petals) * rng.uniform(0.75, 1.1)
    for k in range(petals):
        a = 2 * math.pi * k / petals
        draw.line(_petal(cx, cy, core, length, width, a), fill=0, width=stroke, joint="curve")
    if rng.random() < 0.6:
        for k in range(petals):
            a = 2 * math.pi * (k + 0.5) / petals
            draw.line(_petal(cx, cy, core * 1.1, length * 0.55, width * 0.7, a), fill=0, width=stroke, joint="curve")
    draw.ellipse((cx - core, cy - core, cx + core, cy + core), outline=0, width=stroke)
    dots = rng.randint(5, 9)
    for k in range(dots):
        a = 2 * math.pi * k / dots
        r = core * 0.55
        dx, dy = cx + r * math.cos(a), cy + r * math.sin(a)
        dr = max(stroke, core * 0.09)
        draw.ellipse((dx - dr, dy - dr, dx + dr, dy + dr), outline=0, width=stroke)


def _leaf(draw: ImageDraw.ImageDraw, x: float, y: float, length: float, width: float, angle: float, stroke: int) -> None:
    draw.line(_petal(x, y, 0, length, width, angle), fill=0, width=stroke, joint="curve")
    ux, uy = math.cos(angle), math.sin(angle)
    draw.line([(x, y), (x + ux * length * 0.9, y + uy * length * 0.9)], fill=0, width=max(2, stroke // 2))


def _frame(draw: ImageDraw.ImageDraw, w: int, h: int, margin: float, stroke: int) -> None:
    draw.rounded_rectangle((margin, margin, w - margin, h - margin), radius=margin, outline=0, width=stroke)


def draw_line_art(rng: random.Random, size: tuple[int, int]) -> Image.Image:
    """Deterministic bold line art: flower, mandala or bouquet with a frame."""
    w, h = size
    img = Image.new("L", size, 255)
    d = ImageDraw.Draw(img)
    stroke = max(6, min(w, h) // 160)
    margin = min(w, h) * 0.06
    frame_style = rng.choice(["single", "double", "none"])
    if frame_style != "none":
        _frame(d, w, h, margin, stroke)
    if frame_style == "double":
        _frame(d, w, h, margin * 1.6, max(2, stroke // 2))
    motif = rng.choice(["flower", "mandala", "bouquet"])
    cx, cy = w / 2 + rng.uniform(-0.04, 0.04) * w, h * rng.uniform(0.36, 0.46)
    if motif == "flower":
        radius = min(w, h) * rng.uniform(0.26, 0.34)
        _flower(d, rng, cx, cy, radius, stroke)
        stem_top = cy + radius * 0.9
        stem_bottom = h - margin * 1.8
        d.line([(cx, stem_top), (cx, stem_bottom)], fill=0, width=stroke)
        leaves = rng.randint(2, 4)
        for i in range(leaves):
            y = stem_top + (stem_bottom - stem_top) * (0.25 + 0.6 * i / max(1, leaves - 1))
            side = -1 if i % 2 == 0 else 1
            _leaf(d, cx, y, radius * 0.7, radius * 0.32, math.radians(90 - side * 55), stroke)
    elif motif == "mandala":
        cy = h / 2
        rmax = min(w, h) * 0.42
        rings = rng.randint(3, 5)
        for k in range(rings):
            r = rmax * (k + 1) / rings
            n = 6 + 2 * k
            length = (rmax / rings) * 0.8
            width = (2 * math.pi * r / n) * 0.8
            for j in range(n):
                a = 2 * math.pi * (j + (0.5 if k % 2 else 0)) / n
                d.line(_petal(cx, cy, r - length * 0.9, length, width, a), fill=0, width=stroke, joint="curve")
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=0, width=stroke)
        _flower(d, rng, cx, cy, rmax / rings * 0.8, stroke)
    else:  # bouquet
        base_y = h - margin * 1.6
        vw = w * 0.28
        vh = h * 0.22
        vase = [(cx - vw / 2, base_y - vh), (cx + vw / 2, base_y - vh), (cx + vw / 3, base_y), (cx - vw / 3, base_y)]
        d.polygon(vase, outline=0, width=stroke)
        d.line([(cx - vw / 2, base_y - vh), (cx + vw / 2, base_y - vh)], fill=0, width=stroke)
        count = rng.randint(3, 5)
        for i in range(count):
            fx = cx + (i - (count - 1) / 2) * vw * 0.55 + rng.uniform(-w * 0.03, w * 0.03)
            fy = base_y - vh - h * rng.uniform(0.18, 0.34)
            radius = min(w, h) * rng.uniform(0.09, 0.14)
            d.line([(fx, fy + radius * 0.8), (cx + (fx - cx) * 0.3, base_y - vh)], fill=0, width=stroke)
            _flower(d, rng, fx, fy, radius, stroke)
    return img


class PlaceholderProvider:
    name = "placeholder"

    def __init__(self, seed: int = 7):
        self.seed = seed

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        rng = random.Random(f"{self.seed}:{index}:{attempt}:{prompt}")
        img = draw_line_art(rng, size)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, "PNG")
        return out_path


class FolderProvider:
    name = "folder"

    def __init__(self, folder: Path):
        self.folder = folder
        self.files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if not self.files:
            raise FileNotFoundError(f"No images found in {folder}")

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        # Retries move on to unused files at the end of the list.
        pos = index if attempt == 0 else len(self.files) - 1 - (index + attempt) % len(self.files)
        if pos >= len(self.files) or pos < 0:
            raise ProviderExhausted(f"Folder has {len(self.files)} images; none left for page {index}")
        src = self.files[pos]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.convert("RGB").save(out_path, "PNG")
        return out_path


class OpenAIImagesProvider:
    name = "openai"
    endpoint = "https://api.openai.com/v1/images/generations"

    def __init__(self, model: str | None, size: str, api_key: str | None = None):
        self.model = model or "gpt-image-1"
        self.size = size
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        body = json.dumps({"model": self.model, "prompt": prompt, "n": 1, "size": self.size, "quality": "high"}).encode()
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310 - fixed https endpoint
            payload = json.load(resp)
        item = payload["data"][0]
        if "b64_json" in item:
            data = base64.b64decode(item["b64_json"])
        else:
            with urllib.request.urlopen(item["url"], timeout=180) as r:  # noqa: S310
                data = r.read()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return out_path


def make_provider(source: ImageSource | ArtSource, base_dir: Path) -> ImageProvider:
    if source.provider == "placeholder":
        return PlaceholderProvider(seed=source.seed)
    if source.provider == "folder":
        assert source.path is not None
        p = Path(source.path)
        return FolderProvider(p if p.is_absolute() else base_dir / p)
    if source.provider == "openai":
        return OpenAIImagesProvider(model=source.model, size=source.size)
    if source.provider == "file":
        raise ValueError("'file' is a cover-only source; handled by cover.render")
    raise ValueError(f"Unknown provider {source.provider}")
