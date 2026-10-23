import pytest

from kdp_studio.story import draft
from kdp_studio.story.draft import Character, ChapterDraft, ChapterPlan, Outline, StoryBible, StoryBrief, draft_story


def _fake_parse(system, user, output_model, model="x", max_tokens=0):
    if output_model is StoryBible:
        return StoryBible(title="T", logline="L", characters=[Character(name="A", role="lead", description="d", voice="v")], settings=["s"], themes=["t"], style_guide="short sentences")
    if output_model is Outline:
        return Outline(chapters=[ChapterPlan(number=i, title=f"Plan {i}", summary="s", beats=["b1", "b2"], target_words=300) for i in (1, 2, 3)])
    if output_model is ChapterDraft:
        return ChapterDraft(title="Drafted Title", markdown='"Hello," she said.\n\n***\n\nAnd then it rained.')
    raise AssertionError(output_model)


def test_draft_story_writes_manuscript(tmp_path, monkeypatch):
    monkeypatch.setattr(draft, "parse_structured", _fake_parse)
    brief = StoryBrief(premise="A mailbox that answers letters in a small river town.", chapters=2)
    res = draft_story(brief, tmp_path / "ms", polish=True, progress=lambda m: None)
    assert len(res.chapter_files) == 2  # brief.chapters caps the outline
    assert res.bible_path.is_file() and res.outline_path.is_file() and (tmp_path / "ms" / "PROVENANCE.md").is_file()
    text = res.chapter_files[0].read_text(encoding="utf-8")
    assert text.startswith("# Drafted Title") and "***" in text
    assert res.words > 0


def test_draft_story_requires_claude(tmp_path, monkeypatch):
    monkeypatch.setattr(draft, "parse_structured", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        draft_story(StoryBrief(premise="Something long enough to pass."), tmp_path / "ms", progress=lambda m: None)
