"""Printing through the Windows print system (Qt QPrinter).

Pages are rendered at the printer's resolution (capped at 300 dpi to keep
memory reasonable) and scaled to fit the printable area, keeping the aspect
ratio. Landscape pages printed on portrait paper are rotated automatically
when "auto rotate" is on.

This file uses Qt's painting classes but no widgets; the print dialog lives
in the UI layer.
"""
from __future__ import annotations

import logging
from typing import Callable, Sequence

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QTransform
from PySide6.QtPrintSupport import QPrinter

from app.pdf_viewer.document import PdfDocument

log = logging.getLogger("pdfworkbench.print")

MAX_PRINT_DPI = 300


def print_pages(
    doc: PdfDocument,
    printer: QPrinter,
    pages: Sequence[int],
    auto_rotate: bool = True,
    fit_to_page: bool = True,
    progress: Callable[[int, int], bool] | None = None,
) -> int:
    """Print `pages` (0-based). Returns the number of pages printed.

    `progress(done, total)` may return False to cancel.
    """
    dpi = min(printer.resolution(), MAX_PRINT_DPI) or 150
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("The printer could not be started. Check that it is connected and online.")
    copies = 1
    if not printer.supportsMultipleCopies():
        copies = max(1, printer.copyCount())
    total = len(pages) * copies
    printed = 0
    try:
        first = True
        for _copy in range(copies):
            for page_index in pages:
                if progress is not None and progress(printed, total) is False:
                    log.info("Printing cancelled after %d pages", printed)
                    return printed
                if not first:
                    printer.newPage()
                first = False
                _paint_page(doc, painter, printer, page_index, dpi, auto_rotate, fit_to_page)
                printed += 1
    finally:
        painter.end()
    return printed


def _paint_page(doc, painter, printer, page_index, dpi, auto_rotate, fit_to_page):
    w_pt, h_pt = doc.page_size(page_index)
    area = printer.pageLayout().paintRectPixels(printer.resolution())
    area = QRectF(0, 0, area.width(), area.height())

    rotate = auto_rotate and ((w_pt > h_pt) != (area.width() > area.height()))
    rendered = doc.render(page_index, dpi / 72.0, 90 if rotate else 0)
    image = QImage(rendered.samples, rendered.width, rendered.height, rendered.stride,
                   QImage.Format.Format_RGB888).copy()

    img_w, img_h = image.width(), image.height()
    if fit_to_page:
        s = min(area.width() / img_w, area.height() / img_h)
    else:  # actual size
        s = printer.resolution() / dpi
    target = QRectF(0, 0, img_w * s, img_h * s)
    target.moveCenter(area.center())
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setTransform(QTransform())
    painter.drawImage(target, image)
