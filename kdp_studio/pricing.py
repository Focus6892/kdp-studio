"""KDP printing cost and royalty math (Amazon.com marketplace, USD).

Sources (fetched 2026-10-23):
- Printing cost: https://kdp.amazon.com/en_US/help/topic/G201834340
- Royalty tiers (60% at list >= $9.99, 50% below, since 2025-06-10):
  https://kdp.amazon.com/en_US/help/topic/GXFPA52P6ZJD2U3N
Other marketplaces use different thresholds and currencies; add them to
MARKETPLACES after checking the KDP Royalties page.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

from .specs import get_trim

MARKETPLACES: dict[str, dict] = {
    "amazon.com": {"currency": "USD", "threshold": 9.99, "high_rate": 0.60, "low_rate": 0.50},
}

# ink_group -> size_class -> list of (min_pages, max_pages, fixed_cost, per_page_cost)
PRINT_COST_USD: dict[str, dict[str, list[tuple[int, int, float, float]]]] = {
    "black": {
        "regular": [(24, 108, 2.30, 0.0), (110, 828, 1.00, 0.012)],
        "large": [(24, 108, 2.84, 0.0), (110, 828, 1.00, 0.017)],
    },
    "groundwood": {
        "regular": [(24, 112, 2.23, 0.0), (114, 828, 1.00, 0.0114)],
        "large": [(24, 112, 2.75, 0.0), (114, 828, 1.00, 0.0162)],
    },
    "premium_color": {
        "regular": [(24, 40, 3.60, 0.0), (42, 828, 1.00, 0.065)],
        "large": [(24, 40, 4.20, 0.0), (42, 828, 1.00, 0.08)],
    },
    "standard_color": {
        "regular": [(72, 600, 1.00, 0.0255)],
        "large": [(72, 600, 1.00, 0.0402)],
    },
}

EBOOK_DELIVERY_USD_PER_MB = 0.15


def ink_group(paper: str) -> str:
    if paper in ("white_bw", "cream_bw"):
        return "black"
    if paper == "groundwood_bw":
        return "groundwood"
    if paper in ("premium_color", "standard_color"):
        return paper
    raise ValueError(f"Unknown paper type '{paper}'")


def printing_cost(trim_key: str, paper: str, pages: int, marketplace: str = "amazon.com") -> float:
    if marketplace != "amazon.com":
        raise ValueError("Only amazon.com printing costs are encoded so far")
    trim = get_trim(trim_key)
    tiers = PRINT_COST_USD[ink_group(paper)][trim.size_class]
    for lo, hi, fixed, per_page in tiers:
        if lo <= pages <= hi:
            return round(fixed + pages * per_page, 2)
    # Even page counts never land in the 1-page gaps between tiers, but be safe.
    for lo, hi, fixed, per_page in tiers:
        if pages < lo:
            return round(fixed + pages * per_page, 2)
    raise ValueError(f"Page count {pages} is outside the printable range for {paper} on {trim_key}")


def royalty_rate(list_price: float, marketplace: str = "amazon.com") -> float:
    m = MARKETPLACES[marketplace]
    return m["high_rate"] if list_price >= m["threshold"] - 1e-9 else m["low_rate"]


def royalty(list_price: float, trim_key: str, paper: str, pages: int, marketplace: str = "amazon.com") -> float:
    cost = printing_cost(trim_key, paper, pages, marketplace)
    return round(royalty_rate(list_price, marketplace) * list_price - cost, 2)


def min_list_price(trim_key: str, paper: str, pages: int, marketplace: str = "amazon.com") -> float:
    """Lowest list price KDP accepts (royalty >= 0), considering both rate tiers."""
    m = MARKETPLACES[marketplace]
    cost = printing_cost(trim_key, paper, pages, marketplace)
    low_tier_min = math.ceil(cost / m["low_rate"] * 100) / 100
    if low_tier_min < m["threshold"]:
        return low_tier_min
    high_tier_min = math.ceil(cost / m["high_rate"] * 100) / 100
    return max(m["threshold"], high_tier_min)


def ebook_royalty(list_price: float, file_size_mb: float = 1.0, marketplace: str = "amazon.com") -> float:
    """70% tier for $2.99-$9.99 (minus delivery fee), otherwise 35%."""
    if 2.99 <= list_price <= 9.99:
        return round(0.70 * (list_price - EBOOK_DELIVERY_USD_PER_MB * file_size_mb), 2)
    return round(0.35 * list_price, 2)


@dataclass
class PriceReport:
    trim: str
    paper: str
    pages: int
    marketplace: str
    printing_cost: float
    list_price: float
    royalty_rate: float
    royalty_per_copy: float
    min_list_price: float
    threshold_price: float
    royalty_at_threshold: float

    def as_dict(self) -> dict:
        return asdict(self)


def price_report(trim_key: str, paper: str, pages: int, list_price: float, marketplace: str = "amazon.com") -> PriceReport:
    m = MARKETPLACES[marketplace]
    cost = printing_cost(trim_key, paper, pages, marketplace)
    return PriceReport(
        trim=trim_key,
        paper=paper,
        pages=pages,
        marketplace=marketplace,
        printing_cost=cost,
        list_price=list_price,
        royalty_rate=royalty_rate(list_price, marketplace),
        royalty_per_copy=royalty(list_price, trim_key, paper, pages, marketplace),
        min_list_price=min_list_price(trim_key, paper, pages, marketplace),
        threshold_price=m["threshold"],
        royalty_at_threshold=royalty(m["threshold"], trim_key, paper, pages, marketplace),
    )
