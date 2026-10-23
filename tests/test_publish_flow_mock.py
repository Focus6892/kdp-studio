"""Drives the assisted flow against the local mock KDP pages (file://) in a headless browser.
Skipped when Playwright or a Chromium-based browser is unavailable."""

import shutil
import urllib.parse
from pathlib import Path

import pytest

from kdp_studio.publish.browser import BrowserSession
from kdp_studio.publish.flow import ScriptedApprover, run_flow
from kdp_studio.publish.selectors import load_selectors
from kdp_studio.publish.store import PublishStore
from kdp_studio.schema import load_book

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "tests" / "mock_kdp"
EXAMPLE_DIR = ROOT / "examples" / "bold-easy-flowers"

pytest.importorskip("playwright.sync_api")


def _session(tmp_path, start_url):
    try:
        return BrowserSession(tmp_path / "profile", headless=True, allow_headless_local=True, start_url=start_url, slow_mo_ms=0, screenshot_dir=tmp_path / "shots").open()
    except RuntimeError as exc:  # no browser installed
        pytest.skip(f"no browser available: {exc}")


def test_headless_refused_for_remote_urls(tmp_path):
    with pytest.raises(ValueError):
        BrowserSession(tmp_path / "profile", headless=True, allow_headless_local=True, start_url="https://kdp.amazon.com/bookshelf")


def test_assisted_flow_against_mock(tmp_path):
    work = tmp_path / "book"
    shutil.copytree(EXAMPLE_DIR, work)
    build = work / "build"
    build.mkdir(exist_ok=True)  # the example folder may already carry a build/ from earlier runs
    (build / "interior.pdf").write_bytes(b"%PDF-1.4 mock")
    (build / "cover_wrap.pdf").write_bytes(b"%PDF-1.4 mock")
    book = load_book(work / "book.yaml")

    start = (MOCK / "bookshelf.html").as_uri()
    session = _session(tmp_path, start)
    store = PublishStore(tmp_path / "publish.sqlite")
    approver = ScriptedApprover(["", "", "d"])  # details OK, content OK, saved as draft (never 'p')
    try:
        result = run_flow(book, "paperback", session, load_selectors(None), approver, store, start_url=start, book_path=str(work / "book.yaml"))
        page = session.page
        assert "pricing.html" in page.url
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(page.url).query))
        # the tool never publishes
        assert page.evaluate("window.__published") is False
        assert page.input_value("#data-pricing-print-us-price-input") == "9.99"
        assert page.is_checked("#data-print-book-pricing-rights-all-territories")
    finally:
        session.close()

    assert result.status == "draft"
    assert result.events == ["created", "draft_saved"]
    # details page values travelled through the query string
    assert params["d.data-print-book-title"] == "Bold & Easy Flowers"
    assert params["d.data-print-book-primary-author-last-name"] == "Hartwell" and params["d.data-print-book-primary-author-first-name"] == "Mia"
    assert params["d.data-print-book-language-native"] == "en"
    assert params["d.non-public-domain"] == "false" and params["d.mock-adult-no"] == "false"
    assert params["d.data-print-book-keywords-6"] == "stress relief coloring"
    assert "d.data-view-is-lcb" not in params and "d.data-print-book-large-print" not in params  # coloring books: neither box
    assert "<h4>" in params["d.description-hidden"] and "<h4>" in params["d.description-hidden"]  # filled through the CKEDITOR API
    assert params["d.mock-home-marketplace"] == "Amazon.com"
    # AI disclosure lives on the Content tab: radio + custom comboboxes filled in order (text, images, translations)
    assert params["c.ai-yes"] == "yes"
    assert params["c.ai-images-value"] == "Many or all, with minimal or no editing"
    assert params["c.ai-text-value"] == "None" and params["c.ai-translation-value"] == "None"
    # content page (React redesign structure)
    assert params["c.ink-paper-BW_WHITE"] == "BW_WHITE"
    assert params["c.trim-value"].startswith("8.5 x 11 in")
    assert params["c.bleed-yes"] == "bleed" and params["c.cover-finish-MATTE"] == "MATTE"
    assert params["c.isbn-type-KDP"] == "KDP" and params["c.isbn-assigned"] == "free"
    assert params["c.cover-choice-UPLOAD"] == "UPLOAD"
    assert params["c.manuscript-name"] == "interior.pdf" and params["c.cover-name"] == "cover_wrap.pdf"  # via the file chooser
    # gates were asked in order and screenshots taken
    assert len(approver.prompts) == 3 and "never clicks Publish" in approver.prompts[-1]
    assert len(result.screenshots) == 3
    title_row = store.get_title(book.id, "paperback")
    assert title_row and title_row["status"] == "draft"
    store.close()


def test_inventory_lists_form_controls(tmp_path):
    from kdp_studio.publish.browser import inventory_markdown

    start = (MOCK / "details.html").as_uri()
    session = _session(tmp_path, start)
    try:
        session.goto(start)
        inv = session.inventory()
    finally:
        session.close()
    ids = {e["id"] for sc in inv["scopes"] for e in sc["elements"] if e.get("id")}
    assert {"data-print-book-title", "data-print-book-keywords-6", "save-and-continue-announce", "non-public-domain", "data-view-is-lcb"} <= ids
    sel = next(e for sc in inv["scopes"] for e in sc["elements"] if e.get("id") == "data-print-book-language-native")
    assert "English" in sel["options"] and sel["tag"] == "select"
    md = inventory_markdown(inv)
    assert "data-print-book-title" in md and "| frame |" in md


def test_flow_stops_on_quit(tmp_path):
    book = load_book(EXAMPLE_DIR / "book.yaml")
    start = (MOCK / "details.html").as_uri()
    session = _session(tmp_path, start)
    store = PublishStore(tmp_path / "publish.sqlite")
    try:
        result = run_flow(book, "paperback", session, load_selectors(None), ScriptedApprover(["q"]), store, start_url=start)
    finally:
        session.close()
    assert result.status == "aborted" and result.events == ["aborted"]
    assert store.get_title(book.id, "paperback") is None
    store.close()
