"""Build and validate a reflowable EPUB 3 package without external tools.

KDP accepts EPUB for Kindle eBooks (MOBI is no longer accepted). The package here
is deliberately plain: XHTML5 chapters, one stylesheet, nav.xhtml + toc.ncx,
optional cover image. `validate_epub` performs the structural checks that the
KDP uploader and epubcheck trip over most often (mimetype first and stored,
manifest/spine integrity, well-formed XHTML with no undefined entities).
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from .. import specs
from ..findings import FindingList
from ..schema import Book, StoryInterior
from ..util import file_mb
from .manuscript import Manuscript, language_code

DEFAULT_CSS = """
@charset "utf-8";
html, body { margin: 0; padding: 0; }
body { font-family: serif; line-height: 1.5; }
h1.chapter { text-align: center; margin: 3em 0 2em 0; font-weight: normal; page-break-before: always; }
h1.chapter .num { display: block; font-size: 0.8em; letter-spacing: 0.15em; text-transform: uppercase; margin-bottom: 0.6em; }
h1.chapter .title { display: block; font-size: 1.5em; }
h1.plain { text-align: center; margin: 3em 0 2em 0; font-weight: normal; font-size: 1.4em; page-break-before: always; }
p { margin: 0; text-indent: 1.4em; text-align: justify; }
p.first, h1 + p, h2 + p, hr + p, blockquote p { text-indent: 0; }
hr { border: 0; text-align: center; margin: 1.5em 0; }
hr::after { content: "* * *"; letter-spacing: 0.5em; }
blockquote { margin: 1em 2em; font-style: italic; }
.titlepage { text-align: center; margin-top: 30%; }
.titlepage .book-title { font-size: 2em; margin-bottom: 0.3em; }
.titlepage .subtitle { font-size: 1.1em; font-style: italic; margin-bottom: 2em; }
.titlepage .author { font-size: 1.2em; }
.copyright { font-size: 0.85em; text-align: left; margin-top: 40%; }
.copyright p { text-indent: 0; margin-bottom: 0.8em; }
.dedication, .epigraph { text-align: center; margin-top: 35%; font-style: italic; }
.dedication p, .epigraph p { text-indent: 0; }
.epigraph .source { font-style: normal; margin-top: 1em; }
.backmatter p { text-indent: 0; margin-bottom: 0.8em; }
nav#toc ol { list-style: none; padding-left: 0; }
nav#toc li { margin: 0.4em 0; }
"""


def _xhtml(title: str, body: str, lang: str, body_class: str = "", epub_type: str | None = None) -> str:
    cls = f' class="{body_class}"' if body_class else ""
    et = f' epub:type="{epub_type}"' if epub_type else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">\n'
        f'<head>\n<meta charset="utf-8"/>\n<title>{escape(title)}</title>\n'
        '<link rel="stylesheet" type="text/css" href="../css/style.css"/>\n</head>\n'
        f"<body{cls}{et}>\n{body}\n</body>\n</html>\n"
    )


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _chapter_body(book: Book, number: int, title: str, html: str) -> str:
    interior = book.interior
    assert isinstance(interior, StoryInterior)
    if interior.numbered_chapters and interior.chapter_label:
        heading = f'<h1 class="chapter"><span class="num">{escape(interior.chapter_label)} {number}</span><span class="title">{escape(title)}</span></h1>'
    else:
        heading = f'<h1 class="plain">{escape(title)}</h1>'
    html = re.sub(r"^<p>", '<p class="first">', html, count=1)
    return f'<section epub:type="chapter">\n{heading}\n{html}\n</section>'


def build_epub(book: Book, ms: Manuscript, out_path: Path, cover_jpg: Path | None = None) -> Path:
    interior = book.interior
    assert isinstance(interior, StoryInterior)
    md = book.metadata
    lang = language_code(md.language)
    uid = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'kdp-studio:' + book.id)}"
    year = dt.date.today().year
    modified = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    docs: list[tuple[str, str, str, bool]] = []  # (id, href, xhtml, in_toc)
    toc: list[tuple[str, str]] = []

    include_cover = bool(cover_jpg and Path(cover_jpg).is_file() and interior.epub.include_cover)
    if include_cover:
        docs.append(("cover", "text/cover.xhtml", _xhtml("Cover", '<div class="cover"><img src="../images/cover.jpg" alt="Cover"/></div>', lang, epub_type="cover"), False))

    if "title" in interior.front_matter:
        sub = f'<p class="subtitle">{escape(md.subtitle)}</p>' if md.subtitle else ""
        body = f'<div class="titlepage"><p class="book-title">{escape(md.title)}</p>{sub}<p class="author">{escape(md.author)}</p></div>'
        docs.append(("titlepage", "text/title.xhtml", _xhtml(md.title, body, lang, epub_type="titlepage"), False))
    if "copyright" in interior.front_matter:
        notice = interior.copyright_notice or (
            "All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form "
            "or by any means without the prior written permission of the author, except for brief quotations in reviews."
        )
        body = (
            f'<div class="copyright"><p>{escape(md.full_title)}</p><p>Copyright © {year} {escape(md.author)}</p>'
            f"<p>{escape(notice)}</p><p>This is a work of fiction. Names, characters, places and incidents are products of the author’s imagination or are used fictitiously.</p></div>"
        )
        docs.append(("copyright", "text/copyright.xhtml", _xhtml("Copyright", body, lang, epub_type="copyright-page"), False))
    if "dedication" in interior.front_matter and ms.extras.get("dedication"):
        docs.append(("dedication", "text/dedication.xhtml", _xhtml("Dedication", f'<div class="dedication">{ms.extras["dedication"]}</div>', lang, epub_type="dedication"), False))
    if "epigraph" in interior.front_matter and ms.extras.get("epigraph"):
        src = f'<p class="source">— {escape(interior.epigraph_source)}</p>' if interior.epigraph_source else ""
        docs.append(("epigraph", "text/epigraph.xhtml", _xhtml("Epigraph", f'<div class="epigraph">{ms.extras["epigraph"]}{src}</div>', lang, epub_type="epigraph"), False))

    for ch in ms.chapters:
        href = f"text/chapter-{ch.number:02d}.xhtml"
        label = f"{interior.chapter_label} {ch.number}: {ch.title}" if interior.numbered_chapters and interior.chapter_label else ch.title
        docs.append((f"chapter-{ch.number:02d}", href, _xhtml(label, _chapter_body(book, ch.number, ch.title, ch.html), lang, epub_type="bodymatter"), True))
        toc.append((label, href))

    back_titles = {"about_author": "About the Author", "also_by": f"Also by {md.author}", "review_cta": "A Note from the Author"}
    for kind in interior.back_matter:
        html = ms.extras.get(kind)
        if not html:
            continue
        href = f"text/{kind.replace('_', '-')}.xhtml"
        title = back_titles[kind]
        docs.append((kind, href, _xhtml(title, f'<section class="backmatter" epub:type="backmatter"><h1 class="plain">{escape(title)}</h1>{html}</section>', lang), True))
        toc.append((title, href))

    nav_items = "\n".join(f'<li><a href="{href}">{escape(label)}</a></li>' for label, href in toc)
    landmarks = '<li><a epub:type="bodymatter" href="text/chapter-01.xhtml">Start of Content</a></li>'
    if include_cover:
        landmarks = '<li><a epub:type="cover" href="text/cover.xhtml">Cover</a></li>\n' + landmarks
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">\n'
        f'<head><meta charset="utf-8"/><title>Contents</title><link rel="stylesheet" type="text/css" href="css/style.css"/></head>\n'
        f'<body>\n<nav epub:type="toc" id="toc"><h1>Contents</h1>\n<ol>\n{nav_items}\n</ol>\n</nav>\n'
        f'<nav epub:type="landmarks" hidden="hidden"><h1>Landmarks</h1><ol>\n{landmarks}\n</ol></nav>\n</body>\n</html>\n'
    )

    nav_points = "\n".join(
        f'<navPoint id="np-{i}" playOrder="{i}"><navLabel><text>{escape(label)}</text></navLabel><content src="{href}"/></navPoint>'
        for i, (label, href) in enumerate(toc, start=1)
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'<head><meta name="dtb:uid" content="{uid}"/><meta name="dtb:depth" content="1"/><meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>\n'
        f"<docTitle><text>{escape(md.title)}</text></docTitle>\n<navMap>\n{nav_points}\n</navMap>\n</ncx>\n"
    )

    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>', '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', '<item id="css" href="css/style.css" media-type="text/css"/>']
    if include_cover:
        manifest.append('<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>')
    manifest += [f'<item id="{i}" href="{href}" media-type="application/xhtml+xml"/>' for i, href, _, _ in docs]
    spine_refs = []
    for i, _, _, _ in docs:
        linear = ' linear="no"' if i == "cover" else ""
        spine_refs.append(f'<itemref idref="{i}"{linear}/>')
    spine = "\n".join(spine_refs)
    publisher = interior.epub.publisher or ("Independently published" if book.print_.isbn in ("kdp_free", "none") else md.author)
    description = _strip_tags(md.description_html)
    cover_meta = '<meta name="cover" content="cover-image"/>' if include_cover else ""
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang="{lang}">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'<dc:identifier id="pub-id">{uid}</dc:identifier>\n<dc:title>{escape(md.title)}</dc:title>\n'
        f'<dc:creator id="creator">{escape(md.author)}</dc:creator>\n<meta refines="#creator" property="role" scheme="marc:relators">aut</meta>\n'
        f"<dc:language>{lang}</dc:language>\n<dc:publisher>{escape(publisher)}</dc:publisher>\n<dc:description>{escape(description)}</dc:description>\n"
        f'<dc:date>{year}</dc:date>\n<meta property="dcterms:modified">{modified}</meta>\n{cover_meta}\n</metadata>\n'
        f"<manifest>\n{chr(10).join(manifest)}\n</manifest>\n<spine toc=\"ncx\">\n{spine}\n</spine>\n</package>\n"
    )

    css = DEFAULT_CSS
    if interior.epub.css:
        css = book.resolve(interior.epub.css).read_text(encoding="utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0" encoding="utf-8"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>\n</container>\n', zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/css/style.css", css, zipfile.ZIP_DEFLATED)
        if include_cover:
            z.write(str(cover_jpg), "OEBPS/images/cover.jpg", zipfile.ZIP_DEFLATED)
        for _, href, xhtml, _ in docs:
            z.writestr(f"OEBPS/{href}", xhtml, zipfile.ZIP_DEFLATED)
    return out_path


# --------------------------------------------------------------------------- validation
NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
EPUB_MAX_MB = specs.MAX_FILE_MB
XHTML_SOFT_LIMIT_KB = 300


def validate_epub(path: Path) -> FindingList:
    f = FindingList()
    where = path.name
    if not path.is_file():
        f.error("epub.missing", f"EPUB not found: {path}", where)
        return f
    if file_mb(path) > EPUB_MAX_MB:
        f.error("epub.filesize", f"{file_mb(path):.0f} MB exceeds KDP's {EPUB_MAX_MB} MB limit.", where)
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        f.error("epub.zip", "File is not a valid ZIP container.", where)
        return f
    with z:
        names = z.namelist()
        if not names or names[0] != "mimetype":
            f.error("epub.mimetype_order", "'mimetype' must be the first entry in the archive.", where)
        else:
            info = z.getinfo("mimetype")
            if info.compress_type != zipfile.ZIP_STORED:
                f.error("epub.mimetype_stored", "'mimetype' must be stored uncompressed.", where)
            if z.read("mimetype") != b"application/epub+zip":
                f.error("epub.mimetype_value", "'mimetype' content must be exactly 'application/epub+zip'.", where)
        if "META-INF/container.xml" not in names:
            f.error("epub.container", "META-INF/container.xml is missing.", where)
            return f
        try:
            container = ET.fromstring(z.read("META-INF/container.xml"))
        except ET.ParseError as exc:
            f.error("epub.container_xml", f"container.xml is not well-formed: {exc}", where)
            return f
        rootfile = container.find(".//c:rootfile", NS)
        opf_path = rootfile.get("full-path") if rootfile is not None else None
        if not opf_path or opf_path not in names:
            f.error("epub.opf_missing", f"OPF package file not found ({opf_path}).", where)
            return f
        try:
            opf = ET.fromstring(z.read(opf_path))
        except ET.ParseError as exc:
            f.error("epub.opf_xml", f"OPF is not well-formed: {exc}", where)
            return f
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        for tag, code in (("title", "epub.dc_title"), ("identifier", "epub.dc_identifier"), ("language", "epub.dc_language"), ("creator", "epub.dc_creator")):
            el = opf.find(f"opf:metadata/dc:{tag}", NS)
            if el is None or not (el.text or "").strip():
                (f.error if tag != "creator" else f.warning)(code, f"OPF metadata is missing dc:{tag}.", where)
        if opf.find("opf:metadata/opf:meta[@property='dcterms:modified']", NS) is None:
            f.warning("epub.modified", "OPF lacks <meta property='dcterms:modified'> (required by EPUB 3).", where)
        items = {it.get("id"): it for it in opf.findall("opf:manifest/opf:item", NS)}
        if not any("nav" in (it.get("properties") or "").split() for it in items.values()):
            f.error("epub.nav_missing", "No manifest item with properties='nav' (EPUB 3 navigation document).", where)
        for it in items.values():
            href = base + (it.get("href") or "")
            if href not in names:
                f.error("epub.manifest_href", f"Manifest item '{it.get('id')}' points to missing file {href}.", where)
                continue
            data = z.read(href)
            mt = it.get("media-type") or ""
            if mt == "application/xhtml+xml":
                try:
                    ET.fromstring(data)
                except ET.ParseError as exc:
                    f.error("epub.xhtml", f"{href} is not well-formed XHTML (undefined entities such as &nbsp; count): {exc}", where)
                if len(data) > XHTML_SOFT_LIMIT_KB * 1024:
                    f.info("epub.xhtml_large", f"{href} is {len(data) / 1024:.0f} KB; consider splitting very long chapters.", where)
            if mt.startswith("image/") and len(data) > 5 * 1024 * 1024:
                f.warning("epub.image_large", f"{href} is {len(data) / 1024 / 1024:.1f} MB; large images inflate delivery fees.", where)
        spine = opf.findall("opf:spine/opf:itemref", NS)
        if not spine:
            f.error("epub.spine_empty", "Spine has no itemrefs.", where)
        for ref in spine:
            if ref.get("idref") not in items:
                f.error("epub.spine_idref", f"Spine idref '{ref.get('idref')}' is not in the manifest.", where)
    return f
