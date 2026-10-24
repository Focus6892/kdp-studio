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
    approver = ScriptedApprover(["", "", "s"])  # details OK, content OK, the tool saves the draft itself (never 'p')
    try:
        result = run_flow(book, "paperback", session, load_selectors(None), approver, store, start_url=start, book_path=str(work / "book.yaml"), dump_dir=tmp_path / "dom")
        page = session.page
        assert "pricing.html" in page.url
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(page.url).query))
        # the tool never publishes, but it may save the draft when asked with 's'
        assert page.evaluate("window.__published") is False
        assert page.evaluate("window.__draftSaved") is True
        assert page.input_value("#price-input-usd") == "9.99"
        assert page.is_checked("#worldwide-rights")
        assert page.input_value("#primary-marketplace-value") == "Amazon.com"  # chosen through the ARIA combobox
        # distribution: the 'Amazon' header was mixed (Amazon.co.jp unticked) -> every store enrolled; Expanded Distribution follows book.yaml (off)
        assert page.get_attribute("[aria-label='Enroll all marketplaces in Amazon program']", "aria-checked") == "true"
        assert page.get_attribute("[aria-label='Enroll in Amazon program for Amazon.co.jp']", "aria-checked") == "true"
        assert page.get_attribute("[aria-label='Enroll all marketplaces in Expanded Distribution program']", "aria-checked") == "false"
        # KDP converted CAD itself on blur; the flow clicked 'Base this price on Amazon.com' only for the rows left empty
        assert page.input_value("#price-input-cad") == "13.69"
        assert page.input_value("#price-input-gbp") == "7.89"
        assert page.input_value("input[aria-label='Price for Amazon.fr in EUR']") == "9.19"
        assert page.evaluate("window.__based") == ["Price for Amazon.co.uk in GBP", "Price for Amazon.de in EUR", "Price for Amazon.fr in EUR", "Price for Amazon.co.jp in JPY"]
    finally:
        session.close()

    assert result.status == "draft"
    assert result.events == ["created", "draft_saved"]
    assert {"territories", "primary_marketplace", "amazon_stores", "expanded_distribution", "list_price_us", "other_marketplace_prices"} <= set(result.filled)
    assert not [f for f, _ in result.unfilled if f.startswith("price:")]
    assert any(n.startswith("Based on the Amazon.com price") for n in result.notes)
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
    assert params["c.ai-tool-0"] == "gpt-image-1" and params.get("c.ai-tool-1", "") == ""  # provenance.ai_tools typed into KDP's new field
    assert "c.ai-confirm" not in params  # the accuracy confirmation is the human's tick, never the tool's
    # content page (React redesign structure)
    assert params["c.ink-paper-BW_WHITE"] == "BW_WHITE"
    assert params["c.trim-value"].startswith("8.5 x 11 in")
    assert params["c.bleed-yes"] == "bleed" and params["c.cover-finish-MATTE"] == "MATTE"
    assert params["c.isbn-type-KDP"] == "KDP" and params["c.isbn-assigned"] == "free"
    assert params["c.cover-choice-UPLOAD"] == "UPLOAD"
    assert params["c.manuscript-name"] == "interior.pdf" and params["c.cover-name"] == "cover_wrap.pdf"  # via the file chooser
    # gates were asked in order and screenshots taken
    assert len(approver.prompts) == 3 and "never clicks Publish" in approver.prompts[-1]
    assert len(result.screenshots) == 4  # details, content, pricing, saved-draft
    assert {p.name for p in (tmp_path / "dom").iterdir()} == {"dom-create.json", "dom-create.md", "dom-details.json", "dom-details.md", "dom-categories.json", "dom-categories.md", "dom-content.json", "dom-content.md", "dom-pricing.json", "dom-pricing.md"}
    assert "data-print-book-title" in (tmp_path / "dom" / "dom-details.md").read_text(encoding="utf-8")
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


def test_flow_stops_when_kdp_reports_the_creation_limit(tmp_path):
    from kdp_studio.publish.quota import quota_status

    book = load_book(EXAMPLE_DIR / "book.yaml")
    start = (MOCK / "details.html").as_uri() + "?limit=1"
    session = _session(tmp_path, start)
    store = PublishStore(tmp_path / "publish.sqlite")
    try:
        result = run_flow(book, "paperback", session, load_selectors(None), ScriptedApprover([""]), store, start_url=start)
    finally:
        session.close()
    assert result.status == "blocked" and result.events == ["kdp_limit"]
    assert any("creation limit" in n for n in result.notes)
    assert store.get_title(book.id, "paperback") is None  # nothing was created on KDP
    assert not quota_status(store)["paperback"].can_start  # and the local quota now knows
    store.close()


def test_resume_counts_no_creation(tmp_path):
    book = load_book(EXAMPLE_DIR / "book.yaml")
    start = (MOCK / "details.html").as_uri()
    session = _session(tmp_path, start)
    store = PublishStore(tmp_path / "publish.sqlite")
    try:
        result = run_flow(book, "paperback", session, load_selectors(None), ScriptedApprover(["", "", "d"]), store, start_url=start, resume=True)
    finally:
        session.close()
    assert result.status == "draft" and result.events == ["draft_saved"]
    assert any("Resumed an existing KDP draft" in n for n in result.notes)
    store.close()


def test_flow_never_fills_a_tab_that_did_not_appear(tmp_path):
    """KDP sometimes stays on the Content tab after 'Save and Continue' (disabled button, validation message).
    The flow must then ask the human, and never fill or screenshot the Pricing fields on the wrong page."""
    book = load_book(EXAMPLE_DIR / "book.yaml")
    start = (MOCK / "details.html").as_uri() + "?stay=1"
    session = _session(tmp_path, start)
    store = PublishStore(tmp_path / "publish.sqlite")
    approver = ScriptedApprover(["", "", "", "", "d"])  # details OK, three 'tab not on screen' prompts, saved as draft by hand
    try:
        result = run_flow(book, "paperback", session, load_selectors(None), approver, store, start_url=start, tab_timeout_s=1)
    finally:
        session.close()
    assert result.status == "draft" and "created" not in result.events  # nothing was created on KDP
    assert sum("not on screen yet" in p for p in approver.prompts) == 3
    unfilled = dict(result.unfilled)
    assert "ink_paper" in unfilled and "list_price_us" in unfilled and "territories" in unfilled
    assert any("Content tab never appeared" in n for n in result.notes)
    assert [Path(s).name for s in result.screenshots] == ["01-details.png", "02-content-unmatched.png"]  # the stuck page is kept for selector upkeep
    store.close()


def test_categories_are_picked_in_the_mock_dialog(tmp_path):
    """Three placements under the same subtree: cascading selects once, then three ticks, then Save."""
    book = load_book(ROOT / "examples" / "lantern-lane" / "book.yaml")
    start = (MOCK / "details.html").as_uri()
    session = _session(tmp_path, start)
    store = PublishStore(tmp_path / "publish.sqlite")
    try:
        result = run_flow(book, "paperback", session, load_selectors(None), ScriptedApprover(["q"]), store, start_url=start, dump_dir=tmp_path / "dom")
        page = session.page
        assert page.is_checked("#cat-placement-small-town-rural") and page.is_checked("#cat-placement-friendship") and page.is_checked("#cat-placement-feel-good")
        assert not page.is_checked("#cat-placement-short-stories")
        assert not page.is_visible("#categories-modal")  # saved and closed
    finally:
        session.close()
    assert result.status == "aborted"
    assert all(f"category:{c}" in result.filled for c in book.metadata.categories)
    assert (tmp_path / "dom" / "dom-categories.md").is_file()
    store.close()

