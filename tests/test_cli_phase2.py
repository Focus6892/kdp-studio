import shutil
import zipfile
from pathlib import Path

from kdp_studio.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "examples" / "lantern-lane"


def test_cli_build_story_example(tmp_path, capsys):
    work = tmp_path / "lantern-lane"
    shutil.copytree(EXAMPLE_DIR, work)
    rc = main(["build", str(work / "book.yaml"), "--no-previewer"])
    out = capsys.readouterr().out
    assert rc == 0, out
    build = work / "build"
    epub = build / "st-lantern-lane-001.epub"
    assert (build / "interior.pdf").is_file() and (build / "cover_wrap.pdf").is_file() and epub.is_file()
    assert (build / "preflight.md").is_file() and (build / "story_manifest.json").is_file()
    with zipfile.ZipFile(epub) as z:
        assert "OEBPS/images/cover.jpg" in z.namelist()  # repackaged with the eBook cover
    assert "PASS" in out and "EPUB repackaged" in out
    assert main(["story", "check", str(work / "book.yaml"), "--no-previewer"]) == 0
    assert main(["validate", str(work / "book.yaml")]) == 0


def test_cli_watch_commands(tmp_path):
    wl = tmp_path / "watchlist.yaml"
    db = tmp_path / "w.sqlite"
    assert main(["watch", "add", "--watchlist", str(wl), "--asin", "B0TESTASN1", "--label", "A"]) == 0
    assert main(["watch", "add", "--watchlist", str(wl), "--asin", "B0TESTASN2", "--label", "Ours", "--ours"]) == 0
    assert main(["watch", "snapshot", "--watchlist", str(wl), "--source", "fixture", "--db", str(db), "--day", "0"]) == 0
    assert main(["watch", "snapshot", "--watchlist", str(wl), "--source", "fixture", "--db", str(db), "--day", "7"]) == 0
    assert main(["watch", "report", "--watchlist", str(wl), "--db", str(db), "--out", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "watch_report_latest.md").is_file()
    out_md = tmp_path / "insights.md"
    assert main(["watch", "insights", "--reviews", str(ROOT / "examples" / "reviews-sample.txt"), "--no-claude", "--out", str(out_md)]) == 0
    assert "Differentiation brief" in out_md.read_text(encoding="utf-8")
