import datetime as dt
from pathlib import Path

from kdp_studio.publish.checklist import build_checklist, split_author
from kdp_studio.publish.quota import quota_status, week_window
from kdp_studio.publish.selectors import DEFAULT_SELECTORS, dump_default_yaml, expand, load_selectors
from kdp_studio.publish.store import PublishStore
from kdp_studio.schema import load_book

ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc


def test_week_window_resets_sunday_utc():
    # 2026-10-23 is a Friday -> window starts Sunday 2026-10-18 00:00 UTC
    start, end = week_window(dt.datetime(2026, 10, 23, 15, 0, tzinfo=UTC))
    assert start == dt.datetime(2026, 10, 18, tzinfo=UTC) and end == dt.datetime(2026, 10, 25, tzinfo=UTC)
    # Sunday 00:00 is the start of a new window; Saturday 23:59 still belongs to the old one
    assert week_window(dt.datetime(2026, 10, 25, 0, 0, tzinfo=UTC))[0] == dt.datetime(2026, 10, 25, tzinfo=UTC)
    assert week_window(dt.datetime(2026, 10, 24, 23, 59, tzinfo=UTC))[0] == dt.datetime(2026, 10, 18, tzinfo=UTC)


def test_quota_counts_and_blocks(tmp_path):
    store = PublishStore(tmp_path / "p.sqlite")
    now = dt.datetime(2026, 10, 23, 12, tzinfo=UTC)
    store.add_event("b1", "paperback", "created", ts=now - dt.timedelta(days=1))
    store.add_event("b1", "paperback", "submitted", ts=now - dt.timedelta(days=1))
    store.add_event("b2", "paperback", "created", ts=now - dt.timedelta(hours=2))
    store.add_event("old", "paperback", "created", ts=now - dt.timedelta(days=10))  # previous window
    q = quota_status(store, now)
    assert q["paperback"].created == 2 and q["paperback"].submitted == 1
    assert q["paperback"].remaining_created == 0 and not q["paperback"].can_start
    assert q["ebook"].can_start and q["ebook"].created == 0
    store.close()


def test_store_titles_and_queue(tmp_path):
    store = PublishStore(tmp_path / "p.sqlite")
    t0 = dt.datetime(2026, 10, 1, tzinfo=UTC)
    store.upsert_title("b1", "paperback", "draft", title="Book One", ts=t0)
    store.upsert_title("b1", "paperback", "in_review", ts=t0 + dt.timedelta(days=1))
    row = store.upsert_title("b1", "paperback", "live", asin="B0TESTASN1", ts=t0 + dt.timedelta(days=3))
    assert row["status"] == "live" and row["asin"] == "B0TESTASN1" and row["submitted_ts"].startswith("2026-10-02") and row["created_ts"].startswith("2026-10-01")
    qid = store.queue_add("examples/a/book.yaml", "paperback", priority=2, book_id="a")
    store.queue_add("examples/b/book.yaml", "ebook", priority=1, book_id="b")
    nxt = store.queue_next({"paperback"})
    assert nxt and nxt["id"] == qid
    store.queue_update(qid, "running")
    store.queue_update(qid, "done", notes="submitted")
    assert store.queue_list("queued")[0]["book_id"] == "b"
    assert store.queue_remove(qid) and len(store.queue_list()) == 1
    store.close()


def test_split_author():
    assert split_author("Mia Hartwell") == ("Mia", "Hartwell")
    assert split_author("June Rose Alder") == ("June Rose", "Alder")
    assert split_author("Cher") == ("", "Cher")


def test_checklist_contains_every_field():
    book = load_book(ROOT / "examples" / "bold-easy-flowers" / "book.yaml")
    text = build_checklist(book, "paperback")
    assert "Bold & Easy Flowers" in text and "large print coloring book" in text
    assert "Images: AI-generated" in text and "Low-content book: No" in text
    assert "8.5 x 11 in" in text and "Black & white interior with white paper" in text and "$9.99" in text
    story = load_book(ROOT / "examples" / "lantern-lane" / "book.yaml")
    etext = build_checklist(story, "ebook")
    assert "KDP Select" in etext and "$2.99" in etext


def test_selectors_expand_and_override(tmp_path):
    assert expand(["#data-{fmt}-title"], "paperback") == ["#data-print-book-title"]
    assert expand(["#data-{fmt}-keywords-{i}"], "ebook", i=3) == ["#data-ebook-keywords-3"]
    override = tmp_path / "sel.yaml"
    override.write_text("details:\n  title: ['#my-title']\nbookshelf_url: https://example.test/shelf\n", encoding="utf-8")
    sel = load_selectors(override)
    assert sel["details"]["title"] == ["#my-title"] and sel["details"]["subtitle"] == DEFAULT_SELECTORS["details"]["subtitle"]
    assert sel["bookshelf_url"] == "https://example.test/shelf"
    assert "save-and-publish" in dump_default_yaml()
