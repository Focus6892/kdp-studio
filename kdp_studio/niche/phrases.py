"""Title phrase mining: which 2-3 word phrases do the top results share?"""

from __future__ import annotations

import re
from collections import Counter

STOPWORDS = {
    "a", "an", "the", "for", "and", "of", "with", "to", "in", "on", "by", "&", "your", "you", "from", "at", "or",
    "this", "that", "is", "are", "be", "its", "it", "as", "into", "over", "vol", "volume", "edition", "ed",
}

BRAND_TERMS = [
    "disney", "pixar", "marvel", "dc comics", "pokemon", "pokémon", "barbie", "lego", "minecraft", "roblox",
    "hello kitty", "sanrio", "peppa pig", "paw patrol", "bluey", "harry potter", "star wars", "nintendo", "mario",
    "sonic", "frozen", "spider-man", "spiderman", "batman", "superman", "crayola", "dover", "taylor swift", "bts",
    "squishmallow", "fortnite", "cocomelon", "hot wheels", "transformers", "my little pony", "care bears",
    "stitch", "encanto", "moana", "avengers", "naruto", "one piece", "dragon ball",
]


def tokens(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    return [t for t in re.findall(r"[a-z0-9][a-z0-9'\-]*", text) if t not in STOPWORDS]


def ngrams(words: list[str], n: int) -> set[str]:
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def top_phrases(titles: list[str], n_min: int = 2, n_max: int = 3, top: int = 15, min_docs: int = 2) -> list[tuple[str, int]]:
    """Phrases ranked by the number of titles containing them (document frequency)."""
    counter: Counter[str] = Counter()
    for title in titles:
        words = tokens(title)
        seen: set[str] = set()
        for n in range(n_min, n_max + 1):
            seen |= ngrams(words, n)
        counter.update(seen)
    ranked = [(p, c) for p, c in counter.most_common() if c >= min_docs]
    # Drop 2-grams fully contained in an equally frequent 3-gram.
    kept: list[tuple[str, int]] = []
    for p, c in ranked:
        if any(p != q and p in q and cq >= c for q, cq in ranked):
            continue
        kept.append((p, c))
    return kept[:top]


def brand_hits(titles: list[str], terms: list[str] | None = None) -> list[str]:
    terms = terms or BRAND_TERMS
    joined = " || ".join(t.lower() for t in titles)
    return sorted({term for term in terms if re.search(r"\b" + re.escape(term) + r"\b", joined)})
