import os
from pathlib import Path

import pytest

from kdp_studio.env import KEY_VARS, key_status, load_dotenv
from kdp_studio.interior.generate import (
    GoogleImagenProvider,
    OpenAIImagesProvider,
    ProviderError,
    StabilityProvider,
    _aspect,
    _multipart,
    make_provider,
)
from kdp_studio.schema import ImageSource


def test_dotenv_sets_missing_names_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# keys\nOPENAI_API_KEY="sk-from-file"\nSTABILITY_API_KEY=sk-stab\nBROKEN LINE\n', encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-shell")
    monkeypatch.delenv("STABILITY_API_KEY", raising=False)
    added = load_dotenv(env)
    assert added == ["STABILITY_API_KEY"]
    assert os.environ["OPENAI_API_KEY"] == "sk-from-shell" and os.environ["STABILITY_API_KEY"] == "sk-stab"
    assert set(key_status()) == set(KEY_VARS)
    assert load_dotenv(tmp_path / "missing.env") == []


def test_provider_bodies_are_shaped_for_each_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("STABILITY_API_KEY", "k")
    o = OpenAIImagesProvider(model=None, size="1024x1536", negative_prompt="color, shading")
    body = o.body("a bold flower")
    assert body["model"] == "gpt-image-1" and body["size"] == "1024x1536" and body["output_format"] == "png"
    assert body["prompt"].startswith("a bold flower") and "Avoid: color, shading" in body["prompt"]
    g = GoogleImagenProvider(model=None, size="1024x1536")
    gb = g.body("a bold flower", (1024, 1536))
    assert gb["parameters"]["aspectRatio"] == "3:4" and gb["instances"][0]["prompt"] == "a bold flower"
    assert g.endpoint.endswith("/models/imagen-4.0-generate-001:predict")
    s = StabilityProvider(model=None, size="1024x1536", negative_prompt="color")
    f = s.fields("a bold flower", (1024, 1536))
    assert f["aspect_ratio"] == "2:3" and f["style_preset"] == "line-art" and f["negative_prompt"] == "color"
    assert s.endpoint.endswith("/generate/core")
    sd3 = StabilityProvider(model="sd3.5-large", size="1024x1536")
    assert sd3.endpoint.endswith("/generate/sd3") and sd3.fields("x", (1024, 1536))["model"] == "sd3.5-large"
    body, ctype = _multipart({"prompt": "p", "aspect_ratio": "2:3"})
    assert ctype.startswith("multipart/form-data; boundary=") and b'name="prompt"' in body and body.endswith(b"--\r\n")
    assert _aspect((1536, 1024), GoogleImagenProvider.RATIOS) == "4:3"
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    from kdp_studio.interior.generate import CloudflareProvider, PollinationsProvider

    cf = CloudflareProvider(model=None, size="1024x1536", negative_prompt="woman, child")
    assert cf.body("a daisy", (1024, 1536)) == {"prompt": "a daisy", "steps": 4}  # FLUX: never fold the negative prompt in; 4 steps = schnell's design point
    assert "Avoid" not in PollinationsProvider(model=None, size="1024x1536", negative_prompt="woman").url("a daisy", 1, (1024, 1536))


def test_missing_key_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr("kdp_studio.keys.env_path", lambda: tmp_path / ".env")  # credentials also fall back to .env, so point it at an empty one
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "STABILITY_API_KEY", "KDP_STUDIO_FORCE_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    for provider in ("openai", "google", "stability"):
        with pytest.raises(ProviderError):
            make_provider(ImageSource(provider=provider), Path("."))
    assert make_provider(ImageSource(provider="placeholder"), Path(".")).name == "placeholder"
