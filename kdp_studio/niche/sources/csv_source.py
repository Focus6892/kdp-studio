"""Import search results exported by browser tools (KDSpy, BookBeam, Publisher Rocket, Helium 10,
Apify dataset CSV/JSON...). Column names are matched case-insensitively through an alias table."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from ..models import BookObservation, parse_date, parse_float, parse_int

ALIASES: dict[str, list[str]] = {
    "keyword": ["keyword", "search term", "search_term", "query", "niche"],
    "asin": ["asin"],
    "title": ["title", "book title", "name"],
    "author": ["author", "authors", "by"],
    "price": ["price", "current price", "buy box price", "list price usd"],
    "list_price": ["list price", "list_price", "listprice", "rrp"],
    "bsr": ["bsr", "bsr overall", "bsroverall", "sales rank", "salesrank", "best sellers rank", "rank", "amazon bsr", "websitesalesrank"],
    "bsr_store": ["bsr store", "bsroverallcategory", "store", "top category"],
    "rating": ["rating", "avg rating", "average rating", "stars", "star rating"],
    "rating_count": ["rating count", "ratingcount", "ratings", "num ratings", "number of ratings", "review count", "reviews", "reviewcount", "customer reviews"],
    "review_count": ["written reviews", "text reviews"],
    "pub_date": ["pub date", "publication date", "published", "publish date", "publishdate", "release date", "date"],
    "pages": ["pages", "page count", "pagecount", "print length", "length"],
    "publisher": ["publisher", "imprint"],
    "format": ["format", "binding", "type"],
    "position": ["position", "organic position", "organicposition", "rank in results", "#"],
    "url": ["url", "detail url", "detailurl", "link", "product url"],
    "cover_url": ["cover", "cover url", "image", "coverimageurl", "image url"],
}


def _norm_header(h: str) -> str:
    return re.sub(r"[\s_\-]+", " ", h.strip().lower())


def build_column_map(headers: list[str]) -> dict[str, str]:
    """field -> actual header name."""
    normalized = {_norm_header(h): h for h in headers}
    out: dict[str, str] = {}
    for field, aliases in ALIASES.items():
        for a in aliases:
            if a in normalized and field not in out:
                out[field] = normalized[a]
                break
    return out


def rows_to_observations(rows: list[dict], source: str = "csv", default_keyword: str | None = None, store: str | None = None) -> list[BookObservation]:
    if not rows:
        return []
    cmap = build_column_map(list(rows[0].keys()))
    if "asin" not in cmap or "title" not in cmap:
        raise ValueError(f"Could not find ASIN/title columns. Headers: {list(rows[0].keys())}")
    out: list[BookObservation] = []
    for i, row in enumerate(rows, start=1):
        g = lambda f: row.get(cmap[f]) if f in cmap else None  # noqa: E731
        asin = (g("asin") or "").strip()
        if not asin:
            continue
        keyword = (g("keyword") or default_keyword or "").strip()
        if not keyword:
            raise ValueError("No keyword column in the file; pass --keyword to set one")
        out.append(
            BookObservation(
                keyword=keyword,
                source=source,
                asin=asin,
                title=(g("title") or "").strip(),
                author=(g("author") or None),
                price=parse_float(g("price")),
                list_price=parse_float(g("list_price")),
                bsr=parse_int(g("bsr")),
                bsr_store=(g("bsr_store") or store),
                rating=parse_float(g("rating")),
                rating_count=parse_int(g("rating_count")),
                review_count=parse_int(g("review_count")),
                pub_date=parse_date(g("pub_date")),
                pages=parse_int(g("pages")),
                publisher=(g("publisher") or None),
                format=(g("format") or None),
                position=parse_int(g("position")) or i,
                url=(g("url") or None),
                cover_url=(g("cover_url") or None),
            )
        )
    return out


def load_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in (".json", ".jsonl"):
        if path.suffix.lower() == ".jsonl":
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        data = json.loads(text)
        return data if isinstance(data, list) else data.get("items", [])
    return list(csv.DictReader(text.splitlines()))


class CsvSource:
    name = "csv"

    def __init__(self, path: Path, default_keyword: str | None = None, store: str | None = None):
        self.path = path
        self.books = rows_to_observations(load_rows(path), default_keyword=default_keyword, store=store)

    @property
    def keywords(self) -> list[str]:
        seen: list[str] = []
        for b in self.books:
            if b.keyword not in seen:
                seen.append(b.keyword)
        return seen

    def search(self, keyword: str, max_books: int) -> list[BookObservation]:
        hits = [b for b in self.books if b.keyword.lower() == keyword.lower()]
        hits.sort(key=lambda b: b.position or 10_000)
        return hits[:max_books]
