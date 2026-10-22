"""Editable document window (like Word) for the text of a PDF or of an OCR result.

The document lives only in memory ("temporary document"). Nothing is written to
disk until you press Save (Word and/or PDF, in the original folder or another one, keeping
or removing the original PDF); closing without saving asks first.
The original PDF is never changed.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QFont, QImage, QKeySequence, QPixmap, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from app import config
from app.pdf_editor import doc_export as X
from app.pdf_editor import doc_model as M

log = logging.getLogger("pdfworkbench.doceditor")

SAVE_STYLE = "QToolButton { background:#2f6fdb; color:white; border-radius:4px; padding:4px 10px; font-weight:600; }"


class DocEditorWindow(QMainWindow):
    """Open with DocEditorWindow.open_for(parent, fitz_doc, pages, title, folder)."""

    def __init__(self, pages: list[M.PageModel], source: fitz.Document, title: str, folder: Path, parent=None,
                 original: Path | None = None, retire_original=None):
        super().__init__(parent)
        self.original = Path(original) if original else None       # the PDF this text came from
        self.retire_original = retire_original                   # callback: move the original to the Recycle Bin
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.source = source                    # a private copy of the PDF, for the original-page preview
        self.base_title = title
        self.folder = folder
        self.saved_to: list[str] = []
        self._preview_page = -1
        self.resize(1300, 880)

        self.doc = X.build_document(pages)
        self.edit = QTextEdit()
        self.edit.setDocument(self.doc)
        self.edit.setAcceptRichText(False)
        w, _h = X.page_size_pt(self.doc)
        self.edit.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
        self.edit.setLineWrapColumnOrWidth(int(w * X.PX))
        self.edit.setStyleSheet("QTextEdit { background: white; }")
        self.edit.cursorPositionChanged.connect(self._cursor_moved)
        self.doc.modificationChanged.connect(self._modified_changed)
        self.doc.undoAvailable.connect(lambda v: self.a_undo.setEnabled(v))
        self.doc.redoAvailable.connect(lambda v: self.a_redo.setEnabled(v))
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(12, 12, 12, 12)
        hl.addStretch(1)
        self.edit.setMinimumWidth(int(w * X.PX) + 40)
        hl.addWidget(self.edit, 100)
        hl.addStretch(1)
        holder.setStyleSheet("background:#d6dae0;")
        self.setCentralWidget(holder)

        # original page preview
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

        self._make_toolbar()
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self._modified_changed(False)
        self._cursor_moved()

    # ------------------------------------------------------------- toolbar
    def _make_toolbar(self) -> None:
        tb = QToolBar("Document")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)
        self.a_save = QAction("Save...", self)
        self.a_save.setShortcuts([QKeySequence.StandardKey.Save, QKeySequence("Ctrl+Shift+S")])
        self.a_save.setToolTip("Save as Word or PDF - in the original folder or another one")
        self.a_save.triggered.connect(self.save)
        tb.addAction(self.a_save)
        self.save_btn = tb.widgetForAction(self.a_save)
        # kept for scripts/tests: direct saves without the options window
        self.a_word = QAction("Save as Word", self)
        self.a_word.triggered.connect(self.save_word)
        self.a_pdf = QAction("Save as PDF", self)
        self.a_pdf.triggered.connect(self.save_pdf)
        tb.addSeparator()
        self.a_undo = tb.addAction("Undo", self.edit.undo)
        self.a_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.a_redo = tb.addAction("Redo", self.edit.redo)
        self.a_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.a_undo.setEnabled(False)
        self.a_redo.setEnabled(False)
        tb.addSeparator()
        self.a_bold = tb.addAction("B", self._toggle_bold)
        self.a_bold.setCheckable(True)
        self.a_bold.setShortcut(QKeySequence.StandardKey.Bold)
        f = QFont()
        f.setBold(True)
        self.a_bold.setFont(f)
        self.a_italic = tb.addAction("I", lambda: self.edit.setFontItalic(not self.edit.fontItalic()))
        self.a_italic.setCheckable(True)
        self.a_italic.setShortcut(QKeySequence.StandardKey.Italic)
        f = QFont()
        f.setItalic(True)
        self.a_italic.setFont(f)
        self.a_under = tb.addAction("U", lambda: self.edit.setFontUnderline(not self.edit.fontUnderline()))
        self.a_under.setCheckable(True)
        self.a_under.setShortcut(QKeySequence.StandardKey.Underline)
        f = QFont()
        f.setUnderline(True)
        self.a_under.setFont(f)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems(["8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "36"])
        self.size_box.setMaximumWidth(64)
        self.size_box.setToolTip("Font size")
        self.size_box.activated.connect(lambda _i: self._set_size())
        self.size_box.lineEdit().returnPressed.connect(self._set_size)
        tb.addWidget(self.size_box)
        self.font_box = QComboBox()
        self.font_box.addItems(["Arial", "Times New Roman", "Courier New", "Calibri", "Nirmala UI"])
        self.font_box.setToolTip("Font")
        self.font_box.activated.connect(lambda _i: self._set_family())
        tb.addWidget(self.font_box)
        tb.addSeparator()
        a = tb.addAction("Find && Replace...", self.find_replace)
        a.setShortcut(QKeySequence.StandardKey.Find)
        tb.addAction("Zoom +", lambda: self.edit.zoomIn(1))
        tb.addAction("Zoom -", lambda: self.edit.zoomOut(1))
        tb.addSeparator()
        self.a_preview = tb.addAction("Show Original", lambda: self.preview_dock.setVisible(self.a_preview.isChecked()))
        self.a_preview.setCheckable(True)
        self.a_preview.setChecked(True)
        self.preview_dock.visibilityChanged.connect(self.a_preview.setChecked)
        self.edit.currentCharFormatChanged.connect(self._format_changed)

    def _toggle_bold(self) -> None:
        bold = self.edit.fontWeight() < QFont.Weight.DemiBold.value
        self.edit.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)

    def _set_size(self) -> None:
        try:
            size = float(self.size_box.currentText())
        except ValueError:
            return
        if 3 <= size <= 200:
            self.edit.setFontPointSize(size)
            self.edit.setFocus()

    def _set_family(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamilies([self.font_box.currentText()])
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def _format_changed(self, fmt: QTextCharFormat) -> None:
        self.a_bold.setChecked(fmt.fontWeight() >= QFont.Weight.DemiBold.value)
        self.a_italic.setChecked(fmt.fontItalic())
        self.a_under.setChecked(fmt.fontUnderline())
        if fmt.fontPointSize() > 0:
            self.size_box.setEditText(f"{fmt.fontPointSize():g}")
        fams = fmt.fontFamilies()
        if fams:
            i = self.font_box.findText(fams[0])
            if i >= 0:
                self.font_box.setCurrentIndex(i)

    # --------------------------------------------------------------- state
    def _modified_changed(self, modified: bool) -> None:
        if getattr(self, "save_btn", None) is not None:
            # the Save button stands out as soon as something was changed
            self.a_save.setText("Save changes..." if modified else "Save...")
            self.save_btn.setStyleSheet(SAVE_STYLE if modified or not self.saved_to else "")
        mark = "* " if modified else ""
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
        page = max(0, self.edit.textCursor().block().userState())
        if page != self._preview_page:
            self._preview_page = page
            self._show_original(page)

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

    # ---------------------------------------------------------------- save
    def _ask_path(self, kind: str) -> str | None:
        ext = ".docx" if kind == "word" else ".pdf"
        stem = Path(self.base_title).stem
        start = str(self.folder / f"{stem} - edited{ext}")
        flt = "Word documents (*.docx)" if kind == "word" else "PDF documents (*.pdf)"
        path, _ = QFileDialog.getSaveFileName(self, "Save as Word" if kind == "word" else "Save as PDF", start, flt)
        if not path:
            return None
        if not path.lower().endswith(ext):
            path += ext
        return path

    def save(self) -> bool:
        """Ask format, folder, name and what to do with the original PDF; then save."""
        from app.ui.save_options import SaveOptionsDialog
        stem = Path(self.base_title).stem
        if not stem.lower().endswith("edited"):
            stem += " - edited"
        dlg = SaveOptionsDialog(self.original, stem, ("word", "pdf"), "word", self, "Save the document")
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.choice is None:
            return False
        for target in dlg.choice.targets:
            writer, kind = (X.save_docx, "Word") if target.suffix.lower() == ".docx" else (X.save_pdf, "PDF")
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

    def save_word(self) -> bool:
        path = self._ask_path("word")
        return bool(path) and self._save(path, X.save_docx, "Word")

    def save_pdf(self) -> bool:
        path = self._ask_path("pdf")
        return bool(path) and self._save(path, X.save_pdf, "PDF")

    def _save(self, path: str, writer, kind: str) -> bool:
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
        self.saved_to.append(path)
        self.doc.setModified(False)
        self._modified_changed(False)
        self.statusBar().showMessage(f"Saved {path}", 8000)
        return True

    def closeEvent(self, event) -> None:
        if self.doc.isModified():
            box = QMessageBox(QMessageBox.Icon.Question, "Editable document",
                              "Your changes are not saved yet. Save them before closing?", parent=self)
            b_save = box.addButton("Save...", QMessageBox.ButtonRole.AcceptRole)
            b_drop = box.addButton("Close without saving", QMessageBox.ButtonRole.DestructiveRole)
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

    # ---------------------------------------------------------- find/replace
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
            if not X.is_marker(c.block()):
                c.insertText(new)
                n += 1
            c = self.doc.find(old, c, flags)
        cur.endEditBlock()
        return n

    # ------------------------------------------------------------- opening
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


def scanned_without_text(models: list[M.PageModel]) -> list[int]:
    return [m.index for m in models if not m.has_text]
