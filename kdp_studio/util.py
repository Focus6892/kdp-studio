"""Small shared helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f"Bad color '{color}'; expected #RRGGBB")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def file_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


# --------------------------------------------------------------------------- text helpers
SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"}

MODIFIER_PHRASES = [
    "coloring book for adults", "coloring book for kids", "coloring book for seniors", "coloring book for toddlers",
    "coloring book for teens", "coloring book for women", "coloring book", "coloring books", "coloring pages",
    "activity book", "for adults", "for seniors", "for kids", "for women", "for men", "for teens", "for toddlers",
    "for beginners", "for children", "large print", "bold and easy", "bold & easy", "easy", "simple", "big",
    "relaxing", "cute", "short reads", "short stories", "bedtime stories", "novel", "novella",
]
AUDIENCE_RE = re.compile(r"\bfor (adults|seniors|kids|women|men|teens|toddlers|beginners|children|boys|girls)\b")


def smart_title(text: str) -> str:
    """Title case that keeps small words lowercase and acronyms intact."""
    out = []
    for i, w in enumerate(text.split()):
        lw = w.lower()
        if i > 0 and lw in SMALL_WORDS:
            out.append(lw)
        elif w.isupper() and len(w) > 1:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def niche_subject(keyword: str) -> str:
    """'bold and easy flowers coloring book for seniors' -> 'flowers'."""
    k = " ".join(keyword.lower().split())
    for phrase in sorted(MODIFIER_PHRASES, key=len, reverse=True):
        k = re.sub(r"\b" + re.escape(phrase) + r"\b", " ", k)
    k = " ".join(k.split())
    return k or " ".join(keyword.lower().split())


def niche_audience(keyword: str) -> str | None:
    m = AUDIENCE_RE.search(keyword.lower())
    return m.group(1) if m else None


def clip_words(text: str, limit: int) -> str:
    """Cut at a word boundary so KDP's 50-char keyword limit never splits a word."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.strip()
