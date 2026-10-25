"""Claude through the Claude Code command line (`claude -p`), i.e. the Claude subscription already signed in on this
PC: no Anthropic API key, no per-token bill. One-shot headless prompts with our own system prompt and no tools;
structured output through --json-schema; token counts and the list-price cost come back in the CLI's JSON envelope,
so every call can report what it would have cost on the API."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)
ENV_BIN = "KDP_STUDIO_CLAUDE_CLI"  # path to the claude executable; default: `claude` on PATH
ENV_MODEL = "KDP_STUDIO_CLI_MODEL"  # sonnet / opus / haiku or a full model id; default: the CLI's own default model
ENV_OFF = "KDP_STUDIO_NO_CLAUDE_CLI"  # "1" disables this engine (tests, or to force the API / Cloudflare)


class CLIError(RuntimeError):
    pass


@dataclass
class CLIResult:
    text: str
    structured: object
    model: str
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_write: int
    thinking_tokens: int
    cost_usd: float
    duration_ms: int
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read + self.cache_write

    def summary(self) -> str:
        think = f" ({self.thinking_tokens:,} thinking)" if self.thinking_tokens else ""
        return f"{self.model}: {self.prompt_tokens:,} in ({self.cache_read:,} cached), {self.output_tokens:,} out{think}, ${self.cost_usd:.4f} list price, {self.duration_ms / 1000:.0f} s"


def binary() -> str | None:
    return os.environ.get(ENV_BIN) or shutil.which("claude")


def available() -> bool:
    return os.environ.get(ENV_OFF) != "1" and binary() is not None


def run(prompt: str, system: str | None = None, schema: dict | None = None, model: str | None = None, effort: str | None = None,
        timeout: int = 900, max_budget_usd: float | None = None) -> CLIResult:
    """One prompt in, one answer out. The prompt goes through stdin (no command-line length limit); the system prompt
    replaces Claude Code's own; tools, settings files and MCP servers are off so the context stays about 1,000 tokens."""
    exe = binary()
    if not exe:
        raise CLIError("không thấy lệnh claude: cài Claude Code và đăng nhập, hoặc đặt KDP_STUDIO_CLAUDE_CLI")
    cmd = [exe, "-p", "--output-format", "json", "--max-turns", "1", "--no-session-persistence", "--tools", "", "--setting-sources", "", "--strict-mcp-config"]
    if system:
        cmd += ["--system-prompt", system]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    model = model or os.environ.get(ENV_MODEL)
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    if max_budget_usd:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}  # also runs from inside a Claude Code session
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise CLIError(f"lệnh claude không trả lời trong {timeout} s") from None
    out = (proc.stdout or "").strip()
    data = None
    if "{" in out:
        try:
            data = json.loads(out[out.find("{"):])
        except ValueError:
            data = None
    if not isinstance(data, dict):
        raise CLIError(f"lệnh claude thoát mã {proc.returncode}: {((proc.stderr or '') + out)[:300].strip()}")
    if data.get("is_error") or data.get("subtype") not in (None, "success"):
        raise CLIError(f"lệnh claude: {data.get('subtype')}: {str(data.get('result'))[:300]}")
    usage = data.get("usage") or {}
    model_id = next(iter(data.get("modelUsage") or {}), "") or model or "claude"
    return CLIResult(text=str(data.get("result") or ""), structured=data.get("structured_output"), model=model_id.replace("[1m]", ""),
                     input_tokens=int(usage.get("input_tokens") or 0), output_tokens=int(usage.get("output_tokens") or 0),
                     cache_read=int(usage.get("cache_read_input_tokens") or 0), cache_write=int(usage.get("cache_creation_input_tokens") or 0),
                     thinking_tokens=int((usage.get("output_tokens_details") or {}).get("thinking_tokens") or 0),
                     cost_usd=float(data.get("total_cost_usd") or 0.0), duration_ms=int(data.get("duration_ms") or 0), raw=data)


def ask_json(prompt: str, system: str | None = None, schema: dict | None = None, **kw) -> tuple[dict, CLIResult]:
    """A JSON object answer: the structured output when a schema was given, else the first {...} in the reply."""
    res = run(prompt, system=system, schema=schema, **kw)
    obj = res.structured
    if not isinstance(obj, dict):
        from .suggest import parse_json_object

        obj = parse_json_object(res.text)
    if not isinstance(obj, dict):
        raise CLIError("câu trả lời của claude không có JSON: " + res.text[:200])
    return obj, res
