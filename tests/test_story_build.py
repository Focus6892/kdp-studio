import zipfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from kdp_studio.preflight.pdf_checks import check_interior_pdf
from kdp_studio.schema import load_book
from kdp_studio.story.epub import build_epub, validate_epub
from kdp_studio.story.manuscript import load_manuscript, md_to_html, split_title
from kdp_studio.story.print_pdf import build_print_pdf

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "lantern-lane" / "book.yaml"


def test_manuscript_loading():
    book = load_book(EXAMPLE)
    ms = load_manuscript(book)
    assert len(ms.chapters) == 6 and ms.chapters[0].number == 1
    assert ms.chapters[0].title == "The Blue Mailbox"
    assert "“" in ms.chapters[0].html  # smart quotes applied
    assert "&ldquo;" not in ms.chapters[0].html  # no HTML entities (invalid in EPUB 3)
    assert ms.words > 1500
    assert "dedication" in ms.extras and "about_author" in ms.extras and "review_cta" in ms.extras


def test_split_title_and_markdown_conversion():
    assert split_title("# Hello\n\nBody") == ("Hello", "Body")
    assert split_title("No heading\n\nBody")[0] is None
    html = md_to_html('She said "hi" -- then left...\n\n***\n\nNext *part*.')
    assert "“hi”" in html and "—" in html and "…" in html
    assert "<hr />" in html and "<em>part</em>" in html


def test_epub_build_and_validate(tmp_path):
    book = load_book(EXAMPLE)
    ms = load_manuscript(book)
    out = build_epub(book, ms, tmp_path / "t.epub", None)
    f = validate_epub(out)
    assert f.ok, [x.message for x in f.errors]
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert names[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        nav = z.read("OEBPS/nav.xhtml").decode("utf-8")
        assert "chapter-06.xhtml" in nav and "About the Author" in nav and "Letter 1:" in nav
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:language>en</dc:language>" in opf and "cover-image" not in opf
        assert "OEBPS/text/dedication.xhtml" in names


def test_epub_with_cover(tmp_path):
    book = load_book(EXAMPLE)
    ms = load_manuscript(book)
    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (1600, 2560), (30, 40, 70)).save(cover, "JPEG")
    out = build_epub(book, ms, tmp_path / "c.epub", cover)
    assert validate_epub(out).ok
    with zipfile.ZipFile(out) as z:
        assert "OEBPS/images/cover.jpg" in z.namelist()
        assert 'properties="cover-image"' in z.read("OEBPS/content.opf").decode("utf-8")


def test_validate_epub_catches_broken_package(tmp_path):
    bad = tmp_path / "bad.epub"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("META-INF/container.xml", "<container/>")
        z.writestr("mimetype", "application/epub+zip")
    f = validate_epub(bad)
    assert not f.ok and "epub.mimetype_order" in {x.code for x in f.errors}


def test_print_pdf_layout(tmp_path):
    book = load_book(EXAMPLE)
    ms = load_manuscript(book)
    res = build_print_pdf(book, ms, tmp_path / "interior.pdf")
    assert res.pages % 2 == 0 and res.pages >= 24
    assert res.chapter_pages and all(p % 2 == 1 for p in res.chapter_pages)  # chapters open on recto pages
    assert res.inside_margin_in >= 0.375
    reader = PdfReader(str(res.pdf_path))
    assert len(reader.pages) == res.pages
    mb = reader.pages[0].mediabox
    assert abs(float(mb.width) - 360) < 0.5 and abs(float(mb.height) - 576) < 0.5  # 5x8 in, no bleed
    findings, info = check_interior_pdf(res.pdf_path, book)
    assert findings.ok, [x.message for x in findings.errors]
    assert info and all(ft.embedded for p in info.pages for ft in p.fonts)
    assert not any("Helvetica" in ft.name for p in info.pages for ft in p.fonts)
    first_chapter_text = reader.pages[res.chapter_pages[0] - 1].extract_text()
    assert "Blue Mailbox" in first_chapter_text
    # blank verso pages carry no text at all
    for p in res.blank_pages:
        assert not reader.pages[p - 1].extract_text().strip()
    # front matter (title, copyright, dedication) has no page numbers or running heads
    for p in range(1, res.chapter_pages[0]):
        if p in res.blank_pages:
            continue
        lines = [l.strip() for l in reader.pages[p - 1].extract_text().splitlines() if l.strip()]
        assert str(p) not in lines, f"page number printed on front-matter page {p}"
        assert "JUNE ALDER" not in lines
    # a regular body page (the one after the first chapter opener) has the author running head and its number
    body = res.chapter_pages[0] + 1
    body_lines = [l.strip() for l in reader.pages[body - 1].extract_text().splitlines() if l.strip()]
    assert "JUNE ALDER" in body_lines and str(body) in body_lines
