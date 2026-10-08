"""Main application window: menus, toolbar, document tabs, status bar."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon, QKeySequence
from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDockWidget, QFileDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressDialog, QSizePolicy, QSpinBox, QStackedWidget, QTabWidget, QToolBar, QWidget,
)

from app import config
from app.database.db import AppDatabase
from app.pdf_viewer.document import PdfDocument
from app.pdf_viewer.printing import print_pages
from app.ui import dialogs, theme
from app.ui.document_tab import DocumentTab
from app.pdf_ocr import engine as ocr_engine
from app.ui.icons import make_icon
from app.pdf_pages import operations as ops
from app.ui.page_dialogs import (
    ExtractDialog, InsertDialog, MergeDialog, MoveDialog, PageRangeDialog, ReplaceDialog, SaveChangesBox,
    SplitDialog,
)
from app.ui.page_organizer import build_context_menu
from app.pdf_annotation import annots
from app.pdf_editor import content
from app.ui.edit_dialogs import (
    ApplyRedactionsDialog, CommentTextDialog, HeaderFooterDialog, RedactTextDialog, StampDialog, TextDialog,
    WatermarkDialog,
)
from app.ui.analysis_ui import AnalysisWindow
from app.ui.page_view import TEXT_TOOLS
from app.ui.edit_text_panel import EditTextPanel
from app.ui.properties_panel import DEFAULT_STYLES, TOOL_NAMES, PropertiesPanel, style_from_json, style_to_json
from app.ui.ocr_ui import (
    OcrDialog, OcrInfoDialog, OcrJobWorker, OcrTextDialog, PageTextWorker, describe_pages, saved_languages,
    saved_quality,
)
from app.ui.page_view import FIT_PAGE, FIT_WIDTH, MODE_CONTINUOUS, MODE_SINGLE, MODE_TWO, TOOL_HAND, TOOL_SELECT
from app.utils.pages import parse_page_range
from app.utils.errors import PasswordRequired, WorkbenchError, WrongPassword, describe, log_exception

log = logging.getLogger("pdfworkbench.window")

PDF_FILTER = "PDF documents (*.pdf);;All files (*)"

# Menus for later phases: shown now so the structure is visible, disabled until built.
FUTURE_TOOLS = ("a later phase", ["Compare documents", "Optimise / compress", "Repair", "Forms",
                                   "Security and passwords", "Digital signatures", "Batch processing"])
FUTURE_MENUS = {
}
FUTURE_ANALYSIS = ("a later phase", ["Extract text and tables", "Bank statement analysis", "Bank format library"])


class MainWindow(QMainWindow):
    def __init__(self, db: AppDatabase):
        super().__init__()
        self.db = db
        self.dark = (db.get_setting("theme", "light") == "dark")
        self.setWindowTitle(config.APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1320, 860)
        self.setMinimumSize(760, 480)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("docTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._make_empty_state())   # index 0: welcome text
        self.stack.addWidget(self.tabs)                  # index 1: documents
        self.setCentralWidget(self.stack)

        self.tool_styles = {k: style_from_json(db.get_setting(f"style_{k}") or "", v)
                            for k, v in DEFAULT_STYLES.items()}
        self.stamp_name = db.get_setting("stamp_name") or "PAID"
        self.stamp_date = (db.get_setting("stamp_date") or "1") == "1"
        self.text_style = content.TextStyle()
        self.props = PropertiesPanel()
        self.props.toolStyleChanged.connect(self._on_tool_style_changed)
        self.props.applyToAnnot.connect(self._apply_annot_props)
        self.props.deleteAnnot.connect(lambda info: self._delete_annot(self.current_tab(), info))
        self.props_dock = QDockWidget("Properties", self)
        self.props_dock.setObjectName("propertiesDock")
        self.props_dock.setWidget(self.props)
        self.props_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.props_dock)
        self.props_dock.hide()

        self.text_panel = EditTextPanel()
        self.text_panel.applyRequested.connect(self._apply_text_panel)
        self.text_dock = QDockWidget("Edit Text", self)
        self.text_dock.setObjectName("editTextDock")
        self.text_dock.setWidget(self.text_panel)
        self.text_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.text_dock.setMinimumWidth(340)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.text_dock)
        self.text_dock.hide()
        self.text_dock.visibilityChanged.connect(self._on_text_dock_visibility)

        self.actions: dict[str, QAction] = {}
        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_statusbar()
        self._apply_theme()
        self._restore_window()
        self._update_ui()

    # ============================================================== building
    def _make_empty_state(self) -> QLabel:
        label = QLabel(
            "<div style='text-align:center'>"
            f"<p style='font-size:20px; font-weight:600'>{config.APP_NAME}</p>"
            "<p>Open a PDF with <b>Ctrl+O</b>, or drag PDF files onto this window.</p>"
            "<p style='color:gray'>Everything is processed on this computer. Nothing is uploaded.</p>"
            "</div>"
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _act(self, key: str, text: str, slot, shortcut=None, icon: str | None = None,
             checkable: bool = False, tip: str | None = None) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        if tip:
            a.setStatusTip(tip)
            a.setToolTip(f"{tip} ({a.shortcut().toString()})" if shortcut else tip)
        if icon:
            a.setData(icon)
        a.triggered.connect(slot)
        self.addAction(a)       # shortcuts work even in full screen without menus
        self.actions[key] = a
        return a

    def _create_actions(self) -> None:
        A = self._act
        S = QKeySequence.StandardKey
        A("open", "&Open...", self.open_dialog, S.Open, "open", tip="Open PDF files")
        A("save", "&Save", self.save, S.Save, "save", tip="Save")
        A("save_as", "Save &As...", self.save_as, "Ctrl+Shift+S", tip="Save a copy under a new name")
        A("print", "&Print...", self.print_document, S.Print, "print", tip="Print")
        A("close", "&Close", lambda: self.close_tab(self.tabs.currentIndex()), S.Close, tip="Close document")
        A("close_all", "Close A&ll", self.close_all, "Ctrl+Shift+W")
        A("properties", "Document P&roperties...", self.show_properties, "Ctrl+D", "info", tip="Document properties")
        A("open_folder", "Show in &Folder", self.open_containing_folder)
        A("quit", "E&xit", self.close, S.Quit)

        A("copy", "&Copy", self.copy_selection, S.Copy, tip="Copy selected text")
        A("select_all", "Select &All Text on Page", self.select_all, S.SelectAll)
        A("find", "&Find...", self.focus_search, S.Find, "search", tip="Find text")
        A("find_next", "Find &Next", self.find_next, "F3")
        A("find_prev", "Find &Previous", self.find_prev, "Shift+F3")

        A("zoom_in", "Zoom &In", lambda: self._view_call("zoom_in"), ["Ctrl++", "Ctrl+="], "zoom_in", tip="Zoom in")
        A("zoom_out", "Zoom &Out", lambda: self._view_call("zoom_out"), "Ctrl+-", "zoom_out", tip="Zoom out")
        A("actual", "&Actual Size", lambda: self._view_call("set_zoom", 1.0), "Ctrl+1")
        A("fit_width", "Fit &Width", lambda: self._view_call("fit_width"), "Ctrl+2", "fit_width", tip="Fit width")
        A("fit_page", "Fit &Page", lambda: self._view_call("fit_page"), "Ctrl+0", "fit_page", tip="Fit page")
        A("rotate_cw", "Rotate View &Clockwise", lambda: self._view_call("rotate", 90), "Ctrl+Shift+=", "rotate_cw", tip="Rotate view clockwise")
        A("rotate_ccw", "Rotate View C&ounter-clockwise", lambda: self._view_call("rotate", -90), "Ctrl+Shift+-", "rotate_ccw", tip="Rotate view counter-clockwise")

        self.mode_group = QActionGroup(self)
        for key, text, mode, icon, sc in (("mode_cont", "&Continuous", MODE_CONTINUOUS, "continuous", "Ctrl+4"),
                                          ("mode_single", "&Single Page", MODE_SINGLE, "single", "Ctrl+5"),
                                          ("mode_two", "&Two Pages", MODE_TWO, "two_page", "Ctrl+6")):
            a = A(key, text, lambda _c=False, m=mode: self._view_call("set_mode", m), sc, icon, True, tip=text.replace("&", ""))
            self.mode_group.addAction(a)
        self.actions["mode_cont"].setChecked(True)

        self.tool_group = QActionGroup(self)
        a = A("tool_select", "&Select Text Tool", lambda: self._set_tool(TOOL_SELECT), "V", "select", True, tip="Select text")
        self.tool_group.addAction(a)
        a.setChecked(True)
        self.tool_group.addAction(A("tool_hand", "&Hand Tool", lambda: self._set_tool(TOOL_HAND), "H", "hand", True, tip="Hand tool (drag to scroll)"))

        A("first", "&First Page", lambda: self._view_call("goto_page", 0), "Ctrl+Home", "first", tip="First page")
        A("prev", "&Previous Page", lambda: self._view_call("prev_page"), None, "prev", tip="Previous page")
        A("next", "&Next Page", lambda: self._view_call("next_page"), None, "next", tip="Next page")
        A("last", "&Last Page", self._goto_last, "Ctrl+End", "last", tip="Last page")
        A("goto", "&Go to Page...", self.goto_dialog, "Ctrl+G")

        A("sidebar", "Side &Panel", self.toggle_sidebar, "F4", "sidebar", True, tip="Show/hide side panel")
        self.actions["sidebar"].setChecked(True)
        A("fullscreen", "F&ull Screen", self.toggle_fullscreen, "F11", "fullscreen", True, tip="Full screen")
        A("exit_fullscreen", "Exit Full Screen", self._exit_fullscreen, "Esc")
        A("dark", "&Dark Mode", self.toggle_dark, "Ctrl+Shift+D", "theme", True, tip="Dark mode")
        self.actions["dark"].setChecked(self.dark)

        # ---- page management (Phase 2)
        A("undo", "&Undo", self.undo, S.Undo, "undo", tip="Undo the last page change")
        A("redo", "&Redo", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"], "redo", tip="Redo")
        A("organize", "&Organise Pages", self.toggle_organizer, "Ctrl+Shift+P", "organize", True,
          tip="Organise pages: drag to reorder, select to rotate, delete, extract")
        A("pg_rotate_cw", "Rotate Pages &Clockwise", lambda: self.rotate_pages(90), "Ctrl+R", "rotate_page",
          tip="Turn the selected pages (or current page) clockwise - saved in the file")
        A("pg_rotate_ccw", "Rotate Pages C&ounter-clockwise", lambda: self.rotate_pages(-90), "Ctrl+L",
          tip="Turn the selected pages (or current page) counter-clockwise")
        A("pg_rotate_180", "Rotate Pages &180\u00b0", lambda: self.rotate_pages(180))
        A("pg_delete", "&Delete Pages...", self.delete_pages, "Ctrl+Del", "delete", tip="Delete pages")
        A("pg_duplicate", "D&uplicate Pages", self.duplicate_pages, tip="Insert a copy after each selected page")
        A("pg_move", "&Move Pages...", self.move_pages, tip="Move pages to another position")
        A("pg_reverse", "Re&verse Page Order", self.reverse_pages)
        A("pg_insert_blank", "Insert &Blank Pages...", lambda: self.insert_pages(False))
        A("pg_insert_file", "&Insert Pages from File...", lambda: self.insert_pages(True), "Ctrl+I", "insert",
          tip="Insert pages from another PDF or image")
        A("pg_replace", "Re&place Pages...", self.replace_pages)
        A("pg_extract", "&Extract Pages...", self.extract_pages, "Ctrl+E", "extract",
          tip="Save selected pages as a new PDF")
        A("pg_split", "&Split Document...", self.split_document, tip="Split into several PDFs")
        A("merge", "Co&mbine Files into One PDF...", self.merge_files, "Ctrl+M", "merge",
          tip="Combine several PDFs and images into one PDF")

        # ---- editing & comment tools (Phase 3)
        tools = [
            ("add_text", "Add &Text", "add_text", "Write new text on the page (any language)"),
            ("edit_text", "&Edit Text", "edit_text", "Click a line of text to change it"),
            ("delete_text", "&Delete Text", "delete_text", "Drag over words to delete them"),
            ("add_image", "Add &Picture", "image", "Place a picture (JPG, PNG...) on the page"),
            ("delete_image", "Delete Pict&ure", None, "Drag over a picture to delete it"),
            ("highlight", "&Highlight", "highlight", "Highlight text"),
            ("underline", "&Underline", "underline", "Underline text"),
            ("strike", "&Strikethrough", "strike", "Strike text through"),
            ("squiggly", "S&quiggly Underline", "squiggly", "Wavy underline"),
            ("note", "Sticky &Note", "note", "Add a sticky note"),
            ("textbox", "Text &Box", "textbox", "Add a typed comment in a box"),
            ("rect", "&Rectangle", "rect", "Draw a rectangle"),
            ("ellipse", "&Ellipse", "ellipse", "Draw an ellipse or circle"),
            ("line", "&Line", "line", "Draw a line"),
            ("arrow", "&Arrow", "arrow", "Draw an arrow"),
            ("pen", "&Pen", "pen", "Draw freehand"),
            ("stamp", "Stam&p...", "stamp", "Stamp: PAID, RECEIVED, VERIFIED, APPROVED..."),
            ("eraser", "Era&ser", "eraser", "Click a comment or shape to delete it"),
            ("redact", "&Redact Area", "redact", "Mark areas for permanent removal"),
        ]
        for key, text, icon, tip in tools:
            a = A(f"tool_{key}", text, lambda _c=False, k=key: self._set_tool(k), None, icon, True, tip=tip)
            self.tool_group.addAction(a)
        A("watermark", "&Watermark...", self.add_watermark, None, "watermark", tip="Add a text or image watermark")
        A("header_footer", "Header && &Footer...", self.add_header_footer, tip="Page numbers, date, file name...")
        A("extract_images", "E&xtract Pictures...", self.extract_images, tip="Save the pictures of the document as files")
        A("redact_text", "Mark &Text for Redaction...", self.redact_text, tip="Find a number or word and mark every occurrence")
        A("apply_redactions", "&Apply Redactions...", self.apply_redactions, None, None,
          tip="Permanently remove everything under the redaction marks")
        A("delete_comments", "Delete All &Comments...", self.delete_all_comments)
        A("flatten_comments", "&Flatten Comments", self.flatten_comments,
          tip="Make comments part of the page so they can no longer be changed")
        A("text_panel", "Edit Text &Panel", self.toggle_text_panel, "Ctrl+Shift+E", "edit_text", True,
          tip="Open a panel listing every line of the page: change or delete lines, then Apply")
        A("props_panel", "P&roperties Panel", self.toggle_props_panel, "F6", "sidebar", True,
          tip="Show/hide the Properties panel")

        A("analyse", "&Analyse Document...", self.analyse_document, "Ctrl+Shift+A", "analysis",
          tip="Analyse the PDF: pages, scanned pages, fonts, forms, signatures, structure")

        A("ocr", "&Make Searchable PDF (OCR)...", self.run_ocr, "Ctrl+Shift+O", "ocr",
          tip="Recognise text in scanned pages (OCR)")
        A("ocr_page", "&Recognise Text on This Page...", self.ocr_current_page, "Ctrl+Shift+R",
          tip="Read the text of the current page with OCR and copy it")
        A("ocr_langs", "OCR &Languages...", lambda: OcrInfoDialog(self).exec())

        A("about", "&About", self.about)
        A("logs", "Open &Log Folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.LOG_DIR))))

    def _create_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for k in ("open",):
            m.addAction(self.actions[k])
        self.recent_menu = m.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        m.addSeparator()
        for k in ("save", "save_as"):
            m.addAction(self.actions[k])
        m.addSeparator()
        m.addAction(self.actions["merge"])
        m.addSeparator()
        m.addAction(self.actions["print"])
        m.addSeparator()
        for k in ("properties", "open_folder"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("close", "close_all", "quit"):
            m.addAction(self.actions[k])

        m = mb.addMenu("&Edit")
        for k in ("undo", "redo"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("copy", "select_all"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("find", "find_next", "find_prev"):
            m.addAction(self.actions[k])
        m.addSeparator()
        m.addAction(self.actions["tool_select"])
        m.addAction(self.actions["tool_hand"])
        m.addSeparator()
        m.addAction(self.actions["text_panel"])
        for k in ("add_text", "edit_text", "delete_text", "add_image", "delete_image"):
            m.addAction(self.actions[f"tool_{k}"])
        m.addAction(self.actions["extract_images"])
        m.addSeparator()
        for k in ("watermark", "header_footer"):
            m.addAction(self.actions[k])

        m = mb.addMenu("&View")
        for k in ("zoom_in", "zoom_out", "actual", "fit_width", "fit_page"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("mode_cont", "mode_single", "mode_two"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("rotate_cw", "rotate_ccw"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("sidebar", "props_panel", "text_panel", "fullscreen", "dark"):
            m.addAction(self.actions[k])

        m = mb.addMenu("&Document")
        for k in ("first", "prev", "next", "last", "goto"):
            m.addAction(self.actions[k])
        m.addSeparator()
        m.addAction(self.actions["properties"])

        m = mb.addMenu("&Pages")
        m.addAction(self.actions["organize"])
        m.addSeparator()
        for k in ("pg_rotate_cw", "pg_rotate_ccw", "pg_rotate_180"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("pg_insert_blank", "pg_insert_file", "pg_replace", "pg_duplicate", "pg_move", "pg_reverse",
                  "pg_delete"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for k in ("pg_extract", "pg_split", "merge"):
            m.addAction(self.actions[k])

        m = mb.addMenu("&Tools")
        cm = m.addMenu("&Comment")
        for k in ("highlight", "underline", "strike", "squiggly", "note", "textbox", "rect", "ellipse", "line",
                  "arrow", "pen", "stamp", "eraser"):
            cm.addAction(self.actions[f"tool_{k}"])
        rm = m.addMenu("&Redact")
        for k in ("tool_redact", "redact_text", "apply_redactions"):
            rm.addAction(self.actions[k])
        m.addSeparator()
        for k in ("delete_comments", "flatten_comments"):
            m.addAction(self.actions[k])
        m.addSeparator()
        for text in FUTURE_TOOLS[1]:
            m.addAction(f"{text}   (coming in {FUTURE_TOOLS[0]})").setEnabled(False)

        for title, (phase, items) in FUTURE_MENUS.items():
            fm = mb.addMenu(title)
            for text in items:
                a = fm.addAction(f"{text}   (coming in {phase})")
                a.setEnabled(False)

        m = mb.addMenu("&Analysis")
        m.addAction(self.actions["analyse"])
        m.addSeparator()
        for text in FUTURE_ANALYSIS[1]:
            m.addAction(f"{text}   (coming in {FUTURE_ANALYSIS[0]})").setEnabled(False)

        m = mb.addMenu("&OCR")
        for k in ("ocr", "ocr_page"):
            m.addAction(self.actions[k])
        m.addSeparator()
        m.addAction(self.actions["ocr_langs"])

        m = mb.addMenu("&Help")
        m.addAction(self.actions["logs"])
        m.addAction(self.actions["about"])

    def _create_toolbar(self) -> None:
        tb = QToolBar("Main toolbar")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(tb)
        self.toolbar = tb
        for k in ("open", "save", "print"):
            tb.addAction(self.actions[k])
        tb.addSeparator()
        for k in ("undo", "redo"):
            tb.addAction(self.actions[k])
        tb.addSeparator()
        for k in ("first", "prev"):
            tb.addAction(self.actions[k])
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setKeyboardTracking(False)
        self.page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.setFixedWidth(64)
        self.page_spin.setToolTip("Current page - type a number and press Enter")
        self.page_spin.valueChanged.connect(lambda v: self._view_call("goto_page", v - 1))
        tb.addWidget(self.page_spin)
        self.page_total = QLabel(" / 0 ")
        tb.addWidget(self.page_total)
        for k in ("next", "last"):
            tb.addAction(self.actions[k])
        tb.addSeparator()
        tb.addAction(self.actions["zoom_out"])
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_combo.addItems(["Fit width", "Fit page"] + [f"{int(z * 100)}%" for z in config.ZOOM_STEPS])
        self.zoom_combo.setFixedWidth(100)
        self.zoom_combo.setToolTip("Zoom")
        self.zoom_combo.activated.connect(lambda _i: self._zoom_from_combo())
        self.zoom_combo.lineEdit().returnPressed.connect(self._zoom_from_combo)
        tb.addWidget(self.zoom_combo)
        tb.addAction(self.actions["zoom_in"])
        for k in ("fit_width", "fit_page"):
            tb.addAction(self.actions[k])
        tb.addSeparator()
        for k in ("mode_cont", "mode_single", "mode_two", "rotate_ccw", "rotate_cw"):
            tb.addAction(self.actions[k])
        tb.addSeparator()
        for k in ("organize", "merge", "ocr", "analyse"):
            tb.addAction(self.actions[k])
        tb.addSeparator()
        for k in ("sidebar", "properties", "dark"):
            tb.addAction(self.actions[k])
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("Search  (Ctrl+F)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.returnPressed.connect(self._search_from_toolbar)
        tb.addWidget(self.search_box)

        # second row: editing and comment tools
        self.addToolBarBreak()
        tb2 = QToolBar("Edit and comment tools")
        tb2.setObjectName("editToolbar")
        tb2.setMovable(False)
        tb2.setIconSize(QSize(20, 20))
        self.addToolBar(tb2)
        self.edit_toolbar = tb2
        groups = [("tool_select", "tool_hand"),
                  ("text_panel", "tool_add_text", "tool_edit_text", "tool_delete_text", "tool_add_image"),
                  ("tool_highlight", "tool_underline", "tool_strike", "tool_note", "tool_textbox",
                   "tool_rect", "tool_ellipse", "tool_line", "tool_arrow", "tool_pen", "tool_stamp", "tool_eraser"),
                  ("tool_redact",), ("watermark",)]
        for g in groups:
            for k in g:
                tb2.addAction(self.actions[k])
            tb2.addSeparator()
        panel_btn = tb2.widgetForAction(self.actions["text_panel"])
        if panel_btn is not None:
            self.actions["text_panel"].setIconText("Edit Text Panel")
            panel_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        apply_btn = tb2.addAction("Apply Redactions", self.apply_redactions)
        apply_btn.setToolTip("Permanently remove everything under the redaction marks")
        self.actions["apply_redactions_tb"] = apply_btn
        tb2.addSeparator()
        tb2.addAction(self.actions["props_panel"])

    def _create_statusbar(self) -> None:
        sb = self.statusBar()
        self.status_page = QLabel()
        self.status_zoom = QLabel()
        self.status_rot = QLabel()
        self.status_doc = QLabel()
        for w in (self.status_doc, self.status_rot, self.status_zoom, self.status_page):
            sb.addPermanentWidget(w)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        theme.apply_theme(app, self.dark)
        color = theme.icon_color(self.dark)
        for a in self.actions.values():
            name = a.data()
            if name:
                a.setIcon(make_icon(name, color))
        icon_file = config.asset_path("app.png")
        self.setWindowIcon(QIcon(str(icon_file)) if icon_file.exists() else make_icon("app", theme.ACCENT))
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, DocumentTab):
                tab.view.set_dark(self.dark)

    # ============================================================== documents
    def current_tab(self) -> DocumentTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    def open_dialog(self) -> None:
        start = self.db.get_setting("last_dir", str(Path.home()))
        files, _ = QFileDialog.getOpenFileNames(self, "Open PDF", start, PDF_FILTER)
        if files:
            self.db.set_setting("last_dir", str(Path(files[0]).parent))
            self.open_files(files)

    def open_files(self, paths) -> None:
        for p in paths:
            self.open_file(p)

    def open_file(self, path: str) -> DocumentTab | None:
        path = os.path.abspath(path)
        # already open? just switch to it
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, DocumentTab) and os.path.normcase(str(tab.doc.path)) == os.path.normcase(path):
                self.tabs.setCurrentIndex(i)
                return tab
        doc = self._load_document(path)
        if doc is None:
            return None
        try:
            tab = DocumentTab(doc)
        except Exception as exc:
            doc.close()
            self._show_error("Open", exc)
            return None
        tab.view.set_dark(self.dark)
        tab.view.currentPageChanged.connect(self._on_page_changed)
        tab.view.zoomChanged.connect(lambda _z: self._update_status())
        tab.view.selectionChanged.connect(self._on_selection)
        tab.statusMessage.connect(lambda msg: self.statusBar().showMessage(msg, 6000))
        tab.banner.ocrRequested.connect(self.run_ocr)
        tab.scannedChecked.connect(lambda _p: self._update_status())
        tab.documentChanged.connect(lambda t=tab: self._on_document_changed(t))
        tab.editFailed.connect(self._on_edit_failed)
        tab.organizerToggled.connect(lambda _on: self._update_ui())
        tab.organizer.contextMenuWanted.connect(
            lambda pos: build_context_menu(self, self.actions, len(tab.organizer.selected_pages())).exec(pos))
        tab.organizer.deletePressed.connect(self.delete_pages)
        tab.organizer.filesDropped.connect(lambda files, before, t=tab: self.insert_dropped_files(t, files, before))
        self._connect_edit_signals(tab)
        current_tool = self.tool_group.checkedAction()
        for key, act in self.actions.items():
            if act is current_tool and key.startswith("tool_"):
                tab.view.set_tool(key[5:])
        tab.set_side_panel_visible(self.actions["sidebar"].isChecked())
        index = self.tabs.addTab(tab, doc.title)
        self.tabs.setTabToolTip(index, str(doc.path))
        self.tabs.setCurrentIndex(index)
        last = self.db.last_page(path)
        self.db.add_recent(path, last)
        if 0 < last < doc.page_count:
            tab.view.goto_page(last)
        self.statusBar().showMessage(f"Opened {doc.title}  ({doc.page_count} pages)", 5000)
        return tab

    def _load_document(self, path: str) -> PdfDocument | None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            try:
                return PdfDocument(path)
            except PasswordRequired:
                pass
            finally:
                QApplication.restoreOverrideCursor()
            retry = False
            while True:
                pw = dialogs.ask_password(self, Path(path).name, retry)
                if pw is None:
                    return None
                try:
                    return PdfDocument(path, pw)
                except WrongPassword:
                    retry = True
        except Exception as exc:
            self._show_error("Open", exc)
            if not Path(path).exists():
                self.db.remove_recent(path)
            return None

    def close_tab(self, index: int) -> bool:
        """Close a tab. Asks about unsaved page changes. Returns False if the user cancelled."""
        if index < 0:
            return True
        tab = self.tabs.widget(index)
        if isinstance(tab, DocumentTab):
            if tab.doc.modified:
                self.tabs.setCurrentIndex(index)
                choice = SaveChangesBox.ask(self, tab.doc.title, closing=True)
                if choice == "cancel":
                    return False
                if choice == "new" and not self.save_as(tab):
                    return False
                if choice == "overwrite" and not self._save_to(tab, str(tab.doc.path)):
                    return False
            self.db.set_last_page(str(tab.doc.path), tab.view.current_page)
            win = getattr(tab, "analysis_window", None)
            if win is not None:
                win.close()
            self.tabs.removeTab(index)
            tab.close_document()
            tab.deleteLater()
        self._update_ui()
        return True

    def close_all(self) -> bool:
        while self.tabs.count():
            if not self.close_tab(0):
                return False
        return True

    def save(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if not tab.doc.modified:
            # nothing changed: offer to save a copy
            self.save_as(tab)
            return
        choice = SaveChangesBox.ask(self, tab.doc.title)
        if choice == "new":
            self.save_as(tab)
        elif choice == "overwrite":
            self._save_to(tab, str(tab.doc.path))

    def save_as(self, tab: DocumentTab | None = None) -> bool:
        tab = tab if isinstance(tab, DocumentTab) else self.current_tab()
        if tab is None:
            return False
        suffix = " - edited" if tab.doc.modified else " - copy"
        suggestion = str(ops.unique_path(tab.doc.path.with_name(tab.doc.path.stem + suffix + ".pdf")))
        target, _ = QFileDialog.getSaveFileName(self, "Save As", suggestion, "PDF documents (*.pdf)")
        if not target:
            return False
        if not target.lower().endswith(".pdf"):
            target += ".pdf"
        return self._save_to(tab, target)

    def _save_to(self, tab: DocumentTab, target: str) -> bool:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            tab.doc.save_as(target)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._show_error("Save", exc)
            return False
        QApplication.restoreOverrideCursor()
        self.db.add_recent(str(tab.doc.path), tab.view.current_page)
        self._update_tab_title(tab)
        self._update_ui()
        self.statusBar().showMessage(f"Saved {target}", 6000)
        return True

    def _update_tab_title(self, tab: DocumentTab) -> None:
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.setTabText(index, ("* " if tab.doc.modified else "") + tab.doc.title)
            self.tabs.setTabToolTip(index, str(tab.doc.path) + ("  (unsaved changes)" if tab.doc.modified else ""))

    # ======================================================== page management
    def _on_document_changed(self, tab: DocumentTab) -> None:
        self._update_tab_title(tab)
        if self._text_panel_open() and tab is self.text_panel.tab and self.text_panel.discard_ok():
            self.text_panel.show_page(tab, tab.view.current_page, force=True)
        if tab is self.current_tab():
            self._update_ui()

    def _on_edit_failed(self, label: str, message: str) -> None:
        QMessageBox.warning(self, label, message)

    def toggle_organizer(self) -> None:
        tab = self.current_tab()
        if tab is None:
            self.actions["organize"].setChecked(False)
            return
        tab.show_organizer(not tab.organizer_visible)
        self._update_ui()

    def undo(self) -> None:
        tab = self.current_tab()
        if tab is None or isinstance(QApplication.focusWidget(), QLineEdit):
            focus = QApplication.focusWidget()
            if isinstance(focus, QLineEdit):
                focus.undo()
            return
        label = tab.undo()
        self.statusBar().showMessage(f"Undone: {label}" if label else "Nothing to undo", 4000)

    def redo(self) -> None:
        tab = self.current_tab()
        if tab is None or isinstance(QApplication.focusWidget(), QLineEdit):
            focus = QApplication.focusWidget()
            if isinstance(focus, QLineEdit):
                focus.redo()
            return
        label = tab.redo()
        self.statusBar().showMessage(f"Redone: {label}" if label else "Nothing to redo", 4000)

    @staticmethod
    def _count(pages: list[int]) -> str:
        return f"{len(pages)} page{'s' if len(pages) != 1 else ''}"

    def rotate_pages(self, degrees: int) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        pages = tab.target_pages()
        word = {90: "clockwise", -90: "counter-clockwise", 180: "180\u00b0"}[degrees]
        tab.run_edit(f"Rotate {self._count(pages)} {word}", lambda d: ops.rotate_pages(d, pages, degrees),
                     select=pages, show_page=pages[0])

    def delete_pages(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        pages = tab.target_pages()
        if not tab.organizer_visible:
            dlg = PageRangeDialog("Delete pages", "Pages to delete:", tab.doc.page_count, pages, "Delete", self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            pages = dlg.pages
        first = pages[0]
        tab.run_edit(f"Delete {self._count(pages)} ({describe_pages(pages)})",
                     lambda d: ops.delete_pages(d, pages), select=[min(first, tab.doc.page_count - len(pages))],
                     show_page=first)

    def duplicate_pages(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        pages = tab.target_pages()
        tab.run_edit(f"Duplicate {self._count(pages)}", lambda d: ops.duplicate_pages(d, pages),
                     select=lambda new: new)

    def move_pages(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        dlg = MoveDialog(tab.doc.page_count, tab.target_pages(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pages, before = dlg.pages, dlg.position.insert_before()
        tab.run_edit(f"Move {self._count(pages)}", lambda d: ops.move_pages(d, pages, before),
                     select=lambda new: new)

    def reverse_pages(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        sel = tab.target_pages() if tab.organizer_visible and len(tab.target_pages()) > 1 else None
        label = f"Reverse {self._count(sel)}" if sel else "Reverse page order"
        tab.run_edit(label, lambda d: ops.reverse_pages(d, sel), select=sel)

    def _open_source(self, path: str):
        """Open a PDF/image to take pages from, asking for a password if needed. None = cancelled."""
        opened = self._open_source_pw(path)
        return opened[0] if opened else None

    def _open_source_pw(self, path: str):
        """Like _open_source, but returns (document, password used) or None."""
        if ops.needs_password(path):
            # first try the passwords of documents that are already open
            for i in range(self.tabs.count()):
                t = self.tabs.widget(i)
                if isinstance(t, DocumentTab) and t.doc.password:
                    try:
                        return ops.open_source(path, t.doc.password), t.doc.password
                    except ops.PageOpError:
                        pass
            retry = False
            while True:
                password = dialogs.ask_password(self, Path(path).name, retry)
                if password is None:
                    return None
                try:
                    return ops.open_source(path, password), password
                except ops.PageOpError:
                    retry = True
        try:
            return ops.open_source(path), None
        except ops.PageOpError as exc:
            QMessageBox.warning(self, "Open file", str(exc))
            return None

    def insert_pages(self, from_file: bool) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        cur = tab.target_pages()[-1]
        start = self.db.get_setting("last_dir", str(tab.doc.path.parent))
        dlg = InsertDialog(tab.doc.page_count, cur, tab.doc.page_size(cur), start, from_file, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        at = dlg.position.insert_before()
        if dlg.blank:
            count, size = dlg.count.value(), dlg.blank_size()
            tab.run_edit(f"Insert {count} blank page{'s' if count > 1 else ''}",
                         lambda d: ops.insert_blank_pages(d, at, count, size), select=lambda new: new)
            return
        path = dlg.file_edit.text().strip()
        self.db.set_setting("last_dir", str(Path(path).parent))
        src = self._open_source(path)
        if src is None:
            return
        try:
            src_pages = None
            if dlg.file_pages.text().strip():
                try:
                    src_pages = parse_page_range(dlg.file_pages.text(), src.page_count, keep_order=True)
                except ValueError as exc:
                    QMessageBox.warning(self, "Insert pages", f"{Path(path).name}: {exc}")
                    return
            n = src.page_count if src_pages is None else len(src_pages)
            tab.run_edit(f"Insert {n} page{'s' if n != 1 else ''} from {Path(path).name}",
                         lambda d: ops.insert_document(d, src, at, src_pages), select=lambda new: new)
        finally:
            src.close()

    def insert_dropped_files(self, tab: DocumentTab, files: list[str], before: int) -> None:
        sources = []
        try:
            for f in files:
                src = self._open_source(f)
                if src is None:
                    return
                sources.append((f, src))

            def do(d):
                pos, new = before, []
                for _f, src in sources:
                    new += ops.insert_document(d, src, pos)
                    pos += src.page_count
                return new

            names = ", ".join(Path(f).name for f, _ in sources)
            tab.run_edit(f"Insert {names}", do, select=lambda new: new)
        finally:
            for _f, src in sources:
                src.close()

    def replace_pages(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        start = self.db.get_setting("last_dir", str(tab.doc.path.parent))
        dlg = ReplaceDialog(tab.doc.page_count, tab.target_pages(), start, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path = dlg.file_edit.text().strip()
        src = self._open_source(path)
        if src is None:
            return
        try:
            src_pages = None
            if dlg.src_pages.text().strip():
                try:
                    src_pages = parse_page_range(dlg.src_pages.text(), src.page_count, keep_order=True)
                except ValueError as exc:
                    QMessageBox.warning(self, "Replace pages", f"{Path(path).name}: {exc}")
                    return
            pages = dlg.pages
            tab.run_edit(f"Replace {self._count(pages)} with pages from {Path(path).name}",
                         lambda d: ops.replace_pages(d, pages, src, src_pages), select=lambda new: new)
        finally:
            src.close()

    def extract_pages(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        dlg = ExtractDialog(tab.doc.page_count, tab.target_pages(), tab.doc.path, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pages, out, password = dlg.pages, dlg.output.text().strip(), tab.doc.password
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if dlg.separate.isChecked():
                parts = [ops.SplitPart(f"p{p + 1}", [p]) for p in pages]
                files = tab.doc.run_read(lambda d: ops.split_to_files(d, parts, out, tab.doc.path.stem, password))
                result_text = f"Saved {len(files)} PDF files in\n{out}"
            else:
                path = tab.doc.run_read(lambda d: ops.extract_to_file(d, pages, out, password))
                files = [path]
                result_text = f"Saved {self._count(pages)} to\n{path}"
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._show_error("Extract pages", exc)
            return
        QApplication.restoreOverrideCursor()
        if password:
            result_text += "\n\nThe new file is protected with the same password as this document."
        if dlg.delete_after.isChecked():
            tab.run_edit(f"Delete {self._count(pages)} (extracted)", lambda d: ops.delete_pages(d, pages),
                         select=[min(pages[0], tab.doc.page_count - len(pages))])
        self.statusBar().showMessage(result_text.replace("\n", " "), 8000)
        if dlg.separate.isChecked():
            QMessageBox.information(self, "Extract pages", result_text)
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))
        elif dlg.open_after.isChecked():
            self.open_file(str(files[0]))
        else:
            QMessageBox.information(self, "Extract pages", result_text)

    def split_document(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        has_bm = any(level == 1 for level, _t, _p in tab.doc.outline())
        dlg = SplitDialog(tab.doc.page_count, has_bm, tab.doc.path, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mode, value = dlg.mode()
        folder, stem, password = dlg.folder.text().strip(), dlg.stem.text().strip(), tab.doc.password
        try:
            parts = tab.doc.run_read(lambda d: ops.split_plan(d, mode, value))
        except ops.PageOpError as exc:
            QMessageBox.warning(self, "Split", str(exc))
            return
        if len(parts) > 50 and QMessageBox.question(
                self, "Split", f"This will create {len(parts)} files. Continue?") != QMessageBox.StandardButton.Yes:
            return
        progress = QProgressDialog("Splitting...", "Cancel", 0, len(parts), self)
        progress.setWindowTitle("Split PDF")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(400)

        def step(done: int, total: int) -> bool:
            progress.setValue(done)
            progress.setLabelText(f"Writing file {done + 1} of {total}")
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            files = tab.doc.run_read(lambda d: ops.split_to_files(d, parts, folder, stem, password, step))
        except Exception as exc:
            progress.close()
            self._show_error("Split", exc)
            return
        progress.close()
        msg = f"Created {len(files)} PDF file{'s' if len(files) != 1 else ''} in\n{folder}"
        if tab.doc.modified:
            msg += "\n\n(Your unsaved page changes are included in the split files.)"
        QMessageBox.information(self, "Split PDF", msg)
        if dlg.open_folder.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def merge_files(self) -> None:
        tab = self.current_tab()
        initial = [str(tab.doc.path)] if tab is not None else []
        start = self.db.get_setting("last_dir", str(Path.home()))
        dlg = MergeDialog(start, initial, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        files, out = dlg.files(), dlg.output.text().strip()
        # unsaved changes in an open document are not in its file on disk
        modified_open = [f for f in files for i in range(self.tabs.count())
                         if isinstance(self.tabs.widget(i), DocumentTab)
                         and self.tabs.widget(i).doc.modified
                         and os.path.normcase(str(self.tabs.widget(i).doc.path)) == os.path.normcase(f)]
        if modified_open and QMessageBox.question(
                self, "Combine", "Some of these files have unsaved page changes, which will NOT be included "
                "(the saved version on disk is used). Continue?") != QMessageBox.StandardButton.Yes:
            return
        sources = []
        for f in files:
            opened = self._open_source_pw(f)     # checks each file and asks for passwords
            if opened is None:
                return
            opened[0].close()
            sources.append(ops.MergeSource(f, opened[1]))
        progress = QProgressDialog("Combining...", "Cancel", 0, len(sources), self)
        progress.setWindowTitle("Combine files")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(400)

        def step(done: int, total: int) -> bool:
            progress.setValue(done)
            progress.setLabelText(f"Adding file {done + 1} of {total}")
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            result = ops.merge_files(sources, out, dlg.bookmarks.isChecked(), step)
        except Exception as exc:
            progress.close()
            self._show_error("Combine files", exc)
            return
        progress.close()
        self.statusBar().showMessage(f"Combined {len(sources)} files into {result}", 8000)
        if dlg.open_after.isChecked():
            self.open_file(str(result))
        else:
            QMessageBox.information(self, "Combine files", f"Saved:\n{result}")

    # ================================================================ printing
    def print_document(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        n = tab.doc.page_count
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(tab.doc.title)
        printer.setFromTo(1, n)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle(f"Print - {tab.doc.title}")
        dlg.setMinMax(1, n)
        dlg.setOption(QAbstractPrintDialog.PrintDialogOption.PrintPageRange, True)
        dlg.setOption(QAbstractPrintDialog.PrintDialogOption.PrintCurrentPage, True)
        dlg.setOption(QAbstractPrintDialog.PrintDialogOption.PrintCollateCopies, True)
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return
        pages = self._pages_to_print(printer, dlg, tab)
        if not pages:
            return
        progress = QProgressDialog("Preparing pages...", "Cancel", 0, len(pages), self)
        progress.setWindowTitle("Printing")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)

        def step(done: int, total: int) -> bool:
            progress.setMaximum(total)
            progress.setValue(done)
            progress.setLabelText(f"Printing page {done + 1} of {total}")
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            count = print_pages(tab.doc, printer, pages, progress=step)
            self.statusBar().showMessage(f"Sent {count} page(s) to the printer.", 6000)
        except Exception as exc:
            self._show_error("Print", exc)
        finally:
            progress.close()

    def _pages_to_print(self, printer: QPrinter, dlg: QPrintDialog, tab: DocumentTab) -> list[int]:
        n = tab.doc.page_count
        rng = dlg.printRange()
        if rng == QAbstractPrintDialog.PrintRange.CurrentPage:
            return [tab.view.current_page]
        if rng == QAbstractPrintDialog.PrintRange.PageRange:
            pages: list[int] = []
            try:
                for r in printer.pageRanges().toRangeList():
                    pages.extend(range(r.from_ - 1, min(n, r.to)))
            except Exception:
                pages = []
            if not pages:
                a, b = printer.fromPage(), printer.toPage()
                if a and b:
                    pages = list(range(a - 1, min(n, b)))
            return [p for p in pages if 0 <= p < n] or list(range(n))
        return list(range(n))

    # ===================================================================== OCR
    def _ocr_ready(self, languages: list[str] | None = None) -> bool:
        try:
            ocr_engine.check_ready(languages or ["eng"])
            return True
        except ocr_engine.OcrUnavailable as exc:
            QMessageBox.warning(self, "OCR not available", str(exc))
            return False

    def _ocr_needs_saved(self, tab: DocumentTab) -> bool:
        if tab.doc.modified:
            QMessageBox.information(self, "OCR", "This document has unsaved page changes. OCR works on the saved "
                                    "file, so please save first (File > Save).")
            return True
        return False

    def run_ocr(self) -> None:
        tab = self.current_tab()
        if tab is None or not self._ocr_ready() or self._ocr_needs_saved(tab):
            return
        if getattr(self, "_ocr_job", None) is not None:
            QMessageBox.information(self, "OCR", "An OCR job is already running. Please wait for it to finish.")
            return
        dlg = OcrDialog(tab.doc, tab.view.current_page, tab.scanned_pages, self.db, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if not self._ocr_ready(dlg.languages):
            return
        job = OcrJobWorker(str(tab.doc.path), tab.doc.password, dlg.output, dlg.languages, dlg.dpi,
                           dlg.selected_pages(), self)
        progress = QProgressDialog("Starting OCR...", "Cancel", 0, 0, self)
        progress.setWindowTitle(f"OCR - {tab.doc.title}")
        progress.setWindowModality(Qt.WindowModality.NonModal)   # keep reading other pages meanwhile
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumWidth(420)
        progress.canceled.connect(job.cancel)
        progress.canceled.connect(lambda: progress.setLabelText("Cancelling... finishing the current pages"))

        def on_progress(done: int, total: int, msg: str) -> None:
            progress.setMaximum(max(total, 1))
            progress.setValue(done)
            progress.setLabelText(msg)
            self.statusBar().showMessage(f"OCR: {msg}")

        def finish() -> None:
            progress.close()
            self._ocr_job = None
            job.deleteLater()

        def on_done(result) -> None:
            finish()
            self._ocr_finished(result, dlg.open_after.isChecked())

        def on_failed(message: str) -> None:
            finish()
            self.statusBar().clearMessage()
            QMessageBox.warning(self, "OCR failed", f"OCR could not be completed:\n{message}\n\n"
                                "The original PDF was not changed. Details are in the log.")

        job.progress.connect(on_progress)
        job.done.connect(on_done)
        job.failed.connect(on_failed)
        self._ocr_job = job
        job.start()
        progress.show()

    def _ocr_finished(self, result, open_after: bool) -> None:
        self.statusBar().clearMessage()
        if result.cancelled:
            QMessageBox.information(self, "OCR cancelled", "OCR was cancelled. No file was written.")
            return
        if result.output is None:
            return
        mins, secs = divmod(int(result.seconds), 60)
        took = f"{mins} min {secs} s" if mins else f"{secs} s"
        lines = [f"Saved: {result.output}",
                 f"Recognised {len(result.pages_done)} page(s), {result.words:,} words, in {took}."]
        if result.pages_skipped:
            lines.append(f"Skipped {len(result.pages_skipped)} page(s) that already had text.")
        if not result.pages_done and not result.pages_failed:
            lines.append("No scanned pages were found in the selection, so the copy is identical to the original.")
        icon = QMessageBox.Icon.Information
        if result.pages_failed:
            icon = QMessageBox.Icon.Warning
            lines.append(f"Could not recognise page(s) {describe_pages(sorted(result.pages_failed))}; "
                         "they are kept unchanged. See the log for details.")
        box = QMessageBox(icon, "OCR complete", "\n".join(lines), parent=self)
        box.exec()
        if open_after:
            tab = self.open_file(str(result.output))
            if tab is not None:
                tab.view.goto_page(result.pages_done[0] if result.pages_done else 0)

    def ocr_current_page(self) -> None:
        tab = self.current_tab()
        if tab is None or self._ocr_needs_saved(tab):
            return
        langs = saved_languages(self.db)
        if not self._ocr_ready(langs):
            return
        index = tab.view.current_page
        dpi = ocr_engine.QUALITY_DPI[saved_quality(self.db)]
        worker = PageTextWorker(str(tab.doc.path), tab.doc.password, index, langs, dpi, self)
        names = " + ".join(ocr_engine.language_label(l) for l in langs)
        self.statusBar().showMessage(f"Recognising page {index + 1} ({names})... "
                                     "Change languages in OCR > Make Searchable PDF.")
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)

        def done(page) -> None:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
            worker.deleteLater()
            if page.error:
                QMessageBox.warning(self, "OCR", f"Page {index + 1} could not be recognised:\n{page.error}")
                return
            OcrTextDialog(page, tab.doc.title, langs, self).exec()

        def failed(message: str) -> None:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
            worker.deleteLater()
            QMessageBox.warning(self, "OCR", f"OCR failed:\n{message}")

        worker.done.connect(done)
        worker.failed.connect(failed)
        worker.start()

    # ================================================================ commands
    def _view_call(self, method: str, *args) -> None:
        tab = self.current_tab()
        if tab is not None:
            getattr(tab.view, method)(*args)
            self._update_status()

    def _goto_last(self) -> None:
        tab = self.current_tab()
        if tab:
            tab.view.goto_page(tab.doc.page_count - 1)

    def goto_dialog(self) -> None:
        tab = self.current_tab()
        if tab:
            page = dialogs.ask_page(self, tab.view.current_page, tab.doc.page_count)
            if page is not None:
                tab.view.goto_page(page)

    def _set_tool(self, tool: str) -> None:
        if tool == "stamp":
            dlg = StampDialog(self.stamp_name, self.stamp_date, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._set_tool(TOOL_SELECT)
                return
            self.stamp_name, self.stamp_date = dlg.stamp, dlg.with_date.isChecked()
            self.db.set_setting("stamp_name", self.stamp_name)
            self.db.set_setting("stamp_date", "1" if self.stamp_date else "0")
        tab = self.current_tab()
        if tab is not None and tab.organizer_visible and tool not in (TOOL_SELECT, TOOL_HAND):
            tab.show_organizer(False)
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, DocumentTab):
                t.view.set_tool(tool)
        self._sync_tool_ui(tool)
        if tool not in (TOOL_SELECT, TOOL_HAND) and not self.props_dock.isVisible():
            self.props_dock.show()
            self.actions["props_panel"].setChecked(True)

    def _sync_tool_ui(self, tool: str) -> None:
        action = self.actions.get(f"tool_{tool}")
        if action is not None and not action.isChecked():
            action.setChecked(True)
        style = self.tool_styles.get(tool)
        self.props.set_tool_style(style)
        tab = self.current_tab()
        if tool == TOOL_SELECT and tab is not None and tab.view.selected_annot is not None:
            self.props.show_annot(tab.view.selected_annot)
        else:
            self.props.show_tool(tool, style)
        name = TOOL_NAMES.get(tool, tool)
        if tool not in (TOOL_SELECT, TOOL_HAND):
            self.statusBar().showMessage(f"{name} tool - Esc returns to Select", 5000)

    def _on_view_tool_changed(self, tool: str) -> None:
        # e.g. Esc in the page switched back to Select: apply to every tab
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, DocumentTab) and t.view.tool != tool:
                t.view.set_tool(tool)
        self._sync_tool_ui(tool)

    # ------------------------------------------------------- Edit Text panel
    def toggle_text_panel(self) -> None:
        on = self.actions["text_panel"].isChecked()
        tab = self.current_tab()
        if on:
            if tab is None:
                self.actions["text_panel"].setChecked(False)
                self.statusBar().showMessage("Open a PDF first.", 4000)
                return
            if tab.organizer_visible:
                tab.show_organizer(False)
            self.text_dock.show()
            self._set_tool("edit_text")
            self.props_dock.hide()                    # make room: the panel has its own help text
            self.actions["props_panel"].setChecked(False)
            self.text_panel.show_page(tab, tab.view.current_page, force=True)
        else:
            if not self.text_panel.discard_ok():
                ans = QMessageBox.question(self, "Edit Text", f"{self.text_panel.pending_count()} line(s) were "
                                           "changed but not applied. Close the panel and forget them?")
                if ans != QMessageBox.StandardButton.Yes:
                    self.actions["text_panel"].setChecked(True)
                    return
            self.text_dock.hide()

    def _on_text_dock_visibility(self, visible: bool) -> None:
        if self.actions["text_panel"].isChecked() != visible and not visible and self.isVisible():
            # closed with the dock's own X button
            self.actions["text_panel"].setChecked(False)
        if not visible:
            self.text_panel.show_page(None, -1)
            tab = self.current_tab()
            if tab is not None and tab.view.tool == "edit_text":
                self._set_tool(TOOL_SELECT)

    def _text_panel_open(self) -> bool:
        return self.text_dock.isVisible()

    def _apply_text_panel(self, page: int, changes: list) -> None:
        tab = self.text_panel.tab
        if tab is None:
            return
        deleted = sum(1 for _, t in changes if not t.strip())
        n = len(changes)
        label = (f"Delete {n} line{'s' if n > 1 else ''}" if deleted == n else
                 f"Rewrite {n} line{'s' if n > 1 else ''}" if deleted == 0 else f"Edit {n} lines")
        result = tab.run_edit(label, lambda d: content.replace_lines(d[page], changes))
        if result is not None:
            self.text_panel.show_page(tab, page, force=True)
            self.statusBar().showMessage(f"{label} - Ctrl+Z to undo. Save to keep the change.", 6000)

    def toggle_props_panel(self) -> None:
        self.props_dock.setVisible(self.actions["props_panel"].isChecked())

    def _on_tool_style_changed(self, tool: str, style) -> None:
        self.tool_styles[tool] = style
        self.db.set_setting(f"style_{tool}", style_to_json(style))

    # ============================================================ editing
    def _style(self, tool: str) -> annots.AnnotStyle:
        return self.tool_styles.get(tool) or annots.AnnotStyle()

    def _box(self, tab: DocumentTab, page: int, rect, width: float, height: float):
        """`rect` if it was dragged; for a simple click, a width x height box (as seen on screen)
        starting at the click point, kept inside the page."""
        import pymupdf as fitz
        if rect.width >= 6 and rect.height >= 6:
            return rect

        def make(d):
            pg = d[page]
            v = fitz.Point(rect.x0, rect.y0) * pg.rotation_matrix
            view = pg.rect
            x0 = min(max(view.x0 + 4, v.x), view.x1 - width - 4)
            y0 = min(max(view.y0 + 4, v.y), view.y1 - height - 4)
            r = fitz.Rect(x0, y0, x0 + width, y0 + height) * pg.derotation_matrix
            r.normalize()
            return r
        return tab.doc.run_read(make)

    def _one_shot_done(self, tab: DocumentTab, page: int, xref) -> None:
        """After placing a note, text box, stamp, text or picture: back to Select, new item selected."""
        self._set_tool(TOOL_SELECT)
        if isinstance(xref, int) and xref > 0:
            tab.view.reselect(page, xref)

    def _connect_edit_signals(self, tab: DocumentTab) -> None:
        v = tab.view
        v.markupRequested.connect(lambda tool, page, rects, t=tab: self._on_markup(t, tool, page, rects))
        v.areaRequested.connect(lambda tool, page, rect, t=tab: self._on_area(t, tool, page, rect))
        v.lineRequested.connect(lambda tool, page, a, b, t=tab: self._on_line(t, tool, page, a, b))
        v.inkRequested.connect(lambda page, strokes, t=tab: self._on_ink(t, page, strokes))
        v.pointRequested.connect(lambda tool, page, pt, t=tab: self._on_point(t, tool, page, pt))
        v.annotSelected.connect(lambda info, t=tab: t is self.current_tab() and self._on_annot_selected(info))
        v.annotMoveRequested.connect(lambda page, xref, dx, dy, t=tab: self._move_annot(t, page, xref, dx, dy))
        v.annotResizeRequested.connect(lambda page, xref, r, t=tab: self._resize_annot(t, page, xref, r))
        v.annotEditRequested.connect(lambda info, t=tab: self._edit_annot_text(t, info))
        v.annotDeleteRequested.connect(lambda info, t=tab: self._delete_annot(t, info))
        v.toolChanged.connect(self._on_view_tool_changed)
        tab.comments.activated.connect(lambda page, xref, t=tab: (t.view.goto_page(page), t.view.reselect(page, xref)))

    def _on_annot_selected(self, info) -> None:
        if info is not None:
            if not self.props_dock.isVisible():
                self.props_dock.show()
                self.actions["props_panel"].setChecked(True)
            self.props.show_annot(info)
        else:
            self.props.show_tool(self.current_tab().view.tool if self.current_tab() else TOOL_SELECT,
                                 self.tool_styles.get(self.current_tab().view.tool) if self.current_tab() else None)

    def _on_markup(self, tab, tool, page, rects) -> None:
        kind = TEXT_TOOLS[tool]
        style = self._style(tool)
        tab.run_edit(TOOL_NAMES[tool], lambda d: annots.add_text_markup(d[page], kind, rects, style))

    def _on_area(self, tab, tool, page, rect) -> None:  # noqa: C901
        style = self._style(tool)
        tiny = rect.width < 6 and rect.height < 6
        if tool in ("rect", "ellipse"):
            if tiny:
                return
            kind = "Square" if tool == "rect" else "Circle"
            tab.run_edit(TOOL_NAMES[tool], lambda d: annots.add_shape(d[page], kind, rect, style))
        elif tool == "redact":
            if tiny:
                return
            tab.run_edit("Mark for redaction", lambda d: annots.mark_redaction(d[page], rect, style.fill or (0, 0, 0)))
            self.statusBar().showMessage("Area marked (red box). Tools > Redact > Apply Redactions removes it "
                                         "permanently.", 8000)
        elif tool == "textbox":
            box = self._box(tab, page, rect, 200, 50)
            dlg = CommentTextDialog("Text box", "", self)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.text:
                return
            xref = tab.run_edit("Add text box", lambda d: annots.add_text_box(d[page], box, dlg.text, style))
            self._one_shot_done(tab, page, xref)
        elif tool == "add_text":
            box = self._box(tab, page, rect, 300, 60)
            dlg = TextDialog("Add text", "", self.text_style, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.text.strip():
                return
            self.text_style = dlg.style()
            text, st = dlg.text, dlg.style()
            tab.run_edit("Add text", lambda d: content.add_text(d[page], box, text, st))
            self._set_tool(TOOL_SELECT)
        elif tool == "add_image":
            start = self.db.get_setting("last_image_dir", str(Path.home()))
            path, _ = QFileDialog.getOpenFileName(self, "Choose a picture", start,
                                                  "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)")
            if not path:
                return
            self.db.set_setting("last_image_dir", str(Path(path).parent))
            box = self._box(tab, page, rect, 160, 160)
            tab.run_edit("Add picture", lambda d: content.add_image(d[page], box, path))
            self._set_tool(TOOL_SELECT)
        elif tool == "delete_text":
            if tiny:
                return
            tab.run_edit("Delete text", lambda d: content.delete_text_in(d[page], rect))
        elif tool == "delete_image":
            import pymupdf as fitz
            target = rect if not tiny else fitz.Rect(rect.x0 - 1, rect.y0 - 1, rect.x0 + 1, rect.y0 + 1)
            tab.run_edit("Delete picture", lambda d: content.delete_images_in(d[page], target))

    def _on_line(self, tab, tool, page, a, b) -> None:
        style = self._style(tool)
        tab.run_edit(TOOL_NAMES[tool], lambda d: annots.add_line(d[page], a, b, style, arrow=tool == "arrow"))

    def _on_ink(self, tab, page, strokes) -> None:
        style = self._style("pen")
        tab.run_edit("Pen drawing", lambda d: annots.add_ink(d[page], strokes, style))

    def _on_point(self, tab, tool, page, pt) -> None:
        import pymupdf as fitz
        if tool == "note":
            dlg = CommentTextDialog("Sticky note", "", self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            style = self._style("note")
            xref = tab.run_edit("Add note", lambda d: annots.add_note(d[page], pt, dlg.text, style))
            self._one_shot_done(tab, page, xref)
        elif tool == "stamp":
            box = self._box(tab, page, fitz.Rect(pt, pt), 170, 60)
            name, with_date, style = self.stamp_name, self.stamp_date, self._style("stamp")
            xref = tab.run_edit(f"Stamp {name}", lambda d: annots.add_stamp(d[page], box, name, style, with_date))
            self._one_shot_done(tab, page, xref)
        elif tool == "edit_text" and self._text_panel_open():
            if not self.text_panel.pick(page, pt):
                self.statusBar().showMessage("No text there. (A scanned page is a picture.)", 5000)
        elif tool == "edit_text":
            line = tab.doc.run_read(lambda d: content.text_line_at(d[page], pt))
            if line is None:
                self.statusBar().showMessage("No text there. (A scanned page is a picture - run OCR, or use "
                                             "Add Text and Redact instead.)", 8000)
                return
            dlg = TextDialog("Edit text", line.text, line.style(),
                             "The line is replaced in the closest matching font. Leave it empty to delete the "
                             "line. Use Edit > Undo to go back.", self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            new_text, st = dlg.text.replace("\n", " "), dlg.style()
            if new_text == line.text and st == line.style():
                return
            tab.run_edit("Edit text", lambda d: content.replace_line(d[page], line, new_text, st))

    def _move_annot(self, tab, page, xref, dx, dy) -> None:
        new = tab.run_edit("Move comment", lambda d: annots.move_annot(d[page], xref, dx, dy))
        if new:
            tab.view.reselect(page, new)

    def _resize_annot(self, tab, page, xref, rect) -> None:
        new = tab.run_edit("Resize comment", lambda d: annots.resize_annot(d[page], xref, rect))
        if new:
            tab.view.reselect(page, new)

    def _edit_annot_text(self, tab, info) -> None:
        if not info.has_text:
            return
        dlg = CommentTextDialog(info.label, info.contents, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = tab.run_edit("Change comment text",
                           lambda d: annots.update_annot(d[info.page], info.xref, None, dlg.text))
        if new:
            tab.view.reselect(info.page, new)

    def _apply_annot_props(self, info, style, contents) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        new = tab.run_edit(f"Change {info.label.lower()}",
                           lambda d: annots.update_annot(d[info.page], info.xref, style, contents))
        if new:
            tab.view.reselect(info.page, new)

    def _delete_annot(self, tab, info) -> None:
        if tab is None or info is None:
            return
        tab.run_edit(f"Delete {info.label.lower()}", lambda d: annots.delete_annot(d[info.page], info.xref))
        tab.view.select_annot(None)

    # ------------------------------------------------------------- analysis
    def analyse_document(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        win = getattr(tab, "analysis_window", None)
        if win is not None and win.isVisible():
            win.raise_()
            win.activateWindow()
            return
        win = AnalysisWindow(tab.doc, self)
        win.goToPage.connect(lambda page, t=tab: (self.tabs.setCurrentWidget(t), t.show_organizer(False),
                                                  t.view.goto_page(page)))
        tab.analysis_window = win
        win.show()

    # ------------------------------------------------------- document tools
    def add_watermark(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        dlg = WatermarkDialog(tab.doc.page_count, tab.view.current_page,
                              self.db.get_setting("last_image_dir", str(Path.home())), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pages = dlg.scope.pages()
        opacity = dlg.opacity.value() / 100
        pos, behind = dlg.position.currentData(), dlg.behind.isChecked()
        if dlg.rb_text.isChecked():
            text, size, color, angle = dlg.text.text(), dlg.fontsize.value(), dlg.color.color(), dlg.angle.value()

            def do(d):
                for i in pages:
                    content.add_text_watermark(d[i], text, size, color, opacity, angle, pos, behind=behind)
        else:
            img, scale = dlg.image.text(), dlg.scale.value() / 100

            def do(d):
                for i in pages:
                    content.add_image_watermark(d[i], img, scale, opacity, pos, behind=behind)
        tab.run_edit(f"Watermark on {len(pages)} page(s)", do)

    def add_header_footer(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        dlg = HeaderFooterDialog(tab.doc.page_count, tab.view.current_page, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pages, items = dlg.scope.pages(), dlg.items()
        size, color, margin, offset = dlg.fontsize.value(), dlg.color.color(), dlg.margin.value(), dlg.start.value() - 1
        name = tab.doc.path.name

        def do(d):
            for i in pages:
                content.add_header_footer(d[i], items, d.page_count + offset, name, size, color, margin, offset)
        tab.run_edit(f"Header/footer on {len(pages)} page(s)", do)

    def extract_images(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder for the pictures", str(tab.doc.path.parent))
        if not folder:
            return
        files = tab.doc.run_read(lambda d: content.extract_images(d, range(d.page_count), folder, tab.doc.path.stem))
        if not files:
            QMessageBox.information(self, "Extract pictures", "This document contains no pictures.")
            return
        QMessageBox.information(self, "Extract pictures", f"Saved {len(files)} picture(s) in\n{folder}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def redact_text(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        dlg = RedactTextDialog(tab.doc.page_count, tab.view.current_page, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            pages = dlg.scope.pages()
        except ValueError as exc:
            QMessageBox.warning(self, "Redact", str(exc))
            return
        needle = dlg.text.text()
        n = tab.run_edit(f"Mark '{needle}' for redaction", lambda d: annots.mark_text_redactions(d, needle, pages))
        if n:
            self.statusBar().showMessage(f"Marked {n} place(s). Review them, then Tools > Redact > Apply Redactions.",
                                         10000)

    def apply_redactions(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        marks = tab.doc.run_read(annots.count_redaction_marks)
        if marks == 0:
            QMessageBox.information(self, "Apply redactions", "Nothing is marked yet. Use the Redact tool (drag over "
                                    "an area) or Tools > Redact > Mark Text for Redaction first.")
            return
        dlg = ApplyRedactionsDialog(marks, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        meta = dlg.metadata.isChecked()
        if tab.run_edit("Apply redactions", lambda d: annots.apply_redactions(d, meta)):
            QMessageBox.information(self, "Apply redactions", "The marked content has been removed. Save the result "
                                    "as a new file (File > Save > Save as new file).")

    def delete_all_comments(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if QMessageBox.question(self, "Delete all comments", "Delete every comment, highlight, shape and stamp in "
                                "this document? (Form fields and links are kept. You can Undo.)") \
                != QMessageBox.StandardButton.Yes:
            return
        n = tab.run_edit("Delete all comments", lambda d: annots.delete_all_annots(d))
        self.statusBar().showMessage(f"Deleted {n or 0} comment(s).", 5000)

    def flatten_comments(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if QMessageBox.question(self, "Flatten comments", "Make all comments part of the page? They will look the "
                                "same but can no longer be moved, changed or deleted. (You can Undo before "
                                "saving.)") != QMessageBox.StandardButton.Yes:
            return
        tab.run_edit("Flatten comments", annots.flatten_annots)

    def _zoom_from_combo(self) -> None:
        text = self.zoom_combo.currentText().strip().lower()
        if text.startswith("fit w"):
            self._view_call("fit_width")
        elif text.startswith("fit p"):
            self._view_call("fit_page")
        else:
            try:
                value = float(text.replace("%", "").strip()) / 100.0
            except ValueError:
                self._update_status()
                return
            self._view_call("set_zoom", value)
        tab = self.current_tab()
        if tab:
            tab.view.setFocus()

    def copy_selection(self) -> None:
        tab = self.current_tab()
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            focus.copy()
            return
        if tab and tab.view.copy_selection():
            self.statusBar().showMessage(f"Copied {len(tab.view.selected_text)} characters.", 3000)
        else:
            self.statusBar().showMessage("Nothing selected. Drag over text with the Select tool first.", 4000)

    def select_all(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            focus.selectAll()
            return
        tab = self.current_tab()
        if tab and tab.organizer_visible:
            tab.organizer.selectAll()
            return
        if tab:
            text = tab.view.select_all_on_page()
            if not text:
                self.statusBar().showMessage("This page has no selectable text (it may be a scan; OCR comes in Phase 4).", 6000)

    def focus_search(self) -> None:
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _search_from_toolbar(self) -> None:
        tab = self.current_tab()
        if tab:
            tab.show_search(self.search_box.text())

    def find_next(self) -> None:
        tab = self.current_tab()
        if tab:
            if not tab.search.hits and self.search_box.text():
                tab.show_search(self.search_box.text())
            else:
                tab.search.find_next()

    def find_prev(self) -> None:
        tab = self.current_tab()
        if tab:
            tab.search.find_prev()

    def show_properties(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        try:
            props = tab.doc.properties()
        except Exception as exc:
            self._show_error("Properties", exc)
            return
        dialogs.PropertiesDialog(props, self).exec()

    def open_containing_folder(self) -> None:
        tab = self.current_tab()
        if tab:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(tab.doc.path.parent)))

    def toggle_sidebar(self) -> None:
        visible = self.actions["sidebar"].isChecked()
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, DocumentTab):
                tab.set_side_panel_visible(visible)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
            self.actions["fullscreen"].setChecked(True)

    def _exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized() if getattr(self, "_was_maximized", False) else self.showNormal()
            self.actions["fullscreen"].setChecked(False)
        else:
            tab = self.current_tab()
            if tab:
                tab.view.clear_selection()

    def toggle_dark(self) -> None:
        self.dark = self.actions["dark"].isChecked()
        self.db.set_setting("theme", "dark" if self.dark else "light")
        self._apply_theme()

    def about(self) -> None:
        QMessageBox.about(
            self, f"About {config.APP_NAME}",
            f"<h3>{config.APP_NAME} {config.APP_VERSION}</h3>"
            f"<p>{config.APP_PHASE}</p>"
            "<p>An offline PDF reader and analysis workbench for Windows.</p>"
            "<p><b>Privacy:</b> all documents are processed on this computer. The application makes "
            "no network connections and sends no data anywhere.</p>"
            f"<p>Settings and logs: {config.DATA_DIR}</p>"
            "<p>Built with Qt (PySide6, LGPL) and MuPDF (PyMuPDF, AGPL). "
            "See THIRD_PARTY_LICENSES.md.</p>")

    # ============================================================ recent files
    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = self.db.recent_files()
        if not files:
            a = self.recent_menu.addAction("(no recent files)")
            a.setEnabled(False)
            return
        for n, path in enumerate(files, start=1):
            p = Path(path)
            label = f"&{n if n < 10 else 0}  {p.name}" if n <= 10 else p.name
            a = self.recent_menu.addAction(label)
            a.setToolTip(path)
            a.setStatusTip(path)
            if not p.exists():
                a.setText(label + "   (missing)")
                a.setEnabled(False)
            a.triggered.connect(lambda _c=False, fp=path: self.open_file(fp))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear recent files", self.db.clear_recent)

    # ============================================================== UI updates
    def _on_tab_changed(self, _index: int) -> None:
        self._update_ui()
        tab = self.current_tab()
        if tab is not None:
            self._sync_tool_ui(tab.view.tool)
        if self._text_panel_open():
            self.text_panel.show_page(tab, tab.view.current_page if tab is not None else -1, force=True)

    def _on_page_changed(self, _page: int) -> None:
        self._update_status()
        tab = self.current_tab()
        if self._text_panel_open() and tab is not None:
            self.text_panel.show_page(tab, tab.view.current_page)

    def _on_selection(self, text: str) -> None:
        if text:
            self.statusBar().showMessage(f"{len(text)} characters selected - Ctrl+C to copy", 5000)

    def _update_ui(self) -> None:
        tab = self.current_tab()
        has = tab is not None
        for k in ("save", "save_as", "print", "close", "close_all", "properties", "open_folder", "copy",
                  "select_all", "find", "find_next", "find_prev", "zoom_in", "zoom_out", "actual",
                  "fit_width", "fit_page", "rotate_cw", "rotate_ccw", "mode_cont", "mode_single",
                  "mode_two", "first", "prev", "next", "last", "goto", "ocr", "ocr_page",
                  "organize", "pg_rotate_cw", "pg_rotate_ccw", "pg_rotate_180", "pg_delete", "pg_duplicate",
                  "pg_move", "pg_reverse", "pg_insert_blank", "pg_insert_file", "pg_replace", "pg_extract",
                  "pg_split", "text_panel", "watermark", "header_footer", "extract_images", "redact_text", "apply_redactions",
                  "apply_redactions_tb", "delete_comments", "flatten_comments", "analyse") + tuple(
                      k for k in self.actions if k.startswith("tool_")):
            self.actions[k].setEnabled(has)
        undo_label = tab.doc.undo_label if has else None
        redo_label = tab.doc.redo_label if has else None
        self.actions["undo"].setEnabled(bool(undo_label))
        self.actions["redo"].setEnabled(bool(redo_label))
        self.actions["undo"].setText(f"&Undo {undo_label}" if undo_label else "&Undo")
        self.actions["redo"].setText(f"&Redo {redo_label}" if redo_label else "&Redo")
        self.actions["undo"].setToolTip(f"Undo: {undo_label} (Ctrl+Z)" if undo_label else "Nothing to undo")
        self.actions["redo"].setToolTip(f"Redo: {redo_label} (Ctrl+Y)" if redo_label else "Nothing to redo")
        self.actions["organize"].setChecked(bool(has and tab.organizer_visible))
        self.page_spin.setEnabled(has)
        self.zoom_combo.setEnabled(has)
        self.search_box.setEnabled(has)
        if has:
            self.setWindowTitle(f"{'* ' if tab.doc.modified else ''}{tab.doc.title} - {config.APP_NAME}")
            self.page_total.setText(f" / {tab.doc.page_count} ")
            self.page_spin.blockSignals(True)
            self.page_spin.setMaximum(max(1, tab.doc.page_count))
            self.page_spin.blockSignals(False)
            mode_key = {MODE_CONTINUOUS: "mode_cont", MODE_SINGLE: "mode_single", MODE_TWO: "mode_two"}[tab.view.mode]
            self.actions[mode_key].setChecked(True)
            self.search_box.setText(tab.search.query)
        else:
            self.setWindowTitle(config.APP_NAME)
            self.page_total.setText(" / 0 ")
        # show the welcome text when no document is open
        self.stack.setCurrentIndex(1 if self.tabs.count() else 0)
        self._update_status()

    def _update_status(self) -> None:
        tab = self.current_tab()
        if tab is None:
            for w in (self.status_page, self.status_zoom, self.status_rot, self.status_doc):
                w.setText("")
            return
        v = tab.view
        n = tab.doc.page_count
        self.status_page.setText(f"Page {v.current_page + 1} of {n}")
        fit = {FIT_WIDTH: " (fit width)", FIT_PAGE: " (fit page)"}.get(v.fit_mode, "")
        self.status_zoom.setText(f"{v.zoom * 100:.0f}%{fit}")
        self.status_rot.setText(f"Rotation {v.rotation}°")
        flags = []
        if tab.doc.password:
            flags.append("Encrypted")
        if tab.scanned_pages:
            flags.append(f"{len(tab.scanned_pages)} scanned page(s) - OCR available")
        self.status_doc.setText("   ".join(flags))
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(v.current_page + 1)
        self.page_spin.blockSignals(False)
        if not self.zoom_combo.lineEdit().hasFocus():
            if v.fit_mode == FIT_WIDTH:
                self.zoom_combo.setEditText("Fit width")
            elif v.fit_mode == FIT_PAGE:
                self.zoom_combo.setEditText("Fit page")
            else:
                self.zoom_combo.setEditText(f"{v.zoom * 100:.0f}%")

    # ============================================================= misc / events
    def _show_error(self, context: str, exc: BaseException) -> None:
        log_exception(context, exc)
        message, detail = describe(exc)
        box = QMessageBox(QMessageBox.Icon.Warning, f"{context} - {config.APP_NAME}", message, parent=self)
        if detail:
            box.setDetailedText(detail)
        if not isinstance(exc, WorkbenchError):
            box.setInformativeText("The application is still running. Details were written to the log.")
        box.exec()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".pdf") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile().lower().endswith(".pdf")]
        self.open_files(files)
        event.acceptProposedAction()

    def _restore_window(self) -> None:
        geo = self.db.get_setting("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromHex(geo.encode()))
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        job = getattr(self, "_ocr_job", None)
        if job is not None:
            ans = QMessageBox.question(self, "OCR running", "OCR is still running. Stop it and exit?")
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            job.cancel()
            job.wait(60000)
        try:
            self.db.set_setting("geometry", bytes(self.saveGeometry().toHex()).decode())
        except Exception:
            pass
        if not self.close_all():          # user cancelled on an unsaved document
            event.ignore()
            return
        event.accept()
