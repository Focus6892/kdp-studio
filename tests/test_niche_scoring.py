from kdp_studio.niche.phrases import brand_hits, top_phrases
from kdp_studio.niche.scoring import competition_score, demand_score, est_daily_sales, label_for, monetization_score, summarize
from kdp_studio.niche.sources.fixture import FixtureSource


def test_demand_score_is_monotonic_in_bsr():
    assert demand_score(1_000) == 40
    assert demand_score(1_000) > demand_score(50_000) > demand_score(1_000_000) >= 0
    assert demand_score(None) == 0
    assert demand_score(10_000, "Kindle Store") == demand_score(10_000, "Books")


def test_competition_score_bounds_and_partial_data():
    assert competition_score(10, 0.0, 1.0, 0.5) == 40
    assert competition_score(1000, 1.0, 0.0, 0.0) == 0
    assert competition_score(None, None, None, None) == 0
    partial = competition_score(100, None, None, None)
    assert 0 < partial < 40


def test_monetization_score():
    assert monetization_score(12.99, 1.0) == 20
    assert monetization_score(4.99, 0.0) == 0
    assert monetization_score(None, None) == 0
    assert monetization_score(9.99, 0.6) > monetization_score(7.99, 0.2)


def test_est_daily_sales_relative_curve():
    a, b, c = est_daily_sales(1_000), est_daily_sales(10_000), est_daily_sales(100_000)
    assert a > b > c > 0
    assert est_daily_sales(None) is None


def test_labels():
    assert label_for(80, 90) == "strong"
    assert label_for(60, 90) == "promising"
    assert label_for(45, 90) == "crowded"
    assert label_for(20, 90) == "weak"
    assert label_for(90, 10) == "insufficient data"


def test_summarize_fixture_niches():
    src = FixtureSource(seed=3)
    open_books = src.search("bold and easy flowers coloring book for seniors", 24)
    saturated = src.search("mandala coloring book for adults", 24)
    s_open = summarize("bold and easy flowers coloring book for seniors", open_books, "fixture")
    s_sat = summarize("mandala coloring book for adults", saturated, "fixture")
    for s in (s_open, s_sat):
        assert s.n_books == 24 and s.n_with_bsr == 24
        assert 0 <= s.scores.opportunity <= 100
        assert s.scores.label in {"strong", "promising", "crowded", "weak", "insufficient data"}
        assert s.median_bsr and s.median_bsr > 0
        assert s.top_phrases and all(c >= 2 for _, c in s.top_phrases)
        assert s.scores.confidence >= 90
    assert s_open.scores.competition > s_sat.scores.competition
    assert s_open.share_indie > s_sat.share_indie


def test_phrase_mining_and_brand_detection():
    titles = [
        "Bold and Easy Flowers Coloring Book",
        "Easy Flowers Coloring Book for Seniors",
        "Flowers Coloring Book Large Print",
    ]
    phrases = dict(top_phrases(titles))
    assert phrases.get("flowers coloring book") == 3
    assert "coloring book" not in phrases  # absorbed by the equally frequent 3-gram
    assert brand_hits(["Disney Princess Coloring Book", "Pokemon Fun Pages"]) == ["disney", "pokemon"]
    assert brand_hits(["Garden Flowers Coloring Book"]) == []
