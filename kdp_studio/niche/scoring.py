"""Niche scoring: demand (BSR), competition ease (reviews / indie / freshness), monetization (price).

Scores are heuristics for *comparing* niches with each other, not sales forecasts.
BSR -> sales/day uses a log-log interpolation between widely published anchor points;
public estimators disagree by up to 7x for the same rank, so the figure is used only
for relative concentration (share of the top 3), never reported as an absolute.
"""

from __future__ import annotations

import math
import statistics as st

from .models import BookObservation, NicheSummary, ScoreBreakdown
from .phrases import brand_hits, top_phrases

PRICE_THRESHOLD = 9.99  # 60% royalty tier on amazon.com

# (bsr, est. sales/day) anchors; relative use only.
SALES_ANCHORS = {
    "Books": [(1, 2000), (100, 300), (1_000, 80), (10_000, 11), (100_000, 1.0), (1_000_000, 0.05), (5_000_000, 0.005)],
    "Kindle Store": [(1, 3000), (100, 400), (1_000, 90), (10_000, 12), (100_000, 1.0), (500_000, 0.1), (2_000_000, 0.01)],
}


def est_daily_sales(bsr: float | None, store: str | None = "Books") -> float | None:
    if bsr is None or bsr <= 0:
        return None
    anchors = SALES_ANCHORS.get(store or "Books", SALES_ANCHORS["Books"])
    lb = math.log10(bsr)
    pts = [(math.log10(b), math.log10(s)) for b, s in anchors]
    if lb <= pts[0][0]:
        return 10 ** pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= lb <= x1:
            t = (lb - x0) / (x1 - x0)
            return 10 ** (y0 + t * (y1 - y0))
    return 10 ** pts[-1][1]


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def demand_score(median_bsr: float | None, store: str | None = "Books") -> float:
    """0-40 on a log scale: BSR 1k -> 40, 10k -> ~28, 100k -> ~16, 2M -> 0.

    The same curve is used for the Books and Kindle Store ranks; the anchor tables
    above put both stores within ~10% of each other at equal rank, which is well
    inside the disagreement between public estimators."""
    if median_bsr is None or median_bsr <= 0:
        return 0.0
    top, floor = 3.0, 6.3
    return round(40 * _clamp((floor - math.log10(median_bsr)) / (floor - top)), 1)


def competition_score(median_rating_count: float | None, share_heavy: float | None, share_indie: float | None, share_fresh: float | None) -> float:
    """0-40. Fewer reviews, fewer 1000+ review books, more indie publishers and more recent entrants = easier."""
    parts = []
    if median_rating_count is not None:
        # 10 ratings -> 1.0, 1000 ratings -> 0.0 (log scale)
        parts.append((0.4, _clamp((3.0 - math.log10(max(median_rating_count, 1))) / 2.0)))
    if share_heavy is not None:
        parts.append((0.2, 1.0 - _clamp(share_heavy)))
    if share_indie is not None:
        parts.append((0.2, _clamp(share_indie)))
    if share_fresh is not None:
        parts.append((0.2, _clamp(share_fresh / 0.5)))  # 50% fresh entrants = fully open market
    if not parts:
        return 0.0
    total_w = sum(w for w, _ in parts)
    return round(40 * sum(w * v for w, v in parts) / total_w, 1)


def monetization_score(median_price: float | None, share_ge_threshold: float | None, threshold: float = PRICE_THRESHOLD) -> float:
    """0-20. Median at/above the 60%-tier threshold and most books priced there = full marks."""
    if median_price is None:
        return 0.0
    p = _clamp((median_price - 4.99) / (threshold + 3.0 - 4.99))
    s = share_ge_threshold if share_ge_threshold is not None else p
    return round(20 * (0.6 * p + 0.4 * _clamp(s)), 1)


def confidence_score(n_books: int, n_with_bsr: int, n_with_ratings: int) -> float:
    """0-100: how much to trust the summary (sample size and field coverage)."""
    if n_books == 0:
        return 0.0
    size = _clamp(n_books / 16)
    cov = (0.5 * n_with_bsr + 0.5 * n_with_ratings) / n_books
    return round(100 * (0.5 * size + 0.5 * cov), 0)


def label_for(opportunity: float, confidence: float) -> str:
    if confidence < 35:
        return "insufficient data"
    if opportunity >= 70:
        return "strong"
    if opportunity >= 55:
        return "promising"
    if opportunity >= 40:
        return "crowded"
    return "weak"


def _median(values: list[float]) -> float | None:
    return float(st.median(values)) if values else None


def _share(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 3) if flags else None


def summarize(keyword: str, books: list[BookObservation], source: str, top_n: int = 10, threshold: float = PRICE_THRESHOLD) -> NicheSummary:
    books = sorted(books, key=lambda b: (b.position if b.position is not None else 10_000))
    store = next((b.bsr_store for b in books if b.bsr_store), None)
    with_bsr = [b for b in books if b.bsr]
    top_bsr = sorted(b.bsr for b in with_bsr)[:top_n]  # type: ignore[type-var]
    prices = [b.price for b in books if b.price]
    rcs = [b.rating_count for b in books if b.rating_count is not None]
    pages = [b.pages for b in books if b.pages]

    median_bsr = _median([float(x) for x in top_bsr])
    median_price = _median([float(p) for p in prices])
    median_rc = _median([float(r) for r in rcs])
    share_heavy = _share([r >= 1000 for r in rcs])
    share_low = _share([r <= 20 for r in rcs])
    share_indie = _share([bool(b.is_indie) for b in books if b.is_indie is not None])
    share_fresh = _share([b.age_days <= 365 for b in books if b.age_days is not None])
    share_price_ge = _share([p >= threshold - 1e-9 for p in prices])

    titles = [b.title for b in books]
    hits = brand_hits(titles)
    sales = sorted((est_daily_sales(b.bsr, store) or 0.0 for b in with_bsr), reverse=True)
    conc = round(sum(sales[:3]) / sum(sales), 3) if sales and sum(sales) > 0 and len(sales) >= 5 else None

    d = demand_score(median_bsr, store)
    c = competition_score(median_rc, share_heavy, share_indie, share_fresh)
    m = monetization_score(median_price, share_price_ge, threshold)
    opp = round(d + c + m, 1)
    conf = confidence_score(len(books), len(with_bsr), len(rcs))
    scores = ScoreBreakdown(demand=d, competition=c, monetization=m, opportunity=opp, confidence=conf, label=label_for(opp, conf))

    flags: list[str] = []
    if len(books) < 8:
        flags.append(f"small sample ({len(books)} books)")
    if hits:
        flags.append("brand/IP terms in top titles: " + ", ".join(hits))
    if conc is not None and conc > 0.5:
        flags.append(f"top 3 books hold ~{conc:.0%} of estimated sales")
    if share_indie is not None and share_indie < 0.3:
        flags.append(f"few independent publishers ({share_indie:.0%})")
    if share_fresh is not None and share_fresh < 0.1:
        flags.append(f"almost no new entrants in 12 months ({share_fresh:.0%})")
    if share_heavy is not None and share_heavy > 0.5:
        flags.append(f"{share_heavy:.0%} of books have 1000+ ratings")
    if median_price is not None and median_price < threshold:
        flags.append(f"median price ${median_price:.2f} sits in the 50% royalty tier")
    if median_bsr is not None and median_bsr > 500_000:
        flags.append("weak demand: median BSR of the top 10 above 500k")

    return NicheSummary(
        keyword=keyword,
        source=source,
        n_books=len(books),
        n_with_bsr=len(with_bsr),
        bsr_store=store,
        median_bsr=median_bsr,
        best_bsr=min(top_bsr) if top_bsr else None,
        p25_bsr=float(sorted(top_bsr)[len(top_bsr) // 4]) if top_bsr else None,
        median_price=median_price,
        share_price_ge_threshold=share_price_ge,
        median_rating_count=median_rc,
        share_heavy_reviews=share_heavy,
        share_low_reviews=share_low,
        share_indie=share_indie,
        share_fresh_365=share_fresh,
        median_pages=_median([float(p) for p in pages]),
        top_phrases=top_phrases(titles),
        brand_hits=hits,
        concentration_top3=conc,
        scores=scores,
        flags=flags,
        top_titles=titles[:10],
    )
