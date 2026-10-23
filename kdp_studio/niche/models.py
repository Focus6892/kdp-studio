"""Data model for niche research: one observed book, one keyword summary, one concept."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from pydantic import BaseModel, Field

INDIE_MARKERS = ("independently published", "independent publisher", "createspace", "kdp print", "self-published")

_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y", "%Y/%m/%d", "%Y-%m", "%B %Y", "%Y")


def parse_date(value: Any) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d[\d,\.]*", str(value).replace(" ", "").replace(" ", ""))
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(0))
    return int(digits) if digits else None


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:[\.,]\d+)?", str(value))
    if not m:
        return None
    return float(m.group(0).replace(",", "."))


def is_indie_publisher(publisher: str | None) -> bool | None:
    if not publisher:
        return None
    p = publisher.lower()
    return any(m in p for m in INDIE_MARKERS)


class BookObservation(BaseModel):
    keyword: str
    source: str
    asin: str
    title: str
    author: str | None = None
    price: float | None = None
    list_price: float | None = None
    currency: str = "USD"
    bsr: int | None = None
    bsr_store: str | None = None  # "Books" or "Kindle Store"
    category_ranks: list[tuple[str, int]] = Field(default_factory=list)
    rating: float | None = None
    rating_count: int | None = None
    review_count: int | None = None
    pub_date: dt.date | None = None
    age_days: int | None = None
    pages: int | None = None
    publisher: str | None = None
    is_indie: bool | None = None
    format: str | None = None
    position: int | None = None
    url: str | None = None
    cover_url: str | None = None
    observed_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    def model_post_init(self, __context: Any) -> None:
        if self.age_days is None and self.pub_date is not None:
            self.age_days = max(0, (dt.date.today() - self.pub_date).days)
        if self.is_indie is None:
            self.is_indie = is_indie_publisher(self.publisher)

    @property
    def search_text(self) -> str:
        return self.title


class ScoreBreakdown(BaseModel):
    demand: float = 0.0
    competition: float = 0.0
    monetization: float = 0.0
    opportunity: float = 0.0
    confidence: float = 0.0
    label: str = "insufficient data"


class NicheSummary(BaseModel):
    keyword: str
    source: str
    n_books: int
    n_with_bsr: int
    bsr_store: str | None = None
    median_bsr: float | None = None
    best_bsr: int | None = None
    p25_bsr: float | None = None
    median_price: float | None = None
    share_price_ge_threshold: float | None = None
    median_rating_count: float | None = None
    share_heavy_reviews: float | None = None
    share_low_reviews: float | None = None
    share_indie: float | None = None
    share_fresh_365: float | None = None
    median_pages: float | None = None
    top_phrases: list[tuple[str, int]] = Field(default_factory=list)
    brand_hits: list[str] = Field(default_factory=list)
    concentration_top3: float | None = None
    scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    flags: list[str] = Field(default_factory=list)
    top_titles: list[str] = Field(default_factory=list)
    observed_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


class ConceptCard(BaseModel):
    title_idea: str
    angle: str
    audience: str
    differentiation: str
    why_it_can_rank: str
    risks: str
    keywords: list[str] = Field(default_factory=list)


class NicheRun(BaseModel):
    ts: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    source: str
    book_type: str
    topics: list[str]
    keywords: list[str]
    summaries: list[NicheSummary] = Field(default_factory=list)
    concepts: dict[str, list[ConceptCard]] = Field(default_factory=dict)
    run_id: int | None = None

    def ranked(self) -> list[NicheSummary]:
        return sorted(self.summaries, key=lambda s: (-s.scores.opportunity, -s.scores.confidence))
