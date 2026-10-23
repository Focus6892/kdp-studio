"""Amazon Ads campaign export (CSV) -> ACOS review against a break-even derived from royalties.

Export from the Amazon Ads console (Campaigns table -> Export). Column names vary by
locale and report type; the alias table below covers the common ones.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

ALIASES: dict[str, list[str]] = {
    "campaign": ["campaign", "campaigns", "campaign name", "name"],
    "status": ["status", "state", "campaign status"],
    "impressions": ["impressions"],
    "clicks": ["clicks"],
    "spend": ["spend", "cost", "total spend", "spend(usd)", "spend (usd)"],
    "orders": ["orders", "14 day total orders (#)", "14 day total orders", "purchases", "conversions", "total orders"],
    "sales": ["sales", "14 day total sales", "14 day total sales ($)", "revenue", "total sales", "sales(usd)"],
    "acos": ["acos", "advertising cost of sales", "acos (%)"],
    "budget": ["budget", "daily budget"],
}


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower().replace("_", " "))


def _num(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("-", "–", "N/A", "n/a"):
        return None
    s = s.replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def column_map(headers: list[str]) -> dict[str, str]:
    normalized = {_norm(h): h for h in headers}
    out: dict[str, str] = {}
    for field_name, aliases in ALIASES.items():
        for a in aliases:
            if a in normalized and field_name not in out:
                out[field_name] = normalized[a]
                break
    return out


@dataclass
class AdsRow:
    campaign: str
    status: str | None
    impressions: float
    clicks: float
    spend: float
    orders: float
    sales: float
    acos: float | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def cpc(self) -> float | None:
        return self.spend / self.clicks if self.clicks else None

    @property
    def ctr(self) -> float | None:
        return self.clicks / self.impressions if self.impressions else None

    @property
    def cvr(self) -> float | None:
        return self.orders / self.clicks if self.clicks else None

    def as_dict(self) -> dict:
        return {"campaign": self.campaign, "status": self.status, "impressions": self.impressions, "clicks": self.clicks, "spend": round(self.spend, 2), "orders": self.orders, "sales": round(self.sales, 2), "acos": self.acos, "cpc": self.cpc, "ctr": self.ctr, "cvr": self.cvr, "flags": self.flags}


def load_ads_csv(path: Path) -> list[AdsRow]:
    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        return []
    cmap = column_map(list(rows[0].keys()))
    if "campaign" not in cmap or "spend" not in cmap:
        raise ValueError(f"Could not find campaign/spend columns. Headers: {list(rows[0].keys())}")
    out: list[AdsRow] = []
    for r in rows:
        g = lambda f: r.get(cmap[f]) if f in cmap else None  # noqa: E731
        name = (g("campaign") or "").strip()
        if not name or name.lower() in ("total", "totals"):
            continue
        spend = _num(g("spend")) or 0.0
        sales = _num(g("sales")) or 0.0
        acos = _num(g("acos"))
        if acos is not None and acos > 1.5:  # given as percent
            acos = acos / 100
        if acos is None:
            acos = (spend / sales) if sales else None
        out.append(AdsRow(name, (g("status") or None), _num(g("impressions")) or 0.0, _num(g("clicks")) or 0.0, spend, _num(g("orders")) or 0.0, sales, acos))
    return out


def break_even_acos(royalty_per_copy: float, list_price: float) -> float:
    """Spend per sale that exactly eats the royalty: royalty / list price."""
    return royalty_per_copy / list_price if list_price else 0.0


def summarize_ads(rows: list[AdsRow], target_acos: float = 0.30, break_even: float | None = None, min_clicks_for_judgement: int = 10) -> dict:
    tot_spend = sum(r.spend for r in rows)
    tot_sales = sum(r.sales for r in rows)
    tot_clicks = sum(r.clicks for r in rows)
    tot_orders = sum(r.orders for r in rows)
    for r in rows:
        r.flags = []
        if r.clicks >= min_clicks_for_judgement and r.orders == 0:
            r.flags.append(f"{int(r.clicks)} clicks, no orders — pause or cut bids")
        if r.acos is not None and break_even is not None and r.acos > break_even:
            r.flags.append(f"ACOS {r.acos:.0%} above break-even {break_even:.0%} — losing money per sale")
        elif r.acos is not None and r.acos > target_acos:
            r.flags.append(f"ACOS {r.acos:.0%} above target {target_acos:.0%}")
        if r.cvr is not None and r.clicks >= min_clicks_for_judgement and r.cvr < 0.05:
            r.flags.append(f"conversion {r.cvr:.1%} (< 5%) — listing/cover/price problem, not a bid problem")
    return {
        "campaigns": len(rows),
        "spend": round(tot_spend, 2),
        "sales": round(tot_sales, 2),
        "clicks": tot_clicks,
        "orders": tot_orders,
        "acos": (tot_spend / tot_sales) if tot_sales else None,
        "cpc": (tot_spend / tot_clicks) if tot_clicks else None,
        "target_acos": target_acos,
        "break_even_acos": break_even,
        "rows": sorted(rows, key=lambda r: -r.spend),
        "flagged": [r.campaign for r in rows if r.flags],
    }


def ads_markdown(summary: dict) -> str:
    def pct(v):
        return f"{v:.0%}" if v is not None else "–"

    lines = ["## Amazon Ads", ""]
    lines.append(f"Campaigns: {summary['campaigns']} · spend ${summary['spend']:,.2f} · sales ${summary['sales']:,.2f} · ACOS {pct(summary['acos'])} · CPC {('$' + format(summary['cpc'], '.2f')) if summary['cpc'] else '–'} · target {pct(summary['target_acos'])}" + (f" · break-even {pct(summary['break_even_acos'])}" if summary["break_even_acos"] is not None else ""))
    lines.append("")
    lines.append("| Campaign | Status | Impr. | Clicks | CTR | CPC | Orders | CVR | Spend | Sales | ACOS | Flags |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in summary["rows"]:
        lines.append(
            f"| {r.campaign} | {r.status or '–'} | {int(r.impressions):,} | {int(r.clicks):,} | {pct(r.ctr) if r.ctr is None or r.ctr < 1 else f'{r.ctr:.1%}'} | {('$' + format(r.cpc, '.2f')) if r.cpc else '–'} | {int(r.orders)} | {pct(r.cvr)} | ${r.spend:,.2f} | ${r.sales:,.2f} | {pct(r.acos)} | {'; '.join(r.flags) or '–'} |"
        )
    return "\n".join(lines) + "\n"
