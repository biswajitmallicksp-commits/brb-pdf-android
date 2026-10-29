"""Write an editable (Word-like) document as a PDF with real, searchable text.

Every line is placed where the editor's own layout puts it (laid out at exactly 96 dpi);
MuPDF writes the text with the bundled fonts. Tables get their cell borders, pictures are
embedded, bullets and numbers are drawn, highlight / underline / strike-through are kept.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QSizeF, Qt, QUrl
from PySide6.QtGui import (
    QColor, QFont, QImage, QTextCharFormat, QTextCursor, QTextDocument, QTextListFormat, QTextTable,
)

from app.word.common import PX, base_font, family_of, is_marker, layout_at_96dpi, page_setup

_FAMILY_KEYS = {"arial": "sans", "times new roman": "serif", "courier new": "mono", "calibri": "calibri",
                "nirmala ui": "indic", "helvetica": "sans", "times": "serif", "courier": "mono",
                "cambria": "serif", "georgia": "serif", "consolas": "mono", "verdana": "sans", "tahoma": "sans",
                "segoe ui": "sans"}
_BULLETS = {QTextListFormat.Style.ListDisc: "•", QTextListFormat.Style.ListCircle: "◦",
            QTextListFormat.Style.ListSquare: "▪"}


def _x_of(line, pos: int) -> float:
    v = line.cursorToX(pos)
    return float(v[0] if isinstance(v, tuple) else v)


def _blocks(frame):
    """Every text block in document order, going into tables and frames."""
    it = frame.begin()
    while not it.atEnd():
        child = it.currentFrame()
        block = it.currentBlock()
        if child is not None:
            yield from _blocks(child)
        elif block.isValid():
            yield block
        it += 1


def _tables(frame):
    it = frame.begin()
    while not it.atEnd():
        child = it.currentFrame()
        if child is not None:
            if isinstance(child, QTextTable):
                yield child
            yield from _tables(child)
        it += 1


def save_pdf(doc: QTextDocument, path: str | Path) -> None:
    import pymupdf as fitz

    from app.pdf_editor import content, fonts

    w, h, margins = page_setup(doc)
    base_family, base_size = base_font(doc)
    clone = doc.clone()
    bf_ = QFont(base_family)
    bf_.setPointSizeF(base_size)
    clone.setDefaultFont(bf_)                              # not the editor's zoomed font
    # page markers (from a converted PDF) keep their page break but print nothing
    block = clone.begin()
    while block.isValid():
        if is_marker(block):
            c = QTextCursor(block)
            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            c.removeSelectedText()
            fmt = block.blockFormat()
            fmt.setTopMargin(0)
            fmt.setBottomMargin(0)
            c.setBlockFormat(fmt)
            small = QTextCharFormat()
            small.setFontPointSize(1)
            c.setBlockCharFormat(small)
        block = block.next()
    layout_at_96dpi(clone)
    clone.setPageSize(QSizeF(w * PX, h * PX))
    layout = clone.documentLayout()
    page_h = h * PX
    left_pt = clone.rootFrame().frameFormat().leftMargin() / PX
    out = fitz.open()

    def page_no(n: int):
        while out.page_count <= n:
            out.new_page(width=w, height=h)
        return out[n]
    page_no(0)
    used_fonts: dict[int, set] = {}

    def write(pg, text: str, x: float, y: float, cf: QTextCharFormat) -> None:
        size = cf.fontPointSize() or base_size
        va = cf.verticalAlignment()
        if va == QTextCharFormat.VerticalAlignment.AlignSuperScript:
            size, y = size * 0.66, y - size * 0.33
        elif va == QTextCharFormat.VerticalAlignment.AlignSubScript:
            size, y = size * 0.66, y + size * 0.15
        key = _FAMILY_KEYS.get(family_of(cf, base_family).lower(), "sans")
        bold = cf.fontWeight() >= QFont.Weight.DemiBold.value
        italic = cf.fontItalic()
        col = cf.foreground().color() if cf.foreground().style() != Qt.BrushStyle.NoBrush else QColor(0, 0, 0)
        rgb = (col.redF(), col.greenF(), col.blueF())
        if fonts.needs_indic_font(text):
            style = content.TextStyle("indic", size, rgb, bold, italic)
            box = fitz.Rect(x, y - size * 1.05, min(w - 2, x + size * len(text) * 1.2 + 20), y + size * 0.6)
            try:
                content.add_text(pg, box, text, style, single_line=True)
            except Exception:
                pg.insert_text((x, y), text, fontsize=size, color=rgb)
            return
        fam = fonts.family(key) if any(f.key == key for f in fonts.font_families()) else fonts.family("sans")
        file = fam.file_for(bold, italic)
        if file:
            name = f"PW{fam.key}{'B' if bold else ''}{'I' if italic else ''}"
            font = fitz.Font(fontfile=file)
        else:
            name = content._BASE14[(fam.base14 or "helv", bold, italic)]
            font = fitz.Font(name)
        tw = font.text_length(text, fontsize=size)
        if cf.background().style() != Qt.BrushStyle.NoBrush:
            bg = cf.background().color()
            if bg.isValid() and bg != QColor(255, 255, 255):
                pg.draw_rect(fitz.Rect(x, y - size * 0.92, x + tw, y + size * 0.25),
                             color=None, fill=(bg.redF(), bg.greenF(), bg.blueF()), overlay=True)
        if file:
            pg.insert_text((x, y), text, fontsize=size, fontname=name, fontfile=file, color=rgb)
            used_fonts.setdefault(pg.number, set()).add(name)
        else:
            pg.insert_text((x, y), text, fontsize=size, fontname=name, color=rgb)
        lw = max(0.5, size / 16)
        if cf.fontUnderline():
            pg.draw_line((x, y + size * 0.12), (x + tw, y + size * 0.12), color=rgb, width=lw)
        if cf.fontStrikeOut():
            pg.draw_line((x, y - size * 0.3), (x + tw, y - size * 0.3), color=rgb, width=lw)

    def image(pg, name: str, x: float, y_bottom: float, wpx: float, hpx: float) -> None:
        img = clone.resource(QTextDocument.ResourceType.ImageResource, QUrl(name))
        if not isinstance(img, QImage) or img.isNull():
            return
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        wpt = (wpx if wpx > 0 else img.width()) / PX
        hpt = (hpx if hpx > 0 else img.height()) / PX
        pg.insert_image(fitz.Rect(x, y_bottom - hpt, x + wpt, y_bottom), stream=bytes(buf.data()))

    for block in _blocks(clone.rootFrame()):
        if is_marker(block):
            continue
        text = block.text()
        lst = block.textList()
        if not text.strip() and lst is None:
            continue
        br = layout.blockBoundingRect(block)
        tl = block.layout()
        frags = []
        it = block.begin()
        while not it.atEnd():
            f = it.fragment()
            if f.isValid():
                frags.append((f.position() - block.position(), f.length(), f.charFormat()))
            it += 1
        bf = block.blockFormat()
        if not tl.lineCount():
            continue
        # list bullet / number
        if lst is not None:
            line = tl.lineAt(0)
            top = br.top() + line.y()
            pno = int(top // page_h)
            base = (top - pno * page_h + line.ascent()) / PX
            marker = _BULLETS.get(lst.format().style()) or lst.itemText(block)
            cf0 = frags[0][2] if frags else QTextCharFormat()
            mf = QTextCharFormat(cf0)
            mf.setFontUnderline(False)
            mf.setFontStrikeOut(False)
            mf.clearBackground()
            if marker in _BULLETS.values():
                mf.setFontFamilies(["Arial"])
            x_text = (br.left() + _x_of(line, 0)) / PX
            size = cf0.fontPointSize() or 11
            write(page_no(pno), marker, x_text - size * (0.9 if len(marker) == 1 else 0.6 * len(marker) + 0.4),
                  base, mf)
        tabs = [t.position for t in bf.tabPositions()]
        if tabs and "\t" in text and bf.nonBreakableLines():
            # a row from a converted PDF: every piece goes exactly to its tab stop
            line = tl.lineAt(0)
            top = br.top() + line.y()
            pno = int(top // page_h)
            base = (top - pno * page_h + line.ascent()) / PX
            pg = page_no(pno)
            left = left_pt + bf.leftMargin() / PX
            k = 0
            for fs, fl, cf in frags:
                for j, piece in enumerate(text[fs:fs + fl].split("\t")):
                    if j:
                        k += 1
                    if piece.strip():
                        x = left if k == 0 else left_pt + tabs[min(k, len(tabs)) - 1] / PX
                        if k > len(tabs):
                            x = left_pt + tabs[-1] / PX + 40 * (k - len(tabs))
                        write(pg, piece.strip(), x, base, cf)
            continue
        justify = bool(bf.alignment() & Qt.AlignmentFlag.AlignJustify)
        for li in range(tl.lineCount()):
            line = tl.lineAt(li)
            top = br.top() + line.y()
            pno = int(top // page_h)
            base = (top - pno * page_h + line.ascent()) / PX
            pg = page_no(pno)
            ls, le = line.textStart(), line.textStart() + line.textLength()
            for fs, fl, cf in frags:
                a, b = max(fs, ls), min(fs + fl, le)
                if a >= b:
                    continue
                if cf.isImageFormat():
                    imf = cf.toImageFormat()
                    for p in range(a, b):
                        x = (br.left() + _x_of(line, p)) / PX
                        image(pg, imf.name(), x, base, imf.width(), imf.height())
                    continue
                pattern = r"(\t| | +)" if justify else r"(\t| )"
                pos = a
                for piece in re.split(pattern, text[a:b]):
                    if piece and piece not in ("\t", " ") and piece.strip():
                        lead = len(piece) - len(piece.lstrip(" "))
                        x = (br.left() + _x_of(line, pos + lead)) / PX
                        write(pg, piece.lstrip(" ").replace("￼", ""), x, base, cf)
                    pos += len(piece)
    # table borders
    for table in _tables(clone.rootFrame()):
        _table_borders(table, layout, page_h, page_no, fitz)
    for pno, names in used_fonts.items():
        for name in names:
            content._fix_space_mapping(out[pno], name)
    try:
        out.subset_fonts()
    except Exception:
        pass
    out.set_metadata({"creator": "BRB PDF", "producer": "BRB PDF"})
    out.save(str(path), garbage=3, deflate=True)
    out.close()


def _table_borders(table: QTextTable, layout, page_h: float, page_no, fitz) -> None:
    fmt = table.format()
    if fmt.border() <= 0:
        return
    rows, cols = table.rows(), table.columns()
    pad = fmt.cellPadding()
    frame = layout.frameBoundingRect(table)
    xs = [None] * (cols + 1)
    ys = [None] * (rows + 1)
    xs[0], xs[cols] = frame.left(), frame.right()
    ys[0], ys[rows] = frame.top(), frame.bottom()
    for r in range(rows):
        for c in range(cols):
            cell = table.cellAt(r, c)
            if cell.row() != r or cell.column() != c:
                continue
            br = layout.blockBoundingRect(cell.firstCursorPosition().block())
            if c and cell.columnSpan() >= 1:
                xs[c] = br.left() - pad if xs[c] is None else min(xs[c], br.left() - pad)
            if r:
                ys[r] = br.top() - pad if ys[r] is None else min(ys[r], br.top() - pad)
    for arr in (xs, ys):                                   # fill gaps (columns only reached through merges)
        for i in range(1, len(arr) - 1):
            if arr[i] is None:
                j = next(k for k in range(i + 1, len(arr)) if arr[k] is not None)
                arr[i] = arr[i - 1] + (arr[j] - arr[i - 1]) / (j - i + 1)
    width = max(0.4, fmt.border() / PX)
    col = fmt.borderBrush().color() if fmt.borderBrush().style() != Qt.BrushStyle.NoBrush else QColor(0, 0, 0)
    rgb = (col.redF(), col.greenF(), col.blueF())

    def seg(x0, y0, x1, y1):
        # split a line over the pages it crosses (document y -> page y)
        if y0 == y1:
            pno = int(y0 // page_h)
            page_no(pno).draw_line((x0 / PX, (y0 - pno * page_h) / PX), (x1 / PX, (y1 - pno * page_h) / PX),
                                   color=rgb, width=width)
            return
        y = y0
        while y < y1 - 0.01:
            pno = int(y // page_h)
            end = min(y1, (pno + 1) * page_h)
            page_no(pno).draw_line((x0 / PX, (y - pno * page_h) / PX), (x0 / PX, (end - pno * page_h) / PX),
                                   color=rgb, width=width)
            y = end
    done = set()
    for r in range(rows):
        for c in range(cols):
            cell = table.cellAt(r, c)
            key = (cell.row(), cell.column())
            if key in done:
                continue
            done.add(key)
            r0, c0 = key
            r1, c1 = r0 + cell.rowSpan(), c0 + cell.columnSpan()
            x0, x1, y0, y1 = xs[c0], xs[c1], ys[r0], ys[r1]
            seg(x0, y0, x1, y0)
            seg(x0, y1, x1, y1)
            seg(x0, y0, x0, y1)
            seg(x1, y0, x1, y1)
