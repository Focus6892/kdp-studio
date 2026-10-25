"""Draw coloring pages as vector specs with Claude: through the Claude Code CLI (the subscription on this PC, no API
key) or the Anthropic API. Each subject of a coloring book becomes drawings/NNN_slug.json (see interior/vector.py);
a drawing is validated, rendered and checked (ink, size, canvas bounds) before it is kept, and every call's token
usage and list-price cost go to drawings/_draw_log.json. `kdp draw book.yaml` is the command, the book page the button."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from ..schema import Book, ColoringInterior
from .vector import flatten, render_spec, validate_spec

log = logging.getLogger(__name__)

GUIDE = """You draw bold-and-easy coloring-book pages as vector specs for a simple renderer. Answer with one JSON object only, no prose, no code fences:
{"title": "...", "canvas": [1000, 1500], "stroke": 14, "shapes": [...]}
Coordinates are on a 1000 x 1500 portrait canvas (x to the right, y down). Shape objects:
- {"type":"circle","c":[x,y],"r":r}   {"type":"ellipse","c":[x,y],"rx":rx,"ry":ry,"rotate":deg}
- {"type":"arc","c":[x,y],"r":r,"start":deg,"end":deg}   angles: 0 right, 90 down, 180 left, 270 up
- {"type":"line","points":[[x,y],...]} open polyline   {"type":"polygon","points":[[x,y],...]} closed straight outline
- {"type":"curve","points":[[x,y],...],"closed":true|false} smooth curve through the points: use it for organic outlines
- {"type":"bezier","points":[[x0,y0],[cx1,cy1],[cx2,cy2],[x1,y1]]}
- {"type":"petal","c":[x,y],"r_inner":r0,"length":L,"width":W,"angle":deg} a petal or leaf outline that starts r0 from c and points at angle (-90 = up)
- {"type":"dot","c":[x,y],"r":r} filled circle for eyes and flower centres
- {"type":"repeat","count":n,"center":[x,y],"start":deg,"shapes":[...]} n copies rotated around center
- {"type":"mirror","axis_x":500,"shapes":[...]} the shapes plus their left-right mirror image
Any shape may add "stroke": 8 (thin detail), 12 (normal) or 16 (bold outline).
Rules: one clearly centred subject that fills 70 to 85 percent of the canvas height, with white space around it; big simple shapes and large
areas to colour (no enclosed cell smaller than about 50 x 50); every region closed by its outline; outlines do not cross each other except
where parts join; build symmetry with repeat and mirror; no shading, hatching, text, letters, numbers, people, faces, hands or logos;
between 8 and 60 shapes; every coordinate inside the canvas; "dot" only for small details (radius at most 25), never as a flower centre or a filled area."""


def subject_prompt(subject: str, style: str, audience: str, note: str | None = None) -> str:
    lines = [f"Draw this coloring page: {subject}.", f"Style notes: {style}", f"Audience: {audience}."]
    if note:
        lines.append(f"The previous attempt was rejected: {note}. Fix that and return the whole spec again.")
    lines.append("Return the JSON spec only.")
    return "\n".join(lines)


def ink_ratio(spec: dict, size: tuple[int, int] = (400, 600)) -> float:
    img = render_spec(spec, size)
    return 1.0 - sum(img.histogram()[200:]) / float(size[0] * size[1])


def check_spec(spec: dict) -> list[str]:
    """validate_spec plus what makes a page unusable: off-canvas drawing, a tiny subject, nearly empty or solid ink."""
    problems = validate_spec(spec)
    if problems:
        return problems
    cw, ch = (spec.get("canvas") or [1000, 1500])[:2]
    xs: list[float] = []
    ys: list[float] = []
    for _kind, pts, _extra in flatten(spec["shapes"]):
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    if xs and (min(xs) < -0.05 * cw or max(xs) > 1.05 * cw or min(ys) < -0.05 * ch or max(ys) > 1.05 * ch):
        problems.append("the drawing runs outside the canvas")
    if ys and (max(ys) - min(ys)) < 0.45 * ch:
        problems.append("the subject is too small: make it fill 70 to 85 percent of the canvas height")
    cw_ = float(cw)
    big_dots = [sh for sh in _walk(spec["shapes"]) if sh.get("type") == "dot" and float(sh.get("r", 0)) > 0.03 * cw_]
    if big_dots:
        problems.append(f"{len(big_dots)} filled dot(s) with radius over {0.03 * cw_:.0f} would print as black blobs: use a circle outline instead")
    ink = ink_ratio(spec)
    if ink < 0.015:
        problems.append(f"almost no ink ({ink:.1%}): the drawing is empty or tiny")
    elif ink > 0.35:
        problems.append(f"too much ink ({ink:.1%}): lines too dense or shapes filled")
    return problems


def _walk(shapes: list) -> list[dict]:
    out: list[dict] = []
    for sh in shapes or []:
        if isinstance(sh, dict):
            out.append(sh)
            out += _walk(sh.get("shapes") or [])
    return out


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32].strip("-") or "page"


def parse_pages(text: str | None, total: int) -> list[int]:
    """'1-3,8' -> [0, 1, 2, 7] (1-based in, 0-based out); None -> every page."""
    if not text:
        return list(range(total))
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out += [i - 1 for i in range(lo, hi + 1) if 1 <= i <= total]
    return sorted(set(out))


# ---------------------------------------------------------------- engines
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}  # USD per million tokens (in, out), 2026-10


def _call_cli(system: str, user: str, model: str | None) -> tuple[dict, dict]:
    from .. import claude_cli

    obj, res = claude_cli.ask_json(user, system=system, model=model)
    return obj, {"engine": "cli", "model": res.model, "input_tokens": res.prompt_tokens, "cached_tokens": res.cache_read, "output_tokens": res.output_tokens,
                 "thinking_tokens": res.thinking_tokens, "cost_usd": round(res.cost_usd, 5), "seconds": round(res.duration_ms / 1000, 1)}


def _call_api(system: str, user: str, model: str | None) -> tuple[dict, dict]:
    import anthropic

    from ..llm import DEFAULT_MODEL
    from ..suggest import parse_json_object

    model = model or DEFAULT_MODEL
    client = anthropic.Anthropic()
    with client.messages.stream(model=model, max_tokens=12000, system=system, messages=[{"role": "user", "content": user}]) as stream:
        msg = stream.get_final_message()
    text = "".join(getattr(b, "text", "") for b in msg.content)
    obj = parse_json_object(text)
    if not isinstance(obj, dict):
        raise RuntimeError("the API reply had no JSON object: " + text[:200])
    u = msg.usage
    cached = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    tokens_in = int(u.input_tokens) + cached + int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    price = next((v for k, v in PRICES.items() if k in model), (4.0, 20.0))
    cost = (tokens_in * price[0] + int(u.output_tokens) * price[1]) / 1e6
    return obj, {"engine": "api", "model": model, "input_tokens": tokens_in, "cached_tokens": cached, "output_tokens": int(u.output_tokens), "thinking_tokens": 0,
                 "cost_usd": round(cost, 5), "seconds": 0.0}


GEMINI_DEFAULT = "gemini-2.5-flash"
GEMINI_PRICES = {  # USD per million tokens (input, output incl. thinking) on the paid tier, ai.google.dev/gemini-api/docs/pricing 2026-10; lite before flash so the match is right
    "gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-pro": (1.25, 10.0), "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50), "gemini-3.6-flash": (0.75, 3.75), "gemini-3.8-flash": (0.75, 3.75), "gemini-3-flash": (0.50, 3.00), "gemini-3.1-pro": (2.0, 12.0)}


def _call_gemini(system: str, user: str, model: str | None) -> tuple[dict, dict]:
    """Gemini through the Gemini API (generateContent in JSON mode, key GEMINI_API_KEY from .env or the environment)."""
    import urllib.error
    import urllib.request

    from .. import keys as keymod
    from ..suggest import parse_json_object

    key = keymod.current_values().get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("chưa có GEMINI_API_KEY (Cài đặt -> Google Gemini API)")
    model = model or os.environ.get("KDP_STUDIO_GEMINI_MODEL") or GEMINI_DEFAULT
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", data=json.dumps(body).encode("utf-8"),
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        raw = urllib.request.urlopen(req, timeout=600).read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Gemini HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Gemini: {str(exc)[:200]}") from None
    data = json.loads(raw)
    cands = data.get("candidates") or []
    text = "".join(p.get("text", "") for p in ((cands[0].get("content") or {}).get("parts") or [])) if cands else ""
    obj = parse_json_object(text)
    if not isinstance(obj, dict):
        raise RuntimeError("Gemini reply had no JSON object: " + (text[:200] or json.dumps(data)[:200]))
    u = data.get("usageMetadata") or {}
    tokens_in, tokens_out, thinking = int(u.get("promptTokenCount") or 0), int(u.get("candidatesTokenCount") or 0), int(u.get("thoughtsTokenCount") or 0)
    version = str(data.get("modelVersion") or model)
    price = next((v for k, v in GEMINI_PRICES.items() if k in version), (0.0, 0.0))
    cost = (tokens_in * price[0] + (tokens_out + thinking) * price[1]) / 1e6
    return obj, {"engine": "gemini", "model": version, "input_tokens": tokens_in, "cached_tokens": int(u.get("cachedContentTokenCount") or 0),
                 "output_tokens": tokens_out + thinking, "thinking_tokens": thinking, "cost_usd": round(cost, 5), "seconds": round(time.monotonic() - t0, 1)}


def pick_engine(engine: str = "auto") -> str:
    from .. import claude_cli, llm

    if engine == "auto":
        if claude_cli.available():
            return "cli"
        if llm.claude_available():
            return "api"
        raise RuntimeError("không có cách gọi Claude: cài Claude Code (lệnh claude) và đăng nhập, hoặc đặt ANTHROPIC_API_KEY")
    if engine == "cli" and not claude_cli.available():
        raise RuntimeError("không thấy lệnh claude (Claude Code); cài và đăng nhập, hoặc dùng --engine api")
    if engine == "api" and not llm.claude_available():
        raise RuntimeError("chưa có ANTHROPIC_API_KEY (Cài đặt); hoặc dùng --engine cli")
    if engine == "gemini":
        from .. import keys as keymod

        if not (keymod.current_values().get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")):
            raise RuntimeError("chưa có GEMINI_API_KEY (Cài đặt -> Google Gemini API)")
    return engine


def page_subjects(book: Book) -> list[str]:
    """One subject per page, exactly as the build pipeline numbers them (subjects, then variations or templates)."""
    from .prompts import build_prompts

    interior = book.interior
    assert isinstance(interior, ColoringInterior)
    return [pp.subject for pp in build_prompts(interior, interior.images)]


def draw_specs(book: Book, out_dir: Path, pages: list[int] | None = None, engine: str = "auto", model: str | None = None, overwrite: bool = False,
               retries: int = 1, progress=None) -> dict:
    """Write one spec per requested page; returns {"pages": [...records...], "totals": {...}, "engine": ...}."""
    say = progress or (lambda m: log.info("%s", m))
    engine = pick_engine(engine)
    interior = book.interior
    assert isinstance(interior, ColoringInterior)
    subjects = page_subjects(book)
    pages = pages if pages is not None else list(range(len(subjects)))
    out_dir.mkdir(parents=True, exist_ok=True)
    call = {"cli": _call_cli, "api": _call_api, "gemini": _call_gemini}[engine]
    style = re.sub(r"\bColoringBookAF,?\s*", "", interior.style_prompt or "bold clean outlines, simple shapes, large areas to colour").strip()
    records: list[dict] = []
    totals = {"pages": 0, "ok": 0, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "cost_usd": 0.0, "seconds": 0.0}
    for i in pages:
        subject = subjects[i]
        path = out_dir / f"{i:03d}_{slugify(subject)}.json"
        existing = sorted(out_dir.glob(f"{i:03d}_*.json"))
        if existing and not overwrite:
            say(f"page {i + 1}: kept {existing[0].name} (use --overwrite to redraw)")
            continue
        rec = {"page": i + 1, "subject": subject, "file": path.name, "ok": False, "attempts": 0, "problems": [], "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "cost_usd": 0.0, "seconds": 0.0}
        note = None
        t0 = time.monotonic()
        for attempt in range(retries + 1):
            rec["attempts"] = attempt + 1
            try:
                spec, usage = call(GUIDE, subject_prompt(subject, style, interior.audience, note), model)
            except Exception as exc:  # noqa: BLE001 - reported per page, the run goes on
                rec["problems"].append(str(exc)[:200])
                say(f"page {i + 1} attempt {attempt + 1}: {str(exc)[:160]}")
                continue
            for k in ("input_tokens", "output_tokens", "thinking_tokens", "cost_usd"):
                rec[k] += usage.get(k, 0)
            rec["model"] = usage.get("model")
            problems = check_spec(spec)
            if not problems:
                spec.setdefault("title", subject)
                for old in existing:
                    old.unlink()
                path.write_text(json.dumps(spec, separators=(",", ":")), encoding="utf-8")
                rec["ok"] = True
                rec["chars"] = path.stat().st_size
                rec["ink"] = round(ink_ratio(spec), 3)
                break
            note = "; ".join(problems)
            rec["problems"].append(note)
            say(f"page {i + 1} attempt {attempt + 1} rejected: {note}")
        rec["seconds"] = round(time.monotonic() - t0, 1)
        records.append(rec)
        totals["pages"] += 1
        totals["ok"] += int(rec["ok"])
        for k in ("input_tokens", "output_tokens", "thinking_tokens", "cost_usd", "seconds"):
            totals[k] += rec[k]
        say(f"page {i + 1}/{len(subjects)} {'ok' if rec['ok'] else 'FAILED'}: {rec['input_tokens']:,} in + {rec['output_tokens']:,} out tokens"
            + (f" ({rec['thinking_tokens']:,} thinking)" if rec["thinking_tokens"] else "") + f", ${rec['cost_usd']:.4f}, {rec['seconds']} s - {subject}")
    totals["cost_usd"] = round(totals["cost_usd"], 4)
    log_path = out_dir / "_draw_log.json"
    old_log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else {"pages": []}
    kept = [r for r in old_log.get("pages", []) if r["page"] not in {r2["page"] for r2 in records}]
    log_path.write_text(json.dumps({"engine": engine, "pages": sorted(kept + records, key=lambda r: r["page"]), "last_run": totals}, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"engine": engine, "pages": records, "totals": totals, "log": log_path}


# ---------------------------------------------------------------- point book.yaml at the drawings
SPEC_TOOL = "Claude (vector drawing specs rendered by kdp-studio)"


def set_spec_provider(book_path: Path, folder: str = "drawings") -> list[str]:
    """interior.source -> provider spec + the drawings folder, provenance.interior_images -> ai_generated, the tool name
    added to provenance.ai_tools; edits the YAML text in place so comments survive. Returns the changes made."""
    text = book_path.read_text(encoding="utf-8")
    changes: list[str] = []
    m = re.search(r"^( +)source:[^\n]*\n((?:\1 +[^\n]*\n|[ \t]*\n)*)", text, re.M)
    if not m:
        raise ValueError("không thấy khối interior.source trong book.yaml")
    indent = m.group(1)
    new_block = f"{indent}source:\n{indent}  provider: spec\n{indent}  path: {folder}\n{indent}  seed: 7\n{indent}  size: 1024x1536\n"
    if m.group(0) != new_block:
        text = text[:m.start()] + new_block + text[m.end():]
        changes.append(f"interior.source -> provider spec, path {folder}")
    m_img = re.search(r"^( +)interior_images: *([^\s#]+)", text, re.M)
    if m_img and m_img.group(2) != "ai_generated":
        text = text[:m_img.start()] + f"{m_img.group(1)}interior_images: ai_generated" + text[m_img.end():]
        changes.append("provenance.interior_images -> ai_generated")
    if SPEC_TOOL not in text:
        flow = re.search(r"^( +)ai_tools: *\[([^\]]*)\]", text, re.M)
        block = re.search(r"^( +)ai_tools: *\n(?=( *)- )", text, re.M)
        if flow:
            items = [s.strip() for s in flow.group(2).split(",") if s.strip()] + [json.dumps(SPEC_TOOL)]
            text = text[:flow.start()] + f"{flow.group(1)}ai_tools: [{', '.join(items)}]" + text[flow.end():]
        elif block:
            text = text[:block.end()] + f"{block.group(2)}- {json.dumps(SPEC_TOOL)}\n" + text[block.end():]  # same indent as the existing items
        else:
            text = text.rstrip("\n") + f"\nprovenance:\n  ai_tools: [{json.dumps(SPEC_TOOL)}]\n"
        changes.append(f"provenance.ai_tools += {SPEC_TOOL}")
    if changes:
        book_path.write_text(text, encoding="utf-8")
        from ..schema import load_book

        load_book(book_path)  # the edited file must still validate
    return changes
