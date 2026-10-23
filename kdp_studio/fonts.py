"""Font discovery with a guaranteed fallback.

KDP requires every font in a print PDF to be embedded, so we only ever use
TrueType files we can load and embed ourselves. Search order:
1. an explicit path or file name given in book.yaml
2. ./fonts/ in the current project
3. OS font directories (Windows, Linux, macOS)
4. the Bitstream Vera fonts shipped inside reportlab (always available)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import reportlab

REPORTLAB_FONT_DIR = Path(reportlab.__file__).parent / "fonts"

ROLE_PREFERENCES: dict[str, list[str]] = {
    "display": ["impact.ttf", "GeorgiaPro-Black.ttf", "georgiab.ttf", "arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf", "VeraBd.ttf"],
    "bold": ["arialbd.ttf", "segoeuib.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf", "VeraBd.ttf"],
    "regular": ["arial.ttf", "segoeui.ttf", "calibri.ttf", "DejaVuSans.ttf", "Vera.ttf"],
    "italic": ["ariali.ttf", "georgiai.ttf", "DejaVuSans-Oblique.ttf", "VeraIt.ttf"],
}
FALLBACK_BY_ROLE = {"display": "VeraBd.ttf", "bold": "VeraBd.ttf", "regular": "Vera.ttf", "italic": "VeraIt.ttf"}


def font_dirs() -> list[Path]:
    dirs = [Path.cwd() / "fonts"]
    windir = os.environ.get("WINDIR")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    dirs += [
        Path("C:/Windows/Fonts"),
        Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / ".local/share/fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        REPORTLAB_FONT_DIR,
    ]
    out: list[Path] = []
    for d in dirs:
        if d.is_dir() and d not in out:
            out.append(d)
    return out


@lru_cache(maxsize=None)
def _index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for d in font_dirs():
        for p in d.rglob("*.ttf"):
            index.setdefault(p.name.lower(), p)
    return index


def find_font(name_or_path: str | None = None, role: str = "regular") -> Path:
    """Return a TTF path. Never raises: falls back to a reportlab Vera font."""
    if name_or_path:
        p = Path(name_or_path)
        if p.is_file():
            return p
        key = p.name.lower()
        if not key.endswith(".ttf"):
            key += ".ttf"
        hit = _index().get(key)
        if hit:
            return hit
    for cand in ROLE_PREFERENCES.get(role, ROLE_PREFERENCES["regular"]):
        hit = _index().get(cand.lower())
        if hit:
            return hit
    return REPORTLAB_FONT_DIR / FALLBACK_BY_ROLE.get(role, "Vera.ttf")
