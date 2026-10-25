"""Where runtime data lives: always inside the project folder, whatever the current directory.

The package is installed editable from the repository, so its parent folder is the
project root; when that is not the case (plain site-packages install) fall back to CWD.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True inside the PyInstaller build (kdp-studio.exe)."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Where bundled read-only assets live: the PyInstaller _internal folder, or the repository."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def cli_command(args: list[str]) -> list[str]:
    """The command line that runs this tool with `args` in a child process: the exe itself when frozen, else python -m."""
    if is_frozen():
        return [sys.executable, *args]
    return [sys.executable, "-X", "utf8", "-m", "kdp_studio", *args]


def _seed_home(home: Path) -> None:
    """First run of the exe: create the data folder with the sample books and an empty .env."""
    home.mkdir(parents=True, exist_ok=True)
    src = bundle_dir()
    for name in ("examples", ".env.example", "QUICKSTART.md"):
        s, d = src / name, home / name
        if s.exists() and not d.exists():
            shutil.copytree(s, d) if s.is_dir() else shutil.copy2(s, d)
    if not (home / ".env").exists() and (home / ".env.example").exists():
        shutil.copy2(home / ".env.example", home / ".env")
    (home / "books").mkdir(exist_ok=True)


def project_root() -> Path:
    """Where runtime data lives: the repository when running from source; for the exe, KDP_STUDIO_HOME or
    Documents/kdp-studio (created and seeded with the examples on first run), never the install folder."""
    if is_frozen():
        home = Path(os.environ.get("KDP_STUDIO_HOME") or Path.home() / "Documents" / "kdp-studio")
        if not (home / "books").is_dir():
            _seed_home(home)
        return home
    root = Path(__file__).resolve().parents[1]
    if (root / "pyproject.toml").is_file():
        return root
    return Path.cwd()


def data_path(*parts: str) -> Path:
    return project_root().joinpath(*parts)


def resolve_input(path: str | Path) -> Path:
    """A book.yaml (or any input) given on the command line: as typed when it exists, otherwise the same
    relative path inside the project folder, so `examples/<book>/book.yaml` works from any directory."""
    given = Path(path)
    if given.exists() or given.is_absolute():
        return given
    candidate = project_root() / given
    return candidate if candidate.exists() else given
