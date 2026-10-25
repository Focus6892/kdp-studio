"""Hoàn thiện form "Tạo sách": từ vài ô đã gõ, điền nốt mọi ô còn lại sao cho khớp nhau.

Engines, tried in order (env KDP_STUDIO_SUGGEST = auto | claude | cli | compat | cloudflare | offline, default auto):
  1. Claude through the anthropic SDK (ANTHROPIC_API_KEY), structured output
  2. Claude through the Claude Code CLI (`claude -p`, the subscription signed in on this PC, no key)
  3. any OpenAI-compatible endpoint (OPENAI_COMPAT_BASE_URL / _API_KEY / _MODEL: Oxion AI, OpenRouter, Ollama ...)
  4. a Cloudflare Workers AI text model (CF_ACCOUNT_ID + CF_API_TOKEN) - free tier, the same keys that draw the pages
  5. offline: the built-in niche library (themes.py) plus the pipeline's own variation templates, so the
     button always works without any key.
Typed values are anchors: they are kept and everything else is generated around them; overwrite=True
regenerates every field and treats the typed values as hints (typos fixed). Whatever the engine, the result
goes through one validator: 7 keywords of <= 50 chars, exactly N page subjects with no people (the interior
QA rejects people), a valid folder slug, English text for amazon.com.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request

from pydantic import BaseModel

from . import keys as keymod
from .bookgen import SLUG, default_keywords
from .interior.generate import ProviderError, _request, error_summary
from .interior.prompts import VARIATIONS
from .themes import find_theme

log = logging.getLogger(__name__)

TEXT_FIELDS = ("folder", "title", "subtitle", "author", "theme", "audience")
DEFAULT_AUDIENCE = "adults and kids, beginners"
PEN_NAMES = ("Mia Hartwell", "Nora Fielding", "Ellie Marsh", "June Calloway", "Hazel Brooks", "Clara Winslow", "Ivy Lennox", "Rosie Whitfield", "Tess Alder", "Wren Hollis")
# subjects naming people or human-like figures are dropped: the interior QA would reject the page anyway
PEOPLE = re.compile(
    r"\b(?:man|men|woman|women|boy|boys|girl|girls|child|children|kid|kids|person|people|lady|ladies|princess|prince|mermaid|mermaids|fairy|fairies|elf|elves|"
    r"wizard|witch|knight|pirate|santa|astronaut|farmer|chef|nurse|doctor|king|queen|face|faces|portrait|scarecrow|gingerbread man|snowman|snowmen|angel|"
    r"skeleton|zombie|mummy|ghost|ghosts|couple|bride|groom|dancer|ballerina|teacher|superhero|human|humans)\b", re.I)
CF_TEXT_MODELS = ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/meta/llama-3.1-8b-instruct")

SYSTEM = (
    "You help a self-publisher fill in the metadata of a bold-and-easy coloring book sold on Amazon KDP (amazon.com, English). "
    "Fields: folder (lowercase slug, a-z 0-9 and hyphens, at most 40 characters); title (at most 80 characters, no promises or superlatives); "
    "subtitle (at most 120 characters: number of pages, the style, the audience); author (a plausible two-word pen name unless one was typed); "
    "theme (a short lowercase phrase such as 'bold and easy ocean animals'); audience (a short phrase); "
    "keywords (exactly 7 search phrases, lowercase, each at most 50 characters, no quotes, no brand or competitor names, no words like best/free/cheap, "
    "not merely repeating the title); subjects (one concrete drawable scene per page, at most 12 words each, built from large simple shapes with thick "
    "outlines, all distinct). Subjects must contain no people or human-like figures (no faces, hands, mermaids, fairies, snowmen, Santa), no text, letters, "
    "numbers, logos, brands or copyrighted characters, and must suit the audience. Everything must match the values the author typed."
)
JSON_SHAPE = ('{"folder": "...", "title": "...", "subtitle": "...", "author": "...", "theme": "...", "audience": "...", '
              '"keywords": ["...", "...", "...", "...", "...", "...", "..."], "subjects": ["one line per page", "..."]}')


class SuggestError(RuntimeError):
    pass


class LLMOut(BaseModel):
    folder: str
    title: str
    subtitle: str
    author: str
    theme: str
    audience: str
    keywords: list[str]
    subjects: list[str]


# ------------------------------------------------------------------ small text helpers
_PREFIX = re.compile(r"^(?:(?:bold|simple|easy|large print|big|cute|relaxing|and|&)\s+)+", re.I)
_SUFFIX = re.compile(r"\s+(?:coloring|colouring)\s+(?:book|books|pages?)\b.*$", re.I)
_SMALL = {"and", "of", "the", "for", "with", "in", "on", "a", "an", "to"}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40].strip("-")
    return s if SLUG.match(s) else ""


def title_case(text: str) -> str:
    return " ".join(w if (i and w.lower() in _SMALL) else w[:1].upper() + w[1:] for i, w in enumerate(text.split()))


def theme_noun(text: str) -> str:
    """'bold and easy ocean animals' / 'Ocean Animals Coloring Book' / '30 Sea Creatures' -> 'ocean animals' ..."""
    t = _SUFFIX.sub("", (text or "").strip())
    t = _PREFIX.sub("", t)
    t = re.sub(r"^\d+\s+", "", t)
    return t.strip(" ,-").lower()


def _audience_phrase(audience: str) -> str:
    first = (audience or DEFAULT_AUDIENCE).split(",")[0].strip() or "adults and kids"
    return title_case(first)


def _short(exc: BaseException) -> str:
    return error_summary(exc)


def parse_json_object(text: str) -> dict | None:
    """The first {...} object in a model's reply (code fences and prose around it are ignored; trailing commas tolerated)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    chunk = text[start:end + 1]
    for candidate in (chunk, re.sub(r",\s*([}\]])", r"\1", chunk)):
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        return obj if isinstance(obj, dict) else None
    return None


# ------------------------------------------------------------------ form parsing and validation
def parse_form(form: dict) -> tuple[dict, int]:
    def text(k: str) -> str:
        v = form.get(k)
        return str(v).strip() if v is not None else ""

    try:
        images = int(float(text("images") or 30))
    except ValueError:
        images = 30
    images = max(1, min(400, images))
    given: dict = {k: text(k) for k in TEXT_FIELDS}
    given["keywords"] = [k.strip() for k in text("keywords").split(",") if k.strip()]
    given["subjects"] = [ln.strip() for ln in text("subjects").splitlines() if ln.strip()]
    return given, images


def clean_keywords(candidates: list, fill: list[str], title: str = "") -> list[str]:
    out: list[str] = []
    for raw in list(candidates or []) + list(fill or []):
        k = re.sub(r"\s+", " ", str(raw).strip().strip("\"'").strip()).lower()
        if not k or len(k) > 50 or k == title.strip().lower() or k in out:
            continue
        out.append(k)
        if len(out) == 7:
            break
    return out


def clean_subjects(candidates: list, n: int, pool: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: object) -> None:
        s = re.sub(r"\s+", " ", str(raw).strip().strip('"').rstrip(".").strip())
        if not s or s.lower() in seen or PEOPLE.search(s):
            return
        seen.add(s.lower())
        out.append(s)

    for s in list(candidates or []) + list(pool or []):
        if len(out) >= n:
            break
        add(s)
    base = list(out) or ["a single large subject filling the page"]
    k = 2
    while len(out) < n:  # the pipeline numbers variations the same way when subjects run out
        for s in base:
            if len(out) >= n:
                break
            add(f"{s} (variation {k})")
        k += 1
    return out[:n]


def pools(theme: str, title: str) -> tuple[list[str], list[str], str]:
    """Subjects and keywords to top up with, following the (final) theme: library lists when the niche is known,
    else the pipeline's variation templates around the theme noun."""
    lib = find_theme(theme) or find_theme(title)
    noun = lib["noun"] if lib else title_case(theme_noun(theme) or theme_noun(title) or "flowers")
    subjects = list(lib["subjects"]) if lib else [v.format(theme=noun.lower()) for v in VARIATIONS]
    keywords = list(lib["keywords"]) if lib else default_keywords(noun.lower())
    return subjects, keywords, noun


# ------------------------------------------------------------------ engines
def offline_text(given: dict, images: int, overwrite: bool = False) -> dict:
    """Title, subtitle, pen name, theme, audience and folder from whatever was typed, without any API."""
    seed = (given["theme"] or theme_noun(given["title"]) or given["folder"].replace("-", " ").replace("_", " ")
            or (given["subjects"][0] if given["subjects"] else "") or (given["keywords"][0] if given["keywords"] else "") or "flowers")
    lib = find_theme(seed) or find_theme(given["title"]) or find_theme(given["folder"])
    noun = lib["noun"] if lib else title_case(theme_noun(seed) or seed)
    sub = lib["sub"] if lib else noun
    g = {k: "" for k in TEXT_FIELDS} if overwrite else given
    theme = g["theme"] or f"bold and easy {noun.lower()}"
    title = g["title"] or f"{noun} Coloring Book"
    audience = g["audience"] or DEFAULT_AUDIENCE
    subtitle = g["subtitle"] or f"{images} Bold and Easy {sub} for {_audience_phrase(audience)}"
    author = g["author"] or PEN_NAMES[sum(map(ord, title)) % len(PEN_NAMES)]
    folder = g["folder"] or slugify(noun) or "my-coloring-book"
    return {"folder": folder, "title": title, "subtitle": subtitle, "author": author, "theme": theme, "audience": audience}


def _user_prompt(given: dict, images: int, overwrite: bool) -> str:
    typed = {k: v for k, v in given.items() if v}
    lines = [f"Number of coloring pages, i.e. subjects needed: {images}."]
    if typed:
        lines.append("The author typed these values; treat them as hints: fix typos and improve the wording where it clearly helps."
                     if overwrite else
                     "The author already typed these values. Keep them exactly as given and build every other field to match them; "
                     "for keywords and subjects keep the typed entries first and add new ones to reach the required count.")
        for k, v in typed.items():
            lines.append(f"- {k}: " + (" | ".join(v) if isinstance(v, list) else v))
    else:
        lines.append("Nothing has been typed yet: propose one popular bold-and-easy niche and fill everything for it.")
    lines.append(f"Return every field: exactly 7 keywords and exactly {images} subjects, all in English.")
    return "\n".join(lines)


def _claude(system: str, user: str, out_model: type[BaseModel], max_tokens: int, api_key: str) -> tuple[dict, str]:
    try:
        import anthropic
    except ImportError:
        raise SuggestError("chưa cài SDK: pip install anthropic") from None
    model = os.environ.get("KDP_STUDIO_CLAUDE_MODEL", "claude-opus-5-5")
    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.parse(model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}], output_format=out_model)
    except anthropic.APIStatusError as exc:
        raise SuggestError(f"HTTP {exc.status_code}: {_short(exc)}") from None
    except anthropic.APIConnectionError as exc:
        raise SuggestError(f"không kết nối được: {_short(exc)}") from None
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise SuggestError("Claude không trả về kết quả có cấu trúc")
    return resp.parsed_output.model_dump(), model


def _cloudflare(system: str, user: str, json_shape: str, max_tokens: int) -> tuple[dict, str]:
    """Workers AI text models, trying every configured Cloudflare account (cloudflare, cloudflare#2 ...) that is not
    blocked in the provider state; an account that answers 429 is blocked until its reset time, like for images."""
    from .interior.failover import ProviderState
    from .interior.generate import ProviderQuota

    body = {"messages": [{"role": "system", "content": system + " Respond with one JSON object only - no prose, no code fences - shaped like: " + json_shape},
                         {"role": "user", "content": user}], "max_tokens": min(4096, max_tokens), "temperature": 0.6}
    models = tuple(m for m in (os.environ.get("KDP_STUDIO_CF_TEXT_MODEL"),) if m) + CF_TEXT_MODELS
    state = ProviderState()
    accounts = [p for p in keymod.profiles("cloudflare") if p["complete"]]
    last = "chưa có tài khoản Cloudflare nào"
    for acc in accounts:
        if not state.is_available(acc["id"]):
            until = state.exhausted_until(acc["id"])
            last = f"{acc['id']} tạm khóa đến {until.astimezone():%H:%M %d/%m}" if until else f"{acc['id']} tạm khóa"
            continue
        vals = keymod.profile_values(acc["id"])
        for model in models:
            req = urllib.request.Request(f"https://api.cloudflare.com/client/v4/accounts/{vals['CF_ACCOUNT_ID']}/ai/run/{model}", data=json.dumps(body).encode("utf-8"),
                                         headers={"Authorization": f"Bearer {vals['CF_API_TOKEN']}", "Content-Type": "application/json"}, method="POST")
            try:
                raw = _request(req, timeout=120, tries=2)
            except ProviderQuota as exc:
                state.mark_exhausted(acc["id"], _short(exc))
                last = f"{acc['id']}: {_short(exc)}"
                break  # next account
            except ProviderError as exc:
                last = _short(exc)
                continue  # next model
            try:
                data = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                last = f"{model}: phản hồi không phải JSON"
                continue
            result = data.get("result") if isinstance(data, dict) else None
            text = result.get("response") if isinstance(result, dict) else None
            parsed = text if isinstance(text, dict) else parse_json_object(str(text or ""))
            if parsed:
                return parsed, f"{model.rsplit('/', 1)[-1]} · {acc['id']}"
            last = f"{model}: không tách được JSON từ câu trả lời"
    raise SuggestError(last)


# ------------------------------------------------------------------ merge + entry point
def _merge(llm: dict | None, offline: dict, given: dict, images: int, overwrite: bool) -> dict:
    llm = llm or {}
    out: dict = {}
    for k in TEXT_FIELDS:
        if given[k] and not overwrite:
            out[k] = given[k]
        else:
            out[k] = str(llm.get(k) or "").strip()[:200] or offline[k]
    out["folder"] = slugify(out["folder"]) or offline["folder"]
    subject_pool, keyword_pool, _noun = pools(out["theme"], out["title"])
    typed_kw = [] if overwrite else given["keywords"]
    out["keywords"] = clean_keywords(typed_kw + list(llm.get("keywords") or []), keyword_pool, out["title"])
    typed_sub = [] if overwrite else given["subjects"]
    out["subjects"] = clean_subjects(typed_sub + [s for s in (llm.get("subjects") or []) if str(s).strip()], images, subject_pool)
    return out


def run_engines(system: str, user: str, out_model: type[BaseModel], json_shape: str, max_tokens: int, engine: str | None = None) -> tuple[dict | None, str, str, list[str]]:
    """Try the engines in order (the given engine or env KDP_STUDIO_SUGGEST): (model fields or None, source, label, notes)."""
    engine = (engine or os.environ.get("KDP_STUDIO_SUGGEST") or "auto").strip().lower()
    if engine not in ("auto", "claude", "cli", "compat", "cloudflare", "offline"):
        engine = "auto"
    vals = keymod.current_values()
    llm: dict | None = None
    source, label, notes = "offline", "mẫu có sẵn (không cần key)", []
    if engine in ("auto", "claude"):
        if vals.get("ANTHROPIC_API_KEY"):
            try:
                llm, model = _claude(system, user, out_model, max_tokens, vals["ANTHROPIC_API_KEY"])
                source, label = "claude", f"Claude ({model})"
            except Exception as exc:  # noqa: BLE001 - fall through to the next engine, tell the user why
                notes.append(f"Claude: {_short(exc)}")
        elif engine == "claude":
            notes.append("Claude: chưa có ANTHROPIC_API_KEY (thêm ở Cài đặt)")
    if llm is None and engine in ("auto", "cli"):
        from . import claude_cli

        if claude_cli.available():
            try:
                llm, res = claude_cli.ask_json(user, system=system + " Respond with one JSON object only - no prose, no code fences - shaped like: " + json_shape)
                source, label = "cli", f"Claude Code CLI ({res.model})"
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Claude Code CLI: {_short(exc)}")
        elif engine == "cli":
            notes.append("Claude Code CLI: không thấy lệnh claude (cài Claude Code và đăng nhập)")
    if llm is None and engine in ("auto", "compat"):
        from . import compat

        if compat.available():
            try:
                llm, res = compat.ask_json(system + " Respond with one JSON object only - no prose, no code fences - shaped like: " + json_shape, user)
                source, label = "compat", f"OpenAI-compatible ({res.model})"
            except Exception as exc:  # noqa: BLE001
                notes.append(f"OpenAI-compatible: {_short(exc)}")
        elif engine == "compat":
            notes.append("OpenAI-compatible: chưa đặt OPENAI_COMPAT_BASE_URL / OPENAI_COMPAT_MODEL (Cài đặt)")
    if llm is None and engine in ("auto", "cloudflare"):
        if any(p["complete"] for p in keymod.profiles("cloudflare")):
            try:
                llm, model = _cloudflare(system, user, json_shape, max_tokens)
                source, label = "cloudflare", f"Cloudflare Workers AI ({model})"
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Cloudflare: {_short(exc)}")
        elif engine == "cloudflare":
            notes.append("Cloudflare: chưa có CF_ACCOUNT_ID / CF_API_TOKEN (thêm ở Cài đặt)")
    if engine == "auto" and llm is None and not notes:
        notes.append("chưa có key Anthropic, lệnh claude hay Cloudflare nên dùng thư viện mẫu; thêm key ở Cài đặt (hoặc cài Claude Code) để gợi ý sát chủ đề hơn")
    return llm, source, label, notes


def suggest(form: dict, *, overwrite: bool = False, engine: str | None = None) -> dict:
    """All form fields, completed to match each other: {fields, source, source_label, notes, images, kind}. A form with
    kind=story (premise, chapter outline, keywords of a text book) is handled by suggest_story."""
    if str(form.get("kind") or "").strip().lower() == "story":
        from .suggest_story import suggest_story

        return suggest_story(form, overwrite=overwrite, engine=engine)
    given, images = parse_form(form)
    offline = offline_text(given, images, overwrite)
    llm, source, label, notes = run_engines(SYSTEM, _user_prompt(given, images, overwrite), LLMOut, JSON_SHAPE, min(16000, 2500 + 24 * images), engine)
    out = _merge(llm, offline, given, images, overwrite)
    fields = {**{k: out[k] for k in TEXT_FIELDS}, "keywords": ", ".join(out["keywords"]), "subjects": "\n".join(out["subjects"])}
    return {"fields": fields, "source": source, "source_label": label, "notes": notes, "images": images, "overwrite": overwrite, "kind": "coloring"}
