"""Seed topics -> candidate niche keywords (template modifiers, optional autocomplete, optional Claude)."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ..llm import claude_available, parse_structured
from . import autocomplete

log = logging.getLogger(__name__)

MODIFIERS: dict[str, list[str]] = {
    "coloring": [
        "coloring book", "coloring book for adults", "coloring book for kids", "coloring book for seniors",
        "large print coloring book", "bold and easy coloring book", "coloring book for toddlers",
        "coloring book for teens", "coloring pages", "mandala coloring book", "coloring book for women",
        "coloring book for anxiety", "coloring book gift",
    ],
    "story": [
        "short reads", "cozy mystery", "clean romance", "bedtime stories", "chapter book", "short stories",
        "novella", "box set", "kids book ages 6-8", "picture book", "fantasy novel", "thriller",
    ],
    "generic": ["book", "for adults", "for kids", "for beginners", "gift", "large print", "workbook", "journal"],
}


class KeywordList(BaseModel):
    keywords: list[str] = Field(default_factory=list)


def _norm(k: str) -> str:
    return " ".join(k.lower().split())


def template_expand(seeds: list[str], book_type: str = "coloring") -> list[str]:
    mods = MODIFIERS.get(book_type, MODIFIERS["generic"])
    out: list[str] = []
    seen: set[str] = set()
    for seed in seeds:
        base = _norm(seed)
        cands = [base] + [f"{base} {m}" if m not in base else base for m in mods]
        for c in cands:
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def claude_expand(seeds: list[str], book_type: str, n: int = 30, model: str = "claude-opus-5-5") -> list[str]:
    system = (
        "You are a KDP niche researcher. Given seed topics, propose search phrases that real Amazon shoppers "
        "type when looking for this kind of book. Each phrase is 2-5 words, specific, free of brand names, "
        "copyrighted characters and promotional words (free, bestselling). Mix audiences (adults, seniors, kids "
        "age bands), formats and intents (gift, relaxation, learning). Return only the list."
    )
    user = f"Book type: {book_type}\nSeeds: {', '.join(seeds)}\nReturn {n} phrases, most promising first."
    result = parse_structured(system, user, KeywordList, model=model, max_tokens=4000)
    return [_norm(k) for k in result.keywords] if result else []


def expand_keywords(seeds: list[str], book_type: str = "coloring", use_autocomplete: bool = False, use_claude: bool = False, alias: str = "books", max_total: int = 60) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(items: list[str]) -> None:
        for k in items:
            nk = _norm(k)
            if nk and nk not in seen:
                seen.add(nk)
                out.append(nk)

    add(seeds)
    if use_claude and claude_available():
        add(claude_expand(seeds, book_type))
    if use_autocomplete:
        add(autocomplete.expand(seeds, alias=alias))
    add(template_expand(seeds, book_type))
    return out[:max_total]
