"""Page organiser: a grid of large page thumbnails.

* Click, Ctrl+click and Shift+click to select pages; Ctrl+A selects all.
* Drag selected pages to a new place to reorder them.
* Drag PDF or image files from Explorer onto the grid to insert them there.
* Right-click for the page menu; Delete key deletes the selection.

The organiser only reports what the user wants (signals); the document tab
performs the change through PdfDocument.apply_edit, so everything is undoable.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QMenu

from app.pdf_pages.operations import IMAGE_SUFFIXES
from app.ui.thumbnail_panel import ThumbnailPanel

ORGANIZER_THUMB_WIDTH = 150
_ACCEPTED_SUFFIXES = {".pdf"} | IMAGE_SUFFIXES


class PageOrganizer(ThumbnailPanel):
    KIND = "o"
    MAX_LOADED = 400

    movePages = Signal(list, int)          # pages (0-based), insert before this page
    filesDropped = Signal(list, int)       # file paths, insert before this page
    contextMenuWanted = Signal(QPoint)     # global position
    deletePressed = Signal()

    def __init__(self, doc, renderer, cache, parent=None):
        self._drop_before: int | None = None
        super().__init__(doc, renderer, cache, parent, thumb_width=ORGANIZER_THUMB_WIDTH)
        self.setObjectName("organizer")

    def configure(self) -> None:
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setSpacing(6)
        self.setMovement(QListView.Movement.Snap)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)              # we draw our own insertion bar
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.contextMenuWanted.emit(self.viewport().mapToGlobal(pos)))
        self.itemDoubleClicked.connect(lambda it: self.pageActivated.emit(it.data(Qt.ItemDataRole.UserRole)))

    def item_tooltip(self, page: int) -> str:
        return super().item_tooltip(page) + "\nDrag to move. Double-click to open in the viewer."

    # ------------------------------------------------------------- selection
    def selected_pages(self) -> list[int]:
        return sorted(self.row(it) for it in self.selectedItems())

    def select_pages(self, pages: list[int]) -> None:
        self.clearSelection()
        for p in pages:
            if 0 <= p < self.count():
                self.item(p).setSelected(True)
        if pages and 0 <= pages[0] < self.count():
            self.scrollToItem(self.item(pages[0]), QAbstractItemView.ScrollHint.EnsureVisible)

    # ---------------------------------------------------------- drop position
    def drop_position(self, pos: QPoint) -> int:
        """Page number before which a drop at `pos` (viewport coords) inserts."""
        idx = self.indexAt(pos)
        if idx.isValid():
            rect = self.visualRect(idx)
            return idx.row() + (1 if pos.x() > rect.center().x() else 0)
        # empty area: find the nearest item in the same row, else the end
        best, best_dist = self.count(), None
        for row in range(self.count()):
            rect = self.visualRect(self.model().index(row, 0))
            if rect.top() <= pos.y() <= rect.bottom():
                dist = abs(rect.center().x() - pos.x())
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = row + (1 if pos.x() > rect.center().x() else 0)
        return best

    def _files_from(self, mime) -> list[str]:
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in _ACCEPTED_SUFFIXES]

    def dragEnterEvent(self, event) -> None:
        if event.source() is self or self._files_from(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.source() is self or self._files_from(event.mimeData()):
            self._drop_before = self.drop_position(event.position().toPoint())
            event.setDropAction(Qt.DropAction.MoveAction if event.source() is self else Qt.DropAction.CopyAction)
            event.accept()
            self.viewport().update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drop_before = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        before = self.drop_position(event.position().toPoint())
        self._drop_before = None
        self.viewport().update()
        if event.source() is self:
            pages = self.selected_pages()
            # Tell Qt we handled it ourselves; the list is rebuilt from the document.
            event.setDropAction(Qt.DropAction.IgnoreAction)
            event.accept()
            if pages:
                self.movePages.emit(pages, before)
            return
        files = self._files_from(event.mimeData())
        if files:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.filesDropped.emit(files, before)
        else:
            event.ignore()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_before is None or self.count() == 0:
            return
        # vertical insertion bar between thumbnails
        if self._drop_before < self.count():
            rect: QRect = self.visualRect(self.model().index(self._drop_before, 0))
            x = rect.left() - 3
        else:
            rect = self.visualRect(self.model().index(self.count() - 1, 0))
            x = rect.right() + 3
        p = QPainter(self.viewport())
        p.setPen(QPen(QColor(47, 111, 219), 4))
        p.drawLine(x, rect.top() + 4, x, rect.bottom() - 4)
        p.end()

    # ----------------------------------------------------------------- keys
    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.deletePressed.emit()
            return
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.selectAll()
            return
        super().keyPressEvent(event)


def build_context_menu(parent, actions: dict, selected: int) -> QMenu:
    """Right-click menu of the organiser, built from the main window's actions."""
    menu = QMenu(parent)
    for key in ("pg_rotate_cw", "pg_rotate_ccw", None, "pg_duplicate", "pg_move", "pg_delete", None,
                "pg_extract", "pg_replace", None, "pg_insert_blank", "pg_insert_file"):
        if key is None:
            menu.addSeparator()
        else:
            menu.addAction(actions[key])
    return menu
