"""Quota exhaustion (HTTP 429 after retries) stops a build early, keeps the accepted pages and explains itself."""

import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from kdp_studio.interior import generate as gen
from kdp_studio.interior import pipeline
from kdp_studio.schema import Book

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "bold-easy-flowers" / "book.yaml"
BODY = b'{"errors":[{"message":"AiError: AiError: you have used up your daily free allocation of 10,000 neurons, please upgrade"}],"success":false}'
SUMMARY = "HTTP 429: AiError: AiError: you have used up your daily free allocation of 10,000 neurons, please upgrade"


def test_429_becomes_provider_quota_with_a_readable_summary(monkeypatch):
    req = urllib.request.Request("https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/black-forest-labs/flux-1-schnell", data=b"{}", method="POST")

    def fake_429(r, timeout=0):
        raise urllib.error.HTTPError(r.full_url, 429, "Too Many Requests", {}, io.BytesIO(BODY))

    monkeypatch.setattr(urllib.request, "urlopen", fake_429)
    with pytest.raises(gen.ProviderQuota) as info:
        gen._request(req, tries=1)
    assert isinstance(info.value, gen.ProviderError) and gen.error_summary(info.value) == SUMMARY

    def fake_400(r, timeout=0):
        raise urllib.error.HTTPError(r.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"errors":[{"message":"AiError: Input prompt contains NSFW content."}]}'))

    monkeypatch.setattr(urllib.request, "urlopen", fake_400)
    with pytest.raises(gen.ProviderError) as info2:
        gen._request(req, tries=1)
    assert not isinstance(info2.value, gen.ProviderQuota)
    assert gen.error_summary(info2.value) == "HTTP 400: AiError: Input prompt contains NSFW content."


class QuotaAfterFirstPage:
    name = "cloudflare"  # an API provider, so the pipeline treats it like the real thing

    def __init__(self):
        self.inner = gen.PlaceholderProvider(seed=7)

    def generate(self, prompt, index, attempt, out_path, size):
        if index >= 1:
            raise gen.ProviderQuota("HTTP 429 from https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/black-forest-labs/flux-1-schnell: " + BODY.decode())
        return self.inner.generate(prompt, index, attempt, out_path, size)


def test_build_stops_at_quota_and_keeps_accepted_pages(tmp_path, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO, logger='kdp_studio.interior.pipeline')
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["interior"]["images"] = 4
    data["interior"]["dedupe"]["library"] = str(tmp_path / "hashes.json")
    data["output_dir"] = str(tmp_path / "build")
    book = Book.model_validate(data)
    book.source_path = EXAMPLE
    monkeypatch.setattr(pipeline, "make_provider", lambda *a, **k: QuotaAfterFirstPage())
    result = pipeline.build_coloring_interior(book)
    assert result.image_pages == 1  # page 0 passed, the quota hit on page 1 stopped the rest without 3 retries each
    assert any('page 1/4 done' in r.message for r in caplog.records) and any('1/4 accepted' in r.message for r in caplog.records)  # progress lines for the job log
    manifest = json.loads((tmp_path / "build" / "interior_manifest.json").read_text(encoding="utf-8"))
    assert [r["index"] for r in manifest["rejected"]] == [1, 2, 3]
    assert all(r["reasons"] == [f"provider quota: {SUMMARY}"] for r in manifest["rejected"])
