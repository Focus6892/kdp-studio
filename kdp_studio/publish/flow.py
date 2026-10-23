"""The assisted title-setup flow: Details -> Content -> Pricing, with a human gate at each step.

The flow fills what it can, lists what it could not, and stops before every
irreversible action. It never clicks Publish.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..schema import Book
from .browser import BrowserSession
from .checklist import artifacts_for, split_author
from .selectors import expand
from .store import PublishStore

log = logging.getLogger(__name__)

STOP_WORDS = {"q", "quit", "stop", "abort", "exit"}


class FlowStopped(Exception):
    """Raised to end the flow early; `status` becomes the run status (aborted, or blocked when KDP refused)."""

    def __init__(self, message: str = "", status: str = "aborted"):
        super().__init__(message)
        self.status = status


class Approver(Protocol):
    def ask(self, prompt: str) -> str: ...


class ConsoleApprover:
    def ask(self, prompt: str) -> str:
        print()
        return input(prompt + " ").strip()


class ScriptedApprover:
    """For tests: canned answers, prompts recorded."""

    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else ""


@dataclass
class FlowResult:
    status: str = "aborted"  # submitted | draft | stopped_before_publish | aborted
    filled: list[str] = field(default_factory=list)
    unfilled: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    started: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    finished: str | None = None

    def as_dict(self) -> dict:
        return {"status": self.status, "filled": self.filled, "unfilled": self.unfilled, "notes": self.notes, "screenshots": self.screenshots, "events": self.events, "started": self.started, "finished": self.finished}


class Flow:
    def __init__(self, book: Book, fmt: str, session: BrowserSession, selectors: dict, approver: Approver, store: PublishStore | None, book_path: str | None = None, resume: bool = False):
        self.book, self.fmt, self.s, self.sel, self.approver, self.store = book, fmt, session, selectors, approver, store
        self.book_path = book_path
        self.resume = resume  # continuing an existing KDP draft: no title is created, so no 'created' event
        self.res = FlowResult()

    # ---------------------------------------------------------------- helpers
    def _c(self, group: str, field: str, **kw) -> list[str]:
        return expand(self.sel[group][field], self.fmt, **kw)

    def _record(self, ok: bool, field: str, value: str) -> None:
        if ok:
            if field not in self.res.filled:
                self.res.filled.append(field)
            self.res.unfilled = [(f, v) for f, v in self.res.unfilled if f != field]  # filled on a later tab
        elif field not in self.res.filled and all(f != field for f, _ in self.res.unfilled):
            self.res.unfilled.append((field, value))

    def _gate(self, prompt: str) -> str:
        ans = self.approver.ask(prompt).strip().lower()
        if ans in STOP_WORDS:
            raise FlowStopped("stopped by the operator")
        if not self.s.is_alive():
            raise FlowStopped("the browser window was closed while the tool was waiting for your review")
        return ans

    def _event(self, event: str, notes: str | None = None) -> None:
        self.res.events.append(event)
        if self.store is not None:
            self.store.add_event(self.book.id, self.fmt, event, book_path=self.book_path, notes=notes)

    def _shot(self, name: str) -> None:
        p = self.s.screenshot(name)
        if p:
            self.res.screenshots.append(str(p))

    def _await(self, markers: list, timeout_s: float) -> bool:
        """Wait for the next tab while watching for KDP's 'Title creation limit reached' dialog."""
        deadline = time.time() + timeout_s
        while True:
            if self.s.find_visible(self.sel["limit_markers"]) is not None:
                self._kdp_limit()
            if self.s.find(markers) is not None:
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.5)

    def _kdp_limit(self) -> None:
        msg = ("KDP refused to create the title: weekly title creation limit reached for this format "
               "(drafts count; resets Sunday 00:00 UTC). Nothing was created; the local quota now treats the format as used up.")
        self._event("kdp_limit", msg)
        raise FlowStopped(msg, status="blocked")

    def _wait_access(self) -> None:
        """Hand over to the human for sign-in or CAPTCHA pages; the tool never fills those."""
        for _ in range(20):
            if self.s.is_captcha(self.sel["captcha_markers"]):
                self._gate("A CAPTCHA/challenge is showing. Solve it yourself in the browser window, then press Enter (q to stop):")
                continue
            if self.s.is_signin(self.sel["signin_markers"]):
                self._gate("Amazon is asking you to sign in. Sign in (and complete any OTP) in the browser window, then press Enter (q to stop):")
                continue
            return
        raise FlowStopped("sign-in or CAPTCHA page still showing after 20 rounds")

    # ---------------------------------------------------------------- steps
    def create_title(self) -> None:
        if self.s.find(self._c("details", "title")) is not None:
            return  # already on a details page
        if not self.s.click(self.sel["create_button"]):
            self._gate("Could not find the Create button. Click '+ Create' on your Bookshelf yourself, then press Enter:")
        if self.s.wait_for(self._c("details", "title"), timeout_s=5):
            return
        if not self.s.click(self.sel["format_choice"][self.fmt]):
            self._gate(f"Could not find the '{self.fmt}' choice. Pick it yourself, then press Enter:")
        if not self._await(self._c("details", "title"), timeout_s=60):
            self._gate("The Details page did not appear. Open the new title's Details tab yourself, then press Enter:")

    def fill_ai_disclosure(self) -> bool:
        """KDP's 'AI-Generated Content' block (on the Content tab at the time of writing; the flow
        tries it on every tab and fills it where it exists). Returns True when the block was found."""
        if self.s.find(self._c("ai", "ai_yes")) is None and self.s.find(self._c("ai", "ai_no")) is None:
            return False
        disclosure = self.book.ai_disclosure()
        used_ai = disclosure["Did you use AI tools in creating texts, images and/or translations?"] == "Yes"
        self._record(self.s.check(self._c("ai", "ai_yes" if used_ai else "ai_no")), "ai_content", "yes" if used_ai else "no")
        if not used_ai:
            return True
        # KDP words the scope options differently per category ("Entire work" / "Many or all" / "Some sections" /
        # "One or a few"); pick the broadest declared option, never "None", and leave the editing level to the human.
        declared_needles = ["entire", "many or all", "all", "some", "one or a few"]
        categories = (("Text", "ai_text"), ("Images", "ai_images"), ("Translations", "ai_translation"))
        legacy_selects = self.s.find(self._c("ai", "ai_text")) is not None
        combos = [] if legacy_selects else [loc for loc, name in self.s.comboboxes() if "trim" not in name.lower()]
        for idx, (key, fld) in enumerate(categories):
            wants_ai = disclosure[key].startswith("AI-generated")
            if legacy_selects:
                ok = self.s.select(self._c("ai", fld), label_contains=declared_needles, exclude_contains="none") if wants_ai else self.s.select(self._c("ai", fld), label_contains="none")
            elif idx < len(combos):
                ok = self.s.choose_combobox(combos[idx], label_contains=declared_needles, exclude_contains="none") if wants_ai else self.s.choose_combobox(combos[idx], label_contains="none")
            else:
                ok = False
            if wants_ai:
                self._record(ok, f"ai_{key.lower()}", "AI-generated (confirm scope and editing level yourself)")
                self.res.notes.append(f"AI {key}: declared as AI-generated; confirm the scope and editing level that match your workflow.")
        return True

    def fill_details(self) -> None:
        md = self.book.metadata
        self._record(self.s.select(self._c("details", "language"), label_equals=md.language, label_contains=md.language), "language", md.language)
        self._record(self.s.fill(self._c("details", "title"), md.title), "title", md.title)
        if md.subtitle:
            self._record(self.s.fill(self._c("details", "subtitle"), md.subtitle), "subtitle", md.subtitle)
        if md.edition:
            self._record(self.s.fill(self._c("details", "edition"), md.edition), "edition", md.edition)
        first, last = split_author(md.author)
        if first:
            self._record(self.s.fill(self._c("details", "author_first"), first), "author_first", first)
        self._record(self.s.fill(self._c("details", "author_last"), last), "author_last", last)
        self._record(self.s.fill_rich(self._c("details", "description"), md.description_html.strip()), "description", "(html)")
        self._record(self.s.check(self._c("details", "rights_own")), "publishing_rights", "own copyright")
        self._record(self.s.check(self._c("details", "adult_yes" if md.sexually_explicit else "adult_no")), "sexually_explicit", "yes" if md.sexually_explicit else "no")
        if md.reading_age:
            lo, hi = str(md.reading_age.min), str(md.reading_age.max)
            self._record(self.s.select(self._c("details", "age_min"), value=lo, label_equals=lo), "reading_age_min", lo)
            self._record(self.s.select(self._c("details", "age_max"), value=hi, label_equals=hi), "reading_age_max", hi)
        marketplace = {"amazon.com": "Amazon.com"}.get(self.book.pricing.marketplace, self.book.pricing.marketplace)
        if self.s.find(self._c("details", "primary_marketplace")) is not None:
            self._record(self.s.select(self._c("details", "primary_marketplace"), label_equals=marketplace), "primary_marketplace", marketplace)
        self.fill_ai_disclosure()
        for i, kw in enumerate(md.keywords[:7]):
            self._record(self.s.fill(self._c("details", "keyword", i=i), kw), f"keyword_{i + 1}", kw)
        if md.low_content:
            self._record(self.s.check(self._c("details", "low_content")), "low_content", "yes")
        else:
            self.s.uncheck(self._c("details", "low_content"))
        if md.large_print:
            self._record(self.s.check(self._c("details", "large_print")), "large_print", "yes")
        self.res.notes.append("Categories must be picked in KDP's 'Choose categories' dialog: " + " | ".join(md.categories))

    def _choose_trim(self, trim: str) -> bool:
        label = trim.replace("x", " x ")  # "8.5x11" -> "8.5 x 11"
        loc = self.s.find(self._c("content", "trim"))
        if loc is None:
            return False
        try:
            tag = loc.evaluate("el => el.tagName.toLowerCase()")
        except Exception:  # noqa: BLE001
            tag = ""
        if tag == "select":
            return self.s.select(self._c("content", "trim"), label_contains=label)
        return self.s.choose_combobox(loc, label_contains=[label + " in", label])

    def fill_content(self) -> None:
        art = artifacts_for(self.book, self.fmt)
        if self.fmt != "ebook":
            p = self.book.print_
            if p.isbn == "kdp_free":
                if self.s.check(self._c("content", "isbn_free")) or self.s.click(self._c("content", "isbn_free")):
                    self.s.click(self._c("content", "isbn_confirm"))
                    self._record(True, "isbn", "free KDP ISBN")
                else:
                    self._record(False, "isbn", "free KDP ISBN")
                    if self.s.find(self._c("content", "isbn_none")) is not None:
                        self.res.notes.append("KDP offers 'Publish without an ISBN' here, which means the Low-content box is ticked on Details; untick it to get a free KDP ISBN for a coloring or text book.")
            elif p.isbn == "own":
                self._record(self.s.check(self._c("content", "isbn_own")), "isbn", "own ISBN")
                if p.isbn_number:
                    self._record(self.s.fill(self._c("content", "isbn_own_input"), p.isbn_number), "isbn_number", p.isbn_number)
                if p.imprint:
                    self._record(self.s.fill(self._c("content", "isbn_imprint_input"), p.imprint), "imprint", p.imprint)
            else:
                self._record(self.s.check(self._c("content", "isbn_none")), "isbn", "publish without ISBN (low-content only)")
            self._record(self.s.check(expand(self.sel["content"]["paper"][p.paper], self.fmt)), "ink_paper", p.paper)
            self._record(self._choose_trim(p.trim), "trim", p.trim)
            self._record(self.s.check(self._c("content", "bleed_yes" if p.bleed else "bleed_no")), "bleed", "yes" if p.bleed else "no")
            self._record(self.s.check(self._c("content", "finish_matte" if p.cover_finish == "matte" else "finish_glossy")), "cover_finish", p.cover_finish)
        if art["manuscript"]:
            ok = self.s.set_files(self._c("content", "manuscript_input"), art["manuscript"]) or self.s.upload_via_button(self._c("content", "manuscript_button"), art["manuscript"])
            self._record(ok, "manuscript_upload", art["manuscript"].name)
        else:
            self._record(False, "manuscript_upload", "missing build artifact")
        if art["cover"]:
            self.s.check(self._c("content", "cover_upload_choice")) or self.s.click(self._c("content", "cover_upload_choice"))
            ok = self.s.set_files(self._c("content", "cover_input"), art["cover"]) or self.s.upload_via_button(self._c("content", "cover_button"), art["cover"])
            self._record(ok, "cover_upload", art["cover"].name)
            self.res.notes.append("Leave 'my cover has a barcode' unticked: the cover keeps a white box where KDP prints its own barcode.")
        else:
            self._record(False, "cover_upload", "missing build artifact")
        self.fill_ai_disclosure()

    def fill_pricing(self) -> None:
        pr = self.book.pricing
        self._record(self.s.check(self._c("pricing", "all_territories")), "territories", "All territories (worldwide rights)")
        self._choose_primary_marketplace()
        if self.fmt == "ebook":
            price = pr.ebook_list_price or pr.list_price
            if pr.kdp_select:
                self._record(self.s.check(self._c("pricing", "kdp_select")), "kdp_select", "enroll")
        else:
            price = pr.list_price
            # distribution columns: the book must stay on sale in every Amazon store; Expanded Distribution follows book.yaml
            amazon_all = self._c("pricing", "amazon_all")
            if self.s.find(amazon_all) is not None:
                self._record(self.s.check(amazon_all), "amazon_stores", "all marketplaces enrolled")
            ed_all, ed_us = self._c("pricing", "expanded_distribution_all"), self._c("pricing", "expanded_distribution")
            if pr.expanded_distribution:
                self._record(self.s.check(ed_all) or self.s.check(ed_us), "expanded_distribution", "yes")
            elif self.s.find(ed_all) is not None:
                self._record(self.s.uncheck(ed_all), "expanded_distribution", "no")
            elif self.s.find(ed_us) is not None:
                self._record(self.s.uncheck(ed_us), "expanded_distribution", "no")
        price_us = self._c("pricing", "price_us")
        self._record(self.s.fill(price_us, f"{price:.2f}"), "list_price_us", f"{price:.2f}")
        self.s.press(price_us, "Tab")  # commit the value so KDP converts the other marketplaces
        self._base_other_marketplaces()

    def _choose_primary_marketplace(self) -> None:
        """The redesigned Pricing tab repeats the primary marketplace as a combobox (older UI: a <select>)."""
        cands = self._c("pricing", "primary_marketplace")
        loc = self.s.find(cands)
        if loc is None:
            return
        try:
            tag = loc.evaluate("el => el.tagName.toLowerCase()")
        except Exception:  # noqa: BLE001
            tag = ""
        label = {"amazon.com": "Amazon.com"}.get(self.book.pricing.marketplace, self.book.pricing.marketplace)
        if tag == "select":
            ok = self.s.select(cands, label_equals=label, label_contains=label)
        else:
            ok = self.s.choose_combobox(loc, label_equals=label, label_contains=label)
        self._record(ok, "primary_marketplace", label)

    def _base_other_marketplaces(self) -> None:
        """KDP converts the other marketplaces from the Amazon.com price. Where it left a row empty, click that
        row's 'Base this price on Amazon.com' so no marketplace goes out without a price. Rows are re-read after
        every click because React may re-render the buttons."""
        self._pause(800)
        base = self._c("pricing", "base_on_us")
        clicked: list[str] = []
        skipped: list[str] = []
        rows: list[dict] = []
        for _ in range(24):
            rows = self.s.marketplace_prices()
            todo = [r for r in rows if not self._is_us_row(r) and r["value"] in ("", "0", "0.00") and r["label"] not in skipped]
            if not todo:
                break
            row = todo[0]
            if row["base_index"] is None or not self.s.click_nth(base, row["base_index"]):
                skipped.append(row["label"])
                continue
            clicked.append(row["label"])
            self._pause(300)
        if not rows:
            return  # older UI without per-marketplace inputs: nothing to do
        if clicked:
            self.res.notes.append("Based on the Amazon.com price: " + ", ".join(clicked))
        for label in skipped:
            self._record(False, f"price:{label}", "enter by hand or click 'Base this price on Amazon.com'")
        if not skipped:
            self._record(True, "other_marketplace_prices", "based on Amazon.com")

    def _pause(self, ms: int) -> None:
        try:
            self.s.page.wait_for_timeout(ms)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _is_us_row(row: dict) -> bool:
        label = (row.get("label") or "").lower()
        return row.get("id") == "price-input-usd" or label.startswith("price for amazon.com in") or "us-price" in (row.get("id") or "")

    # ---------------------------------------------------------------- run
    def run(self, start_url: str | None = None) -> FlowResult:
        res = self.res
        try:
            self.s.goto(start_url or self.sel["bookshelf_url"])
            self._wait_access()
            self.create_title()
            self._wait_access()

            self.fill_details()
            self._shot("details")
            self._gate(self._summary("Details") + "\nReview the Details tab in the browser. [Enter] = click 'Save and Continue', q = stop:")
            if not self.s.click(self._c("details", "save_continue")):
                self._gate("Click 'Save and Continue' yourself, then press Enter:")
            if not self._await(self._c("content", "page_markers"), timeout_s=60):
                self._gate("The Content tab did not appear. Open it yourself, then press Enter:")
                self._await(self._c("content", "page_markers"), timeout_s=2)  # a late limit dialog still stops the run
            if self.resume:
                self.res.notes.append("Resumed an existing KDP draft: no title creation counted toward the weekly limit.")
            else:
                self._event("created", "details saved")
            if self.store is not None:
                self.store.upsert_title(self.book.id, self.fmt, "draft", title=self.book.metadata.full_title)
            self.fill_content()
            self._shot("content")
            self._gate(self._summary("Content") + "\nWait for KDP to finish processing both uploads, open 'Launch Previewer' and approve it yourself. Then [Enter] = click 'Save and Continue', q = stop:")
            if not self.s.click(self._c("content", "save_continue")):
                self._gate("Click 'Save and Continue' yourself, then press Enter:")

            if not self.s.wait_for(self._c("pricing", "page_markers"), timeout_s=60):
                self._gate("The Pricing tab did not appear. Open it yourself, then press Enter:")
            self.fill_pricing()
            self._shot("pricing")
            for _ in range(3):
                ans = self._gate(
                    self._summary("Pricing")
                    + "\nThis tool never clicks Publish. Review everything; if it is right, click 'Publish' yourself in the browser.\n"
                    "Then type: p = I clicked Publish, d = I saved it as a draft, q = stop:"
                )
                if ans in ("p", "published", "publish"):
                    self._event("submitted", "human clicked Publish")
                    if self.store is not None:
                        self.store.upsert_title(self.book.id, self.fmt, "in_review", title=self.book.metadata.full_title)
                    res.status = "submitted"
                    break
                if ans in ("d", "draft"):
                    self._event("draft_saved", "human saved as draft")
                    res.status = "draft"
                    break
            else:
                res.status = "stopped_before_publish"
        except FlowStopped as stop:
            res.status = stop.status
            if str(stop):
                res.notes.append(f"Stopped: {stop}")
            if stop.status == "aborted":
                self._event("aborted", str(stop) or None)
        except Exception as exc:  # noqa: BLE001 - keep the run log (flow.json) even when KDP or the browser misbehaves
            log.exception("assisted flow failed")
            res.status = "error"
            msg = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}" if str(exc).strip() else type(exc).__name__
            res.notes.append(f"Flow stopped by an error: {msg}")
            try:
                self._event("error", msg)
            except Exception:  # noqa: BLE001
                pass
        res.finished = dt.datetime.now(dt.timezone.utc).isoformat()
        return res

    def _summary(self, step: str) -> str:
        lines = [f"--- {step}: filled {len(self.res.filled)} field(s)"]
        if self.res.unfilled:
            lines.append("NOT filled (enter by hand): " + "; ".join(f"{f} = {v}" for f, v in self.res.unfilled))
        if self.res.notes:
            lines.extend(self.res.notes[-3:])
        return "\n".join(lines)


def run_flow(book: Book, fmt: str, session: BrowserSession, selectors: dict, approver: Approver, store: PublishStore | None = None, start_url: str | None = None, book_path: str | None = None, resume: bool = False) -> FlowResult:
    return Flow(book, fmt, session, selectors, approver, store, book_path, resume=resume).run(start_url)
