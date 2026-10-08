"""One open document = one tab: side panels + viewer (or page organiser), and its own workers."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget

from app import config
from app.pdf_pages.operations import PageOpError
from app.pdf_viewer.document import PdfDocument
from app.pdf_viewer.render_cache import RenderCache
from app.ui.ocr_ui import ScanCheckWorker, ScannedBanner
from app.ui.page_organizer import PageOrganizer
from app.ui.page_view import PageView
from app.ui.properties_panel import CommentsPanel
from app.ui.side_panels import BookmarksPanel, SearchPanel
from app.ui.thumbnail_panel import ThumbnailPanel
from app.ui.workers import RenderWorker, image_bytes

log = logging.getLogger("pdfworkbench.tab")


class DocumentTab(QWidget):
    statusMessage = Signal(str)
    scannedChecked = Signal(list)
    documentChanged = Signal()           # pages edited, undone, redone or saved
    editFailed = Signal(str, str)        # operation, message
    organizerToggled = Signal(bool)

    def __init__(self, doc: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.page_cache = RenderCache(config.RENDER_CACHE_MB, image_bytes)
        self.thumb_cache = RenderCache(config.THUMB_CACHE_MB, image_bytes)
        self.renderer = RenderWorker(doc, self.page_cache, self.thumb_cache)
        self.renderer.start()

        self.view = PageView(doc, self.renderer, self.page_cache)
        self.organizer = PageOrganizer(doc, self.renderer, self.thumb_cache)
        self.thumbs = ThumbnailPanel(doc, self.renderer, self.thumb_cache)
        self.bookmarks = BookmarksPanel(doc.outline())
        self.search = SearchPanel(doc)

        self.side = QTabWidget()
        self.side.setObjectName("sidePanel")
        self.side.setDocumentMode(True)
        self.side.addTab(self.thumbs, "Pages")
        self.side.addTab(self.bookmarks, "Bookmarks")
        self.side.addTab(self.search, "Search")
        self.comments = CommentsPanel()
        self.side.addTab(self.comments, "Comments")
        self.side.currentChanged.connect(lambda _i: self._load_comments_if_visible())
        if doc.outline():
            self.side.setCurrentWidget(self.bookmarks)

        self.center = QStackedWidget()
        self.center.addWidget(self.view)          # 0: reading
        self.center.addWidget(self.organizer)     # 1: organise pages

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.side)
        self.splitter.addWidget(self.center)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([290, 1000])
        self.splitter.setCollapsible(1, False)

        self.banner = ScannedBanner()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.banner)
        lay.addWidget(self.splitter, 1)

        # find scanned pages in the background (None = not checked yet)
        self.scanned_pages: list[int] | None = None
        self.scan_check: ScanCheckWorker | None = None
        self._start_scan_check()

        # wiring
        self.thumbs.pageActivated.connect(self.view.goto_page)
        self.bookmarks.pageActivated.connect(self.view.goto_page)
        self.view.currentPageChanged.connect(self.thumbs.set_current)
        self.search.hitsAdded.connect(self.view.add_search_hits)
        self.search.hitsCleared.connect(self.view.clear_search)
        self.search.hitActivated.connect(self.view.show_hit)
        self.search.statusChanged.connect(self.statusMessage)
        self.organizer.pageActivated.connect(self._open_from_organizer)
        self.organizer.movePages.connect(self._move_from_drag)

    # ------------------------------------------------------------ scanned pages
    def _start_scan_check(self) -> None:
        if self.scan_check is not None:
            self.scan_check.stop()
            self.scan_check.wait(5000)
        self.scan_check = ScanCheckWorker(self.doc)
        self.scan_check.checked.connect(self._on_scan_checked)
        self.scan_check.start()

    def _on_scan_checked(self, pages: list, total: int) -> None:
        if self.sender() is not self.scan_check:
            return
        self.scanned_pages = pages
        self.banner.show_for(pages, total)
        self.search.scanned_pages = pages
        self.scannedChecked.emit(pages)

    # ----------------------------------------------------------------- basics
    @property
    def title(self) -> str:
        return self.doc.title

    def side_panel_visible(self) -> bool:
        return self.side.isVisible()

    def set_side_panel_visible(self, visible: bool) -> None:
        self.side.setVisible(visible)

    def show_search(self, text: str | None = None) -> None:
        self.show_organizer(False)
        self.side.setVisible(True)
        self.side.setCurrentWidget(self.search)
        if text is not None:
            self.search.start_search(text)
        else:
            self.search.edit.setFocus()

    # ---------------------------------------------------------------- organiser
    @property
    def organizer_visible(self) -> bool:
        return self.center.currentWidget() is self.organizer

    def show_organizer(self, on: bool) -> None:
        if on == self.organizer_visible:
            return
        if on:
            self.center.setCurrentWidget(self.organizer)
            self.organizer.select_pages([self.view.current_page])
            self.organizer.setFocus()
        else:
            self.center.setCurrentWidget(self.view)
            self.view.setFocus()
        self.organizerToggled.emit(on)

    def _open_from_organizer(self, page: int) -> None:
        self.show_organizer(False)
        self.view.goto_page(page)

    def target_pages(self) -> list[int]:
        """Pages an operation applies to: the organiser selection, else the current page."""
        if self.organizer_visible:
            sel = self.organizer.selected_pages()
            if sel:
                return sel
        return [self.view.current_page]

    # -------------------------------------------------------------------- edits
    def _layout_signature(self) -> list:
        return [self.doc.page_size(i) for i in range(self.doc.page_count)]

    def run_edit(self, label: str, func, select=None, show_page: int | None = None):
        """Apply an undoable change. `select(result)` (or a list) = pages to select afterwards."""
        self._before = self._layout_signature()
        try:
            result = self.doc.apply_edit(label, func)
        except PageOpError as exc:
            self.editFailed.emit(label, str(exc))
            return None
        except Exception as exc:
            log.exception("%s failed", label)
            self.editFailed.emit(label, f"Unexpected error: {exc}\n\nThe document was not changed.")
            return None
        pages = select(result) if callable(select) else select
        self.refresh(pages, show_page)
        self.statusMessage.emit(f"{label} - Ctrl+Z to undo")
        return result

    def _move_from_drag(self, pages: list, before: int) -> None:
        from app.pdf_pages import operations as ops
        if not pages or ops.move_order(self.doc.page_count, pages, before) == list(range(self.doc.page_count)):
            return
        n = len(pages)
        self.run_edit(f"Move {n} page{'s' if n > 1 else ''}", lambda d: ops.move_pages(d, pages, before),
                      select=lambda new: new)

    def undo(self) -> str | None:
        self._before = self._layout_signature()
        label = self.doc.undo()
        if label:
            self.refresh(None)
        return label

    def redo(self) -> str | None:
        self._before = self._layout_signature()
        label = self.doc.redo()
        if label:
            self.refresh(None)
        return label

    def refresh(self, select: list[int] | None = None, show_page: int | None = None) -> None:
        """Rebuild everything that depends on the pages after a change."""
        same_layout = getattr(self, "_before", None) == self._layout_signature()
        self._before = None
        if same_layout and show_page is None and not select:
            self._light_refresh()
            return
        n = self.doc.page_count
        if select:
            select = [p for p in select if 0 <= p < n]
        target = show_page if show_page is not None else (select[0] if select else None)
        self.search.reset()
        self.view.document_changed(target)
        self.thumbs.rebuild([self.view.current_page])
        self.organizer.rebuild(select or [self.view.current_page])
        self.bookmarks.load(self.doc.outline())
        self.scanned_pages = None
        self._start_scan_check()
        self._load_comments_if_visible()
        self.documentChanged.emit()

    def _light_refresh(self) -> None:
        """Page content changed (annotations, text...) but no page moved: keep the scroll position."""
        self.view._lines_cache.clear()
        self.view.viewport().update()          # re-renders with the new revision; old image shown meanwhile
        for panel in (self.thumbs, self.organizer):
            panel._loaded.clear()
            panel._timer.start()
        self.bookmarks.load(self.doc.outline())
        self._start_scan_check()
        self._load_comments_if_visible()
        self.documentChanged.emit()

    def _load_comments_if_visible(self) -> None:
        if self.side.isVisible() and self.side.currentWidget() is self.comments:
            self.comments.load(self.doc)

    # -------------------------------------------------------------------- close
    def close_document(self) -> None:
        try:
            self.search.cancel()
            if self.scan_check is not None:
                self.scan_check.stop()
                self.scan_check.wait(5000)
            self.renderer.stop()
            self.renderer.wait(5000)
        finally:
            self.doc.close()
            self.page_cache.clear()
            self.thumb_cache.clear()
            log.info("Closed %s", self.doc.path)
