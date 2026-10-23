import datetime as dt
from pathlib import Path

from kdp_studio.monitor.ads import break_even_acos, load_ads_csv, summarize_ads
from kdp_studio.monitor.report import monitor_markdown, write_monitor_report
from kdp_studio.monitor.sales import load_sales, summarize_sales
from kdp_studio.monitor.status import mark_title, title_rows
from kdp_studio.publish.store import PublishStore
from kdp_studio.watch.models import load_watchlist

UTC = dt.timezone.utc


def test_ads_csv_parsing_and_flags(tmp_path):
    csv_path = tmp_path / "ads.csv"
    csv_path.write_text(
        "Campaigns,Status,Impressions,Clicks,Spend,14 Day Total Orders (#),14 Day Total Sales,ACOS\n"
        "Auto - Flowers,Enabled,\"12,340\",85,$41.20,9,$89.91,45.82%\n"
        "Manual - Seniors,Enabled,\"4,100\",22,$11.00,0,$0.00,\n"
        "Brand - Bold Easy,Paused,900,30,$9.00,6,$59.94,15.0%\n"
        "Total,,17340,137,$61.20,15,$149.85,\n",
        encoding="utf-8",
    )
    rows = load_ads_csv(csv_path)
    assert len(rows) == 3  # totals row dropped
    be = break_even_acos(3.15, 9.99)  # $3.15 royalty on a $9.99 list price
    s = summarize_ads(rows, target_acos=0.30, break_even=be)
    by = {r.campaign: r for r in s["rows"]}
    assert abs(by["Auto - Flowers"].acos - 0.4582) < 0.001 and any("break-even" in f for f in by["Auto - Flowers"].flags)
    assert any("no orders" in f for f in by["Manual - Seniors"].flags)
    assert by["Brand - Bold Easy"].flags == []
    assert s["spend"] == 61.2 and s["orders"] == 15 and s["flagged"] and s["acos"] is not None


def test_sales_csv_parsing(tmp_path):
    p = tmp_path / "royalties.csv"
    p.write_text(
        "Royalty Date,Title,Author Name,ASIN/ISBN,Marketplace,Royalty Type,Transaction Type,Units Sold,Units Refunded,Net Units Sold,Avg. List Price without tax,Royalty,Currency\n"
        "2026-09-03,Bold & Easy Flowers,Mia Hartwell,9798000000001,Amazon.com,60%,Standard,3,0,3,9.99,9.45,USD\n"
        "2026-09-14,Bold & Easy Flowers,Mia Hartwell,9798000000001,Amazon.co.uk,60%,Standard,1,0,1,7.99,2.10,GBP\n"
        "2026-10-02,The Lantern Lane Letters,June Alder,B0LANTERN1,Amazon.com,70%,Standard,2,1,1,2.99,1.99,USD\n",
        encoding="utf-8",
    )
    rows = load_sales(p)
    assert len(rows) == 3 and rows[0].units == 3 and rows[0].royalty == 9.45
    s = summarize_sales(rows)
    assert s["units"] == 5 and abs(s["royalty"] - 13.54) < 0.01
    assert s["titles"][0]["title"] == "Bold & Easy Flowers" and s["titles"][0]["asins"] == ["9798000000001"]
    assert set(s["months"]) == {"2026-09", "2026-10"}
    s2 = summarize_sales(rows, since=dt.date(2026, 10, 1))
    assert s2["units"] == 1


def test_title_status_and_mark_adds_to_watchlist(tmp_path):
    store = PublishStore(tmp_path / "p.sqlite")
    now = dt.datetime(2026, 10, 23, 12, tzinfo=UTC)
    store.upsert_title("slow", "paperback", "in_review", title="Slow Book", ts=now - dt.timedelta(days=6))
    store.upsert_title("fresh", "paperback", "draft", title="Fresh Book", ts=now)
    wl_path = tmp_path / "watchlist.yaml"
    mark_title(store, "fresh", "paperback", "live", asin="b0newasin1", title="Fresh Book", watchlist_path=wl_path, now=now)
    rows = {r["book_id"]: r for r in title_rows(store, now)}
    assert any("in review for" in f for f in rows["slow"]["flags"])
    assert rows["fresh"]["status"] == "live" and rows["fresh"]["asin"] == "b0newasin1"
    assert any("editable" in f for f in rows["fresh"]["flags"])
    wl = load_watchlist(wl_path)
    assert wl.items and wl.items[0].asin == "B0NEWASIN1" and wl.items[0].ours
    text = monitor_markdown(store, now=now)
    assert "| slow | paperback | in_review" in text and "Weekly quota" in text
    paths = write_monitor_report(text, tmp_path / "out", now)
    assert paths["latest"].is_file()
    store.close()


def test_mark_counts_hand_finished_titles_toward_quota(tmp_path):
    import datetime as dt

    from kdp_studio.publish.quota import quota_status
    from kdp_studio.publish.store import PublishStore

    store = PublishStore(tmp_path / "p.sqlite")
    now = dt.datetime(2026, 10, 23, 8, tzinfo=dt.timezone.utc)
    mark_title(store, "by-hand", "paperback", "draft", title="Finished by hand", now=now)
    q = quota_status(store, now)["paperback"]
    assert q.created == 1 and q.submitted == 0
    mark_title(store, "by-hand", "paperback", "in_review", now=now + dt.timedelta(hours=1))
    q = quota_status(store, now)["paperback"]
    assert q.created == 1 and q.submitted == 1  # no duplicate 'created'
    store.close()

