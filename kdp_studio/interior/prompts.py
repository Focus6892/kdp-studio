"""Turn a theme into N distinct page prompts.

Two modes:
- template (offline, deterministic): theme x curated variation list
- claude: asks Claude for N varied subjects via structured output, then
  appends the book's style prompt. Falls back to template on any API problem.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ..schema import ColoringInterior

log = logging.getLogger(__name__)

VARIATIONS = [
    "a single large {theme} subject filling the page",
    "a symmetrical mandala built from {theme} motifs",
    "a cozy scene featuring {theme}",
    "a repeating pattern of {theme} shapes",
    "a close-up detail of {theme}",
    "{theme} framed by a decorative border",
    "{theme} with a butterfly resting nearby",
    "{theme} arranged in a basket",
    "{theme} with ribbons and bows",
    "{theme} with leaves and curling vines",
    "{theme} under a crescent moon and stars",
    "{theme} seen through an open window",
    "{theme} on a table with a teacup",
    "a wreath made of {theme}",
    "{theme} in a watering can",
    "a bouquet of {theme} tied with string",
    "{theme} with a friendly bee",
    "{theme} growing in a garden bed",
    "{theme} in a tall vase",
    "a heart shape made of {theme}",
    "{theme} with a small bird",
    "{theme} with raindrops and clouds",
    "a circular medallion of {theme}",
    "{theme} with a sun and gentle rays",
    "{theme} in a wooden crate",
    "{theme} with a snail and mushrooms",
    "{theme} at a picnic",
    "{theme} with a lantern",
    "an oval cameo of {theme}",
    "{theme} on a quilt pattern background",
]


class PagePrompt(BaseModel):
    index: int = Field(ge=0)
    subject: str
    prompt: str


class PagePromptList(BaseModel):
    prompts: list[PagePrompt]


def _compose(subject: str, interior: ColoringInterior) -> str:
    return f"{subject}, {interior.style_prompt}"


def template_prompts(interior: ColoringInterior, n: int) -> list[PagePrompt]:
    out: list[PagePrompt] = []
    for i in range(n):
        variation = VARIATIONS[i % len(VARIATIONS)]
        suffix = "" if i < len(VARIATIONS) else f" (variation {i // len(VARIATIONS) + 1})"
        subject = variation.format(theme=interior.theme) + suffix
        out.append(PagePrompt(index=i, subject=subject, prompt=_compose(subject, interior)))
    return out


def claude_prompts(interior: ColoringInterior, n: int, model: str) -> list[PagePrompt] | None:
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; using template prompts (pip install 'kdp-studio[ai]')")
        return None

    system = (
        "You design subjects for coloring-book pages. Each subject must be a concrete, "
        "drawable scene or object described in one sentence, distinct from every other "
        "subject in the list, suitable for the stated audience, free of text, logos, "
        "brands, celebrities and copyrighted characters."
    )
    user = (
        f"Theme: {interior.theme}\n"
        f"Audience: {interior.audience}\n"
        f"Number of pages: {n}\n"
        "Return exactly that many prompts. 'subject' is the short name; 'prompt' is the "
        "full one-sentence drawing description. Do not include style words such as "
        "'line art' or 'black and white' — they are appended automatically. "
        "Index pages from 0."
    )
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=PagePromptList,
        )
    except anthropic.AuthenticationError:
        log.warning("Anthropic authentication failed (set ANTHROPIC_API_KEY or run `ant auth login`); using template prompts")
        return None
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit hit; using template prompts")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Anthropic API error %s; using template prompts", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("Could not reach the Anthropic API; using template prompts")
        return None

    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.warning("Claude declined or returned no parsed output; using template prompts")
        return None

    items = response.parsed_output.prompts[:n]
    out = [PagePrompt(index=i, subject=p.subject, prompt=_compose(p.prompt, interior)) for i, p in enumerate(items)]
    if len(out) < n:
        out.extend(template_prompts(interior, n)[len(out):])
    return out


def build_prompts(interior: ColoringInterior, n: int) -> list[PagePrompt]:
    if interior.prompts_with_claude:
        got = claude_prompts(interior, n, interior.prompts_model)
        if got:
            return got
    return template_prompts(interior, n)
