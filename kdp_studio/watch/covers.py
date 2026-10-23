"""Competitor cover analysis: dominant palette offline, style/legibility review with Claude vision."""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path

from PIL import Image

from ..llm import claude_available

log = logging.getLogger(__name__)

COVER_SCHEMA = {
    "type": "object",
    "properties": {
        "art_style": {"type": "string"},
        "palette": {"type": "array", "items": {"type": "string"}, "description": "3-5 dominant colors as plain words"},
        "title_treatment": {"type": "string", "description": "font style, size, placement, contrast"},
        "mood": {"type": "string"},
        "thumbnail_legible": {"type": "boolean", "description": "Is the title readable at Amazon thumbnail size?"},
        "cliches": {"type": "array", "items": {"type": "string"}},
        "differentiation_ideas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["art_style", "palette", "title_treatment", "mood", "thumbnail_legible", "cliches", "differentiation_ideas"],
    "additionalProperties": False,
}


def dominant_colors(path: Path, n: int = 5) -> list[str]:
    with Image.open(path) as im:
        small = im.convert("RGB").resize((120, 160))
        q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
        palette = q.getpalette()[: n * 3]
        counts = sorted(q.getcolors(), reverse=True)
    out = []
    for count, idx in counts[:n]:
        r, g, b = palette[idx * 3 : idx * 3 + 3]
        out.append(f"#{r:02X}{g:02X}{b:02X}")
    return out


def _b64_jpeg(path: Path, long_side: int = 1024) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        scale = long_side / max(im.size)
        if scale < 1:
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def claude_cover_review(path: Path, model: str = "claude-opus-5-5") -> dict | None:
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64_jpeg(path)}},
                    {"type": "text", "text": "Review this book cover as a KDP cover designer studying a competitor. Judge thumbnail legibility at 100px wide."},
                ],
            }],
            output_config={"format": {"type": "json_schema", "schema": COVER_SCHEMA}},
        )
    except anthropic.AnthropicError as exc:
        log.warning("Claude cover review failed: %s", exc)
        return None
    if response.stop_reason == "refusal":
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    return json.loads(text) if text else None


def analyze_covers(paths: list[Path], use_claude: bool = True) -> list[dict]:
    out = []
    for p in paths:
        entry: dict = {"file": str(p), "palette_hex": dominant_colors(p)}
        if use_claude and claude_available():
            review = claude_cover_review(p)
            if review:
                entry.update(review)
                entry["source"] = "claude"
        entry.setdefault("source", "palette-only")
        out.append(entry)
    return out


def covers_markdown(results: list[dict]) -> str:
    lines = ["# Cover analysis", ""]
    for r in results:
        lines.append(f"## {Path(r['file']).name}")
        lines.append(f"- Palette: {', '.join(r.get('palette_hex', []))}")
        if r.get("source") == "claude":
            lines.append(f"- Style: {r.get('art_style')} · mood: {r.get('mood')}")
            lines.append(f"- Title treatment: {r.get('title_treatment')} · thumbnail legible: {r.get('thumbnail_legible')}")
            if r.get("cliches"):
                lines.append("- Clichés: " + "; ".join(r["cliches"]))
            if r.get("differentiation_ideas"):
                lines.append("- Differentiation: " + "; ".join(r["differentiation_ideas"]))
        lines.append("")
    return "\n".join(lines) + "\n"
