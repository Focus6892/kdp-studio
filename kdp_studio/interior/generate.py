"""Image providers for interior pages and cover art.

- PlaceholderProvider: deterministic procedural line art (offline; lets the whole
  pipeline run and be tested without any API key).
- FolderProvider: use images you already have (e.g. exported from ComfyUI/Midjourney).
- OpenAIImagesProvider (gpt-image-1), GoogleImagenProvider (Imagen via the Gemini API) and
  StabilityProvider (Stable Image core/ultra/sd3): real generators behind one interface, keys from
  the environment or the project's .env (OPENAI_API_KEY, GEMINI_API_KEY, STABILITY_API_KEY).
  Requests retry on 429/5xx; API refusals surface as ProviderError with the API's message.

Any provider's output counts as AI-generated for KDP disclosure purposes except
FolderProvider, whose provenance you declare yourself in book.yaml.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw

from ..schema import ArtSource, ImageSource

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class ProviderExhausted(RuntimeError):
    """Raised when a folder provider has no image left for the requested index."""


class ImageProvider(Protocol):
    name: str

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path: ...


# --------------------------------------------------------------------------- placeholder art
def _petal(cx: float, cy: float, r_inner: float, length: float, width: float, angle: float, steps: int = 28) -> list[tuple[float, float]]:
    ux, uy = math.cos(angle), math.sin(angle)
    pts = []
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        ex = (length / 2) * (1 + math.cos(t))
        ey = (width / 2) * math.sin(t)
        pts.append((cx + ux * (r_inner + ex) - uy * ey, cy + uy * (r_inner + ex) + ux * ey))
    return pts


def _flower(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, cy: float, radius: float, stroke: int) -> None:
    petals = rng.randint(5, 12)
    core = radius * rng.uniform(0.18, 0.3)
    length = radius - core
    width = (2 * math.pi * (core + length / 2) / petals) * rng.uniform(0.75, 1.1)
    for k in range(petals):
        a = 2 * math.pi * k / petals
        draw.line(_petal(cx, cy, core, length, width, a), fill=0, width=stroke, joint="curve")
    if rng.random() < 0.6:
        for k in range(petals):
            a = 2 * math.pi * (k + 0.5) / petals
            draw.line(_petal(cx, cy, core * 1.1, length * 0.55, width * 0.7, a), fill=0, width=stroke, joint="curve")
    draw.ellipse((cx - core, cy - core, cx + core, cy + core), outline=0, width=stroke)
    dots = rng.randint(5, 9)
    for k in range(dots):
        a = 2 * math.pi * k / dots
        r = core * 0.55
        dx, dy = cx + r * math.cos(a), cy + r * math.sin(a)
        dr = max(stroke, core * 0.09)
        draw.ellipse((dx - dr, dy - dr, dx + dr, dy + dr), outline=0, width=stroke)


def _leaf(draw: ImageDraw.ImageDraw, x: float, y: float, length: float, width: float, angle: float, stroke: int) -> None:
    draw.line(_petal(x, y, 0, length, width, angle), fill=0, width=stroke, joint="curve")
    ux, uy = math.cos(angle), math.sin(angle)
    draw.line([(x, y), (x + ux * length * 0.9, y + uy * length * 0.9)], fill=0, width=max(2, stroke // 2))


def _frame(draw: ImageDraw.ImageDraw, w: int, h: int, margin: float, stroke: int) -> None:
    draw.rounded_rectangle((margin, margin, w - margin, h - margin), radius=margin, outline=0, width=stroke)


def draw_line_art(rng: random.Random, size: tuple[int, int]) -> Image.Image:
    """Deterministic bold line art: flower, mandala or bouquet with a frame."""
    w, h = size
    img = Image.new("L", size, 255)
    d = ImageDraw.Draw(img)
    stroke = max(6, min(w, h) // 160)
    margin = min(w, h) * 0.06
    frame_style = rng.choice(["single", "double", "none"])
    if frame_style != "none":
        _frame(d, w, h, margin, stroke)
    if frame_style == "double":
        _frame(d, w, h, margin * 1.6, max(2, stroke // 2))
    motif = rng.choice(["flower", "mandala", "bouquet"])
    cx, cy = w / 2 + rng.uniform(-0.04, 0.04) * w, h * rng.uniform(0.36, 0.46)
    if motif == "flower":
        radius = min(w, h) * rng.uniform(0.26, 0.34)
        _flower(d, rng, cx, cy, radius, stroke)
        stem_top = cy + radius * 0.9
        stem_bottom = h - margin * 1.8
        d.line([(cx, stem_top), (cx, stem_bottom)], fill=0, width=stroke)
        leaves = rng.randint(2, 4)
        for i in range(leaves):
            y = stem_top + (stem_bottom - stem_top) * (0.25 + 0.6 * i / max(1, leaves - 1))
            side = -1 if i % 2 == 0 else 1
            _leaf(d, cx, y, radius * 0.7, radius * 0.32, math.radians(90 - side * 55), stroke)
    elif motif == "mandala":
        cy = h / 2
        rmax = min(w, h) * 0.42
        rings = rng.randint(3, 5)
        for k in range(rings):
            r = rmax * (k + 1) / rings
            n = 6 + 2 * k
            length = (rmax / rings) * 0.8
            width = (2 * math.pi * r / n) * 0.8
            for j in range(n):
                a = 2 * math.pi * (j + (0.5 if k % 2 else 0)) / n
                d.line(_petal(cx, cy, r - length * 0.9, length, width, a), fill=0, width=stroke, joint="curve")
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=0, width=stroke)
        _flower(d, rng, cx, cy, rmax / rings * 0.8, stroke)
    else:  # bouquet
        base_y = h - margin * 1.6
        vw = w * 0.28
        vh = h * 0.22
        vase = [(cx - vw / 2, base_y - vh), (cx + vw / 2, base_y - vh), (cx + vw / 3, base_y), (cx - vw / 3, base_y)]
        d.polygon(vase, outline=0, width=stroke)
        d.line([(cx - vw / 2, base_y - vh), (cx + vw / 2, base_y - vh)], fill=0, width=stroke)
        count = rng.randint(3, 5)
        for i in range(count):
            fx = cx + (i - (count - 1) / 2) * vw * 0.55 + rng.uniform(-w * 0.03, w * 0.03)
            fy = base_y - vh - h * rng.uniform(0.18, 0.34)
            radius = min(w, h) * rng.uniform(0.09, 0.14)
            d.line([(fx, fy + radius * 0.8), (cx + (fx - cx) * 0.3, base_y - vh)], fill=0, width=stroke)
            _flower(d, rng, fx, fy, radius, stroke)
    return img


class PlaceholderProvider:
    name = "placeholder"

    def __init__(self, seed: int = 7):
        self.seed = seed

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        rng = random.Random(f"{self.seed}:{index}:{attempt}:{prompt}")
        img = draw_line_art(rng, size)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, "PNG")
        return out_path


class SpecProvider:
    """Vector drawing specs (JSON, see interior/vector.py) rendered to crisp line art - no image model at all."""

    name = "spec"

    def __init__(self, folder: Path):
        from .vector import load_specs

        self.folder = folder
        self.specs = load_specs(folder)

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        from .vector import render_spec, validate_spec

        pos = index if attempt == 0 else len(self.specs) - 1 - (index + attempt) % len(self.specs)
        if pos >= len(self.specs) or pos < 0:
            raise ProviderExhausted(f"{len(self.specs)} drawing spec(s) in {self.folder}; none left for page {index}")
        path, spec = self.specs[pos]
        problems = validate_spec(spec)
        if problems:
            raise ProviderError(f"{path.name}: " + "; ".join(problems))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        render_spec(spec, size).save(out_path, "PNG")
        return out_path


class FolderProvider:
    name = "folder"

    def __init__(self, folder: Path):
        self.folder = folder
        self.files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if not self.files:
            raise FileNotFoundError(f"No images found in {folder}")

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        # Retries move on to unused files at the end of the list.
        pos = index if attempt == 0 else len(self.files) - 1 - (index + attempt) % len(self.files)
        if pos >= len(self.files) or pos < 0:
            raise ProviderExhausted(f"Folder has {len(self.files)} images; none left for page {index}")
        src = self.files[pos]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.convert("RGB").save(out_path, "PNG")
        return out_path


log = logging.getLogger(__name__)

# rough list prices per image in USD (2026-10), only for the running estimate printed by image-test / build
APPROX_COST_USD = {"spec": 0.0, "local": 0.0, "openai": 0.07, "google": 0.04, "stability": 0.03, "pollinations": 0.0, "cloudflare": 0.0, "placeholder": 0.0, "folder": 0.0, "file": 0.0}
API_PROVIDERS = ("openai", "google", "stability", "pollinations", "cloudflare", "local")  # network or GPU: replaced by KDP_STUDIO_FORCE_PROVIDER in tests
FREE_PROVIDERS = ("pollinations", "cloudflare")


class ProviderError(RuntimeError):
    """The image API refused the request (bad key, moderation, quota...) - the message carries the API's text."""


def _request(req: urllib.request.Request, timeout: int = 180, tries: int = 3) -> bytes:
    """urlopen with retries on 408/409/429/5xx and network hiccups; other 4xx are raised at once."""
    delay = 2.0
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            if (exc.code in (408, 409, 429) or exc.code >= 500) and attempt + 1 < tries:
                log.info("image API HTTP %s, retrying in %.0f s", exc.code, delay)
                time.sleep(delay)
                delay *= 2.5
                continue
            raise ProviderError(f"HTTP {exc.code} from {req.full_url}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt + 1 < tries:
                time.sleep(delay)
                delay *= 2.5
                continue
            raise ProviderError(f"network error talking to {req.full_url}: {exc}") from None
    raise ProviderError("image API: retries exhausted")


def _write(out_path: Path, data: bytes) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path


def _aspect(size: tuple[int, int], choices: dict[str, float]) -> str:
    """The provider's aspect-ratio token closest to the requested pixel size."""
    target = size[0] / size[1]
    return min(choices, key=lambda k: abs(choices[k] - target))


def _with_negative(prompt: str, negative: str | None) -> str:
    return f"{prompt}. Avoid: {negative}" if negative else prompt


def _multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = "----kdpstudio" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _key(var: str, *alternatives: str) -> str:
    for name in (var, *alternatives):
        value = os.environ.get(name)
        if value:
            return value
    raise ProviderError(f"{var} is not set: put it in {Path('.env').resolve().parent / '.env'} as {var}=... or export it in the shell")


class OpenAIImagesProvider:
    """OpenAI Images API, gpt-image-1 family (b64 PNG back). Written from the public docs, verify with a key."""

    name = "openai"
    endpoint = "https://api.openai.com/v1/images/generations"
    SIZES = {"1024x1024": 1.0, "1024x1536": 1024 / 1536, "1536x1024": 1536 / 1024}

    def __init__(self, model: str | None, size: str, api_key: str | None = None, quality: str = "medium", negative_prompt: str | None = None):
        self.model = model or "gpt-image-1"
        self.size = size if size in self.SIZES else "1024x1536"
        self.quality = quality
        self.negative_prompt = negative_prompt
        self.api_key = api_key or _key("OPENAI_API_KEY")

    def body(self, prompt: str) -> dict:
        return {"model": self.model, "prompt": _with_negative(prompt, self.negative_prompt), "n": 1, "size": self.size, "quality": self.quality, "output_format": "png"}

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        req = urllib.request.Request(self.endpoint, data=json.dumps(self.body(prompt)).encode(), headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        item = json.loads(_request(req))["data"][0]
        data = base64.b64decode(item["b64_json"]) if item.get("b64_json") else _request(urllib.request.Request(item["url"]))
        return _write(out_path, data)


class GoogleImagenProvider:
    """Imagen through the Gemini API (`models/<model>:predict`, header x-goog-api-key). Written from the public docs."""

    name = "google"
    RATIOS = {"1:1": 1.0, "3:4": 0.75, "4:3": 4 / 3, "9:16": 9 / 16, "16:9": 16 / 9}

    def __init__(self, model: str | None, size: str, api_key: str | None = None, negative_prompt: str | None = None):
        self.model = model or "imagen-4.0-generate-001"
        self.negative_prompt = negative_prompt
        self.api_key = api_key or _key("GEMINI_API_KEY", "GOOGLE_API_KEY")

    @property
    def endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:predict"

    def body(self, prompt: str, size: tuple[int, int]) -> dict:
        return {"instances": [{"prompt": _with_negative(prompt, self.negative_prompt)}], "parameters": {"sampleCount": 1, "aspectRatio": _aspect(size, self.RATIOS), "personGeneration": "allow_adult"}}

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        req = urllib.request.Request(self.endpoint, data=json.dumps(self.body(prompt, size)).encode(), headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        payload = json.loads(_request(req))
        preds = payload.get("predictions") or []
        if not preds or not preds[0].get("bytesBase64Encoded"):
            raise ProviderError(f"Imagen returned no image (filtered?): {json.dumps(payload)[:400]}")
        return _write(out_path, base64.b64decode(preds[0]["bytesBase64Encoded"]))


class StabilityProvider:
    """Stability AI Stable Image (core / ultra / sd3.*) - multipart request, raw PNG back. Written from the public docs."""

    name = "stability"
    RATIOS = {"1:1": 1.0, "2:3": 2 / 3, "3:2": 1.5, "4:5": 0.8, "5:4": 1.25, "9:16": 9 / 16, "16:9": 16 / 9}

    def __init__(self, model: str | None, size: str, api_key: str | None = None, negative_prompt: str | None = None, style_preset: str | None = "line-art"):
        self.model = model or "core"
        self.negative_prompt = negative_prompt
        self.style_preset = style_preset
        self.api_key = api_key or _key("STABILITY_API_KEY")

    @property
    def endpoint(self) -> str:
        family = "sd3" if self.model.startswith("sd3") else self.model
        return f"https://api.stability.ai/v2beta/stable-image/generate/{family}"

    def fields(self, prompt: str, size: tuple[int, int]) -> dict[str, str]:
        f = {"prompt": prompt, "aspect_ratio": _aspect(size, self.RATIOS), "output_format": "png"}
        if self.negative_prompt:
            f["negative_prompt"] = self.negative_prompt
        if self.style_preset and self.model == "core":
            f["style_preset"] = self.style_preset
        if self.model.startswith("sd3"):
            f["model"] = self.model
        return f

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        body, ctype = _multipart(self.fields(prompt, size))
        req = urllib.request.Request(self.endpoint, data=body, headers={"Authorization": f"Bearer {self.api_key}", "Accept": "image/*", "Content-Type": ctype})
        return _write(out_path, _request(req))


class PollinationsProvider:
    """pollinations.ai - free, keyless FLUX endpoint (GET .../prompt/<text>). Anonymous calls are rate-limited
    and come back downsized (about 630x940 for a 1024x1536 request); a free account token
    (POLLINATIONS_API_KEY) lifts both. Images are JPEG; the cleanup step re-thresholds them anyway."""

    name = "pollinations"
    endpoint = "https://image.pollinations.ai/prompt/"

    def __init__(self, model: str | None, size: str, negative_prompt: str | None = None, min_interval_s: float = 4.0):
        self.model = model or "flux"
        self.size = size
        self.negative_prompt = negative_prompt
        self.min_interval_s = min_interval_s
        self.token = os.environ.get("POLLINATIONS_API_KEY")
        self._last = 0.0

    def url(self, prompt: str, seed: int, size: tuple[int, int]) -> str:
        q = {"width": size[0], "height": size[1], "model": self.model, "nologo": "true", "enhance": "false", "safe": "true", "seed": seed}
        return self.endpoint + urllib.parse.quote(_with_negative(prompt, self.negative_prompt)) + "?" + urllib.parse.urlencode(q)

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        wait = self.min_interval_s - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)  # be polite to a free service
        headers = {"User-Agent": "kdp-studio/0.1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url(prompt, 1000 * index + attempt + 1, size), headers=headers)
        data = _request(req, timeout=240, tries=4)
        self._last = time.time()
        if not data or data[:4] not in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb", b"\x89PNG") and not data.startswith(b"RIFF"):
            raise ProviderError(f"pollinations returned no image ({data[:80]!r})")
        return _write(out_path, data)


class CloudflareProvider:
    """Cloudflare Workers AI (free daily allowance with a Cloudflare account): POST accounts/<id>/ai/run/<model>.
    Default model @cf/black-forest-labs/flux-1-schnell returns {"result": {"image": <base64 jpeg>}} at 1024x1024;
    @cf/stabilityai/stable-diffusion-xl-base-1.0 honours width/height and returns raw PNG bytes."""

    name = "cloudflare"

    def __init__(self, model: str | None, size: str, negative_prompt: str | None = None):
        if model and not model.startswith("@cf/"):
            log.warning("cloudflare: model %r is not a Workers AI id; using flux-1-schnell", model)
            model = None
        self.model = model or "@cf/black-forest-labs/flux-1-schnell"
        self.negative_prompt = negative_prompt
        self.account = _key("CF_ACCOUNT_ID")
        self.token = _key("CF_API_TOKEN")

    @property
    def endpoint(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account}/ai/run/{self.model}"

    def body(self, prompt: str, size: tuple[int, int]) -> dict:
        if "flux" in self.model:
            return {"prompt": _with_negative(prompt, self.negative_prompt), "steps": 6}
        # SDXL / DreamShaper-LCM (Beta): width/height 256-2048; LCM wants few steps and low guidance
        lcm = "lcm" in self.model
        b = {"prompt": prompt, "width": min(size[0], 2048), "height": min(size[1], 2048), "num_steps": 8 if lcm else 20}
        if lcm:
            b["guidance"] = 1.5
        if self.negative_prompt:
            b["negative_prompt"] = self.negative_prompt
        return b

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        req = urllib.request.Request(self.endpoint, data=json.dumps(self.body(prompt, size)).encode(), headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        data = _request(req, timeout=240)
        if data[:1] == b"{":
            payload = json.loads(data)
            image = (payload.get("result") or {}).get("image")
            if not payload.get("success", True) or not image:
                raise ProviderError(f"Workers AI: {json.dumps(payload)[:400]}")
            data = base64.b64decode(image)
        return _write(out_path, data)


class LocalDiffusersProvider:
    """Stable Diffusion 1.5-family checkpoint (+ optional LoRA) on the local GPU through `diffusers`.
    Free and unlimited; a 4 GB card runs fp16 at 512x768 with attention slicing in roughly 30-60 s per page.
    Install with `kdp local-setup`; models download once into the Hugging Face cache."""

    name = "local"
    DEFAULT_MODEL = "Lykon/dreamshaper-8"

    def __init__(self, model, size, negative_prompt=None, lora=None, lora_scale=0.8, steps=28, guidance=7.0, seed=7):
        self.model = model or self.DEFAULT_MODEL
        self.size = size
        self.negative_prompt = negative_prompt
        self.lora, self.lora_scale, self.steps, self.guidance, self.seed = lora, lora_scale, steps, guidance, seed
        self._pipe = None

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        try:
            import torch
            from diffusers import StableDiffusionPipeline
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise ProviderError("local provider needs torch + diffusers (+ peft for LoRA): run `kdp local-setup`") from exc
        if self.lora:
            try:
                import peft  # noqa: F401 - diffusers loads LoRA weights through PEFT
            except ImportError as exc:  # pragma: no cover
                raise ProviderError("LoRA needs the peft package: python -m pip install --user peft") from exc
        cuda = torch.cuda.is_available()
        kw = {"dtype": torch.float16 if cuda else torch.float32, "safety_checker": None, "requires_safety_checker": False}  # diffusers >= 0.36 ('torch_dtype' before)
        src = Path(self.model)
        pipe = StableDiffusionPipeline.from_single_file(str(src), **kw) if src.suffix == ".safetensors" and src.is_file() else StableDiffusionPipeline.from_pretrained(self.model, **kw)
        if self.lora:
            repo, _, fname = self.lora.partition(":")
            lp = Path(self.lora)
            if lp.is_file():
                pipe.load_lora_weights(str(lp.parent), weight_name=lp.name)
            elif fname:
                pipe.load_lora_weights(repo, weight_name=fname)
            else:
                pipe.load_lora_weights(repo)
            pipe.fuse_lora(lora_scale=self.lora_scale)
        pipe = pipe.to("cuda" if cuda else "cpu")
        if cuda:  # memory savers for 4 GB cards; method names moved between diffusers releases
            if hasattr(pipe, "enable_attention_slicing"):
                pipe.enable_attention_slicing("max")
            if hasattr(pipe, "enable_vae_slicing"):
                pipe.enable_vae_slicing()
            elif hasattr(getattr(pipe, "vae", None), "enable_slicing"):
                pipe.vae.enable_slicing()
        else:
            log.warning("no CUDA device: generating on the CPU (minutes per page)")
        pipe.set_progress_bar_config(disable=True)
        self._pipe = pipe
        return pipe

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        import torch

        pipe = self._load()
        w, h = (int(x) for x in self.size.lower().split("x"))
        w, h = max(256, w // 8 * 8), max(256, h // 8 * 8)
        gen = torch.Generator(device=pipe.device.type).manual_seed(self.seed * 1000 + index * 10 + attempt)
        image = pipe(prompt=prompt, negative_prompt=self.negative_prompt or None, width=w, height=h, num_inference_steps=self.steps, guidance_scale=self.guidance, generator=gen).images[0]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path, "PNG")
        return out_path


def make_provider(source: ImageSource | ArtSource, base_dir: Path, negative_prompt: str | None = None) -> ImageProvider:
    forced = os.environ.get("KDP_STUDIO_FORCE_PROVIDER")  # tests/CI: keep example books off the GPU and the network
    if forced and source.provider in API_PROVIDERS and forced in ("placeholder", "spec"):  # only network/GPU providers are replaced
        log.info("KDP_STUDIO_FORCE_PROVIDER=%s overrides provider %s", forced, source.provider)
        source = source.model_copy(update={"provider": forced})
    if source.provider == "placeholder":
        return PlaceholderProvider(seed=source.seed)
    if source.provider == "folder":
        assert source.path is not None
        p = Path(source.path)
        return FolderProvider(p if p.is_absolute() else base_dir / p)
    if source.provider == "spec":
        assert source.path is not None
        p = Path(source.path)
        return SpecProvider(p if p.is_absolute() else base_dir / p)
    if source.provider == "openai":
        return OpenAIImagesProvider(model=source.model, size=source.size, negative_prompt=negative_prompt)
    if source.provider == "google":
        return GoogleImagenProvider(model=source.model, size=source.size, negative_prompt=negative_prompt)
    if source.provider == "stability":
        return StabilityProvider(model=source.model, size=source.size, negative_prompt=negative_prompt)
    if source.provider == "local":
        return LocalDiffusersProvider(source.model, getattr(source, "local_size", "512x768"), negative_prompt, getattr(source, "lora", None), getattr(source, "lora_scale", 0.8), getattr(source, "steps", 28), getattr(source, "guidance", 7.0), source.seed)
    if source.provider == "pollinations":
        return PollinationsProvider(model=source.model, size=source.size, negative_prompt=negative_prompt)
    if source.provider == "cloudflare":
        return CloudflareProvider(model=source.model, size=source.size, negative_prompt=negative_prompt)
    if source.provider == "file":
        raise ValueError("'file' is a cover-only source; handled by cover.render")
    raise ValueError(f"Unknown provider {source.provider}")
