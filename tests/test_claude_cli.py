"""Claude through the Claude Code CLI: the engine module, drawing specs with it, the LLM and suggest fallbacks, the UI job."""

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from kdp_studio import claude_cli, llm
from kdp_studio import suggest as sg
from kdp_studio.bookgen import new_coloring_book
from kdp_studio.interior import draw
from kdp_studio.schema import load_book

ROOT = Path(__file__).resolve().parents[1]
ENVELOPE = {"type": "result", "subtype": "success", "is_error": False, "result": "```json\n{\"title\": \"Big daisy\", \"n\": 3}\n```", "structured_output": None,
            "total_cost_usd": 0.0123, "duration_ms": 4200, "modelUsage": {"claude-sonnet-5-5[1m]": {"costUSD": 0.0123}},
            "usage": {"input_tokens": 2, "output_tokens": 95, "cache_creation_input_tokens": 1143, "cache_read_input_tokens": 0, "output_tokens_details": {"thinking_tokens": 40}}}
SPEC = {"title": "Big daisy", "canvas": [1000, 1500], "stroke": 14, "shapes": [
    {"type": "repeat", "count": 12, "center": [500, 650], "shapes": [{"type": "petal", "c": [500, 650], "r_inner": 120, "length": 330, "width": 160, "angle": -90}]},
    {"type": "circle", "c": [500, 650], "r": 120}, {"type": "curve", "points": [[500, 1100], [480, 1250], [510, 1420]]},
    {"type": "petal", "c": [490, 1250], "r_inner": 0, "length": 220, "width": 100, "angle": 200}]}


def fake_run_factory(envelope):
    calls = []

    def fake_run(cmd, input=None, **kw):
        calls.append({"cmd": cmd, "input": input, "env": kw.get("env")})
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(envelope), stderr="")

    return fake_run, calls


@pytest.fixture
def cli_on(monkeypatch):
    monkeypatch.delenv("KDP_STUDIO_NO_CLAUDE_CLI", raising=False)
    monkeypatch.setattr(claude_cli, "binary", lambda: "C:/fake/claude.exe")


def test_cli_run_parses_envelope_and_keeps_context_small(monkeypatch, cli_on):
    fake, calls = fake_run_factory(ENVELOPE)
    monkeypatch.setattr(claude_cli.subprocess, "run", fake)
    monkeypatch.setenv("CLAUDECODE", "1")
    res = claude_cli.run("hello", system="sys", schema={"type": "object"}, model="sonnet")
    assert res.model == "claude-sonnet-5-5" and res.output_tokens == 95 and res.cache_write == 1143 and res.thinking_tokens == 40 and res.cost_usd == 0.0123
    assert res.prompt_tokens == 1145 and "1,145 in" in res.summary()
    cmd = calls[0]["cmd"]
    assert calls[0]["input"] == "hello" and "--strict-mcp-config" in cmd and "--setting-sources" in cmd and "--system-prompt" in cmd and "--json-schema" in cmd and "sonnet" in cmd
    assert "CLAUDECODE" not in calls[0]["env"]  # also runs from inside a Claude Code session
    obj, _ = claude_cli.ask_json("hello")
    assert obj == {"title": "Big daisy", "n": 3}  # fenced JSON in the text when there is no structured output
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run_factory({**ENVELOPE, "is_error": True, "subtype": "error_max_turns", "result": "boom"})[0])
    with pytest.raises(claude_cli.CLIError):
        claude_cli.run("hello")


def test_draw_specs_writes_validated_drawings_and_log(tmp_path, monkeypatch):
    book = load_book(ROOT / "examples" / "bold-easy-flowers" / "book.yaml")
    answers = iter([{"title": "tiny", "shapes": [{"type": "circle", "c": [500, 700], "r": 30}]}, SPEC, SPEC])
    usage = {"engine": "cli", "model": "claude-sonnet-5-5", "input_tokens": 1200, "cached_tokens": 1000, "output_tokens": 800, "thinking_tokens": 0, "cost_usd": 0.01, "seconds": 5.0}
    prompts = []

    def fake_call(system, user, model):
        prompts.append(user)
        return json.loads(json.dumps(next(answers))), dict(usage)

    monkeypatch.setattr(draw, "pick_engine", lambda engine="auto": "cli")
    monkeypatch.setattr(draw, "_call_cli", fake_call)
    out = tmp_path / "drawings"
    res = draw.draw_specs(book, out, pages=[0, 1], progress=lambda m: None)
    files = sorted(p.name for p in out.glob("*.json") if not p.name.startswith("_"))  # _draw_log.json sits next to the specs
    assert res["totals"]["ok"] == 2 and len(files) == 2 and files[0].startswith("000_") and files[1].startswith("001_")
    assert res["pages"][0]["attempts"] == 2 and "too small" in res["pages"][0]["problems"][0] and "rejected" in prompts[1]  # the retry carries the reason
    assert res["totals"]["input_tokens"] == 3600 and res["totals"]["cost_usd"] == 0.03
    log = json.loads((out / "_draw_log.json").read_text(encoding="utf-8"))
    assert [r["page"] for r in log["pages"]] == [1, 2] and log["last_run"]["ok"] == 2
    assert draw.draw_specs(book, out, pages=[0], progress=lambda m: None)["totals"]["pages"] == 0  # existing specs are kept unless overwrite
    assert draw.parse_pages("1-3,8", 30) == [0, 1, 2, 7] and draw.parse_pages(None, 3) == [0, 1, 2]


def test_set_spec_provider_edits_yaml_in_place(tmp_path):
    p = new_coloring_book(tmp_path, "cats", "Cats", "Mia", "cats", provider="local", subjects=["a cat"])
    changes = draw.set_spec_provider(p)
    b = load_book(p)
    assert b.interior.source.provider == "spec" and b.interior.source.path == "drawings" and b.provenance.interior_images == "ai_generated"
    assert draw.SPEC_TOOL in b.provenance.ai_tools and len(b.provenance.ai_tools) == 2 and len(changes) == 2
    assert "# Generated by kdp-studio" in p.read_text(encoding="utf-8") and draw.set_spec_provider(p) == []  # comments survive; idempotent


def test_llm_and_suggest_use_the_cli_when_no_key(monkeypatch, cli_on):
    class Out(BaseModel):
        title: str
        n: int

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run_factory({**ENVELOPE, "structured_output": {"title": "Snow Line", "n": 3}})[0])
    monkeypatch.setattr(llm, "claude_available", lambda: False)
    monkeypatch.setattr(llm, "cloudflare_available", lambda: False)
    assert llm.parse_structured("sys", "user", Out) == Out(title="Snow Line", n=3) and "Claude Code CLI" in llm.last_engine()
    monkeypatch.setattr(sg.keymod, "current_values", lambda: {})
    out = {"folder": "snow-line", "title": "Snow Line", "subtitle": "s", "author": "Tess Alder", "theme": "bold and easy snow", "audience": "adults", "keywords": ["a"], "subjects": ["a pine tree"]}
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run_factory({**ENVELOPE, "result": json.dumps(out)})[0])
    r = sg.suggest({"folder": "snow-line", "images": 3}, engine="cli")
    assert r["source"] == "cli" and "Claude Code CLI" in r["source_label"] and r["fields"]["subjects"].splitlines()[0] == "a pine tree"


def test_ui_draw_route_starts_a_job(monkeypatch, tmp_path):
    pytest.importorskip("flask")
    from kdp_studio.ui.app import create_app, discover_books

    monkeypatch.setattr("kdp_studio.ui.app.data_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr("kdp_studio.keys.env_path", lambda: tmp_path / ".env")
    app = create_app([ROOT / "examples"])
    app.config["TESTING"] = True
    client = app.test_client()
    idx = next(i for i, b in enumerate(discover_books([ROOT / "examples"])) if b.get("type") == "coloring")
    assert "Vẽ trang bằng Claude" in client.get(f"/book/{idx}").get_data(as_text=True)
    started = []
    monkeypatch.setattr(app.extensions["jobs"], "start", lambda title, cmd, book_idx=None: started.append((title, cmd, book_idx)) or "job-d")
    r = client.post(f"/book/{idx}/draw", data={"pages": "1-3", "engine": "cli", "model": "sonnet", "set_provider": "1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/jobs/job-d")
    title, cmd, bidx = started[0]
    assert title.startswith("vẽ vector") and bidx == idx and cmd[-7:] == ["--engine", "cli", "--pages", "1-3", "--model", "sonnet", "--set-provider"]


def test_gemini_engine_parses_usage_and_prices(monkeypatch):
    import urllib.request

    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(SPEC)}]}}], "modelVersion": "gemini-2.5-flash",
               "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 1000, "thoughtsTokenCount": 500}}
    seen = {}

    class Resp:
        def read(self):
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        seen.update(url=req.full_url, body=json.loads(req.data.decode("utf-8")), key=req.get_header("X-goog-api-key"))
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("kdp_studio.keys.current_values", lambda: {"GEMINI_API_KEY": "g-test"})
    obj, usage = draw._call_gemini("sys", "draw a daisy", None)
    assert obj["title"] == "Big daisy" and "gemini-2.5-flash:generateContent" in seen["url"] and seen["key"] == "g-test"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json" and seen["body"]["system_instruction"]["parts"][0]["text"] == "sys"
    assert usage["input_tokens"] == 900 and usage["output_tokens"] == 1500 and usage["thinking_tokens"] == 500 and usage["model"] == "gemini-2.5-flash"
    assert usage["cost_usd"] == round((900 * 0.30 + 1500 * 2.50) / 1e6, 5) and draw.pick_engine("gemini") == "gemini"
    monkeypatch.setattr("kdp_studio.keys.current_values", lambda: {})
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        draw.pick_engine("gemini")
