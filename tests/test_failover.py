"""Backup accounts (_2, _3 suffixes), the failover chain and its quota memory."""

import datetime as dt
from pathlib import Path

import pytest

from kdp_studio import keys as keymod
from kdp_studio.bookgen import new_coloring_book
from kdp_studio.interior import failover as fo
from kdp_studio.interior.generate import ProviderError, ProviderQuota, make_provider
from kdp_studio.schema import ImageSource, load_book

CF_MSG = ('HTTP 429 from https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/black-forest-labs/flux-1-schnell: '
          '{"errors":[{"message":"AiError: AiError: you have used up your daily free allocation of 10,000 neurons, please upgrade"}]}')


@pytest.fixture
def two_cloudflare_accounts(monkeypatch, tmp_path):
    monkeypatch.setattr(keymod, "env_path", lambda: tmp_path / ".env")
    for v in keymod.all_var_names():
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc1")
    monkeypatch.setenv("CF_API_TOKEN", "tok1")
    monkeypatch.setenv("CF_ACCOUNT_ID_2", "acc2")
    monkeypatch.setenv("CF_API_TOKEN_2", "tok2")
    monkeypatch.setattr(fo, "state_path", lambda: tmp_path / "state.json")
    return tmp_path


def test_profiles_numbered_vars_and_chain_expansion(two_cloudflare_accounts):
    prof = keymod.profiles("cloudflare")
    assert [p["id"] for p in prof] == ["cloudflare", "cloudflare#2"] and all(p["complete"] for p in prof)
    assert prof[1]["vars"] == {"CF_ACCOUNT_ID": "CF_ACCOUNT_ID_2", "CF_API_TOKEN": "CF_API_TOKEN_2"} and prof[1]["masked"]["CF_API_TOKEN"] == "tok2"
    assert keymod.profile_values("cloudflare#2") == {"CF_ACCOUNT_ID": "acc2", "CF_API_TOKEN": "tok2"}
    assert keymod.parse_profile_id("openai#3") == ("openai", 3) and keymod.parse_profile_id("openai") == ("openai", 1)
    assert keymod.next_profile_n("cloudflare") == 3 and keymod.next_profile_n("openai") == 2
    assert fo.expand_chain(["cloudflare", "local", " ", "openai#2"]) == ["cloudflare", "cloudflare#2", "local", "openai#2"]
    assert fo.default_chain()[:2] == ["cloudflare", "cloudflare#2"]
    written = keymod.save_env({"CF_API_TOKEN_3": "tok3", "CF_API_TOKEN_10": "nope", keymod.CHAIN_VAR: "cloudflare#2, local"})
    assert written == ["CF_API_TOKEN_3", keymod.CHAIN_VAR] and keymod.chain_setting() == "cloudflare#2, local"
    assert fo.default_chain() == ["cloudflare#2", "local"]
    assert keymod.remove_env([keymod.CHAIN_VAR, "CF_API_TOKEN_3"]) == [keymod.CHAIN_VAR, "CF_API_TOKEN_3"] and keymod.chain_setting() == ""
    assert keymod.check("cloudflare", 3)["detail"].startswith("thiếu CF_ACCOUNT_ID_3")


class Quota:
    name = "cloudflare"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, index, attempt, out_path, size):
        self.calls += 1
        raise ProviderQuota(CF_MSG)


class Works:
    name = "cloudflare"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, index, attempt, out_path, size):
        self.calls += 1
        Path(out_path).write_bytes(b"png")
        return Path(out_path)


class Refused:
    name = "openai"

    def generate(self, *a):
        raise ProviderError("HTTP 401 from https://api.openai.com/v1/images/generations: invalid api key")


class Moderated:
    name = "cloudflare"

    def generate(self, *a):
        raise ProviderError("HTTP 400 from https://api.cloudflare.com/x: NSFW content")


def test_failover_switches_on_quota_and_remembers(tmp_path):
    state = fo.ProviderState(tmp_path / "s.json")
    a, b = Quota(), Works()
    prov = fo.FailoverProvider([("cloudflare", a), ("cloudflare#2", b)], state)
    out = prov.generate("p", 0, 0, tmp_path / "0.png", (1024, 1024))
    assert out.exists() and a.calls == 1 and b.calls == 1 and prov.profile == "cloudflare#2" and prov.used == ["cloudflare"]
    until = state.exhausted_until("cloudflare")
    assert until is not None and dt.timedelta(hours=1, minutes=50) < until - dt.datetime.now(dt.timezone.utc) <= dt.timedelta(hours=2)  # Cloudflare: retry in two hours
    prov.generate("p", 1, 0, tmp_path / "1.png", (1024, 1024))
    assert a.calls == 1 and b.calls == 2  # the exhausted member is not asked again
    # a later build (another process) reads the state file and skips account 1 without calling it
    state2 = fo.ProviderState(tmp_path / "s.json")
    a2, b2 = Quota(), Works()
    prov2 = fo.FailoverProvider([("cloudflare", a2), ("cloudflare#2", b2)], state2)
    prov2.generate("p", 2, 0, tmp_path / "2.png", (1024, 1024))
    assert a2.calls == 0 and b2.calls == 1 and state2.images_today("cloudflare#2") == 3
    summary = {s["id"]: s for s in state2.summary()}
    assert summary["cloudflare"]["available"] is False and "daily free allocation" in summary["cloudflare"]["reason"] and summary["cloudflare#2"]["available"] is True
    state2.clear("cloudflare")
    assert fo.ProviderState(tmp_path / "s.json").is_available("cloudflare")


def test_failover_refused_key_switches_but_moderation_does_not(tmp_path):
    state = fo.ProviderState(tmp_path / "s.json")
    prov = fo.FailoverProvider([("openai", Refused()), ("cloudflare", Works())], state)
    prov.generate("p", 0, 0, tmp_path / "0.png", (1024, 1024))
    assert not state.is_available("openai") and prov.name == "cloudflare"
    prov2 = fo.FailoverProvider([("cloudflare", Moderated()), ("cloudflare#2", Works())], fo.ProviderState(tmp_path / "s2.json"))
    with pytest.raises(ProviderError) as info:
        prov2.generate("p", 0, 0, tmp_path / "1.png", (1024, 1024))
    assert not isinstance(info.value, ProviderQuota)  # one attempt lost in the pipeline, no switch
    prov3 = fo.FailoverProvider([("cloudflare", Quota()), ("cloudflare#2", Quota())], fo.ProviderState(tmp_path / "s3.json"))
    with pytest.raises(ProviderQuota) as info3:
        prov3.generate("p", 0, 0, tmp_path / "2.png", (1024, 1024))
    assert "cloudflare#2" in str(info3.value)


def test_reset_time_rules():
    now = dt.datetime(2026, 10, 24, 13, 0, tzinfo=dt.timezone.utc)
    assert fo.reset_time("cloudflare", "HTTP 429: you have used up your daily free allocation of 10,000 neurons", now) == now + dt.timedelta(hours=2)
    assert fo.reset_time("openai", "HTTP 429: rate limit", now) == now + dt.timedelta(hours=1)
    assert fo.reset_time("openai", "HTTP 402: insufficient_quota", now) == now + dt.timedelta(hours=24)
    assert fo.reset_time("stability", "HTTP 401: unauthorized", now) == now + dt.timedelta(hours=24)
    assert fo.reset_time("pollinations", "HTTP 429", now) == now + dt.timedelta(minutes=15)


def test_make_provider_builds_chains(two_cloudflare_accounts, monkeypatch):
    monkeypatch.delenv("KDP_STUDIO_FORCE_PROVIDER", raising=False)
    prov = make_provider(ImageSource(provider="cloudflare"), two_cloudflare_accounts)
    assert isinstance(prov, fo.FailoverProvider) and prov.describe() == "cloudflare -> cloudflare#2"
    assert [m.account for _, m in prov.members] == ["acc1", "acc2"] and prov.name == "cloudflare"
    auto = make_provider(ImageSource(provider="auto", chain=["cloudflare#2", "cloudflare"]), two_cloudflare_accounts)
    assert auto.describe() == "cloudflare#2 -> cloudflare" and auto.members[0][1].account == "acc2"
    monkeypatch.setenv("KDP_STUDIO_FORCE_PROVIDER", "placeholder")
    assert make_provider(ImageSource(provider="auto"), two_cloudflare_accounts).name == "placeholder"
    monkeypatch.delenv("KDP_STUDIO_FORCE_PROVIDER", raising=False)
    for v in ("CF_ACCOUNT_ID", "CF_API_TOKEN", "CF_ACCOUNT_ID_2", "CF_API_TOKEN_2"):
        monkeypatch.delenv(v)
    monkeypatch.setattr(fo, "local_available", lambda: False)
    with pytest.raises(ProviderError):
        make_provider(ImageSource(provider="auto"), two_cloudflare_accounts)


def test_bookgen_auto_declares_every_member(tmp_path):
    path = new_coloring_book(tmp_path, "sea-life", "Sea Life", "Mia Hartwell", "sea life", provider="auto", subjects=["a whale"])
    book = load_book(path)
    assert book.interior.source.provider == "auto" and book.interior.source.lora and len(book.provenance.ai_tools) == 2
    assert "ColoringBookAF" not in book.interior.style_prompt  # the LoRA trigger word is only for a pure local book
