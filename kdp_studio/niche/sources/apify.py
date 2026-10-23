"""Apify actor `getascraper/kdp-book-niche-analyzer` as a book source.

The actor scrapes Kindle Store search results (so BSR is the Kindle Store rank) and
returns BOOK records with the fields listed in its README (bsrOverall, ratingCount,
publishDate, publisherType, organicPosition, ...). Pay-per-event pricing, roughly
$1 per 1,000 book records. Requires APIFY_TOKEN.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

from ..models import BookObservation, parse_date, parse_float, parse_int

log = logging.getLogger(__name__)

ACTOR_ID = "getascraper~kdp-book-niche-analyzer"
API = "https://api.apify.com/v2"


def record_to_observation(rec: dict, store: str = "Kindle Store") -> BookObservation | None:
    if rec.get("recordType", "BOOK") != "BOOK" or not rec.get("asin"):
        return None
    ranks = []
    for cr in rec.get("categoryRanks") or []:
        if isinstance(cr, dict) and cr.get("rank") is not None:
            ranks.append((str(cr.get("category") or cr.get("name") or ""), int(cr["rank"])))
    publisher_type = (rec.get("publisherType") or "").lower()
    is_indie = None
    if publisher_type:
        is_indie = "independent" in publisher_type or "self" in publisher_type
    return BookObservation(
        keyword=rec.get("keyword") or "",
        source="apify",
        asin=rec["asin"],
        title=rec.get("title") or "",
        author=rec.get("author"),
        price=parse_float(rec.get("price")),
        list_price=parse_float(rec.get("listPrice")),
        currency=rec.get("currency") or "USD",
        bsr=parse_int(rec.get("bsrOverall")),
        bsr_store=rec.get("bsrOverallCategory") or store,
        category_ranks=ranks,
        rating=parse_float(rec.get("rating")),
        rating_count=parse_int(rec.get("ratingCount")),
        review_count=parse_int(rec.get("reviewCount")),
        pub_date=parse_date(rec.get("publishDate")),
        age_days=parse_int(rec.get("publicationAgeDays")),
        pages=parse_int(rec.get("pageCount")),
        publisher=rec.get("publisher"),
        is_indie=is_indie,
        format=rec.get("format"),
        position=parse_int(rec.get("organicPosition")),
        url=rec.get("detailUrl"),
        cover_url=rec.get("coverImageUrl"),
    )


class ApifySource:
    name = "apify"

    def __init__(self, token: str | None = None, store: str = "Kindle Store", timeout_s: int = 600):
        self.token = token or os.environ.get("APIFY_TOKEN")
        if not self.token:
            raise RuntimeError("APIFY_TOKEN is not set")
        self.store = store
        self.timeout_s = timeout_s
        self._cache: dict[str, list[BookObservation]] = {}

    def run(self, keywords: list[str], max_books: int) -> dict[str, list[BookObservation]]:
        body = {
            "keywords": keywords,
            "bookUrls": [],
            "includeAutocompleteSuggestions": False,
            "analyzeAutocompleteSuggestions": False,
            "maxBooksPerKeyword": max_books,
            "includeNicheRows": False,
            "monitorChanges": False,
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyCountry": "US"},
        }
        q = urllib.parse.urlencode({"token": self.token, "timeout": self.timeout_s, "format": "json", "clean": "true"})
        req = urllib.request.Request(
            f"{API}/acts/{ACTOR_ID}/run-sync-get-dataset-items?{q}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s + 30) as resp:  # noqa: S310 - fixed https endpoint
            items = json.load(resp)
        out: dict[str, list[BookObservation]] = {k: [] for k in keywords}
        for rec in items:
            obs = record_to_observation(rec, self.store)
            if obs is None:
                continue
            out.setdefault(obs.keyword, []).append(obs)
        for k, books in out.items():
            books.sort(key=lambda b: b.position or 10_000)
        self._cache.update(out)
        return out

    def search(self, keyword: str, max_books: int) -> list[BookObservation]:
        if keyword not in self._cache:
            self.run([keyword], max_books)
        return self._cache.get(keyword, [])[:max_books]
