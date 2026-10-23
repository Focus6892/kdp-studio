"""Page quality checks: a fast local heuristic and an optional Claude vision review."""

from __future__ import annotations

import base64
import io
import json
import logging
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter

from ..schema import QAOptions
from .cleanup import ink_ratio

log = logging.getLogger(__name__)


@dataclass
class QAResult:
    ok: bool
    source: str
    reasons: list[str] = field(default_factory=list)
    ink_ratio: float = 0.0
    notes: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "source": self.source, "reasons": self.reasons, "ink_ratio": round(self.ink_ratio, 4), "notes": self.notes}


def heuristic_qa(art: Image.Image, opts: QAOptions) -> QAResult:
    reasons: list[str] = []
    ratio = ink_ratio(art)
    if ratio < opts.min_ink_ratio:
        reasons.append(f"too little ink ({ratio:.3f} < {opts.min_ink_ratio})")
    if ratio > opts.max_ink_ratio:
        reasons.append(f"too much ink ({ratio:.3f} > {opts.max_ink_ratio})")

    # Solid black regions survive a heavy erosion of the ink mask; lines do not.
    small = art.resize((max(1, art.width // 4), max(1, art.height // 4)), Image.BOX)
    eroded = small.filter(ImageFilter.MaxFilter(9))  # ink is dark: max() shrinks dark regions
    solid = float((np.asarray(eroded) < 128).mean())
    if solid > 0.004:
        reasons.append(f"large solid black areas ({solid:.3%} of page after erosion)")

    return QAResult(ok=not reasons, source="heuristic", reasons=reasons, ink_ratio=ratio)


QA_SCHEMA = {
    "type": "object",
    "properties": {
        "clean_line_art": {"type": "boolean", "description": "Clear black outlines on white, suitable for coloring"},
        "contains_text": {"type": "boolean", "description": "Any letters, numbers, words or signatures"},
        "large_black_areas": {"type": "boolean"},
        "visual_artifacts": {"type": "boolean", "description": "Broken anatomy, floating fragments, noise, half-drawn objects"},
        "ip_or_brand_risk": {"type": "boolean", "description": "Recognizable copyrighted characters, logos or brands"},
        "age_appropriate": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": ["clean_line_art", "contains_text", "large_black_areas", "visual_artifacts", "ip_or_brand_risk", "age_appropriate", "notes"],
    "additionalProperties": False,
}

QA_PROMPT = (
    "You are checking a single coloring-book page before it is printed. Judge it strictly "
    "against the schema fields. Audience: {audience}. Keep notes under 40 words."
)


def _downscaled_jpeg_b64(art: Image.Image, long_side: int = 1024) -> str:
    im = art.convert("L")
    scale = long_side / max(im.size)
    if scale < 1:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def claude_qa(art: Image.Image, opts: QAOptions, audience: str) -> QAResult | None:
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; skipping Claude QA")
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=opts.model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _downscaled_jpeg_b64(art)}},
                    {"type": "text", "text": QA_PROMPT.format(audience=audience)},
                ],
            }],
            output_config={"format": {"type": "json_schema", "schema": QA_SCHEMA}},
        )
    except anthropic.AuthenticationError:
        log.warning("Anthropic authentication failed; skipping Claude QA")
        return None
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit; skipping Claude QA for this page")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Anthropic API error %s; skipping Claude QA", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("Could not reach the Anthropic API; skipping Claude QA")
        return None

    if response.stop_reason == "refusal":
        return QAResult(ok=False, source="claude", reasons=["model declined to review the image"])
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return None
    data = json.loads(text)
    reasons = []
    if not data["clean_line_art"]:
        reasons.append("not clean line art")
    if data["contains_text"]:
        reasons.append("contains text")
    if data["large_black_areas"]:
        reasons.append("large black areas")
    if data["visual_artifacts"]:
        reasons.append("visual artifacts")
    if data["ip_or_brand_risk"]:
        reasons.append("IP/brand risk")
    if not data["age_appropriate"]:
        reasons.append("not age appropriate")
    return QAResult(ok=not reasons, source="claude", reasons=reasons, notes=data.get("notes", ""))
