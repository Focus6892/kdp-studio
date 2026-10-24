"""API keys for the image / LLM platforms: where to get them, how to store them (.env), and a cheap
live check per platform. Values are never printed or returned unmasked.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .paths import project_root

TIMEOUT = 20


def env_path() -> Path:
    return project_root() / ".env"


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "kdp-studio/0.1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed https hosts
            return r.status, r.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)


def _check_openai(v: dict) -> tuple[bool, str]:
    code, body = _get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {v['OPENAI_API_KEY']}"})
    if code == 200:
        names = [m.get("id", "") for m in json.loads(body).get("data", [])]
        return True, "key hợp lệ" + (" · có gpt-image-1" if any("gpt-image" in n for n in names) else "")
    return False, f"HTTP {code}: {body[:160]}"


def _check_google(v: dict) -> tuple[bool, str]:
    code, body = _get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=5", {"x-goog-api-key": v["GEMINI_API_KEY"]})
    return (True, "key hợp lệ (Gemini API)") if code == 200 else (False, f"HTTP {code}: {body[:160]}")


def _check_stability(v: dict) -> tuple[bool, str]:
    code, body = _get("https://api.stability.ai/v1/user/balance", {"Authorization": f"Bearer {v['STABILITY_API_KEY']}"})
    if code == 200:
        return True, f"key hợp lệ · còn {json.loads(body).get('credits', '?')} credit"
    return False, f"HTTP {code}: {body[:160]}"


def _check_cloudflare(v: dict) -> tuple[bool, str]:
    code, body = _get("https://api.cloudflare.com/client/v4/user/tokens/verify", {"Authorization": f"Bearer {v['CF_API_TOKEN']}"})
    if code != 200:
        return False, f"token: HTTP {code}: {body[:160]}"
    code2, body2 = _get(f"https://api.cloudflare.com/client/v4/accounts/{v['CF_ACCOUNT_ID']}/ai/models/search?search=flux", {"Authorization": f"Bearer {v['CF_API_TOKEN']}"})
    if code2 == 200:
        n = len(json.loads(body2).get("result", []))
        return True, f"token hợp lệ · account truy cập được Workers AI ({n} model FLUX)"
    return False, f"account/Workers AI: HTTP {code2}: {body2[:160]}"


def _check_pollinations(v: dict) -> tuple[bool, str]:
    headers = {"Authorization": f"Bearer {v['POLLINATIONS_API_KEY']}"} if v.get("POLLINATIONS_API_KEY") else {}
    code, body = _get("https://image.pollinations.ai/models", headers)
    return (True, "dịch vụ phản hồi" + (" · có token" if headers else " · không key (ảnh nhỏ, watermark)")) if code == 200 else (False, f"HTTP {code}: {body[:120]}")


def _check_anthropic(v: dict) -> tuple[bool, str]:
    code, body = _get("https://api.anthropic.com/v1/models", {"x-api-key": v["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    return (True, "key hợp lệ") if code == 200 else (False, f"HTTP {code}: {body[:160]}")


def _check_hf(v: dict) -> tuple[bool, str]:
    code, body = _get("https://huggingface.co/api/whoami-v2", {"Authorization": f"Bearer {v['HF_TOKEN']}"})
    return (True, f"token hợp lệ · user {json.loads(body).get('name', '?')}") if code == 200 else (False, f"HTTP {code}: {body[:120]}")


PROVIDERS: list[dict] = [
    {"id": "local", "name": "Model cục bộ (Stable Diffusion trên GPU)", "vars": [], "url": "https://huggingface.co/Lykon/dreamshaper-8", "free": "Miễn phí, vô hạn; cần GPU NVIDIA 4 GB trở lên.",
     "steps": ["Chạy `kdp local-setup` một lần (tải PyTorch + model ~4 GB)", "Trong book.yaml đặt interior.source.provider: local"]},
    {"id": "spec", "name": "Bản vẽ vector (Claude soạn hoặc tự vẽ)", "vars": [], "url": "", "free": "Miễn phí, không cần model hay key.",
     "steps": ["Đặt file JSON vào thư mục drawings/ của cuốn sách", "interior.source.provider: spec, path: drawings"]},
    {"id": "cloudflare", "name": "Cloudflare Workers AI (FLUX schnell, SDXL, DreamShaper-LCM)", "vars": ["CF_ACCOUNT_ID", "CF_API_TOKEN"], "url": "https://dash.cloudflare.com/profile/api-tokens",
     "free": "Miễn phí 10.000 neuron/ngày (≈170–230 ảnh FLUX), reset 00:00 UTC.", "check": _check_cloudflare,
     "steps": ["Tạo tài khoản Cloudflare miễn phí tại dash.cloudflare.com", "Account ID: mở Workers & Pages, cột phải hiện Account ID (hoặc lấy từ URL dash.cloudflare.com/<account id>/...)", "API token: Profile → API Tokens → Create Token → mẫu 'Workers AI' (quyền Workers AI: Read) → Create → sao chép token"]},
    {"id": "openai", "name": "OpenAI (gpt-image-1)", "vars": ["OPENAI_API_KEY"], "url": "https://platform.openai.com/api-keys", "free": "Không có hạn mức miễn phí; ~0.04–0.17 USD mỗi ảnh.", "check": _check_openai,
     "steps": ["Đăng nhập platform.openai.com", "Dashboard → API keys → Create new secret key", "Billing → nạp tiền trước khi gọi"]},
    {"id": "google", "name": "Google Gemini API (Imagen 4)", "vars": ["GEMINI_API_KEY"], "url": "https://aistudio.google.com/apikey", "free": "Model ảnh không có free tier (10/2026); ~0.04 USD mỗi ảnh Imagen.", "check": _check_google,
     "steps": ["Đăng nhập Google AI Studio", "Get API key → Create API key (gắn một dự án Google Cloud có billing)", "Dán vào ô bên dưới"]},
    {"id": "stability", "name": "Stability AI (Stable Image core / sd3.5)", "vars": ["STABILITY_API_KEY"], "url": "https://platform.stability.ai/account/keys", "free": "25 credit dùng thử (≈8 ảnh core), sau đó ~0.03 USD mỗi ảnh.", "check": _check_stability,
     "steps": ["Đăng ký platform.stability.ai", "Account → API Keys → Create", "Nút Kiểm tra sẽ hiện số credit còn lại"]},
    {"id": "pollinations", "name": "pollinations.ai (FLUX, không bắt buộc key)", "vars": ["POLLINATIONS_API_KEY"], "optional": True, "url": "https://auth.pollinations.ai", "free": "Không cần key: ảnh 630×940 có watermark, 1 ảnh/45 giây. Token miễn phí (đăng nhập GitHub) bỏ watermark và giới hạn.", "check": _check_pollinations,
     "steps": ["Vào auth.pollinations.ai, đăng nhập bằng GitHub", "Tạo API key và dán vào ô bên dưới (có thể bỏ trống)"]},
    {"id": "anthropic", "name": "Anthropic Claude (prompt đa dạng, metadata, concept, draft truyện, QA ảnh)", "vars": ["ANTHROPIC_API_KEY"], "url": "https://console.anthropic.com/settings/keys", "free": "Trả theo token; không bắt buộc, tool có đường offline.", "check": _check_anthropic,
     "steps": ["Đăng nhập console.anthropic.com", "Settings → API Keys → Create Key", "Nạp credit trong Billing"]},
    {"id": "huggingface", "name": "Hugging Face token (tải model nhanh hơn)", "vars": ["HF_TOKEN"], "optional": True, "url": "https://huggingface.co/settings/tokens", "free": "Miễn phí; chỉ cần cho model gated hoặc để tránh giới hạn tải.", "check": _check_hf,
     "steps": ["Đăng nhập huggingface.co", "Settings → Access Tokens → Create new token (Read)"]},
]

ALL_VARS = [v for p in PROVIDERS for v in p["vars"]]


def mask(value: str | None) -> str:
    if not value:
        return ""
    return value if len(value) <= 8 else f"{value[:3]}…{value[-4:]}"


def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or env_path()
    out: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.split(" #")[0].strip().strip('"').strip("'")
    return out


def current_values() -> dict[str, str]:
    """Environment first (shell wins), then .env - same precedence the tool uses at runtime."""
    file_vals = read_env()
    return {var: os.environ.get(var) or file_vals.get(var, "") for var in ALL_VARS}


def save_env(updates: dict[str, str], path: Path | None = None) -> list[str]:
    """Write NAME=value lines into .env, keeping comments and other lines; empty values are ignored.
    Also exports them into this process so a check right after works. Returns the names written."""
    path = path or env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    written: list[str] = []
    for name, value in updates.items():
        value = (value or "").strip()
        if not value or name not in ALL_VARS:
            continue
        replaced = False
        for i, raw in enumerate(lines):
            if raw.strip().startswith(name + "=") or raw.strip().startswith(name + " ="):
                lines[i] = f"{name}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{name}={value}")
        os.environ[name] = value
        written.append(name)
    if written:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def check(provider_id: str) -> dict:
    """Live check for one provider: {ok, detail}. Never includes key material."""
    prov = next((p for p in PROVIDERS if p["id"] == provider_id), None)
    if prov is None:
        return {"ok": False, "detail": "không có nền tảng này"}
    vals = current_values()
    missing = [v for v in prov["vars"] if not vals.get(v)]
    if missing and not prov.get("optional"):
        return {"ok": False, "detail": "thiếu " + ", ".join(missing)}
    if not prov.get("check"):
        return {"ok": True, "detail": "không cần key"}
    try:
        ok, detail = prov["check"]({v: vals.get(v, "") for v in prov["vars"]})
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"lỗi kiểm tra: {str(exc)[:160]}"
    return {"ok": ok, "detail": detail}


def status_table() -> list[dict]:
    vals = current_values()
    return [{**{k: p[k] for k in ("id", "name", "vars", "url", "free", "steps")}, "optional": p.get("optional", False), "present": {v: bool(vals.get(v)) for v in p["vars"]}, "masked": {v: mask(vals.get(v)) for v in p["vars"]}} for p in PROVIDERS]
