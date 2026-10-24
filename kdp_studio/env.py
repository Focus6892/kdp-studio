"""Load API keys from a project-level `.env` file (never committed; `.gitignore` already lists it).

Format: one `NAME=value` per line, `#` comments and blank lines ignored, optional quotes around the
value. Existing environment variables win, so a key exported in the shell overrides the file.
"""

from __future__ import annotations

import os
from pathlib import Path

from .paths import project_root

KEY_VARS = {
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "stability": "STABILITY_API_KEY",
    "pollinations": "POLLINATIONS_API_KEY",  # optional: keyless works, a free account token raises limits/resolution
    "cloudflare": "CF_API_TOKEN",  # plus CF_ACCOUNT_ID
    "anthropic": "ANTHROPIC_API_KEY",
}


def load_dotenv(path: Path | None = None) -> list[str]:
    """Read `.env` (project root by default) into os.environ; returns the names that were set."""
    path = path or project_root() / ".env"
    if not path.is_file():
        return []
    added: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value
            added.append(name)
    return added


def key_status() -> dict[str, bool]:
    """Which provider keys are present (values are never returned)."""
    return {provider: bool(os.environ.get(var)) for provider, var in KEY_VARS.items()}
