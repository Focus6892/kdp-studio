"""Inspect PDFs with pypdf and check them against KDP print requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from .. import specs
from ..cover.geometry import cover_geometry
from ..findings import FindingList
from ..schema import Book
from ..util import file_mb

PT_TOLERANCE = 1.0


@dataclass
class ImageInfo:
    width: int
    height: int
    colorspace: str
    bpc: int
    has_smask: bool
    filters: list[str]


@dataclass
class FontInfo:
    name: str
    subtype: str
    embedded: bool


@dataclass
class PageInfo:
    number: int
    width_pt: float
    height_pt: float
    images: list[ImageInfo] = field(default_factory=list)
    fonts: list[FontInfo] = field(default_factory=list)
    transparency_group: bool = False
    annotations: int = 0


@dataclass
class PdfInfo:
    path: Path
    file_mb: float
    encrypted: bool
    pages: list[PageInfo]


def _obj(x):
    return x.get_object() if hasattr(x, "get_object") else x


def _colorspace_name(cs) -> str:
    cs = _obj(cs)
    if cs is None:
        return "unknown"
    if isinstance(cs, (list, tuple)):
        head = str(_obj(cs[0]))
        if head == "/ICCBased" and len(cs) > 1:
            stream = _obj(cs[1])
            n = _obj(stream.get("/N")) if hasattr(stream, "get") else None
            return f"/ICCBased(N={n})"
        if head == "/Indexed" and len(cs) > 1:
            return f"/Indexed({_colorspace_name(cs[1])})"
        return head
    return str(cs)


def _filters(x) -> list[str]:
    f = _obj(x.get("/Filter"))
    if f is None:
        return []
    if isinstance(f, (list, tuple)):
        return [str(_obj(i)) for i in f]
    return [str(f)]


def _walk_resources(res, page: PageInfo, depth: int = 0, seen: set | None = None) -> None:
    seen = seen if seen is not None else set()
    res = _obj(res)
    if not hasattr(res, "get") or depth > 6:
        return
    fonts = _obj(res.get("/Font"))
    if hasattr(fonts, "items"):
        for _, ref in fonts.items():
            font = _obj(ref)
            subtype = str(_obj(font.get("/Subtype")))
            descriptor = None
            if subtype == "/Type0":
                desc = _obj(font.get("/DescendantFonts"))
                if desc:
                    descriptor = _obj(_obj(desc[0]).get("/FontDescriptor"))
            else:
                descriptor = _obj(font.get("/FontDescriptor"))
            embedded = bool(descriptor) and any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3"))
            page.fonts.append(FontInfo(str(_obj(font.get("/BaseFont"))), subtype, embedded))
    xobjects = _obj(res.get("/XObject"))
    if hasattr(xobjects, "items"):
        for _, ref in xobjects.items():
            key = getattr(ref, "idnum", id(ref))
            if key in seen:
                continue
            seen.add(key)
            x = _obj(ref)
            st = str(_obj(x.get("/Subtype")))
            if st == "/Image":
                page.images.append(
                    ImageInfo(
                        width=int(_obj(x.get("/Width"))),
                        height=int(_obj(x.get("/Height"))),
                        colorspace=_colorspace_name(x.get("/ColorSpace")),
                        bpc=int(_obj(x.get("/BitsPerComponent")) or 0),
                        has_smask=("/SMask" in x) or ("/Mask" in x),
                        filters=_filters(x),
                    )
                )
            elif st == "/Form":
                group = _obj(x.get("/Group"))
                if hasattr(group, "get") and str(_obj(group.get("/S"))) == "/Transparency":
                    page.transparency_group = True
                _walk_resources(x.get("/Resources"), page, depth + 1, seen)


def inspect_pdf(path: Path) -> PdfInfo:
    reader = PdfReader(str(path))
    pages: list[PageInfo] = []
    for i, p in enumerate(reader.pages, start=1):
        mb = p.mediabox
        info = PageInfo(i, float(mb.width), float(mb.height))
        _walk_resources(p.get("/Resources"), info)
        group = _obj(p.get("/Group"))
        if hasattr(group, "get") and str(_obj(group.get("/S"))) == "/Transparency":
            info.transparency_group = True
        annots = _obj(p.get("/Annots"))
        info.annotations = len(annots) if annots else 0
        pages.append(info)
    return PdfInfo(path, file_mb(path), bool(reader.is_encrypted), pages)


def _size_ok(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= PT_TOLERANCE


def check_interior_pdf(path: Path, book: Book) -> tuple[FindingList, PdfInfo | None]:
    f = FindingList()
    where = str(path.name)
    if not path.is_file():
        f.error("interior.missing", f"Interior PDF not found: {path}", where)
        return f, None
    info = inspect_pdf(path)
    trim = book.print_.trim_size
    bleed = book.print_.bleed
    n = len(info.pages)

    if info.encrypted:
        f.error("interior.encrypted", "PDF is encrypted/locked; KDP rejects secured files.", where)
    if info.file_mb > specs.MAX_FILE_MB:
        f.error("interior.filesize", f"{info.file_mb:.0f} MB exceeds KDP's {specs.MAX_FILE_MB} MB limit.", where)

    lo, hi = specs.page_range(book.print_.trim, book.print_.paper)
    if n < lo:
        f.error("interior.pages_min", f"{n} pages; KDP minimum is {lo}.", where)
    if n > hi:
        f.error("interior.pages_max", f"{n} pages; KDP maximum for {trim.key}/{book.print_.paper} is {hi}.", where)
    if n % 2:
        f.warning("interior.pages_odd", f"{n} pages is odd; KDP rounds up and adds a blank page, which changes spine width. Pad the file yourself.", where)

    exp_w, exp_h = (specs.pt(v) for v in specs.page_size_in(trim, bleed))
    bad_sizes = [p.number for p in info.pages if not (_size_ok(p.width_pt, exp_w) and _size_ok(p.height_pt, exp_h))]
    if bad_sizes:
        sample = info.pages[bad_sizes[0] - 1]
        f.error(
            "interior.page_size",
            f"{len(bad_sizes)} page(s) are {sample.width_pt / 72:.3f}x{sample.height_pt / 72:.3f} in; expected {exp_w / 72:.3f}x{exp_h / 72:.3f} in "
            f"({'with' if bleed else 'without'} bleed). First: page {bad_sizes[0]}.",
            where,
        )

    for p in info.pages:
        for ft in p.fonts:
            if not ft.embedded:
                f.error("interior.font_not_embedded", f"Font {ft.name} ({ft.subtype}) on page {p.number} is not embedded.", where)
        if p.annotations:
            f.error("interior.annotations", f"Page {p.number} has {p.annotations} annotation(s)/comments; remove them.", where)
        if p.transparency_group:
            f.warning("interior.transparency", f"Page {p.number} uses a transparency group; flatten before upload.", where)
        for im in p.images:
            est_dpi = im.width / trim.width_in
            if im.has_smask:
                f.error("interior.image_transparency", f"Image {im.width}x{im.height} on page {p.number} has a soft mask (transparency); flatten it.", where)
            if est_dpi < specs.DPI - 1:
                f.error(
                    "interior.image_dpi",
                    f"Image {im.width}x{im.height} on page {p.number} is ~{est_dpi:.0f} DPI if it spans the page width; KDP needs {specs.DPI}.",
                    where,
                )
            if est_dpi > 600:
                f.info("interior.image_dpi_high", f"Image on page {p.number} is ~{est_dpi:.0f} DPI; KDP recommends at most 600 to avoid processing timeouts.", where)
            if book.print_.paper.endswith("_bw") and ("RGB" in im.colorspace or "N=3" in im.colorspace or "N=4" in im.colorspace or "CMYK" in im.colorspace):
                f.info("interior.image_color", f"Color image ({im.colorspace}) on page {p.number} in a black-ink book; KDP converts to grayscale. Convert yourself for predictable output.", where)
    return f, info


def check_cover_pdf(path: Path, book: Book, pages: int) -> tuple[FindingList, PdfInfo | None]:
    f = FindingList()
    where = str(path.name)
    if not path.is_file():
        f.error("cover.missing", f"Cover PDF not found: {path}", where)
        return f, None
    info = inspect_pdf(path)
    geo = cover_geometry(book.print_.trim, pages, book.print_.paper)

    if info.encrypted:
        f.error("cover.encrypted", "Cover PDF is encrypted/locked.", where)
    if len(info.pages) != 1:
        f.error("cover.page_count", f"Cover PDF has {len(info.pages)} pages; KDP needs exactly one page (back + spine + front).", where)
    if info.file_mb > specs.MAX_FILE_MB:
        f.error("cover.filesize", f"{info.file_mb:.0f} MB exceeds {specs.MAX_FILE_MB} MB.", where)
    elif info.file_mb > specs.RECOMMENDED_COVER_MB:
        f.warning("cover.filesize_large", f"{info.file_mb:.1f} MB; KDP recommends covers under {specs.RECOMMENDED_COVER_MB} MB.", where)

    exp_w, exp_h = geo.size_pt
    if info.pages:
        p = info.pages[0]
        if not (_size_ok(p.width_pt, exp_w) and _size_ok(p.height_pt, exp_h)):
            f.error(
                "cover.size",
                f"Cover is {p.width_pt / 72:.4f}x{p.height_pt / 72:.4f} in; expected {geo.width_in:.4f}x{geo.height_in:.4f} in for {pages} pages on {book.print_.paper} (spine {geo.spine_in:.4f} in).",
                where,
            )
        for ft in p.fonts:
            if not ft.embedded:
                f.error("cover.font_not_embedded", f"Font {ft.name} is not embedded.", where)
        if p.transparency_group:
            f.error("cover.transparency", "Cover uses a transparency group; flatten it.", where)
        if p.annotations:
            f.error("cover.annotations", "Cover has annotations; remove them.", where)
        if not p.images:
            f.info("cover.vector_only", "No raster images found; cover is vector/text only.", where)
        for im in p.images:
            if im.has_smask:
                f.error("cover.image_transparency", "Cover image has a soft mask (transparency); flatten it.", where)
            if "CMYK" not in im.colorspace and "N=4" not in im.colorspace:
                f.warning("cover.colorspace", f"Cover image colorspace is {im.colorspace}; KDP asks for CMYK and converts RGB itself (colors may shift).", where)
            est_dpi = im.width / geo.width_in
            if est_dpi < specs.DPI - 1:
                f.error("cover.image_dpi", f"Cover image {im.width}x{im.height} is ~{est_dpi:.0f} DPI across the wrap; KDP needs {specs.DPI}.", where)
    if book.cover.spine_text is True and not geo.spine_text_allowed:
        f.error("cover.spine_text", f"Spine text requires at least {specs.SPINE_TEXT_MIN_PAGES} pages; book has {pages}.", "cover.spine_text")
    return f, info


def check_ebook_cover(path: Path) -> FindingList:
    f = FindingList()
    where = str(path.name)
    if not path.is_file():
        f.error("ebook_cover.missing", f"eBook cover not found: {path}", where)
        return f
    with Image.open(path) as im:
        w, h = im.size
        mode, fmt = im.mode, im.format
    if fmt not in ("JPEG", "TIFF"):
        f.error("ebook_cover.format", f"Format {fmt}; KDP accepts JPEG or TIFF.", where)
    if mode != "RGB":
        f.error("ebook_cover.mode", f"Color mode {mode}; KDP requires RGB.", where)
    min_w, min_h = specs.EBOOK_COVER_MIN
    if w < min_w or h < min_h:
        f.error("ebook_cover.too_small", f"{w}x{h}; minimum is {min_w}x{min_h}.", where)
    if max(w, h) > specs.EBOOK_COVER_MAX_SIDE:
        f.error("ebook_cover.too_large", f"{w}x{h}; no side may exceed {specs.EBOOK_COVER_MAX_SIDE}px.", where)
    if h / w < specs.EBOOK_COVER_MIN_RATIO - 0.005:
        f.error("ebook_cover.ratio", f"Aspect ratio {h / w:.3f}; KDP requires at least {specs.EBOOK_COVER_MIN_RATIO}:1 (height:width).", where)
    ideal_w, ideal_h = specs.EBOOK_COVER_IDEAL
    if (w, h) != (ideal_w, ideal_h):
        f.info("ebook_cover.not_ideal", f"{w}x{h}; KDP's ideal is {ideal_w}x{ideal_h}.", where)
    if file_mb(path) > specs.EBOOK_COVER_MAX_MB:
        f.error("ebook_cover.filesize", f"File exceeds {specs.EBOOK_COVER_MAX_MB} MB.", where)
    return f
