"""Thin wrapper around the Anthropic SDK used by every LLM-assisted step.

All calls go through `parse_structured`, which returns None (and logs why) on any
API problem so callers can fall back to deterministic templates. Credentials are
resolved by the SDK itself (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an
`ant auth login` profile); `claude_available()` is only a cheap pre-check used to
decide whether to try at all.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
T = TypeVar("T", bound=BaseModel)


def sdk_installed() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def claude_available() -> bool:
    if not sdk_installed():
        return False
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    profile_dir = Path.home() / ".config" / "anthropic"
    return profile_dir.is_dir() and any(profile_dir.iterdir())


def parse_structured(system: str, user: str, output_model: type[T], model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> T | None:
    """One structured-output call. Returns the parsed pydantic object or None."""
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed (pip install 'kdp-studio[ai]'); skipping Claude step")
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_model,
        )
    except anthropic.AuthenticationError:
        log.warning("Anthropic authentication failed (set ANTHROPIC_API_KEY or run `ant auth login`); skipping Claude step")
        return None
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit hit; skipping Claude step")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Anthropic API error %s; skipping Claude step", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("Could not reach the Anthropic API; skipping Claude step")
        return None
    except anthropic.AnthropicError as exc:  # e.g. no credentials configured at all
        log.warning("Anthropic client error: %s; skipping Claude step", exc)
        return None

    if response.stop_reason == "refusal":
        log.warning("Claude declined this request (%s)", getattr(response.stop_details, "category", None))
        return None
    if response.stop_reason == "max_tokens":
        log.warning("Claude hit max_tokens; output may be incomplete")
    return response.parsed_output
