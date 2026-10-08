"""Editing page CONTENT (no Qt): add / change / delete text, add / delete images,
watermarks, headers and footers.

All rectangles and points are in UNROTATED page space (the space of
`page.get_text("words")`), which is what the viewer works with. Functions that
must look upright on a rotated page take care of the rotation themselves.

How existing text is changed
----------------------------
PDF has no "paragraphs" - only positioned characters. To change a line we
(1) truly remove the old characters with a text-only redaction (images and
drawings under them stay), then (2) write the new text at the same place in
the closest available font, size and colour. The result is close to the
original but the font may differ slightly if the original font cannot be
reused (most PDFs embed only the characters they use).
"""
from __future__ import annotations

import datetime as _dt
import html
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pymupdf as fitz

from app.pdf_editor import fonts
from app.pdf_pages.operations import PageOpError

log = logging.getLogger("pdfworkbench.edit")


def _rgb(color) -> tuple[float, float, float]:
    """(r, g, b) 0-1 floats from an int 0xRRGGBB, a tuple of 0-255 or 0-1 values, or '#rrggbb'."""
    if color is None:
        return (0.0, 0.0, 0.0)
    if isinstance(color, str):
        c = color.lstrip("#")
        return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    if isinstance(color, int):
        return ((color >> 16 & 255) / 255, (color >> 8 & 255) / 255, (color & 255) / 255)
    vals = tuple(color)[:3]
    return tuple(v / 255 for v in vals) if any(v > 1 for v in vals) else tuple(float(v) for v in vals)


def _hex(color) -> str:
    r, g, b = _rgb(color)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


# ============================================================ writing text
@dataclass
class TextStyle:
    family: str = "sans"        # fonts.FontFamily.key
    size: float = 11.0
    color: tuple = (0, 0, 0)
    bold: bool = False
    italic: bool = False
    align: str = "left"         # left / center / right


def _css(style: TextStyle, family: fonts.FontFamily, use_file: str | None) -> tuple[str, fitz.Archive | None]:
    weight = "bold" if style.bold else "normal"
    fstyle = "italic" if style.italic else "normal"
    if use_file:
        p = Path(use_file)
        css = (f"@font-face {{font-family: PWF; src: url({p.name});}}"
               f"* {{font-family: PWF; font-size: {style.size}px; color: {_hex(style.color)};"
               f" text-align: {style.align}; line-height: 1.2; margin: 0; padding: 0;}}")
        return css, fitz.Archive(str(p.parent))
    generic = {"helv": "sans-serif", "tiro": "serif", "cour": "monospace"}.get(family.base14, "sans-serif")
    css = (f"* {{font-family: {generic}; font-size: {style.size}px; font-weight: {weight}; font-style: {fstyle};"
           f" color: {_hex(style.color)}; text-align: {style.align}; line-height: 1.2; margin: 0; padding: 0;}}")
    return css, None


def add_text(page: fitz.Page, rect: fitz.Rect, text: str, style: TextStyle, single_line: bool = False) -> fitz.Rect:
    """Write `text` as real page content inside `rect` (unrotated page space), wrapped to its width.
    Works for any language the chosen font supports; Bengali/Hindi switch to the Indic font.
    Returns the rectangle actually used."""
    text = text.rstrip("\n")
    if not text.strip():
        raise PageOpError("There is no text to add.")
    fam = fonts.family(style.family)
    if not fonts.needs_indic_font(text):
        return _add_plain_text(page, rect, text, style, fam, single_line)
    if not fam.indic:
        fam = fonts.indic_family() or fam
    font_file = fam.file_for(style.bold, style.italic)
    css, archive = _css(style, fam, font_file)
    body = html.escape(text).replace("\n", "<br/>")
    if single_line:
        body = f"<span style='white-space: nowrap'>{body}</span>"

    rot = page.rotation % 360
    # insert_htmlbox expects the box in the page's VISIBLE (rotated) space
    view_rect = fitz.Rect(rect) * page.rotation_matrix
    view_rect.normalize()
    page_view = page.rect
    # give the text room to grow downwards (and rightwards for single lines)
    box = fitz.Rect(view_rect.x0, view_rect.y0,
                    max(view_rect.x1, page_view.x1 - 4) if single_line else view_rect.x1,
                    max(view_rect.y1, min(page_view.y1, view_rect.y0 + style.size * 1.3 * (text.count("\n") + 1) * 4)))
    kwargs = dict(css=css, scale_low=1, rotate=0)
    if archive is not None:
        kwargs["archive"] = archive
    try:
        if rot == 0:
            spare, _scale = page.insert_htmlbox(box, body, **kwargs)
        else:
            spare, _scale = _rotated_htmlbox(page, box, body, kwargs)
    except Exception as exc:
        raise PageOpError(f"The text could not be written: {exc}") from exc
    if spare < 0:
        raise PageOpError("The text does not fit in the box. Draw a larger box or use a smaller font size.")
    used = fitz.Rect(box.x0, box.y0, box.x1, box.y1 - spare)
    return used * page.derotation_matrix


_BASE14 = {("helv", False, False): "helv", ("helv", True, False): "hebo", ("helv", False, True): "heit",
           ("helv", True, True): "hebi", ("tiro", False, False): "tiro", ("tiro", True, False): "tibo",
           ("tiro", False, True): "tiit", ("tiro", True, True): "tibi", ("cour", False, False): "cour",
           ("cour", True, False): "cobo", ("cour", False, True): "coit", ("cour", True, True): "cobi"}


def _add_plain_text(page: fitz.Page, rect: fitz.Rect, text: str, style: TextStyle, fam: fonts.FontFamily,
                    single_line: bool) -> fitz.Rect:
    """English / Latin text: written character by character (no ligatures), so search and copy
    give exactly the typed text in every PDF reader."""
    font_file = fam.file_for(style.bold, style.italic)
    if font_file:
        font_name = f"PW{fam.key}{'B' if style.bold else ''}{'I' if style.italic else ''}"
        font = fitz.Font(fontfile=font_file)
    else:
        font_name = _BASE14[(fam.base14 or "helv", style.bold, style.italic)]
        font = fitz.Font(font_name)
    view = fitz.Rect(rect) * page.rotation_matrix
    view.normalize()
    lines = text.split("\n")
    line_h = style.size * 1.25
    if single_line:
        width = max(font.text_length(t, fontsize=style.size) for t in lines) + style.size
        view.x1 = max(view.x1, min(page.rect.x1 - 2, view.x0 + width))
    needed = line_h * (len(lines) + 1)
    view.y1 = max(view.y1, min(page.rect.y1 - 2, view.y0 + needed))
    align = {"left": fitz.TEXT_ALIGN_LEFT, "center": fitz.TEXT_ALIGN_CENTER,
             "right": fitz.TEXT_ALIGN_RIGHT}.get(style.align, fitz.TEXT_ALIGN_LEFT)
    box = view * page.derotation_matrix
    box.normalize()
    kwargs = dict(fontsize=style.size, fontname=font_name, color=_rgb(style.color), align=align,
                  rotate=page.rotation % 360, lineheight=1.25)
    if font_file:
        kwargs["fontfile"] = font_file
    spare = page.insert_textbox(box, text, **kwargs)
    if spare < 0:
        raise PageOpError("The text does not fit in the box. Draw a larger box or use a smaller font size.")
    return box


def _rotated_htmlbox(page: fitz.Page, view_box: fitz.Rect, body: str, kwargs: dict):
    """insert_htmlbox on a page with /Rotate: give the box in unrotated space and turn the text."""
    rot = page.rotation % 360
    unrot = view_box * page.derotation_matrix
    unrot.normalize()
    kwargs = dict(kwargs)
    kwargs["rotate"] = rot
    return page.insert_htmlbox(unrot, body, **kwargs)


# ======================================================= existing text
@dataclass
class TextLine:
    page: int
    rect: fitz.Rect          # unrotated page space
    text: str
    font: str
    size: float
    color: int
    flags: int
    origin: fitz.Point
    editable: bool = True

    def style(self) -> TextStyle:
        bold, italic = fonts.style_from_font(self.font, self.flags)
        return TextStyle(fonts.guess_family(self.font, self.flags), round(self.size, 1),
                         _rgb(self.color), bold, italic)


def text_line_at(page: fitz.Page, point: fitz.Point, tolerance: float = 2.0) -> TextLine | None:
    """The text line under `point` (unrotated page space), with its main font, size and colour."""
    data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    best = None
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            bbox = fitz.Rect(line["bbox"])
            hit = fitz.Rect(bbox.x0 - tolerance, bbox.y0 - tolerance, bbox.x1 + tolerance, bbox.y1 + tolerance)
            if not hit.contains(point):
                continue
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            main = max(spans, key=lambda s: len(s["text"].strip()))
            cand = TextLine(page.number, bbox, text, main["font"], main["size"], main["color"], main["flags"],
                            fitz.Point(main["origin"]))
            if best is None or abs(bbox) < abs(best.rect):
                best = cand
    return best


def remove_text(page: fitz.Page, rects: Iterable[fitz.Rect]) -> int:
    """Truly delete the characters inside `rects` (text only; images and lines stay).
    Returns the number of areas processed."""
    n = 0
    for r in rects:
        r = fitz.Rect(r)
        if r.is_empty:
            continue
        page.add_redact_annot(r, fill=False)
        n += 1
    if n:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    return n


def words_in(page: fitz.Page, rect: fitz.Rect) -> list[fitz.Rect]:
    """Boxes of the words touched by `rect`."""
    return [fitz.Rect(w[:4]) for w in page.get_text("words") if fitz.Rect(w[:4]).intersects(rect)]


def delete_text_in(page: fitz.Page, rect: fitz.Rect) -> int:
    """Delete every word touched by `rect`. Returns the number of words removed."""
    boxes = words_in(page, rect)
    if not boxes:
        raise PageOpError("There is no text in the selected area. (Scanned pages are pictures - "
                          "use Redact to black out an area, or OCR first.)")
    remove_text(page, [_shrink(b, page=page) for b in boxes])
    return len(boxes)


def _shrink(r: fitz.Rect, by: float = 0.15, page: fitz.Page | None = None) -> fitz.Rect:
    """Slightly thinner box (across the text line), so neighbouring lines are not touched.
    On rotated pages the text runs vertically in unrotated space, so shrink in visible space."""
    m = page.rotation_matrix if page is not None else fitz.Identity
    v = fitz.Rect(r) * m
    v.normalize()
    dy = v.height * by
    v = fitz.Rect(v.x0, v.y0 + dy, v.x1, v.y1 - dy) * ~m
    v.normalize()
    return v


def replace_line(page: fitz.Page, line: TextLine, new_text: str, style: TextStyle | None = None) -> fitz.Rect:
    """Replace one text line with `new_text` (empty = delete the line)."""
    style = style or line.style()
    remove_text(page, [_shrink(line.rect, 0.1, page)])
    if not new_text.strip():
        return line.rect
    return _write_line(page, line, new_text, style)


def _write_line(page: fitz.Page, line: TextLine, new_text: str, style: TextStyle) -> fitz.Rect:
    """Write `new_text` where `line` was (same baseline, size, colour, closest font)."""
    # work in the page's visible space so rotated pages behave the same
    view = fitz.Rect(line.rect) * page.rotation_matrix
    view.normalize()
    if page.rotation % 360 == 0:
        top = line.origin.y - style.size * 0.93          # baseline minus ascent
    else:
        top = view.y0
    box = fitz.Rect(view.x0, top, max(view.x1, view.x0 + 50), top + style.size * 2.5)
    rect = box * page.derotation_matrix
    rect.normalize()
    return add_text(page, rect, new_text, style, single_line=True)


def _is_ocr_layer(font_name: str) -> bool:
    """Invisible OCR text (glyphless fonts) is not part of what the page shows."""
    return "glyphless" in (font_name or "").lower()


def page_lines(page: fitz.Page, column_gap: float = 1.6) -> list[TextLine]:
    """Every visible line of text on the page, top to bottom, for the Edit Text panel.

    A line is cut into separate pieces where there is a wide gap (more than `column_gap`
    times the font size), so table columns (date | description | amount) can be edited
    one by one. Each piece has `editable` = True when it reads left-to-right on screen.
    Rects are in unrotated page space (like the rest of this module)."""
    data = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    rot = fitz.Matrix(page.rotation_matrix)
    rot.e = rot.f = 0
    vis = page.rotation_matrix
    out: list[TextLine] = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            d = fitz.Point(line.get("dir", (1, 0))) * rot
            upright = abs(d.y) < 0.05 and d.x > 0
            pieces: list[list[tuple[dict, dict]]] = [[]]
            prev = None
            for span in line.get("spans", []):
                if _is_ocr_layer(span.get("font", "")):
                    continue
                for ch in span.get("chars", []):
                    box = fitz.Rect(ch["bbox"]) * vis
                    box.normalize()
                    if prev is not None and upright and ch["c"].strip():
                        gap = box.x0 - prev[1].x1
                        if gap > column_gap * max(span["size"], prev[0]["size"]):
                            pieces.append([])
                    pieces[-1].append((span, ch))
                    if ch["c"].strip():
                        prev = (span, box)
            for piece in pieces:
                ink = [(sp, ch) for sp, ch in piece if ch["c"].strip()]
                if not ink:
                    continue
                text = "".join(ch["c"] for _, ch in piece).strip()
                rect = fitz.Rect(ink[0][1]["bbox"])
                for _, ch in ink[1:]:
                    rect |= fitz.Rect(ch["bbox"])
                # main style = the span holding most of the letters
                counts: dict[int, int] = {}
                for sp, _ in ink:
                    counts[id(sp)] = counts.get(id(sp), 0) + 1
                main = max((sp for sp, _ in ink), key=lambda sp: counts[id(sp)])
                tl = TextLine(page.number, rect, text, main["font"], main["size"], main["color"], main["flags"],
                              fitz.Point(ink[0][1]["origin"]))
                tl.editable = upright
                out.append(tl)
    def key(t: TextLine):
        # same baseline = same row (heights differ between fonts), then left to right
        o = t.origin * vis
        v = fitz.Rect(t.rect) * vis
        v.normalize()
        return (round(o.y / 2), v.x0)
    out.sort(key=key)
    return out


def replace_lines(page: fitz.Page, changes: list[tuple[TextLine, str]]) -> int:
    """Rewrite or delete several lines at once (empty text = delete).
    All old words are removed first, then the new words written. Returns the number changed."""
    changes = [(ln, t.replace("\n", " ").rstrip()) for ln, t in changes]
    if not changes:
        return 0
    remove_text(page, [_shrink(ln.rect, 0.2, page) for ln, _ in changes])
    for ln, text in changes:
        if text.strip():
            _write_line(page, ln, text, ln.style())
    return len(changes)


# ================================================================== images
def add_image(page: fitz.Page, rect: fitz.Rect, image_path: str, keep_proportion: bool = True,
              opacity: float = 1.0) -> None:
    """Place a picture (JPG, PNG, ...) in `rect` (unrotated space), upright on rotated pages."""
    path = Path(image_path)
    if not path.is_file():
        raise PageOpError(f"Image not found:\n{path}")
    try:
        if opacity < 1.0:
            pix = fitz.Pixmap(str(path))
            if not pix.alpha:
                pix = fitz.Pixmap(pix, 1)
            pix.set_alpha(bytes([int(255 * opacity)]) * (pix.width * pix.height))
            page.insert_image(rect, pixmap=pix, keep_proportion=keep_proportion, rotate=page.rotation)
        else:
            page.insert_image(rect, filename=str(path), keep_proportion=keep_proportion, rotate=page.rotation)
    except Exception as exc:
        raise PageOpError(f"The image could not be added: {exc}") from exc


def image_boxes(page: fitz.Page) -> list[tuple[int, fitz.Rect]]:
    """(xref, rectangle) of every picture shown on the page."""
    out = []
    _forget_image_cache(page)
    for info in page.get_image_info(xrefs=True):
        out.append((info.get("xref", 0), fitz.Rect(info["bbox"])))
    return out


def _forget_image_cache(page: fitz.Page) -> None:
    """PyMuPDF remembers a page's picture list; forget it after the page changed."""
    if hasattr(page, "_image_info"):
        page._image_info = None


def delete_images_in(page: fitz.Page, rect: fitz.Rect) -> int:
    """Remove the pictures that touch `rect` from this page. Text and drawings stay."""
    infos = [i for i in page.get_image_info(xrefs=True) if fitz.Rect(i["bbox"]).intersects(rect)]
    if not infos:
        raise PageOpError("There is no picture in the selected area.")
    if _remove_image_calls(page, infos):
        return len(infos)
    # fallback (pictures inside nested objects): blank out exactly the picture area
    for i in infos:
        r = fitz.Rect(i["bbox"])
        page.add_redact_annot(fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1), fill=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_NONE)
    return len(infos)


def _remove_image_calls(page: fitz.Page, infos: list[dict]) -> bool:
    """Delete the 'draw this picture' commands from the page content. Only used when each
    picture is drawn exactly once, directly on the page; returns False otherwise."""
    import re
    doc = page.parent
    boxes = [fitz.Rect(i["bbox"]) for i in infos]
    page.clean_contents()                      # one content stream (may rename resources)
    _forget_image_cache(page)
    all_infos = page.get_image_info(xrefs=True)
    infos = [i for i in all_infos if any(fitz.Rect(i["bbox"]) == b for b in boxes)]
    if len(infos) != len(boxes):
        return False
    names = []
    for info in infos:
        xref = info.get("xref", 0)
        if xref <= 0 or sum(1 for i in all_infos if i.get("xref") == xref) != 1:
            return False
        name = next((img[7] for img in page.get_images(full=True) if img[0] == xref and img[9] == 0), None)
        if not name:
            return False
        names.append(name)
    xrefs = page.get_contents()
    if len(xrefs) != 1:
        return False
    stream = doc.xref_stream(xrefs[0]).decode("latin-1")
    new = stream
    for name in names:
        new, n = re.subn(rf"/{re.escape(name)}\s+Do\b", "", new)
        if n != 1:
            return False
    doc.update_stream(xrefs[0], new.encode("latin-1"))
    _forget_image_cache(page)
    return True


def extract_images(doc: fitz.Document, pages: Iterable[int], folder: str | Path, stem: str) -> list[Path]:
    """Save every picture on `pages` as a file (original format where possible)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written, seen = [], set()
    for pno in pages:
        for img in doc[pno].get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                data = doc.extract_image(xref)
            except Exception:
                continue
            if not data or not data.get("image"):
                continue
            ext = data.get("ext", "png")
            out = folder / f"{stem}_p{pno + 1}_img{len(written) + 1}.{ext}"
            out.write_bytes(data["image"])
            written.append(out)
    return written


# ============================================================ watermark etc.
POSITIONS = ("top-left", "top-center", "top-right", "center", "bottom-left", "bottom-center", "bottom-right")


def _anchor(view: fitz.Rect, box_w: float, box_h: float, position: str, margin: float) -> fitz.Point:
    """Top-left corner of a box_w x box_h box placed at `position` within `view`."""
    vert, _, horiz = position.partition("-")
    if position == "center":
        vert, horiz = "middle", "center"
    x = {"left": view.x0 + margin, "center": view.x0 + (view.width - box_w) / 2,
         "right": view.x1 - margin - box_w}[horiz]
    y = {"top": view.y0 + margin, "middle": view.y0 + (view.height - box_h) / 2,
         "bottom": view.y1 - margin - box_h}[vert]
    return fitz.Point(x, y)


def add_text_watermark(page: fitz.Page, text: str, fontsize: float = 60, color=(0.6, 0.6, 0.6),
                       opacity: float = 0.3, angle: float = 45, position: str = "center",
                       margin: float = 36, behind: bool = False) -> None:
    """Large (usually diagonal) text, semi-transparent, drawn on top of the page (or behind it)."""
    if not text.strip():
        raise PageOpError("Enter the watermark text.")
    font = fitz.Font("helv")
    width = font.text_length(text, fontsize=fontsize)
    view = page.rect
    a = _anchor(view, width, fontsize, position, margin)
    center = fitz.Point(a.x + width / 2, a.y + fontsize / 2)
    origin = fitz.Point(center.x - width / 2, center.y + fontsize * 0.35)
    # build in view space, then map to unrotated space
    derot = page.derotation_matrix
    rot = page.rotation % 360
    morph = (center * derot, fitz.Matrix(angle) if angle else fitz.Matrix(1, 1))
    page.insert_text(origin * derot, text, fontsize=fontsize, fontname="helv", color=_rgb(color),
                     fill_opacity=opacity, stroke_opacity=opacity, rotate=rot, morph=morph, overlay=not behind)


def add_image_watermark(page: fitz.Page, image_path: str, scale: float = 0.5, opacity: float = 0.3,
                        position: str = "center", margin: float = 36, behind: bool = False) -> None:
    pix = fitz.Pixmap(str(image_path))
    view = page.rect
    w = view.width * scale
    h = w * pix.height / max(1, pix.width)
    if h > view.height * scale:
        h = view.height * scale
        w = h * pix.width / max(1, pix.height)
    a = _anchor(view, w, h, position, margin)
    box = fitz.Rect(a.x, a.y, a.x + w, a.y + h) * page.derotation_matrix
    box.normalize()
    if not pix.alpha:
        pix = fitz.Pixmap(pix, 1)
    pix.set_alpha(bytes([int(255 * opacity)]) * (pix.width * pix.height))
    page.insert_image(box, pixmap=pix, overlay=not behind, rotate=page.rotation)


@dataclass
class HeaderFooterItem:
    position: str        # one of POSITIONS except 'center'
    text: str            # may contain {page} {pages} {date} {file}


def expand_tokens(text: str, page_no: int, pages: int, file_name: str, date: _dt.date | None = None) -> str:
    date = date or _dt.date.today()
    return (text.replace("{page}", str(page_no)).replace("{pages}", str(pages))
            .replace("{date}", date.strftime("%d-%m-%Y")).replace("{file}", file_name))


def add_header_footer(page: fitz.Page, items: list[HeaderFooterItem], total_pages: int, file_name: str,
                      fontsize: float = 9, color=(0.2, 0.2, 0.2), margin: float = 24,
                      number_offset: int = 0) -> None:
    font = fitz.Font("helv")
    view = page.rect
    derot = page.derotation_matrix
    rot = page.rotation % 360
    for item in items:
        text = expand_tokens(item.text, page.number + 1 + number_offset, total_pages, file_name)
        if not text.strip():
            continue
        width = font.text_length(text, fontsize=fontsize)
        a = _anchor(view, width, fontsize, item.position, margin)
        origin = fitz.Point(a.x, a.y + fontsize * 0.8)
        page.insert_text(origin * derot, text, fontsize=fontsize, fontname="helv", color=_rgb(color), rotate=rot)
