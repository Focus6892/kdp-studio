"""Page quality checks: a fast local heuristic, a free local OWLv2 content filter (people / nudity)
and an optional Claude vision review."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

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
    if solid > opts.max_solid_black:
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


# ---------------------------------------------------------------- content filter: people / nudity (free, local)
# Open-vocabulary detection (OWLv2, Apache-2.0) finds a stylised figure hidden in dense floral line art where
# whole-image CLIP scoring does not. Calibrated 2026-10-24 on 30 generated pages (6 with people): the max score
# over PEOPLE_QUERIES was >= 0.33 on every page with a person and <= 0.21 on every page without.
PEOPLE_QUERIES = ["a portrait of a woman with flowers in her hair", "a human face", "a girl", "a human figure"]
NUDITY_QUERIES = ["a naked body"]
_detector = {}


def decide_content(scores: dict[str, float], opts: QAOptions) -> list[str]:
    """Pure decision on per-query max detection scores, testable without the model."""
    people = max((scores.get(k, 0.0) for k in PEOPLE_QUERIES), default=0.0)
    nude = max((scores.get(k, 0.0) for k in NUDITY_QUERIES), default=0.0)
    reasons = []
    if nude >= 0.10:
        reasons.append(f"possible nudity (score {nude:.2f})")
    if people >= opts.people_threshold:
        reasons.append(f"contains a person (score {people:.2f} >= {opts.people_threshold})")
    return reasons


def _load_detector(model_name: str, device: str):
    key = (model_name, device)
    if key not in _detector:
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        _detector[key] = (Owlv2Processor.from_pretrained(model_name), Owlv2ForObjectDetection.from_pretrained(model_name).to(device).eval())
    return _detector[key]


def content_qa(image: "Image.Image | Path", opts: QAOptions) -> QAResult | None:
    """Reject pages showing people or nudity, judged on the colour original. Returns None when the model stack
    is unavailable or KDP_STUDIO_SKIP_CONTENT_QA=1 (tests), so a build never stalls on it. Runs on the CPU by
    default (about 5-10 s per page) so it never competes with the image model for a small GPU's memory."""
    if os.environ.get("KDP_STUDIO_SKIP_CONTENT_QA") == "1":
        return None
    try:
        import torch

        processor, model = _load_detector(opts.content_model, opts.content_device)
    except Exception as exc:  # noqa: BLE001 - torch/transformers/scipy missing or download failed
        log.warning("content filter unavailable (%s); pages are not screened for people", str(exc).splitlines()[0][:120])
        return None
    queries = PEOPLE_QUERIES + NUDITY_QUERIES
    img = Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB")
    with torch.no_grad():
        inputs = processor(text=[queries], images=img, return_tensors="pt").to(opts.content_device)
        out = model(**inputs)
        res = processor.post_process_grounded_object_detection(out, threshold=0.01, target_sizes=torch.tensor([[img.height, img.width]]).to(opts.content_device), text_labels=[queries])[0]
    scores = {qq: 0.0 for qq in queries}
    for sc, label in zip(res["scores"].tolist(), res["text_labels"]):
        scores[label] = max(scores[label], sc)
    reasons = decide_content(scores, opts)
    top = sorted(scores.items(), key=lambda kv: -kv[1])[:2]
    return QAResult(ok=not reasons, source="owlv2", reasons=reasons, notes="; ".join(f"{k} {v:.2f}" for k, v in top))
