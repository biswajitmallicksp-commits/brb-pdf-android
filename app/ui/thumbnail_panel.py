"""Page thumbnails, rendered lazily as you scroll.

`ThumbnailPanel` is the strip in the left panel. `app/ui/page_organizer.py`
builds the large page-organiser grid on the same class.
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem

from app import config
from app.pdf_viewer.document import PdfDocument
from app.pdf_viewer.render_cache import RenderCache
from app.ui.workers import RenderWorker, make_key


class ThumbnailPanel(QListWidget):
    pageActivated = Signal(int)

    KIND = "t"            # render-cache kind
    MAX_LOADED = 300      # icons kept in memory on very long documents

    def __init__(self, doc: PdfDocument, renderer: RenderWorker, cache: RenderCache, parent=None,
                 thumb_width: int = config.THUMB_WIDTH):
        super().__init__(parent)
        self.setObjectName("thumbs")
        self.doc = doc
        self.renderer = renderer
        self.cache = cache
        self.thumb_w = thumb_width
        self.thumb_h = int(thumb_width * 1.42)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(self.thumb_w, self.thumb_h))
        self.setGridSize(QSize(self.thumb_w + 36, self.thumb_h + 34))
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.configure()

        blank = QImage(int(self.thumb_w * 0.72), int(self.thumb_w * 1.02), QImage.Format.Format_RGB32)
        blank.fill(QColor("white"))
        self._blank = QIcon(self._framed(blank))
        self._loaded: set[int] = set()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._request_visible)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._timer.start())
        self.renderer.rendered.connect(self._on_rendered)
        self.rebuild()

    def configure(self) -> None:
        """Layout of the side-panel strip; the organiser overrides this."""
        self.setFlow(QListView.Flow.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.itemClicked.connect(lambda it: self.pageActivated.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.itemActivated.connect(lambda it: self.pageActivated.emit(it.data(Qt.ItemDataRole.UserRole)))

    # ------------------------------------------------------------------ build
    def rebuild(self, select: list[int] | None = None) -> None:
        """(Re)create one item per page - called after pages change."""
        self.blockSignals(True)
        self.clear()
        self._loaded.clear()
        for i in range(self.doc.page_count):
            item = QListWidgetItem(self._blank, self.item_label(i))
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setToolTip(self.item_tooltip(i))
            self.addItem(item)
        for p in select or []:
            if 0 <= p < self.count():
                self.item(p).setSelected(True)
        self.blockSignals(False)
        if select and 0 <= select[0] < self.count():
            self.setCurrentItem(self.item(select[0]), QItemSelectionModel.SelectionFlag.NoUpdate)
            self.scrollToItem(self.item(select[0]), QAbstractItemView.ScrollHint.PositionAtCenter)
        self._timer.start()

    def item_label(self, page: int) -> str:
        return str(page + 1)

    def item_tooltip(self, page: int) -> str:
        w, h = self.doc.page_size(page)
        return f"Page {page + 1}  ({w / 72 * 25.4:.0f} x {h / 72 * 25.4:.0f} mm)"

    # ---------------------------------------------------------------- render
    def _key(self, page: int) -> tuple:
        w, h = self.doc.page_size(page)
        scale = min(self.thumb_w / w, self.thumb_h / h)
        return make_key(self.KIND, page, scale, 0, self.devicePixelRatioF(), self.doc.revision)

    def _visible_range(self) -> tuple[int, int]:
        vp = self.viewport()
        top = self.indexAt(QPoint(10, 10)).row()
        bottom = self.indexAt(QPoint(vp.width() - 10, vp.height() - 10)).row()
        if top < 0:
            top = 0
        if bottom < 0:
            bottom = min(self.count() - 1, top + 30)
        return top, bottom

    def _request_visible(self) -> None:
        if not self.isVisible() or self.count() == 0:
            return
        top, bottom = self._visible_range()
        wanted = []
        for i in range(max(0, top - 4), min(self.count(), bottom + 5)):
            key = self._key(i)
            img = self.cache.get(key)
            if img is not None:
                self._set_icon(i, img)
            else:
                wanted.append(key)
        self.request(wanted)

    def request(self, keys: list[tuple]) -> None:
        self.renderer.request_thumbs(keys)

    def _on_rendered(self, key: tuple, img: QImage) -> None:
        if key[0] == self.KIND and key[5] == self.doc.revision and 0 <= key[1] < self.count():
            self._set_icon(key[1], img)

    def _set_icon(self, page: int, img: QImage) -> None:
        if page in self._loaded:
            return
        self._loaded.add(page)
        framed = self._framed(img)
        icon = QIcon()
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
            icon.addPixmap(framed, mode)          # no colour tint on selected pages
        self.item(page).setIcon(icon)
        if len(self._loaded) > self.MAX_LOADED:
            top, bottom = self._visible_range()
            for pg in list(self._loaded):
                if (pg < top - 60 or pg > bottom + 60) and pg < self.count():
                    self.item(pg).setIcon(self._blank)
                    self._loaded.discard(pg)

    def _framed(self, img: QImage) -> QPixmap:
        """Centre the page image in a fixed-size cell with a thin border, so pages of
        any shape line up and white pages stand out from the background."""
        dpr = img.devicePixelRatio() or 1.0
        canvas = QPixmap(int(self.thumb_w * dpr), int(self.thumb_h * dpr))
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(Qt.GlobalColor.transparent)
        w = min(self.thumb_w, img.width() / dpr)
        h = min(self.thumb_h, img.height() / dpr)
        x = (self.thumb_w - w) / 2
        y = (self.thumb_h - h) / 2
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(QRectF(x + 2, y + 2, w, h), QColor(0, 0, 0, 45))      # soft shadow
        painter.drawImage(QRectF(x, y, w, h), img)
        painter.setPen(QPen(QColor(150, 155, 162), 1))
        painter.drawRect(QRectF(x, y, w - 1, h - 1))
        painter.end()
        return canvas

    def set_current(self, page: int) -> None:
        if 0 <= page < self.count():
            self.blockSignals(True)
            self.setCurrentRow(page)
            self.blockSignals(False)
            self.scrollToItem(self.item(page), QAbstractItemView.ScrollHint.PositionAtCenter)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._timer.start()
