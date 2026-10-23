"""Write a chosen candidate into a book.yaml, preserving comments when ruamel.yaml is installed."""

from __future__ import annotations

import shutil
from pathlib import Path

from .generate import MetadataCandidate


def _ruamel():
    try:
        from ruamel.yaml import YAML
    except ImportError:
        return None
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    return y


def apply_candidate(book_path: Path, cand: MetadataCandidate, author: str | None = None, backup: bool = True) -> Path | None:
    book_path = Path(book_path)
    backup_path = None
    if backup:
        backup_path = book_path.with_suffix(book_path.suffix + ".bak")
        shutil.copyfile(book_path, backup_path)

    yaml_rt = _ruamel()
    if yaml_rt is not None:
        data = yaml_rt.load(book_path.read_text(encoding="utf-8"))
    else:
        import yaml

        data = yaml.safe_load(book_path.read_text(encoding="utf-8"))

    md = data.setdefault("metadata", {})
    md["title"] = cand.title
    if cand.subtitle:
        md["subtitle"] = cand.subtitle
    elif "subtitle" in md:
        del md["subtitle"]
    if author:
        md["author"] = author
    md["description_html"] = cand.description_html
    md["keywords"] = list(cand.keywords[:7])
    md["categories"] = list(cand.categories[:3])
    if cand.reading_age is not None:
        md["reading_age"] = {"min": cand.reading_age.min, "max": cand.reading_age.max}
    elif "reading_age" in md:
        del md["reading_age"]
    if cand.series_name:
        series = md.get("series") or {}
        series["name"] = cand.series_name
        md["series"] = series

    if yaml_rt is not None:
        with book_path.open("w", encoding="utf-8") as fh:
            yaml_rt.dump(data, fh)
    else:
        import yaml

        book_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return backup_path
