"""The local web UI, driven through Flask's test client (no server, no browser)."""

from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

from kdp_studio.ui.app import create_app, discover_books  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    # keep the queue/store writes out of the real publishing/ folder
    monkeypatch.setattr("kdp_studio.ui.app.data_path", lambda *parts: tmp_path.joinpath(*parts))
    app = create_app([ROOT / "examples"])
    app.config["TESTING"] = True
    return app.test_client()


def test_discover_books_reads_both_examples():
    books = discover_books([ROOT / "examples"])
    ids = {b.get("id") for b in books}
    assert {"co-bold-easy-flowers-001", "st-lantern-lane-001"} <= ids or len(books) >= 2
    flowers = next(b for b in books if b.get("type") == "coloring")
    assert flowers["drawings"] >= 3 and flowers["provider"] in {"placeholder", "spec", "local"}


def test_pages_render_and_queue_selection_works(client):
    for url in ("/", "/queue", "/runs", "/license", "/book/0", "/book/1?fmt=ebook"):
        r = client.get(url)
        assert r.status_code == 200, url
    html = client.get("/").get_data(as_text=True)
    assert "Quota KDP" in html and "API key" in html
    books = discover_books([ROOT / "examples"])
    paths = [b["path"] for b in books if not b.get("error")]
    r = client.post("/queue/add", data={"books": paths, "fmt": "paperback", "priority": "2"}, follow_redirects=True)
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert "Đang chờ (2)" in page or "Đang chờ (1)" in page
    assert client.get("/jobs/nope").status_code == 404
    assert client.get("/file?p=C:/Windows/win.ini").status_code in (403, 404)
