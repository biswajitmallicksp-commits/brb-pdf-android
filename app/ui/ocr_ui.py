"""OCR user interface: the OCR dialog, background jobs, result text window."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.pdf_ocr import engine
from app.pdf_viewer.document import PdfDocument
from app.utils.pages import describe_pages, parse_page_range  # noqa: F401 (re-exported)

log = logging.getLogger("pdfworkbench.ocr_ui")

QUALITY_LABELS = [
    ("fast", "Fast - 200 dpi (clear, large print)"),
    ("standard", "Standard - 300 dpi (recommended)"),
    ("high", "High - 400 dpi (small or faint print)"),
]
SECONDS_PER_PAGE_PER_LANGUAGE = 1.8   # rough estimate for the time hint


# ================================================================== helpers
def saved_languages(db) -> list[str]:
    installed = engine.available_languages()
    wanted = (db.get_setting("ocr_langs") or "eng+ben+hin").split("+")
    langs = [l for l in wanted if l in installed]
    return langs or (["eng"] if "eng" in installed else installed[:1])


def saved_quality(db) -> str:
    q = db.get_setting("ocr_quality") or "standard"
    return q if q in engine.QUALITY_DPI else "standard"


# ============================================================ background jobs
class ScanCheckWorker(QThread):
    """Finds pages that are scanned images without text (runs when a document opens)."""

    checked = Signal(list, int)     # pages needing OCR (0-based), total pages

    def __init__(self, doc: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        pages = []
        for i in range(self.doc.page_count):
            if self._stop or not self.doc.is_open:
                return
            try:
                if self.doc.classify_page(i).needs_ocr:
                    pages.append(i)
            except Exception as exc:
                log.debug("classify page %d failed: %s", i + 1, exc)
        self.checked.emit(pages, self.doc.page_count)


class OcrJobWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)            # engine.OcrJobResult
    failed = Signal(str)

    def __init__(self, path: str, password: str | None, output: str, languages: list[str],
                 dpi: int, pages: list[int] | None, parent=None):
        super().__init__(parent)
        self.args = (path, password, output, languages, dpi, pages)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        path, password, output, languages, dpi, pages = self.args
        try:
            result = engine.make_searchable(
                path, password, output, languages, dpi, pages,
                progress=lambda d, t, m: self.progress.emit(d, t, m),
                is_cancelled=lambda: self._cancel)
            self.done.emit(result)
        except Exception as exc:
            log.exception("OCR job failed")
            self.failed.emit(str(exc))


class PageTextWorker(QThread):
    done = Signal(object)            # engine.OcrPage
    failed = Signal(str)

    def __init__(self, path: str, password: str | None, index: int, languages: list[str], dpi: int, parent=None):
        super().__init__(parent)
        self.args = (path, password, index, languages, dpi)

    def run(self) -> None:
        try:
            self.done.emit(engine.recognize_single_page(*self.args))
        except Exception as exc:
            log.exception("Page OCR failed")
            self.failed.emit(str(exc))


# =================================================================== widgets
class ScannedBanner(QWidget):
    """Yellow bar shown above a document that contains scanned pages."""

    ocrRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("scannedBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#scannedBanner { background: #fff4c2; border-bottom: 1px solid #e6cf6e; }"
                           "#scannedBanner QLabel { color: #4a3b00; }")
        self.label = QLabel()
        self.label.setWordWrap(True)
        run = QPushButton("Make searchable (OCR)...")
        close = QPushButton("Dismiss")
        close.setFlat(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 10, 5)
        lay.addWidget(self.label, 1)
        lay.addWidget(run)
        lay.addWidget(close)
        run.clicked.connect(self.ocrRequested)
        close.clicked.connect(self.hide)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.hide()

    def show_for(self, pages: list[int], total: int) -> None:
        if not pages:
            self.hide()
            return
        if len(pages) == total:
            msg = (f"<b>This document is scanned</b> ({total} page{'s' if total > 1 else ''} of images). "
                   "Its text cannot be searched or copied until you run OCR.")
        else:
            msg = (f"<b>{len(pages)} of {total} pages are scanned images</b> (pages {describe_pages(pages)}). "
                   "Run OCR to make them searchable.")
        self.label.setText(msg)
        self.show()


class OcrDialog(QDialog):
    """Choose pages, languages, quality and the output file."""

    def __init__(self, doc: PdfDocument, current_page: int, scanned_pages: list[int] | None, db, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.db = db
        self.current_page = current_page
        self.scanned_pages = scanned_pages
        self.setWindowTitle("Make searchable PDF (OCR)")
        self.setMinimumWidth(560)

        n = doc.page_count
        if scanned_pages is None:
            summary = f"{n} pages. Checking which pages are scanned..."
        elif scanned_pages:
            summary = (f"{len(scanned_pages)} of {n} pages are scanned images without text "
                       f"(pages {describe_pages(scanned_pages)}).")
        else:
            summary = (f"All {n} pages already contain text, so there is nothing to recognise. "
                       "(Use OCR > Recognise Text on This Page to read the image text anyway.)")
        info = QLabel(summary + "<br><span style='color:gray'>Pages that already have text are skipped "
                      "automatically. The original file is not changed - the result is saved as a new PDF "
                      "that looks identical but has searchable, copyable text.</span>")
        info.setWordWrap(True)

        # pages
        pages_box = QGroupBox("Pages")
        self.rb_all = QRadioButton("All pages")
        self.rb_current = QRadioButton(f"Current page ({current_page + 1})")
        self.rb_range = QRadioButton("Pages:")
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("e.g. 1-5, 8, 10-12")
        self.rb_all.setChecked(True)
        group = QButtonGroup(self)
        for rb in (self.rb_all, self.rb_current, self.rb_range):
            group.addButton(rb)
        self.range_edit.textEdited.connect(lambda _t: self.rb_range.setChecked(True))
        grid = QGridLayout(pages_box)
        grid.addWidget(self.rb_all, 0, 0, 1, 2)
        grid.addWidget(self.rb_current, 1, 0, 1, 2)
        grid.addWidget(self.rb_range, 2, 0)
        grid.addWidget(self.range_edit, 2, 1)

        # languages
        lang_box = QGroupBox("Languages in the document")
        lang_lay = QGridLayout(lang_box)
        self.lang_checks: dict[str, QCheckBox] = {}
        chosen = set(saved_languages(db))
        for i, code in enumerate(engine.available_languages()):
            cb = QCheckBox(engine.language_label(code))
            cb.setChecked(code in chosen)
            cb.toggled.connect(self._update_estimate)
            self.lang_checks[code] = cb
            lang_lay.addWidget(cb, i // 3, i % 3)
        hint = QLabel("Tick only the languages that appear: fewer languages = faster and more accurate.")
        hint.setStyleSheet("color: gray")
        hint.setWordWrap(True)
        lang_lay.addWidget(hint, (len(self.lang_checks) + 2) // 3, 0, 1, 3)

        # quality + output
        self.quality = QComboBox()
        for key, label in QUALITY_LABELS:
            self.quality.addItem(label, key)
        self.quality.setCurrentIndex([k for k, _ in QUALITY_LABELS].index(saved_quality(db)))
        self.quality.currentIndexChanged.connect(self._update_estimate)
        self.output_edit = QLineEdit(str(engine.default_output_path(doc.path)))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(browse)
        self.open_after = QCheckBox("Open the searchable PDF when finished")
        self.open_after.setChecked(True)
        form = QFormLayout()
        form.addRow("Quality:", self.quality)
        form.addRow("Save as:", out_row)
        form.addRow("", self.open_after)

        self.estimate = QLabel()
        self.estimate.setWordWrap(True)
        self.estimate.setStyleSheet("color: gray")
        for rb in (self.rb_all, self.rb_current, self.rb_range):
            rb.toggled.connect(self._update_estimate)
        self.range_edit.textChanged.connect(self._update_estimate)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start OCR")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(pages_box)
        lay.addWidget(lang_box)
        lay.addLayout(form)
        lay.addWidget(self.estimate)
        lay.addWidget(buttons)
        self._update_estimate()

    # results ---------------------------------------------------------------
    @property
    def languages(self) -> list[str]:
        return [c for c, cb in self.lang_checks.items() if cb.isChecked()]

    @property
    def dpi(self) -> int:
        return engine.QUALITY_DPI[self.quality.currentData()]

    @property
    def output(self) -> str:
        return self.output_edit.text().strip()

    def selected_pages(self) -> list[int] | None:
        if self.rb_all.isChecked():
            return None
        if self.rb_current.isChecked():
            return [self.current_page]
        return parse_page_range(self.range_edit.text(), self.doc.page_count)

    # internals -------------------------------------------------------------
    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save searchable PDF as", self.output, "PDF documents (*.pdf)")
        if path:
            self.output_edit.setText(path if path.lower().endswith(".pdf") else path + ".pdf")

    def _update_estimate(self) -> None:
        try:
            pages = self.selected_pages()
        except ValueError:
            self.estimate.setText("")
            return
        candidates = range(self.doc.page_count) if pages is None else pages
        if self.scanned_pages is not None:
            scanned = set(self.scanned_pages)
            count = sum(1 for p in candidates if p in scanned)
        else:
            count = len(candidates)
        langs = max(1, len(self.languages))
        factor = {"fast": 0.6, "standard": 1.0, "high": 1.7}[self.quality.currentData()]
        cores = engine.worker_count()
        seconds = count * SECONDS_PER_PAGE_PER_LANGUAGE * (0.6 + 0.4 * langs) * factor / cores
        if count == 0:
            self.estimate.setText("No scanned pages in this selection - nothing to recognise.")
        else:
            when = f"about {max(1, round(seconds / 60))} minute(s)" if seconds >= 60 else "under a minute"
            self.estimate.setText(f"{count} page(s) to recognise, {when} using {cores} processor core(s). "
                                  "You can keep working while OCR runs.")

    def _accept(self) -> None:
        if not self.languages:
            QMessageBox.warning(self, "OCR", "Tick at least one language.")
            return
        try:
            self.selected_pages()
        except ValueError as exc:
            QMessageBox.warning(self, "OCR", str(exc))
            return
        out = Path(self.output) if self.output else None
        if out is None or out.suffix.lower() != ".pdf":
            QMessageBox.warning(self, "OCR", "Choose where to save the searchable PDF (a .pdf file).")
            return
        if out.resolve() == self.doc.path.resolve():
            QMessageBox.warning(self, "OCR", "Please choose a different file name: the original PDF is never "
                                "overwritten by OCR.")
            return
        if out.exists():
            ans = QMessageBox.question(self, "OCR", f"{out.name} already exists. Replace it?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.db.set_setting("ocr_langs", "+".join(self.languages))
        self.db.set_setting("ocr_quality", self.quality.currentData())
        self.accept()


class OcrTextDialog(QDialog):
    """Shows recognised text of one page with Copy / Save buttons."""

    def __init__(self, page: engine.OcrPage, title: str, languages: list[str], parent=None):
        super().__init__(parent)
        self.page = page
        self.setWindowTitle(f"Recognised text - page {page.index + 1}")
        self.resize(760, 620)
        self.edit = QPlainTextEdit()
        self.edit.setReadOnly(False)
        self.keep_columns = QCheckBox("Keep table columns apart (good for bank statements)")
        self.keep_columns.setChecked(True)
        self.keep_columns.toggled.connect(self._refresh)
        # fixed-width font keeps columns aligned, but only for Latin text:
        # Bengali/Devanagari need the normal font to be drawn correctly
        if page.text(layout=False).isascii():
            self.edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        else:
            f = self.edit.font()
            f.setPointSizeF(f.pointSizeF() * 1.15)
            self.edit.setFont(f)
        names = ", ".join(engine.language_label(l) for l in languages)
        head = QLabel(f"{title} - page {page.index + 1} - {page.word_count} words - languages: {names}. "
                      "You can correct the text here before copying.")
        head.setWordWrap(True)
        copy_btn = QPushButton("Copy all")
        save_btn = QPushButton("Save as TXT...")
        close_btn = QPushButton("Close")
        copy_btn.clicked.connect(self._copy)
        save_btn.clicked.connect(self._save)
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(self.keep_columns)
        row.addStretch(1)
        row.addWidget(copy_btn)
        row.addWidget(save_btn)
        row.addWidget(close_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(self.edit, 1)
        lay.addLayout(row)
        self._title = title
        self._refresh()

    def _refresh(self) -> None:
        text = self.page.text(layout=self.keep_columns.isChecked())
        self.edit.setPlainText(text or "(No text was recognised on this page. Try High quality, or check "
                                       "that the right languages are ticked and the page is not upside down.)")

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.edit.toPlainText())

    def _save(self) -> None:
        default = str(Path.home() / f"{Path(self._title).stem}_page{self.page.index + 1}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save text", default, "Text files (*.txt)")
        if path:
            Path(path).write_text(self.edit.toPlainText(), encoding="utf-8-sig")   # BOM: opens right in Notepad/Excel


class OcrInfoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR languages")
        self.resize(560, 360)
        folder = engine.find_tessdata()
        langs = engine.available_languages(folder)
        lines = "".join(f"<li>{engine.language_label(l)} <span style='color:gray'>({l})</span></li>" for l in langs)
        if folder is None:
            body = ("<p><b>No OCR language files were found.</b></p><p>Expected a <code>tessdata</code> folder "
                    "next to PDFWorkbench.exe containing eng.traineddata, ben.traineddata and "
                    "hin.traineddata.</p>")
        else:
            body = (f"<p>OCR runs completely on this computer. Installed languages:</p><ul>{lines}</ul>"
                    f"<p>Language folder:<br><code>{folder}</code></p>"
                    "<p>To add a language (for example Tamil <code>tam</code>, Odia <code>ori</code>, Gujarati "
                    "<code>guj</code>), download its <code>.traineddata</code> file from the "
                    "<i>tesseract-ocr/tessdata_best</i> project on GitHub, copy it into this folder and "
                    "restart the application.</p>")
        label = QLabel(body)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        open_btn = QPushButton("Open language folder")
        open_btn.setEnabled(folder is not None)
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addButton(open_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(label, 1)
        lay.addWidget(buttons)
