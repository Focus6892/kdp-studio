import shutil
from pathlib import Path

from kdp_studio.metadata.apply import apply_candidate
from kdp_studio.metadata.brief import Brief, load_brief
from kdp_studio.metadata.generate import MetadataCandidate, generate_candidates, validate_candidate
from kdp_studio.metadata.report import write_candidates
from kdp_studio.metadata.score import score_candidate
from kdp_studio.schema import load_book

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "examples" / "bold-easy-flowers"


def test_template_candidates_are_kdp_compliant():
    brief = load_brief(EXAMPLE_DIR / "brief.yaml")
    scored = generate_candidates(brief, n=5, use_claude=False)
    assert len(scored) == 5
    assert all(not sc.findings.errors for sc in scored)
    assert scored[0].score >= 60
    for sc in scored:
        c = sc.candidate
        assert len(c.title) + len(c.subtitle or "") + 2 < 200
        assert len(c.keywords) == 7 and len(c.categories) == 3
        assert all(len(k) <= 50 for k in c.keywords)


def test_rubric_penalizes_rule_violations():
    brief = Brief(niche_keyword="flowers coloring book", audience="adults")
    clean = MetadataCandidate(title="Garden Flowers", subtitle="A Calm Coloring Book for Adults with 30 Easy Designs", description_html="<h4>Relax</h4><p>" + "Thirty easy designs. " * 30 + "</p><ul><li>Single-sided</li></ul>", keywords=["easy coloring adults", "garden coloring pages", "relaxing coloring book", "simple flower designs", "stress relief coloring", "large print coloring", "coloring gift women"], categories=["a", "b", "c"])
    bad = clean.model_copy(update={"title": "Free Bestselling Garden Flowers", "description_html": "<p>Visit www.example.com</p>"})
    s_clean, _ = score_candidate(clean, brief, validate_candidate(clean, brief))
    s_bad, b = score_candidate(bad, brief, validate_candidate(bad, brief))
    assert s_clean > s_bad and b["compliance"] < 40


def test_brief_kid_detection():
    assert Brief(niche_keyword="x", audience="kids ages 4-8").is_for_kids
    assert not Brief(niche_keyword="x", audience="adults and seniors").is_for_kids


def test_apply_preserves_comments_and_other_fields(tmp_path):
    book_copy = tmp_path / "book.yaml"
    shutil.copyfile(EXAMPLE_DIR / "book.yaml", book_copy)
    brief = load_brief(EXAMPLE_DIR / "brief.yaml")
    scored = generate_candidates(brief, n=2, use_claude=False)
    backup = apply_candidate(book_copy, scored[1].candidate, author="Mia Hartwell")
    assert backup is not None and backup.is_file()
    text = book_copy.read_text(encoding="utf-8")
    assert "# KDP: coloring books are NOT low-content" in text  # ruamel round-trip keeps comments
    book = load_book(book_copy)
    assert book.metadata.title == scored[1].candidate.title
    assert book.metadata.keywords == scored[1].candidate.keywords
    assert book.print_.trim == "8.5x11" and book.interior.images == 30 and book.pricing.list_price == 9.99


def test_write_candidates(tmp_path):
    brief = load_brief(EXAMPLE_DIR / "brief.yaml")
    scored = generate_candidates(brief, n=3, use_claude=False)
    paths = write_candidates(scored, brief, tmp_path)
    assert paths["json"].is_file() and paths["markdown"].is_file()
    assert scored[0].candidate.title in paths["markdown"].read_text(encoding="utf-8")
