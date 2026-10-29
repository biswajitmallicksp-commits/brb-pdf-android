"""Build the editable document (QTextDocument) from the page model, and save it
as a Word (.docx) or PDF file.

Units: the page model is in points; QTextDocument layout uses 96-dpi pixels
(PX = 96/72 per point); font sizes stay in points.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSizeF, Qt
from PySide6.QtGui import (
    QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor,
    QTextDocument, QTextFormat, QTextOption,
)

from app.pdf_editor.doc_model import PageModel

PX = 96 / 72
MARGIN_PT = 36.0
PAGE_MARK = QTextFormat.Property.UserProperty + 1      # block property: page number (0-based) of a page marker
FAMILIES = {"sans": "Arial", "serif": "Times New Roman", "mono": "Courier New"}


def is_marker(block) -> bool:
    return block.blockFormat().hasProperty(PAGE_MARK)


def marker_text(page: int) -> str:
    return f"────  Page {page + 1}  ────"


# ================================================================== build
def build_document(pages: list[PageModel]) -> QTextDocument:
    doc = QTextDocument()
    first = pages[0] if pages else PageModel(0, 595, 842)
    doc.setDocumentMargin(MARGIN_PT * PX)
    doc.setPageSize(QSizeF(first.width * PX, first.height * PX))
    doc.setProperty("page_size_pt", (first.width, first.height))
    font = QFont(FAMILIES["sans"])
    font.setPointSizeF(10)
    doc.setDefaultFont(font)
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    started = False

    def new_block(bf: QTextBlockFormat, cf: QTextCharFormat | None = None) -> None:
        nonlocal started
        if started:
            cur.insertBlock(bf, cf or QTextCharFormat())
        else:
            cur.setBlockFormat(bf)
            if cf is not None:
                cur.setBlockCharFormat(cf)
            started = True

    for k, pm in enumerate(pages):
        # page marker: a grey line in the editor, a page break in Word / PDF
        bf = QTextBlockFormat()
        bf.setProperty(PAGE_MARK, pm.index)
        bf.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        bf.setTopMargin(18 if k else 0)
        bf.setBottomMargin(6)
        if k:
            bf.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        mf = QTextCharFormat()
        mf.setForeground(QColor(150, 150, 150))
        mf.setFontPointSize(8)
        new_block(bf, mf)
        cur.insertText(marker_text(pm.index), mf)
        cur.block().setUserState(pm.index)
        if not pm.has_text:
            bf = QTextBlockFormat()
            cf = QTextCharFormat()
            cf.setForeground(QColor(160, 60, 0))
            new_block(bf, cf)
            cur.insertText(f"[Page {pm.index + 1} has no text. If it is a scanned page, run OCR first.]", cf)
            cur.block().setUserState(pm.index)
            continue
        for p in pm.paras:
            bf = QTextBlockFormat()
            bf.setTopMargin(min(p.space_before, 72) * PX * 0.75)
            bf.setLineHeight(100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            if p.align == "center":
                bf.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            texts = []
            if p.is_row:
                tabs = []
                for s in p.segs:
                    pos = (s.x - MARGIN_PT) * PX
                    if pos > 2 and (not tabs or pos > tabs[-1].position + 4):
                        tabs.append(QTextOption.Tab(pos, QTextOption.TabType.LeftTab))
                bf.setTabPositions(tabs)
                bf.setNonBreakableLines(True)              # a table row stays on one line
                lead = (p.segs[0].x - MARGIN_PT) * PX > 2
                for j, s in enumerate(p.segs):
                    texts.append(("\t" if (j or lead) else "", s))
            else:
                if p.align != "center":
                    bf.setLeftMargin(max(0.0, (p.x - MARGIN_PT) * PX))
                texts.append(("", p.segs[0]))
            new_block(bf, QTextCharFormat())
            for prefix, s in texts:
                for i, r in enumerate(s.runs):
                    cf = QTextCharFormat()
                    cf.setFontFamilies([FAMILIES.get(r.family, "Arial")])
                    cf.setFontPointSize(max(4.0, r.size))
                    cf.setFontWeight(QFont.Weight.Bold if r.bold else QFont.Weight.Normal)
                    cf.setFontItalic(r.italic)
                    cf.setForeground(QColor.fromRgbF(*r.color))
                    cur.insertText((prefix if i == 0 else "") + r.text, cf)
            cur.block().setUserState(pm.index)
    cur.endEditBlock()
    doc.setModified(False)
    doc.clearUndoRedoStacks()
    return doc


def page_size_pt(doc: QTextDocument) -> tuple[float, float]:
    v = doc.property("page_size_pt")
    if v:
        return float(v[0]), float(v[1])
    s = doc.pageSize()
    return s.width() / PX, s.height() / PX


# =================================================================== PDF
_FAMILY_KEYS = {"arial": "sans", "times new roman": "serif", "courier new": "mono", "calibri": "calibri",
                "nirmala ui": "indic", "helvetica": "sans", "times": "serif", "courier": "mono"}


def _x_of(line, pos: int) -> float:
    v = line.cursorToX(pos)
    return float(v[0] if isinstance(v, tuple) else v)


def save_pdf(doc: QTextDocument, path: str | Path) -> None:
    """Write the document as a PDF with REAL text (searchable and copyable), placed exactly where the
    editor shows it. Page markers become page breaks and are not printed. (See app.word.pdf_out.)"""
    from app.word import pdf_out
    from app.word.common import set_page_setup
    if doc.property("margins_pt") is None:
        w, h = page_size_pt(doc)
        copy = doc.clone(doc)                            # parented: lives as long as the original
        set_page_setup(copy, w, h, (MARGIN_PT,) * 4)
        pdf_out.save_pdf(copy, path)
        return
    pdf_out.save_pdf(doc, path)


# ================================================================== Word
def save_docx(doc: QTextDocument, path: str | Path) -> None:
    """Write the document as a Word file (see app.word.docx_io)."""
    from app.word import docx_io
    from app.word.common import set_page_setup
    if doc.property("margins_pt") is None:
        w, h = page_size_pt(doc)
        copy = doc.clone(doc)                            # parented: lives as long as the original
        set_page_setup(copy, w, h, (MARGIN_PT,) * 4)
        docx_io.save_docx(copy, path)
        return
    docx_io.save_docx(doc, path)


def plain_text(doc: QTextDocument) -> str:
    """The text without page markers (for tests and Copy All)."""
    lines = []
    block = doc.begin()
    while block.isValid():
        if not is_marker(block):
            lines.append(block.text())
        block = block.next()
    return "\n".join(lines)
