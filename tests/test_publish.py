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
    assert "Images scope: many or all (interior pages)" in text and "AI tools: gpt-image-1" in text and "I confirm that my answers are accurate" in text
    assert "8.5 x 11 in" in text and "Black & white interior with white paper" in text and "$9.99" in text
    story = load_book(ROOT / "examples" / "lantern-lane" / "book.yaml")
    assert story.ai_scope()["Images"][0] == "one or a few"  # only the cover is AI-made
    assert "REQUIRED" in story.ai_disclosure()["AI tools"]  # no tool names given yet
    etext = build_checklist(story, "ebook")
    assert "KDP Select" in etext and "$2.99" in etext


def test_diagnose_cover_size_error():
    from kdp_studio.publish.diagnose import explain_cover_size_error, guess_cover

    # the live KDP previewer message from the Lantern Lane test upload (draft left on KDP's 6x9 white defaults)
    res = explain_cover_size_error("Your expected cover size is 12.313x9.250 but the submitted file size is 10.320x8.250.", pages=28)
    assert res["expected"].trim == "6x9" and "white_bw" in res["expected"].papers
    assert res["submitted"].trim == "5x8" and res["submitted"].papers == ["cream_bw"]
    assert any("Trim Size" in a and "5x8" in a for a in res["advice"])
    g = guess_cover(17.3986, 11.25, pages=66)
    assert g.trim == "8.5x11" and "white_bw" in g.papers
    assert guess_cover(10.32, 8.25).pages_estimate["cream_bw"] == 28


def test_selectors_expand_and_override(tmp_path):
    assert expand(["#data-{fmt}-title"], "paperback") == ["#data-print-book-title"]
    assert expand(["#data-{fmt}-keywords-{i}"], "ebook", i=3) == ["#data-ebook-keywords-3"]
    assert expand(["input[name='data[{fmt_u}][keywords][{i}]']"], "paperback", i=2) == ["input[name='data[print_book][keywords][2]']"]
    override = tmp_path / "sel.yaml"
    override.write_text("details:\n  title: ['#my-title']\nbookshelf_url: https://example.test/shelf\n", encoding="utf-8")
    sel = load_selectors(override)
    assert sel["details"]["title"] == ["#my-title"] and sel["details"]["subtitle"] == DEFAULT_SELECTORS["details"]["subtitle"]
    assert sel["bookshelf_url"] == "https://example.test/shelf"
    assert "save-and-publish" in dump_default_yaml()


def test_flow_records_errors_instead_of_crashing(tmp_path):
    from kdp_studio.publish.browser import BrowserSession
    from kdp_studio.publish.flow import ScriptedApprover, run_flow

    book = load_book(ROOT / "examples" / "lantern-lane" / "book.yaml")
    session = BrowserSession(tmp_path / "profile")  # never opened: no browser needed
    assert session.is_alive() is False

    def boom(url):
        raise RuntimeError("Target page, context or browser has been closed")

    session.goto = boom
    store = PublishStore(tmp_path / "p.sqlite")
    res = run_flow(book, "paperback", session, load_selectors(None), ScriptedApprover([]), store, start_url="file:///mock.html")
    assert res.status == "error" and res.events == ["error"] and res.finished
    assert any("RuntimeError: Target page" in n for n in res.notes)
    assert store.get_title(book.id, "paperback") is None  # nothing was created on KDP
    store.close()


def test_quota_counts_hand_made_titles_and_kdp_limit(tmp_path):
    from kdp_studio.publish.quota import quota_markdown, record_external, record_kdp_limit

    store = PublishStore(tmp_path / "p.sqlite")
    now = dt.datetime(2026, 10, 23, 12, tzinfo=UTC)
    record_external(store, "paperback", created=1, note="test draft made by hand", now=now)
    assert quota_status(store, now)["paperback"].created == 1
    record_kdp_limit(store, "paperback", now=now)
    q = quota_status(store, now)["paperback"]
    assert q.kdp_blocked and q.created == 2 and not q.can_start
    assert quota_status(store, now + dt.timedelta(days=7))["paperback"].can_start  # next window
    assert "Title creation limit reached" in quota_markdown(quota_status(store, now))
    store.close()


def test_resume_skips_the_creation_check(tmp_path):
    from kdp_studio.publish.pipeline import check_preconditions
    from kdp_studio.publish.quota import record_kdp_limit

    book = load_book(ROOT / "examples" / "bold-easy-flowers" / "book.yaml")
    store = PublishStore(tmp_path / "p.sqlite")
    now = dt.datetime(2026, 10, 23, 12, tzinfo=UTC)
    record_kdp_limit(store, "paperback", now=now)
    blocked, _ = check_preconditions(book, "paperback", store, require_preflight=False, now=now)
    assert any(x.code == "publish.quota" for x in blocked.errors)
    resumed, _ = check_preconditions(book, "paperback", store, require_preflight=False, now=now, resume=True)
    assert not any(x.code == "publish.quota" for x in resumed.errors)
    store.close()

