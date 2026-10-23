"""Selectors for the KDP title-setup pages.

Amazon changes its DOM without notice, so every field has an ordered list of
candidate selectors (CSS or Playwright text selectors) and the flow falls back to
label text. `{fmt}` expands to `print-book` or `ebook`. Override anything with a
YAML file (`kdp publish selectors --dump` writes the defaults) and use
`kdp publish probe` on a live KDP page to see which candidates match.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

FMT_TOKEN = {"ebook": "ebook", "paperback": "print-book", "hardcover": "print-book"}

DEFAULT_SELECTORS: dict = {
    "bookshelf_url": "https://kdp.amazon.com/bookshelf",
    "signin_markers": ["#ap_email", "#ap_password", "form[name='signIn']", "input[name='email'][type='email']"],
    "captcha_markers": ["#auth-captcha-image", "img[src*='captcha']", "#captchacharacters", "text=Enter the characters you see"],
    "create_button": ["#create-new-title", "a:has-text('+ Create')", "a:has-text('Create')", "button:has-text('Create')"],
    "format_choice": {
        "ebook": ["#ebook-create-title-button", "a:has-text('Create eBook')", "text=Kindle eBook"],
        "paperback": ["#paperback-create-title-button", "a:has-text('Create paperback')", "text=Paperback"],
        "hardcover": ["#hardcover-create-title-button", "a:has-text('Create hardcover')", "text=Hardcover"],
    },
    "details": {
        "language": ["#data-{fmt}-language-select", "select[name*='language']"],
        "title": ["#data-{fmt}-title", "input[name*='title']:not([name*='subtitle'])"],
        "subtitle": ["#data-{fmt}-subtitle", "input[name*='subtitle']"],
        "author_first": ["#data-{fmt}-primary-author-first-name", "#data-{fmt}-contributors-0-first-name"],
        "author_last": ["#data-{fmt}-primary-author-last-name", "#data-{fmt}-contributors-0-last-name"],
        "description": ["#data-{fmt}-description", "textarea[name*='description']", "[id^='cke_'][id$='description'] iframe", "[contenteditable='true']"],
        "rights_own": ["#non-public-domain", "input[value='non-public-domain']", "label:has-text('I own the copyright')"],
        "adult_no": ["#data-{fmt}-is-adult-content-no", "input[name*='adult'][value='false']", "input[name*='adult'][value='no']"],
        "adult_yes": ["#data-{fmt}-is-adult-content-yes", "input[name*='adult'][value='true']"],
        "age_min": ["#data-{fmt}-min-age", "#data-{fmt}-reading-age-min", "select[name*='min']"],
        "age_max": ["#data-{fmt}-max-age", "#data-{fmt}-reading-age-max", "select[name*='max']"],
        "ai_yes": ["#data-{fmt}-ai-content-yes", "input[name*='ai'][value='true']", "input[name*='ai'][value='yes']"],
        "ai_no": ["#data-{fmt}-ai-content-no", "input[name*='ai'][value='false']", "input[name*='ai'][value='no']"],
        "ai_text": ["#data-{fmt}-ai-content-text", "select[name*='ai'][name*='text']"],
        "ai_images": ["#data-{fmt}-ai-content-images", "select[name*='ai'][name*='image']"],
        "ai_translation": ["#data-{fmt}-ai-content-translation", "select[name*='ai'][name*='translat']"],
        "keyword": ["#data-{fmt}-keywords-{i}", "input[name*='keywords-{i}']", "input[name*='keyword'][name*='{i}']"],
        "low_content": ["#data-{fmt}-is-low-content", "#data-{fmt}-low-content", "input[name*='low-content']", "input[name*='lowContent']"],
        "save_continue": ["#save-and-continue-announce", "button:has-text('Save and Continue')", "input[value='Save and Continue']"],
    },
    "content": {
        "isbn_free": ["#free-print-isbn-btn-announce", "button:has-text('Assign me a free KDP ISBN')", "button:has-text('Get a free KDP ISBN')"],
        "isbn_confirm": ["#print-isbn-confirm-button-announce", "button:has-text('Assign ISBN')", "button:has-text('Confirm')"],
        "paper": {
            "white_bw": ["#data-print-book-paper-type-black-and-white-white", "input[value='bw-white']", "label:has-text('white paper'):near(:text('Black & white'))"],
            "cream_bw": ["#data-print-book-paper-type-black-and-white-cream", "input[value='bw-cream']", "label:has-text('cream paper')"],
            "groundwood_bw": ["#data-print-book-paper-type-black-and-white-groundwood", "input[value='bw-groundwood']"],
            "standard_color": ["#data-print-book-paper-type-standard-color-white", "input[value='standard-color']"],
            "premium_color": ["#data-print-book-paper-type-premium-color-white", "input[value='premium-color']"],
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
    "pricing": {
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
    out = []
    for c in candidates:
        try:
            out.append(c.format(fmt=tok, **kw))
        except (KeyError, IndexError):
            out.append(c)
    return out
