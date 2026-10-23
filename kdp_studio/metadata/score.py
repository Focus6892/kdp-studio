"""Rubric scoring for metadata candidates (0-100). Compliance dominates; the rest rewards
search coverage, readable lengths and use of the brief's differentiators."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..findings import FindingList
from ..metadata_rules import HTML_TAG
from .brief import Brief
from .generate import MetadataCandidate


@dataclass
class ScoredCandidate:
    candidate: MetadataCandidate
    findings: FindingList
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "breakdown": self.breakdown,
            "errors": [f.message for f in self.findings.errors],
            "warnings": [f.message for f in self.findings.warnings],
            "candidate": self.candidate.model_dump(mode="json"),
        }


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def score_candidate(cand: MetadataCandidate, brief: Brief, findings: FindingList) -> tuple[float, dict[str, float]]:
    b: dict[str, float] = {}
    b["compliance"] = max(0.0, 40.0 - 15.0 * len(findings.errors) - 4.0 * len(findings.warnings))

    title_words = _words(cand.title + " " + (cand.subtitle or ""))
    kws = [k for k in cand.keywords if k.strip()]
    kw_score = 5.0 if len(kws) == 7 else 2.0 if len(kws) >= 5 else 0.0
    if kws and not any((_words(k) - {"for", "and", "the", "of", "a", "with"}) <= title_words for k in kws):
        kw_score += 5.0
    if kws:
        avg_len = sum(len(k.split()) for k in kws) / len(kws)
        if 2 <= avg_len <= 4:
            kw_score += 5.0
    b["keywords"] = kw_score

    t = 5.0 if len(cand.title) <= 60 else 2.0
    sub = cand.subtitle or ""
    t += 5.0 if 40 <= len(sub) <= 150 else 2.0 if sub else 0.0
    niche_terms = _words(brief.niche_keyword) - {"for", "and", "the", "of", "a", "with", "book"}
    if niche_terms and len(niche_terms & title_words) >= max(1, len(niche_terms) // 2):
        t += 5.0
    b["title"] = t

    d = cand.description_html
    plain = HTML_TAG.sub(" ", d)
    ds = 5.0 if 500 <= len(d) <= 3000 else 2.0 if 250 <= len(d) <= 3800 else 0.0
    if re.search(r"<(ul|ol|li|h4|h5|h6)\b", d, re.IGNORECASE):
        ds += 5.0
    diff_hits = sum(1 for term in (brief.differentiators + brief.must_include_terms) if term and term.lower() in plain.lower())
    ds += 5.0 if diff_hits >= 2 else 2.5 if diff_hits == 1 else 0.0
    b["description"] = ds

    c = 5.0 if len(cand.categories) == 3 else 2.0 if cand.categories else 0.0
    if brief.is_for_kids:
        c += 5.0 if cand.reading_age is not None else 0.0
    else:
        c += 5.0
    b["categories"] = c

    everything = " ".join([cand.title, sub, plain, " ".join(kws)]).lower()
    must_ok = all(term.lower() in everything for term in brief.must_include_terms) if brief.must_include_terms else True
    avoid_hit = any(term.lower() in everything for term in brief.avoid_terms if term)
    b["brief_fit"] = (5.0 if must_ok else 0.0) - (10.0 if avoid_hit else 0.0)

    total = max(0.0, min(100.0, sum(b.values())))
    return round(total, 1), b
