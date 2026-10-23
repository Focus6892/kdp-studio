"""KDP Metadata Guidelines as validators.

Source: https://kdp.amazon.com/en_US/help/topic/G201097560 (fetched 2026-10-23)
- Title + subtitle together must be fewer than 200 characters.
- No sales-rank claims ("bestselling"), no promotions ("free"), no repeated
  generic keywords ("notebook", "journal", "gifts", "books"), no HTML tags,
  no unauthorized references to other titles/authors.
- Description: HTML allowed; no URLs/emails/phone numbers, no reviews or
  testimonials, no price/availability, no time-sensitive info, no keyword lists.
- Keywords: 7 fields, 2-3 word phrases recommended, no misleading terms.
- Categories: up to 3, relevant to the book.
"""

from __future__ import annotations

import re

from .findings import FindingList
from .schema import Book, Metadata

TITLE_MAX_CHARS = 200
DESCRIPTION_MAX_CHARS = 4000
KEYWORD_MAX_CHARS = 50
KEYWORD_SLOTS = 7
CATEGORY_SLOTS = 3

BANNED_CLAIMS = re.compile(
    r"\b(best[\s-]?sell(?:er|ers|ing)|#\s?1|number\s+one|free|sale|discount|giveaway|new\s+release)\b",
    re.IGNORECASE,
)
PLATFORM_WORDS = re.compile(r"\b(amazon|kindle|kdp)\b", re.IGNORECASE)
GENERIC_WORDS = {"notebook", "notebooks", "journal", "journals", "gift", "gifts", "book", "books"}
HTML_TAG = re.compile(r"<[^>]+>")
ALLOWED_DESCRIPTION_TAGS = {"br", "p", "b", "strong", "em", "i", "u", "h4", "h5", "h6", "ol", "ul", "li"}
URL_RE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|co|us|shop)\b)", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{7,}\d)(?!\d)")
REVIEW_WORDS = re.compile(r"\b(review|reviews|testimonial|testimonials|5[\s-]?stars?|five[\s-]?stars?)\b|★|⭐", re.IGNORECASE)
PRICE_RE = re.compile(r"[$€£]\s?\d|\b\d+(\.\d{2})?\s?(usd|dollars)\b", re.IGNORECASE)
CHILDREN_RE = re.compile(r"\b(children|children's|kids|juvenile|teen|young adult|toddler|baby)\b", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def validate_metadata(md: Metadata, book_type: str | None = None) -> FindingList:
    f = FindingList()
    full = md.full_title

    # --- title / subtitle -------------------------------------------------
    if len(full) >= TITLE_MAX_CHARS:
        f.error("title.length", f"Title + subtitle is {len(full)} chars; KDP requires fewer than {TITLE_MAX_CHARS}.", "metadata.title")
    for field_name, value in (("title", md.title), ("subtitle", md.subtitle or ""), ("author", md.author)):
        if HTML_TAG.search(value):
            f.error(f"{field_name}.html", f"HTML tags are not allowed in the {field_name}.", f"metadata.{field_name}")
    for m in BANNED_CLAIMS.finditer(full):
        f.error("title.banned_word", f"'{m.group(0)}' in title/subtitle: KDP prohibits sales-rank or promotional claims.", "metadata.title")
    for m in PLATFORM_WORDS.finditer(full):
        f.warning("title.platform_word", f"'{m.group(0)}' in title/subtitle may be flagged as an unauthorized reference.", "metadata.title")
    counts: dict[str, int] = {}
    for w in _words(full):
        if w in GENERIC_WORDS:
            counts[w] = counts.get(w, 0) + 1
    for w, n in counts.items():
        if n > 1:
            f.warning("title.generic_repeat", f"Generic keyword '{w}' appears {n} times in title/subtitle; KDP flags repeated generic keywords.", "metadata.title")
    if md.subtitle and len(md.subtitle) > 150:
        f.info("subtitle.long", "Subtitle longer than 150 chars; long keyword-stuffed subtitles are a common rejection trigger.", "metadata.subtitle")

    # --- description --------------------------------------------------------
    d = md.description_html
    if len(d) > DESCRIPTION_MAX_CHARS:
        f.error("description.length", f"Description is {len(d)} chars; KDP allows up to {DESCRIPTION_MAX_CHARS}.", "metadata.description_html")
    for tag in HTML_TAG.findall(d):
        name = re.sub(r"^</?\s*([a-zA-Z0-9]+).*$", r"\1", tag).lower()
        if name not in ALLOWED_DESCRIPTION_TAGS:
            f.error("description.html_tag", f"HTML tag <{name}> is not supported in KDP descriptions.", "metadata.description_html")
    plain = HTML_TAG.sub(" ", d)
    if URL_RE.search(plain):
        f.error("description.url", "Description contains a URL or domain; KDP prohibits website addresses.", "metadata.description_html")
    if EMAIL_RE.search(plain):
        f.error("description.email", "Description contains an email address.", "metadata.description_html")
    if PHONE_RE.search(plain):
        f.warning("description.phone", "Description may contain a phone number (prohibited).", "metadata.description_html")
    if REVIEW_WORDS.search(plain):
        f.warning("description.review", "Description mentions reviews/testimonials/stars; quotes and reviews are prohibited.", "metadata.description_html")
    if PRICE_RE.search(plain):
        f.warning("description.price", "Description mentions a price; pricing/availability info is prohibited.", "metadata.description_html")
    for m in BANNED_CLAIMS.finditer(plain):
        f.warning("description.claim", f"'{m.group(0)}' in description may be read as a sales-rank/promotional claim.", "metadata.description_html")

    # --- keywords -----------------------------------------------------------
    if len(md.keywords) > KEYWORD_SLOTS:
        f.error("keywords.count", f"{len(md.keywords)} keywords; KDP has {KEYWORD_SLOTS} fields.", "metadata.keywords")
    if not md.keywords:
        f.warning("keywords.empty", "No keywords set; you are leaving all 7 search fields empty.", "metadata.keywords")
    seen: set[str] = set()
    title_words = set(_words(full))
    for i, kw in enumerate(md.keywords):
        where = f"metadata.keywords[{i}]"
        if not kw.strip():
            f.error("keywords.blank", "Empty keyword field.", where)
            continue
        if len(kw) > KEYWORD_MAX_CHARS:
            f.error("keywords.length", f"'{kw}' is {len(kw)} chars; max {KEYWORD_MAX_CHARS} per field.", where)
        if HTML_TAG.search(kw):
            f.error("keywords.html", "HTML in keyword.", where)
        if BANNED_CLAIMS.search(kw):
            f.error("keywords.banned_word", f"'{kw}' contains a prohibited claim word.", where)
        if PLATFORM_WORDS.search(kw):
            f.warning("keywords.platform_word", f"'{kw}' references Amazon/Kindle/KDP.", where)
        low = kw.strip().lower()
        if low in seen:
            f.warning("keywords.duplicate", f"Keyword '{kw}' is duplicated.", where)
        seen.add(low)
        wc = len(_words(kw))
        if wc > 5:
            f.info("keywords.long_phrase", f"'{kw}' has {wc} words; KDP recommends 2-3 word phrases.", where)
        kw_words = set(_words(kw)) - {"for", "and", "the", "of", "a", "with", "to", "in"}
        if kw_words and kw_words <= title_words:
            f.info("keywords.in_title", f"'{kw}' only repeats words already in the title; KDP advises not to spend keywords on existing metadata.", where)

    # --- categories ---------------------------------------------------------
    if len(md.categories) > CATEGORY_SLOTS:
        f.error("categories.count", f"{len(md.categories)} categories; KDP allows {CATEGORY_SLOTS}.", "metadata.categories")
    if not md.categories:
        f.warning("categories.empty", "No categories chosen.", "metadata.categories")
    is_childrens = any(CHILDREN_RE.search(c) for c in md.categories)
    if is_childrens and md.reading_age is None:
        f.warning("reading_age.missing", "A Children's/Teen category without a reading age is not eligible for that category and is hidden from age-specific search.", "metadata.reading_age")
    if is_childrens and md.sexually_explicit:
        f.error("audience.conflict", "Sexually explicit = Yes makes the book ineligible for Children's categories.", "metadata.sexually_explicit")

    # --- low-content flag -----------------------------------------------------
    if book_type == "coloring" and md.low_content:
        f.error("low_content.coloring", "KDP: coloring/activity books are NOT low-content. Untick the Low-content box or the book will be rejected.", "metadata.low_content")
    if md.low_content and md.series is not None:
        f.error("low_content.series", "Low-content books cannot be part of a series.", "metadata.series")

    return f


def validate_book_metadata(book: Book) -> FindingList:
    return validate_metadata(book.metadata, book.type)
