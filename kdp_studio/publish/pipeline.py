"""Preconditions -> quota -> browser flow -> run log, for one book and format."""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..findings import FindingList
from ..paths import data_path
from ..preflight.run import run_preflight
from ..schema import Book, load_book
from ..util import write_json
from .browser import BrowserSession
from .checklist import artifacts_for, build_checklist, pdf_pages
from .flow import Approver, FlowResult, run_flow
from .quota import QuotaStatus, quota_status
from .selectors import load_selectors
from .store import PublishStore

log = logging.getLogger(__name__)


def default_profile_dir() -> Path:
    base = os.environ.get("KDP_STUDIO_HOME") or (os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share"))
    return Path(base) / "kdp-studio" / "browser-profile"


@dataclass
class PublishOptions:
    fmt: str = "paperback"
    profile_dir: Path = field(default_factory=default_profile_dir)
    selectors_path: Path | None = None
    store_path: Path = field(default_factory=lambda: data_path("publishing", "publish.sqlite"))
    runs_dir: Path = field(default_factory=lambda: data_path("publishing", "runs"))
    require_preflight: bool = True
    headless_local: bool = False
    start_url: str | None = None
    channels: tuple[str | None, ...] = ("msedge", "chrome", None)
    slow_mo_ms: int = 60
    resume: bool = False  # start_url is an existing draft's Details tab: nothing new is created


def check_preconditions(book: Book, fmt: str, store: PublishStore, require_preflight: bool = True, now: dt.datetime | None = None, resume: bool = False) -> tuple[FindingList, QuotaStatus]:
    f = FindingList()
    if fmt not in book.formats:
        f.warning("publish.format", f"'{fmt}' is not listed in book.formats {book.formats}.", "formats")
    art = artifacts_for(book, fmt)
    if not art["manuscript"]:
        f.error("publish.manuscript_missing", f"No {'EPUB' if fmt == 'ebook' else 'interior.pdf'} in {book.build_dir}; run `kdp build` first.", "build")
    if not art["cover"]:
        f.error("publish.cover_missing", f"No {'cover_ebook.jpg' if fmt == 'ebook' else 'cover_wrap.pdf'} in {book.build_dir}; run `kdp build` first.", "build")
    if require_preflight and art["manuscript"] and art["cover"]:
        pages = pdf_pages(art["manuscript"]) if fmt != "ebook" else pdf_pages(book.build_dir / "interior.pdf")
        report = run_preflight(
            book,
            pages,
            book.build_dir / "interior.pdf" if (book.build_dir / "interior.pdf").is_file() else None,
            book.build_dir / "cover_wrap.pdf" if (book.build_dir / "cover_wrap.pdf").is_file() else None,
            book.build_dir / "cover_ebook.jpg" if (book.build_dir / "cover_ebook.jpg").is_file() else None,
            epub_path=art["manuscript"] if fmt == "ebook" else None,
        )
        for x in report.findings.errors:
            f.error(x.code, x.message, x.where)
        for x in report.findings.warnings:
            f.warning(x.code, x.message, x.where)
    q = quota_status(store, now)[fmt]
    need_create = not resume
    if (need_create and q.remaining_created == 0) or q.remaining_submitted == 0:
        hint = " (KDP showed the limit dialog)" if q.kdp_blocked else ""
        more = "; continuing an existing draft with --resume-url needs no creation." if need_create and q.remaining_submitted > 0 else "."
        f.error("publish.quota", f"KDP weekly limit reached for {fmt}: {q.created}/{q.limit} created, {q.submitted}/{q.limit} submitted in the window ending {q.window_end:%Y-%m-%d %H:%M} UTC{hint}{more}", "quota")
    existing = store.get_title(book.id, fmt)
    if existing and existing["status"] in ("in_review", "live"):
        f.error("publish.already", f"{book.id} ({fmt}) is already {existing['status']}" + (f" as {existing['asin']}" if existing.get("asin") else "") + ".", "publish")
    return f, q


def run_publish(book_path: Path, opts: PublishOptions, approver: Approver, now: dt.datetime | None = None) -> tuple[FlowResult | None, FindingList, Path]:
    book = load_book(book_path)
    store = PublishStore(opts.store_path)
    try:
        findings, quota = check_preconditions(book, opts.fmt, store, opts.require_preflight, now, resume=opts.resume)
        stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%d-%H%M%S")
        run_dir = opts.runs_dir / f"{stamp}-{book.id}-{opts.fmt}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "checklist.md").write_text(build_checklist(book, opts.fmt, quota), encoding="utf-8")
        if findings.errors:
            write_json(run_dir / "preconditions.json", {"ok": False, "findings": [x.as_dict() for x in findings]})
            return None, findings, run_dir

        selectors = load_selectors(opts.selectors_path)
        headless = bool(opts.headless_local)
        with BrowserSession(opts.profile_dir, channels=opts.channels, headless=headless, allow_headless_local=opts.headless_local, start_url=opts.start_url, slow_mo_ms=opts.slow_mo_ms, screenshot_dir=run_dir / "screenshots") as session:
            result = run_flow(book, opts.fmt, session, selectors, approver, store, start_url=opts.start_url, book_path=str(book_path), resume=opts.resume)
        write_json(run_dir / "flow.json", {**result.as_dict(), "book_id": book.id, "format": opts.fmt, "browser": session.channel_used, "preconditions": [x.as_dict() for x in findings]})
        return result, findings, run_dir
    finally:
        store.close()
