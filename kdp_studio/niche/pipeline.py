"""niche-scout orchestration: topics -> keywords -> observations -> summaries -> concepts -> store + report."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..llm import claude_available
from .concepts import concept_cards
from .keywords import expand_keywords
from .models import BookObservation, NicheRun
from .report import write_run
from .scoring import summarize
from .sources import make_source
from .store import NicheStore

log = logging.getLogger(__name__)


@dataclass
class ScoutOptions:
    topics: list[str] = field(default_factory=list)
    source: str = "fixture"
    book_type: str = "coloring"
    max_books: int = 24
    expand: bool = False
    use_autocomplete: bool = False
    use_claude: bool = True
    concepts_for_top: int = 3
    concepts_n: int = 10
    out_dir: Path = Path("niches")
    db_path: Path | None = None
    csv_path: Path | None = None
    default_keyword: str | None = None
    max_keywords: int = 40
    alias: str = "books"
    seed: int = 1


def run_scout(opts: ScoutOptions) -> tuple[NicheRun, dict[str, Path]]:
    source = make_source(opts.source, csv_path=opts.csv_path, default_keyword=opts.default_keyword, seed=opts.seed)
    topics = list(opts.topics)
    if not topics and hasattr(source, "keywords"):
        topics = list(source.keywords)  # csv files carry their own keywords
    if not topics:
        raise ValueError("Give at least one --topic (or a CSV that contains a keyword column)")

    claude_ok = opts.use_claude and claude_available()
    if opts.expand:
        keywords = expand_keywords(topics, opts.book_type, use_autocomplete=opts.use_autocomplete, use_claude=claude_ok, alias=opts.alias, max_total=opts.max_keywords)
    else:
        keywords = topics
    log.info("scoring %d keyword(s) from %s", len(keywords), source.name)

    observations: dict[str, list[BookObservation]] = {}
    run = NicheRun(source=source.name, book_type=opts.book_type, topics=topics, keywords=keywords)
    for kw in keywords:
        try:
            books = source.search(kw, opts.max_books)
        except Exception as exc:  # one failing keyword must not kill the run
            log.warning("search failed for %r: %s", kw, exc)
            continue
        if not books:
            log.info("no results for %r", kw)
            continue
        observations[kw] = books
        run.summaries.append(summarize(kw, books, source.name))

    for s in run.ranked()[: max(0, opts.concepts_for_top)]:
        run.concepts[s.keyword] = concept_cards(s, opts.book_type, opts.concepts_n, use_claude=claude_ok)

    db_path = opts.db_path or (opts.out_dir / "niche_scout.sqlite")
    store = NicheStore(db_path)
    try:
        store.save_run(run, observations)
    finally:
        store.close()
    paths = write_run(run, opts.out_dir)
    paths["db"] = db_path
    return run, paths
