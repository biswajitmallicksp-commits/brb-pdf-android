"""Background workers: page rendering and text search.

Both run in their own threads so the window never freezes, even on a
600-page scanned document. Access to the PDF itself is serialised by the
lock inside PdfDocument.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QMutex, QMutexLocker, QThread, QWaitCondition, Signal, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from app.pdf_viewer.document import PdfDocument
from app.pdf_viewer.render_cache import RenderCache

log = logging.getLogger("pdfworkbench.workers")

# Render key: (kind, page_index, scale_milli, rotation, dpr_milli)
#   kind 'p' = page in the main view, 't' = thumbnail, 'o' = page organiser


def make_key(kind: str, page: int, scale: float, rotation: int, dpr: float, revision: int = 0) -> tuple:
    """Cache key of one rendered image. `revision` (PdfDocument.revision) changes when pages
    are edited, so an image of an old page is never shown for a new one."""
    return (kind, page, int(round(scale * 1000)), rotation, int(round(dpr * 1000)), revision)


def image_bytes(img: QImage) -> int:
    return img.sizeInBytes()


class RenderWorker(QThread):
    """Renders requested pages newest-request-first; stale requests are dropped."""

    rendered = Signal(object, QImage)

    def __init__(self, doc: PdfDocument, page_cache: RenderCache, thumb_cache: RenderCache, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.page_cache = page_cache
        self.thumb_cache = thumb_cache
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._pages: list[tuple] = []
        self._thumbs: list[tuple] = []
        self._stop = False

    def request_pages(self, keys: list[tuple]) -> None:
        with QMutexLocker(self._mutex):
            self._pages = [k for k in keys if k not in self.page_cache]
            if self._pages:
                self._cond.wakeAll()

    def request_thumbs(self, keys: list[tuple]) -> None:
        with QMutexLocker(self._mutex):
            self._thumbs = [k for k in keys if k not in self.thumb_cache]
            if self._thumbs:
                self._cond.wakeAll()

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stop = True
            self._pages.clear()
            self._thumbs.clear()
            self._cond.wakeAll()

    def run(self) -> None:  # noqa: C901 - simple loop
        while True:
            self._mutex.lock()
            while not self._stop and not self._pages and not self._thumbs:
                self._cond.wait(self._mutex)
            if self._stop:
                self._mutex.unlock()
                return
            if self._pages:
                key = self._pages.pop(0)
                cache = self.page_cache
            else:
                key = self._thumbs.pop(0)
                cache = self.thumb_cache
            self._mutex.unlock()

            if key in cache:
                continue
            kind, page, scale_m, rotation, dpr_m, _rev = key
            dpr = dpr_m / 1000.0
            try:
                if not self.doc.is_open:
                    continue
                r = self.doc.render(page, scale_m / 1000.0 * dpr, rotation)
                img = QImage(r.samples, r.width, r.height, r.stride, QImage.Format.Format_RGB888).copy()
            except Exception as exc:  # never let one bad page stop the viewer
                log.warning("Render failed for page %d: %s", page + 1, exc)
                img = _error_image(self.doc, page, scale_m / 1000.0 * dpr, rotation)
            img.setDevicePixelRatio(dpr)
            cache.put(key, img)
            self.rendered.emit(key, img)


def _error_image(doc: PdfDocument, page: int, scale: float, rotation: int) -> QImage:
    w, h = doc.page_size(page)
    if rotation in (90, 270):
        w, h = h, w
    img = QImage(max(1, int(w * scale)), max(1, int(h * scale)), QImage.Format.Format_RGB888)
    img.fill(QColor("#fbeaea"))
    p = QPainter(img)
    p.setPen(QColor("#9b2c2c"))
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter,
               f"Page {page + 1} could not be displayed.\nSee Help > Open log folder for details.")
    p.end()
    return img


class SearchWorker(QThread):
    """Searches all pages, reporting hits as they are found."""

    hitsFound = Signal(list)          # list[SearchHit]
    progress = Signal(int, int)       # pages done, total
    finishedSearch = Signal(int, bool)  # total hits, cancelled

    def __init__(self, doc: PdfDocument, needle: str, start_page: int = 0, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.needle = needle
        self.start_page = start_page
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        total = self.doc.page_count
        found = 0
        for n in range(total):
            if self._cancel or not self.doc.is_open:
                self.finishedSearch.emit(found, True)
                return
            try:
                hits = self.doc.search_page(n, self.needle)
            except Exception as exc:
                log.warning("Search skipped page %d: %s", n + 1, exc)
                hits = []
            if hits:
                found += len(hits)
                self.hitsFound.emit(hits)
            if n % 10 == 0 or n == total - 1:
                self.progress.emit(n + 1, total)
        self.finishedSearch.emit(found, False)
