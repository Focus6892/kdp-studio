"""Create a new coloring-book project (folder + book.yaml) from a handful of answers, with the same
defaults the bold-easy-flowers example uses. Used by the web UI's "Tạo sách" page and reusable from code.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .schema import load_book

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")

# what to declare to KDP per image source (provenance.ai_tools); procedural sources are not AI
AI_TOOLS = {
    "local": ["Stable Diffusion 1.5 (DreamShaper-8) with ColoringBookRedmond LoRA"],  # provider local
    "cloudflare": ["FLUX.1 schnell via Cloudflare Workers AI"],
    "pollinations": ["FLUX via pollinations.ai"],
    "openai": ["gpt-image-1"],
    "google": ["Imagen 4"],
    "stability": ["Stable Image Core"],
    "spec": ["Claude (vector drawing specs)"],
    "placeholder": [],
    "folder": [],
}

DEFAULT_LORA = "artificialguybr/coloringbook-redmond-1-5v-coloring-book-lora-for-liberteredmond-sd-1-5:ColoringBookRedmond15V-LiberteRedmond-ColoringBookAF.safetensors"


def default_keywords(theme: str) -> list[str]:
    t = theme.strip().lower()
    base = [f"{t} coloring book", f"{t} coloring pages", "easy coloring book for adults", "bold and easy coloring book", "large print coloring book", "relaxing coloring book", "coloring book for seniors"]
    out: list[str] = []
    for k in base:
        if k not in out and len(k) <= 50:
            out.append(k)
    return out[:7]


def default_description(title: str, theme: str, images: int, audience: str) -> str:
    return (
        f"<h4>{images} bold and easy {theme} designs, one per page</h4>"
        f"<p>{title} gives you {images} large, simple illustrations with thick clean outlines, printed single-sided on 8.5 x 11 inch pages "
        f"so markers and gel pens never bleed through onto the next picture. Made for {audience}.</p>"
        "<ul><li>Big shapes, no tiny details</li><li>Single-sided pages with blank backs</li><li>Color test page included</li></ul>"
        "<p>Relax, color, repeat.</p>"
    )


def new_coloring_book(root: Path, folder: str, title: str, author: str, theme: str, *, subtitle: str | None = None, audience: str = "adults",
                      images: int = 30, trim: str = "8.5x11", price: float = 9.99, provider: str = "local", keywords: list[str] | None = None,
                      subjects: list[str] | None = None, model: str | None = None, lora: str | None = None) -> Path:
    folder = folder.strip().lower()
    if not SLUG.match(folder):
        raise ValueError("tên thư mục chỉ gồm chữ thường, số và dấu gạch ngang (ví dụ ocean-animals)")
    if not title.strip() or not author.strip() or not theme.strip():
        raise ValueError("cần có tiêu đề, tác giả và chủ đề")
    if provider not in AI_TOOLS:
        raise ValueError(f"nguồn ảnh không hợp lệ: {provider}")
    book_dir = Path(root) / folder
    if (book_dir / "book.yaml").exists():
        raise ValueError(f"{book_dir / 'book.yaml'} đã tồn tại")
    book_dir.mkdir(parents=True, exist_ok=True)
    source: dict = {"provider": provider, "seed": 7, "size": "1024x1536"}
    if provider == "local":
        source.update(model=model or "Lykon/dreamshaper-8", lora=lora or DEFAULT_LORA, lora_scale=0.8, steps=22, local_size="512x768")
    elif provider == "spec":
        (book_dir / "drawings").mkdir(exist_ok=True)
        source["path"] = "drawings"
    elif model:
        source["model"] = model
    style = "coloring book page, bold clean black outlines, simple shapes, large areas to color, no shading, no gray, pure white background, no text, no watermark, centered composition"
    if provider == "local" and (lora or DEFAULT_LORA) == DEFAULT_LORA:
        style = "ColoringBookAF, " + style
    doc = {
        "id": f"cb-{folder}-001",
        "type": "coloring",
        "niche": theme,
        "formats": ["paperback"],
        "metadata": {
            "title": title.strip(), "subtitle": (subtitle or "").strip() or None, "author": author.strip(), "language": "English",
            "description_html": default_description(title.strip(), theme.strip(), images, audience),
            "keywords": (keywords or default_keywords(theme))[:7],
            "categories": ["Crafts, Hobbies & Home > Crafts & Hobbies > Coloring Books for Grown-Ups", "Arts & Photography > Drawing > Coloring Books"],
            "low_content": False, "large_print": False,
        },
        "print": {"trim": trim, "paper": "white_bw", "bleed": True, "cover_finish": "matte", "isbn": "kdp_free"},
        "interior": {
            "type": "coloring", "theme": theme.strip(), "audience": audience, "images": images, "single_sided": True, "back_page": "blank",
            "front_matter": ["title", "copyright", "belongs_to", "test_colors"], "back_matter": ["thank_you", "blank"],
            "style_prompt": style,
            "negative_prompt": "color, shading, gradients, gray fill, text, letters, numbers, watermark, signature, blurry, photo, person, woman, man, face, portrait, child, tiny details, cross-hatching",
            "subjects": subjects or [],
            "source": source,
            "cleanup": {"threshold": 128, "min_line_px": 3, "despeckle": 1, "art_margin_in": 0.5},
            "dedupe": {"enabled": True, "max_distance": 10, "library": "library/image_hashes.json"},
            "qa": {"heuristic": True, "claude": False},
        },
        "cover": {"art": {"provider": "placeholder", "seed": 11}, "palette": {"background": "#FBF3E4", "accent": "#C94C4C", "text": "#2B2B2B", "title_text": "#FFFFFF"},
                  "back_blurb": f"{images} {theme} designs with thick, forgiving outlines and large shapes, each on its own page with a blank back.",
                  "back_bullets": [f"{images} single-sided pages", "Bold, easy lines", f"Large {trim.replace('x', ' x ')} inch format"], "barcode_box": True},
        "pricing": {"marketplace": "amazon.com", "list_price": price},
        "provenance": {"text": "human", "interior_images": "ai_generated" if AI_TOOLS[provider] else "human", "cover_art": "human", "ai_tools": AI_TOOLS[provider]},
    }
    if doc["metadata"]["subtitle"] is None:
        del doc["metadata"]["subtitle"]
    path = book_dir / "book.yaml"
    path.write_text("# Generated by kdp-studio (Tạo sách). Edit freely; run `kdp validate` after changes.\n" + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    try:
        load_book(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path
