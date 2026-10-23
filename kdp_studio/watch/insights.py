"""Review mining -> differentiation brief. Reviews come from a text/JSON file you export
yourself (copy from the product page, a Chrome extension export, etc.); this module does
not scrape Amazon. Claude extracts themes when available; otherwise a lexicon heuristic runs."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from ..llm import claude_available, parse_structured


class ReviewInsights(BaseModel):
    complaints: list[str] = Field(default_factory=list)
    praise: list[str] = Field(default_factory=list)
    requests: list[str] = Field(default_factory=list)
    differentiation_brief: list[str] = Field(default_factory=list)
    summary: str = ""
    source: str = "heuristic"


COMPLAINT_LEXICON = {
    "paper too thin / bleed-through": ["thin paper", "bleed through", "bleeds through", "bled through", "see through", "shows through"],
    "double-sided pages": ["both sides", "double sided", "double-sided", "back of the page", "back side"],
    "designs too detailed / small": ["too detailed", "too small", "tiny", "intricate", "hard to see", "squint", "eye strain", "too complex", "too busy"],
    "repetitive or duplicate pages": ["repetitive", "same picture", "duplicate", "repeated", "copy and paste", "copied"],
    "print quality / blurry lines": ["blurry", "pixelated", "low quality", "faded", "fuzzy", "jagged"],
    "binding / pages falling out": ["binding", "fell out", "falling out", "spine", "pages came loose"],
    "misleading cover or description": ["not as described", "misleading", "nothing like the cover", "cover is different", "false advertising"],
    "too few pages / short": ["too short", "not enough pages", "only", "few pages", "too few"],
    "ai-looking artwork": ["ai generated", "ai-generated", "ai art", "computer generated", "extra fingers"],
    "price too high": ["overpriced", "too expensive", "not worth"],
}
PRAISE_LEXICON = {
    "thick bold lines": ["thick lines", "bold lines", "bold outlines", "big shapes", "easy to color", "simple designs"],
    "single-sided pages": ["single sided", "single-sided", "one side", "blank back"],
    "relaxing / calming": ["relaxing", "calming", "stress relief", "therapeutic", "soothing"],
    "good for seniors / low vision": ["seniors", "elderly", "grandma", "grandmother", "dementia", "low vision", "arthritis", "my mom"],
    "variety of designs": ["variety", "lots of different", "no repeats", "unique designs"],
    "paper quality": ["thick paper", "good paper", "quality paper", "heavy paper"],
    "great gift": ["gift", "present", "loved it"],
}
REQUEST_PATTERNS = [r"\bwish(?:ed)? (?:it|there|they|the book)\b([^.!?]*)", r"\bwould (?:be nice|love|like|prefer)\b([^.!?]*)", r"\bshould (?:have|include|be)\b([^.!?]*)", r"\bif only\b([^.!?]*)"]


def load_reviews(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".json", ".jsonl"):
        data = [json.loads(l) for l in text.splitlines() if l.strip()] if path.suffix.lower() == ".jsonl" else json.loads(text)
        if isinstance(data, dict):
            data = data.get("reviews") or data.get("items") or []
        out = []
        for d in data:
            if isinstance(d, str):
                out.append(d)
            elif isinstance(d, dict):
                out.append(" ".join(str(d.get(k, "")) for k in ("title", "text", "body", "review", "content") if d.get(k)))
        return [r for r in out if r.strip()]
    # plain text: blank-line separated reviews (or one per line)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return blocks if len(blocks) > 1 else [l.strip() for l in text.splitlines() if l.strip()]


def _hits(reviews: list[str], lexicon: dict[str, list[str]]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for r in reviews:
        low = r.lower()
        for theme, cues in lexicon.items():
            if any(c in low for c in cues):
                counter[theme] += 1
    return counter.most_common()


def heuristic_insights(reviews: list[str]) -> ReviewInsights:
    n = max(len(reviews), 1)
    complaints = [f"{theme} ({count} of {n} reviews)" for theme, count in _hits(reviews, COMPLAINT_LEXICON)]
    praise = [f"{theme} ({count} of {n} reviews)" for theme, count in _hits(reviews, PRAISE_LEXICON)]
    requests: list[str] = []
    for r in reviews:
        for pat in REQUEST_PATTERNS:
            for m in re.finditer(pat, r, re.IGNORECASE):
                frag = " ".join(m.group(0).split())
                if 12 <= len(frag) <= 140 and frag not in requests:
                    requests.append(frag)
    brief = []
    for theme, count in _hits(reviews, COMPLAINT_LEXICON)[:5]:
        brief.append({
            "paper too thin / bleed-through": "Print single-sided on white paper and say so on the cover and in the first bullet.",
            "double-sided pages": "One design per page with a blank back; state it in the subtitle or bullets.",
            "designs too detailed / small": "Bold outlines, large shapes, fewer elements per page; mention 'large print' / 'bold and easy'.",
            "repetitive or duplicate pages": "Run the dedupe check and promise 'no repeated designs' in the description.",
            "print quality / blurry lines": "Render at 300 DPI with crisp 1-bit line art; avoid gray anti-aliasing.",
            "binding / pages falling out": "Keep page count moderate (60-100) so the glue binding holds; recommend scanning pages for markers.",
            "misleading cover or description": "Show interior samples in A+ Content and keep the cover style consistent with the pages.",
            "too few pages / short": "Add a color-test page and bonus pages; state the exact design count in the subtitle.",
            "ai-looking artwork": "Run vision QA for artifacts; disclose AI use to KDP; curate every page by hand.",
            "price too high": "Price at $9.99 (60% tier) and justify with page count and single-sided printing.",
        }.get(theme, f"Address: {theme}") + f" (seen in {count} reviews)")
    return ReviewInsights(complaints=complaints, praise=praise, requests=requests[:10], differentiation_brief=brief, summary=f"{len(reviews)} reviews analyzed with the offline lexicon.", source="heuristic")


def claude_insights(reviews: list[str], product_context: str = "", model: str = "claude-opus-5-5") -> ReviewInsights | None:
    system = (
        "You analyze Amazon customer reviews for an independent publisher planning a competing book. Extract recurring complaints, "
        "recurring praise and explicit requests, each as a short phrase with an approximate count. Then write a differentiation brief: "
        "5-8 concrete, verifiable product decisions (paper, page layout, line weight, design count, pricing, description promises) that "
        "would beat the reviewed books. No marketing fluff; never quote more than a few words from any review."
    )
    joined = "\n\n".join(f"[{i + 1}] {r.strip()}" for i, r in enumerate(reviews[:300]))
    user = f"Product context: {product_context or 'n/a'}\n\nReviews ({len(reviews)}):\n{joined}"
    res = parse_structured(system, user, ReviewInsights, model=model, max_tokens=6000)
    if res:
        res.source = "claude"
    return res


def mine_reviews(reviews: list[str], use_claude: bool = True, product_context: str = "") -> ReviewInsights:
    if use_claude and claude_available():
        res = claude_insights(reviews, product_context)
        if res:
            return res
    return heuristic_insights(reviews)


def insights_markdown(ins: ReviewInsights) -> str:
    lines = ["# Review insights", "", ins.summary, ""]
    for title, items in (("Complaints", ins.complaints), ("Praise", ins.praise), ("Requests", ins.requests), ("Differentiation brief", ins.differentiation_brief)):
        lines.append(f"## {title}")
        lines.extend(f"- {x}" for x in items) if items else lines.append("- none found")
        lines.append("")
    lines.append(f"_Source: {ins.source}_")
    return "\n".join(lines) + "\n"
