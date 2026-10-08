"""Left-panel tabs: Bookmarks and Search results."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.pdf_viewer.document import PdfDocument, SearchHit
from app.ui.workers import SearchWorker


class BookmarksPanel(QTreeWidget):
    pageActivated = Signal(int)

    def __init__(self, outline: list[tuple[int, str, int]], parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.itemClicked.connect(self._clicked)
        self.load(outline)

    def load(self, outline: list[tuple[int, str, int]]) -> None:
        self.clear()
        parents: dict[int, QTreeWidgetItem] = {}
        for level, title, page in outline:
            item = QTreeWidgetItem([title or "(untitled)"])
            item.setData(0, Qt.ItemDataRole.UserRole, page)
            item.setToolTip(0, f"{title}  -  page {page + 1}")
            parent_item = parents.get(level - 1)
            if level > 1 and parent_item is not None:
                parent_item.addChild(item)
            else:
                self.addTopLevelItem(item)
            parents[level] = item
        if not outline:
            empty = QTreeWidgetItem(["This document has no bookmarks."])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addTopLevelItem(empty)
        self.expandToDepth(0)

    def _clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None:
            self.pageActivated.emit(int(page))


class SearchPanel(QWidget):
    """Search box + result list. Emits hits for the viewer to highlight."""

    hitsAdded = Signal(list)        # list[SearchHit]
    hitsCleared = Signal()
    hitActivated = Signal(object)   # SearchHit
    statusChanged = Signal(str)

    def __init__(self, doc: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.scanned_pages: list[int] | None = None
        self._worker: SearchWorker | None = None
        self._hits: list[SearchHit] = []
        self._index = -1
        self._last_query = ""

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find text in this document")
        self.edit.setClearButtonEnabled(True)
        self.go = QPushButton("Search")
        self.stop = QPushButton("Stop")
        self.stop.setEnabled(False)
        self.status = QLabel("Type a word or phrase and press Enter.")
        self.status.setWordWrap(True)
        self.results = QListWidget()
        self.results.setUniformItemSizes(True)
        self.results.setWordWrap(False)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.go)
        row.addWidget(self.stop)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.edit)
        lay.addLayout(row)
        lay.addWidget(self.status)
        lay.addWidget(self.results, 1)

        self.edit.returnPressed.connect(lambda: self.start_search(self.edit.text()))
        self.go.clicked.connect(lambda: self.start_search(self.edit.text()))
        self.stop.clicked.connect(self.cancel)
        self.results.currentRowChanged.connect(self._row_changed)

    # --------------------------------------------------------------- control
    @property
    def query(self) -> str:
        return self._last_query

    @property
    def hits(self) -> list[SearchHit]:
        return self._hits

    def start_search(self, text: str) -> None:
        text = text.strip()
        if text and text == self._last_query and self._hits and self._worker is None:
            self.find_next()
            return
        self.cancel()
        self.edit.setText(text)
        self._hits = []
        self._index = -1
        self.results.clear()
        self.hitsCleared.emit()
        self._last_query = text
        if not text:
            self.status.setText("Type a word or phrase and press Enter.")
            return
        worker = SearchWorker(self.doc, text, parent=self)
        worker.hitsFound.connect(self._on_hits)
        worker.progress.connect(self._on_progress)
        worker.finishedSearch.connect(self._on_finished)
        self._worker = worker
        self.stop.setEnabled(True)
        self.status.setText("Searching...")
        worker.start()

    def reset(self) -> None:
        """Forget the results (pages changed, so page numbers are no longer valid)."""
        self.cancel()
        had = bool(self._hits)
        self._hits = []
        self._index = -1
        self._last_query = ""
        self.results.clear()
        if had:
            self.status.setText("Pages changed - search again.")
        self.hitsCleared.emit()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(5000)
            self._worker = None
        self.stop.setEnabled(False)

    def find_next(self) -> None:
        if self._hits:
            self.results.setCurrentRow((self._index + 1) % len(self._hits))

    def find_prev(self) -> None:
        if self._hits:
            self.results.setCurrentRow((self._index - 1) % len(self._hits))

    # --------------------------------------------------------------- signals
    def _on_hits(self, hits: list[SearchHit]) -> None:
        if self.sender() is not self._worker:     # late results from a cancelled search
            return
        first_batch = not self._hits
        for h in hits:
            self._hits.append(h)
            item = QListWidgetItem(f"p. {h.page + 1}   {h.snippet}")
            item.setToolTip(h.snippet)
            self.results.addItem(item)
        self.hitsAdded.emit(hits)
        if first_batch:
            self.results.setCurrentRow(0)

    def _on_progress(self, done: int, total: int) -> None:
        if self.sender() is not self._worker:
            return
        self.status.setText(f"Searching... page {done} of {total}  -  {len(self._hits)} found")

    def _on_finished(self, count: int, cancelled: bool) -> None:
        if self.sender() is not self._worker:
            return
        self._worker = None
        self.stop.setEnabled(False)
        if cancelled:
            msg = f"Search stopped - {count} matches so far."
        elif count == 0:
            msg = f'No matches for "{self._last_query}".'
            if self.scanned_pages:
                msg += (f" {len(self.scanned_pages)} page(s) are scanned images: use OCR > Make Searchable PDF "
                        "so their text can be found.")
        else:
            msg = f'{count} matches for "{self._last_query}".  F3 = next, Shift+F3 = previous.'
        self.status.setText(msg)
        self.statusChanged.emit(msg)

    def _row_changed(self, row: int) -> None:
        if 0 <= row < len(self._hits):
            self._index = row
            self.hitActivated.emit(self._hits[row])
            self.statusChanged.emit(f"Match {row + 1} of {len(self._hits)}")
