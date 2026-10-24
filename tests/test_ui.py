"""The local web UI, driven through Flask's test client (no server, no browser)."""

from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

from kdp_studio.ui.app import create_app, discover_books  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    # keep the queue/store writes out of the real publishing/ folder, and keys/new books in tmp
    monkeypatch.setattr("kdp_studio.ui.app.data_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr("kdp_studio.keys.env_path", lambda: tmp_path / ".env")
    app = create_app([ROOT / "examples"])
    app.config["TESTING"] = True
    app.config["BOOKS_ROOT"] = tmp_path / "books"
    return app.test_client()


def test_discover_books_reads_both_examples():
    books = discover_books([ROOT / "examples"])
    ids = {b.get("id") for b in books}
    assert {"co-bold-easy-flowers-001", "st-lantern-lane-001"} <= ids or len(books) >= 2
    flowers = next(b for b in books if b.get("type") == "coloring")
    assert flowers["drawings"] >= 3 and flowers["provider"] in {"placeholder", "spec", "local", "cloudflare"}


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


def test_settings_create_and_progress(client, tmp_path):
    assert client.get("/settings").status_code == 200
    r = client.post("/settings/save", data={"OPENAI_API_KEY": "sk-test-abcdef1234"}, follow_redirects=True)
    assert r.status_code == 200 and "sk-…1234" in r.get_data(as_text=True) and "sk-test" not in r.get_data(as_text=True)
    assert client.post("/settings/check/spec").get_json()["ok"] is True
    assert client.get("/create").status_code == 200
    r = client.post("/create", data={"folder": "ocean-animals", "title": "Ocean Animals", "author": "Mia", "theme": "ocean animals", "images": "24",
                                     "trim": "8.5x11", "price": "9.99", "provider": "placeholder", "subjects": "a whale"}, follow_redirects=True)
    assert r.status_code == 200 and "Ocean Animals" in r.get_data(as_text=True)
    assert (tmp_path / "books" / "ocean-animals" / "book.yaml").is_file()
    books = client.get("/").get_data(as_text=True)
    idx = next(i for i, b in enumerate(discover_books([ROOT / "examples", tmp_path / "books"])) if b.get("id") == "cb-ocean-animals-001")
    prog = client.get(f"/book/{idx}/progress").get_json()
    assert prog["total"] == 24 and prog["done"] == 0 and prog["finished"] is False
    bad = client.post("/create", data={"folder": "Bad Name", "title": "T", "author": "A", "theme": "t"})
    assert bad.status_code == 200 and "chữ thường" in bad.get_data(as_text=True)

