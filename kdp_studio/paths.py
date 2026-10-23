"""Where runtime data lives: always inside the project folder, whatever the current directory.

The package is installed editable from the repository, so its parent folder is the
project root; when that is not the case (plain site-packages install) fall back to CWD.
"""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
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
