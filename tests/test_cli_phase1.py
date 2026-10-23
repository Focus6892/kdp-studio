import shutil
from pathlib import Path

from kdp_studio.cli import main
from kdp_studio.schema import load_book

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "examples" / "bold-easy-flowers"


def test_cli_niche_run_trends_concepts(tmp_path, capsys):
    db = tmp_path / "db.sqlite"
    rc = main(["niche", "run", "--topic", "bold and easy flowers coloring book", "--topic", "cats coloring book for kids", "--source", "fixture", "--no-claude", "--out", str(tmp_path), "--db", str(db), "--concepts", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "| # | Keyword |" in out and "Concept cards for" in out
    assert main(["niche", "trends", "--db", str(db)]) == 0
    assert main(["niche", "concepts", "--keyword", "cats coloring book for kids", "--db", str(db), "--no-claude", "--n", "3", "--out", str(tmp_path / "cards.json")]) == 0
    assert (tmp_path / "cards.json").is_file()
    assert main(["niche", "expand", "--topic", "flowers", "--no-claude", "--max", "5"]) == 0


def test_cli_metadata_generate_and_apply(tmp_path):
    book_copy = tmp_path / "book.yaml"
    shutil.copyfile(EXAMPLE_DIR / "book.yaml", book_copy)
    rc = main(["metadata", "generate", "--brief", str(EXAMPLE_DIR / "brief.yaml"), "--no-claude", "--n", "3", "--out", str(tmp_path / "meta")])
    assert rc == 0
    rc = main(["metadata", "apply", "--book", str(book_copy), "--candidates", str(tmp_path / "meta" / "candidates.json"), "--pick", "2"])
    assert rc == 0
    assert load_book(book_copy).metadata.title
