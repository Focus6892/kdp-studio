import datetime as dt
from pathlib import Path

from PIL import Image

from kdp_studio.watch.covers import analyze_covers, dominant_colors
from kdp_studio.watch.insights import heuristic_insights, load_reviews
from kdp_studio.watch.models import Snapshot, WatchItem, Watchlist, load_watchlist, save_watchlist
from kdp_studio.watch.pipeline import make_report, take_snapshot
from kdp_studio.watch.report import build_report
from kdp_studio.watch.store import WatchStore

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc


def test_watchlist_roundtrip(tmp_path):
    p = tmp_path / "wl.yaml"
    wl = Watchlist()
    assert wl.add(WatchItem(asin="B0TESTASN1", label="A"))
    assert not wl.add(WatchItem(asin="B0TESTASN1", label="dup"))
    save_watchlist(p, wl)
    assert load_watchlist(p).items[0].label == "A"
    assert load_watchlist(tmp_path / "missing.yaml").items == []


def test_fixture_snapshots_and_report(tmp_path):
    wl_path = tmp_path / "wl.yaml"
    wl = Watchlist()
    wl.add(WatchItem(asin="B0TESTASN1", label="A"))
    wl.add(WatchItem(asin="B0TESTASN2", label="B", ours=True))
    save_watchlist(wl_path, wl)
    db = tmp_path / "watch.sqlite"
    now = dt.datetime(2026, 10, 1, tzinfo=UTC)
    for day in (0, 7, 14):
        snaps = take_snapshot(wl_path, "fixture", db, day=day, now=now)
        assert len(snaps) == 2
    rep, paths = make_report(wl_path, db, tmp_path / "out", now=now + dt.timedelta(days=14))
    assert len(rep.rows) == 2 and all(r.snapshots == 3 for r in rep.rows)
    assert all(r.week_ago is not None and r.bsr_delta_week is not None for r in rep.rows)
    assert any(r.ours for r in rep.rows)
    assert paths["latest"].is_file() and paths["csv"].is_file()
    assert "| ASIN |" in paths["latest"].read_text(encoding="utf-8")


def test_alert_rules(tmp_path):
    store = WatchStore(tmp_path / "w.sqlite")
    t0 = dt.datetime(2026, 9, 1, tzinfo=UTC)
    store.add([
        Snapshot(ts=t0, asin="B0ALERTAS1", source="t", price=9.99, bsr=50_000, bsr_store="Books", rating_count=100),
        Snapshot(ts=t0 + dt.timedelta(days=8), asin="B0ALERTAS1", source="t", price=7.99, bsr=30_000, bsr_store="Books", rating_count=150),
    ])
    wl = Watchlist(items=[WatchItem(asin="B0ALERTAS1", label="Hot")])
    rep = build_report(store, wl, now=t0 + dt.timedelta(days=8))
    store.close()
    alerts = " | ".join(rep.alerts)
    assert "price cut" in alerts and "BSR improved" in alerts and "ratings/day" in alerts


def test_csv_watch_source(tmp_path):
    csv_path = tmp_path / "export.csv"
    csv_path.write_text("ASIN,Title,Price,BSR,Ratings\nB0CSVASIN1,Some Book,$8.99,\"#12,000 in Books\",45\nB0OTHERAS1,Other,$5,1000,3\n", encoding="utf-8")
    wl_path = tmp_path / "wl.yaml"
    save_watchlist(wl_path, Watchlist(items=[WatchItem(asin="B0CSVASIN1", label="csv")]))
    snaps = take_snapshot(wl_path, "csv", tmp_path / "w.sqlite", csv_path=csv_path)
    assert len(snaps) == 1 and snaps[0].bsr == 12000 and snaps[0].price == 8.99 and snaps[0].rating_count == 45


def test_review_insights_heuristic():
    reviews = load_reviews(ROOT / "examples" / "reviews-sample.txt")
    assert len(reviews) == 8
    ins = heuristic_insights(reviews)
    themes = " ".join(ins.complaints)
    assert "paper too thin / bleed-through" in themes and "designs too detailed / small" in themes and "double-sided pages" in themes
    assert any("wish" in r.lower() for r in ins.requests)
    assert ins.differentiation_brief and ins.source == "heuristic"


def test_cover_palette_offline(tmp_path):
    p = tmp_path / "cover.jpg"
    img = Image.new("RGB", (300, 480), (200, 60, 60))
    img.paste((20, 30, 90), (0, 0, 300, 160))
    img.save(p, "JPEG")
    colors = dominant_colors(p)
    assert 1 <= len(colors) <= 5 and all(c.startswith("#") and len(c) == 7 for c in colors)
    res = analyze_covers([p], use_claude=False)
    assert res[0]["source"] == "palette-only" and res[0]["palette_hex"]
