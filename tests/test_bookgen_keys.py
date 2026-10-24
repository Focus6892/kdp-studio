from pathlib import Path

from kdp_studio import keys as keymod
from kdp_studio.bookgen import new_coloring_book
from kdp_studio.schema import load_book


def test_new_coloring_book_writes_a_valid_project(tmp_path):
    path = new_coloring_book(tmp_path, "ocean-animals", "Ocean Animals Coloring Book", "Mia Hartwell", "bold and easy ocean animals",
                             subtitle="30 Sea Creatures", images=24, subjects=["a smiling whale", "a sea turtle"], provider="local")
    book = load_book(path)
    assert book.id == "cb-ocean-animals-001" and book.interior.images == 24 and book.interior.subjects == ["a smiling whale", "a sea turtle"]
    assert book.interior.source.provider == "local" and book.interior.source.lora and "ColoringBookAF" in book.interior.style_prompt
    assert book.provenance.interior_images == "ai_generated" and book.provenance.ai_tools
    assert len(book.metadata.keywords) == 7 and all(len(k) <= 50 for k in book.metadata.keywords)
    spec = new_coloring_book(tmp_path, "mandalas", "Mandalas", "A. Author", "bold mandalas", provider="spec")
    assert (spec.parent / "drawings").is_dir() and load_book(spec).interior.source.path == "drawings"
    for bad in ({"folder": "Ocean Animals"}, {"folder": "ocean-animals"}, {"folder": "x", "provider": "nope"}):
        try:
            new_coloring_book(tmp_path, bad.get("folder", "ok-name"), "T", "A", "theme", provider=bad.get("provider", "placeholder"))
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad}")


def test_keys_env_roundtrip_and_masking(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# keys\nOPENAI_API_KEY=old\nSOMETHING_ELSE=1\n", encoding="utf-8")
    monkeypatch.setattr(keymod, "env_path", lambda: env)
    for v in keymod.ALL_VARS:
        monkeypatch.delenv(v, raising=False)
    written = keymod.save_env({"OPENAI_API_KEY": "sk-new-value-1234", "CF_API_TOKEN": "cf-token-abcdef", "BOGUS": "x", "GEMINI_API_KEY": ""})
    assert written == ["OPENAI_API_KEY", "CF_API_TOKEN"]
    text = env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-new-value-1234" in text and "SOMETHING_ELSE=1" in text and "BOGUS" not in text and "# keys" in text
    assert keymod.read_env(env)["CF_API_TOKEN"] == "cf-token-abcdef"
    assert keymod.mask("sk-new-value-1234") == "sk-…1234" and keymod.mask("short") == "short" and keymod.mask("") == ""
    table = {p["id"]: p for p in keymod.status_table()}
    assert table["openai"]["present"]["OPENAI_API_KEY"] is True and table["openai"]["masked"]["OPENAI_API_KEY"] == "sk-…1234"
    assert table["cloudflare"]["present"]["CF_ACCOUNT_ID"] is False and table["cloudflare"]["url"].startswith("https://")
    assert keymod.check("spec") == {"ok": True, "detail": "không cần key"}
    assert keymod.check("stability")["ok"] is False and "thiếu" in keymod.check("stability")["detail"]
    assert keymod.check("nope")["ok"] is False
