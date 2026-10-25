"""Any OpenAI-compatible chat endpoint as an LLM engine: Oxion AI, OpenRouter, Groq, Together, the Gemini or Cloudflare
compatibility endpoints, or a local server (Ollama, LM Studio). Three settings in .env or the environment:
OPENAI_COMPAT_BASE_URL (e.g. https://oxionai.com/v1), OPENAI_COMPAT_API_KEY (optional for local servers) and
OPENAI_COMPAT_MODEL (the id the server expects). Only /chat/completions is used; JSON mode is requested and dropped
automatically when the server rejects it. Token usage comes from the response; prices from the server's /models/{id}
when it publishes them (Oxion, OpenRouter), else from OPENAI_COMPAT_PRICE_IN / _OUT (USD per million tokens)."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)
VARS = ("OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_MODEL")
_PRICE_CACHE: dict[str, tuple[float, float]] = {}


class CompatError(RuntimeError):
    pass


@dataclass
class CompatResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost_usd: float
    duration_ms: int

    def summary(self) -> str:
        think = f" ({self.thinking_tokens:,} thinking)" if self.thinking_tokens else ""
        return f"{self.model}: {self.input_tokens:,} in, {self.output_tokens:,} out{think}, ${self.cost_usd:.4f}, {self.duration_ms / 1000:.0f} s"


def settings() -> dict[str, str]:
    from . import keys as keymod

    vals = keymod.current_values()
    out = {v: (vals.get(v) or os.environ.get(v) or "").strip() for v in VARS}
    out["OPENAI_COMPAT_BASE_URL"] = out["OPENAI_COMPAT_BASE_URL"].rstrip("/")
    return out


def available() -> bool:
    s = settings()
    return bool(s["OPENAI_COMPAT_BASE_URL"] and s["OPENAI_COMPAT_MODEL"])


def label() -> str:
    s = settings()
    return f"{s['OPENAI_COMPAT_MODEL']} @ {s['OPENAI_COMPAT_BASE_URL']}"


def _headers(key: str) -> dict[str, str]:
    h = {"Content-Type": "application/json", "User-Agent": "kdp-studio/0.1"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _post(url: str, body: dict, key: str, timeout: int) -> tuple[int, str]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=_headers(key), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - the URL the user configured
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CompatError(f"không kết nối được {url}: {str(exc)[:160]}") from None


RETRY_CODES = (429, 502, 503, 504)
RETRY_WAITS = (5, 15, 30)  # seconds between attempts on a busy or upgrading gateway


def _post_retrying(url: str, body: dict, key: str, timeout: int) -> tuple[int, str]:
    code, raw = _post(url, body, key, timeout)
    for wait in RETRY_WAITS:
        if code not in RETRY_CODES:
            break
        log.warning("%s answered HTTP %s, retrying in %s s", url, code, wait)
        time.sleep(wait)
        code, raw = _post(url, body, key, timeout)
    return code, raw


def model_price(base_url: str, key: str, model: str) -> tuple[float, float]:
    """USD per million tokens (in, out): the env override, else the server's /models/{id} when it carries prices
    (Oxion: pricing.input_per_1k; OpenRouter: pricing.prompt per token), else 0 (unknown)."""
    env_in, env_out = os.environ.get("OPENAI_COMPAT_PRICE_IN"), os.environ.get("OPENAI_COMPAT_PRICE_OUT")
    if env_in or env_out:
        return float(env_in or 0), float(env_out or 0)
    cache_key = f"{base_url}|{model}"
    if cache_key not in _PRICE_CACHE:
        price = (0.0, 0.0)
        req = urllib.request.Request(f"{base_url}/models/{model}", headers=_headers(key))
        try:
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
                p = (json.loads(r.read().decode("utf-8", "replace")) or {}).get("pricing") or {}
            if "input_per_1k" in p:
                price = (float(p["input_per_1k"]) * 1000, float(p.get("output_per_1k") or 0) * 1000)
            elif "prompt" in p:
                price = (float(p["prompt"]) * 1e6, float(p.get("completion") or 0) * 1e6)
        except Exception:  # noqa: BLE001 - prices are a nicety
            pass
        _PRICE_CACHE[cache_key] = price
    return _PRICE_CACHE[cache_key]


def chat(system: str | None, user: str, json_mode: bool = True, model: str | None = None, max_tokens: int = 8000, temperature: float = 0.7, timeout: int = 600) -> CompatResult:
    s = settings()
    base, key = s["OPENAI_COMPAT_BASE_URL"], s["OPENAI_COMPAT_API_KEY"]
    model = model or s["OPENAI_COMPAT_MODEL"]
    if not base or not model:
        raise CompatError("chưa đặt OPENAI_COMPAT_BASE_URL và OPENAI_COMPAT_MODEL (Cài đặt -> OpenAI-compatible API)")
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    t0 = time.monotonic()
    code, raw = _post_retrying(f"{base}/chat/completions", body, key, timeout)
    if code == 400 and json_mode and "response_format" in raw:  # a server without JSON mode: ask again as plain text
        body.pop("response_format", None)
        code, raw = _post_retrying(f"{base}/chat/completions", body, key, timeout)
    if code == 401:
        raise CompatError("HTTP 401: key sai hoặc thiếu (OPENAI_COMPAT_API_KEY)")
    if code == 402:
        raise CompatError("HTTP 402: hết số dư hoặc hết gói token của tài khoản")
    if code == 429:
        raise CompatError("HTTP 429: vượt giới hạn tốc độ hoặc hạn mức; thử lại sau")
    if code != 200:
        raise CompatError(f"HTTP {code}: {raw[:200]}")
    data = json.loads(raw)
    choices = data.get("choices") or []
    msg = (choices[0].get("message") or {}) if choices else {}
    content = msg.get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not str(content).strip():
        raise CompatError("server trả về nội dung rỗng" + (f" (finish_reason {choices[0].get('finish_reason')})" if choices else ""))
    u = data.get("usage") or {}
    tokens_in, tokens_out = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
    thinking = int(((u.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0)
    price = model_price(base, key, model)
    cost = (tokens_in * price[0] + tokens_out * price[1]) / 1e6
    return CompatResult(str(content), str(data.get("model") or model), tokens_in, tokens_out, thinking, round(cost, 5), int((time.monotonic() - t0) * 1000))


def ask_json(system: str | None, user: str, **kw) -> tuple[dict, CompatResult]:
    from .suggest import parse_json_object

    res = chat(system, user, json_mode=True, **kw)
    obj = parse_json_object(res.text)
    if not isinstance(obj, dict):
        raise CompatError("câu trả lời không có JSON: " + res.text[:200])
    return obj, res
