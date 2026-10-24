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
    # KDP's modal when the weekly creation limit is used up (seen live 2026-10-23 after 'Save and Continue' on Details)
    "limit_markers": ["text=Title creation limit reached", "text=weekly title creation limit"],
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
    # AI-generated content lives on the Content tab (verified 2026-10-23): radios name=has-ai-content
    # followed by three unnamed ARIA comboboxes (text, images, translations) that the flow fills by order.
    "ai": {
        "ai_yes": ["input[name='has-ai-content'][value='yes']", "#data-{fmt}-ai-content-yes", "input[name*='ai_content'][value='true']", "input[name*='ai-content'][value='true']"],
        "ai_no": ["input[name='has-ai-content'][value='no']", "#data-{fmt}-ai-content-no", "input[name*='ai_content'][value='false']", "input[name*='ai-content'][value='false']"],
        # legacy <select> variants (older UI / eBook flow); the React comboboxes have no stable ids
        "ai_text": ["#data-{fmt}-ai-content-text", "select[name*='ai_content'][name*='text']", "select[name*='ai-content'][name*='text']"],
        "ai_images": ["#data-{fmt}-ai-content-images", "select[name*='ai_content'][name*='image']", "select[name*='ai-content'][name*='image']"],
        "ai_translation": ["#data-{fmt}-ai-content-translation", "select[name*='ai_content'][name*='translat']", "select[name*='ai-content'][name*='translat']"],
        # 2026-10: KDP asks which AI tools were used (text inputs, placeholder 'e.g. DALL-E') and for a confirmation tick
        "ai_tools_input": ["input[placeholder*='DALL-E']", "input[aria-label*='AI tool']", "input[name*='ai-tool']", "input[name*='aiTool']"],
        "ai_confirm": ["label:has-text('I confirm that my answers are accurate')", "input[type='checkbox'][name*='confirm']", "[role='checkbox'][aria-label*='confirm']"],
    },
    # Content tab (React redesign, verified 2026-10-23 on a paperback draft). Trim size and the AI
    # dropdowns are custom comboboxes; uploads open the native file chooser from a button.
    "content": {
        "page_markers": ["input[name='isbn-type']", "#ink-paper-BW_WHITE", "button:has-text('Upload manuscript')", "#data-print-book-publisher-interior-file-upload"],
        "isbn_none": ["input[name='isbn-type'][value='NONE']", "label:has-text('Publish without an ISBN')"],
        "isbn_own": ["input[name='isbn-type'][value='OWNER']", "label:has-text('Add your own ISBN')"],
        "isbn_own_input": ["#owner-isbn", "input[name*='isbn']"],
        "isbn_imprint_input": ["#owner-imprint", "input[name*='imprint']"],
        # free KDP ISBN: shown only when the title is NOT low-content (unverified values)
        "isbn_free": ["input[name='isbn-type'][value='KDP']", "input[name='isbn-type'][value='FREE']", "input[name='isbn-type'][value='AMAZON']", "label:has-text('Get a free KDP ISBN')", "label:has-text('free KDP ISBN')", "#free-print-isbn-btn-announce"],
        "isbn_confirm": ["button:has-text('Assign me a free KDP ISBN')", "button:has-text('Assign ISBN')", "#print-isbn-confirm-button-announce"],
        "paper": {
            "white_bw": ["#ink-paper-BW_WHITE", "input[value='BW_WHITE']", "#data-print-book-paper-type-black-and-white-white"],
            "cream_bw": ["#ink-paper-BW_CREAM", "input[value='BW_CREAM']", "#data-print-book-paper-type-black-and-white-cream"],
            "groundwood_bw": ["#ink-paper-BW_GROUNDWOOD", "input[value='BW_GROUNDWOOD']"],
            "standard_color": ["#ink-paper-COLOR_WHITE", "input[value='COLOR_WHITE']", "#data-print-book-paper-type-standard-color-white"],
            "premium_color": ["#ink-paper-COLOR_COLOR", "input[value='COLOR_COLOR']", "#data-print-book-paper-type-premium-color-white"],
        },
        "trim": [{"role": "combobox", "name": "Trim Size"}, "#data-print-book-trim-size", "select[name*='trim']"],
        "bleed_yes": ["#bleed-yes", "input[value='bleed']", "#data-print-book-bleed-yes", "label:has-text('Bleed (PDF only)')"],
        "bleed_no": ["#bleed-no", "input[value='no-bleed']", "#data-print-book-bleed-no", "label:has-text('No Bleed')"],
        "finish_matte": ["#cover-finish-MATTE", "input[value='MATTE']", "#data-print-book-cover-finish-matte"],
        "finish_glossy": ["#cover-finish-GLOSSY", "input[value='GLOSSY']", "#data-print-book-cover-finish-glossy"],
        "manuscript_button": ["button:has-text('Upload manuscript')", "button:has-text('Upload paperback manuscript')", "button:has-text('Upload eBook manuscript')"],
        "manuscript_input": ["#data-print-book-publisher-interior-file-upload", "#data-ebook-publisher-file-upload", "input[type='file'][name*='interior']", "input[type='file'][name*='manuscript']"],
        "cover_upload_choice": ["input[name='cover-choice'][value='UPLOAD']", "label:has-text('Upload a cover you already have')", "#data-print-book-publisher-cover-choice-accordion"],
        "cover_button": ["button:has-text('Upload your cover file')", "button:has-text('Upload cover')"],
        "cover_input": ["#data-print-book-publisher-cover-file-upload", "#data-ebook-publisher-cover-file-upload", "input[type='file'][name*='cover']"],
        "cover_has_barcode": ["#publisher-barcode", "[role='checkbox']:has-text('my cover has a barcode')"],
        "upload_ok": ["text=Manuscript uploaded successfully", "text=Cover uploaded successfully", "text=uploaded successfully"],
        "previewer": ["button:has-text('Launch Previewer')", "#print-previewer-button-announce", "#ebook-previewer-button-announce"],
        "save_draft": ["button:has-text('Save as Draft')", "#save-announce"],
        "save_continue": ["button:has-text('Save and Continue')", "#save-and-continue-announce"],
    },
    # Rights & Pricing tab (React redesign, verified 2026-10-23 on a paperback draft at print-setup/<fmt>/<id>/pricing).
    # Territory radios carry ids; the distribution checkboxes are ARIA checkboxes known only by their aria-label;
    # price inputs are #price-input-<currency> (the EUR id repeats across seven marketplaces, so aria-labels win).
    # The eBook variant (KDP Select, royalty plan) has not been probed yet - those candidates are still guesses.
    "pricing": {
        "page_markers": ["#worldwide-rights", "input[name='territory-selection-type']", "#price-input-usd", "button:has-text('Publish Your')", "input[id*='us-price']"],
        "all_territories": ["#worldwide-rights", "input[name='territory-selection-type'][value='worldwide']", "#data-print-book-pricing-rights-all-territories", "#data-ebook-pricing-rights-all-territories", {"role": "radio", "name": "All territories"}],
        "individual_territories": ["#individual-territories", "input[name='territory-selection-type'][value='individual']"],
        "primary_marketplace": ["#primary-marketplace", {"role": "combobox", "name": "Primary marketplace"}, "select[name*='home_marketplace']"],
        # distribution columns: "Amazon" = on sale in that Amazon store (keep all ticked); Expanded Distribution exists for .com and .co.uk only
        "amazon_all": ["[role='checkbox'][aria-label='Enroll all marketplaces in Amazon program']"],
        "amazon_us": ["[role='checkbox'][aria-label='Enroll in Amazon program for Amazon.com']"],
        "expanded_distribution_all": ["[role='checkbox'][aria-label='Enroll all marketplaces in Expanded Distribution program']"],
        "expanded_distribution": ["[role='checkbox'][aria-label='Enroll in Expanded Distribution program for Amazon.com']", "#data-pricing-print-expanded-distribution", "input[name*='expanded']"],
        "expanded_distribution_uk": ["[role='checkbox'][aria-label='Enroll in Expanded Distribution program for Amazon.co.uk']"],
        "price_us": ["#price-input-usd", "input[aria-label='Price for Amazon.com in USD']", "#data-pricing-print-us-price-input", "#data-pricing-ebook-us-price-input", "input[id*='us-price']"],
        "price_inputs": ["input[aria-label^='Price for Amazon']", "input[id^='price-input-']"],
        # one per non-US marketplace, right after its price input; clicked only for rows KDP left empty
        "base_on_us": ["a[aria-label='Base this price on Amazon.com'], [role='button'][aria-label='Base this price on Amazon.com']"],
        "kdp_select": ["#data-ebook-kdp-select-enroll", "input[name*='kdp-select']", "input[name*='kdpSelect']", "[role='checkbox'][aria-label*='KDP Select']", "label:has-text('Enroll my eBook in KDP Select')"],
        "back": ["button:has-text('Back to Content')"],
        "save_draft": ["button:has-text('Save as Draft')", "#save-announce"],
        # located for the page marker and screenshots only - the flow never clicks it
        "publish": ["button:has-text('Publish Your')", "#save-and-publish-announce", "button:has-text('Publish')"],
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


def expand(candidates: list, fmt: str, **kw) -> list:
    """Substitute {fmt}/{fmt_u}/{i} in string candidates; role dicts pass through unchanged."""
    tok = FMT_TOKEN.get(fmt, "print-book")
    tok_u = tok.replace("-", "_")  # form field names use data[print_book][...]
    out: list = []
    for c in candidates:
        if not isinstance(c, str):
            out.append(c)
            continue
        try:
            out.append(c.format(fmt=tok, fmt_u=tok_u, **kw))
        except (KeyError, IndexError):
            out.append(c)
    return out
