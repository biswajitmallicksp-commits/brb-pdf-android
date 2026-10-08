"""PDF analysis (no Qt in this file).

`analyze()` examines a PDF and returns a `DocumentReport`:
  * basic information (file, size, pages, version, dates, author, producer...),
  * a per-page table (size, orientation, text / images / OCR status, blank,
    comments, links, form fields, ruled tables),
  * the document structure (bookmarks, links, comments by type, form fields,
    attachments, digital signatures, JavaScript, encryption),
  * the fonts used (embedded or not),
  * findings: things worth knowing, e.g. scanned pages without OCR, missing fonts.

It reads one page at a time through a `with_doc(func)` callback, so the viewer
can keep drawing pages while a long analysis runs.
"""
from __future__ import annotations

import csv
import datetime as _dt
import html
import io
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymupdf as fitz

from app.pdf_annotation.annots import TYPE_LABELS

PAPER = {"A3": (842, 1191), "A4": (595, 842), "A5": (420, 595), "Letter": (612, 792), "Legal": (612, 1008),
         "Tabloid": (792, 1224), "B5": (499, 709)}
OCR_FONT_HINTS = ("glyphless", "ocr")
WIDGET_TYPES = {
    fitz.PDF_WIDGET_TYPE_BUTTON: "Button", fitz.PDF_WIDGET_TYPE_CHECKBOX: "Check box",
    fitz.PDF_WIDGET_TYPE_COMBOBOX: "Drop-down", fitz.PDF_WIDGET_TYPE_LISTBOX: "List",
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "Radio button", fitz.PDF_WIDGET_TYPE_SIGNATURE: "Signature",
    fitz.PDF_WIDGET_TYPE_TEXT: "Text field",
}


def paper_name(w: float, h: float, tol: float = 4.0) -> str:
    a, b = sorted((w, h))
    for name, (pw, ph) in PAPER.items():
        if abs(a - pw) <= tol and abs(b - ph) <= tol:
            return name
    return "Custom"


def pdf_date(value: str) -> str:
    v = (value or "").strip()
    if v.startswith("D:") and len(v) >= 10:
        d = v[2:]
        out = f"{d[6:8]}-{d[4:6]}-{d[0:4]}"
        if len(d) >= 12:
            out += f" {d[8:10]}:{d[10:12]}"
        return out
    return v or "-"


@dataclass
class PageReport:
    number: int                 # 1-based
    width_mm: float
    height_mm: float
    paper: str
    orientation: str
    rotation: int
    chars: int
    words: int
    images: int
    image_coverage: float       # 0-100 %
    status: str                 # Text / Scanned - needs OCR / Scanned with OCR text / Blank / Mixed
    blank: bool
    comments: int
    links: int
    fields: int
    tables: int | None          # None = not checked
    fonts: int

    COLUMNS = ["Page", "Size (mm)", "Paper", "Orientation", "Rotation", "Content", "Characters", "Words",
               "Images", "Image cover %", "Comments", "Links", "Form fields", "Ruled tables", "Fonts"]

    def row(self) -> list:
        return [self.number, f"{self.width_mm:.0f} x {self.height_mm:.0f}", self.paper, self.orientation,
                self.rotation, self.status, self.chars, self.words, self.images, round(self.image_coverage),
                self.comments, self.links, self.fields, "-" if self.tables is None else self.tables, self.fonts]


@dataclass
class FontInfo:
    name: str
    type: str
    embedded: bool
    subset: bool
    encoding: str
    pages: list[int] = field(default_factory=list)


@dataclass
class DocumentReport:
    path: str
    basic: list[tuple[str, str]] = field(default_factory=list)
    pages: list[PageReport] = field(default_factory=list)
    bookmarks: list[tuple[int, str, int]] = field(default_factory=list)
    comments: Counter = field(default_factory=Counter)
    links: int = 0
    link_targets: Counter = field(default_factory=Counter)
    form_fields: list[tuple[int, str, str, str]] = field(default_factory=list)   # page, name, type, value
    signatures: list[dict] = field(default_factory=list)
    attachments: list[tuple[str, int]] = field(default_factory=list)              # name, size
    fonts: list[FontInfo] = field(default_factory=list)
    javascript: bool = False
    open_action: bool = False
    findings: list[tuple[str, str]] = field(default_factory=list)                 # level, text
    cancelled: bool = False

    # ------------------------------------------------------------- summaries
    def count(self, status: str) -> int:
        return sum(1 for p in self.pages if p.status == status)

    def pages_with(self, status: str) -> list[int]:
        return [p.number for p in self.pages if p.status == status]

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(PageReport.COLUMNS)
        for p in self.pages:
            w.writerow(p.row())
        return buf.getvalue()

    def to_text(self) -> str:
        lines = [f"PDF ANALYSIS REPORT - {Path(self.path).name}", f"Created {_dt.datetime.now():%d-%m-%Y %H:%M}", ""]
        lines.append("BASIC INFORMATION")
        lines += [f"  {k}: {v}" for k, v in self.basic]
        lines += ["", "FINDINGS"]
        lines += [f"  [{lvl}] {t}" for lvl, t in self.findings] or ["  none"]
        lines += ["", "STRUCTURE"]
        lines += [f"  {k}: {v}" for k, v in self.structure_rows()]
        if self.form_fields:
            lines += ["", "FORM FIELDS"] + [f"  p.{p}  {n}  ({t})  = {v}" for p, n, t, v in self.form_fields]
        if self.signatures:
            lines += ["", "DIGITAL SIGNATURES"] + [f"  {s['field']}: {s['state']}" for s in self.signatures]
        lines += ["", "FONTS"] + [f"  {f.name}  {f.type}  {'embedded' if f.embedded else 'NOT embedded'}"
                                  f"{' (subset)' if f.subset else ''}" for f in self.fonts]
        lines += ["", "PAGES", "  " + " | ".join(PageReport.COLUMNS)]
        lines += ["  " + " | ".join(str(c) for c in p.row()) for p in self.pages]
        return "\n".join(lines)

    def to_html(self) -> str:
        e = html.escape
        css = ("body{font-family:Segoe UI,Arial,sans-serif;font-size:10pt;margin:24px;color:#222}"
               "h1{font-size:16pt}h2{font-size:12pt;margin-top:18px;border-bottom:1px solid #ccc}"
               "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 7px;text-align:left}"
               "th{background:#f0f2f5}.warn{color:#9a5b00}.info{color:#245}")
        out = [f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>",
               f"<h1>PDF analysis - {e(Path(self.path).name)}</h1>",
               f"<p>Created {_dt.datetime.now():%d-%m-%Y %H:%M} by PDF Workbench (offline).</p>",
               "<h2>Findings</h2><ul>"]
        out += [f"<li class='{'warn' if lvl == 'Attention' else 'info'}'><b>{e(lvl)}:</b> {e(t)}</li>"
                for lvl, t in self.findings] or ["<li>No issues found.</li>"]
        out.append("</ul><h2>Basic information</h2><table>")
        out += [f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in self.basic]
        out.append("</table><h2>Structure</h2><table>")
        out += [f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in self.structure_rows()]
        out.append("</table>")
        if self.signatures:
            out.append("<h2>Digital signatures</h2><table><tr><th>Field</th><th>Page</th><th>Status</th>"
                       "<th>Signer</th><th>Date</th></tr>")
            out += [f"<tr><td>{e(s['field'])}</td><td>{s['page']}</td><td>{e(s['state'])}</td>"
                    f"<td>{e(s.get('signer', ''))}</td><td>{e(s.get('date', ''))}</td></tr>" for s in self.signatures]
            out.append("</table>")
        out.append("<h2>Fonts</h2><table><tr><th>Font</th><th>Type</th><th>Embedded</th><th>Pages</th></tr>")
        out += [f"<tr><td>{e(f.name)}</td><td>{e(f.type)}</td><td>{'Yes' + (' (subset)' if f.subset else '') if f.embedded else '<b>No</b>'}"
                f"</td><td>{e(_short_pages(f.pages))}</td></tr>" for f in self.fonts]
        out.append("</table><h2>Pages</h2><table><tr>" + "".join(f"<th>{e(c)}</th>" for c in PageReport.COLUMNS)
                   + "</tr>")
        out += ["<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in p.row()) + "</tr>" for p in self.pages]
        out.append("</table></body></html>")
        return "".join(out)

    def structure_rows(self) -> list[tuple[str, str]]:
        comments = ", ".join(f"{TYPE_LABELS.get(k, k)}: {v}" for k, v in self.comments.most_common()) or "none"
        return [
            ("Text pages", str(self.count("Text"))),
            ("Scanned pages without OCR", str(self.count("Scanned - needs OCR"))),
            ("Scanned pages with OCR text", str(self.count("Scanned with OCR text"))),
            ("Blank pages", str(self.count("Blank"))),
            ("Total images", str(sum(p.images for p in self.pages))),
            ("Ruled tables found", "not checked" if any(p.tables is None for p in self.pages)
             else str(sum(p.tables or 0 for p in self.pages))),
            ("Bookmarks", str(len(self.bookmarks))),
            ("Links", f"{self.links}" + (f" ({', '.join(f'{k}: {v}' for k, v in self.link_targets.items())})"
                                          if self.links else "")),
            ("Comments / annotations", comments),
            ("Form fields", str(len(self.form_fields))),
            ("Digital signatures", str(len(self.signatures))),
            ("Attachments / embedded files", ", ".join(f"{n} ({_size(s)})" for n, s in self.attachments) or "none"),
            ("Fonts", f"{len(self.fonts)} ({sum(1 for f in self.fonts if not f.embedded)} not embedded)"),
            ("JavaScript", "Yes" if self.javascript else "No"),
            ("Runs an action when opened", "Yes" if self.open_action else "No"),
        ]


def _size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _short_pages(pages: list[int]) -> str:
    from app.utils.pages import describe_pages
    return describe_pages([p - 1 for p in pages], limit=8)


# =================================================================== analyse
def analyze_page(page: fitz.Page, detect_tables: bool) -> PageReport:
    view = page.rect
    w, h = view.width, view.height
    words = page.get_text("words")
    chars = sum(len(wd[4]) for wd in words)
    # visible vs invisible (OCR) text
    invisible = visible = 0
    try:
        for span in page.get_texttrace():
            n = len(span.get("chars", ()))
            if span.get("type") == 3 or span.get("opacity", 1) == 0 or \
                    any(hint in (span.get("font") or "").lower() for hint in OCR_FONT_HINTS):
                invisible += n
            else:
                visible += n
    except Exception:
        visible = chars
    infos = page.get_image_info()
    area = abs(page.rect) or 1
    covered = sum(abs(fitz.Rect(i["bbox"]) & page.rect) for i in infos)
    coverage = min(100.0, covered / area * 100)
    drawings = 0
    if not words and not infos:
        try:
            drawings = len(page.get_drawings())
        except Exception:
            drawings = 0
    blank = chars == 0 and not infos and drawings == 0
    if blank:
        status = "Blank"
    elif coverage >= 20 and visible < 30:
        status = "Scanned with OCR text" if invisible >= 30 else "Scanned - needs OCR"
    elif visible >= 30 and coverage >= 60:
        status = "Mixed"
    elif chars == 0 and infos:
        status = "Images only"
    else:
        status = "Text"
    comments = links = fields = 0
    for a in page.annots() or []:
        comments += a.type[1] not in ("Link", "Widget", "Popup")
    links = len(page.get_links())
    fields = sum(1 for _ in page.widgets() or [])
    tables = None
    if detect_tables:
        try:
            tables = len(page.find_tables().tables)
        except Exception:
            tables = 0
    try:
        nfonts = len(page.get_fonts())
    except Exception:
        nfonts = 0
    return PageReport(page.number + 1, w / 72 * 25.4, h / 72 * 25.4, paper_name(w, h),
                      "Landscape" if w > h + 1 else ("Portrait" if h > w + 1 else "Square"), page.rotation,
                      chars, len(words), len(infos), coverage, status, blank, comments, links, fields, tables, nfonts)


def analyze(with_doc: Callable, path: str, file_size: int, permissions_text: str = "", encrypted: bool = False,
            detect_tables: bool = False,
            progress: Callable[[int, int], None] | None = None,
            is_cancelled: Callable[[], bool] | None = None) -> DocumentReport:
    """Analyse a document. `with_doc(func)` must call func(fitz.Document) (holding any lock)."""
    report = DocumentReport(path)
    n = with_doc(lambda d: d.page_count)

    # -------- pages (one at a time, so the viewer stays responsive)
    fonts: dict[tuple, FontInfo] = {}
    for i in range(n):
        if is_cancelled and is_cancelled():
            report.cancelled = True
            break

        def one(d, i=i):
            page = d[i]
            pr = analyze_page(page, detect_tables)
            for xref, ext, ftype, basefont, _name, enc, *_ in d.get_page_fonts(i):
                key = (xref, basefont)
                if key not in fonts:
                    subset = len(basefont) > 7 and basefont[6] == "+" and basefont[:6].isupper()
                    fonts[key] = FontInfo(basefont[7:] if subset else basefont, ftype, ext != "n/a", subset, enc)
                fonts[key].pages.append(i + 1)
            for a in page.annots() or []:
                if a.type[1] not in ("Link", "Widget", "Popup"):
                    report.comments[a.type[1]] += 1
            for link in page.get_links():
                report.links += 1
                kind = {fitz.LINK_GOTO: "inside the document", fitz.LINK_URI: "web addresses",
                        fitz.LINK_LAUNCH: "opens files/programs", fitz.LINK_GOTOR: "other PDFs",
                        fitz.LINK_NAMED: "named actions"}.get(link.get("kind"), "other")
                report.link_targets[kind] += 1
            for wdg in page.widgets() or []:
                ftype = WIDGET_TYPES.get(wdg.field_type, wdg.field_type_string)
                value = str(wdg.field_value or "")
                report.form_fields.append((i + 1, wdg.field_name or "(no name)", ftype, value[:80]))
                if wdg.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    report.signatures.append(_signature_info(d, wdg, i + 1))
            return pr
        report.pages.append(with_doc(one))
        if progress:
            progress(i + 1, n)
    report.fonts = sorted(fonts.values(), key=lambda f: (f.embedded, f.name.lower()))

    # -------- document level
    def doc_level(d):
        meta = dict(d.metadata or {})
        report.bookmarks = d.get_toc(simple=True)
        for name in d.embfile_names():
            try:
                report.attachments.append((name, int(d.embfile_info(name).get("size", 0))))
            except Exception:
                report.attachments.append((name, 0))
        cat = d.pdf_catalog()
        try:
            report.open_action = d.xref_get_key(cat, "OpenAction")[0] != "null"
            names = d.xref_get_key(cat, "Names")
            js = d.xref_get_key(cat, "Names/JavaScript")
            report.javascript = js[0] != "null" or "JavaScript" in (names[1] if names[0] == "dict" else "")
        except Exception:
            pass
        try:
            for xref in range(1, d.xref_length()):
                if report.javascript:
                    break
                t = d.xref_get_key(xref, "S")
                if t[1] == "/JavaScript":
                    report.javascript = True
        except Exception:
            pass
        return meta, d.is_repaired, d.version_count, d.is_fast_webaccess, d.is_form_pdf
    meta, repaired, versions, fast, is_form = with_doc(doc_level)

    sizes = Counter(p.paper + " " + p.orientation for p in report.pages)
    report.basic = [
        ("File name", Path(path).name),
        ("Location", str(Path(path).parent)),
        ("File size", f"{_size(file_size)}  ({file_size:,} bytes)"),
        ("Pages", str(n) + ("" if not report.cancelled else f" (analysed {len(report.pages)})")),
        ("PDF version", meta.get("format") or "-"),
        ("Page sizes", ", ".join(f"{k} x{v}" for k, v in sizes.most_common(4)) or "-"),
        ("Title", meta.get("title") or "-"),
        ("Author", meta.get("author") or "-"),
        ("Subject", meta.get("subject") or "-"),
        ("Keywords", meta.get("keywords") or "-"),
        ("Creator (made with)", meta.get("creator") or "-"),
        ("Producer (PDF made by)", meta.get("producer") or "-"),
        ("Created", pdf_date(meta.get("creationDate", ""))),
        ("Modified", pdf_date(meta.get("modDate", ""))),
        ("Encryption", meta.get("encryption") or ("Password protected" if encrypted else "None")),
        ("Permissions", permissions_text or "-"),
        ("Saved versions (incremental updates)", str(max(1, versions or 1))),
        ("Optimised for fast web view", "Yes" if fast else "No"),
        ("Interactive form", "Yes" if is_form else "No"),
    ]

    # -------- findings
    f = report.findings
    scanned = report.pages_with("Scanned - needs OCR")
    if scanned:
        f.append(("Attention", f"{len(scanned)} scanned page(s) have no searchable text (pages "
                               f"{_short_pages(scanned)}). Use OCR > Make Searchable PDF."))
    if report.count("Scanned with OCR text"):
        f.append(("Info", f"{report.count('Scanned with OCR text')} scanned page(s) already carry an OCR text layer."))
    blanks = report.pages_with("Blank")
    if blanks:
        f.append(("Info", f"{len(blanks)} blank page(s): {_short_pages(blanks)}."))
    if len(sizes) > 1:
        f.append(("Info", "Pages have different sizes or orientations: " + ", ".join(sizes)))
    missing = [ft.name for ft in report.fonts if not ft.embedded]
    if missing:
        f.append(("Attention", f"{len(missing)} font(s) are not embedded ({', '.join(missing[:5])}"
                               f"{'...' if len(missing) > 5 else ''}); text may look different on other computers."))
    if report.signatures:
        signed = sum(1 for s in report.signatures if s["signed"])
        f.append(("Info", f"{len(report.signatures)} signature field(s), {signed} signed. Signature validity is "
                          "NOT checked here (verification comes in a later phase)."))
    if report.javascript:
        f.append(("Attention", "The document contains JavaScript. PDF Workbench never runs it."))
    if report.open_action:
        f.append(("Info", "The document asks to run an action when opened (often just 'go to page 1')."))
    if report.link_targets.get("opens files/programs"):
        f.append(("Attention", "Some links try to open files or programs on the computer."))
    if report.attachments:
        f.append(("Info", f"{len(report.attachments)} attached/embedded file(s)."))
    if repaired:
        f.append(("Attention", "The file was damaged; it was repaired in memory when opened. Save a copy to keep "
                               "the repaired version."))
    if versions and versions > 1:
        f.append(("Info", f"The file was edited {versions - 1} time(s) after creation (incremental updates). "
                          "Earlier versions may still be inside the file."))
    if encrypted:
        f.append(("Info", "The document is password protected."))
    if report.cancelled:
        f.append(("Attention", "Analysis was stopped before the end."))
    return report


def _signature_info(d: fitz.Document, wdg, page_no: int) -> dict:
    info = {"field": wdg.field_name or "(no name)", "page": page_no, "signed": False,
            "state": "Empty signature field (not signed)"}
    try:
        kind, val = d.xref_get_key(wdg.xref, "V")
        if kind == "xref":
            info["signed"] = True
            vx = int(val.split()[0])
            name = d.xref_get_key(vx, "Name")
            when = d.xref_get_key(vx, "M")
            reason = d.xref_get_key(vx, "Reason")
            if name[0] == "string":
                info["signer"] = name[1]
            if when[0] == "string":
                info["date"] = pdf_date(when[1])
            if reason[0] == "string":
                info["reason"] = reason[1]
            info["state"] = "Signed - validity NOT verified"
    except Exception:
        pass
    return info


def analyze_file(path: str, password: str | None = None, detect_tables: bool = True) -> DocumentReport:
    """Convenience for tests and batch use: analyse a file on disk."""
    doc = fitz.open(path)
    if doc.needs_pass and not doc.authenticate(password or ""):
        raise RuntimeError("password required")
    try:
        return analyze(lambda f: f(doc), path, os.path.getsize(path), encrypted=bool(password),
                       detect_tables=detect_tables)
    finally:
        doc.close()
