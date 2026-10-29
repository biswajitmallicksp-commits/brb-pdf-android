"""Shared units and page settings for the editable (Word-like) documents."""
from __future__ import annotations

from PySide6.QtCore import QSizeF
from PySide6.QtGui import QFont, QImage, QTextDocument, QTextFormat

PX = 96 / 72                                             # layout pixels per point
PAGE_MARK = QTextFormat.Property.UserProperty + 1        # block property: page marker (from a PDF page)

A4 = (595.28, 841.89)
LETTER = (612.0, 792.0)
LEGAL = (612.0, 1008.0)


def is_marker(block) -> bool:
    return block.blockFormat().hasProperty(PAGE_MARK)


def page_setup(doc: QTextDocument) -> tuple[float, float, tuple[float, float, float, float]]:
    """(width, height, (left, top, right, bottom)) in points."""
    size = doc.property("page_size_pt")
    if size:
        w, h = float(size[0]), float(size[1])
    else:
        s = doc.pageSize()
        w, h = (s.width() / PX, s.height() / PX) if s.width() > 0 else A4
    m = doc.property("margins_pt")
    if m:
        margins = tuple(float(v) for v in m)
    else:
        fmt = doc.rootFrame().frameFormat()
        margins = (fmt.leftMargin() / PX, fmt.topMargin() / PX, fmt.rightMargin() / PX, fmt.bottomMargin() / PX)
    return w, h, margins                                  # type: ignore[return-value]


def set_page_setup(doc: QTextDocument, w: float, h: float, margins: tuple[float, float, float, float]) -> None:
    doc.setProperty("page_size_pt", (w, h))
    doc.setProperty("margins_pt", tuple(margins))
    doc.setDocumentMargin(0)
    fmt = doc.rootFrame().frameFormat()
    fmt.setLeftMargin(margins[0] * PX)
    fmt.setTopMargin(margins[1] * PX)
    fmt.setRightMargin(margins[2] * PX)
    fmt.setBottomMargin(margins[3] * PX)
    doc.rootFrame().setFrameFormat(fmt)
    doc.setPageSize(QSizeF(w * PX, h * PX))


def layout_at_96dpi(doc: QTextDocument) -> None:
    """Lay the document out at exactly 96 dpi whatever the screen scaling, so positions are reproducible."""
    ref = QImage(8, 8, QImage.Format.Format_RGB32)
    ref.setDotsPerMeterX(round(96 / 0.0254))
    ref.setDotsPerMeterY(round(96 / 0.0254))
    doc.documentLayout().setPaintDevice(ref)
    doc._ref_device = ref                                 # keep it alive with the document


def family_of(cf, default: str = "") -> str:
    """The first font family of a char format. (Calling fontFamilies() on a format without one can crash
    PySide6, so check first.)"""
    if cf.hasProperty(QTextFormat.Property.FontFamilies):
        fams = cf.fontFamilies()
        if fams:
            return str(fams[0])
    if cf.hasProperty(QTextFormat.Property.FontFamily):
        return cf.fontFamily() or default
    return default


def set_base_font(doc: QTextDocument, family: str, size: float) -> None:
    """The document's normal font. Kept apart from defaultFont(), which the editor's zoom changes."""
    doc.setProperty("base_font", (family, float(size)))
    f = QFont(family)
    f.setPointSizeF(size)
    doc.setDefaultFont(f)


def base_font(doc: QTextDocument) -> tuple[str, float]:
    v = doc.property("base_font")
    if v:
        return str(v[0]), float(v[1])
    f = doc.defaultFont()
    return f.family() or "Calibri", (f.pointSizeF() if f.pointSizeF() > 0 else 11.0)
