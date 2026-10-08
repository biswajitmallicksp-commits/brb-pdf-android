"""PDF Analysis window (Analysis > Analyse Document)."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from app.pdf_analysis.analyzer import DocumentReport, PageReport, analyze
from app.pdf_viewer.document import PdfDocument, _describe_permissions

log = logging.getLogger("pdfworkbench.analysis_ui")

STATUS_COLORS = {"Scanned - needs OCR": QColor(255, 236, 179), "Blank": QColor(230, 230, 230),
                 "Scanned with OCR text": QColor(214, 236, 255), "Mixed": QColor(232, 245, 233)}


class AnalysisWorker(QThread):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, doc: PdfDocument, detect_tables: bool, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.detect_tables = detect_tables
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            size = self.doc.path.stat().st_size if self.doc.path.exists() else 0
            perms = _describe_permissions(self.doc._permissions)
            report = analyze(self.doc.run_read, str(self.doc.path), size, perms, bool(self.doc.password),
                             self.detect_tables, progress=lambda a, b: self.progress.emit(a, b),
                             is_cancelled=lambda: self._cancel)
            self.done.emit(report)
        except Exception as exc:
            log.exception("Analysis failed")
            self.failed.emit(str(exc))


class AnalysisWindow(QDialog):
    """Shows the analysis of one document. Non-modal: the document stays usable."""

    goToPage = Signal(int)          # 0-based

    def __init__(self, doc: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.report: DocumentReport | None = None
        self.worker: AnalysisWorker | None = None
        self.setWindowTitle(f"Analysis - {doc.title}")
        self.resize(1000, 700)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)

        self.tables_box = QCheckBox("Detect ruled tables (slower)")
        self.tables_box.setChecked(doc.page_count <= 40)
        self.run_btn = QPushButton("Analyse again")
        self.run_btn.clicked.connect(self.start)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(lambda: self.worker and self.worker.cancel())
        top = QHBoxLayout()
        top.addWidget(self.tables_box)
        top.addWidget(self.run_btn)
        top.addWidget(self.progress, 1)
        top.addWidget(self.stop_btn)

        self.summary = QTextBrowser()
        self.summary.setOpenLinks(False)
        self.pages = QTableWidget(0, len(PageReport.COLUMNS))
        self.pages.setHorizontalHeaderLabels(PageReport.COLUMNS)
        self.pages.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pages.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.pages.verticalHeader().setVisible(False)
        self.pages.setSortingEnabled(True)
        self.pages.cellDoubleClicked.connect(self._row_activated)
        self.structure = QTreeWidget()
        self.structure.setHeaderLabels(["Item", "Details"])
        self.structure.setColumnWidth(0, 300)
        self.structure.itemDoubleClicked.connect(self._tree_activated)
        self.fonts = QTableWidget(0, 5)
        self.fonts.setHorizontalHeaderLabels(["Font", "Type", "Embedded", "Encoding", "Pages"])
        self.fonts.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fonts.verticalHeader().setVisible(False)
        self.fonts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.summary, "Summary")
        self.tabs.addTab(self.pages, "Pages")
        self.tabs.addTab(self.structure, "Structure")
        self.tabs.addTab(self.fonts, "Fonts")

        hint = QLabel("Double-click a page (or an item in Structure) to show it in the document.")
        hint.setStyleSheet("color: gray")
        csv_btn = QPushButton("Export pages (CSV for Excel)...")
        report_btn = QPushButton("Save report...")
        copy_btn = QPushButton("Copy summary")
        close_btn = QPushButton("Close")
        csv_btn.clicked.connect(self.export_csv)
        report_btn.clicked.connect(self.save_report)
        copy_btn.clicked.connect(lambda: self.report and QGuiApplication.clipboard().setText(self.report.to_text()))
        close_btn.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        for b in (csv_btn, report_btn, copy_btn, close_btn):
            bottom.addWidget(b)
        self.export_buttons = (csv_btn, report_btn, copy_btn)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.tabs, 1)
        lay.addLayout(bottom)
        self.start()

    # ------------------------------------------------------------------ run
    def start(self) -> None:
        if self.worker is not None:
            return
        self.progress.setRange(0, max(1, self.doc.page_count))
        self.progress.setValue(0)
        self.progress.setFormat("Analysing page %v of %m")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        for b in self.export_buttons:
            b.setEnabled(False)
        self.worker = AnalysisWorker(self.doc, self.tables_box.isChecked(), self)
        self.worker.progress.connect(lambda a, b: self.progress.setValue(a))
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _finish(self) -> None:
        self.worker = None
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _failed(self, message: str) -> None:
        self._finish()
        QMessageBox.warning(self, "Analysis", f"The analysis could not be completed:\n{message}")

    def _done(self, report: DocumentReport) -> None:
        self._finish()
        self.report = report
        self.progress.setFormat("Stopped" if report.cancelled else "Done")
        for b in self.export_buttons:
            b.setEnabled(True)
        self._fill_summary(report)
        self._fill_pages(report)
        self._fill_structure(report)
        self._fill_fonts(report)

    # -------------------------------------------------------------- display
    def _fill_summary(self, r: DocumentReport) -> None:
        body = r.to_html()
        start = body.find("<h1>")
        end = body.find("<h2>Fonts</h2>")
        self.summary.setHtml(body[:body.find("<body>") + 6] + body[start:end] + "</body></html>")

    def _fill_pages(self, r: DocumentReport) -> None:
        self.pages.setSortingEnabled(False)
        self.pages.setRowCount(len(r.pages))
        for row, p in enumerate(r.pages):
            for col, value in enumerate(p.row()):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.DisplayRole, value)
                if p.status in STATUS_COLORS:
                    item.setBackground(STATUS_COLORS[p.status])
                    item.setForeground(QColor(30, 30, 30))
                self.pages.setItem(row, col, item)
        self.pages.resizeColumnsToContents()
        self.pages.setSortingEnabled(True)
        self.pages.sortItems(0, Qt.SortOrder.AscendingOrder)

    def _fill_structure(self, r: DocumentReport) -> None:
        t = self.structure
        t.clear()
        for k, v in r.structure_rows():
            t.addTopLevelItem(QTreeWidgetItem([k, v]))

        def group(title: str, rows: list[tuple[str, str, int | None]]):
            top = QTreeWidgetItem([title, str(len(rows))])
            t.addTopLevelItem(top)
            for a, b, page in rows:
                it = QTreeWidgetItem([a, b])
                if page is not None:
                    it.setData(0, Qt.ItemDataRole.UserRole, page)
                top.addChild(it)
            return top

        if r.bookmarks:
            group("Bookmarks", [("  " * (lvl - 1) + title, f"page {pg}", pg - 1) for lvl, title, pg in r.bookmarks])
        if r.form_fields:
            group("Form fields", [(f"{n}  ({tp})", f"page {pg}: {v}", pg - 1) for pg, n, tp, v in r.form_fields])
        if r.signatures:
            group("Digital signatures", [(s["field"], f"page {s['page']}: {s['state']}"
                                          + (f" - {s['signer']}" if s.get("signer") else "")
                                          + (f" - {s['date']}" if s.get("date") else ""), s["page"] - 1)
                                         for s in r.signatures])
        if r.attachments:
            group("Attachments", [(n, f"{s:,} bytes", None) for n, s in r.attachments])
        scanned = [p for p in r.pages if p.status == "Scanned - needs OCR"]
        if scanned:
            group("Scanned pages without OCR", [(f"Page {p.number}", f"{p.images} image(s), "
                                                 f"{p.image_coverage:.0f}% covered", p.number - 1) for p in scanned])
        blanks = [p for p in r.pages if p.status == "Blank"]
        if blanks:
            group("Blank pages", [(f"Page {p.number}", "", p.number - 1) for p in blanks])

    def _fill_fonts(self, r: DocumentReport) -> None:
        from app.utils.pages import describe_pages
        self.fonts.setRowCount(len(r.fonts))
        for row, f in enumerate(r.fonts):
            vals = [f.name, f.type, ("Yes (subset)" if f.subset else "Yes") if f.embedded else "NO", f.encoding,
                    describe_pages([p - 1 for p in f.pages], limit=10)]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if not f.embedded:
                    item.setForeground(QColor(170, 90, 0))
                self.fonts.setItem(row, col, item)
        self.fonts.resizeColumnsToContents()

    # -------------------------------------------------------------- actions
    def _row_activated(self, row: int, _col: int) -> None:
        item = self.pages.item(row, 0)
        if item is not None:
            self.goToPage.emit(int(item.data(Qt.ItemDataRole.DisplayRole)) - 1)

    def _tree_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None:
            self.goToPage.emit(int(page))

    def export_csv(self) -> None:
        if self.report is None:
            return
        default = str(self.doc.path.with_name(f"{self.doc.path.stem}_analysis.csv"))
        path, _ = QFileDialog.getSaveFileName(self, "Export page analysis", default, "CSV (*.csv)")
        if path:
            Path(path).write_text(self.report.to_csv(), encoding="utf-8-sig")   # BOM: Excel reads it correctly

    def save_report(self) -> None:
        if self.report is None:
            return
        default = str(self.doc.path.with_name(f"{self.doc.path.stem}_analysis.html"))
        path, filt = QFileDialog.getSaveFileName(self, "Save analysis report", default,
                                                 "Web page report (*.html);;Text report (*.txt)")
        if not path:
            return
        if path.lower().endswith(".txt") or "txt" in filt and not path.lower().endswith(".html"):
            Path(path).write_text(self.report.to_text(), encoding="utf-8-sig")
        else:
            Path(path).write_text(self.report.to_html(), encoding="utf-8")

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(10000)
        super().closeEvent(event)
