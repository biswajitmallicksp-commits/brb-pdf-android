"""BRB PDF Word: an offline, Word-like editor.

Two ways in:
  * a Word document (.docx) - opened, edited and saved back to the same file (Ctrl+S), or a new blank one;
  * the text of a PDF / OCR result ("Convert PDF to Word") - a temporary document in memory. Nothing is
    written until you press Save (Word and/or PDF, in the original folder or another one, keeping or
    removing the original PDF). The original PDF is never changed.

Tools: fonts, sizes, bold / italic / underline / strike, colours, highlight, headings, alignment,
bullets and numbering, indents, line spacing, tables (add / remove rows and columns, merge), pictures,
page breaks, page size and margins, find and replace, print, save as Word or PDF.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QMarginsF, QSize, QSizeF, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction, QActionGroup, QBrush, QColor, QFont, QImage, QKeySequence, QPageLayout, QPageSize, QPainter, QPen,
    QPixmap, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat, QTextFrameFormat,
    QTextImageFormat, QTextLength, QTextListFormat, QTextTableFormat,
)
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QRadioButton, QScrollArea,
    QSpinBox, QTextEdit, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from app import config
from app.pdf_editor import doc_export as X
from app.pdf_editor import doc_model as M
from app.word import docx_io, pdf_out
from app.word.common import A4, base_font, family_of, set_base_font, LEGAL, LETTER, PX, is_marker, layout_at_96dpi, page_setup, set_page_setup

log = logging.getLogger("pdfworkbench.doceditor")

SAVE_STYLE = "QToolButton { background:#2f6fdb; color:white; border-radius:4px; padding:4px 10px; font-weight:600; }"
WORD_FILTER = "Word document (*.docx)"
PDF_FILTER = "PDF document (*.pdf)"
FONTS = ["Calibri", "Arial", "Times New Roman", "Cambria", "Georgia", "Verdana", "Tahoma", "Courier New",
         "Nirmala UI"]
SIZES = ["8", "9", "10", "10.5", "11", "12", "14", "16", "18", "20", "22", "24", "28", "36", "48", "72"]
# name: (size, bold, colour, heading level, space before, space after)
STYLES = {
    "Normal": (None, False, None, 0, 0, 8),
    "Title": (26, False, "#17365d", 1, 0, 12),
    "Heading 1": (16, True, "#365f91", 1, 18, 6),
    "Heading 2": (13, True, "#4f81bd", 2, 10, 4),
    "Heading 3": (12, True, "#4f81bd", 3, 10, 4),
}
HIGHLIGHTS = [("Yellow", "#ffff00"), ("Bright green", "#00ff00"), ("Turquoise", "#00ffff"), ("Pink", "#ff00ff"),
              ("Light grey", "#c0c0c0")]
PAGE_SIZES = {"A4": A4, "Letter": LETTER, "Legal": LEGAL}
CM = 72 / 2.54


class _Editor(QTextEdit):
    """QTextEdit that pastes pictures and shows where pages begin (dashed line) and page breaks."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.page_starts: list[tuple[int, int, int]] = []     # (block number, line, page index)

    def canInsertFromMimeData(self, source) -> bool:
        return source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QImage) and not img.isNull():
                self.owner.insert_image(img)
                return
        super().insertFromMimeData(source)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        doc = self.document()
        lay = doc.documentLayout()
        dx, dy = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        p = QPainter(self.viewport())
        p.setPen(QPen(QColor(150, 160, 175), 1, Qt.PenStyle.DashLine))
        f = p.font()
        f.setPointSizeF(7.5)
        p.setFont(f)
        width = self.viewport().width()
        h = self.viewport().height()
        for bno, li, page in self.page_starts:
            block = doc.findBlockByNumber(bno)
            if not block.isValid() or is_marker(block):
                continue
            br = lay.blockBoundingRect(block)
            tl = block.layout()
            y = br.top() + (tl.lineAt(li).y() if 0 <= li < tl.lineCount() else 0) - dy - 2
            if -10 < y < h + 10:
                p.drawLine(0, int(y), width, int(y))
                p.drawText(6 - dx, int(y) - 2, f"Page {page + 1}")


class DocEditorWindow(QMainWindow):
    """PDF text:      DocEditorWindow.open_for(parent, pdf_bytes, pages, title, folder, ...)
    Word document: DocEditorWindow.open_docx(parent, path) / DocEditorWindow.new_document(parent, folder)"""

    def __init__(self, pages: list[M.PageModel] | None, source: fitz.Document | None, title: str, folder: Path,
                 parent=None, original: Path | None = None, retire_original=None,
                 document: QTextDocument | None = None, path: Path | None = None):
        # its own window (own taskbar button, can go behind BRB PDF); `host` is the BRB PDF main window
        super().__init__(None)
        self.host = parent
        if parent is not None and not parent.windowIcon().isNull():
            self.setWindowIcon(parent.windowIcon())
        self.original = Path(original) if original else None       # the PDF this text came from
        self.retire_original = retire_original                   # callback: move the original to the Recycle Bin
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.source = source                    # a private copy of the PDF, for the original-page preview
        self.word_mode = document is not None   # a Word document (not the text of a PDF)
        self.path = Path(path) if path else None                  # the .docx being edited
        self.base_title = title
        self.folder = Path(folder)
        self.saved_to: list[str] = []
        self._preview_page = -1
        self._images = 0
        self.resize(1300, 900)

        self.doc = document if document is not None else X.build_document(pages or [])
        if self.doc.property("margins_pt") is None:              # a converted PDF: keep its 0.5 inch margins
            w, h = X.page_size_pt(self.doc)
            m = X.MARGIN_PT
            set_page_setup(self.doc, w, h, (m, m, m, m))
            self.doc.setModified(False)
            self.doc.clearUndoRedoStacks()
        if self.doc.property("base_font") is None:
            df = self.doc.defaultFont()
            set_base_font(self.doc, df.family(), df.pointSizeF() if df.pointSizeF() > 0 else 11)
        fam, size = base_font(self.doc)
        self.edit = _Editor(self)
        self.edit.setDocument(self.doc)
        font = QFont(fam)
        font.setPointSizeF(size)
        self.edit.setFont(font)                    # QTextEdit gives its document the widget's font
        self.doc.setModified(False)
        self.edit.setAcceptRichText(self.word_mode)
        self.edit.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
        self.edit.setStyleSheet("QTextEdit { background: white; border: 1px solid #b8bec8; }")
        self.edit.cursorPositionChanged.connect(self._cursor_moved)
        self.doc.modificationChanged.connect(self._modified_changed)
        self.doc.contentsChanged.connect(self._schedule_pages)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(12, 12, 12, 12)
        hl.addStretch(1)
        hl.addWidget(self.edit, 100)
        hl.addStretch(1)
        holder.setStyleSheet("background:#d6dae0;")
        self.setCentralWidget(holder)
        self._apply_page_width()

        # original page preview (PDF text only)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.preview_label = QLabel()
        pv = QWidget()
        pl = QVBoxLayout(pv)
        pl.addWidget(self.preview_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview)
        pl.addWidget(scroll, 1)
        self.preview_dock = QDockWidget("Original page", self)
        self.preview_dock.setObjectName("originalPreview")
        self.preview_dock.setWidget(pv)
        self.preview_dock.setMinimumWidth(360)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.preview_dock)
        if self.source is None:
            self.preview_dock.hide()

        self._pages_timer = QTimer(self)
        self._pages_timer.setSingleShot(True)
        self._pages_timer.setInterval(700)
        self._pages_timer.timeout.connect(self._update_pages)
        self.page_count = 1

        self._make_actions()
        self._make_menus()
        self._make_toolbars()
        self.doc.undoAvailable.connect(self.a_undo.setEnabled)
        self.doc.redoAvailable.connect(self.a_redo.setEnabled)
        self.status = QLabel()
        self.pages_label = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.pages_label)
        self._modified_changed(False)
        self._cursor_moved()
        self._update_pages()
        self._format_changed(self.edit.currentCharFormat())

    # ============================================================ actions
    def _act(self, text: str, slot, shortcut=None, tip: str = "", checkable: bool = False) -> QAction:
        a = QAction(text, self)
        a.triggered.connect(lambda _c=False: slot())
        if shortcut:
            a.setShortcuts(shortcut if isinstance(shortcut, list) else [QKeySequence(shortcut)])
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        self.addAction(a)
        return a

    def _make_actions(self) -> None:  # noqa: C901
        A = self._act
        # file
        self.a_new = A("&New Word Document", self.new_window, "Ctrl+N")
        self.a_open = A("&Open...", self.open_other, "Ctrl+O", "Open a Word document or a PDF")
        if self.word_mode:
            self.a_save = A("&Save", self.save, [QKeySequence(QKeySequence.StandardKey.Save)],
                            "Save the Word document")
            self.a_save_as = A("Save &As...", self.save_as, "Ctrl+Shift+S", "Save as a new Word or PDF file")
        else:
            self.a_save = A("Save...", self.save, [QKeySequence(QKeySequence.StandardKey.Save),
                                                   QKeySequence("Ctrl+Shift+S")],
                            "Save as Word or PDF - in the original folder or another one")
            self.a_save_as = self.a_save
        self.a_export_pdf = A("Export as &PDF...", self.export_pdf, "Ctrl+Shift+P",
                              "Save a PDF copy (real, searchable text)")
        self.a_print = A("&Print...", self.print_document, "Ctrl+P")
        self.a_page_setup = A("Page Set&up...", self.page_setup_dialog, None, "Paper size, orientation and margins")
        self.a_close = A("&Close", self.close, "Ctrl+W")
        # kept for scripts/tests: direct saves without the options window
        self.a_word = A("Save as Word", self.save_word)
        self.a_pdf = A("Save as PDF", self.save_pdf)
        # edit
        self.a_undo = A("Undo", self.edit.undo, [QKeySequence(QKeySequence.StandardKey.Undo)])
        self.a_redo = A("Redo", self.edit.redo, [QKeySequence(QKeySequence.StandardKey.Redo)])
        self.a_undo.setEnabled(False)
        self.a_redo.setEnabled(False)
        self.a_find = A("Find && Replace...", self.find_replace, [QKeySequence(QKeySequence.StandardKey.Find),
                                                                   QKeySequence("Ctrl+H")])
        # character
        self.a_bold = A("B", self._toggle_bold, [QKeySequence(QKeySequence.StandardKey.Bold)], "Bold (Ctrl+B)", True)
        self.a_italic = A("I", lambda: self.edit.setFontItalic(not self.edit.fontItalic()),
                          [QKeySequence(QKeySequence.StandardKey.Italic)], "Italic (Ctrl+I)", True)
        self.a_under = A("U", lambda: self.edit.setFontUnderline(not self.edit.fontUnderline()),
                         [QKeySequence(QKeySequence.StandardKey.Underline)], "Underline (Ctrl+U)", True)
        self.a_strike = A("S", self._toggle_strike, None, "Strikethrough", True)
        for a, how in ((self.a_bold, "bold"), (self.a_italic, "italic"), (self.a_under, "under"),
                       (self.a_strike, "strike")):
            f = QFont()
            f.setBold(how == "bold")
            f.setItalic(how == "italic")
            f.setUnderline(how == "under")
            f.setStrikeOut(how == "strike")
            a.setFont(f)
        self.a_super = A("x²", lambda: self._vertical(QTextCharFormat.VerticalAlignment.AlignSuperScript),
                         "Ctrl+Shift++", "Superscript", True)
        self.a_sub = A("x₂", lambda: self._vertical(QTextCharFormat.VerticalAlignment.AlignSubScript),
                       "Ctrl+=", "Subscript", True)
        self.a_color = A("A", self.choose_color, None, "Font colour")
        self.a_clear = A("Clear Formatting", self.clear_formatting, "Ctrl+Space")
        # paragraph
        self.align_group = QActionGroup(self)
        self.a_left = A("Left", lambda: self.set_alignment(Qt.AlignmentFlag.AlignLeft), "Ctrl+L", "Align left", True)
        self.a_center = A("Center", lambda: self.set_alignment(Qt.AlignmentFlag.AlignHCenter), "Ctrl+E",
                          "Center", True)
        self.a_right = A("Right", lambda: self.set_alignment(Qt.AlignmentFlag.AlignRight), "Ctrl+R",
                         "Align right", True)
        self.a_justify = A("Justify", lambda: self.set_alignment(Qt.AlignmentFlag.AlignJustify), "Ctrl+J",
                           "Justify", True)
        for a in (self.a_left, self.a_center, self.a_right, self.a_justify):
            self.align_group.addAction(a)
        self.a_bullets = A("• List", lambda: self.toggle_list(QTextListFormat.Style.ListDisc), "Ctrl+Shift+L",
                           "Bullets", True)
        self.a_numbers = A("1. List", lambda: self.toggle_list(QTextListFormat.Style.ListDecimal), None,
                           "Numbering", True)
        self.a_outdent = A("⇤", lambda: self.change_indent(-1), "Ctrl+Shift+M", "Decrease indent")
        self.a_indent = A("⇥", lambda: self.change_indent(1), "Ctrl+M", "Increase indent")
        # insert
        self.a_table = A("Table...", self.insert_table_dialog, None, "Insert a table")
        self.a_picture = A("Picture...", self.insert_picture, None, "Insert a picture from a file")
        self.a_break = A("Page Break", self.insert_page_break, "Ctrl+Return", "Start a new page")
        self.a_pic_size = A("Picture Size...", self.picture_size_dialog, None, "Change the size of the picture")
        # table
        self.a_row_above = A("Insert Row Above", lambda: self._table_op("row_above"))
        self.a_row_below = A("Insert Row Below", lambda: self._table_op("row_below"))
        self.a_col_left = A("Insert Column Left", lambda: self._table_op("col_left"))
        self.a_col_right = A("Insert Column Right", lambda: self._table_op("col_right"))
        self.a_del_row = A("Delete Row", lambda: self._table_op("del_row"))
        self.a_del_col = A("Delete Column", lambda: self._table_op("del_col"))
        self.a_del_table = A("Delete Table", lambda: self._table_op("del_table"))
        self.a_merge = A("Merge Cells", lambda: self._table_op("merge"))
        self.a_split = A("Split Cell", lambda: self._table_op("split"))
        # view
        self.a_zoom_in = A("Zoom In", lambda: self.edit.zoomIn(1), "Ctrl++")
        self.a_zoom_out = A("Zoom Out", lambda: self.edit.zoomOut(1), "Ctrl+-")
        self.a_preview = A("Show Original", lambda: self.preview_dock.setVisible(self.a_preview.isChecked()),
                           None, "Show the original PDF page beside the text", True)
        self.a_preview.setChecked(self.source is not None)
        self.a_preview.setEnabled(self.source is not None)
        self.preview_dock.visibilityChanged.connect(self.a_preview.setChecked)
        self.edit.currentCharFormatChanged.connect(self._format_changed)

    def _make_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_open):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_save)
        if self.word_mode:
            m.addAction(self.a_save_as)
        m.addAction(self.a_export_pdf)
        m.addSeparator()
        m.addAction(self.a_page_setup)
        m.addAction(self.a_print)
        m.addSeparator()
        m.addAction(self.a_close)
        m = mb.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo):
            m.addAction(a)
        m.addSeparator()
        m.addAction("Cu&t", self.edit.cut, QKeySequence.StandardKey.Cut)
        m.addAction("&Copy", self.edit.copy, QKeySequence.StandardKey.Copy)
        m.addAction("&Paste", self.edit.paste, QKeySequence.StandardKey.Paste)
        m.addAction("Paste as Plain Text", self.paste_plain, QKeySequence("Ctrl+Shift+V"))
        m.addAction("Select &All", self.edit.selectAll, QKeySequence.StandardKey.SelectAll)
        m.addSeparator()
        m.addAction(self.a_find)
        m = mb.addMenu("&Insert")
        for a in (self.a_table, self.a_picture, self.a_break):
            m.addAction(a)
        m = mb.addMenu("F&ormat")
        for a in (self.a_bold, self.a_italic, self.a_under, self.a_strike, self.a_super, self.a_sub):
            m.addAction(a)
        m.addAction(self.a_color)
        hl = m.addMenu("Highlight")
        self._fill_highlight_menu(hl)
        m.addAction(self.a_clear)
        m.addSeparator()
        for a in (self.a_left, self.a_center, self.a_right, self.a_justify):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_bullets, self.a_numbers, self.a_indent, self.a_outdent):
            m.addAction(a)
        sp = m.addMenu("Line Spacing")
        for v in ("1.0", "1.15", "1.5", "2.0"):
            sp.addAction(v, lambda _c=False, x=float(v): self.set_line_spacing(x))
        m.addSeparator()
        m.addAction(self.a_pic_size)
        m.addAction(self.a_page_setup)
        m = mb.addMenu("T&able")
        m.addAction(self.a_table)
        m.addSeparator()
        for a in (self.a_row_above, self.a_row_below, self.a_col_left, self.a_col_right):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_del_row, self.a_del_col, self.a_del_table):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_merge)
        m.addAction(self.a_split)
        self.table_menu = m
        m = mb.addMenu("&View")
        m.addAction(self.a_zoom_in)
        m.addAction(self.a_zoom_out)
        m.addAction(self.a_preview)

    def _fill_highlight_menu(self, menu: QMenu) -> None:
        for name, col in HIGHLIGHTS:
            pm = QPixmap(14, 14)
            pm.fill(QColor(col))
            menu.addAction(pm, name, lambda _c=False, c=col: self.set_highlight(c))
        menu.addAction("No highlight", lambda: self.set_highlight(None))

    def _make_toolbars(self) -> None:
        tb = QToolBar("File")
        tb.setObjectName("fileBar")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)
        tb.addAction(self.a_save)
        self.save_btn = tb.widgetForAction(self.a_save)
        if self.word_mode:
            tb.addAction(self.a_save_as)
        tb.addAction(self.a_export_pdf)
        tb.addAction(self.a_print)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()
        tb.addAction(self.a_find)
        tb.addAction(self.a_page_setup)
        tb.addSeparator()
        tb.addAction(self.a_zoom_in)
        tb.addAction(self.a_zoom_out)
        if self.source is not None:
            tb.addAction(self.a_preview)
        self.addToolBarBreak()

        fb = QToolBar("Format")
        fb.setObjectName("formatBar")
        fb.setMovable(False)
        fb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(fb)
        self.style_box = QComboBox()
        self.style_box.addItems(list(STYLES))
        self.style_box.setToolTip("Style")
        self.style_box.activated.connect(lambda _i: self.apply_style(self.style_box.currentText()))
        fb.addWidget(self.style_box)
        self.font_box = QComboBox()
        self.font_box.setEditable(True)
        self.font_box.addItems(FONTS)
        self.font_box.setMinimumWidth(140)
        self.font_box.setToolTip("Font")
        self.font_box.activated.connect(lambda _i: self._set_family())
        self.font_box.lineEdit().returnPressed.connect(self._set_family)
        fb.addWidget(self.font_box)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems(SIZES)
        self.size_box.setMinimumWidth(70)
        self.size_box.setMaximumWidth(80)
        self.size_box.setToolTip("Font size")
        self.size_box.activated.connect(lambda _i: self._set_size())
        self.size_box.lineEdit().returnPressed.connect(self._set_size)
        fb.addWidget(self.size_box)
        fb.addSeparator()
        for a in (self.a_bold, self.a_italic, self.a_under, self.a_strike):
            fb.addAction(a)
        fb.addAction(self.a_color)
        self.color_btn = fb.widgetForAction(self.a_color)
        hb = QToolButton()
        hb.setText("Highlight")
        hb.setToolTip("Highlight colour")
        hb.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        hm = QMenu(hb)
        self._fill_highlight_menu(hm)
        hb.setMenu(hm)
        fb.addWidget(hb)
        fb.addSeparator()
        for a in (self.a_left, self.a_center, self.a_right, self.a_justify):
            fb.addAction(a)
        fb.addSeparator()
        for a in (self.a_bullets, self.a_numbers, self.a_outdent, self.a_indent):
            fb.addAction(a)
        self.spacing_box = QComboBox()
        self.spacing_box.addItems(["1.0", "1.15", "1.5", "2.0"])
        self.spacing_box.setToolTip("Line spacing")
        self.spacing_box.activated.connect(lambda _i: self.set_line_spacing(float(self.spacing_box.currentText())))
        fb.addWidget(self.spacing_box)
        fb.addSeparator()
        fb.addAction(self.a_table)
        tbtn = QToolButton()
        tbtn.setText("Table ▾")
        tbtn.setToolTip("Rows, columns, merge")
        tbtn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tbtn.setMenu(self.table_menu)
        fb.addWidget(tbtn)
        fb.addAction(self.a_picture)
        fb.addAction(self.a_break)

    # ======================================================== formatting
    def _toggle_bold(self) -> None:
        bold = self.edit.fontWeight() < QFont.Weight.DemiBold.value
        self.edit.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)

    def _toggle_strike(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self.edit.currentCharFormat().fontStrikeOut())
        self.edit.mergeCurrentCharFormat(fmt)

    def _vertical(self, va) -> None:
        cur = self.edit.currentCharFormat().verticalAlignment()
        fmt = QTextCharFormat()
        fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal if cur == va else va)
        self.edit.mergeCurrentCharFormat(fmt)

    def _set_size(self) -> None:
        try:
            size = float(self.size_box.currentText())
        except ValueError:
            return
        if 3 <= size <= 400:
            self.edit.setFontPointSize(size)
            self.edit.setFocus()

    def _set_family(self) -> None:
        name = self.font_box.currentText().strip()
        if not name:
            return
        fmt = QTextCharFormat()
        fmt.setFontFamilies([name])
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def choose_color(self) -> None:
        col = QColorDialog.getColor(self.edit.textColor(), self, "Font colour")
        if col.isValid():
            self.set_text_color(col)

    def set_text_color(self, col: QColor) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(QBrush(col))
        self.edit.mergeCurrentCharFormat(fmt)
        self.color_btn.setStyleSheet(f"QToolButton {{ color: {col.name()}; font-weight: 700; }}")

    def set_highlight(self, col: str | None) -> None:
        fmt = QTextCharFormat()
        if col:
            fmt.setBackground(QBrush(QColor(col)))
            self.edit.mergeCurrentCharFormat(fmt)
        else:
            cur = self.edit.textCursor()
            if not cur.hasSelection():
                cur.select(QTextCursor.SelectionType.WordUnderCursor)
            f = cur.charFormat()
            f.clearBackground()
            cur.setCharFormat(f) if cur.hasSelection() else None

    def clear_formatting(self) -> None:
        cur = self.edit.textCursor()
        if not cur.hasSelection():
            return
        fmt = QTextCharFormat()
        fam, size = base_font(self.doc)
        fmt.setFontFamilies([fam])
        fmt.setFontPointSize(size)
        cur.setCharFormat(fmt)

    def set_alignment(self, al) -> None:
        self.edit.setAlignment(al)

    def set_line_spacing(self, factor: float) -> None:
        cur = self.edit.textCursor()
        bf = QTextBlockFormat()
        bf.setLineHeight(factor * 100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cur.mergeBlockFormat(bf)

    def apply_style(self, name: str) -> None:
        size, bold, colour, level, before, after = STYLES[name]
        cur = self.edit.textCursor()
        cur.beginEditBlock()
        bf = QTextBlockFormat()
        bf.setHeadingLevel(level if name != "Normal" else 0)
        bf.setProperty(docx_io._STYLE_PROP, "Title" if name == "Title" else "")
        bf.setTopMargin(before * PX)
        bf.setBottomMargin(after * PX)
        cur.mergeBlockFormat(bf)
        sel = QTextCursor(cur)
        start, end = sel.selectionStart(), sel.selectionEnd()
        sel.setPosition(start)
        sel.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        sel.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        sel.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cf = QTextCharFormat()
        cf.setFontPointSize(size or base_font(self.doc)[1])
        cf.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        cf.setForeground(QBrush(QColor(colour or "#000000")))
        sel.mergeCharFormat(cf)
        cur.endEditBlock()

    def toggle_list(self, style) -> None:
        cur = self.edit.textCursor()
        cur.beginEditBlock()
        lst = cur.currentList()
        if lst is not None and lst.format().style() == style:
            # take the selected paragraphs out of the list
            start, end = cur.selectionStart(), cur.selectionEnd()
            b = self.doc.findBlock(start)
            while b.isValid() and b.position() <= end:
                if b.textList() is not None:
                    b.textList().remove(b)
                    c = QTextCursor(b)
                    bf = b.blockFormat()
                    bf.setIndent(0)
                    c.setBlockFormat(bf)
                b = b.next()
        elif lst is not None:
            fmt = lst.format()
            fmt.setStyle(style)
            lst.setFormat(fmt)
        else:
            fmt = QTextListFormat()
            fmt.setStyle(style)
            fmt.setIndent(1)
            cur.createList(fmt)
        cur.endEditBlock()
        self._update_paragraph_buttons()

    def change_indent(self, step: int) -> None:
        cur = self.edit.textCursor()
        lst = cur.currentList()
        if lst is not None:
            fmt = QTextListFormat(lst.format())
            new = max(1, min(8, fmt.indent() + step))
            if new == fmt.indent():
                return
            fmt.setIndent(new)
            if fmt.style() not in (QTextListFormat.Style.ListDecimal,):
                fmt.setStyle([QTextListFormat.Style.ListDisc, QTextListFormat.Style.ListCircle,
                              QTextListFormat.Style.ListSquare][(new - 1) % 3])
            cur.createList(fmt)
            return
        bf = QTextBlockFormat()
        cur_left = cur.blockFormat().leftMargin()
        bf.setLeftMargin(max(0.0, cur_left + step * 36 * PX))            # half an inch, like Word
        cur.mergeBlockFormat(bf)

    def paste_plain(self) -> None:
        from PySide6.QtWidgets import QApplication
        self.edit.insertPlainText(QApplication.clipboard().text())

    # ======================================================== insert
    def insert_table_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Insert Table")
        rows, cols = QSpinBox(), QSpinBox()
        rows.setRange(1, 500)
        cols.setRange(1, 30)
        rows.setValue(3)
        cols.setValue(4)
        form = QFormLayout(dlg)
        form.addRow("Rows:", rows)
        form.addRow("Columns:", cols)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.insert_table(rows.value(), cols.value())

    def insert_table(self, rows: int, cols: int):
        tf = QTextTableFormat()
        tf.setCellPadding(4)
        tf.setCellSpacing(0)
        tf.setBorder(1)
        tf.setBorderBrush(QBrush(QColor(0, 0, 0)))
        tf.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        tf.setBorderCollapse(True)
        w, _h, m = page_setup(self.doc)
        col_w = (w - m[0] - m[2]) * PX / cols - 1
        tf.setColumnWidthConstraints([QTextLength(QTextLength.Type.FixedLength, col_w)] * cols)
        table = self.edit.textCursor().insertTable(rows, cols, tf)
        self.edit.setFocus()
        return table

    def _table_op(self, op: str) -> None:
        cur = self.edit.textCursor()
        table = cur.currentTable()
        if table is None:
            self.statusBar().showMessage("Put the cursor in a table first.", 5000)
            return
        cell = table.cellAt(cur)
        r, c = cell.row(), cell.column()
        if op == "row_above":
            table.insertRows(r, 1)
        elif op == "row_below":
            table.insertRows(r + cell.rowSpan(), 1)
        elif op == "col_left":
            table.insertColumns(c, 1)
        elif op == "col_right":
            table.insertColumns(c + cell.columnSpan(), 1)
        elif op == "del_row":
            if table.rows() == 1:
                self._table_op("del_table")
            else:
                table.removeRows(r, 1)
        elif op == "del_col":
            if table.columns() == 1:
                self._table_op("del_table")
            else:
                table.removeColumns(c, 1)
        elif op == "del_table":
            sel = QTextCursor(self.doc)
            sel.setPosition(table.firstPosition() - 1)
            sel.setPosition(table.lastPosition() + 1, QTextCursor.MoveMode.KeepAnchor)
            sel.removeSelectedText()
        elif op == "merge":
            if cur.hasComplexSelection() or cur.hasSelection():
                table.mergeCells(cur)
            else:
                self.statusBar().showMessage("Select the cells to merge first.", 5000)
        elif op == "split":
            if cell.rowSpan() > 1 or cell.columnSpan() > 1:
                table.splitCell(r, c, 1, 1)

    def insert_picture(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Insert Picture", str(self.folder),
                                              "Pictures (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Insert Picture", f"{Path(path).name} could not be read as a picture.")
            return
        self.insert_image(img)

    def insert_image(self, img: QImage) -> None:
        self._images += 1
        name = f"docximg://new{self._images}"
        self.doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), img)
        w, _h, m = page_setup(self.doc)
        max_w = (w - m[0] - m[2]) * PX
        # pictures come in at their 96-dpi size, never wider than the text
        wpx = img.width() * 96 / max(1.0, img.dotsPerMeterX() * 0.0254) if img.dotsPerMeterX() > 0 else img.width()
        hpx = wpx * img.height() / max(1, img.width())
        if wpx > max_w:
            hpx *= max_w / wpx
            wpx = max_w
        fmt = QTextImageFormat()
        fmt.setName(name)
        fmt.setWidth(wpx)
        fmt.setHeight(hpx)
        self.edit.textCursor().insertImage(fmt)

    def _image_at_cursor(self) -> QTextCursor | None:
        """A cursor selecting the picture that is selected or right next to the cursor."""
        cur = self.edit.textCursor()
        spots = [cur.selectionStart()] if cur.hasSelection() else [cur.position() - 1, cur.position()]
        for p in spots:
            if 0 <= p < self.doc.characterCount() - 1 and self.doc.characterAt(p) == "\ufffc":
                c = QTextCursor(self.doc)
                c.setPosition(p)
                c.setPosition(p + 1, QTextCursor.MoveMode.KeepAnchor)
                if c.charFormat().isImageFormat():      # format of the character before position() = the picture
                    return c
        return None

    def picture_size_dialog(self) -> None:
        c = self._image_at_cursor()
        if c is None:
            self.statusBar().showMessage("Click just after (or select) a picture first.", 5000)
            return
        fmt = c.charFormat().toImageFormat()
        dlg = QDialog(self)
        dlg.setWindowTitle("Picture Size")
        pct = QSpinBox()
        pct.setRange(5, 400)
        pct.setSuffix(" %")
        pct.setValue(100)
        form = QFormLayout(dlg)
        form.addRow(QLabel(f"Now {fmt.width() / PX / CM:.1f} x {fmt.height() / PX / CM:.1f} cm"))
        form.addRow("Scale:", pct)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.resize_picture(c, pct.value() / 100)

    def resize_picture(self, c: QTextCursor, factor: float) -> None:
        fmt = c.charFormat().toImageFormat()
        fmt.setWidth(fmt.width() * factor)
        fmt.setHeight(fmt.height() * factor)
        c.setCharFormat(fmt)

    def insert_page_break(self) -> None:
        cur = self.edit.textCursor()
        cur.beginEditBlock()
        cur.insertBlock()
        bf = QTextBlockFormat()
        bf.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        cur.mergeBlockFormat(bf)
        cur.endEditBlock()
        self.edit.setTextCursor(cur)

    # ======================================================== page setup
    def _apply_page_width(self) -> None:
        w, _h, _m = page_setup(self.doc)
        self.edit.setLineWrapColumnOrWidth(int(w * PX))
        self.edit.setMinimumWidth(int(w * PX) + 40)
        self.edit.setMaximumWidth(int(w * PX) + 60)

    def page_setup_dialog(self) -> None:
        w, h, m = page_setup(self.doc)
        dlg = QDialog(self)
        dlg.setWindowTitle("Page Setup")
        size = QComboBox()
        size.addItems(list(PAGE_SIZES) + ["Custom"])
        portrait, landscape = QRadioButton("Portrait"), QRadioButton("Landscape")
        (landscape if w > h else portrait).setChecked(True)
        short, long_ = sorted((w, h))
        match = [k for k, (a, b) in PAGE_SIZES.items() if abs(a - short) < 2 and abs(b - long_) < 2]
        size.setCurrentText(match[0] if match else "Custom")
        boxes = []
        for v in m:
            sb = QDoubleSpinBox()
            sb.setRange(0, 10)
            sb.setDecimals(2)
            sb.setSingleStep(0.25)
            sb.setSuffix(" cm")
            sb.setValue(v / CM)
            boxes.append(sb)
        form = QFormLayout(dlg)
        form.addRow("Paper size:", size)
        ol = QHBoxLayout()
        ol.addWidget(portrait)
        ol.addWidget(landscape)
        form.addRow("Orientation:", ol)
        for label, sb in zip(("Left margin:", "Top margin:", "Right margin:", "Bottom margin:"), boxes):
            form.addRow(label, sb)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if size.currentText() in PAGE_SIZES:
            short, long_ = PAGE_SIZES[size.currentText()]
        nw, nh = (long_, short) if landscape.isChecked() else (short, long_)
        self.set_page(nw, nh, tuple(sb.value() * CM for sb in boxes))

    def set_page(self, w: float, h: float, margins) -> None:
        set_page_setup(self.doc, w, h, margins)
        self._apply_page_width()
        self.doc.setModified(True)
        self._update_pages()

    # ======================================================== status
    def _format_changed(self, fmt: QTextCharFormat) -> None:
        self.a_bold.setChecked(fmt.fontWeight() >= QFont.Weight.DemiBold.value)
        self.a_italic.setChecked(fmt.fontItalic())
        self.a_under.setChecked(fmt.fontUnderline())
        self.a_strike.setChecked(fmt.fontStrikeOut())
        va = fmt.verticalAlignment()
        self.a_super.setChecked(va == QTextCharFormat.VerticalAlignment.AlignSuperScript)
        self.a_sub.setChecked(va == QTextCharFormat.VerticalAlignment.AlignSubScript)
        size = fmt.fontPointSize() or base_font(self.doc)[1]
        if size > 0:
            self.size_box.setEditText(f"{size:g}")
        fam = family_of(fmt, base_font(self.doc)[0])
        if fam:
            self.font_box.setEditText(fam)

    def _update_paragraph_buttons(self) -> None:
        cur = self.edit.textCursor()
        al = cur.blockFormat().alignment()
        if al & Qt.AlignmentFlag.AlignHCenter:
            self.a_center.setChecked(True)
        elif al & Qt.AlignmentFlag.AlignJustify:
            self.a_justify.setChecked(True)
        elif al & Qt.AlignmentFlag.AlignRight:
            self.a_right.setChecked(True)
        else:
            self.a_left.setChecked(True)
        lst = cur.currentList()
        style = lst.format().style() if lst is not None else None
        self.a_bullets.setChecked(style is not None and style in (QTextListFormat.Style.ListDisc,
                                                                  QTextListFormat.Style.ListCircle,
                                                                  QTextListFormat.Style.ListSquare))
        self.a_numbers.setChecked(style == QTextListFormat.Style.ListDecimal)
        bf = cur.blockFormat()
        level = bf.headingLevel()
        name = "Normal"
        if bf.property(docx_io._STYLE_PROP) == "Title":
            name = "Title"
        elif level:
            name = f"Heading {min(level, 3)}"
        self.style_box.setCurrentText(name)
        lh = bf.lineHeight() if bf.lineHeightType() == QTextBlockFormat.LineHeightTypes.ProportionalHeight.value \
            else 100
        i = self.spacing_box.findText(f"{(lh or 100) / 100:.2f}".rstrip("0").rstrip(".")
                                      if lh not in (100, 200) else f"{lh / 100:.1f}")
        if i >= 0:
            self.spacing_box.setCurrentIndex(i)
        self.a_pic_size.setEnabled(True)
        in_table = cur.currentTable() is not None
        for a in (self.a_row_above, self.a_row_below, self.a_col_left, self.a_col_right, self.a_del_row,
                  self.a_del_col, self.a_del_table, self.a_merge, self.a_split):
            a.setEnabled(in_table)

    def _modified_changed(self, modified: bool) -> None:
        if getattr(self, "save_btn", None) is not None:
            if self.word_mode:
                self.save_btn.setStyleSheet(SAVE_STYLE if modified else "")
            else:
                # the Save button stands out as soon as something was changed
                self.a_save.setText("Save changes..." if modified else "Save...")
                self.save_btn.setStyleSheet(SAVE_STYLE if modified or not self.saved_to else "")
        mark = "* " if modified else ""
        if self.word_mode:
            name = self.path.name if self.path else self.base_title
            self.setWindowTitle(f"{mark}{name} - {config.APP_NAME} Word")
            if modified:
                self.status.setText("Changed - press Ctrl+S to save." if self.path else
                                    "New document - press Ctrl+S to save it.")
            else:
                self.status.setText(str(self.path) if self.path else "New document (not saved yet).")
            return
        where = f"saved as {Path(self.saved_to[-1]).name}" if self.saved_to else "temporary document - not saved yet"
        self.setWindowTitle(f"{mark}{self.base_title} - editable document ({where}) - {config.APP_NAME}")
        if modified:
            self.status.setText("Changed. Press Save to keep your changes as Word or PDF - nothing is written "
                                "until you do.")
        elif self.saved_to:
            self.status.setText(f"Saved: {self.saved_to[-1]}")
        else:
            self.status.setText("Temporary document in memory. Edit anything like in Word, then press Save.")

    def _cursor_moved(self) -> None:
        if hasattr(self, "a_left"):
            self._update_paragraph_buttons()
            self._show_page_number()
        if self.source is None:
            return
        page = max(0, self.edit.textCursor().block().userState())
        if page != self._preview_page:
            self._preview_page = page
            self._show_original(page)

    def _schedule_pages(self) -> None:
        self._pages_timer.start()

    def _update_pages(self) -> None:
        """Where each page begins (laid out like the PDF / printout), for the dashed lines and 'Page x of y'."""
        if not hasattr(self, "pages_label"):
            return
        try:
            w, h, m = page_setup(self.doc)
            clone = self.doc.clone()
            set_page_setup(clone, w, h, m)
            set_base_font(clone, *base_font(self.doc))
            layout_at_96dpi(clone)
            clone.setPageSize(QSizeF(w * PX, h * PX))
            lay = clone.documentLayout()
            page_h = h * PX
            starts, last = [], 0
            block = clone.begin()
            while block.isValid():
                br = lay.blockBoundingRect(block)
                tl = block.layout()
                for li in range(max(1, tl.lineCount())):
                    top = br.top() + (tl.lineAt(li).y() if tl.lineCount() else 0)
                    pno = int(top // page_h)
                    if pno > last:
                        starts.append((block.blockNumber(), li, pno))
                        last = pno
                block = block.next()
            self.edit.page_starts = starts
            self.page_count = max(1, clone.pageCount(), last + 1)
        except Exception as exc:  # pragma: no cover
            log.warning("page count failed: %s", exc)
        self.edit.viewport().update()
        self._show_page_number()

    def _show_page_number(self) -> None:
        if not hasattr(self, "pages_label"):
            return
        cur = self.edit.textCursor()
        bno = cur.block().blockNumber()
        li = cur.block().layout().lineForTextPosition(cur.positionInBlock()).lineNumber() \
            if cur.block().layout().lineCount() else 0
        page = 0
        for sb, sl, pno in self.edit.page_starts:
            if (sb, sl) <= (bno, max(0, li)):
                page = pno
        words = len(self.doc.toPlainText().split())
        self.pages_label.setText(f"Page {page + 1} of {self.page_count}   ·   {words:,} words")

    def _show_original(self, page: int) -> None:
        if self.source is None or not (0 <= page < self.source.page_count):
            self.preview.clear()
            return
        try:
            pg = self.source[page]
            want = max(240, self.preview_dock.width() - 40)
            pix = pg.get_pixmap(dpi=int(max(30, min(110, 72 * want / max(1.0, pg.rect.width)))))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_RGBA8888).copy()
            self.preview.setPixmap(QPixmap.fromImage(img))
            self.preview_label.setText(f"Original - page {page + 1} of {self.source.page_count}")
        except Exception as exc:  # pragma: no cover
            log.warning("preview failed: %s", exc)

    # ======================================================== saving
    def _remember(self, path) -> None:
        db = getattr(self.host, "db", None)
        if db is not None:
            try:
                db.add_recent(str(path), 0)
            except Exception:
                pass

    def _ask_path(self, kind: str) -> str | None:
        ext = ".docx" if kind == "word" else ".pdf"
        stem = Path(self.base_title).stem
        if not self.word_mode:
            stem += " - edited"
        start = str(self.folder / f"{stem}{ext}")
        flt = WORD_FILTER if kind == "word" else PDF_FILTER
        path, _ = QFileDialog.getSaveFileName(self, "Save as Word" if kind == "word" else "Save as PDF", start, flt)
        if not path:
            return None
        if not path.lower().endswith(ext):
            path += ext
        return path

    def save(self) -> bool:
        if self.word_mode:
            if self.path is None or self.path.suffix.lower() != ".docx":
                return self.save_as()
            return self._save(str(self.path), docx_io.save_docx, "Word")
        # text of a PDF: ask format, folder, name and what to do with the original PDF; then save
        from app.ui.save_options import SaveOptionsDialog
        stem = Path(self.base_title).stem
        if not stem.lower().endswith("edited"):
            stem += " - edited"
        dlg = SaveOptionsDialog(self.original, stem, ("word", "pdf"), "word", self, "Save the document")
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.choice is None:
            return False
        for target in dlg.choice.targets:
            writer, kind = ((docx_io.save_docx, "Word") if target.suffix.lower() == ".docx"
                            else (pdf_out.save_pdf, "PDF"))
            if not self._save(str(target), writer, kind):
                return False
        if dlg.choice.delete_original and self.original is not None:
            ok, msg = self.retire_original(self.original) if self.retire_original else (False, "not available")
            if ok:
                self.statusBar().showMessage(f"Saved. {self.original.name} was moved to the Recycle Bin.", 10000)
            else:
                QMessageBox.warning(self, "Original PDF", f"The new file(s) were saved, but {self.original.name} "
                                    f"was not deleted:\n{msg}")
        return True

    def save_as(self) -> bool:
        if not self.word_mode:
            return self.save()
        start = str(self.path if self.path else self.folder / f"{Path(self.base_title).stem}.docx")
        path, flt = QFileDialog.getSaveFileName(self, "Save As", start, f"{WORD_FILTER};;{PDF_FILTER}")
        if not path:
            return False
        if flt == PDF_FILTER or path.lower().endswith(".pdf"):
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            return self._save(path, pdf_out.save_pdf, "PDF", export=self.path is not None)
        if not path.lower().endswith(".docx"):
            path += ".docx"
        if self._save(path, docx_io.save_docx, "Word"):
            self.path = Path(path)
            self.folder = self.path.parent
            self.base_title = self.path.name
            self._modified_changed(False)
            return True
        return False

    def export_pdf(self) -> bool:
        path = self._ask_path("pdf")
        if not path:
            return False
        return self._save(path, pdf_out.save_pdf, "PDF", export=self.word_mode)

    def save_word(self) -> bool:
        path = self._ask_path("word")
        return bool(path) and self._save(path, docx_io.save_docx, "Word")

    def save_pdf(self) -> bool:
        path = self._ask_path("pdf")
        return bool(path) and self._save(path, pdf_out.save_pdf, "PDF")

    def _save(self, path: str, writer, kind: str, export: bool = False) -> bool:
        if self.original is not None and Path(path).resolve() == self.original.resolve():
            QMessageBox.warning(self, "Save", "Choose another name - the original PDF is never overwritten.")
            return False
        try:
            writer(self.doc, path)
        except PermissionError:
            QMessageBox.warning(self, "Save", f"{Path(path).name} could not be written. Is it open in another "
                                "program (e.g. Word)? Close it there, or choose another name.")
            return False
        except Exception as exc:
            log.exception("save %s failed", kind)
            QMessageBox.warning(self, "Save", f"The {kind} file could not be saved:\n{exc}")
            return False
        self._remember(path)
        if export:                       # a PDF copy of a Word document: the .docx itself is not saved by this
            self.statusBar().showMessage(f"PDF saved: {path}", 8000)
            return True
        self.saved_to.append(path)
        self.doc.setModified(False)
        self._modified_changed(False)
        self.statusBar().showMessage(f"Saved {path}", 8000)
        return True

    def print_document(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        w, h, _m = page_setup(self.doc)
        printer.setPageLayout(QPageLayout(QPageSize(QSizeF(w, h), QPageSize.Unit.Point),
                                          QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)))
        printer.setFullPage(True)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        clone = self.doc.clone()
        _w, _h, m = page_setup(self.doc)
        set_page_setup(clone, w, h, m)
        set_base_font(clone, *base_font(self.doc))
        clone.print_(printer)

    def closeEvent(self, event) -> None:
        if self.doc.isModified():
            if self.word_mode:
                name = self.path.name if self.path else "this new document"
                text = f"Do you want to save the changes to {name}?"
            else:
                text = "Your changes are not saved yet. Save them before closing?"
            box = QMessageBox(QMessageBox.Icon.Question, "Editable document" if not self.word_mode
                              else config.APP_NAME, text, parent=self)
            b_save = box.addButton("Save..." if not self.word_mode else "Save", QMessageBox.ButtonRole.AcceptRole)
            b_drop = box.addButton("Close without saving" if not self.word_mode else "Don't Save",
                                   QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(b_save)
            box.exec()
            clicked = box.clickedButton()
            if clicked is b_save and not self.save():
                event.ignore()
                return
            if clicked not in (b_save, b_drop):
                event.ignore()
                return
        if self.source is not None:
            try:
                self.source.close()
            except Exception:
                pass
            self.source = None
        event.accept()

    # ======================================================== other windows
    def new_window(self) -> None:
        parent = self.host
        if parent is not None and hasattr(parent, "new_word_document"):
            parent.new_word_document()
        else:
            DocEditorWindow.new_document(parent, self.folder)

    def open_other(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open", str(self.folder),
                                              "Word or PDF (*.docx *.pdf);;Word documents (*.docx);;"
                                              "PDF documents (*.pdf)")
        if not path:
            return
        parent = self.host
        if parent is not None and hasattr(parent, "open_file"):
            parent.open_file(path)
        elif path.lower().endswith(".docx"):
            DocEditorWindow.open_docx(parent, path)

    # ======================================================== find/replace
    def find_replace(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Find and Replace")
        find, repl = QLineEdit(self.edit.textCursor().selectedText()), QLineEdit()
        case = QCheckBox("Match case")
        form = QFormLayout()
        form.addRow("Find:", find)
        form.addRow("Replace with:", repl)
        form.addRow("", case)
        info = QLabel("")
        bb = QDialogButtonBox()
        b_next = bb.addButton("Find Next", QDialogButtonBox.ButtonRole.ActionRole)
        b_one = bb.addButton("Replace", QDialogButtonBox.ButtonRole.ActionRole)
        b_all = bb.addButton("Replace All", QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)

        def flags():
            return QTextDocument.FindFlag.FindCaseSensitively if case.isChecked() else QTextDocument.FindFlag(0)

        def nxt() -> bool:
            if not find.text():
                return False
            if self.edit.find(find.text(), flags()):
                return True
            self.edit.moveCursor(QTextCursor.MoveOperation.Start)
            ok = self.edit.find(find.text(), flags())
            info.setText("" if ok else "Not found.")
            return ok

        def one() -> None:
            c = self.edit.textCursor()
            if c.hasSelection() and (c.selectedText() == find.text() if case.isChecked()
                                     else c.selectedText().lower() == find.text().lower()):
                c.insertText(repl.text())
            nxt()

        def everything() -> None:
            n = self.replace_all(find.text(), repl.text(), case.isChecked())
            info.setText(f"{n} replaced.")

        b_next.clicked.connect(nxt)
        b_one.clicked.connect(one)
        b_all.clicked.connect(everything)
        lay = QVBoxLayout(dlg)
        lay.addLayout(form)
        lay.addWidget(info)
        lay.addWidget(bb)
        dlg.show()

    def replace_all(self, old: str, new: str, match_case: bool = False) -> int:
        if not old:
            return 0
        flags = QTextDocument.FindFlag.FindCaseSensitively if match_case else QTextDocument.FindFlag(0)
        n = 0
        cur = QTextCursor(self.doc)
        cur.beginEditBlock()
        c = self.doc.find(old, 0, flags)
        while not c.isNull():
            if not is_marker(c.block()):
                c.insertText(new)
                n += 1
            c = self.doc.find(old, c, flags)
        cur.endEditBlock()
        return n

    # ======================================================== opening
    @staticmethod
    def open_for(parent, pdf_bytes: bytes, pages: list[int] | None, title: str, folder: Path,
                 password: str | None = None, original: Path | None = None,
                 retire_original=None) -> "DocEditorWindow":
        """Build the editable document from a PDF (bytes of the current state) and show the window."""
        src = fitz.open("pdf", pdf_bytes)
        if src.needs_pass:
            src.authenticate(password or "")
        models = M.build_pages(src, pages)
        win = DocEditorWindow(models, src, title, folder, parent, original, retire_original)
        win.show()
        return win

    @staticmethod
    def open_docx(parent, path) -> "DocEditorWindow":
        """Open a Word document for editing (raises docx_io.DocxError with a readable message)."""
        path = Path(path)
        qd = docx_io.load_docx(path)
        win = DocEditorWindow(None, None, path.name, path.parent, parent, document=qd, path=path)
        win._remember(path)
        win.show()
        return win

    @staticmethod
    def new_document(parent, folder: Path | None = None) -> "DocEditorWindow":
        n = getattr(DocEditorWindow, "_new_count", 0) + 1
        DocEditorWindow._new_count = n
        win = DocEditorWindow(None, None, f"Document{n}", Path(folder or Path.home() / "Documents"), parent,
                              document=docx_io.new_document())
        win.show()
        return win


def scanned_without_text(models: list[M.PageModel]) -> list[int]:
    return [m.index for m in models if not m.has_text]
