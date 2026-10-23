"""Draft a manuscript with Claude: brief -> story bible -> outline -> chapters (-> optional polish).

Everything produced here is AI-generated text for KDP purposes: set
`provenance.text: ai_generated` in book.yaml. The brief is the only human input.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ..llm import DEFAULT_MODEL, parse_structured
from ..schema import AgeRange
from .manuscript import count_words, slugify

log = logging.getLogger(__name__)


class StoryBrief(BaseModel):
    premise: str = Field(min_length=10)
    title_hint: str | None = None
    genre: str = "cozy fiction"
    audience: str = "adults"
    reading_age: AgeRange | None = None
    chapters: int = Field(6, ge=1, le=60)
    words_per_chapter: int = Field(1500, ge=200, le=6000)
    pov: str = "third person limited"
    tense: str = "past"
    tone: str = "warm, gently humorous, hopeful"
    setting: str | None = None
    themes: list[str] = Field(default_factory=list)
    content_rules: list[str] = Field(default_factory=lambda: ["no explicit content", "no graphic violence", "no real brands or celebrities"])
    names_to_avoid: list[str] = Field(default_factory=list)
    language: str = "English"
    series: str | None = None
    extra_notes: str | None = None


class Character(BaseModel):
    name: str
    role: str
    description: str
    voice: str


class StoryBible(BaseModel):
    title: str
    logline: str
    characters: list[Character]
    settings: list[str]
    themes: list[str]
    style_guide: str


class ChapterPlan(BaseModel):
    number: int
    title: str
    summary: str
    beats: list[str]
    target_words: int


class Outline(BaseModel):
    chapters: list[ChapterPlan]


class ChapterDraft(BaseModel):
    title: str
    markdown: str


@dataclass
class DraftResult:
    out_dir: Path
    bible_path: Path
    outline_path: Path
    chapter_files: list[Path] = field(default_factory=list)
    words: int = 0


def load_story_brief(path: str | Path) -> StoryBrief:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return StoryBrief.model_validate(data)


def _brief_text(b: StoryBrief) -> str:
    lines = [
        f"Premise: {b.premise}",
        f"Working title: {b.title_hint or 'propose one'}",
        f"Genre: {b.genre}; audience: {b.audience}" + (f"; reading age {b.reading_age.min}-{b.reading_age.max}" if b.reading_age else ""),
        f"Length: {b.chapters} chapters x about {b.words_per_chapter} words",
        f"POV: {b.pov}; tense: {b.tense}; tone: {b.tone}",
        f"Setting: {b.setting or 'propose one'}",
        f"Themes: {', '.join(b.themes) or 'propose'}",
        f"Content rules: {'; '.join(b.content_rules)}",
        f"Names to avoid: {', '.join(b.names_to_avoid) or 'none'}",
        f"Language: {b.language}",
    ]
    if b.series:
        lines.append(f"Series: {b.series}")
    if b.extra_notes:
        lines.append(f"Notes: {b.extra_notes}")
    return "\n".join(lines)


SYSTEM = (
    "You are a professional fiction author and developmental editor working for an independent publisher on Amazon KDP. "
    "Write original prose only: no real brands, celebrities or copyrighted characters, nothing lifted from existing works. "
    "Respect the content rules exactly. Keep continuity with the bible and the outline."
)


def _require(obj, step: str):
    if obj is None:
        raise RuntimeError(f"Claude was unavailable during the '{step}' step (check ANTHROPIC_API_KEY / `ant auth login`).")
    return obj


def draft_story(brief: StoryBrief, out_dir: Path, model: str = DEFAULT_MODEL, polish: bool = False, progress=None) -> DraftResult:
    say = progress or (lambda msg: log.info("%s", msg))
    out_dir.mkdir(parents=True, exist_ok=True)
    chapters_dir = out_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)

    say("story bible…")
    bible = _require(parse_structured(SYSTEM, f"{_brief_text(brief)}\n\nCreate the story bible: a title, a one-sentence logline, 3-6 characters (name, role, description, distinct voice), settings, themes and a concise style guide (sentence rhythm, vocabulary level, humor, what to avoid).", StoryBible, model=model, max_tokens=6000), "bible")
    bible_path = out_dir / "bible.json"
    bible_path.write_text(bible.model_dump_json(indent=2), encoding="utf-8")

    say("outline…")
    outline = _require(parse_structured(SYSTEM, f"{_brief_text(brief)}\n\nStory bible:\n{bible.model_dump_json(indent=1)}\n\nWrite a chapter outline with exactly {brief.chapters} chapters. Each chapter: number, title, 2-3 sentence summary, 4-8 beats, target_words about {brief.words_per_chapter}. Build a clear arc with escalating stakes and a satisfying ending.", Outline, model=model, max_tokens=8000), "outline")
    outline_path = out_dir / "outline.json"
    outline_path.write_text(outline.model_dump_json(indent=2), encoding="utf-8")

    files: list[Path] = []
    words = 0
    previous_tail = ""
    for plan in outline.chapters[: brief.chapters]:
        say(f"chapter {plan.number}: {plan.title}…")
        user = (
            f"{_brief_text(brief)}\n\nStory bible:\n{bible.model_dump_json(indent=1)}\n\n"
            f"Full outline (for continuity):\n{json.dumps([c.model_dump() for c in outline.chapters], indent=1)}\n\n"
            f"Previous chapter ending (last words):\n{previous_tail or '(this is the first chapter)'}\n\n"
            f"Write chapter {plan.number} in full as Markdown prose (no heading line; paragraphs separated by blank lines; use *** for scene breaks). "
            f"Target about {plan.target_words} words. Follow the beats: {'; '.join(plan.beats)}."
        )
        draft = _require(parse_structured(SYSTEM, user, ChapterDraft, model=model, max_tokens=16000), f"chapter {plan.number}")
        text = draft.markdown.strip()
        if polish:
            say(f"  polishing chapter {plan.number}…")
            polished = parse_structured(
                SYSTEM,
                f"Style guide:\n{bible.style_guide}\n\nEdit this chapter for rhythm, clarity, continuity and show-don't-tell. Keep the plot, length and Markdown formatting. Return the full edited chapter.\n\n{text}",
                ChapterDraft, model=model, max_tokens=16000,
            )
            if polished and polished.markdown.strip():
                text = polished.markdown.strip()
        title = re.sub(r"\s+", " ", draft.title or plan.title).strip()
        path = chapters_dir / f"{plan.number:02d}-{slugify(title)}.md"
        path.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
        files.append(path)
        words += count_words(text)
        previous_tail = " ".join(text.split()[-120:])

    (out_dir / "PROVENANCE.md").write_text(
        f"# Provenance\n\nDrafted with Claude ({model}) from story_brief.yaml on this machine. For KDP this manuscript is **AI-generated text** and must be declared "
        f"(set `provenance.text: ai_generated` in book.yaml). Human edits do not change that classification.\n",
        encoding="utf-8",
    )
    return DraftResult(out_dir, bible_path, outline_path, files, words)
