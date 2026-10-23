"""The brief that drives metadata generation (usually distilled from a niche report + concept card)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from ..schema import AgeRange


class Brief(BaseModel):
    book_type: Literal["coloring", "story"] = "coloring"
    niche_keyword: str = Field(min_length=1)
    concept_title: str | None = None
    angle: str | None = None
    audience: str = "adults"
    differentiators: list[str] = Field(default_factory=list)
    competitor_insights: list[str] = Field(default_factory=list)
    must_include_terms: list[str] = Field(default_factory=list)
    avoid_terms: list[str] = Field(default_factory=list)
    series_name: str | None = None
    formats: list[Literal["paperback", "hardcover", "ebook"]] = Field(default_factory=lambda: ["paperback"])
    reading_age: AgeRange | None = None
    language: str = "English"
    author: str | None = None
    page_count: int | None = None
    image_count: int | None = None
    tone: str = "warm, concrete, benefit-led, no hype"
    extra_notes: str | None = None

    @property
    def is_for_kids(self) -> bool:
        a = self.audience.lower()
        return self.reading_age is not None or any(w in a for w in ("kid", "child", "toddler", "preschool", "teen", "boys", "girls"))


def load_brief(path: str | Path) -> Brief:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a YAML mapping")
    return Brief.model_validate(data)
