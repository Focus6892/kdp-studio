"""Thin wrapper around the Anthropic SDK used by every LLM-assisted step.

All calls go through `parse_structured`, which returns None (and logs why) on any
API problem so callers can fall back to deterministic templates. Credentials are
resolved by the SDK itself (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an
`ant auth login` profile); `claude_available()` is only a cheap pre-check used to
decide whether to try at all.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
T = TypeVar("T", bound=BaseModel)


def sdk_installed() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def claude_available() -> bool:
    if not sdk_installed():
        return False
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    profile_dir = Path.home() / ".config" / "anthropic"
    return profile_dir.is_dir() and any(profile_dir.iterdir())


_LAST_ENGINE: str | None = None
_LAST_ERROR: str | None = None


def last_engine() -> str | None:
    """Which engine answered the most recent parse_structured call (for provenance notes)."""
    return _LAST_ENGINE


def last_error() -> str | None:
    """Why the most recent parse_structured call got no answer (quota block, bad reply ...), for error messages."""
    return _LAST_ERROR


def cloudflare_available() -> bool:
    from . import keys as keymod

    return any(p["complete"] for p in keymod.profiles("cloudflare"))


def cli_available() -> bool:
    """The Claude Code command line (`claude -p`): Claude through the subscription signed in on this PC, no API key."""
    from . import claude_cli

    return claude_cli.available()


def _cli_structured(system: str, user: str, output_model: type[T]) -> T | None:
    """The model's JSON schema as the CLI's structured output; a plain JSON reply if the CLI rejects the schema."""
    from . import claude_cli
    from .suggest import parse_json_object

    global _LAST_ENGINE, _LAST_ERROR
    schema = output_model.model_json_schema()
    for use_schema in (True, False):
        try:
            res = claude_cli.run(user, system=system, schema=schema if use_schema else None)
        except claude_cli.CLIError as exc:
            _LAST_ERROR = f"Claude Code CLI: {str(exc)[:160]}"
            log.warning("%s", _LAST_ERROR)
            if use_schema:
                continue
            return None
        obj = res.structured if isinstance(res.structured, dict) else parse_json_object(res.text)
        if not isinstance(obj, dict):
            _LAST_ERROR = "Claude Code CLI: no JSON object in the reply"
            log.warning("%s", _LAST_ERROR)
            continue
        try:
            parsed = output_model.model_validate(obj)
        except Exception as exc:  # noqa: BLE001 - pydantic validation
            _LAST_ERROR = f"Claude Code CLI: reply did not match {output_model.__name__}"
            log.warning("%s (%s)", _LAST_ERROR, str(exc).splitlines()[0][:120])
            continue
        _LAST_ENGINE, _LAST_ERROR = f"Claude ({res.model}) via Claude Code CLI", None
        log.info("Claude Code CLI %s", res.summary())
        return parsed
    return None


def compat_available() -> bool:
    """An OpenAI-compatible endpoint configured with OPENAI_COMPAT_BASE_URL / _MODEL (Oxion AI, OpenRouter, Ollama ...)."""
    from . import compat

    return compat.available()


def _compat_structured(system: str, user: str, output_model: type[T], max_tokens: int) -> T | None:
    from . import compat

    global _LAST_ENGINE, _LAST_ERROR
    try:
        obj, res = compat.ask_json(system + " Respond with one JSON object only - no prose, no code fences - matching this JSON schema: "
                                   + json.dumps(output_model.model_json_schema()), user, max_tokens=min(16000, max_tokens))
    except compat.CompatError as exc:
        _LAST_ERROR = f"OpenAI-compatible: {str(exc)[:160]}"
        log.warning("%s", _LAST_ERROR)
        return None
    try:
        parsed = output_model.model_validate(obj)
    except Exception as exc:  # noqa: BLE001 - pydantic validation
        _LAST_ERROR = f"OpenAI-compatible: reply did not match {output_model.__name__}"
        log.warning("%s (%s)", _LAST_ERROR, str(exc).splitlines()[0][:120])
        return None
    _LAST_ENGINE, _LAST_ERROR = f"{res.model} via OpenAI-compatible API", None
    log.info("OpenAI-compatible %s", res.summary())
    return parsed


def _cloudflare_structured(system: str, user: str, output_model: type[T], max_tokens: int) -> T | None:
    """The free fallback: a Workers AI text model gets the JSON schema in its instructions and its reply is parsed
    and validated. Accounts and quota blocks are shared with the image providers (state/provider_state.json)."""
    import json
    import urllib.request

    from . import keys as keymod
    from .interior.failover import ProviderState
    from .interior.generate import ProviderError, ProviderQuota, _request, error_summary
    from .suggest import CF_TEXT_MODELS, parse_json_object

    global _LAST_ENGINE, _LAST_ERROR
    schema = json.dumps(output_model.model_json_schema())
    body = {"messages": [{"role": "system", "content": system + " Respond with one JSON object only - no prose, no code fences - that matches this JSON schema: " + schema},
                         {"role": "user", "content": user}], "max_tokens": min(4096, max_tokens), "temperature": 0.7}
    state = ProviderState()
    models = tuple(m for m in (os.environ.get("KDP_STUDIO_CF_TEXT_MODEL"),) if m) + CF_TEXT_MODELS
    for acc in [p for p in keymod.profiles("cloudflare") if p["complete"]]:
        if not state.is_available(acc["id"]):
            until = state.exhausted_until(acc["id"])
            _LAST_ERROR = f"Cloudflare {acc['id']} tạm khóa" + (f" đến {until.astimezone():%H:%M %d/%m}" if until else "") + " (hết quota ngày hoặc lỗi key)"
            log.warning("Workers AI %s skipped: %s", acc["id"], _LAST_ERROR)
            continue
        vals = keymod.profile_values(acc["id"])
        for model_id in models:
            req = urllib.request.Request(f"https://api.cloudflare.com/client/v4/accounts/{vals['CF_ACCOUNT_ID']}/ai/run/{model_id}", data=json.dumps(body).encode("utf-8"),
                                         headers={"Authorization": f"Bearer {vals['CF_API_TOKEN']}", "Content-Type": "application/json"}, method="POST")
            try:
                raw = _request(req, timeout=240, tries=2)
            except ProviderQuota as exc:
                state.mark_exhausted(acc["id"], error_summary(exc))
                _LAST_ERROR = f"Cloudflare {acc['id']}: {error_summary(exc)}"
                log.warning("Workers AI %s: %s - trying the next account", acc["id"], error_summary(exc))
                break
            except ProviderError as exc:
                _LAST_ERROR = f"{model_id}: {error_summary(exc)}"
                log.warning("Workers AI %s: %s", model_id, error_summary(exc))
                continue
            try:
                data = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            result = data.get("result") if isinstance(data, dict) else None
            text = result.get("response") if isinstance(result, dict) else None
            obj = text if isinstance(text, dict) else parse_json_object(str(text or ""))
            if not obj and "markdown" in output_model.model_fields and text:  # a chapter that came back as plain prose
                obj = {"title": "", "markdown": str(text).strip()}
            if not obj:
                _LAST_ERROR = f"{model_id}: no JSON object in the reply"
                log.warning("Workers AI %s: no JSON object in the reply", model_id)
                continue
            try:
                parsed = output_model.model_validate(obj)
            except Exception as exc:  # noqa: BLE001 - pydantic validation
                _LAST_ERROR = f"{model_id}: reply did not match {output_model.__name__}"
                log.warning("Workers AI %s: reply did not match %s (%s)", model_id, output_model.__name__, str(exc).splitlines()[0][:120])
                continue
            _LAST_ENGINE, _LAST_ERROR = f"{model_id.rsplit('/', 1)[-1]} via Cloudflare Workers AI", None
            return parsed
    return None


ENGINES = ("claude", "cli", "compat", "cloudflare")  # the auto order; KDP_STUDIO_LLM=<engine> forces one


def parse_structured(system: str, user: str, output_model: type[T], model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> T | None:
    """One structured-output call. Engines in order unless KDP_STUDIO_LLM names one: Claude through the API (key),
    Claude through the Claude Code CLI (subscription), an OpenAI-compatible endpoint (Oxion AI, OpenRouter, Ollama ...),
    a Cloudflare Workers AI text model (free). None when nothing answers; last_error() says why."""
    global _LAST_ENGINE, _LAST_ERROR
    _LAST_ERROR = None
    forced = (os.environ.get("KDP_STUDIO_LLM") or "auto").strip().lower()
    for engine in ([forced] if forced in ENGINES else ENGINES):
        if engine == "claude" and claude_available():
            out = _claude_structured(system, user, output_model, model, max_tokens)
            if out is not None:
                _LAST_ENGINE = f"Claude ({model})"
                return out
            _LAST_ERROR = "Claude: không trả lời được (xem log)"
        elif engine == "cli" and cli_available():
            out = _cli_structured(system, user, output_model)
            if out is not None:
                return out
        elif engine == "compat" and compat_available():
            out = _compat_structured(system, user, output_model, max_tokens)
            if out is not None:
                return out
        elif engine == "cloudflare" and cloudflare_available():
            out = _cloudflare_structured(system, user, output_model, max_tokens)
            if out is not None:
                return out
    _LAST_ERROR = _LAST_ERROR or ("chưa có key Anthropic, lệnh claude, endpoint OpenAI-compatible hay Cloudflare (Cài đặt)" if forced not in ENGINES
                                  else f"engine {forced} (KDP_STUDIO_LLM) chưa cấu hình hoặc không trả lời")
    log.warning("no LLM answered: %s", _LAST_ERROR)
    return None


def _claude_structured(system: str, user: str, output_model: type[T], model: str, max_tokens: int) -> T | None:
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed (pip install 'kdp-studio[ai]'); skipping Claude step")
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_model,
        )
    except anthropic.AuthenticationError:
        log.warning("Anthropic authentication failed (set ANTHROPIC_API_KEY or run `ant auth login`); skipping Claude step")
        return None
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit hit; skipping Claude step")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Anthropic API error %s; skipping Claude step", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("Could not reach the Anthropic API; skipping Claude step")
        return None
    except anthropic.AnthropicError as exc:  # e.g. no credentials configured at all
        log.warning("Anthropic client error: %s; skipping Claude step", exc)
        return None

    if response.stop_reason == "refusal":
        log.warning("Claude declined this request (%s)", getattr(response.stop_details, "category", None))
        return None
    if response.stop_reason == "max_tokens":
        log.warning("Claude hit max_tokens; output may be incomplete")
    return response.parsed_output
