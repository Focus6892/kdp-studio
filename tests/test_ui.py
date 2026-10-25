"""The local web UI, driven through Flask's test client (no server, no browser)."""

import json
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


def test_create_suggest_route(client):
    r = client.post("/create/suggest", json={"folder": "ocenan", "images": 24, "overwrite": False})
    assert r.status_code == 200
    d = r.get_json()
    assert d["source"] == "offline" and d["fields"]["folder"] == "ocenan" and d["fields"]["title"] == "Ocean Animals Coloring Book"
    assert len(d["fields"]["subjects"].splitlines()) == 24 and len(d["fields"]["keywords"].split(", ")) == 7


def test_settings_backup_accounts_and_unblock(client, tmp_path, monkeypatch):
    monkeypatch.setattr("kdp_studio.interior.failover.state_path", lambda: tmp_path / "state.json")
    for v in ("CF_ACCOUNT_ID_2", "CF_API_TOKEN_2"):
        monkeypatch.delenv(v, raising=False)
    html = client.get("/settings").get_data(as_text=True)
    assert "Thêm tài khoản dự phòng" in html and "Chuỗi dự phòng" in html
    r = client.post("/settings/save", data={"CF_ACCOUNT_ID_2": "acc-two", "CF_API_TOKEN_2": "tok-two-abcdef"}, follow_redirects=True)
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "Tài khoản 2" in page and "tok…cdef" in page and "tok-two" not in page
    assert client.post("/settings/check/cloudflare?n=3").get_json()["detail"].startswith("thiếu")
    assert client.post("/settings/unblock", data={"profile": "cloudflare#2"}).status_code == 302
    r = client.post("/settings/remove", data={"provider": "cloudflare", "n": "2"}, follow_redirects=True)
    assert r.status_code == 200 and "Tài khoản 2" not in r.get_data(as_text=True)
    assert client.post("/settings/remove", data={"provider": "cloudflare", "n": "1"}).status_code == 400


def test_build_job_page_shows_the_book_progress(client):
    import sys

    jobs = client.application.extensions["jobs"]
    job_id = jobs.start("build test", [sys.executable, "-c", "print('hello')"], book_idx=0)
    html = client.get(f"/jobs/{job_id}").get_data(as_text=True)
    assert "Tiến trình tạo ruột" in html and "/book/0/progress" in html
    plain = jobs.start("image-test", [sys.executable, "-c", "print('x')"])
    assert "Tiến trình tạo ruột" not in client.get(f"/jobs/{plain}").get_data(as_text=True)


def test_add_pick_remove_book_dirs_and_open_folder(client, tmp_path, monkeypatch):
    import kdp_studio.ui.app as app_module
    from kdp_studio.bookgen import new_coloring_book

    ext = tmp_path / "elsewhere"
    new_coloring_book(ext, "ext-book", "External Book", "Mia", "cats", provider="placeholder", subjects=["a cat"])
    r = client.post("/books/add-dir", data={"path": str(ext)}, follow_redirects=True)
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "External Book" in page and "Đã thêm" in page and "1 sách" in page
    saved = tmp_path / "state" / "book_dirs.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == [str(ext.resolve())]  # remembered for the next start
    client.post("/books/add-dir", data={"path": str(ext)})  # same folder again is not duplicated
    assert json.loads(saved.read_text(encoding="utf-8")) == [str(ext.resolve())]
    assert "không có book.yaml" in client.post("/books/add-dir", data={"path": str(tmp_path)}, follow_redirects=True).get_data(as_text=True)
    other = tmp_path / "picked"
    new_coloring_book(other, "picked-book", "Picked Book", "Mia", "dogs", provider="placeholder", subjects=["a dog"])
    monkeypatch.setattr(app_module, "_pick_folder", lambda: str(other))  # the native dialog is stubbed
    assert "Picked Book" in client.post("/books/pick-dir", follow_redirects=True).get_data(as_text=True)
    opened = []
    monkeypatch.setattr(app_module, "_open_in_file_manager", lambda p: opened.append(Path(p)))
    books = discover_books([ROOT / "examples", ext, other])
    idx = next(i for i, b in enumerate(books) if b.get("id") == "cb-ext-book-001")
    assert client.post(f"/book/{idx}/open-folder").status_code == 302 and opened[0].resolve() == (ext / "ext-book").resolve()
    queue_page = client.get("/queue").get_data(as_text=True)
    assert f"/book/{idx}" in queue_page and "mở trang sách" in queue_page
    r = client.post("/books/remove-dir", data={"path": str(ext)}, follow_redirects=True)
    assert "External Book" not in r.get_data(as_text=True) and "Picked Book" in r.get_data(as_text=True)
    assert "mặc định" in client.post("/books/remove-dir", data={"path": str(ROOT / "examples")}, follow_redirects=True).get_data(as_text=True)



def test_create_story_book_and_draft_job(client, tmp_path, monkeypatch):
    import sys

    page = client.get("/create?kind=story").get_data(as_text=True)
    assert 'name="premise"' in page and "Truyện chữ + eBook" in page
    s = client.post("/create/suggest", json={"kind": "story", "folder": "harbour-parrot", "genre": "cozy mystery", "chapters": 6})
    assert s.status_code == 200 and s.get_json()["kind"] == "story" and len(s.get_json()["fields"]["outline"].splitlines()) == 6
    form = {"folder": "harbour-parrot", "title": "A Parrot Never Lies", "author": "Rosie Whitfield", "genre": "cozy mystery", "chapters": "4", "words_per_chapter": "1200",
            "premise": "A bakery owner clears a friend's name after a theft at the harbour fair, with a parrot as the only witness.", "formats": ["paperback", "ebook"],
            "trim": "5x8", "price": "9.99", "ebook_price": "2.99", "outline": "The Fair: Nell sees the theft."}
    r = client.post("/create/story", data=form, follow_redirects=True)
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "A Parrot Never Lies" in page and "Viết nháp các chương" in page and "The Fair" in page and "0/4 chương" in page
    book_dir = tmp_path / "books" / "harbour-parrot"
    assert (book_dir / "book.yaml").is_file() and (book_dir / "story_brief.yaml").is_file() and len(list((book_dir / "manuscript" / "chapters").glob("*.md"))) == 4
    idx = int(r.request.path.rsplit("/", 1)[1])
    prog = client.get(f"/book/{idx}/story-progress").get_json()
    assert prog == {"drafted": 0, "total": 4, "words": 0, "running": False, "last": None, "pdf": None, "epub": None, "cover": None}
    home = client.get("/").get_data(as_text=True)
    assert "A Parrot Never Lies" in home and "4 chương" in home
    jobs = client.application.extensions["jobs"]
    real = jobs.start("viết nháp harbour-parrot", [sys.executable, "-c", "print('hi')"], book_idx=idx)
    job_page = client.get(f"/jobs/{real}").get_data(as_text=True)
    assert "Tiến trình viết nháp" in job_page and f"/book/{idx}/story-progress" in job_page and "Tiến trình tạo ruột" not in job_page
    started = []
    monkeypatch.setattr(jobs, "start", lambda title, cmd, book_idx=None: started.append((title, cmd, book_idx)) or "job-x")
    r = client.post(f"/book/{idx}/draft", data={"polish": "1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/jobs/job-x")
    title, cmd, bidx = started[0]
    assert title == "viết nháp harbour-parrot" and bidx == idx and "draft" in cmd
    assert cmd[-5:] == ["--brief", str(book_dir / "story_brief.yaml"), "--out", str(book_dir / "manuscript"), "--polish"]
    r = client.post("/create/story", data={**form, "folder": "second-story", "draft_now": "1"})  # create + draft in one go
    assert r.status_code == 302 and r.headers["Location"].endswith("/jobs/job-x") and started[-1][0] == "viết nháp second-story"
    r = client.post("/create/story", data={**form, "folder": "Bad Folder"})  # the error re-renders the story tab with the typed values
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "Bad Folder" in page and 'name="premise"' in page and "Nell sees the theft" in page
