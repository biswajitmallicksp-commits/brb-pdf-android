"""AI Assistant panel (offline): prompt box, summaries, questions, form filling.

Everything runs on this computer. With the local model installed, answers are
written by the model; without it ("quick mode") the app shows the most
important / most relevant sentences of the document itself.
"""
from __future__ import annotations

import html
import logging
import re
import threading
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget,
)

from app.ai import engine
from app.ai import forms as F
from app.ai import tasks as K
from app.ai import text as T
from app.utils.pages import parse_page_range

log = logging.getLogger("pdfworkbench.ai")


class _Bridge(QObject):
    """Carries results from the worker thread to the window."""
    token = Signal(str)
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)


def _linkify(text: str) -> str:
    """Escape text, keep line breaks, turn 'p. 5' / 'page 5' into clickable links."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?m)^#{1,4}\s*(.+)$", r"<b>\1</b>", t)
    t = re.sub(r"\b(pp?\.\s?|[Pp]age\s)(\d{1,4})\b", r'<a href="page:\2">\1\2</a>', t)
    return t.replace("\n", "<br>")


class AIPanel(QWidget):
    """Lives in a dock at the right of the main window."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.win = window                      # MainWindow (current_tab, open_file, statusBar)
        self.bridge = _Bridge()
        self.bridge.token.connect(self._on_token)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.done.connect(self._on_done)
        self.bridge.failed.connect(self._on_failed)
        self.job: K.Job | None = None
        self._answer_buf = ""
        self._history: list[str] = []
        self._chapters: list[T.Chapter] = []

        self.engine_label = QLabel()
        self.engine_label.setWordWrap(True)

        # --- summarise row
        self.scope = QComboBox()
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText("e.g. 3-7")
        self.pages_edit.setMaximumWidth(80)
        self.pages_edit.setVisible(False)
        self.length = QComboBox()
        self.length.addItems(["Short", "Medium", "Detailed"])
        self.length.setCurrentIndex(1)
        self.sum_btn = QPushButton("Summarise")
        self.sum_btn.clicked.connect(self.summarise_clicked)
        row1 = QHBoxLayout()
        row1.addWidget(self.scope, 1)
        row1.addWidget(self.pages_edit)
        row1.addWidget(self.length)
        row1.addWidget(self.sum_btn)

        self.form_btn = QPushButton("Fill a Form from this PDF...")
        self.form_btn.setToolTip("Choose a form (PDF). Its blanks are filled with details found in the open PDF; "
                                 "you check every value before a filled copy is saved.")
        self.form_btn.clicked.connect(self.fill_form_clicked)

        # --- prompt
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Ask anything about this PDF, for example:\n"
                                       "  What is the loan amount and interest rate?\n"
                                       "  Summarise chapter 2 in short")
        self.prompt.setFixedHeight(76)
        QShortcut(QKeySequence("Ctrl+Return"), self.prompt, activated=self.send_clicked)
        self.send_btn = QPushButton("Send  (Ctrl+Enter)")
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self.send_clicked)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        row2 = QHBoxLayout()
        row2.addWidget(self.send_btn, 1)
        row2.addWidget(self.stop_btn)

        # --- output
        self.output = QTextBrowser()
        self.output.setOpenLinks(False)
        self.output.anchorClicked.connect(self._link)
        self.status = QLabel("")
        self.status.setStyleSheet("color:gray;")
        self.status.setWordWrap(True)
        copy_btn = QPushButton("Copy Answer")
        copy_btn.clicked.connect(self.copy_answer)
        save_btn = QPushButton("Save as Text...")
        save_btn.clicked.connect(self.save_text)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear)
        row3 = QHBoxLayout()
        for b in (copy_btn, save_btn, clear_btn):
            row3.addWidget(b)

        note = QLabel("Runs offline on this computer. AI can make mistakes: check important figures against the page "
                      "(click the page numbers).")
        note.setWordWrap(True)
        note.setStyleSheet("color:gray; font-size:11px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self.engine_label)
        lay.addLayout(row1)
        lay.addWidget(self.form_btn)
        lay.addWidget(self.prompt)
        lay.addLayout(row2)
        lay.addWidget(self.output, 1)
        lay.addWidget(self.status)
        lay.addLayout(row3)
        lay.addWidget(note)
        self.refresh_engine()
        self.document_changed()

    # ----------------------------------------------------------- state
    def refresh_engine(self) -> None:
        m = engine.get_model()
        if m is not None:
            self.engine_label.setText(f"<b>AI Assistant</b><br><span style='color:#1a7f37'>Local AI: {m.name} "
                                      "- offline, on this computer</span>")
        else:
            self.engine_label.setText("<b>AI Assistant</b><br><span style='color:#9a6700'>Quick mode: no AI model "
                                      "installed. Summaries pick key sentences; answers show the best matching "
                                      "passages; forms are filled from 'Label: value' lines.</span>")

    def document_changed(self) -> None:
        """New tab or changed document: refresh the chapter list."""
        tab = self.win.current_tab()
        cur = self.scope.currentData()
        self.scope.blockSignals(True)
        self.scope.clear()
        self.scope.addItem("Whole document", ("document", None))
        self.scope.addItem("Current page", ("page", None))
        self.scope.addItem("Pages...", ("pages", None))
        self._chapters = []
        if tab is not None:
            try:
                self._chapters = tab.doc.run_read(lambda d: T.chapters(d))
            except Exception:  # pragma: no cover
                self._chapters = []
        for k, ch in enumerate(self._chapters):
            self.scope.addItem("Chapter: " + ch.label.strip(), ("chapter", k))
        if cur is not None:
            i = self.scope.findData(cur)
            if i >= 0:
                self.scope.setCurrentIndex(i)
        self.scope.blockSignals(False)
        self._scope_changed()
        busy = self.job is not None
        for w in (self.sum_btn, self.send_btn, self.form_btn):
            w.setEnabled(tab is not None and not busy)

    def _scope_changed(self) -> None:
        data = self.scope.currentData() or ("document", None)
        self.pages_edit.setVisible(data[0] == "pages")

    def _busy(self, on: bool) -> None:
        for w in (self.sum_btn, self.send_btn, self.form_btn, self.prompt, self.scope, self.length):
            w.setEnabled(not on and self.win.current_tab() is not None)
        self.prompt.setEnabled(not on)
        self.stop_btn.setEnabled(on)
        if not on:
            self.job = None

    # ------------------------------------------------------------ output
    def _append(self, html_text: str) -> None:
        self._history.append(html_text)
        self.output.setHtml("<hr>".join(self._history))
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    def _start_answer(self, heading: str) -> None:
        self._answer_buf = ""
        self._history.append(f"<p><b>{html.escape(heading)}</b></p><p></p>")
        self.output.setHtml("<hr>".join(self._history))

    def _set_answer(self, text: str) -> None:
        self._history[-1] = self._history[-1].rsplit("<p>", 1)[0] + "<p>" + _linkify(text) + "</p>"
        self.output.setHtml("<hr>".join(self._history))
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    def _on_token(self, piece: str) -> None:
        self._answer_buf += piece
        self._set_answer(self._answer_buf)

    def _on_progress(self, msg: str) -> None:
        self.status.setText(msg)

    def _on_done(self, result) -> None:
        self._busy(False)
        self.status.setText("")
        if callable(result):
            result()
            return
        self._answer_buf = str(result)
        self._set_answer(self._answer_buf)

    def _on_failed(self, msg: str) -> None:
        self._busy(False)
        self.status.setText("")
        self._answer_buf = (self._answer_buf + "\n\n" if self._answer_buf else "") + f"(Stopped: {msg})"
        self._set_answer(self._answer_buf)

    def _link(self, url: QUrl) -> None:
        s = url.toString()
        tab = self.win.current_tab()
        if s.startswith("page:") and tab is not None:
            n = int(s[5:]) - 1
            if 0 <= n < tab.doc.page_count:
                tab.view.goto_page(n)

    def copy_answer(self) -> None:
        if self._answer_buf:
            QApplication.clipboard().setText(self._answer_buf)
            self.win.statusBar().showMessage("Answer copied", 3000)

    def save_text(self) -> None:
        if not self._history:
            return
        tab = self.win.current_tab()
        start = str(Path(tab.doc.path).with_name(Path(tab.doc.path).stem + "_AI.txt")) if tab else "AI.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Save as text", start, "Text (*.txt)")
        if path:
            Path(path).write_text(self.output.document().toPlainText(), encoding="utf-8")
            self.win.statusBar().showMessage(f"Saved {path}", 5000)

    def clear(self) -> None:
        self._history = []
        self._answer_buf = ""
        self.output.clear()

    def stop(self) -> None:
        if self.job is not None:
            self.job.cancel.set()
            self.status.setText("Stopping...")

    # ------------------------------------------------------------- run
    def _run(self, heading: str, work) -> None:
        """Run work(job) in a background thread; it returns the final text (or a callable for the window)."""
        self.job = K.Job(progress=self.bridge.progress.emit, token=self.bridge.token.emit)
        job = self.job
        self._busy(True)
        self._start_answer(heading)

        def target():
            try:
                result = work(job)
                self.bridge.done.emit(result)
            except engine.Cancelled:
                self.bridge.failed.emit("you pressed Stop")
            except engine.ModelError as exc:
                self.bridge.failed.emit(str(exc))
            except Exception as exc:  # pragma: no cover - shown to the user
                log.exception("AI task failed")
                self.bridge.failed.emit(f"unexpected error: {exc}")
        threading.Thread(target=target, daemon=True, name="ai-task").start()

    @staticmethod
    def _read(tab, pages: list[int], job: K.Job) -> list[T.Passage]:
        out = []
        for k, i in enumerate(pages):
            if k % 20 == 0:
                job.check()
                job.progress(f"Reading page {i + 1}...")
            out += tab.doc.run_read(lambda d, i=i: T.pages_text(d, [i]))
        return out

    def summarise_clicked(self) -> None:
        tab = self.win.current_tab()
        if tab is None:
            return
        kind, extra = self.scope.currentData() or ("document", None)
        n = tab.doc.page_count
        req = K.Request("summary", length=self.length.currentText().lower())
        if kind == "page":
            req.scope, req.pages = "page", [tab.view.current_page]
        elif kind == "pages":
            try:
                req.pages = parse_page_range(self.pages_edit.text(), n)
            except Exception as exc:
                QMessageBox.warning(self, "Pages", str(exc))
                return
            req.scope = "pages"
        elif kind == "chapter":
            ch = self._chapters[extra]
            req.scope, req.chapter, req.pages = "chapter", ch.title, list(range(ch.first, ch.last + 1))
        else:
            req.pages = list(range(n))
        self._summary(tab, req, f"Summary of {K.scope_words(req)} ({req.length})")

    def _summary(self, tab, req: K.Request, heading: str) -> None:
        model = engine.get_model()

        def work(job):
            passages = self._read(tab, req.pages, job)
            return K.summarise(model, passages, req, job)
        self._run(heading, work)

    def send_clicked(self) -> None:
        tab = self.win.current_tab()
        text = self.prompt.toPlainText().strip()
        if tab is None or not text or self.job is not None:
            return
        self.prompt.clear()
        req = K.route(text, tab.doc.page_count, tab.view.current_page, self._chapters)
        if req.kind == "summary":
            self._summary(tab, req, text)
            return
        model = engine.get_model()
        pages = list(range(tab.doc.page_count))

        def work(job):
            passages = self._read(tab, pages, job)
            return K.answer(model, passages, text, job)
        self._run(text, work)

    # --------------------------------------------------------- form fill
    def fill_form_clicked(self) -> None:
        tab = self.win.current_tab()
        if tab is None:
            return
        start = str(Path(tab.doc.path).parent)
        path, _ = QFileDialog.getOpenFileName(self, "Choose the form to fill", start, "PDF forms (*.pdf)")
        if not path:
            return
        if Path(path).resolve() == Path(tab.doc.path).resolve():
            QMessageBox.information(self, "Fill a form", "Choose the FORM to fill. The open PDF is where the "
                                    "information is taken from.")
            return
        self.fill_form(tab, path)

    def fill_form(self, tab, form_path: str) -> None:
        try:
            form = fitz.open(form_path)
            if form.needs_pass:
                QMessageBox.warning(self, "Fill a form", "That form is password protected. Open it, save an "
                                    "unprotected copy, and choose that copy.")
                return
            fields = F.detect_fields(form)
            form.close()
        except Exception as exc:
            QMessageBox.warning(self, "Fill a form", f"The form could not be read: {exc}")
            return
        if not fields:
            QMessageBox.information(self, "Fill a form", "No blanks were found in that form. It should have "
                                    "fillable fields, or printed blanks such as 'Name: ________' or 'PAN:'. "
                                    "(A scanned form is a picture: run OCR on it first.)")
            return
        model = engine.get_model()
        pages = list(range(tab.doc.page_count))
        source_name = tab.doc.title

        def work(job):
            passages = self._read(tab, pages, job)
            job.progress(f"Looking for {len(fields)} values...")
            F.find_values(fields, passages, model, job)
            found = sum(1 for f in fields if f.found)
            return lambda: self._review(tab, form_path, fields, found, source_name)
        self._run(f"Fill form: {Path(form_path).name}", work)

    def _review(self, tab, form_path: str, fields: list[F.FormField], found: int, source_name: str) -> None:
        self._answer_buf = (f"{found} of {len(fields)} values found in {source_name}. Check them in the window "
                            "that opened, then save the filled form.")
        self._set_answer(self._answer_buf)
        dlg = FormReviewDialog(form_path, fields, source_name, self)
        dlg.pageRequested.connect(lambda p: tab.view.goto_page(p))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._set_answer(self._answer_buf + "\n(Not saved.)")
            return
        fields = dlg.fields()
        start = str(Path(form_path).with_name(Path(form_path).stem + "_filled.pdf"))
        out, _ = QFileDialog.getSaveFileName(self, "Save the filled form as", start, "PDF (*.pdf)")
        if not out:
            return
        if Path(out).resolve() == Path(form_path).resolve():
            QMessageBox.warning(self, "Fill a form", "Please save under a new name - the original form is kept "
                                "unchanged.")
            return
        try:
            doc = fitz.open(form_path)
            n = F.fill(doc, fields, out)
            doc.close()
        except Exception as exc:
            QMessageBox.warning(self, "Fill a form", f"The filled form could not be saved: {exc}")
            return
        self._set_answer(self._answer_buf + f"\nSaved {n} values in {Path(out).name}.")
        self.win.open_file(out)


class FormReviewDialog(QDialog):
    """Every value is shown before it goes into the form: edit, clear, or jump to its source page."""
    pageRequested = Signal(int)

    def __init__(self, form_path: str, fields: list[F.FormField], source_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Check the values - {Path(form_path).name}")
        self.resize(820, 560)
        self._fields = fields
        info = QLabel(f"Values found in <b>{html.escape(source_name)}</b>. Check each one - correct or fill in "
                      "anything that is wrong or missing. Empty values are left blank in the form. "
                      "Double-click a source page to see it.")
        info.setWordWrap(True)
        self.table = QTableWidget(len(fields), 4)
        self.table.setHorizontalHeaderLabels(["Form field", "Value (you can edit)", "Found by", "Source page"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        how = {"label": "matching label", "pattern": "pattern", "AI": "local AI", "already filled": "already in form"}
        for r, f in enumerate(fields):
            a = QTableWidgetItem(f.label)
            a.setFlags(a.flags() & ~Qt.ItemFlag.ItemIsEditable)
            b = QTableWidgetItem(f.value)
            c = QTableWidgetItem(how.get(f.source, "not found"))
            c.setFlags(c.flags() & ~Qt.ItemFlag.ItemIsEditable)
            d = QTableWidgetItem("" if f.source_page is None else str(f.source_page + 1))
            d.setFlags(d.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not f.found:
                for it in (a, c):
                    it.setForeground(Qt.GlobalColor.darkYellow)
            self.table.setItem(r, 0, a)
            self.table.setItem(r, 1, b)
            self.table.setItem(r, 2, c)
            self.table.setItem(r, 3, d)
        self.table.cellDoubleClicked.connect(self._jump)
        buttons = QDialogButtonBox()
        self.ok = buttons.addButton("Fill and Save As...", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.table, 1)
        lay.addWidget(buttons)

    def _jump(self, row: int, _col: int) -> None:
        p = self._fields[row].source_page
        if p is not None:
            self.pageRequested.emit(p)

    def fields(self) -> list[F.FormField]:
        for r, f in enumerate(self._fields):
            item = self.table.item(r, 1)
            new = (item.text() if item else "").strip()
            if new != f.value:
                f.value, f.source = new, ("typed" if new else "")
        return self._fields
