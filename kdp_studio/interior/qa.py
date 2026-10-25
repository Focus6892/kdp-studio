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
from .cleanup import component_areas, ink_ratio

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

    # Busy, textured pages (stippling, foliage, crowd scenes) shatter into thousands of ink pieces after cleanup; a
    # bold-and-easy drawing is a few dozen connected strokes. Measured 2026-10-25 on 30 FLUX pages: 20-180 pieces.
    stats = fragmentation(art)
    if stats is not None:
        pieces, frag = stats
        if pieces > opts.max_components:
            reasons.append(f"too busy ({pieces} separate ink pieces > {opts.max_components})")
        if frag > opts.max_fragment_ink:
            reasons.append(f"fragmented lines ({frag:.0%} of the ink is in tiny pieces > {opts.max_fragment_ink:.0%})")
    # Dense foliage, stippling and shading leave most of the drawing as cells too small to color. Measured 2026-10-25:
    # 30 Cloudflare FLUX bold-and-easy pages <= 4% of the page; the 8 visibly over-detailed SD1.5 pages 10-19%.
    tiny = tiny_white_share(art)
    if tiny is not None and tiny > opts.max_tiny_white:
        reasons.append(f"too detailed to color ({tiny:.0%} of the page is tiny enclosed cells > {opts.max_tiny_white:.0%})")

    return QAResult(ok=not reasons, source="heuristic", reasons=reasons, ink_ratio=ratio)


def tiny_white_share(art: Image.Image, cell_frac: float = 0.001) -> float | None:
    """Share of the page covered by enclosed white cells smaller than `cell_frac` of the page (about 1 cm square on a
    letter page). The largest white region is the outer background and is left out. None without scipy."""
    mask = np.asarray(art) < 128
    areas = component_areas(~mask)
    if areas is None:
        return None
    if len(areas) <= 1:
        return 0.0
    inner = np.sort(areas)[:-1]
    return float(inner[inner < cell_frac * mask.size].sum() / mask.size)


def fragmentation(art: Image.Image) -> tuple[int, float] | None:
    """(number of separate ink pieces, share of ink in pieces smaller than 0.05% of the page); None without scipy."""
    mask = np.asarray(art) < 128
    areas = component_areas(mask)
    if areas is None:
        return None
    if len(areas) == 0:
        return 0, 0.0
    tiny = areas < max(1, int(0.0005 * mask.size))
    return int(len(areas)), float(areas[tiny].sum() / areas.sum())


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
# Fake signatures / pseudo-text ("Cdoorine Llloddna") appear near the bottom of 4 of 30 SD1.5 pages. OWLv2 scores them
# highest under "a watermark" (0.39-0.61); plain "text"/"letters" queries score ~0 on this kind of writing.
TEXT_QUERIES = ["a watermark", "a signature"]
_detector = {}


def decide_content(scores: dict[str, float], opts: QAOptions) -> list[str]:
    """Pure decision on per-query max detection scores, testable without the model."""
    people = max((scores.get(k, 0.0) for k in PEOPLE_QUERIES), default=0.0)
    nude = max((scores.get(k, 0.0) for k in NUDITY_QUERIES), default=0.0)
    text = max((scores.get(k, 0.0) for k in TEXT_QUERIES), default=0.0)
    reasons = []
    if nude >= 0.10:
        reasons.append(f"possible nudity (score {nude:.2f})")
    if opts.reject_people and people >= opts.people_threshold:
        reasons.append(f"contains a person (score {people:.2f} >= {opts.people_threshold})")
    if opts.reject_text and text >= opts.text_threshold:
        reasons.append(f"contains text or a signature (score {text:.2f} >= {opts.text_threshold})")
    return reasons


def _load_detector(model_name: str, device: str):
    key = (model_name, device)
    if key not in _detector:
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        _detector[key] = (Owlv2Processor.from_pretrained(model_name), Owlv2ForObjectDetection.from_pretrained(model_name).to(device).eval())
    return _detector[key]


def content_qa(image: "Image.Image | Path", opts: QAOptions) -> QAResult | None:
    """Reject pages showing people, nudity or written text, judged on the colour original. Returns None when the model stack
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
    queries = PEOPLE_QUERIES + NUDITY_QUERIES + TEXT_QUERIES
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
