#!/usr/bin/env python3
"""Build EPUB 3 archives for Manannán from existing Markdown chapters."""

from __future__ import annotations

import argparse
import html
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EPUB_DIR = Path(__file__).resolve().parent
CAIBIDLI_DIR = ROOT / "caibidlí"
ASSETS_DIR = ROOT / "assets"

FONTS_DIR = EPUB_DIR / "fonts"

GAELIC_FONT_FAMILIES = {
    "bunchlo": {
        "css_name": "Bunchlo GC",
        "files": [
            ("bungc.otf", "normal", "normal", "font/otf"),
            ("bunigc.otf", "italic", "normal", "font/otf"),
            ("buntgc.otf", "normal", "bold", "font/otf"),
        ],
    },
    "lanchlo": {
        "css_name": "Lanchlo GC",
        "files": [
            ("langc.otf", "normal", "normal", "font/otf"),
            ("lanigc.otf", "italic", "normal", "font/otf"),
            ("lantgc.otf", "normal", "bold", "font/otf"),
        ],
    },
}

EDITIONS = {
    "old": {
        "src_dir": CAIBIDLI_DIR / "old-orthography",
        "out_file": EPUB_DIR / "Manannán-old.epub",
        "title": "Manannán (Seanlitriú)",
        "author": "Máiréad Ní Ġráda",
        "embed_gaelic_font": True,
    },
    "new": {
        "src_dir": CAIBIDLI_DIR / "new-orthography",
        "out_file": EPUB_DIR / "Manannán-new.epub",
        "title": "Manannán (Litriú Nua)",
        "author": "Máiréad Ní Ghráda",
        "embed_gaelic_font": False,
    },
}

REF_DEF_RE = re.compile(r"^\[[^\]]+\]:\s*\S+.*$")
HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$")
HR_RE = re.compile(r"^(?:[-*_]\s*){3,}$")
TABLE_ROW_RE = re.compile(r"^\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
EM_RE = re.compile(r"\*([^*\n]+)\*")
CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
WORD_CHAR_CLASS = r"A-Za-záéíóúÁÉÍÓÚḃċḋḟġṁṗṡṫḂĊḊḞĠṀṖṠṪ"
LINEWRAP_HYPHEN_RE = re.compile(rf"[{WORD_CHAR_CLASS}]-$")
TERMINAL_PUNCT_RE = re.compile(r'[.!?…”"]$')
# Matches Bungló/Lánchló OpenType `ss01` targets for readers (e.g. Kindle KFX) that strip font-feature-settings.
INSULAR_RS_TRANS = str.maketrans({"r": "\u027c", "s": "\u017f", "ṡ": "\u1e9b"})


@dataclass
class BuildReport:
    edition: str
    chapters: int = 0
    insular_rs: bool = False
    embedded_fonts: list[str] = field(default_factory=list)
    control_chars_stripped: int = 0
    empty_headings: list[tuple[str, int]] = field(default_factory=list)
    unmatched_asterisks: list[tuple[str, int, str]] = field(default_factory=list)
    mid_sentence_page_splits: list[tuple[str, int, str]] = field(default_factory=list)
    merged_page_breaks: int = 0
    stray_trailing_hyphens: list[tuple[str, int, str]] = field(default_factory=list)
    linewrap_hyphens: list[tuple[str, int, str]] = field(default_factory=list)
    mid_word_capitals: list[tuple[str, int, str]] = field(default_factory=list)


def render_inline(text: str, filename: str, line_no: int, report: BuildReport) -> str:
    """Strip XML control chars, escape XHTML, and convert paired *emphasis* spans."""
    text, n_ctrl = CTRL_CHAR_RE.subn("", text)
    report.control_chars_stripped += n_ctrl
    if report.insular_rs:
        text = text.translate(INSULAR_RS_TRANS)
    parts: list[str] = []
    pos = 0
    for m in EM_RE.finditer(text):
        before = text[pos : m.start()]
        if "*" in before:
            report.unmatched_asterisks.append((filename, line_no, text.strip()))
        parts.append(html.escape(before, quote=False))
        parts.append(f"<em>{html.escape(m.group(1), quote=False)}</em>")
        pos = m.end()
    tail = text[pos:]
    if "*" in tail:
        report.unmatched_asterisks.append((filename, line_no, text.strip()))
    parts.append(html.escape(tail, quote=False))
    return "".join(parts)


def parse_table(lines: list[str], start: int, filename: str, report: BuildReport) -> tuple[str, int]:
    """Convert a Markdown pipe table starting at `start` into XHTML."""
    rows: list[list[str]] = []
    idx = start
    while idx < len(lines) and TABLE_ROW_RE.match(lines[idx].strip()):
        cells = [c.strip() for c in lines[idx].strip().strip("|").split("|")]
        rows.append(cells)
        idx += 1

    alignments: list[str] = []
    has_header = len(rows) >= 2 and TABLE_SEP_RE.match(lines[start + 1].strip())
    if has_header:
        sep_cells = [c.strip() for c in lines[start + 1].strip().strip("|").split("|")]
        for sep in sep_cells:
            if sep.startswith(":") and sep.endswith(":"):
                alignments.append("center")
            elif sep.endswith(":"):
                alignments.append("right")
            else:
                alignments.append("left")

    out = ['<table>']
    if has_header:
        out.append("<thead><tr>")
        for col_i, cell in enumerate(rows[0]):
            align = alignments[col_i] if col_i < len(alignments) else "left"
            content = render_inline(cell, filename, start + 1, report)
            out.append(f'<th style="text-align:{align}">{content}</th>')
        out.append("</tr></thead>")
        body_rows = rows[2:]
        body_line_offset = 2
    else:
        body_rows = rows
        body_line_offset = 0

    out.append("<tbody>")
    for r_i, row in enumerate(body_rows):
        out.append("<tr>")
        for col_i, cell in enumerate(row):
            align = alignments[col_i] if col_i < len(alignments) else "left"
            content = render_inline(cell, filename, start + body_line_offset + r_i + 1, report)
            out.append(f'<td style="text-align:{align}">{content}</td>')
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out), idx


def audit_source(lines: list[str], filename: str, report: BuildReport) -> None:
    """Scan raw Markdown lines for formatting/OCR issues affecting EPUB quality."""
    for idx, raw in enumerate(lines):
        line_no = idx + 1
        stripped = raw.strip()
        if not TABLE_SEP_RE.match(stripped) and re.search(r"\S-\s", raw):
            report.stray_trailing_hyphens.append((filename, line_no, stripped))
        if LINEWRAP_HYPHEN_RE.search(stripped):
            report.linewrap_hyphens.append((filename, line_no, stripped))
        if re.search(r"[a-záéíóúḃċḋḟġṁṗṡṫ][A-ZḂĊḊḞĠṀṖṠṪ]", raw):
            report.mid_word_capitals.append((filename, line_no, stripped))


def markdown_to_xhtml_body(md_text: str, filename: str, report: BuildReport) -> tuple[str, str]:
    """Convert chapter Markdown as-is into an XHTML body and extract first title."""
    lines = md_text.splitlines()
    audit_source(lines, filename, report)

    blocks: list[str] = []
    first_heading = ""
    i = 0
    para_lines: list[tuple[int, str]] = []

    def flush_para() -> None:
        if not para_lines:
            return
        parts: list[str] = []
        for idx_p, (ln, text) in enumerate(para_lines):
            chunk = render_inline(text, filename, ln, report)
            if idx_p == 0 or LINEWRAP_HYPHEN_RE.search(para_lines[idx_p - 1][1]):
                parts.append(chunk)
            else:
                parts.append(" " + chunk)
        blocks.append(f"<p>{''.join(parts)}</p>")
        para_lines.clear()

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if not stripped or REF_DEF_RE.match(stripped):
            j = i
            ref_line_no = 0
            while j < len(lines):
                cand = lines[j].strip()
                if not cand:
                    j += 1
                elif REF_DEF_RE.match(cand):
                    if not ref_line_no:
                        ref_line_no = j + 1
                    j += 1
                else:
                    break
            if ref_line_no and para_lines and j < len(lines):
                next_s = lines[j].strip()
                is_block_next = bool(
                    HEADING_RE.match(next_s)
                    or HR_RE.match(next_s)
                    or TABLE_ROW_RE.match(next_s)
                )
                if not is_block_next and not TERMINAL_PUNCT_RE.search(para_lines[-1][1]):
                    report.merged_page_breaks += 1
                    i = j
                    continue
                if not TERMINAL_PUNCT_RE.search(para_lines[-1][1]):
                    report.mid_sentence_page_splits.append(
                        (filename, ref_line_no, para_lines[-1][1][-40:])
                    )
            flush_para()
            i = j
            continue

        hm = HEADING_RE.match(stripped)
        if hm:
            flush_para()
            level = len(hm.group(1))
            title_text = hm.group(2).strip()
            if not title_text:
                report.empty_headings.append((filename, i + 1))
                blocks.append(f"<h{level}>&#160;</h{level}>")
            else:
                if not first_heading:
                    first_heading = title_text
                rendered_h = render_inline(title_text, filename, i + 1, report)
                blocks.append(f"<h{level}>{rendered_h}</h{level}>")
            i += 1
            continue

        if HR_RE.match(stripped):
            flush_para()
            blocks.append("<hr/>")
            i += 1
            continue

        if TABLE_ROW_RE.match(stripped):
            flush_para()
            table_html, i = parse_table(lines, i, filename, report)
            blocks.append(table_html)
            continue

        para_lines.append((i + 1, stripped))
        i += 1

    flush_para()
    return "\n".join(blocks), first_heading or Path(filename).stem


def wrap_xhtml(title: str, body_html: str, css_href: str = "epub.css") -> str:
    escaped_title = html.escape(title, quote=False)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ga" lang="ga">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        f"  <title>{escaped_title}</title>\n"
        f'  <link rel="stylesheet" type="text/css" href="{css_href}"/>\n'
        "</head>\n"
        "<body>\n"
        f"{body_html}\n"
        "</body>\n"
        "</html>\n"
    )


def build_edition(
    edition_key: str,
    gaelic_font: str = "bunchlo",
    insular_rs: bool = False,
    out_override: Path | None = None,
) -> BuildReport:
    cfg = EDITIONS[edition_key]
    src_dir: Path = cfg["src_dir"]
    out_file: Path = out_override or cfg["out_file"]
    title: str = cfg["title"]
    author: str = cfg["author"]

    chapter_files = sorted(src_dir.glob("manannan[0-9][0-9].md"))
    if not chapter_files:
        raise FileNotFoundError(f"No chapter files found in {src_dir}")

    report = BuildReport(
        edition=edition_key,
        chapters=len(chapter_files),
        insular_rs=bool(insular_rs and cfg.get("embed_gaelic_font")),
    )
    book_uuid = str(uuid.uuid4())
    modified_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    chapter_entries: list[tuple[str, str, str]] = []
    for idx, ch_path in enumerate(chapter_files):
        body_html, ch_title = markdown_to_xhtml_body(
            ch_path.read_text(encoding="utf-8"), ch_path.name, report
        )
        if idx == 0 and ch_title == "MANANNÁN":
            ch_title = "Clár & Tús"
        href = f"ch{idx:02d}.xhtml"
        xhtml = wrap_xhtml(ch_title, body_html)
        chapter_entries.append((href, ch_title, xhtml))

    cover_jpg = ASSETS_DIR / "manannan.jpg"
    has_cover = cover_jpg.is_file()
    css_path = EPUB_DIR / "epub.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""

    font_entries: list[tuple[str, str, Path]] = []
    if cfg.get("embed_gaelic_font"):
        font_cfg = GAELIC_FONT_FAMILIES[gaelic_font]
        css_font_name = font_cfg["css_name"]
        font_face_blocks: list[str] = []
        for idx, (fname, fstyle, fweight, mime) in enumerate(font_cfg["files"]):
            fpath = FONTS_DIR / fname
            if fpath.is_file():
                font_entries.append((f"font-{idx}", mime, fpath))
                report.embedded_fonts.append(fname)
                font_face_blocks.append(
                    "@font-face {\n"
                    f'  font-family: "{css_font_name}";\n'
                    f'  src: url("fonts/{fname}") format("opentype");\n'
                    f"  font-style: {fstyle};\n"
                    f"  font-weight: {fweight};\n"
                    '  font-feature-settings: "ss01" 1;\n'
                    "}"
                )
        if font_face_blocks:
            css_text = (
                "\n".join(font_face_blocks)
                + "\n\n"
                + css_text
                + (
                    "\nhtml, body, p, h1, h2, h3, td, th {\n"
                    f'  font-family: "{css_font_name}", serif;\n'
                    '  font-feature-settings: "ss01" 1;\n'
                    '  -webkit-font-feature-settings: "ss01" 1;\n'
                    "}\n"
                )
            )

    def fmt_nav_label(label: str) -> str:
        if report.insular_rs:
            label = label.translate(INSULAR_RS_TRANS)
        return html.escape(label, quote=False)

    nav_items = "\n".join(
        f'        <li><a href="{href}">{fmt_nav_label(ch_title)}</a></li>'
        for href, ch_title, _ in chapter_entries
    )
    nav_body = (
        '  <nav epub:type="toc" id="toc">\n'
        f"    <h1>{fmt_nav_label(title)}</h1>\n"
        "    <ol>\n"
        f"{nav_items}\n"
        "    </ol>\n"
        "  </nav>"
    )
    nav_xhtml = wrap_xhtml("Clár an Leabhair", nav_body)

    ncx_points = []
    play_order = 1
    if has_cover:
        ncx_points.append(
            f'    <navPoint id="navPoint-{play_order}" playOrder="{play_order}">\n'
            f'      <navLabel><text>Clúdach</text></navLabel>\n'
            f'      <content src="cover.xhtml"/>\n'
            f"    </navPoint>"
        )
        play_order += 1
    for href, ch_title, _ in chapter_entries:
        ncx_points.append(
            f'    <navPoint id="navPoint-{play_order}" playOrder="{play_order}">\n'
            f"      <navLabel><text>{html.escape(ch_title, quote=False)}</text></navLabel>\n"
            f'      <content src="{href}"/>\n'
            f"    </navPoint>"
        )
        play_order += 1

    toc_ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "  <head>\n"
        f'    <meta name="dtb:uid" content="urn:uuid:{book_uuid}"/>\n'
        '    <meta name="dtb:depth" content="1"/>\n'
        '    <meta name="dtb:totalPageCount" content="0"/>\n'
        '    <meta name="dtb:maxPageNumber" content="0"/>\n'
        "  </head>\n"
        f"  <docTitle><text>{html.escape(title, quote=False)}</text></docTitle>\n"
        "  <navMap>\n"
        + "\n".join(ncx_points)
        + "\n  </navMap>\n</ncx>\n"
    )

    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="epub.css" media-type="text/css"/>',
    ]
    spine_items = []
    if has_cover:
        manifest_items.append(
            '<item id="cover-image" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>'
        )
        manifest_items.append(
            '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_items.append('<itemref idref="cover"/>')

    for font_id, mime, fpath in font_entries:
        manifest_items.append(
            f'<item id="{font_id}" href="fonts/{fpath.name}" media-type="{mime}"/>'
        )
    for idx, (href, _, _) in enumerate(chapter_entries):
        item_id = f"ch{idx:02d}"
        manifest_items.append(f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="{item_id}"/>')

    cover_meta = '    <meta name="cover" content="cover-image"/>\n' if has_cover else ""
    content_opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="bookid">urn:uuid:{book_uuid}</dc:identifier>\n'
        f"    <dc:title>{html.escape(title, quote=False)}</dc:title>\n"
        f"    <dc:creator>{html.escape(author, quote=False)}</dc:creator>\n"
        "    <dc:language>ga</dc:language>\n"
        f'    <meta property="dcterms:modified">{modified_iso}</meta>\n'
        f"{cover_meta}"
        "  </metadata>\n"
        "  <manifest>\n    "
        + "\n    ".join(manifest_items)
        + "\n  </manifest>\n"
        '  <spine toc="ncx">\n    '
        + "\n    ".join(spine_items)
        + "\n  </spine>\n"
        "</package>\n"
    )

    container_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_file, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_DEFLATED)
        if font_entries:
            ibooks_opts = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<display_options>\n"
                '  <platform name="*">\n'
                '    <option name="specified-fonts">true</option>\n'
                "  </platform>\n"
                "</display_options>\n"
            )
            zf.writestr(
                "META-INF/com.apple.ibooks.display-options.xml",
                ibooks_opts,
                compress_type=zipfile.ZIP_DEFLATED,
            )
        zf.writestr("OEBPS/content.opf", content_opf, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/toc.ncx", toc_ncx, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/epub.css", css_text, compress_type=zipfile.ZIP_DEFLATED)
        for _, _, fpath in font_entries:
            zf.writestr(f"OEBPS/fonts/{fpath.name}", fpath.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        if has_cover:
            zf.writestr("OEBPS/cover.jpg", cover_jpg.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
            cover_body = '<div style="text-align:center"><img src="cover.jpg" alt="Manannán" style="max-width:100%;height:auto"/></div>'
            zf.writestr("OEBPS/cover.xhtml", wrap_xhtml("Clúdach", cover_body), compress_type=zipfile.ZIP_DEFLATED)
        for href, _, xhtml in chapter_entries:
            zf.writestr(f"OEBPS/{href}", xhtml, compress_type=zipfile.ZIP_DEFLATED)

    return report


def print_report(r: BuildReport, out_file: Path | None = None) -> None:
    target = out_file or EDITIONS[r.edition]["out_file"]
    size_kb = target.stat().st_size / 1024
    fonts_label = ", ".join(r.embedded_fonts) if r.embedded_fonts else "none (system serif)"
    mode = " [insular r/s baked]" if r.insular_rs else ""
    print(f"Built {target} ({size_kb:.1f} KB, {r.chapters} chapters, fonts: {fonts_label}{mode})")
    print(f"  - Control chars stripped (U+0090 etc.): {r.control_chars_stripped}")
    print(f"  - Empty headings (#): {len(r.empty_headings)}")
    print(f"  - Unmatched '*' in prose: {len(r.unmatched_asterisks)}")
    print(
        f"  - Mid-sentence page-marker paragraph splits: {len(r.mid_sentence_page_splits)}"
        f" (merged cleanly: {r.merged_page_breaks})"
    )
    print(f"  - Stray trailing hyphens (word- ): {len(r.stray_trailing_hyphens)}")
    print(f"  - Line-wrap hyphens (word-\\n): {len(r.linewrap_hyphens)}")
    print(f"  - Mid-word capitals (OCR): {len(r.mid_word_capitals)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--edition",
        choices=["old", "new", "both"],
        default="both",
        help="Which orthography edition(s) to build (default: both)",
    )
    ap.add_argument(
        "--gaelic-font",
        choices=sorted(GAELIC_FONT_FAMILIES),
        default="bunchlo",
        help="Cló Gaelach font family to embed in the old edition (default: bunchlo)",
    )
    ap.add_argument(
        "--insular-rs",
        action="store_true",
        help="Bake U+027C/U+017F/U+1E9B insular r/s/ṡ glyphs into old-edition XHTML for readers (e.g. Kindle KFX) that ignore OpenType ss01",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output path override (valid only when building a single edition)",
    )
    args = ap.parse_args()

    targets = ["old", "new"] if args.edition == "both" else [args.edition]
    if args.out and len(targets) != 1:
        ap.error("--out requires a single --edition target")
    for key in targets:
        report = build_edition(
            key,
            gaelic_font=args.gaelic_font,
            insular_rs=args.insular_rs,
            out_override=args.out,
        )
        print_report(report, out_file=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
