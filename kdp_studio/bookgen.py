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
    "auto": ["FLUX.1 schnell via Cloudflare Workers AI", "Stable Diffusion 1.5 (DreamShaper-8) with ColoringBookRedmond LoRA"],  # failover chain: declare every member it may use
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
    elif provider == "auto":  # chain members use their own default models; the LoRA settings apply to the local member when the chain reaches it
        source.update(lora=lora or DEFAULT_LORA, lora_scale=0.8, steps=22, local_size="512x768")
    elif provider == "spec":
        (book_dir / "drawings").mkdir(exist_ok=True)
        source["path"] = "drawings"
    elif model:
        source["model"] = model
    style = ("coloring book page, one subject centered on a plain white background with generous empty space around it, bold clean black outlines of even thickness, "
             "simple shapes, large areas to color, no shading, no gray, no hatching, no background scenery, no text, no watermark")
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
            "qa": {"heuristic": True, "claude": False, **({"max_tiny_white": 0.2} if provider == "local" else {})},  # SD1.5 + LoRA draws denser than FLUX
        },
        "cover": {"art": {"provider": "colorize", "seed": 11, "sticker": True}, "layout": "poster", "theme": "midnight", "badge": f"{images} designs",
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


# ---------------------------------------------------------------- story books (paperback + Kindle eBook)
STORY_BEATS = [
    ("An Ordinary Morning", "Meet the main character in the ordinary world; a small detail hints that something is about to change."),
    ("The Letter", "An unexpected message or arrival sets the story in motion and gives the character a reason to act."),
    ("First Steps", "The character makes a choice, meets an ally and discovers the first obstacle."),
    ("Complications", "A setback raises the stakes; an old habit or fear gets in the way."),
    ("What the Town Knows", "A conversation reveals a secret or history that changes how the character sees the problem."),
    ("The Long Night", "The lowest point: a plan fails and the character must decide what truly matters."),
    ("Lanterns", "With help from friends the character tries again, differently and with heart."),
    ("Home", "Resolution: the problem is settled, relationships are mended, and a final image echoes the opening."),
]
STORY_GENRES = ("cozy fiction", "cozy mystery", "sweet romance", "women's fiction", "fantasy", "science fiction", "thriller", "historical fiction",
                "literary fiction", "children's chapter book", "middle grade adventure", "young adult", "short stories")
STORY_TRIMS = ("5x8", "5.25x8", "5.5x8.5", "6x9")
STORY_AI_TOOLS = ["Claude (Anthropic) or Llama 3.3 via Cloudflare Workers AI, through kdp story draft"]


def default_story_keywords(genre: str) -> list[str]:
    g = genre.strip().lower()
    base = [f"{g} books", f"{g} novels", f"clean {g}", f"feel good {g}", f"{g} short reads", "heartwarming fiction", "small town fiction"]
    out: list[str] = []
    for k in base:
        if k not in out and len(k) <= 50:
            out.append(k)
    return out[:7]


def default_story_description(title: str, genre: str, premise: str, chapters: int, audience: str) -> str:
    return (f"<h4>{title}</h4><p>{premise.strip()}</p>"
            f"<ul><li>{chapters} chapters of {genre.strip()}</li><li>Clean, warm and easy to read in a few sittings</li><li>For {audience.strip() or 'adults'}</li>"
            "<li>Available in paperback and as a Kindle eBook</li></ul>")


def skeleton_outline(chapters: int) -> list[str]:
    """'Title: summary' lines for a story with no outline yet, following a simple three-act shape."""
    out: list[str] = []
    seen: dict[str, int] = {}
    for i in range(chapters):
        title, summary = STORY_BEATS[min(i * len(STORY_BEATS) // max(1, chapters), len(STORY_BEATS) - 1)]
        seen[title] = seen.get(title, 0) + 1
        if seen[title] > 1:
            title, summary = f"{title}, Part {seen[title]}", "Continue the previous beat from a new angle and raise the stakes a notch."
        out.append(f"{title}: {summary}")
    return out


def chapter_filename(index: int, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or f"chapter-{index}"
    return f"{index:02d}-{slug}.md"


SKELETON_MARK = "<!-- kdp-studio: chapter skeleton, replaced by `kdp story draft` -->"
STORY_CATEGORIES = [  # (genre keyword, KDP browse path) - first match wins; edit book.yaml for the exact placement KDP's picker shows
    ("cozy mystery", "Mystery, Thriller & Suspense > Mystery > Cozy"), ("mystery", "Mystery, Thriller & Suspense > Mystery"),
    ("thriller", "Mystery, Thriller & Suspense > Thrillers & Suspense"), ("romance", "Romance > Clean & Wholesome"),
    ("fantasy", "Science Fiction & Fantasy > Fantasy"), ("science fiction", "Science Fiction & Fantasy > Science Fiction"),
    ("historical", "Literature & Fiction > Historical Fiction"), ("horror", "Literature & Fiction > Horror"),
    ("children", "Children's Books > Literature & Fiction > Chapter Books"), ("middle grade", "Children's Books > Literature & Fiction > Action & Adventure"),
    ("young adult", "Teen & Young Adult > Literature & Fiction"), ("short stor", "Literature & Fiction > Short Stories & Anthologies"),
    ("women", "Literature & Fiction > Women's Fiction"), ("literary", "Literature & Fiction > Literary Fiction"),
]


def story_category(genre: str) -> str:
    g = genre.lower()
    for key, path in STORY_CATEGORIES:
        if key in g:
            return path
    return "Literature & Fiction > Genre Fiction > Feel-Good"


def new_story_book(root: Path, folder: str, title: str, author: str, genre: str, premise: str, *, subtitle: str | None = None, audience: str = "adults",
                   chapters: int = 8, words_per_chapter: int = 1500, formats: list[str] | None = None, trim: str = "5x8", price: float = 9.99,
                   ebook_price: float = 2.99, keywords: list[str] | None = None, outline: list[str] | None = None, draft_ai: bool = True,
                   tone: str = "warm, gently humorous, hopeful", setting: str | None = None, pov: str = "third person limited",
                   chapter_label: str = "Chapter", categories: list[str] | None = None) -> Path:
    """A text book project: book.yaml (type story, paperback + Kindle eBook), story_brief.yaml for `kdp story draft`, and a
    manuscript skeleton with one Markdown file per chapter holding its outline line, to be drafted by AI or written by hand."""
    folder = folder.strip().lower()
    if not SLUG.match(folder):
        raise ValueError("tên thư mục chỉ gồm chữ thường, số và dấu gạch ngang (ví dụ lantern-lane)")
    if not title.strip() or not author.strip() or not genre.strip() or len(premise.strip()) < 10:
        raise ValueError("cần có tiêu đề, tác giả, thể loại và tiền đề (ít nhất một câu)")
    if trim not in STORY_TRIMS:
        raise ValueError(f"khổ truyện chữ phải là một trong {', '.join(STORY_TRIMS)}")
    chapters = max(1, min(60, int(chapters)))
    words_per_chapter = max(200, min(6000, int(words_per_chapter)))
    formats = [f for f in (formats or []) if f in ("paperback", "ebook", "hardcover")] or ["paperback", "ebook"]
    book_dir = Path(root) / folder
    if (book_dir / "book.yaml").exists():
        raise ValueError(f"{book_dir / 'book.yaml'} đã tồn tại")
    chapters_dir = book_dir / "manuscript" / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    lines = [ln.strip() for ln in (outline or []) if ln.strip()][:chapters]
    lines += skeleton_outline(chapters)[len(lines):]
    for i, line in enumerate(lines, start=1):
        ctitle, _, summary = line.partition(":")
        ctitle = re.sub(r"^(?:chapter\s+)?\d+\s*[.:)-]\s*", "", ctitle.strip().lstrip("#").strip(), flags=re.I).strip() or f"{chapter_label} {i}"
        (chapters_dir / chapter_filename(i, ctitle)).write_text(
            f"# {ctitle}\n\n{SKELETON_MARK}\n\n_{summary.strip() or 'Tóm tắt chương.'}_\n\n"
            "(Chương này chưa có nội dung. Bấm 'Viết nháp các chương' trên trang sách để AI viết từ dàn ý này, hoặc thay cả tệp bằng văn bản của bạn.)\n",
            encoding="utf-8")
    brief = {"premise": premise.strip(), "title_hint": title.strip(), "genre": genre.strip(), "audience": audience.strip() or "adults", "chapters": chapters,
             "words_per_chapter": words_per_chapter, "pov": pov, "tense": "past", "tone": tone, "setting": (setting or "").strip() or None, "themes": [],
             "content_rules": ["no explicit content", "no graphic violence", "no real brands, celebrities or copyrighted characters", "no profanity"],
             "language": "English",
             "extra_notes": "Chapter outline to follow, keeping these chapter titles and their order: " + " | ".join(f"{i}. {ln}" for i, ln in enumerate(lines, start=1))}
    (book_dir / "story_brief.yaml").write_text("# Brief for `kdp story draft` (bible -> outline -> chapters). Edit freely before drafting.\n"
                                               + yaml.safe_dump(brief, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    doc = {
        "id": f"st-{folder}-001", "type": "story", "niche": genre.strip(), "formats": formats,
        "metadata": {"title": title.strip(), "subtitle": (subtitle or "").strip() or None, "author": author.strip(), "language": "English",
                     "description_html": default_story_description(title.strip(), genre.strip(), premise, chapters, audience),
                     "keywords": (keywords or default_story_keywords(genre))[:7], "categories": (categories or [story_category(genre)])[:3]},
        "print": {"trim": trim, "paper": "cream_bw", "bleed": False, "cover_finish": "matte", "isbn": "kdp_free"},
        "ebook": {"drm": False, "accessibility_images": "all"},
        "interior": {"type": "story", "manuscript_dir": "manuscript", "chapters_glob": "chapters/*.md", "body_font": "georgia", "font_size_pt": 11, "leading": 1.45,
                     "chapter_label": chapter_label, "front_matter": ["title", "copyright"], "back_matter": ["review_cta"],
                     "review_cta": "If you enjoyed this book, a short honest review helps other readers find it. Thank you.",
                     "min_words": max(500, chapters * words_per_chapter // 2), "kindle_previewer": False},
        "cover": {"art": {"provider": "placeholder", "seed": 21}, "layout": "poster", "theme": "midnight", "back_blurb": premise.strip(),
                  "back_bullets": [f"{chapters} chapters", genre.strip().title(), "Paperback and Kindle edition"], "barcode_box": True},
        "pricing": {"marketplace": "amazon.com", "list_price": price, "ebook_list_price": ebook_price},
        "provenance": {"text": "ai_generated" if draft_ai else "human", "interior_images": "human", "cover_art": "human",
                       "ai_tools": list(STORY_AI_TOOLS) if draft_ai else []},
    }
    if doc["metadata"]["subtitle"] is None:
        del doc["metadata"]["subtitle"]
    path = book_dir / "book.yaml"
    path.write_text("# Generated by kdp-studio (Tạo sách, truyện chữ). Edit freely; run `kdp validate` after changes.\n"
                    + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    try:
        load_book(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def manuscript_stats(book_dir: Path, manuscript_dir: str = "manuscript", chapters_glob: str = "chapters/*.md") -> dict:
    """Chapters of a story book with word counts and whether they are still untouched skeletons."""
    chapters = []
    for f in sorted((Path(book_dir) / manuscript_dir).glob(chapters_glob)):
        text = f.read_text(encoding="utf-8", errors="replace")
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), f.stem)
        body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#") and SKELETON_MARK not in ln)
        chapters.append({"file": f.name, "path": str(f), "title": first.lstrip("#").strip(), "words": len(body.split()), "skeleton": SKELETON_MARK in text})
    return {"chapters": chapters, "words": sum(c["words"] for c in chapters if not c["skeleton"]), "drafted": sum(1 for c in chapters if not c["skeleton"]), "total": len(chapters)}
