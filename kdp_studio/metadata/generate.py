"""Generate metadata candidates with Claude (structured output) or offline templates,
validate each against the KDP metadata rules, repair once if needed, and score."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ..findings import FindingList
from ..llm import claude_available, parse_structured
from ..metadata_rules import validate_metadata
from ..schema import AgeRange, Metadata, Series
from ..util import clip_words, niche_subject, smart_title
from .brief import Brief
from .categories import suggest_categories

log = logging.getLogger(__name__)


class MetadataCandidate(BaseModel):
    title: str
    subtitle: str | None = None
    description_html: str
    keywords: list[str] = Field(default_factory=list, max_length=7)
    categories: list[str] = Field(default_factory=list, max_length=3)
    reading_age: AgeRange | None = None
    series_name: str | None = None
    a_plus_headline: str | None = None
    a_plus_body: str | None = None
    rationale: str = ""


class CandidateList(BaseModel):
    candidates: list[MetadataCandidate] = Field(default_factory=list)


KDP_RULES = (
    "KDP metadata rules (hard constraints):\n"
    "- title + subtitle together under 200 characters; the title must be exactly what will appear on the cover\n"
    "- never use: bestselling, best seller, #1, free, sale, discount, new release, Amazon, Kindle, KDP, other authors' or books' names\n"
    "- do not repeat generic words (book, books, notebook, journal, gift, gifts) in the title/subtitle\n"
    "- description: HTML limited to <h4> <h5> <h6> <p> <br> <b> <strong> <i> <em> <u> <ul> <ol> <li>; 600-2500 characters; "
    "no URLs, emails, phone numbers, prices, reviews, star ratings, testimonials or time-sensitive events; no keyword lists\n"
    "- exactly 7 keywords, each a 2-4 word shopper phrase under 50 characters, no duplicates, none that only repeat title words\n"
    "- exactly 3 categories from the suggested list (or an equally specific real KDP path)\n"
    "- reading_age (min/max) only for children's or teen audiences; omit for adults\n"
    "- no claims about health outcomes; no brand or copyrighted-character references"
)


def brief_text(brief: Brief) -> str:
    lines = [
        f"Book type: {brief.book_type}",
        f"Niche keyword: {brief.niche_keyword}",
        f"Concept title idea: {brief.concept_title or 'propose one'}",
        f"Angle: {brief.angle or 'n/a'}",
        f"Audience: {brief.audience}",
        f"Differentiators: {'; '.join(brief.differentiators) or 'n/a'}",
        f"Competitor insights (complaints/gaps): {'; '.join(brief.competitor_insights) or 'n/a'}",
        f"Must include terms: {', '.join(brief.must_include_terms) or 'none'}",
        f"Avoid terms: {', '.join(brief.avoid_terms) or 'none'}",
        f"Series: {brief.series_name or 'none'}",
        f"Formats: {', '.join(brief.formats)}",
        f"Language: {brief.language}; tone: {brief.tone}",
        f"Pages: {brief.page_count or 'n/a'}; images: {brief.image_count or 'n/a'}",
        f"Suggested categories: {' | '.join(suggest_categories(brief.book_type, brief.audience))}",
    ]
    if brief.reading_age:
        lines.append(f"Reading age: {brief.reading_age.min}-{brief.reading_age.max}")
    if brief.extra_notes:
        lines.append(f"Notes: {brief.extra_notes}")
    return "\n".join(lines)


def to_metadata(cand: MetadataCandidate, brief: Brief) -> Metadata:
    return Metadata(
        title=cand.title,
        subtitle=cand.subtitle,
        author=brief.author or "Pen Name",
        description_html=cand.description_html,
        keywords=cand.keywords[:7],
        categories=cand.categories[:3],
        reading_age=cand.reading_age,
        series=Series(name=cand.series_name) if cand.series_name else None,
        language=brief.language,
    )


def validate_candidate(cand: MetadataCandidate, brief: Brief) -> FindingList:
    return validate_metadata(to_metadata(cand, brief), brief.book_type)


# --------------------------------------------------------------------------- offline templates
def template_candidates(brief: Brief, n: int = 5) -> list[MetadataCandidate]:
    """Offline fallback that still passes the KDP validator. Claude candidates are richer."""
    kw = " ".join(brief.niche_keyword.split())
    subject = niche_subject(kw)
    subj_t = smart_title(subject)
    audience = brief.audience.split(",")[0].strip()
    aud_t = smart_title(audience)
    aud_short = audience.split(" and ")[0].strip()
    count = brief.image_count or 30
    diffs = brief.differentiators or ["thick, easy-to-follow outlines", "one design per page with a blank back", "large pages with wide margins"]
    cats = suggest_categories(brief.book_type, brief.audience)[:3]
    coloring = brief.book_type == "coloring"

    if coloring:
        patterns = [
            (brief.concept_title or subj_t, f"{subj_t} Coloring Book for {aud_t} with {count} Simple Designs for Relaxation"),
            (f"Bold & Easy {subj_t}", f"Large Print Coloring Book for {aud_t} with {count} Simple Designs"),
            (f"{subj_t} to Color", f"A Relaxing Coloring Book for {aud_t} Featuring {count} Easy Designs"),
            (f"Simply {subj_t}", f"{count} Big and Easy Coloring Pages for {aud_t}, Beginners and Stress Relief"),
            (f"The {subj_t} Coloring Book", f"{count} Calm, Easy Designs for {aud_t} Who Want to Relax"),
        ]
        keywords = [
            f"{subject} coloring book",
            f"easy coloring book {aud_short}",
            "large print coloring book",
            f"bold {subject} coloring pages",
            f"relaxing coloring book {aud_short}",
            "simple designs beginners",
            "stress relief coloring",
        ]
        headline = f"{count} {subject} designs made for relaxed, confident coloring"
        intro = (
            f"Open to any page and start. Every illustration in this {subject} coloring book is drawn with clear outlines "
            f"and generous shapes, so {audience} can enjoy a calm hour without squinting or worrying about tiny details."
        )
        closing = "Perfect for quiet evenings, waiting rooms and gifting to someone who deserves a slow afternoon. Pick up your favorite pencils or markers and let the pages bloom."
        a_plus = (f"{count} bold designs, zero frustration", f"Thick lines and big shapes make this {subject} coloring book a relaxing choice for {audience}.")
    else:
        patterns = [
            (brief.concept_title or subj_t, f"{count} Short {subj_t} Stories for {aud_t}"),
            (f"Tales of {subj_t}", f"A Collection of {count} Heartwarming Stories for {aud_t}"),
            (f"{subj_t} at Dusk", f"{count} Cozy Stories to Read in One Sitting"),
            (f"Little {subj_t} Stories", f"Quick Reads for {aud_t} Who Love {subj_t}"),
            (f"The {subj_t} Collection", f"{count} Gentle Stories for {aud_t}"),
        ]
        keywords = [
            f"{subject} short stories",
            f"{subject} stories for {aud_short}",
            "short reads under one hour",
            f"cozy {subject} fiction",
            "feel good short stories",
            f"{subject} story collection",
            "quick reads for busy people",
        ]
        headline = f"{count} {subject} stories you can finish in one sitting"
        intro = f"Each story stands alone, so {audience} can pick up this collection for ten quiet minutes or a whole evening."
        closing = "Settle in with a warm drink and let the first story carry you away."
        a_plus = (f"{count} stories, one cozy world", f"Short, warm {subject} stories written for {audience}.")

    bullets = "".join(f"<li>{d[0].upper() + d[1:]}</li>" for d in diffs[:4])
    desc = f"<h4>{headline}</h4><p>{intro}</p><ul>{bullets}</ul><p>{closing}</p>"

    seen: list[str] = []
    for k in keywords:
        k = clip_words(" ".join(k.split()), 50)
        if k and k.lower() not in {s.lower() for s in seen}:
            seen.append(k)

    out: list[MetadataCandidate] = []
    for i, (title, subtitle) in enumerate(patterns[:n]):
        out.append(
            MetadataCandidate(
                title=title,
                subtitle=subtitle,
                description_html=desc,
                keywords=seen[:7],
                categories=cats,
                reading_age=brief.reading_age,
                series_name=brief.series_name,
                a_plus_headline=a_plus[0],
                a_plus_body=a_plus[1],
                rationale=f"Template variant {i + 1}: niche subject in title/subtitle, audience and count stated, differentiators as bullets.",
            )
        )
    return out


# --------------------------------------------------------------------------- Claude
SYSTEM = (
    "You write Amazon KDP listing metadata that ranks and converts while staying strictly inside KDP's rules. "
    "Each candidate must take a genuinely different positioning (title structure, promise, audience phrasing), not a "
    "paraphrase of the others. Subtitles carry the main search phrases naturally; descriptions open with a benefit headline, "
    "then one short paragraph, then 3-5 concrete bullets, then a closing line.\n\n" + KDP_RULES
)


def claude_candidates(brief: Brief, n: int, model: str) -> list[MetadataCandidate]:
    user = f"{brief_text(brief)}\n\nReturn exactly {n} candidates, strongest first, each with a one-sentence rationale."
    result = parse_structured(SYSTEM, user, CandidateList, model=model, max_tokens=12000)
    return result.candidates[:n] if result else []


def repair_with_claude(cand: MetadataCandidate, findings: FindingList, brief: Brief, model: str) -> MetadataCandidate | None:
    problems = "\n".join(f"- [{f.level}] {f.code}: {f.message}" for f in findings if f.level in ("error", "warning"))
    user = (
        f"{brief_text(brief)}\n\nFix this candidate so every listed problem disappears while keeping its positioning. "
        f"Return exactly 1 candidate.\n\nCandidate:\n{cand.model_dump_json(indent=1)}\n\nProblems:\n{problems}"
    )
    result = parse_structured(SYSTEM, user, CandidateList, model=model, max_tokens=6000)
    return result.candidates[0] if result and result.candidates else None


def generate_candidates(brief: Brief, n: int = 5, use_claude: bool = True, repair: bool = True, model: str = "claude-opus-5-5"):
    from .score import ScoredCandidate, score_candidate

    cands: list[MetadataCandidate] = []
    used_claude = False
    if use_claude and claude_available():
        cands = claude_candidates(brief, n, model)
        used_claude = bool(cands)
    if not cands:
        cands = template_candidates(brief, n)

    scored: list[ScoredCandidate] = []
    for cand in cands:
        findings = validate_candidate(cand, brief)
        if used_claude and repair and (findings.errors or findings.warnings):
            fixed = repair_with_claude(cand, findings, brief, model)
            if fixed is not None:
                f2 = validate_candidate(fixed, brief)
                if len(f2.errors) <= len(findings.errors) and len(f2.warnings) <= len(findings.warnings):
                    cand, findings = fixed, f2
        s, breakdown = score_candidate(cand, brief, findings)
        scored.append(ScoredCandidate(cand, findings, s, breakdown))
    scored.sort(key=lambda sc: -sc.score)
    return scored
