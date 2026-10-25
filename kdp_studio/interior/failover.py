"""Several accounts and several image APIs behind one provider.

When the account in use is out of quota (HTTP 429/402) or its key is refused (401/403), the next member takes over -
for this request and, through a small state file, for later builds too, until the quota comes back.

Profiles: 'cloudflare' = CF_ACCOUNT_ID / CF_API_TOKEN, 'cloudflare#2' = CF_ACCOUNT_ID_2 / CF_API_TOKEN_2, ... (the same
suffix scheme works for every API provider, see keys.py). Chain: book.yaml `source.provider: auto` with
`source.chain: [cloudflare, cloudflare#2, local]`, or the env/.env variable KDP_STUDIO_PROVIDER_CHAIN; a provider name
without #n expands to all of its configured accounts. State file: state/provider_state.json, one entry per profile with
exhausted_until (UTC), the reason, and images generated per UTC day.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from .. import keys as keymod
from ..paths import data_path

log = logging.getLogger(__name__)

STATE_FILE = ("state", "provider_state.json")
KEEP_DAYS = 14


def state_path() -> Path:
    return data_path(*STATE_FILE)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def provider_of(profile_id: str) -> str:
    return keymod.parse_profile_id(profile_id)[0]


def reset_time(provider_id: str, message: str, now: dt.datetime | None = None) -> dt.datetime:
    """When to try a profile again. Cloudflare's free neurons come back at 00:00 UTC; a refused key (401/403) or an empty
    balance (402, 'insufficient', 'credit', 'billing') waits a day; pollinations' per-IP limit a quarter of an hour; any other
    rate limit an hour."""
    now = now or _now()
    m = message.lower()
    if "http 401" in m or "http 403" in m:
        return now + dt.timedelta(hours=24)
    if provider_id == "cloudflare" and ("daily free allocation" in m or "neurons" in m):
        # Cloudflare documents a 00:00 UTC reset, but on 2026-10-25 the account was still refused at 04:10 UTC after
        # exhausting the allocation the previous afternoon; a two-hour retry window costs one refused call per try.
        return now + dt.timedelta(hours=2)
    if "http 402" in m or "insufficient" in m or "balance" in m or "credit" in m or "billing" in m:
        return now + dt.timedelta(hours=24)
    if provider_id == "pollinations":
        return now + dt.timedelta(minutes=15)
    return now + dt.timedelta(hours=1)


class ProviderState:
    """Per-profile memory shared by builds, image tests and the suggest engine: who is blocked until when, and how many
    images each account produced today."""

    def __init__(self, path: Path | None = None):
        self.path = path or state_path()
        self.data: dict[str, dict] = {}
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                log.warning("provider state file %s is unreadable; starting empty", self.path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def entry(self, profile_id: str) -> dict:
        return self.data.setdefault(profile_id, {"exhausted_until": None, "reason": "", "images": {}})

    def exhausted_until(self, profile_id: str) -> dt.datetime | None:
        raw = self.data.get(profile_id, {}).get("exhausted_until")
        if not raw:
            return None
        until = dt.datetime.fromisoformat(raw)
        return until if until.tzinfo else until.replace(tzinfo=dt.timezone.utc)

    def is_available(self, profile_id: str) -> bool:
        until = self.exhausted_until(profile_id)
        return until is None or until <= _now()

    def mark_exhausted(self, profile_id: str, message: str, until: dt.datetime | None = None) -> dt.datetime:
        until = until or reset_time(provider_of(profile_id), message)
        e = self.entry(profile_id)
        e["exhausted_until"] = until.isoformat()
        e["reason"] = message[:220]
        e["since"] = _now().isoformat()
        self.save()
        return until

    def clear(self, profile_id: str | None = None) -> None:
        targets = [profile_id] if profile_id else list(self.data)
        for pid in targets:
            if pid in self.data:
                self.data[pid]["exhausted_until"] = None
                self.data[pid]["reason"] = ""
        self.save()

    def record_images(self, profile_id: str, n: int = 1) -> None:
        e = self.entry(profile_id)
        today = _now().date().isoformat()
        e["images"][today] = int(e["images"].get(today, 0)) + n
        for day in sorted(e["images"]):  # keep two weeks
            if (dt.date.fromisoformat(today) - dt.date.fromisoformat(day)).days > KEEP_DAYS:
                del e["images"][day]
        self.save()

    def images_today(self, profile_id: str) -> int:
        return int(self.data.get(profile_id, {}).get("images", {}).get(_now().date().isoformat(), 0))

    def summary(self) -> list[dict]:
        out = []
        for pid in sorted(self.data):
            until = self.exhausted_until(pid)
            available = until is None or until <= _now()
            out.append({"id": pid, "available": available, "until": until.astimezone().strftime("%H:%M %d/%m") if (until and not available) else "",
                        "reason": "" if available else self.data[pid].get("reason", ""), "images_today": self.images_today(pid)})
        return out


@lru_cache(maxsize=1)
def local_available() -> bool:
    """A local Stable Diffusion stack is installed (torch + diffusers). Cheap: no import, so the UI can ask on every page."""
    return importlib.util.find_spec("torch") is not None and importlib.util.find_spec("diffusers") is not None


def expand_chain(entries: list[str]) -> list[str]:
    """['cloudflare', 'local'] -> ['cloudflare', 'cloudflare#2', 'local'] from the configured accounts; an explicit
    'cloudflare#2' is kept as written; unknown or keyless names are kept so make_provider can explain what is missing."""
    out: list[str] = []
    for raw in entries:
        e = raw.strip()
        if not e:
            continue
        if "#" in e:
            out.append(e)
            continue
        prov = keymod.provider_by_id(e)
        if prov and prov["vars"]:
            ids = [p["id"] for p in keymod.profiles(e) if p["complete"]]
            out.extend(ids or [e])
        else:
            out.append(e)
    return list(dict.fromkeys(out))


def default_chain() -> list[str]:
    """The chain used by provider 'auto': KDP_STUDIO_PROVIDER_CHAIN when set (env, then .env), else every configured
    Cloudflare account followed by the local GPU when its stack is installed. Paid APIs are never added on their own."""
    setting = os.environ.get(keymod.CHAIN_VAR) or keymod.chain_setting()
    if setting.strip():
        return expand_chain(setting.split(","))
    chain = [p["id"] for p in keymod.profiles("cloudflare") if p["complete"]]
    if local_available():
        chain.append("local")
    return chain


class FailoverProvider:
    """One provider made of several (profile, provider) members. generate() uses the first available member and moves on
    when a member reports quota exhaustion or a refused key; the switch is written to the state file so the next build
    skips that account until its reset time. Other provider errors (moderation, 5xx) are raised as usual: they cost one
    attempt in the pipeline, not a switch."""

    def __init__(self, members: list[tuple[str, object]], state: ProviderState | None = None):
        if not members:
            raise ValueError("failover chain is empty")
        self.members = members
        self.state = state or ProviderState()
        self.used: list[str] = []
        self._current = 0

    @property
    def name(self) -> str:  # provider type of the member in use: drives the API_PROVIDERS checks and the cost table
        return self.members[self._current][1].name

    @property
    def profile(self) -> str:
        return self.members[self._current][0]

    def describe(self) -> str:
        return " -> ".join(pid for pid, _ in self.members)

    def generate(self, prompt: str, index: int, attempt: int, out_path: Path, size: tuple[int, int]) -> Path:
        from .generate import ProviderError, ProviderQuota, error_summary  # generate.py imports this module

        skipped: list[str] = []
        for i in range(self._current, len(self.members)):
            pid, prov = self.members[i]
            if not self.state.is_available(pid):
                until = self.state.exhausted_until(pid)
                skipped.append(f"{pid} (khóa đến {until.astimezone():%H:%M %d/%m})" if until else pid)
                continue
            try:
                path = prov.generate(prompt, index, attempt, out_path, size)
            except ProviderQuota as exc:
                summary = error_summary(exc)
                until = self.state.mark_exhausted(pid, summary)
                log.warning("%s hết quota (%s); khóa đến %s, chuyển sang thành viên kế tiếp", pid, summary, until.astimezone().strftime("%H:%M %d/%m"))
                skipped.append(f"{pid} ({summary})")
                continue
            except ProviderError as exc:
                summary = error_summary(exc)
                if "HTTP 401" in summary or "HTTP 403" in summary:
                    self.state.mark_exhausted(pid, summary)
                    log.warning("%s bị từ chối (%s); chuyển sang thành viên kế tiếp", pid, summary)
                    skipped.append(f"{pid} ({summary})")
                    continue
                raise
            self._current = i
            if prov.name not in self.used:
                self.used.append(prov.name)
            self.state.record_images(pid)
            return path
        raise ProviderQuota("mọi nguồn trong chuỗi dự phòng đều tạm khóa: " + "; ".join(skipped))
