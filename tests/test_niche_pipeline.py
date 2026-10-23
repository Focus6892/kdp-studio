from dataclasses import replace

from kdp_studio.niche.pipeline import ScoutOptions, run_scout
from kdp_studio.niche.store import NicheStore

TOPICS = ["bold and easy flowers coloring book for seniors", "mandala coloring book for adults"]


def test_run_scout_fixture_writes_report_and_trends(tmp_path):
    opts = ScoutOptions(topics=TOPICS, source="fixture", use_claude=False, out_dir=tmp_path / "niches", concepts_for_top=1, seed=1)
    run, paths = run_scout(opts)
    assert len(run.summaries) == 2 and run.run_id == 1
    assert paths["latest"].is_file() and paths["csv"].is_file() and paths["json"].is_file()
    text = paths["latest"].read_text(encoding="utf-8")
    assert "| # | Keyword |" in text and "Concept cards" in text
    top = run.ranked()[0].keyword
    # angles already stated in the keyword (e.g. "bold and easy") are skipped, so 8-10 cards remain
    assert 8 <= len(run.concepts[top]) <= 10
    assert all(c.title_idea and len(c.keywords) == 3 and all(len(k) <= 50 for k in c.keywords) for c in run.concepts[top])

    run_scout(replace(opts, seed=2))
    store = NicheStore(paths["db"])
    try:
        trends = store.trends()
        latest = store.latest_summaries()
        hist = store.history(TOPICS[0])
    finally:
        store.close()
    assert len(trends) == 2 and all("delta_opportunity" in t for t in trends)
    assert len(latest) == 2 and latest[0].scores.opportunity >= latest[1].scores.opportunity
    assert len(hist) == 2


def test_run_scout_requires_topics(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        run_scout(ScoutOptions(topics=[], source="fixture", use_claude=False, out_dir=tmp_path))
