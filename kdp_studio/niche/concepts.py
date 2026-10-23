"""Concept cards: turn a niche summary into 10 distinct book ideas with a required differentiation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import claude_available, parse_structured
from ..util import clip_words, niche_subject, smart_title
from .models import ConceptCard, NicheSummary

ANGLES = {
    "coloring": [
        ("Bold & Easy", "thick outlines, large shapes", "seniors, low vision, beginners"),
        ("Large Print", "big single subjects, wide margins", "adults 60+"),
        ("Mindful Affirmations", "each page pairs art with a short positive phrase", "women 30-55, anxiety relief"),
        ("For Kids 4-8", "simple shapes, friendly faces", "parents of preschool and early-grade kids"),
        ("Bilingual Labels", "each subject labeled in two languages", "bilingual families, language learners"),
        ("Seasonal Edition", "holiday or season themed set", "gift buyers Q4"),
        ("Pocket / Travel Size", "6x9 compact pages", "commuters, travelers"),
        ("Pattern & Mandala", "subject woven into repeating patterns", "adult colorists who like detail"),
        ("Story Coloring", "a light storyline runs across the pages", "kids 6-10, read-aloud"),
        ("Color by Number", "numbered regions with a legend", "beginners, dementia-friendly activity"),
    ],
    "story": [
        ("Short Read Series", "65-100 page installments, read-through hooks", "Kindle Unlimited binge readers"),
        ("Cozy Setting", "small-town, low-stakes mystery or romance", "women 35-65"),
        ("Clean & Wholesome", "no explicit content, warm tone", "faith and family readers"),
        ("Bedtime Collection", "5-minute stories with a calm ending", "parents of kids 3-7"),
        ("Themed Anthology", "ten stories around one motif", "gift buyers, short-attention readers"),
        ("Illustrated Chapter Book", "early chapter book with line illustrations", "kids 6-9"),
        ("Box Set", "3-in-1 bundle of existing stories", "value seekers"),
        ("Holiday Novella", "seasonal standalone", "Q4 shoppers"),
        ("Dual Timeline", "past/present interleaved", "book-club readers"),
        ("Workplace Comedy", "light humor in a specific profession", "professionals in that field"),
    ],
}


class ConceptList(BaseModel):
    concepts: list[ConceptCard] = Field(default_factory=list)


def _summary_brief(s: NicheSummary) -> str:
    phrases = ", ".join(f"{p} ({c})" for p, c in s.top_phrases[:10]) or "n/a"
    titles = "\n".join(f"- {t}" for t in s.top_titles[:10]) or "- n/a"
    return (
        f"Keyword: {s.keyword}\n"
        f"Books analyzed: {s.n_books}; median BSR (top 10): {s.median_bsr}; median price: {s.median_price}; "
        f"median ratings: {s.median_rating_count}; share indie: {s.share_indie}; share published <1y: {s.share_fresh_365}\n"
        f"Opportunity {s.scores.opportunity}/100 ({s.scores.label}), confidence {s.scores.confidence}\n"
        f"Flags: {'; '.join(s.flags) or 'none'}\n"
        f"Common title phrases: {phrases}\n"
        f"Top titles:\n{titles}"
    )


def template_concepts(summary: NicheSummary, book_type: str, n: int = 10) -> list[ConceptCard]:
    """Offline fallback: proven angles x the niche subject, skipping angles the keyword already states."""
    out: list[ConceptCard] = []
    keyword = summary.keyword
    kw_l = keyword.lower()
    subject = niche_subject(keyword)
    subj_t = smart_title(subject)
    kind = "coloring book" if book_type == "coloring" else "book"
    for name, mechanic, audience in ANGLES.get(book_type, ANGLES["coloring"]):
        name_l = name.lower().replace("&", "and")
        angle_words = [w for w in name_l.split() if w not in ("and", "/")]
        if all(w in kw_l for w in angle_words):
            continue  # the keyword already is this angle; a card would just repeat it
        aud_short = " ".join(audience.split(",")[0].split()[:3])
        if name_l.startswith("for "):  # "Flowers for Kids 4-8", not "For Kids 4-8 Flowers"
            title = f"{subj_t} {name}"
            phrase = f"{subject} {kind} {name_l}"
        else:
            title = f"{name} {subj_t}"
            phrase = f"{name_l} {subject} {kind}"
        out.append(
            ConceptCard(
                title_idea=title,
                angle=mechanic,
                audience=audience,
                differentiation=f"Adds the {name_l} format ({mechanic}) to '{subject}', a combination the top titles for '{keyword}' do not offer.",
                why_it_can_rank=f"The long-tail phrase '{phrase}' sits inside the proven demand for '{keyword}'.",
                risks="Verify with a live search that no established title already owns this exact combination; keep every illustration original.",
                keywords=[clip_words(phrase, 50), clip_words(f"{subject} {kind} for {aud_short}", 50), clip_words(keyword, 50)],
            )
        )
        if len(out) >= n:
            break
    return out


def claude_concepts(summary: NicheSummary, book_type: str, n: int = 10, model: str = "claude-opus-5-5") -> list[ConceptCard]:
    system = (
        "You are a KDP publishing strategist. From a niche summary, propose distinct book concepts that could "
        "rank for the keyword while being clearly different from the existing top titles — KDP removes books that "
        "are 'not significantly different from content in another book'. Each concept needs a real differentiation "
        "(audience, format, mechanic, bundle, language), not a cosmetic rename. No brand names, no copyrighted "
        "characters, no promotional words. Keywords are 2-4 word shopper phrases."
    )
    user = f"Book type: {book_type}\n\n{_summary_brief(summary)}\n\nReturn exactly {n} concepts, strongest first."
    result = parse_structured(system, user, ConceptList, model=model, max_tokens=8000)
    return result.concepts[:n] if result else []


def concept_cards(summary: NicheSummary, book_type: str, n: int = 10, use_claude: bool = True) -> list[ConceptCard]:
    if use_claude and claude_available():
        cards = claude_concepts(summary, book_type, n)
        if cards:
            return cards
    return template_concepts(summary, book_type, n)
