"""The create-form "Gợi ý" engine: offline library, validation of model output, engine fallback."""

from kdp_studio import suggest as sg
from kdp_studio.themes import THEMES, find_theme


def test_find_theme_handles_typos_titles_and_unknowns():
    assert find_theme("ocenan")["key"] == "ocean"
    assert find_theme("Ocean Animals Coloring Book")["key"] == "ocean"
    assert find_theme("bold and easy sea creatures")["key"] == "ocean"
    assert find_theme("cats")["key"] == "cats"
    assert find_theme("vintage robots") is None and find_theme("") is None


def test_library_is_clean():
    for key, rec in THEMES.items():
        assert len(rec["subjects"]) == 30 and len({s.lower() for s in rec["subjects"]}) == 30, key
        assert len(rec["keywords"]) == 7 and all(len(k) <= 50 for k in rec["keywords"]), key
        assert not any(sg.PEOPLE.search(s) for s in rec["subjects"]), (key, [s for s in rec["subjects"] if sg.PEOPLE.search(s)])


def test_offline_fills_everything_around_typed_values():
    r = sg.suggest({"folder": "ocenan", "images": "30"}, engine="offline")
    f = r["fields"]
    assert r["source"] == "offline" and f["folder"] == "ocenan"  # typed values are anchors
    assert f["title"] == "Ocean Animals Coloring Book" and f["subtitle"] == "30 Bold and Easy Sea Creatures for Adults and Kids" and f["author"]
    assert f["theme"] == "bold and easy ocean animals" and f["audience"] == sg.DEFAULT_AUDIENCE
    assert len(f["keywords"].split(", ")) == 7 and len(f["subjects"].splitlines()) == 30
    r2 = sg.suggest({"folder": "ocenan", "title": "Ocean Animals"}, overwrite=True, engine="offline")
    assert r2["fields"]["folder"] == "ocean-animals" and r2["fields"]["title"] == "Ocean Animals Coloring Book"


def test_offline_unknown_theme_keeps_partial_lists_first():
    r = sg.suggest({"theme": "vintage robots", "images": "12", "subjects": "a robot watering flowers\na robot with a kite", "keywords": "robot coloring book"}, engine="offline")
    subs = r["fields"]["subjects"].splitlines()
    assert len(subs) == 12 and subs[:2] == ["a robot watering flowers", "a robot with a kite"] and all("vintage robots" in s for s in subs[2:])
    kws = r["fields"]["keywords"].split(", ")
    assert kws[0] == "robot coloring book" and len(kws) == 7 and len(set(kws)) == 7
    assert r["fields"]["title"] == "Vintage Robots Coloring Book" and r["fields"]["folder"] == "vintage-robots"


def test_more_pages_than_subjects_get_numbered_variations():
    subs = sg.clean_subjects(["a whale", "a crab"], 5, [])
    assert subs == ["a whale", "a crab", "a whale (variation 2)", "a crab (variation 2)", "a whale (variation 3)"]


def test_llm_output_is_validated(monkeypatch):
    fake = {"folder": "Ocean Animals!!", "title": "Ocean Animals Coloring Book", "subtitle": "x", "author": "A B", "theme": "ocean animals", "audience": "kids",
            "keywords": ["Ocean Coloring Book", "ocean coloring book", "k" * 60, "kw1", "kw2", "kw3"],
            "subjects": ["a mermaid waving", "a whale", "A whale", "a crab on the beach."]}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(sg, "_claude", lambda *a, **k: (fake, "claude-test"))
    r = sg.suggest({"images": "6"}, engine="claude")
    f = r["fields"]
    assert r["source"] == "claude" and r["source_label"] == "Claude (claude-test)" and f["folder"] == "ocean-animals"
    kws = f["keywords"].split(", ")
    assert len(kws) == 7 and kws[0] == "ocean coloring book" and all(len(k) <= 50 for k in kws) and len(set(kws)) == 7
    subs = f["subjects"].splitlines()
    assert len(subs) == 6 and subs[:2] == ["a whale", "a crab on the beach"] and "a mermaid waving" not in subs
    assert all(s in THEMES["ocean"]["subjects"] for s in subs[2:])  # topped up from the theme the model chose, not from the default


def test_engine_failures_fall_back_to_offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")

    def boom(*a, **k):
        raise sg.SuggestError("HTTP 401: bad key")

    monkeypatch.setattr(sg, "_claude", boom)
    monkeypatch.setattr(sg, "_cloudflare", boom)
    r = sg.suggest({"theme": "cats"}, engine="auto")
    assert r["source"] == "offline" and any(n.startswith("Claude: HTTP 401") for n in r["notes"]) and any(n.startswith("Cloudflare:") for n in r["notes"])
    assert r["fields"]["title"] == "Cats Coloring Book"


def test_parse_json_object_tolerates_fences_and_trailing_commas():
    assert sg.parse_json_object('Sure! ```json\n{"a": 1, "b": [1, 2,],}\n```')["a"] == 1
    assert sg.parse_json_object("no json here") is None and sg.parse_json_object("[1, 2]") is None
