"""The document viewer widget.

Design notes
------------
* Only pages that are on screen (plus a small look-ahead) are rendered.
  Rendering happens in RenderWorker; this widget only paints what is
  already in the cache, and shows a blank page (or the previous zoom level
  scaled) until the sharp image arrives.
* Page geometry is computed from page sizes alone, so opening a 2,000-page
  file is instant.
* Three layouts: continuous (one column), single page, two pages side by
  side (continuous).
"""
from __future__ import annotations

import bisect
import logging

import pymupdf as fitz
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QKeySequence
from PySide6.QtWidgets import QAbstractScrollArea

from app import config
from app.pdf_viewer.document import PdfDocument, SearchHit, TextSelection
from app.pdf_viewer.render_cache import RenderCache
from app.ui.workers import RenderWorker, make_key

log = logging.getLogger("pdfworkbench.view")

MODE_CONTINUOUS = "continuous"
MODE_SINGLE = "single"
MODE_TWO = "two"

FIT_WIDTH = "width"
FIT_PAGE = "page"

TOOL_SELECT = "select"
TOOL_HAND = "hand"

# Editing / comment tools (Phase 3). The view only reports what the user drew (signals);
# the main window performs the change through the undoable edit system.
TEXT_TOOLS = {"highlight": "Highlight", "underline": "Underline", "strike": "StrikeOut", "squiggly": "Squiggly"}
AREA_TOOLS = {"textbox", "rect", "ellipse", "redact", "add_text", "add_image", "delete_text", "delete_image"}
LINE_TOOLS = {"line", "arrow"}
POINT_TOOLS = {"note", "stamp", "edit_text", "eraser"}
TOOL_PEN = "pen"
DRAW_COLOR = QColor(47, 111, 219)


class PageView(QAbstractScrollArea):
    currentPageChanged = Signal(int)
    zoomChanged = Signal(float)
    selectionChanged = Signal(str)
    layoutChanged = Signal()
    # editing signals - geometry is in UNROTATED page space (pymupdf objects)
    markupRequested = Signal(str, int, list)            # tool, page, word rects
    areaRequested = Signal(str, int, object)            # tool, page, fitz.Rect (may be tiny = click)
    lineRequested = Signal(str, int, object, object)    # tool, page, start, end
    inkRequested = Signal(int, list)                    # page, list of strokes (lists of fitz.Point)
    pointRequested = Signal(str, int, object)           # tool, page, fitz.Point
    annotSelected = Signal(object)                      # AnnotInfo or None
    annotMoveRequested = Signal(int, int, float, float) # page, xref, dx, dy
    annotResizeRequested = Signal(int, int, object)     # page, xref, new fitz.Rect
    annotEditRequested = Signal(object)                 # AnnotInfo (double-click)
    annotDeleteRequested = Signal(object)               # AnnotInfo (Delete key)
    toolChanged = Signal(str)

    def __init__(self, doc: PdfDocument, renderer: RenderWorker, cache: RenderCache, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.renderer = renderer
        self.cache = cache
        self.dark = False

        self._zoom = config.DEFAULT_ZOOM
        self._fit: str | None = FIT_WIDTH
        self._rotation = 0
        self._mode = MODE_CONTINUOUS
        self._current = 0
        self._tool = TOOL_SELECT
        self._base = max(self.logicalDpiX(), 72) / 72.0     # 100 % = real size on screen

        self._items: list[tuple[int, QRectF]] = []     # (page, rect in content coords)
        self._tops: list[float] = []                   # for bisect, sorted
        self._page_rect: dict[int, QRectF] = {}
        self._content_w = 0.0
        self._content_h = 0.0
        self._fallback: dict[int, QImage] = {}
        self._matrix_cache: dict[tuple, fitz.Matrix] = {}

        self._hits: dict[int, list[fitz.Rect]] = {}
        self._current_hit: SearchHit | None = None
        self._selection: TextSelection | None = None
        self._band_start: QPointF | None = None        # content coords
        self._band_end: QPointF | None = None
        self._pan_origin: QPoint | None = None
        self._pan_scroll = (0, 0)
        self._sel_annot = None              # AnnotInfo of the selected annotation
        self._drag: dict | None = None      # current drag (move / resize / shape / line / ink)
        self._hover_line: tuple[int, fitz.Rect] | None = None
        self._lines_cache: dict[tuple, list] = {}

        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        self.renderer.rendered.connect(self._on_rendered)
        self._apply_cursor()

        # compute fit zoom once the widget has its real size
        QTimer.singleShot(0, self._refit)
        self._relayout()

    # ================================================================ public API
    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def scale(self) -> float:
        """Logical pixels per PDF point."""
        return self._zoom * self._base

    @property
    def rotation(self) -> int:
        return self._rotation

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def fit_mode(self) -> str | None:
        return self._fit

    @property
    def current_page(self) -> int:
        return self._current

    @property
    def tool(self) -> str:
        return self._tool

    @property
    def selected_text(self) -> str:
        return self._selection.text if self._selection else ""

    def set_dark(self, dark: bool) -> None:
        self.dark = dark
        self.viewport().update()

    def set_tool(self, tool: str) -> None:
        if tool != self._tool:
            self._tool = tool
            self._drag = None
            self._hover_line = None
            if tool != TOOL_SELECT:
                self.select_annot(None)
            self._apply_cursor()
            self.viewport().update()
            self.toolChanged.emit(tool)

    # ---------------------------------------------------------- annotations
    @property
    def selected_annot(self):
        return self._sel_annot

    def select_annot(self, info) -> None:
        """Select an annotation (AnnotInfo) or clear the selection (None)."""
        self._sel_annot = info
        self.annotSelected.emit(info)
        self.viewport().update()

    def reselect(self, page: int, xref: int) -> None:
        """Select the annotation with `xref` on `page` again (after it was changed)."""
        from app.pdf_annotation import annots
        try:
            infos = self.doc.run_read(lambda d: annots.list_annots(d[page]))
        except Exception:
            infos = []
        self.select_annot(next((i for i in infos if i.xref == xref), None))

    def _annot_at(self, page: int, pt: fitz.Point):
        from app.pdf_annotation import annots
        try:
            return self.doc.run_read(lambda d: annots.annot_at(d[page], pt))
        except Exception:
            return None

    def set_zoom(self, zoom: float, anchor: QPoint | None = None) -> None:
        zoom = max(config.MIN_ZOOM, min(config.MAX_ZOOM, zoom))
        self._fit = None
        self._apply_zoom(zoom, anchor)

    def zoom_in(self) -> None:
        bigger = [z for z in config.ZOOM_STEPS if z > self._zoom + 1e-3]
        self.set_zoom(bigger[0] if bigger else config.MAX_ZOOM)

    def zoom_out(self) -> None:
        smaller = [z for z in config.ZOOM_STEPS if z < self._zoom - 1e-3]
        self.set_zoom(smaller[-1] if smaller else config.MIN_ZOOM)

    def fit_width(self) -> None:
        self._fit = FIT_WIDTH
        self._refit()

    def fit_page(self) -> None:
        self._fit = FIT_PAGE
        self._refit()

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        page = self._current
        self._mode = mode
        self._relayout()
        self._refit()
        self.goto_page(page)

    def rotate(self, delta: int) -> None:
        page = self._current
        self._rotation = (self._rotation + delta) % 360
        self._fallback.clear()
        self._relayout()
        self._refit()
        self.goto_page(page)

    def goto_page(self, index: int, y_fraction: float = 0.0) -> None:
        if self.doc.page_count == 0:
            return
        index = max(0, min(self.doc.page_count - 1, index))
        if self._mode == MODE_SINGLE:
            if index != self._current:
                self._current = index
                self._relayout()
                self._refit()
            self.verticalScrollBar().setValue(0)
            self._set_current(index, force=True)
            return
        rect = self._page_rect.get(index)
        if rect is None:
            return
        self._set_current(index, force=True)
        target = rect.top() - config.PAGE_GAP + y_fraction * rect.height()
        self.verticalScrollBar().setValue(int(target))
        self.viewport().update()

    def document_changed(self, show_page: int | None = None) -> None:
        """Pages were added, removed, moved or rotated: rebuild the layout."""
        n = self.doc.page_count
        target = self._current if show_page is None else show_page
        target = max(0, min(n - 1, target))
        self._fallback.clear()
        self._matrix_cache.clear()
        self._hits = {}
        self._current_hit = None
        self._selection = None
        self._sel_annot = None
        self._lines_cache.clear()
        self._current = target
        self._relayout()
        if self._fit is not None:
            self._refit()
        self.goto_page(target)
        self.selectionChanged.emit("")
        self.viewport().update()

    def next_page(self) -> None:
        step = 2 if self._mode == MODE_TWO else 1
        self.goto_page(self._current + step)

    def prev_page(self) -> None:
        step = 2 if self._mode == MODE_TWO else 1
        self.goto_page(self._current - step)

    # ------------------------------------------------------------ search hits
    def set_search_hits(self, hits: list[SearchHit]) -> None:
        self._hits = {}
        for h in hits:
            self._hits.setdefault(h.page, []).append(h.rect)
        self.viewport().update()

    def add_search_hits(self, hits: list[SearchHit]) -> None:
        for h in hits:
            self._hits.setdefault(h.page, []).append(h.rect)
        self.viewport().update()

    def clear_search(self) -> None:
        self._hits = {}
        self._current_hit = None
        self.viewport().update()

    def show_hit(self, hit: SearchHit) -> None:
        """Scroll so the hit is visible (about a third from the top)."""
        self._current_hit = hit
        if self._mode == MODE_SINGLE and hit.page != self._current:
            self.goto_page(hit.page)
        page_rect = self._page_rect.get(hit.page)
        if page_rect is None:
            self.goto_page(hit.page)
            page_rect = self._page_rect.get(hit.page)
            if page_rect is None:
                return
        vr = self._to_view_rect(hit.page, hit.rect).translated(page_rect.topLeft())
        vp = self.viewport().rect()
        view_top = self.verticalScrollBar().value()
        if not (view_top + 20 < vr.top() and vr.bottom() < view_top + vp.height() - 20):
            self.verticalScrollBar().setValue(int(vr.top() - vp.height() / 3))
        left = self.horizontalScrollBar().value() - self._x_offset()
        if not (left < vr.left() and vr.right() < left + vp.width()):
            self.horizontalScrollBar().setValue(int(vr.center().x() - vp.width() / 2 + self._x_offset()))
        self._set_current(hit.page, force=True)
        self.viewport().update()

    # -------------------------------------------------------------- selection
    def clear_selection(self) -> None:
        if self._selection is not None:
            self._selection = None
            self.selectionChanged.emit("")
            self.viewport().update()

    def select_all_on_page(self) -> str:
        try:
            self._selection = self.doc.all_words(self._current)
        except Exception as exc:
            log.warning("Select all failed: %s", exc)
            self._selection = None
        self.selectionChanged.emit(self.selected_text)
        self.viewport().update()
        return self.selected_text

    def copy_selection(self) -> bool:
        text = self.selected_text
        if text:
            QGuiApplication.clipboard().setText(text)
            return True
        return False

    # =============================================================== geometry
    def _page_view_size(self, index: int) -> tuple[float, float]:
        w, h = self.doc.page_size(index)
        if self._rotation in (90, 270):
            w, h = h, w
        s = self.scale
        return w * s, h * s

    def _pages_in_layout(self) -> list[list[int]]:
        n = self.doc.page_count
        if n == 0:
            return []
        if self._mode == MODE_SINGLE:
            return [[self._current]]
        if self._mode == MODE_TWO:
            return [[i, i + 1] if i + 1 < n else [i] for i in range(0, n, 2)]
        return [[i] for i in range(n)]

    def _relayout(self) -> None:
        gap = config.PAGE_GAP
        rows = self._pages_in_layout()
        row_sizes = []
        max_w = 0.0
        for row in rows:
            sizes = [self._page_view_size(i) for i in row]
            width = sum(s[0] for s in sizes) + gap * (len(sizes) - 1)
            height = max(s[1] for s in sizes)
            row_sizes.append((sizes, width, height))
            max_w = max(max_w, width)
        self._content_w = max_w + 2 * gap
        items: list[tuple[int, QRectF]] = []
        y = gap
        for row, (sizes, width, height) in zip(rows, row_sizes):
            x = (self._content_w - width) / 2
            for page, (w, h) in zip(row, sizes):
                items.append((page, QRectF(x, y + (height - h) / 2, w, h)))
                x += w + gap
            y += height + gap
        self._content_h = y
        self._items = items
        self._tops = [r.top() for _, r in items]
        self._page_rect = {p: r for p, r in items}
        self._matrix_cache.clear()
        self._update_scrollbars()
        self.layoutChanged.emit()
        self.viewport().update()

    def _update_scrollbars(self) -> None:
        vp = self.viewport().size()
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        hbar.setRange(0, max(0, int(self._content_w - vp.width())))
        hbar.setPageStep(vp.width())
        hbar.setSingleStep(40)
        vbar.setRange(0, max(0, int(self._content_h - vp.height())))
        vbar.setPageStep(vp.height())
        vbar.setSingleStep(48)

    def _x_offset(self) -> float:
        """Horizontal offset that centres narrow content in a wide window."""
        return max(0.0, (self.viewport().width() - self._content_w) / 2)

    def _content_to_viewport(self, pt: QPointF) -> QPointF:
        return QPointF(pt.x() - self.horizontalScrollBar().value() + self._x_offset(),
                       pt.y() - self.verticalScrollBar().value())

    def _viewport_to_content(self, pt: QPointF) -> QPointF:
        return QPointF(pt.x() + self.horizontalScrollBar().value() - self._x_offset(),
                       pt.y() + self.verticalScrollBar().value())

    def _page_at(self, content_pt: QPointF) -> int | None:
        for page, rect in self._visible_items(QRectF(content_pt.x() - 1, content_pt.y() - 1, 2, 2)):
            if rect.contains(content_pt):
                return page
        return None

    def _visible_items(self, area: QRectF) -> list[tuple[int, QRectF]]:
        if not self._items:
            return []
        # items are sorted by top; start a bit before the first candidate
        start = max(0, bisect.bisect_left(self._tops, area.top()) - 2)
        out = []
        for page, rect in self._items[start:]:
            if rect.top() > area.bottom():
                break
            if rect.intersects(area):
                out.append((page, rect))
        return out

    def _matrix(self, page: int) -> fitz.Matrix:
        key = (page, round(self.scale, 5), self._rotation)
        m = self._matrix_cache.get(key)
        if m is None:
            m = self.doc.view_matrix(page, self.scale, self._rotation)
            self._matrix_cache[key] = m
        return m

    def _to_view_rect(self, page: int, rect: fitz.Rect) -> QRectF:
        r = fitz.Rect(rect) * self._matrix(page)
        return QRectF(r.x0, r.y0, r.width, r.height)

    def _to_page_rect(self, page: int, view_rect: QRectF) -> fitz.Rect:
        inv = ~self._matrix(page)
        r = fitz.Rect(view_rect.left(), view_rect.top(), view_rect.right(), view_rect.bottom()) * inv
        r.normalize()
        return r

    # ================================================================ zooming
    def _fit_zoom(self) -> float | None:
        if self._fit is None or self.doc.page_count == 0:
            return None
        vp = self.viewport().size()
        gap = config.PAGE_GAP
        if self._mode == MODE_TWO:
            first = self._current - (self._current % 2)
            pages = [first] + ([first + 1] if first + 1 < self.doc.page_count else [])
        else:
            pages = [self._current]
        widths, heights = [], []
        for i in pages:
            w, h = self.doc.page_size(i)
            if self._rotation in (90, 270):
                w, h = h, w
            widths.append(w)
            heights.append(h)
        avail_w = vp.width() - 2 * gap - gap * (len(pages) - 1)
        zw = avail_w / (sum(widths) * self._base)
        if self._fit == FIT_WIDTH:
            return zw
        zh = (vp.height() - 2 * gap) / (max(heights) * self._base)
        return min(zw, zh)

    def _refit(self) -> None:
        z = self._fit_zoom()
        if z is not None:
            self._apply_zoom(max(config.MIN_ZOOM, min(config.MAX_ZOOM, z)), None)
            self._center_horizontally()

    def _center_horizontally(self) -> None:
        """Centre the current page (or pair) when the layout is wider than the window,
        e.g. a landscape page elsewhere in the document widens the content."""
        hbar = self.horizontalScrollBar()
        if hbar.maximum() == 0:
            return
        if self._mode == MODE_TWO:
            first = self._current - (self._current % 2)
            rects = [self._page_rect[p] for p in (first, first + 1) if p in self._page_rect]
        else:
            rects = [self._page_rect[self._current]] if self._current in self._page_rect else []
        if rects:
            cx = (min(r.left() for r in rects) + max(r.right() for r in rects)) / 2
            hbar.setValue(int(cx - self.viewport().width() / 2))

    def _apply_zoom(self, zoom: float, anchor: QPoint | None) -> None:
        if abs(zoom - self._zoom) < 1e-4 and self._items:
            self.zoomChanged.emit(self._zoom)
            return
        # remember which point stays put: the anchor, or the top of the view
        vp = self.viewport()
        anchor_vp = QPointF(anchor) if anchor is not None else QPointF(vp.width() / 2, 0)
        content_pt = self._viewport_to_content(anchor_vp)
        page = self._page_at(content_pt)
        rel = None
        if page is not None:
            r = self._page_rect[page]
            rel = ((content_pt.x() - r.left()) / r.width(), (content_pt.y() - r.top()) / r.height())
        else:
            page = self._current
        self._zoom = zoom
        self._relayout()
        r = self._page_rect.get(page)
        if r is not None:
            if rel is None:
                rel = (0.5, 0.0)
                new_pt = QPointF(r.left() + rel[0] * r.width(), r.top() - config.PAGE_GAP)
            else:
                new_pt = QPointF(r.left() + rel[0] * r.width(), r.top() + rel[1] * r.height())
            self.horizontalScrollBar().setValue(int(new_pt.x() + self._x_offset() - anchor_vp.x()))
            self.verticalScrollBar().setValue(int(new_pt.y() - anchor_vp.y()))
        self.zoomChanged.emit(self._zoom)
        self.viewport().update()

    # ============================================================ current page
    def _set_current(self, page: int, force: bool = False) -> None:
        if page != self._current or force:
            changed = page != self._current
            self._current = page
            if changed or force:
                self.currentPageChanged.emit(page)

    def _on_scrolled(self, _value: int) -> None:
        if self._mode != MODE_SINGLE and self._items:
            probe_y = self.verticalScrollBar().value() + self.viewport().height() * 0.3
            idx = max(0, bisect.bisect_right(self._tops, probe_y) - 1)
            page = self._items[idx][0]
            if page != self._current:
                self._current = page
                self.currentPageChanged.emit(page)
        self.viewport().update()

    # ================================================================ painting
    def _on_rendered(self, key: tuple, _img: QImage) -> None:
        if key[0] == "p":
            self.viewport().update()

    def _key(self, page: int) -> tuple:
        return make_key("p", page, self.scale, self._rotation, self.devicePixelRatioF(), self.doc.revision)

    def paintEvent(self, _event) -> None:  # noqa: C901
        p = QPainter(self.viewport())
        vp = self.viewport().rect()
        from app.ui.theme import viewer_background
        p.fillRect(vp, viewer_background(self.dark))
        if not self._items:
            p.end()
            return

        visible_area = QRectF(self._viewport_to_content(QPointF(0, 0)), self._viewport_to_content(QPointF(vp.width(), vp.height())))
        visible = self._visible_items(visible_area)
        needed: list[tuple] = []
        shadow = QColor(0, 0, 0, 60)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        for page, rect in visible:
            target = QRectF(self._content_to_viewport(rect.topLeft()), rect.size())
            p.fillRect(target.translated(2, 3), shadow)
            p.fillRect(target, QColor("white"))
            key = self._key(page)
            img = self.cache.get(key)
            if img is not None:
                p.drawImage(target, img)
                self._fallback[page] = img
            else:
                fb = self._fallback.get(page)
                if fb is not None:
                    p.drawImage(target, fb)
                needed.append(key)
            self._paint_overlays(p, page, target)

        # rubber band for text selection
        if self._band_start is not None and self._band_end is not None:
            band = QRectF(self._content_to_viewport(self._band_start), self._content_to_viewport(self._band_end)).normalized()
            p.setPen(QPen(QColor(47, 111, 219), 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(47, 111, 219, 30))
            p.drawRect(band)
        p.end()

        # look-ahead: one screen below the visible pages
        ahead = QRectF(visible_area.left(), visible_area.bottom(), visible_area.width(), visible_area.height())
        for page, _rect in self._visible_items(ahead)[:3]:
            k = self._key(page)
            if k not in needed:
                needed.append(k)
        self.renderer.request_pages(needed)

        # forget fallback images far from the view to bound memory
        if len(self._fallback) > 12:
            keep = {pg for pg, _ in visible}
            for pg in list(self._fallback):
                if pg not in keep:
                    del self._fallback[pg]

    def _paint_overlays(self, p: QPainter, page: int, target: QRectF) -> None:
        hits = self._hits.get(page)
        sel = self._selection if self._selection and self._selection.page == page else None
        cur = self._current_hit if self._current_hit and self._current_hit.page == page else None
        ann = self._sel_annot if self._sel_annot is not None and self._sel_annot.page == page else None
        hover = self._hover_line if self._hover_line and self._hover_line[0] == page else None
        drag = self._drag if self._drag and self._drag.get("page") == page else None
        if not (hits or sel or cur or ann or hover or drag):
            return
        p.save()
        p.translate(target.topLeft())
        p.setPen(Qt.PenStyle.NoPen)
        if hits:
            p.setBrush(QColor(255, 214, 0, 95))
            for r in hits:
                p.drawRect(self._to_view_rect(page, r))
        if cur:
            p.setBrush(QColor(255, 128, 0, 120))
            p.setPen(QPen(QColor(230, 90, 0), 1.5))
            p.drawRect(self._to_view_rect(page, cur.rect).adjusted(-1, -1, 1, 1))
            p.setPen(Qt.PenStyle.NoPen)
        if sel:
            p.setBrush(QColor(47, 111, 219, 80))
            for r in sel.rects:
                p.drawRect(self._to_view_rect(page, r))
        if hover:
            p.setBrush(QColor(47, 111, 219, 35))
            p.setPen(QPen(DRAW_COLOR, 1, Qt.PenStyle.DashLine))
            p.drawRect(self._to_view_rect(page, hover[1]).adjusted(-2, -2, 2, 2))
        if ann:
            vr = self._to_view_rect(page, ann.rect).normalized().adjusted(-3, -3, 3, 3)
            if drag and drag["kind"] == "move":
                vr = vr.translated(drag["delta"])
            elif drag and drag["kind"] == "resize":
                vr = QRectF(vr.topLeft(), vr.bottomRight() + drag["delta"]).normalized()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(DRAW_COLOR, 1.5, Qt.PenStyle.DashLine))
            p.drawRect(vr)
            if ann.resizable:
                p.setPen(QPen(QColor("white"), 1))
                p.setBrush(DRAW_COLOR)
                p.drawRect(self._handle_rect(vr))
        if drag and drag["kind"] in ("area", "line", "ink"):
            pen = QPen(DRAW_COLOR, 1.5, Qt.PenStyle.DashLine if drag["kind"] == "area" else Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.setBrush(QColor(47, 111, 219, 25) if drag["kind"] == "area" else Qt.BrushStyle.NoBrush)
            if drag["kind"] == "area":
                r = QRectF(drag["start_local"], drag["end_local"]).normalized()
                p.drawEllipse(r) if drag["tool"] == "ellipse" else p.drawRect(r)
            elif drag["kind"] == "line":
                p.drawLine(drag["start_local"], drag["end_local"])
            else:
                for stroke in drag["strokes"]:
                    for a, b in zip(stroke, stroke[1:]):
                        p.drawLine(a, b)
        p.restore()

    @staticmethod
    def _handle_rect(vr: QRectF) -> QRectF:
        return QRectF(vr.right() - 5, vr.bottom() - 5, 10, 10)

    # ================================================================== events
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit is not None:
            self._refit()
        self._update_scrollbars()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if delta:
                factor = 1.1 ** (delta / 120)
                self._fit = None
                self._apply_zoom(max(config.MIN_ZOOM, min(config.MAX_ZOOM, self._zoom * factor)),
                                 event.position().toPoint())
            event.accept()
            return
        if self._mode == MODE_SINGLE:
            vbar = self.verticalScrollBar()
            if delta < 0 and vbar.value() >= vbar.maximum() and self._current < self.doc.page_count - 1:
                self.goto_page(self._current + 1)
                event.accept()
                return
            if delta > 0 and vbar.value() <= vbar.minimum() and self._current > 0:
                self.goto_page(self._current - 1)
                vbar.setValue(vbar.maximum())
                event.accept()
                return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        vbar = self.verticalScrollBar()
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            return
        if key == Qt.Key.Key_Home:
            self.goto_page(0)
        elif key == Qt.Key.Key_End:
            self.goto_page(self.doc.page_count - 1)
        elif key == Qt.Key.Key_PageDown:
            if self._mode == MODE_SINGLE and vbar.value() >= vbar.maximum():
                self.next_page()
            else:
                vbar.setValue(vbar.value() + int(vbar.pageStep() * 0.9))
        elif key == Qt.Key.Key_PageUp:
            if self._mode == MODE_SINGLE and vbar.value() <= vbar.minimum():
                self.prev_page()
            else:
                vbar.setValue(vbar.value() - int(vbar.pageStep() * 0.9))
        elif key == Qt.Key.Key_Down:
            vbar.setValue(vbar.value() + vbar.singleStep())
        elif key == Qt.Key.Key_Up:
            vbar.setValue(vbar.value() - vbar.singleStep())
        elif key == Qt.Key.Key_Right and self.horizontalScrollBar().maximum() == 0:
            self.next_page()
        elif key == Qt.Key.Key_Left and self.horizontalScrollBar().maximum() == 0:
            self.prev_page()
        elif key == Qt.Key.Key_Escape:
            if self._drag is not None:
                self._drag = None
                self.viewport().update()
            elif self._tool not in (TOOL_SELECT, TOOL_HAND):
                self.set_tool(TOOL_SELECT)
            elif self._sel_annot is not None:
                self.select_annot(None)
            else:
                self.clear_selection()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._sel_annot is not None:
            self.annotDeleteRequested.emit(self._sel_annot)
        else:
            super().keyPressEvent(event)

    def _apply_cursor(self) -> None:
        t = self._tool
        if t == TOOL_HAND:
            shape = Qt.CursorShape.OpenHandCursor
        elif t in AREA_TOOLS or t in LINE_TOOLS or t == TOOL_PEN:
            shape = Qt.CursorShape.CrossCursor
        elif t in POINT_TOOLS:
            shape = Qt.CursorShape.PointingHandCursor
        else:
            shape = Qt.CursorShape.IBeamCursor
        self.viewport().setCursor(shape)

    # --------------------------------------------------------- coordinates
    def _locate(self, content_pt: QPointF, page: int | None = None):
        """(page, local view point, page-space point) for a content point; None if outside pages.
        With `page`, the point is clamped to that page."""
        if page is None:
            page = self._page_at(content_pt)
            if page is None:
                return None
        r = self._page_rect.get(page)
        if r is None:
            return None
        local = QPointF(min(max(content_pt.x(), r.left()), r.right()) - r.left(),
                        min(max(content_pt.y(), r.top()), r.bottom()) - r.top())
        pt = fitz.Point(local.x(), local.y()) * ~self._matrix(page)
        return page, local, pt

    def _to_page_vector(self, page: int, d: QPointF) -> tuple[float, float]:
        inv = ~self._matrix(page)
        a = fitz.Point(0, 0) * inv
        b = fitz.Point(d.x(), d.y()) * inv
        return b.x - a.x, b.y - a.y

    def _line_rects(self, page: int) -> list:
        key = (page, self.doc.revision)
        if key not in self._lines_cache:
            def read(d):
                rects = []
                for block in d[page].get_text("dict").get("blocks", []):
                    for line in block.get("lines", []):
                        if "".join(s["text"] for s in line["spans"]).strip():
                            rects.append(fitz.Rect(line["bbox"]))
                return rects
            try:
                self._lines_cache = {key: self.doc.run_read(read)}
            except Exception:
                self._lines_cache = {key: []}
        return self._lines_cache[key]

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, event) -> None:  # noqa: C901
        self.setFocus()
        pos = event.position()
        content = self._viewport_to_content(pos)
        if event.button() == Qt.MouseButton.MiddleButton or (
                event.button() == Qt.MouseButton.LeftButton and self._tool == TOOL_HAND):
            self._pan_origin = pos.toPoint()
            self._pan_scroll = (self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        loc = self._locate(content)
        tool = self._tool

        if tool == TOOL_SELECT:
            # click on the selected annotation's resize handle / body, or on another annotation
            if loc is not None:
                page, local, pt = loc
                ann = self._sel_annot if self._sel_annot is not None and self._sel_annot.page == page else None
                if ann is not None:
                    vr = self._to_view_rect(page, ann.rect).normalized().adjusted(-3, -3, 3, 3)
                    if ann.resizable and self._handle_rect(vr).adjusted(-3, -3, 3, 3).contains(local):
                        self._drag = dict(kind="resize", page=page, start=pos, delta=QPointF(0, 0))
                        return
                hit = self._annot_at(page, pt)
                if hit is not None:
                    if self._sel_annot is None or hit.xref != self._sel_annot.xref or hit.page != self._sel_annot.page:
                        self.select_annot(hit)
                    if hit.movable:
                        self._drag = dict(kind="move", page=page, start=pos, delta=QPointF(0, 0))
                    return
            if self._sel_annot is not None:
                self.select_annot(None)
            self._start_band(content)
            return

        if loc is None:
            return
        page, local, pt = loc
        if tool in TEXT_TOOLS:
            self._start_band(content)
        elif tool in AREA_TOOLS:
            self._drag = dict(kind="area", tool=tool, page=page, start_local=local, end_local=local, start_pt=pt)
        elif tool in LINE_TOOLS:
            self._drag = dict(kind="line", tool=tool, page=page, start_local=local, end_local=local, start_pt=pt)
        elif tool == TOOL_PEN:
            self._drag = dict(kind="ink", tool=tool, page=page, strokes=[[local]], points=[[pt]])
        elif tool in POINT_TOOLS:
            if tool == "eraser":
                hit = self._annot_at(page, pt)
                if hit is not None:
                    self.annotDeleteRequested.emit(hit)
            else:
                self.pointRequested.emit(tool, page, pt)
        self.viewport().update()

    def _start_band(self, content: QPointF) -> None:
        self._band_start = content
        self._band_end = content
        if self._selection is not None:
            self._selection = None
            self.selectionChanged.emit("")
        self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._pan_origin is not None:
            d = pos.toPoint() - self._pan_origin
            self.horizontalScrollBar().setValue(self._pan_scroll[0] - d.x())
            self.verticalScrollBar().setValue(self._pan_scroll[1] - d.y())
            return
        content = self._viewport_to_content(pos)
        drag = self._drag
        if drag is not None:
            if drag["kind"] in ("move", "resize"):
                drag["delta"] = pos - drag["start"]
            else:
                loc = self._locate(content, drag["page"])
                if loc is not None:
                    _p, local, pt = loc
                    if drag["kind"] == "ink":
                        drag["strokes"][-1].append(local)
                        drag["points"][-1].append(pt)
                    else:
                        drag["end_local"] = local
                        drag["end_pt"] = pt
            self._autoscroll(pos)
            self.viewport().update()
            return
        if self._band_start is not None:
            self._band_end = content
            self._autoscroll(pos)
            self.viewport().update()
            return
        if self._tool == "edit_text":
            loc = self._locate(content)
            hover = None
            if loc is not None:
                page, _local, pt = loc
                for r in self._line_rects(page):
                    if fitz.Rect(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2).contains(pt):
                        hover = (page, r)
                        break
            if hover != self._hover_line:
                self._hover_line = hover
                self.viewport().update()

    def _autoscroll(self, pos: QPointF) -> None:
        if pos.y() > self.viewport().height() - 10:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + 20)
        elif pos.y() < 10:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - 20)

    def mouseReleaseEvent(self, event) -> None:  # noqa: C901
        if self._pan_origin is not None:
            self._pan_origin = None
            self._apply_cursor()
            return
        drag, self._drag = self._drag, None
        if drag is not None:
            page = drag["page"]
            kind = drag["kind"]
            if kind == "move" and self._sel_annot is not None:
                d = drag["delta"]
                if abs(d.x()) + abs(d.y()) >= 2:
                    dx, dy = self._to_page_vector(page, d)
                    self.annotMoveRequested.emit(page, self._sel_annot.xref, dx, dy)
            elif kind == "resize" and self._sel_annot is not None:
                d = drag["delta"]
                vr = self._to_view_rect(page, self._sel_annot.rect).normalized()
                vr = QRectF(vr.topLeft(), vr.bottomRight() + d).normalized()
                self.annotResizeRequested.emit(page, self._sel_annot.xref,
                                               self._to_page_rect(page, vr))
            elif kind == "area":
                end_pt = drag.get("end_pt", drag["start_pt"])
                rect = fitz.Rect(drag["start_pt"], end_pt)
                rect.normalize()
                self.areaRequested.emit(drag["tool"], page, rect)
            elif kind == "line":
                end_pt = drag.get("end_pt")
                if end_pt is not None:
                    self.lineRequested.emit(drag["tool"], page, drag["start_pt"], end_pt)
            elif kind == "ink":
                strokes = [s for s in drag["points"] if len(s) >= 2]
                if strokes:
                    self.inkRequested.emit(page, strokes)
            self.viewport().update()
            return
        if self._band_start is None:
            return
        start, end = self._band_start, self._viewport_to_content(event.position())
        self._band_start = self._band_end = None
        band = QRectF(start, end).normalized()
        if band.width() < 3 and band.height() < 3:
            self.viewport().update()
            return
        page = self._page_at(start) if self._page_at(start) is not None else self._page_at(band.center())
        if page is None:
            self.viewport().update()
            return
        page_rect = self._page_rect[page]
        # a perfectly straight drag has zero height (or width), which Qt treats as an empty box
        band = band.adjusted(-1 if band.width() < 2 else 0, -1 if band.height() < 2 else 0,
                             1 if band.width() < 2 else 0, 1 if band.height() < 2 else 0)
        local = band.intersected(page_rect).translated(-page_rect.left(), -page_rect.top())
        try:
            selection = self.doc.words_in_rect(page, self._to_page_rect(page, local))
        except Exception as exc:
            log.warning("Text selection failed: %s", exc)
            selection = None
        if selection is not None and not selection.rects:
            selection = None
        if self._tool in TEXT_TOOLS:
            if selection is not None:
                self.markupRequested.emit(self._tool, page, list(selection.rects))
            self.viewport().update()
            return
        self._selection = selection
        self.selectionChanged.emit(self.selected_text)
        self.viewport().update()

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-click: edit an annotation's text, or select the word under the cursor."""
        content = self._viewport_to_content(event.position())
        loc = self._locate(content)
        if loc is None:
            return
        page, local, pt = loc
        if self._tool == TOOL_SELECT:
            hit = self._annot_at(page, pt)
            if hit is not None:
                self.select_annot(hit)
                self.annotEditRequested.emit(hit)
                return
        if self._tool not in (TOOL_SELECT, TOOL_HAND):
            return
        try:
            self._selection = self.doc.words_in_rect(page, fitz.Rect(pt.x - 1, pt.y - 1, pt.x + 1, pt.y + 1))
        except Exception:
            self._selection = None
        if self._selection is not None and not self._selection.rects:
            self._selection = None
        self.selectionChanged.emit(self.selected_text)
        self.viewport().update()
