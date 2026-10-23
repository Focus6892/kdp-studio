"""End-to-end: example book.yaml -> interior PDF + cover PDF + eBook JPEG -> preflight passes."""

from pathlib import Path

import yaml
from PIL import Image
from pypdf import PdfReader

from kdp_studio.cover.geometry import cover_geometry
from kdp_studio.cover.render import render_cover
from kdp_studio.interior.pipeline import build_coloring_interior
from kdp_studio.preflight.run import run_preflight
from kdp_studio.schema import Book

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "bold-easy-flowers" / "book.yaml"


def test_full_build_passes_preflight(tmp_path):
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["interior"]["images"] = 10
    data["interior"]["dedupe"]["library"] = str(tmp_path / "hashes.json")
    data["output_dir"] = str(tmp_path / "build")
    book = Book.model_validate(data)
    book.source_path = EXAMPLE

    interior = build_coloring_interior(book)
    # 4 front + 10 images x 2 (single-sided) + 2 back = 26 pages
    assert interior.total_pages == 26
    assert interior.image_pages == 10
    assert len(PdfReader(str(interior.pdf_path)).pages) == 26

    cover = render_cover(book, interior.total_pages)
    geo = cover_geometry("8.5x11", 26, "white_bw")
    page = PdfReader(str(cover.pdf_path)).pages[0]
    assert abs(float(page.mediabox.width) - geo.width_in * 72) < 0.5
    assert abs(float(page.mediabox.height) - geo.height_in * 72) < 0.5
    assert not cover.spine_text_drawn  # 26 pages < 79

    with Image.open(cover.ebook_jpg) as im:
        assert im.size == (1600, 2560) and im.mode == "RGB"

    report = run_preflight(book, interior.total_pages, interior.pdf_path, cover.pdf_path, cover.ebook_jpg)
    assert report.ok, [f.message for f in report.findings.errors]
    assert (tmp_path / "build" / "preflight.md").is_file()
    assert (tmp_path / "hashes.json").is_file()

    disclosure = book.ai_disclosure()
    assert disclosure["Images"].startswith("AI-generated")
    assert disclosure["Text"] == "None"
