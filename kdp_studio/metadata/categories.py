"""Commonly used KDP category paths. KDP's picker changes over time: treat these as
suggestions to confirm in the KDP title setup screen, not as an authoritative list."""

from __future__ import annotations

CATEGORIES: dict[str, list[str]] = {
    "coloring_adults": [
        "Crafts, Hobbies & Home > Crafts & Hobbies > Coloring Books for Grown-Ups",
        "Self-Help > Stress Management",
        "Arts & Photography > Drawing > Coloring Books",
        "Health, Fitness & Dieting > Mental Health > Anxieties & Phobias",
        "Crafts, Hobbies & Home > Crafts & Hobbies > Papercrafts, Stamping & Stenciling",
        "Humor & Entertainment > Puzzles & Games > Activity Books",
    ],
    "coloring_seniors": [
        "Crafts, Hobbies & Home > Crafts & Hobbies > Coloring Books for Grown-Ups",
        "Health, Fitness & Dieting > Aging",
        "Self-Help > Stress Management",
        "Health, Fitness & Dieting > Diseases & Physical Ailments > Alzheimer's Disease",
    ],
    "coloring_kids": [
        "Children's Books > Activities, Crafts & Games > Activity Books",
        "Children's Books > Activities, Crafts & Games > Coloring Books",
        "Children's Books > Early Learning > Basic Concepts",
        "Children's Books > Animals",
        "Children's Books > Growing Up & Facts of Life > Friendship, Social Skills & School Life",
    ],
    "story_adult_fiction": [
        "Literature & Fiction > Genre Fiction > Short Stories",
        "Mystery, Thriller & Suspense > Mystery > Cozy",
        "Romance > Clean & Wholesome",
        "Literature & Fiction > Women's Fiction",
        "Science Fiction & Fantasy > Fantasy > Short Stories",
    ],
    "story_kids": [
        "Children's Books > Literature & Fiction > Chapter Books & Readers",
        "Children's Books > Fairy Tales, Folk Tales & Myths",
        "Children's Books > Animals",
        "Children's Books > Growing Up & Facts of Life > Family Life",
        "Children's Books > Bedtime & Dreaming",
    ],
}


def suggest_categories(book_type: str, audience: str, limit: int = 6) -> list[str]:
    a = audience.lower()
    kids = any(w in a for w in ("kid", "child", "toddler", "preschool", "teen", "boys", "girls", "ages"))
    if book_type == "coloring":
        key = "coloring_kids" if kids else ("coloring_seniors" if any(w in a for w in ("senior", "elder", "dementia", "low vision")) else "coloring_adults")
    else:
        key = "story_kids" if kids else "story_adult_fiction"
    return CATEGORIES[key][:limit]
