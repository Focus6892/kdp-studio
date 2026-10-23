import datetime as dt

import pytest

from kdp_studio.niche.autocomplete import parse_suggestions
from kdp_studio.niche.keywords import expand_keywords, template_expand
from kdp_studio.niche.sources.apify import record_to_observation
from kdp_studio.niche.sources.creators import item_to_observation
from kdp_studio.niche.sources.csv_source import CsvSource, rows_to_observations
from kdp_studio.niche.sources.fixture import FixtureSource


def test_fixture_is_deterministic_and_keyword_dependent():
    a = [b.asin for b in FixtureSource(seed=1).search("flowers coloring book", 10)]
    b = [b.asin for b in FixtureSource(seed=1).search("flowers coloring book", 10)]
    c = [b.asin for b in FixtureSource(seed=1).search("cats coloring book", 10)]
    assert a == b and a != c and len(a) == 10


def test_csv_alias_mapping_and_parsing(tmp_path):
    rows = [
        {
            "ASIN": "B0TEST0001",
            "Book Title": "Bold and Easy Flowers Coloring Book",
            "Price": "$9.99",
            "Best Sellers Rank": "#12,345 in Books",
            "Ratings": "1,234",
            "Publication Date": "May 1, 2024",
            "Page Count": "66 pages",
            "Publisher": "Independently published",
            "Search Term": "bold and easy flowers",
        }
    ]
    obs = rows_to_observations(rows)
    assert len(obs) == 1
    o = obs[0]
    assert o.asin == "B0TEST0001" and o.price == 9.99 and o.bsr == 12345 and o.rating_count == 1234
    assert o.pub_date == dt.date(2024, 5, 1) and o.pages == 66 and o.is_indie is True and o.keyword == "bold and easy flowers"
    assert o.age_days is not None and o.age_days > 0


def test_csv_source_requires_keyword(tmp_path):
    p = tmp_path / "export.csv"
    p.write_text("asin,title,bsr\nB01,Some Title,5000\n", encoding="utf-8")
    with pytest.raises(ValueError):
        CsvSource(p)
    src = CsvSource(p, default_keyword="some niche")
    assert src.keywords == ["some niche"]
    assert src.search("Some Niche", 10)[0].bsr == 5000


def test_apify_record_mapping():
    rec = {
        "recordType": "BOOK", "keyword": "gratitude journal", "asin": "B0APIFY001", "title": "Daily Gratitude Journal",
        "author": "A. Writer", "price": 7.99, "currency": "USD", "bsrOverall": "45,210", "bsrOverallCategory": "Kindle Store",
        "categoryRanks": [{"category": "Self-Help", "rank": 120}], "rating": "4.6", "ratingCount": "312", "publishDate": "2025-02-10",
        "publicationAgeDays": 255, "pageCount": 120, "publisher": "Independently published", "publisherType": "independent",
        "organicPosition": 3, "detailUrl": "https://www.amazon.com/dp/B0APIFY001",
    }
    o = record_to_observation(rec)
    assert o is not None and o.bsr == 45210 and o.bsr_store == "Kindle Store" and o.category_ranks == [("Self-Help", 120)]
    assert o.rating_count == 312 and o.age_days == 255 and o.is_indie is True and o.position == 3
    assert record_to_observation({"recordType": "NICHE", "asin": "x"}) is None


def test_creators_item_mapping():
    item = {
        "asin": "B0CREATOR1",
        "detailPageURL": "https://www.amazon.com/dp/B0CREATOR1?tag=xyz-20",
        "itemInfo": {
            "title": {"displayValue": "Bold & Easy Flowers", "label": "Title", "locale": "en_US"},
            "byLineInfo": {
                "contributors": [{"name": "Mia Hartwell", "role": "Author", "roleType": "author", "locale": "en_US"}],
                "manufacturer": {"displayValue": "Independently published", "label": "Manufacturer", "locale": "en_US"},
            },
            "contentInfo": {
                "pagesCount": {"displayValue": 66, "label": "Number of Pages", "locale": "en_US"},
                "publicationDate": {"displayValue": "2026-03-04T00:00:01Z", "label": "Publication Date", "locale": "en_US"},
            },
            "classifications": {"binding": {"displayValue": "Paperback", "label": "Binding", "locale": "en_US"}},
        },
        "offersV2": {"listings": [{"price": {"money": {"amount": 9.99, "currency": "USD"}}}]},
        "browseNodeInfo": {
            "websiteSalesRank": {"displayName": "Books", "salesRank": 23456},
            "browseNodes": [{"id": "4253", "displayName": "Coloring Books for Grown-Ups", "salesRank": 87}],
        },
    }
    o = item_to_observation(item, "bold and easy flowers", 1)
    assert o is not None and o.title == "Bold & Easy Flowers" and o.author == "Mia Hartwell" and o.publisher == "Independently published"
    assert o.pages == 66 and o.pub_date == dt.date(2026, 3, 4) and o.format == "Paperback" and o.price == 9.99
    assert o.bsr == 23456 and o.bsr_store == "Books" and o.category_ranks == [("Coloring Books for Grown-Ups", 87)]
    assert o.is_indie is True and o.rating_count is None


def test_keyword_expansion_offline():
    kws = expand_keywords(["Flowers"], "coloring")
    assert kws[0] == "flowers" and "flowers coloring book" in kws
    assert len(kws) == len(set(kws))
    assert template_expand(["bold and easy coloring book"], "coloring")[0] == "bold and easy coloring book"


def test_parse_suggestions_filters_and_dedupes():
    payload = {"suggestions": [{"value": "coloring book for adults", "type": "KEYWORD"}, {"value": "Coloring Book For Adults"}, {"value": "x", "type": "WIDGET"}, {"value": ""}]}
    assert parse_suggestions(payload) == ["coloring book for adults"]
