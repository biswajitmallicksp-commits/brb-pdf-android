"""Annotations and redaction (no Qt in this file).

Annotations are the standard PDF "comment" objects (highlight, note, shapes,
pen, stamps, text boxes). They stay editable: any PDF reader can show, move,
change or delete them later. All coordinates are UNROTATED page space.

Redaction is different: marked areas are permanently removed from the page
when redactions are APPLIED (text, image pixels and drawings underneath), and
replaced by a filled box. Drawing a black rectangle is NOT redaction - the
text would still be underneath; this module never pretends otherwise.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

import pymupdf as fitz

from app.pdf_editor.content import _rgb
from app.pdf_pages.operations import PageOpError

AUTHOR = "PDF Workbench user"

MARKUP_TYPES = {"Highlight", "Underline", "StrikeOut", "Squiggly"}
VERTEX_TYPES = {"Line", "Ink", "Polygon", "PolyLine"}
RESIZABLE_TYPES = {"Square", "Circle", "FreeText", "Stamp", "FileAttachment"}

TYPE_LABELS = {
    "Highlight": "Highlight", "Underline": "Underline", "StrikeOut": "Strikethrough", "Squiggly": "Squiggly",
    "Text": "Sticky note", "FreeText": "Text box", "Square": "Rectangle", "Circle": "Ellipse",
    "Line": "Line / arrow", "Ink": "Pen drawing", "Polygon": "Polygon", "PolyLine": "Polyline",
    "Stamp": "Stamp", "Redact": "Redaction mark (not yet applied)", "Link": "Link", "Widget": "Form field",
    "Caret": "Caret", "FileAttachment": "Attachment", "Popup": "Popup",
}

STANDARD_STAMPS = ["Approved", "AsIs", "Confidential", "Departmental", "Experimental", "Expired", "Final",
                   "ForComment", "ForPublicRelease", "NotApproved", "NotForPublicRelease", "Sold",
                   "TopSecret", "Draft"]
OFFICE_STAMPS = ["PAID", "RECEIVED", "VERIFIED", "ORIGINAL SEEN", "APPROVED", "REJECTED", "COPY",
                 "CONFIDENTIAL", "DRAFT"]


@dataclass
class AnnotStyle:
    stroke: tuple = (0.85, 0.1, 0.1)        # outline / text-markup colour (0-1 floats)
    fill: tuple | None = None               # fill colour, None = transparent
    width: float = 1.5                      # line width in points
    opacity: float = 1.0
    fontsize: float = 11.0
    text_color: tuple = (0, 0, 0)


@dataclass
class AnnotInfo:
    xref: int
    page: int
    kind: str                     # PDF subtype, e.g. 'Square'
    rect: fitz.Rect               # unrotated page space
    contents: str = ""
    stroke: tuple | None = None
    fill: tuple | None = None
    width: float = 1.0
    opacity: float = 1.0
    fontsize: float = 11.0
    text_color: tuple | None = None
    author: str = ""
    modified: str = ""
    vertices: list = field(default_factory=list)
    subject: str = ""

    @property
    def label(self) -> str:
        if self.kind == "FreeText" and self.subject == "Stamp":
            return "Stamp"
        return TYPE_LABELS.get(self.kind, self.kind)

    @property
    def movable(self) -> bool:
        return self.kind not in MARKUP_TYPES | {"Widget", "Link", "Popup"}

    @property
    def resizable(self) -> bool:
        return self.kind in RESIZABLE_TYPES

    @property
    def has_text(self) -> bool:
        return self.kind in ("Text", "FreeText")


def _finish(annot: fitz.Annot, style: AnnotStyle | None = None, contents: str | None = None) -> int:
    info = {"title": AUTHOR, "modDate": fitz.get_pdf_now()}
    if contents is not None:
        info["content"] = contents
    annot.set_info(**info)
    if style is not None and style.opacity < 1:
        annot.set_opacity(style.opacity)
    annot.update()
    return annot.xref


def _get(page: fitz.Page, xref: int) -> fitz.Annot:
    annot = page.load_annot(xref)
    if annot is None:
        raise PageOpError("That annotation no longer exists.")
    return annot


# ================================================================ create
def add_text_markup(page: fitz.Page, kind: str, word_rects: list[fitz.Rect], style: AnnotStyle) -> int:
    """Highlight / Underline / StrikeOut / Squiggly over the given word boxes."""
    if not word_rects:
        raise PageOpError("Select some text first: drag over the words.")
    quads = [fitz.Rect(r).quad for r in word_rects]
    maker = {"Highlight": page.add_highlight_annot, "Underline": page.add_underline_annot,
             "StrikeOut": page.add_strikeout_annot, "Squiggly": page.add_squiggly_annot}[kind]
    annot = maker(quads=quads)
    annot.set_colors(stroke=_rgb(style.stroke))
    return _finish(annot, style)


def add_note(page: fitz.Page, point: fitz.Point, text: str, style: AnnotStyle) -> int:
    annot = page.add_text_annot(point, text, icon="Comment")
    annot.set_colors(stroke=_rgb(style.stroke))
    return _finish(annot, style, text)


def add_text_box(page: fitz.Page, rect: fitz.Rect, text: str, style: AnnotStyle, callout: fitz.Point | None = None,
                 border: bool = True) -> int:
    """A typed comment in a box (English/Latin characters; for Bengali/Hindi use Edit > Add Text).
    The border is drawn in the text colour."""
    kwargs = dict(fontsize=style.fontsize, fontname="helv", text_color=_rgb(style.text_color),
                  fill_color=_rgb(style.fill) if style.fill else None, rotate=page.rotation, align=0,
                  border_width=style.width if border else 0)
    if callout is not None:
        kwargs["callout"] = [callout, fitz.Point(rect.x0, (rect.y0 + rect.y1) / 2)]
        kwargs["line_end"] = fitz.PDF_ANNOT_LE_OPEN_ARROW
    try:
        annot = page.add_freetext_annot(rect, text, **kwargs)
    except TypeError:                        # older PyMuPDF without callouts
        kwargs.pop("callout", None)
        kwargs.pop("line_end", None)
        annot = page.add_freetext_annot(rect, text, **kwargs)
    return _finish(annot, style, text)


def add_shape(page: fitz.Page, kind: str, rect: fitz.Rect, style: AnnotStyle) -> int:
    """kind: 'Square' (rectangle) or 'Circle' (ellipse)."""
    rect = fitz.Rect(rect)
    rect.normalize()
    if rect.width < 2 or rect.height < 2:
        raise PageOpError("Drag to draw the shape.")
    annot = page.add_rect_annot(rect) if kind == "Square" else page.add_circle_annot(rect)
    annot.set_colors(stroke=_rgb(style.stroke), fill=_rgb(style.fill) if style.fill else None)
    annot.set_border(width=style.width)
    return _finish(annot, style)


def add_line(page: fitz.Page, p1: fitz.Point, p2: fitz.Point, style: AnnotStyle, arrow: bool = False) -> int:
    if abs(p1 - p2) < 2:
        raise PageOpError("Drag to draw the line.")
    annot = page.add_line_annot(p1, p2)
    annot.set_colors(stroke=_rgb(style.stroke), fill=_rgb(style.stroke))
    annot.set_border(width=style.width)
    if arrow:
        annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
    return _finish(annot, style)


def add_ink(page: fitz.Page, strokes: list[list[fitz.Point]], style: AnnotStyle) -> int:
    strokes = [[(p.x, p.y) for p in s] for s in strokes if len(s) >= 2]
    if not strokes:
        raise PageOpError("Drag to draw.")
    annot = page.add_ink_annot(strokes)
    annot.set_colors(stroke=_rgb(style.stroke))
    annot.set_border(width=style.width)
    return _finish(annot, style)


def add_polygon(page: fitz.Page, points: list[fitz.Point], style: AnnotStyle) -> int:
    if len(points) < 3:
        raise PageOpError("A polygon needs at least 3 points.")
    annot = page.add_polygon_annot(points)
    annot.set_colors(stroke=_rgb(style.stroke), fill=_rgb(style.fill) if style.fill else None)
    annot.set_border(width=style.width)
    return _finish(annot, style)


def add_stamp(page: fitz.Page, rect: fitz.Rect, name: str, style: AnnotStyle, with_date: bool = True) -> int:
    """A standard PDF stamp, or an office stamp such as PAID / RECEIVED (red box with the date)."""
    if name in STANDARD_STAMPS and page.rotation % 360 == 0:
        # MuPDF's built-in stamp designs do not turn with rotated pages, so they are used on
        # upright pages only; elsewhere the office-style stamp below is used.
        annot = page.add_stamp_annot(rect, stamp=STANDARD_STAMPS.index(name))
        return _finish(annot, style)
    label = _stamp_label(name)
    text = label + (f"\n{_dt.date.today():%d-%m-%Y}" if with_date else "")
    st = AnnotStyle(stroke=style.stroke, fill=None, width=2.5, opacity=style.opacity,
                    fontsize=max(10.0, min(28.0, rect.height / (2.8 if with_date else 1.6))),
                    text_color=style.stroke)
    annot = page.add_freetext_annot(rect, text, fontsize=st.fontsize, fontname="hebo",
                                    text_color=_rgb(st.text_color), border_width=st.width,
                                    align=fitz.TEXT_ALIGN_CENTER, rotate=page.rotation)
    annot.set_info(subject="Stamp")
    return _finish(annot, st, text)


def _stamp_label(name: str) -> str:
    """'NotForPublicRelease' -> 'NOT FOR PUBLIC RELEASE'."""
    import re
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).upper()


# ================================================================== read
def list_annots(page: fitz.Page) -> list[AnnotInfo]:
    out = []
    for a in page.annots() or []:
        try:
            colors = a.colors or {}
            info = a.info or {}
            border = a.border or {}
            vertices = []
            try:
                vertices = a.vertices or []
            except Exception:
                pass
            fontsize, text_color = 11.0, None
            if a.type[1] == "FreeText":
                fontsize, text_color = _parse_da(page.parent, a.xref)
            out.append(AnnotInfo(
                xref=a.xref, page=page.number, kind=a.type[1], rect=fitz.Rect(a.rect),
                contents=info.get("content", ""), stroke=tuple(colors.get("stroke") or ()) or None,
                fill=tuple(colors.get("fill") or ()) or None, width=float(border.get("width", 1) or 1),
                opacity=float(a.opacity if a.opacity is not None and a.opacity >= 0 else 1),
                fontsize=fontsize, text_color=text_color, author=info.get("title", ""),
                modified=info.get("modDate", ""), vertices=vertices, subject=info.get("subject", "")))
        except Exception:
            continue
    return out


def _parse_da(doc: fitz.Document, xref: int) -> tuple[float, tuple | None]:
    """Font size and text colour of a text box, from its /DA string like '/Helv 11 Tf 0 0 1 rg'."""
    import re
    try:
        kind, da = doc.xref_get_key(xref, "DA")
    except Exception:
        return 11.0, None
    da = da.strip("()") if kind == "string" else da
    size = re.search(r"([\d.]+)\s+Tf", da)
    rgb = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da)
    gray = re.search(r"([\d.]+)\s+g(?:\s|$)", da)
    color = (tuple(float(v) for v in rgb.groups()) if rgb else
             (float(gray.group(1)),) * 3 if gray else None)
    return (float(size.group(1)) if size else 11.0), color


def annot_at(page: fitz.Page, point: fitz.Point, tolerance: float = 3.0) -> AnnotInfo | None:
    """Topmost annotation under `point` (smallest one wins when they overlap)."""
    hits = []
    for info in list_annots(page):
        if info.kind in ("Popup", "Link", "Widget"):
            continue
        r = fitz.Rect(info.rect)
        r = fitz.Rect(r.x0 - tolerance, r.y0 - tolerance, r.x1 + tolerance, r.y1 + tolerance)
        if r.contains(point):
            hits.append(info)
    return min(hits, key=lambda i: abs(i.rect)) if hits else None


# ================================================================ change
def update_annot(page: fitz.Page, xref: int, style: AnnotStyle | None = None, contents: str | None = None) -> int:
    """Change colour / fill / width / opacity / text of an annotation."""
    a = _get(page, xref)
    kind = a.type[1]
    if style is not None:
        if kind == "FreeText":
            if contents is None:
                contents = a.info.get("content", "")
            a.set_border(width=style.width)
            a.update(fontsize=style.fontsize, text_color=_rgb(style.text_color),
                     fill_color=_rgb(style.fill) if style.fill else None)
        elif kind in MARKUP_TYPES or kind in ("Text", "Ink", "Stamp"):
            a.set_colors(stroke=_rgb(style.stroke))
            if kind == "Ink":
                a.set_border(width=style.width)
        else:
            a.set_colors(stroke=_rgb(style.stroke),
                         fill=_rgb(style.fill) if style.fill and kind != "Line" else
                         (_rgb(style.stroke) if kind == "Line" else None))
            a.set_border(width=style.width)
        a.set_opacity(style.opacity)
    if contents is not None:
        a.set_info(content=contents)
        if kind == "FreeText":
            # the visible text of a text box is its contents
            a.set_info(content=contents)
    a.set_info(title=a.info.get("title") or AUTHOR, modDate=fitz.get_pdf_now())
    a.update()
    return a.xref


def move_annot(page: fitz.Page, xref: int, dx: float, dy: float) -> int:
    """Move an annotation by (dx, dy) points (unrotated space). Returns its (possibly new) xref."""
    a = _get(page, xref)
    kind = a.type[1]
    if kind in MARKUP_TYPES:
        raise PageOpError("Highlights and underlines belong to their text and cannot be moved.")
    if kind in VERTEX_TYPES:
        return _rebuild_shifted(page, a, dx, dy)
    r = fitz.Rect(a.rect)
    a.set_rect(fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy))
    a.update()
    return a.xref


def resize_annot(page: fitz.Page, xref: int, new_rect: fitz.Rect) -> int:
    a = _get(page, xref)
    if a.type[1] not in RESIZABLE_TYPES:
        raise PageOpError("This kind of annotation cannot be resized; delete and draw it again.")
    new_rect = fitz.Rect(new_rect)
    new_rect.normalize()
    if new_rect.width < 4 or new_rect.height < 4:
        raise PageOpError("Too small.")
    a.set_rect(new_rect)
    a.update()
    return a.xref


def _rebuild_shifted(page: fitz.Page, a: fitz.Annot, dx: float, dy: float) -> int:
    """Lines, pen drawings and polygons keep their points in the PDF; recreate them shifted."""
    kind = a.type[1]
    colors = a.colors or {}
    border = a.border or {}
    style = AnnotStyle(stroke=tuple(colors.get("stroke") or (0, 0, 0)),
                       fill=tuple(colors.get("fill")) if colors.get("fill") else None,
                       width=float(border.get("width", 1) or 1),
                       opacity=a.opacity if a.opacity is not None and a.opacity >= 0 else 1.0)
    info = dict(a.info or {})
    line_ends = a.line_ends
    if kind == "Ink":
        strokes = [[fitz.Point(x + dx, y + dy) for x, y in s] for s in (a.vertices or [])]
        page.delete_annot(a)
        xref = add_ink(page, strokes, style)
    elif kind == "Line":
        (x1, y1), (x2, y2) = a.vertices[:2]
        page.delete_annot(a)
        xref = add_line(page, fitz.Point(x1 + dx, y1 + dy), fitz.Point(x2 + dx, y2 + dy), style)
        if line_ends:
            na = page.load_annot(xref)
            na.set_line_ends(*line_ends)
            na.update()
    else:
        pts = [fitz.Point(x + dx, y + dy) for x, y in (a.vertices or [])]
        page.delete_annot(a)
        xref = add_polygon(page, pts, style)
    na = page.load_annot(xref)
    na.set_info(content=info.get("content", ""), title=info.get("title", AUTHOR))
    na.update()
    return xref


def delete_annot(page: fitz.Page, xref: int) -> None:
    page.delete_annot(_get(page, xref))


def delete_all_annots(doc: fitz.Document, pages: list[int] | None = None, keep_forms: bool = True) -> int:
    n = 0
    for pno in pages if pages is not None else range(doc.page_count):
        page = doc[pno]
        for a in list(page.annots() or []):
            if a.type[1] in ("Widget", "Link") and keep_forms:
                continue
            page.delete_annot(a)
            n += 1
    return n


def flatten_annots(doc: fitz.Document) -> None:
    """Make annotations part of the page (no longer editable) - useful before sending a file."""
    doc.bake(annots=True, widgets=False)


# ============================================================== redaction
def mark_redaction(page: fitz.Page, rect: fitz.Rect, fill=(0, 0, 0), overlay_text: str = "") -> int:
    rect = fitz.Rect(rect)
    rect.normalize()
    if rect.width < 2 or rect.height < 2:
        raise PageOpError("Drag over the area to redact.")
    annot = page.add_redact_annot(rect, text=overlay_text or None, fill=_rgb(fill),
                                  text_color=(1, 1, 1) if overlay_text else None)
    annot.set_colors(stroke=(0.9, 0.1, 0.1))
    annot.set_info(title=AUTHOR)
    annot.update()
    return annot.xref


def mark_text_redactions(doc: fitz.Document, needle: str, pages: list[int] | None = None,
                         fill=(0, 0, 0)) -> int:
    """Mark every occurrence of `needle` (e.g. an account number) for redaction."""
    if not needle.strip():
        raise PageOpError("Enter the text to redact.")
    n = 0
    for pno in pages if pages is not None else range(doc.page_count):
        page = doc[pno]
        for r in page.search_for(needle):
            mark_redaction(page, r, fill)
            n += 1
    if n == 0:
        raise PageOpError(f"'{needle}' was not found. (Scanned pages need OCR before text can be found.)")
    return n


def count_redaction_marks(doc: fitz.Document) -> int:
    return sum(1 for p in doc for a in (p.annots(types=[fitz.PDF_ANNOT_REDACT]) or []))


def apply_redactions(doc: fitz.Document, remove_metadata: bool = False) -> int:
    """Permanently remove everything under the redaction marks. Returns the number of pages changed."""
    changed = 0
    for page in doc:
        if any(True for _ in page.annots(types=[fitz.PDF_ANNOT_REDACT]) or []):
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS,
                                  graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)
            changed += 1
    if changed == 0:
        raise PageOpError("There are no redaction marks. Use the Redact tool to mark areas first.")
    if remove_metadata:
        doc.set_metadata({})
        try:
            doc.del_xml_metadata()
        except Exception:
            pass
    return changed
