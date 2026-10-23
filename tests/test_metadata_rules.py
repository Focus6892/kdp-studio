from kdp_studio.metadata_rules import validate_metadata
from kdp_studio.schema import Metadata


def _md(**over):
    base = dict(
        title="Bold & Easy Flowers",
        subtitle="Large Print Coloring Book for Adults",
        author="Mia Hartwell",
        description_html="<p>Thirty bold designs.</p>",
        keywords=["large print coloring book", "easy coloring adults"],
        categories=["Crafts & Hobbies > Coloring Books for Grown-Ups"],
    )
    base.update(over)
    return Metadata(**base)


def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level == level}


def test_clean_metadata_has_no_errors():
    assert validate_metadata(_md(), "coloring").ok


def test_banned_words_in_title_are_errors():
    f = validate_metadata(_md(title="Bestselling Free Flowers"), "coloring")
    assert "title.banned_word" in codes(f, "error")


def test_title_length_limit():
    f = validate_metadata(_md(subtitle="x" * 200), "coloring")
    assert "title.length" in codes(f, "error")


def test_generic_keyword_repetition_warns():
    f = validate_metadata(_md(title="Notebook Journal Notebook", subtitle=None), "coloring")
    assert "title.generic_repeat" in codes(f, "warning")


def test_description_rules():
    f = validate_metadata(_md(description_html="<p>Visit www.example.com or email me at a@b.com. 5 stars! Only $4.99 <script>x</script></p>"), "coloring")
    c = codes(f)
    assert {"description.url", "description.email", "description.html_tag"} <= codes(f, "error")
    assert {"description.review", "description.price"} <= codes(f, "warning")
    assert "script" not in c


def test_keyword_rules():
    f = validate_metadata(_md(keywords=["free coloring book", "a" * 60, "large print coloring book", "large print coloring book"]), "coloring")
    assert {"keywords.banned_word", "keywords.length"} <= codes(f, "error")
    assert "keywords.duplicate" in codes(f, "warning")


def test_low_content_flag_on_coloring_book_is_error():
    f = validate_metadata(_md(low_content=True), "coloring")
    assert "low_content.coloring" in codes(f, "error")


def test_childrens_category_without_reading_age_warns():
    f = validate_metadata(_md(categories=["Children's Books > Activities, Crafts & Games"]), "coloring")
    assert "reading_age.missing" in codes(f, "warning")
    f2 = validate_metadata(_md(categories=["Children's Books > Activities"], reading_age={"min": 4, "max": 8}), "coloring")
    assert "reading_age.missing" not in codes(f2)
