"""Tạo sách for text books: the project generator, story suggestions and the free Workers AI fallback of the LLM helper."""

import json

import pytest
import yaml
from pydantic import BaseModel

from kdp_studio import llm
from kdp_studio import suggest as sg
from kdp_studio.bookgen import manuscript_stats, new_story_book, skeleton_outline, story_category
from kdp_studio.schema import load_book
from kdp_studio.story.draft import StoryBrief
from kdp_studio.suggest_story import clean_outline, family

PREMISE = "A bakery owner clears a friend's name after a theft at the harbour fair, with a parrot as the only witness."


def test_new_story_book_writes_project_brief_and_skeleton(tmp_path):
    p = new_story_book(tmp_path, "harbour-parrot", "A Parrot Never Lies", "Rosie Whitfield", "cozy mystery", PREMISE, chapters=6,
                       outline=["The Fair: Nell sees the theft.", "2. Feathers: the parrot talks"], ebook_price=3.49)
    b = load_book(p)
    assert b.type == "story" and b.formats == ["paperback", "ebook"] and b.pricing.ebook_list_price == 3.49 and b.print_.trim == "5x8"
    assert b.provenance.text == "ai_generated" and b.provenance.ai_tools and b.metadata.categories == ["Mystery, Thriller & Suspense > Mystery > Cozy"]
    files = sorted(f.name for f in (p.parent / "manuscript" / "chapters").glob("*.md"))
    assert files == ["01-the-fair.md", "02-feathers.md", "03-first-steps.md", "04-what-the-town-knows.md", "05-the-long-night.md", "06-lanterns.md"]
    st = manuscript_stats(p.parent)
    assert st["total"] == 6 and st["drafted"] == 0 and st["words"] == 0 and all(c["skeleton"] for c in st["chapters"]) and st["chapters"][1]["title"] == "Feathers"
    brief = yaml.safe_load((p.parent / "story_brief.yaml").read_text(encoding="utf-8"))
    assert brief["chapters"] == 6 and brief["title_hint"] == "A Parrot Never Lies" and "1. The Fair" in brief["extra_notes"]
    StoryBrief.model_validate(brief)
    (p.parent / "manuscript" / "chapters" / "01-the-fair.md").write_text("# The Fair\n\n" + "word " * 300, encoding="utf-8")  # a hand-written chapter
    st = manuscript_stats(p.parent)
    assert st["drafted"] == 1 and st["words"] == 300 and not st["chapters"][0]["skeleton"]
    with pytest.raises(ValueError):
        new_story_book(tmp_path, "harbour-parrot", "Again", "Rosie", "cozy mystery", PREMISE)
    with pytest.raises(ValueError):
        new_story_book(tmp_path, "Bad Folder", "Title", "Rosie", "cozy mystery", PREMISE)
    human = load_book(new_story_book(tmp_path, "by-hand", "By Hand", "Rosie", "sweet romance", PREMISE, draft_ai=False, formats=["ebook"], trim="6x9"))
    assert human.provenance.text == "human" and human.provenance.ai_tools == [] and human.formats == ["ebook"] and human.metadata.categories == ["Romance > Clean & Wholesome"]


def test_skeleton_outline_and_categories():
    lines = skeleton_outline(12)
    assert len(lines) == 12 and len({ln.split(":")[0] for ln in lines}) == 12 and all(": " in ln for ln in lines)
    assert story_category("poetry") == "Literature & Fiction > Genre Fiction > Feel-Good" and story_category("Middle Grade adventure").startswith("Children's Books")
    assert family("a cozy mystery at the seaside") == "mystery" and family("young adult") == "children" and family("") == "cozy"
    assert clean_outline(["1. A: x", "A: y", "", "Chapter 2 - B"], 3) == ["A: x", "B", "An Ordinary Morning: Meet the main character in the ordinary world; a small detail hints that something is about to change."]


def test_story_suggest_offline_fills_everything_around_typed_values():
    r = sg.suggest({"kind": "story", "folder": "harbour-parrot", "genre": "cozy mystery", "chapters": "10"}, engine="offline")
    f = r["fields"]
    assert r["kind"] == "story" and r["source"] == "offline" and f["folder"] == "harbour-parrot" and f["title"] == "Harbour Parrot" and f["genre"] == "cozy mystery"
    assert "parrot" in f["premise"] and f["author"] and f["subtitle"] == "A Cozy Mystery" and len(f["keywords"].split(", ")) == 7
    outline = f["outline"].splitlines()
    assert len(outline) == 10 and len({ln.split(":")[0] for ln in outline}) == 10
    r2 = sg.suggest({"kind": "story", "title": "The Map That Remembered", "keywords": "fantasy adventure books",
                     "outline": "Chapter 1 - The Apprentice: Wren inks her first map.\n2. The Vanishing Road: a road disappears overnight"}, engine="offline")
    f2 = r2["fields"]
    ol = f2["outline"].splitlines()
    assert f2["folder"] == "the-map-that-remembered" and f2["genre"] == "fantasy" and f2["keywords"].startswith("fantasy adventure books") and len(ol) == 8
    assert ol[:2] == ["The Apprentice: Wren inks her first map.", "The Vanishing Road: a road disappears overnight"]
    r3 = sg.suggest({"kind": "story", "title": "Harbour", "genre": "cozy mystery"}, overwrite=True, engine="offline")
    assert r3["fields"]["title"] == "A Parrot Never Lies"  # typed values are only hints when overwriting


def test_story_suggest_validates_model_output(monkeypatch):
    monkeypatch.setattr(sg.keymod, "current_values", lambda: {"ANTHROPIC_API_KEY": "sk-test"})
    out = {"folder": "Snow Line!!", "title": "Snow Line", "subtitle": "A Thriller", "author": "Tess Alder", "genre": "thriller", "audience": "adults", "setting": "a lakeside hotel",
           "premise": "A night manager at a snowed-in hotel hunts the author of threatening notes.", "tone": "tense", "keywords": [f"keyword {i}" for i in range(10)],
           "outline": [f"Chapter {i}: Night {i}: the notes arrive" for i in range(1, 10)]}
    monkeypatch.setattr(sg, "_claude", lambda *a, **k: (out, "claude-test"))
    r = sg.suggest({"kind": "story", "chapters": 8}, engine="claude")
    f = r["fields"]
    assert r["source"] == "claude" and f["folder"] == "snow-line" and len(f["keywords"].split(", ")) == 7
    assert f["outline"].splitlines() == [f"Night {i}: the notes arrive" for i in range(1, 9)]


class Out(BaseModel):
    title: str
    n: int


def test_parse_structured_falls_back_to_workers_ai(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "claude_available", lambda: False)
    monkeypatch.setattr("kdp_studio.keys.profiles", lambda provider: [{"id": "cloudflare", "complete": True}] if provider == "cloudflare" else [])
    monkeypatch.setattr("kdp_studio.keys.profile_values", lambda pid: {"CF_ACCOUNT_ID": "acc", "CF_API_TOKEN": "tok"})
    monkeypatch.setattr("kdp_studio.interior.failover.state_path", lambda: tmp_path / "state.json")
    calls = []

    def fake_request(req, timeout=60, tries=2):
        calls.append(json.loads(req.data.decode("utf-8")))
        return json.dumps({"result": {"response": "Sure! ```json\n{\"title\": \"Snow Line\", \"n\": 3}\n```"}}).encode("utf-8")

    monkeypatch.setattr("kdp_studio.interior.generate._request", fake_request)
    assert llm.parse_structured("sys", "user", Out) == Out(title="Snow Line", n=3)
    assert "Cloudflare" in llm.last_engine() and "JSON schema" in calls[0]["messages"][0]["content"] and calls[0]["messages"][1]["content"] == "user"
    monkeypatch.setattr("kdp_studio.keys.profiles", lambda provider: [])
    assert llm.parse_structured("sys", "user", Out) is None  # nothing configured: None, no exception
