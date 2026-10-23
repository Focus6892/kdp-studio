"""Amazon search-box suggestions (unofficial endpoint used by most KDP keyword tools).

Polite by design: one request per prefix, a pause between requests, a hard cap per
run, and failures return an empty list. Amazon's Conditions of Use prohibit
automated data gathering, so keep volumes small and treat this as a convenience,
not a pipeline backbone.
"""

from __future__ import annotations

import json
import logging
import string
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

ENDPOINT = "https://completion.amazon.com/api/2017/suggestions"
MARKETPLACE_IDS = {"amazon.com": "ATVPDKIKX0DER", "amazon.co.uk": "A1F83G8C2ARO7P", "amazon.de": "A1PA6795UKMFR9", "amazon.ca": "A2EUQ1WTGCTBG2"}
ALIASES = {"books": "stripbooks", "kindle": "digital-text", "all": "aps"}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def parse_suggestions(payload: dict) -> list[str]:
    out: list[str] = []
    for s in payload.get("suggestions", []):
        if s.get("type") not in (None, "KEYWORD"):
            continue
        v = (s.get("value") or "").strip()
        if v and v.lower() not in {o.lower() for o in out}:
            out.append(v)
    return out


def fetch_suggestions(prefix: str, alias: str = "books", marketplace: str = "amazon.com", limit: int = 11, timeout: float = 15.0) -> list[str]:
    params = {
        "mid": MARKETPLACE_IDS.get(marketplace, MARKETPLACE_IDS["amazon.com"]),
        "alias": ALIASES.get(alias, alias),
        "prefix": prefix,
        "limit": str(limit),
        "lop": "en_US",
        "site-variant": "desktop",
        "client-info": "amazon-search-ui",
        "page-type": "Search",
        "event": "onKeyPress",
        "suggestion-type": "KEYWORD",
        "fuzzy": "0",
        "b2b": "0",
        "fresh": "0",
    }
    req = urllib.request.Request(ENDPOINT + "?" + urllib.parse.urlencode(params), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoint
            return parse_suggestions(json.load(resp))
    except Exception as exc:  # network / HTTP / JSON — all non-fatal
        log.warning("autocomplete failed for %r: %s", prefix, exc)
        return []


def expand(seeds: list[str], alias: str = "books", marketplace: str = "amazon.com", letters: bool = False, max_requests: int = 40, pause: float = 0.8) -> list[str]:
    """Suggestions for each seed, optionally also for 'seed a' .. 'seed z' (Publisher-Rocket style)."""
    prefixes: list[str] = []
    for seed in seeds:
        prefixes.append(seed)
        if letters:
            prefixes.extend(f"{seed} {ch}" for ch in string.ascii_lowercase)
    prefixes = prefixes[:max_requests]
    out: list[str] = []
    seen = {s.lower() for s in seeds}
    for i, p in enumerate(prefixes):
        for s in fetch_suggestions(p, alias, marketplace):
            if s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        if i < len(prefixes) - 1:
            time.sleep(pause)
    return out
