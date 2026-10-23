"""Selectors for the KDP title-setup pages.

Verified against a live KDP account on 2026-10-23 (Bookshelf and Paperback Details
probe dumps); Content and Pricing entries marked `unverified` still follow the same
naming scheme and must be checked with `kdp publish probe`. Amazon changes its DOM
without notice, so every field has an ordered list of candidate selectors (CSS or
Playwright text selectors) and the flow falls back to label text. `{fmt}` expands to
`print-book` or `ebook`. Override anything with a YAML file (`kdp publish selectors
--dump` writes the defaults).
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

FMT_TOKEN = {"ebook": "ebook", "paperback": "print-book", "hardcover": "print-book"}

# Paths of the three title-setup tabs per format (seen on the live site)
TITLE_SETUP_PATH = {"ebook": "title-setup/kindle", "paperback": "title-setup/paperback", "hardcover": "title-setup/hardcover"}

DEFAULT_SELECTORS: dict = {
    "bookshelf_url": "https://kdp.amazon.com/bookshelf",
    "signin_markers": ["#ap_email", "#ap_password", "form[name='signIn']", "input[name='email'][type='email']"],
    "captcha_markers": ["#auth-captcha-image", "img[src*='captcha']", "#captchacharacters", "text=Enter the characters you see"],
    # Bookshelf: the yellow "+ Create new title or series" button is a plain anchor to /create
    "create_button": ["a[href*='/create']:has-text('Create')", "a:has-text('Create new title')", "text=Create new title or series", "a:has-text('+ Create')", "button:has-text('Create')"],
    # /create page: one entry per format (anchors into title-setup/<format>/new/details)
    "format_choice": {
        "ebook": ["a[href*='title-setup/kindle/new/details']", "a:has-text('Create eBook')", "text=Kindle eBook"],
        "paperback": ["a[href*='title-setup/paperback/new/details']", "a:has-text('Create paperback')", "text=Paperback"],
        "hardcover": ["a[href*='title-setup/hardcover/new/details']", "a:has-text('Create hardcover')", "text=Hardcover"],
    },
    "details": {
        "language": ["#data-{fmt}-language-native", "select[name='data[{fmt_u}][language]']", "select[name*='language']"],
        "title": ["#data-{fmt}-title", "input[name='data[{fmt_u}][title]']"],
        "subtitle": ["#data-{fmt}-subtitle", "input[name='data[{fmt_u}][subtitle]']"],
        "edition": ["#data-{fmt}-edition-number", "input[name*='edition_number']"],
        "author_first": ["#data-{fmt}-primary-author-first-name", "input[name*='primary_author][first_name']"],
        "author_last": ["#data-{fmt}-primary-author-last-name", "input[name*='primary_author][last_name']"],
        # description is a CKEditor instance; fill_rich() uses the CKEDITOR JS API first, these are fallbacks
        "description": [".cke_editable[contenteditable='true']", "iframe.cke_wysiwyg_frame", "[contenteditable='true']", "textarea[name*='description']"],
        "rights_own": ["#non-public-domain", "input[name*='is-public-domain'][value='false']", "label:has-text('I own the copyright')"],
        # Keep name-based fallbacks specific: a bare name*='adult' or name*='ai' also matches unrelated
        # fields (e.g. 'is-public-dom*ai*n'), which would silently change a legal declaration.
        "adult_no": ["input[name*='is_adult_content'][value='false']", "#data-{fmt}-is-adult-content-no"],
        "adult_yes": ["input[name*='is_adult_content'][value='true']", "#data-{fmt}-is-adult-content-yes"],
        "age_min": ["#data-{fmt}-reading-interest-age-start-input-native", "select[name*='reading_interest_age][min']"],
        "age_max": ["#data-{fmt}-reading-interest-age-end-input-native", "select[name*='reading_interest_age][max']"],
        "primary_marketplace": ["select[name*='home_marketplace']"],
        "categories_button": ["#categories-modal-button", "button:has-text('Choose categories')"],
        "low_content": ["#data-view-is-lcb", "input[name*='is_lcb']", "#data-{fmt}-is-low-content"],
        "large_print": ["#data-{fmt}-large-print", "input[name*='large_print']"],
        "keyword": ["#data-{fmt}-keywords-{i}", "input[name='data[{fmt_u}][keywords][{i}]']"],
        "save_draft": ["#save-announce", "button:has-text('Save as Draft')"],
        "save_continue": ["#save-and-continue-announce", "button:has-text('Save and Continue')"],
    },
    # AI-generated content lives on the Content tab (not on Details); the flow fills it wherever it finds it.
    "ai": {  # unverified ids; names must contain 'ai_content'/'ai-content'/'generative' - never a bare 'ai'
        "ai_yes": ["#data-{fmt}-ai-content-yes", "input[name*='ai_content'][value='true']", "input[name*='ai-content'][value='true']", "input[name*='generative'][value='true']", "input[name*='ai_content'][value='yes']"],
        "ai_no": ["#data-{fmt}-ai-content-no", "input[name*='ai_content'][value='false']", "input[name*='ai-content'][value='false']", "input[name*='generative'][value='false']", "input[name*='ai_content'][value='no']"],
        "ai_text": ["#data-{fmt}-ai-content-text", "select[name*='ai_content'][name*='text']", "select[name*='ai-content'][name*='text']", "select[name*='generative'][name*='text']"],
        "ai_images": ["#data-{fmt}-ai-content-images", "select[name*='ai_content'][name*='image']", "select[name*='ai-content'][name*='image']", "select[name*='generative'][name*='image']"],
        "ai_translation": ["#data-{fmt}-ai-content-translation", "select[name*='ai_content'][name*='translat']", "select[name*='ai-content'][name*='translat']", "select[name*='generative'][name*='translat']"],
    },
    "content": {  # unverified: probe the Content tab and adjust
        "isbn_free": ["#free-print-isbn-btn-announce", "button:has-text('Assign me a free KDP ISBN')", "button:has-text('Get a free KDP ISBN')"],
        "isbn_confirm": ["#print-isbn-confirm-button-announce", "button:has-text('Assign ISBN')", "button:has-text('Confirm')"],
        "paper": {
            "white_bw": ["#data-print-book-paper-type-black-and-white-white", "input[value='bw-white']", "input[name*='paper'][value*='white']:not([value*='color'])"],
            "cream_bw": ["#data-print-book-paper-type-black-and-white-cream", "input[value='bw-cream']", "input[name*='paper'][value*='cream']"],
            "groundwood_bw": ["#data-print-book-paper-type-black-and-white-groundwood", "input[value='bw-groundwood']", "input[name*='paper'][value*='groundwood']"],
            "standard_color": ["#data-print-book-paper-type-standard-color-white", "input[value='standard-color']", "input[name*='paper'][value*='standard']"],
            "premium_color": ["#data-print-book-paper-type-premium-color-white", "input[value='premium-color']", "input[name*='paper'][value*='premium']"],
        },
        "trim": ["#data-print-book-trim-size", "select[name*='trim']", "#trim-size-select"],
        "bleed_yes": ["#data-print-book-bleed-yes", "input[name*='bleed'][value='true']", "label:has-text('Bleed (PDF only)')"],
        "bleed_no": ["#data-print-book-bleed-no", "input[name*='bleed'][value='false']", "label:has-text('No Bleed')"],
        "finish_matte": ["#data-print-book-cover-finish-matte", "input[name*='finish'][value='matte']", "label:has-text('Matte')"],
        "finish_glossy": ["#data-print-book-cover-finish-glossy", "input[name*='finish'][value='glossy']", "label:has-text('Glossy')"],
        "manuscript_input": ["#data-print-book-publisher-interior-file-upload", "#data-ebook-publisher-file-upload", "input[type='file'][name*='interior']", "input[type='file'][name*='manuscript']", "input[type='file']"],
        "cover_own": ["#data-print-book-publisher-cover-choice-accordion", "#data-ebook-publisher-cover-choice-accordion", "text=Upload a cover you already have", "text=Upload your cover file"],
        "cover_input": ["#data-print-book-publisher-cover-file-upload", "#data-ebook-publisher-cover-file-upload", "input[type='file'][name*='cover']"],
        "upload_ok": ["text=Manuscript uploaded successfully", "text=Cover uploaded successfully", "text=uploaded successfully"],
        "previewer": ["#print-previewer-button-announce", "#ebook-previewer-button-announce", "button:has-text('Launch Previewer')"],
        "save_continue": ["#save-and-continue-announce", "button:has-text('Save and Continue')"],
    },
    "pricing": {  # unverified: probe the Pricing tab and adjust
        "all_territories": ["#data-print-book-pricing-rights-all-territories", "#data-ebook-pricing-rights-all-territories", "input[name*='territor'][value='all']", "label:has-text('All territories')"],
        "kdp_select": ["#data-ebook-kdp-select-enroll", "input[name*='kdp-select']", "input[name*='kdpSelect']"],
        "price_us": ["#data-pricing-print-us-price-input", "#data-pricing-ebook-us-price-input", "input[id*='us-price']", "input[name*='price'][name*='US']"],
        "expanded_distribution": ["#data-pricing-print-expanded-distribution", "input[name*='expanded']"],
        "publish": ["#save-and-publish-announce", "button:has-text('Publish Your')", "button:has-text('Publish')"],
    },
}


def load_selectors(path: Path | None = None) -> dict:
    sel = copy.deepcopy(DEFAULT_SELECTORS)
    if path and Path(path).is_file():
        override = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        _merge(sel, override)
    return sel


def _merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def dump_default_yaml() -> str:
    return yaml.safe_dump(DEFAULT_SELECTORS, sort_keys=False, allow_unicode=True, width=200)


def expand(candidates: list[str], fmt: str, **kw) -> list[str]:
    tok = FMT_TOKEN.get(fmt, "print-book")
    tok_u = tok.replace("-", "_")  # form field names use data[print_book][...]
    out = []
    for c in candidates:
        try:
            out.append(c.format(fmt=tok, fmt_u=tok_u, **kw))
        except (KeyError, IndexError):
            out.append(c)
    return out
