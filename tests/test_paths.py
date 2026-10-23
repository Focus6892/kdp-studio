from pathlib import Path

from kdp_studio.cli import main
from kdp_studio.paths import project_root, resolve_input

ROOT = Path(__file__).resolve().parents[1]


def test_project_root_is_the_repo():
    assert project_root() == ROOT


def test_resolve_input_falls_back_to_project_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # like running from C:\Users\<me>
    found = resolve_input("examples/lantern-lane/book.yaml")
    assert found.is_file() and found == ROOT / "examples" / "lantern-lane" / "book.yaml"
    local = tmp_path / "book.yaml"
    local.write_text("x", encoding="utf-8")
    assert resolve_input("book.yaml") == Path("book.yaml")  # CWD wins when the file exists there
    assert resolve_input("nope/book.yaml") == Path("nope/book.yaml")  # unknown paths are left alone


def test_cli_reports_missing_book_clearly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["validate", "examples/does-not-exist/book.yaml"]) == 2
    err = capsys.readouterr().err
    assert "book file not found" in err and "does-not-exist" in err
    assert main(["validate", "examples/lantern-lane/book.yaml"]) == 0
