"""A guarded Playwright session for the assisted publisher.

- persistent profile (your own Amazon login lives there; never commit that folder)
- headful by default; headless is only accepted for local mock pages (file:// / localhost)
- uses the Edge or Chrome already installed before falling back to Playwright's Chromium
- detects sign-in and CAPTCHA pages and hands control to the human
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


class PlaywrightMissing(RuntimeError):
    pass


def _is_local(url: str | None) -> bool:
    if not url:
        return False
    u = url.lower()
    return u.startswith("file://") or "://localhost" in u or "://127.0.0.1" in u


class BrowserSession:
    def __init__(
        self,
        profile_dir: Path,
        *,
        channels: tuple[str | None, ...] = ("msedge", "chrome", None),
        headless: bool = False,
        allow_headless_local: bool = False,
        start_url: str | None = None,
        slow_mo_ms: int = 60,
        screenshot_dir: Path | None = None,
    ):
        if headless and not (allow_headless_local and _is_local(start_url)):
            raise ValueError("Headless mode is only allowed against a local mock page; the KDP dashboard must stay visible to you.")
        self.profile_dir = Path(profile_dir)
        self.channels = channels
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms
        self.screenshot_dir = screenshot_dir
        self._pw = None
        self._ctx = None
        self.channel_used: str | None = None
        self.screenshots: list[Path] = []

    # ------------------------------------------------------------------ lifecycle
    def open(self) -> "BrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise PlaywrightMissing("Playwright is not installed: pip install 'kdp-studio[publish]' (uses your Edge/Chrome, or run `playwright install chromium`)") from exc
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        last_exc: Exception | None = None
        for channel in self.channels:
            kw: dict = {"headless": self.headless, "slow_mo": self.slow_mo_ms, "accept_downloads": True}
            if channel:
                kw["channel"] = channel
            if not self.headless:
                kw["no_viewport"] = True
                kw["args"] = ["--start-maximized"]
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **kw)
                self.channel_used = channel or "chromium"
                break
            except Exception as exc:  # noqa: BLE001 - try the next browser channel
                last_exc = exc
                log.info("browser channel %s unavailable: %s", channel or "chromium", str(exc).splitlines()[0][:120])
        if self._ctx is None:
            self._pw.stop()
            raise RuntimeError(f"No browser could be launched (tried {', '.join(c or 'chromium' for c in self.channels)}): {last_exc}")
        return self

    def close(self) -> None:
        try:
            if self._ctx is not None:
                self._ctx.close()
        finally:
            self._ctx = None
            if self._pw is not None:
                self._pw.stop()
                self._pw = None

    def __enter__(self) -> "BrowserSession":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ page helpers
    @property
    def page(self):
        assert self._ctx is not None, "session not open"
        return self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    @property
    def url(self) -> str:
        return self.page.url

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")

    def _scopes(self):
        """Main page first, then every child frame (KDP may render parts of the form in frames)."""
        page = self.page
        scopes = [page]
        try:
            scopes += [f for f in page.frames if f != page.main_frame]
        except Exception:  # noqa: BLE001
            pass
        return scopes

    def find(self, candidates: list[str]):
        """First candidate selector that matches at least one element (in any frame), else None."""
        for sel in candidates:
            for scope in self._scopes():
                try:
                    loc = scope.locator(sel)
                    if loc.count() > 0:
                        return loc.first
                except Exception:  # noqa: BLE001 - invalid selector or detached frame
                    continue
        return None

    def inventory(self, limit: int = 600) -> dict:
        """Structural dump of every form control and button on the page and its frames.
        Captures ids, names, labels and option values only - never what the user typed."""
        js = """
        () => {
          const q = 'input, select, textarea, button, [contenteditable="true"], a[role="button"], [role="radio"], [role="checkbox"], [role="combobox"]';
          const els = Array.from(document.querySelectorAll(q));
          const lab = el => { const l = el.labels && el.labels[0]; if (l) return l.textContent.trim().replace(/\\s+/g, ' ').slice(0, 100);
                              const al = el.getAttribute('aria-labelledby'); if (al) { const t = document.getElementById(al); if (t) return t.textContent.trim().replace(/\\s+/g, ' ').slice(0, 100); } return null; };
          return {
            headings: Array.from(document.querySelectorAll('h1, h2, h3')).slice(0, 40).map(h => h.textContent.trim().replace(/\\s+/g, ' ').slice(0, 100)),
            elements: els.map(el => ({
              tag: el.tagName.toLowerCase(), type: el.getAttribute('type'), id: el.id || null, name: el.getAttribute('name'),
              placeholder: el.getAttribute('placeholder'), aria: el.getAttribute('aria-label'), role: el.getAttribute('role'),
              label: lab(el), text: (el.tagName === 'BUTTON' || el.tagName === 'A') ? el.textContent.trim().replace(/\\s+/g, ' ').slice(0, 80) : null,
              option_value: (el.type === 'radio' || el.type === 'checkbox') ? el.value : null,
              options: el.tagName === 'SELECT' ? Array.from(el.options).slice(0, 40).map(o => o.textContent.trim().slice(0, 60)) : null,
              classes: (el.className && typeof el.className === 'string') ? el.className.trim().slice(0, 120) : null,
              visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
            }))
          };
        }
        """
        out = {"url": self.url, "title": "", "frames": [], "scopes": []}
        try:
            out["title"] = self.page.title()
        except Exception:  # noqa: BLE001
            pass
        for idx, scope in enumerate(self._scopes()):
            try:
                frame_url = scope.url
                data = scope.evaluate(js)
            except Exception as exc:  # noqa: BLE001 - cross-origin frame or navigation in progress
                out["frames"].append({"index": idx, "url": getattr(scope, "url", "?"), "error": str(exc).splitlines()[0][:120]})
                continue
            elements = data.get("elements", [])[:limit]
            for e in elements:
                e["frame"] = idx
            out["frames"].append({"index": idx, "url": frame_url, "elements": len(elements), "headings": data.get("headings", [])})
            out["scopes"].append({"frame": idx, "url": frame_url, "headings": data.get("headings", []), "elements": elements})
        return out

    def fill(self, candidates: list[str], value: str) -> bool:
        loc = self.find(candidates)
        if loc is None:
            return False
        try:
            loc.fill(value)
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("fill failed for %s: %s", candidates[0], str(exc).splitlines()[0][:120])
            return False

    def fill_rich(self, candidates: list[str], html: str) -> bool:
        """Description editors: CKEditor (via its JS API, which also syncs the hidden form field),
        then plain textarea/input, contenteditable, or a CKEditor iframe as fallbacks."""
        try:
            done = self.page.evaluate(
                """(h) => {
                    const ck = window.CKEDITOR;
                    if (!ck || !ck.instances) return false;
                    const names = Object.keys(ck.instances);
                    if (!names.length) return false;
                    const name = names.find(n => /descr/i.test(n)) || names[0];
                    const inst = ck.instances[name];
                    inst.setData(h);
                    if (inst.updateElement) inst.updateElement();
                    return true;
                }""",
                html,
            )
            if done:
                return True
        except Exception as exc:  # noqa: BLE001
            log.info("CKEditor API not usable: %s", str(exc).splitlines()[0][:120])
        loc = self.find(candidates)
        if loc is None:
            return False
        try:
            tag = loc.evaluate("el => el.tagName.toLowerCase()")
            if tag in ("textarea", "input"):
                loc.fill(html)
                return True
            if tag == "iframe":
                frame = loc.content_frame() if hasattr(loc, "content_frame") else None
                if frame is not None:
                    frame.locator("body").evaluate("(el, h) => { el.innerHTML = h; el.dispatchEvent(new Event('input', {bubbles: true})); }", html)
                    return True
                return False
            loc.evaluate("(el, h) => { el.innerHTML = h; el.dispatchEvent(new Event('input', {bubbles: true})); }", html)
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("rich fill failed: %s", str(exc).splitlines()[0][:120])
            return False

    def check(self, candidates: list[str]) -> bool:
        loc = self.find(candidates)
        if loc is None:
            return False
        try:
            tag = loc.evaluate("el => el.tagName.toLowerCase()")
            if tag == "label":
                loc.click()
            else:
                loc.check()
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("check failed: %s", str(exc).splitlines()[0][:120])
            return False

    def uncheck(self, candidates: list[str]) -> bool:
        loc = self.find(candidates)
        if loc is None:
            return False
        try:
            if loc.is_checked():
                loc.uncheck()
            return True
        except Exception:  # noqa: BLE001
            return False

    def select(self, candidates: list[str], *, value: str | None = None, label_equals: str | None = None, label_contains: str | list[str] | None = None, exclude_contains: str | None = None) -> bool:
        """Select by value, by exact label, by the first label needle that matches (in order),
        or - with `exclude_contains` - the first option whose label does not contain that word."""
        loc = self.find(candidates)
        if loc is None:
            return False
        try:
            if value is not None:
                try:
                    loc.select_option(value=value)
                    return True
                except Exception:  # noqa: BLE001 - value not present, fall through to labels
                    pass
            options = loc.evaluate("el => Array.from(el.options).map(o => [o.value, o.textContent.trim()])")
            if label_equals is not None:
                for val, text in options:
                    if text.lower() == label_equals.lower():
                        loc.select_option(value=val)
                        return True
            needles = [label_contains] if isinstance(label_contains, str) else list(label_contains or [])
            for needle in needles:
                for val, text in options:
                    if needle.lower() in text.lower():
                        loc.select_option(value=val)
                        return True
            if exclude_contains is not None:
                for val, text in options:
                    if text and exclude_contains.lower() not in text.lower() and val != "":
                        loc.select_option(value=val)
                        return True
            return False
        except Exception as exc:  # noqa: BLE001
            log.info("select failed: %s", str(exc).splitlines()[0][:120])
            return False

    def set_files(self, candidates: list[str], path: Path) -> bool:
        loc = self.find(candidates)
        if loc is None:
            return False
        try:
            loc.set_input_files(str(path))
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("file upload failed: %s", str(exc).splitlines()[0][:120])
            return False

    def click(self, candidates: list[str]) -> bool:
        loc = self.find(candidates)
        if loc is None:
            return False
        try:
            loc.click()
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("click failed: %s", str(exc).splitlines()[0][:120])
            return False

    def wait_for(self, candidates: list[str], timeout_s: float = 60, poll_s: float = 1.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.find(candidates) is not None:
                return True
            time.sleep(poll_s)
        return False

    def is_signin(self, markers: list[str]) -> bool:
        return "ap/signin" in self.url or "/ap/" in self.url and "signin" in self.url or self.find(markers) is not None

    def is_captcha(self, markers: list[str]) -> bool:
        return self.find(markers) is not None

    def screenshot(self, name: str) -> Path | None:
        if self.screenshot_dir is None:
            return None
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = self.screenshot_dir / f"{len(self.screenshots) + 1:02d}-{name}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except Exception as exc:  # noqa: BLE001
            log.info("screenshot failed: %s", exc)
            return None
        self.screenshots.append(path)
        return path

    def matches(self, group: dict, fmt: str) -> dict[str, str | None]:
        """For `probe`: which candidate (if any) matches for each field of a selector group."""
        from .selectors import expand

        out: dict[str, str | None] = {}
        for field, cands in group.items():
            if isinstance(cands, dict):
                for sub, sub_cands in cands.items():
                    out[f"{field}.{sub}"] = self._first_match(expand(sub_cands, fmt, i=0))
            else:
                out[field] = self._first_match(expand(cands, fmt, i=0))
        return out

    def _first_match(self, cands: list[str]) -> str | None:
        for sel in cands:
            for scope in self._scopes():
                try:
                    if scope.locator(sel).count() > 0:
                        return sel
                except Exception:  # noqa: BLE001
                    continue
        return None


def inventory_markdown(inv: dict) -> str:
    """Human-readable version of `BrowserSession.inventory()` for the probe dump."""
    lines = [f"# Probe dump — {inv.get('title') or ''}", "", f"URL: {inv.get('url')}", ""]
    for fr in inv.get("frames", []):
        if "error" in fr:
            lines.append(f"- frame {fr['index']}: {fr['url']} — not readable ({fr['error']})")
        else:
            lines.append(f"- frame {fr['index']}: {fr['url']} — {fr['elements']} control(s); headings: {' | '.join(fr.get('headings', [])[:8])}")
    lines.append("")
    lines.append("| frame | tag | type/role | id | name | label / text / aria / placeholder | options / value | visible |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for sc in inv.get("scopes", []):
        for e in sc["elements"]:
            desc = e.get("label") or e.get("text") or e.get("aria") or e.get("placeholder") or ""
            opts = ", ".join(e["options"][:6]) if e.get("options") else (e.get("option_value") or "")
            lines.append(f"| {e['frame']} | {e['tag']} | {e.get('type') or e.get('role') or ''} | {e.get('id') or ''} | {e.get('name') or ''} | {desc} | {opts} | {'y' if e.get('visible') else 'n'} |")
    return "\n".join(lines) + "\n"


def wait_for_human(session: BrowserSession, ask: Callable[[str], str], prompt: str) -> str:
    """Block until the human presses Enter (or types a stop word)."""
    return ask(prompt)
