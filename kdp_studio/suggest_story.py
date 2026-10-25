"""Story (text book) mode of the create-form "Gợi ý": premise, chapter outline, keywords and metadata that fit each
other, for a paperback + Kindle eBook. Same engines and anchoring rules as the coloring mode (suggest.py): typed
values are kept, everything else is generated around them, and one validator shapes whatever the engine returns."""

from __future__ import annotations

import re

from pydantic import BaseModel

from .bookgen import default_story_keywords, skeleton_outline
from .suggest import PEN_NAMES, clean_keywords, run_engines, slugify, title_case

TEXT_FIELDS = ("folder", "title", "subtitle", "author", "genre", "audience", "premise", "setting", "tone")
DEFAULT_AUDIENCE = "adults who enjoy gentle, feel-good fiction"
SYSTEM = (
    "You help a self-publisher plan an original work of fiction sold on Amazon KDP as a paperback and a Kindle eBook (amazon.com, English). "
    "Fields: folder (lowercase slug, a-z 0-9 and hyphens, at most 40 characters); title (at most 80 characters, evocative, no superlatives); "
    "subtitle (at most 120 characters: the genre promise and the hook, e.g. 'A Cozy Small-Town Mystery'); author (a plausible two-word pen name unless one was typed); "
    "genre (a short lowercase phrase such as 'cozy mystery'); audience (a short phrase); premise (2-4 sentences: protagonist, what they want, "
    "what stands in the way, the setting and the stakes); setting (one line: place and time); tone (3-5 adjectives); "
    "keywords (exactly 7 search phrases, lowercase, each at most 50 characters, no quotes, no brand, author or competitor names, no words like best/free/cheap, "
    "not merely repeating the title); outline (exactly N lines, one per chapter, each 'Chapter title: one or two sentences of what happens', titles distinct and "
    "without numbers, forming a complete arc - setup, rising complications, a midpoint turn, a crisis, a climax and a resolution). "
    "No real people, brands or copyrighted characters; nothing explicit or graphic. Everything must match the values the author typed."
)
JSON_SHAPE = ('{"folder": "...", "title": "...", "subtitle": "...", "author": "...", "genre": "...", "audience": "...", "premise": "...", "setting": "...", '
              '"tone": "...", "keywords": ["...", "...", "...", "...", "...", "...", "..."], "outline": ["Chapter title: what happens", "..."]}')


class StoryLLMOut(BaseModel):
    folder: str
    title: str
    subtitle: str
    author: str
    genre: str
    audience: str
    premise: str
    setting: str
    tone: str
    keywords: list[str]
    outline: list[str]


# one seed per genre family for the offline engine: (title, subtitle, setting, hero, want, twist, tone)
SEEDS = {
    "cozy": ("The Last Post Office on Maple Street", "A Cozy Small-Town Story", "a small river town in autumn", "a retired schoolteacher", "keep the town's last post office open through the winter", "a letter arrives with no name on it", "warm, quietly funny, hopeful"),
    "mystery": ("A Parrot Never Lies", "A Cozy Mystery", "a seaside village with one tea shop", "a bakery owner with a sharp memory", "clear a friend's name after a theft at the harbour fair", "the only witness is a parrot", "light, witty, puzzle-driven"),
    "romance": ("Coffee at the Corner Bookshop", "A Sweet Small-Town Romance", "a mountain town that runs on one bookshop", "a bookshop owner who has sworn off love", "save the shop before the winter season", "the rival developer keeps showing up with coffee", "sweet, funny, slow-burn"),
    "fantasy": ("The Map That Remembered", "A Fantasy Adventure", "a kingdom where the maps redraw themselves each night", "an apprentice mapmaker", "find the one road that leads home", "the maps begin writing her name", "wondrous, brisk, hopeful"),
    "science fiction": ("Signals from the Drift", "A Science Fiction Story", "a cargo station at the edge of the solar system", "a repair technician", "bring a drifting ship back before its air runs out", "the ship is sending messages dated next week", "tense, curious, humane"),
    "thriller": ("Snow Line", "A Thriller", "a snowed-in lakeside hotel", "a night manager", "find who is leaving the threatening notes", "every guest has a reason to lie", "tense, fast, twisty"),
    "historical": ("The Clockmaker's Daughter", "A Historical Novel", "a market town on the English coast in 1922", "a clockmaker's daughter", "keep the family workshop after the war", "a stranger brings a watch that stopped on the day her brother vanished", "wistful, vivid, hopeful"),
    "children": ("The Cloud Who Was Afraid of Heights", "A Chapter Book for Young Readers", "a town where the clouds are shaped like animals", "a curious nine-year-old", "return a lost cloud to the sky", "the cloud turns out to be afraid of heights", "playful, kind, funny"),
}
FAMILY = (("cozy mystery", "mystery"), ("mystery", "mystery"), ("thriller", "thriller"), ("suspense", "thriller"), ("horror", "thriller"), ("romance", "romance"),
          ("fantasy", "fantasy"), ("science fiction", "science fiction"), ("sci-fi", "science fiction"), ("historical", "historical"), ("children", "children"),
          ("middle grade", "children"), ("chapter book", "children"), ("young adult", "children"), ("kids", "children"))
GENRE_NAME = {"cozy": "cozy fiction", "children": "children's chapter book", "historical": "historical fiction"}


def family(text: str) -> str:
    t = text.lower()
    for key, fam in FAMILY:
        if key in t:
            return fam
    return "cozy"


def parse_story_form(form: dict) -> tuple[dict, int]:
    def text(k: str) -> str:
        v = form.get(k)
        return str(v).strip() if v is not None else ""

    try:
        chapters = int(float(text("chapters") or 8))
    except ValueError:
        chapters = 8
    chapters = max(1, min(60, chapters))
    given: dict = {k: text(k) for k in TEXT_FIELDS}
    given["keywords"] = [k.strip() for k in text("keywords").split(",") if k.strip()]
    given["outline"] = [ln.strip() for ln in text("outline").splitlines() if ln.strip()]
    return given, chapters


def clean_outline(candidates: list, n: int) -> list[str]:
    """Exactly n 'Title: summary' lines with distinct titles: typed and model lines first, then the generic three-act skeleton."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(candidates or []) + skeleton_outline(n):
        if len(out) >= n:
            break
        s = re.sub(r"\s+", " ", str(raw).strip().strip('"').strip())
        s = re.sub(r"^(?:chapter\s+)?\d+\s*[.:)-]\s*", "", s, flags=re.I)  # "1. Title: ..." / "Chapter 3 - Title" -> "Title: ..."
        if not s:
            continue
        title, sep, summary = s.partition(":")
        if not sep and len(s.split()) > 8:  # a bare summary: make a short title out of its first words
            title, summary = " ".join(s.split()[:5]).rstrip(" ,.;-"), s
        title = title.strip().rstrip(".")
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append(f"{title}: {summary.strip()}" if summary.strip() else title)
    return out[:n]


def offline_story(given: dict, chapters: int, overwrite: bool = False) -> dict:
    """Title, premise, pen name, genre and the rest from whatever was typed, without any API."""
    g = {k: "" for k in TEXT_FIELDS} if overwrite else given
    hint = " ".join([given["genre"], given["title"], given["subtitle"], given["premise"], " ".join(given["keywords"]), given["folder"].replace("-", " ")])
    fam = family(hint)
    s_title, s_sub, s_setting, hero, want, twist, s_tone = SEEDS[fam]
    title = g["title"] or (title_case(given["folder"].replace("-", " ")) if given["folder"] else s_title)
    setting = g["setting"] or s_setting
    premise = g["premise"] or (f"In {setting}, {hero} must {want}. When {twist}, every neighbour turns out to have a part to play, "
                               "and the only way through is together.")
    return {"folder": g["folder"] or slugify(title) or "my-story", "title": title, "subtitle": g["subtitle"] or s_sub,
            "author": g["author"] or PEN_NAMES[sum(map(ord, title)) % len(PEN_NAMES)], "genre": g["genre"] or GENRE_NAME.get(fam, fam),
            "audience": g["audience"] or DEFAULT_AUDIENCE, "premise": premise, "setting": setting, "tone": g["tone"] or s_tone}


def _user_prompt(given: dict, chapters: int, overwrite: bool) -> str:
    typed = {k: v for k, v in given.items() if v}
    lines = [f"Number of chapters, i.e. outline lines needed: {chapters}."]
    if typed:
        lines.append("The author typed these values; treat them as hints: fix typos and improve the wording where it clearly helps."
                     if overwrite else
                     "The author already typed these values. Keep them exactly as given and build every other field to match them; "
                     "for keywords and outline keep the typed entries first and add new ones to reach the required count.")
        for k, v in typed.items():
            lines.append(f"- {k}: " + (" | ".join(v) if isinstance(v, list) else v))
    else:
        lines.append("Nothing has been typed yet: propose one marketable, original premise in a popular genre and fill everything for it.")
    lines.append(f"Return every field: exactly 7 keywords and exactly {chapters} outline lines, all in English.")
    return "\n".join(lines)


def suggest_story(form: dict, *, overwrite: bool = False, engine: str | None = None) -> dict:
    """All story-form fields completed to match each other: {fields, source, source_label, notes, chapters, kind}."""
    given, chapters = parse_story_form(form)
    offline = offline_story(given, chapters, overwrite)
    llm, source, label, notes = run_engines(SYSTEM, _user_prompt(given, chapters, overwrite), StoryLLMOut, JSON_SHAPE, min(16000, 3000 + 60 * chapters), engine)
    llm = llm or {}
    out: dict = {}
    for k in TEXT_FIELDS:
        out[k] = given[k] if (given[k] and not overwrite) else (str(llm.get(k) or "").strip()[:1200] or offline[k])
    out["folder"] = slugify(out["folder"]) or offline["folder"]
    typed_kw = [] if overwrite else given["keywords"]
    out["keywords"] = clean_keywords(typed_kw + list(llm.get("keywords") or []), default_story_keywords(out["genre"]), out["title"])
    typed_ol = [] if overwrite else given["outline"]
    out["outline"] = clean_outline(typed_ol + [s for s in (llm.get("outline") or []) if str(s).strip()], chapters)
    fields = {**{k: out[k] for k in TEXT_FIELDS}, "keywords": ", ".join(out["keywords"]), "outline": "\n".join(out["outline"])}
    return {"fields": fields, "source": source, "source_label": label, "notes": notes, "chapters": chapters, "overwrite": overwrite, "kind": "story"}
