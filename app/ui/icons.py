"""Original line icons drawn with QPainter.

No image files, no third-party or Adobe artwork: every icon is a few
lines and arcs drawn here, in the current theme's text colour, so icons
stay crisp at any screen scaling and follow dark/light mode.
"""
from __future__ import annotations


from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_SIZE = 64


def _pen(color: QColor, width: float = 4.5) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _chevron(p: QPainter, x: float, direction: int) -> None:
    """direction -1 = pointing left, +1 = pointing right."""
    d = 12 * direction
    path = QPainterPath(QPointF(x - d, 18))
    path.lineTo(x + d, 32)
    path.lineTo(x - d, 46)
    p.drawPath(path)


def _magnifier(p: QPainter) -> None:
    p.drawEllipse(QRectF(10, 10, 32, 32))
    p.drawLine(QPointF(37, 37), QPointF(54, 54))


def _arc_arrow(p: QPainter, clockwise: bool) -> None:
    rect = QRectF(14, 14, 36, 36)
    if clockwise:
        p.drawArc(rect, 90 * 16, -270 * 16)
        # arrow head at the arc end (pointing down at the left... top)
        end = QPointF(32, 14)
        p.drawLine(end, QPointF(end.x() - 9, end.y() - 7))
        p.drawLine(end, QPointF(end.x() - 9, end.y() + 7))
    else:
        p.drawArc(rect, 90 * 16, 270 * 16)
        end = QPointF(32, 14)
        p.drawLine(end, QPointF(end.x() + 9, end.y() - 7))
        p.drawLine(end, QPointF(end.x() + 9, end.y() + 7))


def _draw(name: str, p: QPainter, color: QColor) -> None:
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if name == "open":
        path = QPainterPath(QPointF(8, 50))
        path.lineTo(8, 16); path.lineTo(24, 16); path.lineTo(29, 22); path.lineTo(52, 22); path.lineTo(52, 30)
        p.drawPath(path)
        path2 = QPainterPath(QPointF(8, 50))
        path2.lineTo(16, 30); path2.lineTo(58, 30); path2.lineTo(50, 50); path2.closeSubpath()
        p.drawPath(path2)
    elif name == "save":
        p.drawRoundedRect(QRectF(10, 10, 44, 44), 5, 5)
        p.drawRect(QRectF(20, 10, 22, 14))
        p.drawRect(QRectF(18, 34, 28, 20))
    elif name == "print":
        p.drawRect(QRectF(18, 8, 28, 14))
        p.drawRoundedRect(QRectF(8, 22, 48, 22), 4, 4)
        p.drawRect(QRectF(18, 36, 28, 20))
    elif name == "first":
        p.drawLine(QPointF(16, 16), QPointF(16, 48)); _chevron(p, 34, -1)
    elif name == "prev":
        _chevron(p, 32, -1)
    elif name == "next":
        _chevron(p, 32, 1)
    elif name == "last":
        _chevron(p, 30, 1); p.drawLine(QPointF(48, 16), QPointF(48, 48))
    elif name == "zoom_in":
        _magnifier(p); p.drawLine(QPointF(19, 26), QPointF(33, 26)); p.drawLine(QPointF(26, 19), QPointF(26, 33))
    elif name == "zoom_out":
        _magnifier(p); p.drawLine(QPointF(19, 26), QPointF(33, 26))
    elif name == "search":
        _magnifier(p)
    elif name == "fit_width":
        p.drawRect(QRectF(16, 8, 32, 48))
        p.drawLine(QPointF(6, 32), QPointF(58, 32))
        p.drawLine(QPointF(6, 32), QPointF(12, 26)); p.drawLine(QPointF(6, 32), QPointF(12, 38))
        p.drawLine(QPointF(58, 32), QPointF(52, 26)); p.drawLine(QPointF(58, 32), QPointF(52, 38))
    elif name == "fit_page":
        p.drawRect(QRectF(18, 12, 28, 40))
        for x, y, dx, dy in ((6, 6, 1, 1), (58, 6, -1, 1), (6, 58, 1, -1), (58, 58, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 8 * dx, y)); p.drawLine(QPointF(x, y), QPointF(x, y + 8 * dy))
    elif name == "select":
        path = QPainterPath(QPointF(18, 8))
        path.lineTo(18, 50); path.lineTo(29, 40); path.lineTo(37, 56); path.lineTo(43, 53)
        path.lineTo(35, 37); path.lineTo(49, 37); path.closeSubpath()
        p.drawPath(path)
    elif name == "hand":
        for i, h in enumerate((22, 16, 18, 26)):
            x = 20 + i * 8
            p.drawLine(QPointF(x, 34), QPointF(x, h))
        path = QPainterPath(QPointF(20, 34))
        path.lineTo(20, 44); path.quadTo(22, 56, 34, 56); path.quadTo(46, 56, 46, 44); path.lineTo(46, 30)
        p.drawPath(path)
        p.drawLine(QPointF(20, 38), QPointF(12, 32))
    elif name == "rotate_cw":
        _arc_arrow(p, True)
    elif name == "rotate_ccw":
        _arc_arrow(p, False)
    elif name == "info":
        p.drawEllipse(QRectF(8, 8, 48, 48)); p.drawLine(QPointF(32, 29), QPointF(32, 45))
        p.setBrush(color); p.drawEllipse(QPointF(32, 20), 2.2, 2.2)
    elif name == "sidebar":
        p.drawRoundedRect(QRectF(8, 12, 48, 40), 4, 4); p.drawLine(QPointF(24, 12), QPointF(24, 52))
    elif name == "fullscreen":
        for x, y, dx, dy in ((10, 10, 1, 1), (54, 10, -1, 1), (10, 54, 1, -1), (54, 54, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 12 * dx, y)); p.drawLine(QPointF(x, y), QPointF(x, y + 12 * dy))
    elif name == "theme":
        p.drawEllipse(QRectF(10, 10, 44, 44))
        path = QPainterPath(QPointF(32, 10)); path.arcTo(QRectF(10, 10, 44, 44), 90, 180); path.closeSubpath()
        p.setBrush(color); p.drawPath(path)
    elif name == "continuous":
        p.drawRect(QRectF(18, 4, 28, 24)); p.drawRect(QRectF(18, 36, 28, 24))
    elif name == "single":
        p.drawRect(QRectF(16, 8, 32, 48))
    elif name == "two_page":
        p.drawRect(QRectF(6, 14, 24, 36)); p.drawRect(QRectF(34, 14, 24, 36))
    elif name == "ocr":
        # scan frame corners with text lines inside
        for x, y, dx, dy in ((8, 8, 1, 1), (56, 8, -1, 1), (8, 56, 1, -1), (56, 56, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 12 * dx, y)); p.drawLine(QPointF(x, y), QPointF(x, y + 12 * dy))
        p.drawLine(QPointF(20, 22), QPointF(44, 22)); p.drawLine(QPointF(32, 22), QPointF(32, 44))  # a "T"
    elif name == "organize":
        for x in (8, 26, 44):
            for y in (8, 34):
                p.drawRoundedRect(QRectF(x, y, 12, 20), 2, 2)
    elif name in ("undo", "redo"):
        sign = -1 if name == "undo" else 1
        path = QPainterPath(QPointF(32 - 18 * sign, 44))
        path.cubicTo(32 - 18 * sign, 20, 32 + 10 * sign, 18, 32 + 20 * sign, 26)
        p.drawPath(path)
        tip = QPointF(32 + 20 * sign, 26)
        p.drawLine(tip, QPointF(tip.x() - 12 * sign, tip.y() - 4))
        p.drawLine(tip, QPointF(tip.x() - 4 * sign, tip.y() + 11))
    elif name == "rotate_page":
        p.drawRect(QRectF(20, 22, 26, 34))
        p.drawArc(QRectF(10, 6, 30, 30), 180 * 16, -120 * 16)
        p.drawLine(QPointF(38, 15), QPointF(36, 6)); p.drawLine(QPointF(38, 15), QPointF(29, 16))
    elif name == "delete":
        p.drawLine(QPointF(12, 16), QPointF(52, 16)); p.drawLine(QPointF(26, 16), QPointF(28, 9))
        p.drawLine(QPointF(28, 9), QPointF(36, 9)); p.drawLine(QPointF(36, 9), QPointF(38, 16))
        path = QPainterPath(QPointF(17, 16)); path.lineTo(20, 55); path.lineTo(44, 55); path.lineTo(47, 16)
        p.drawPath(path)
        p.drawLine(QPointF(28, 25), QPointF(28, 46)); p.drawLine(QPointF(36, 25), QPointF(36, 46))
    elif name == "insert":
        p.drawRect(QRectF(14, 8, 36, 48)); p.drawLine(QPointF(32, 20), QPointF(32, 44))
        p.drawLine(QPointF(20, 32), QPointF(44, 32))
    elif name == "extract":
        p.drawRect(QRectF(8, 14, 30, 42)); p.drawLine(QPointF(30, 30), QPointF(56, 30))
        p.drawLine(QPointF(56, 30), QPointF(47, 22)); p.drawLine(QPointF(56, 30), QPointF(47, 38))
    elif name == "merge":
        p.drawRect(QRectF(6, 8, 20, 28)); p.drawRect(QRectF(38, 8, 20, 28))
        p.drawLine(QPointF(16, 36), QPointF(32, 50)); p.drawLine(QPointF(48, 36), QPointF(32, 50))
        p.drawLine(QPointF(32, 50), QPointF(32, 58))
    elif name == "split":
        p.drawRect(QRectF(22, 6, 20, 24)); p.drawLine(QPointF(32, 30), QPointF(14, 44))
        p.drawLine(QPointF(32, 30), QPointF(50, 44)); p.drawRect(QRectF(4, 44, 18, 14)); p.drawRect(QRectF(42, 44, 18, 14))
    elif name == "add_text":
        p.drawLine(QPointF(14, 14), QPointF(50, 14)); p.drawLine(QPointF(32, 14), QPointF(32, 52))
        p.drawLine(QPointF(48, 40), QPointF(48, 56)); p.drawLine(QPointF(40, 48), QPointF(56, 48))
    elif name == "edit_text":
        p.drawLine(QPointF(8, 14), QPointF(36, 14)); p.drawLine(QPointF(22, 14), QPointF(22, 44))
        path = QPainterPath(QPointF(34, 56)); path.lineTo(36, 46); path.lineTo(52, 30); path.lineTo(58, 36)
        path.lineTo(42, 52); path.closeSubpath(); p.drawPath(path)
    elif name == "delete_text":
        p.drawLine(QPointF(8, 14), QPointF(40, 14)); p.drawLine(QPointF(24, 14), QPointF(24, 46))
        p.drawLine(QPointF(40, 36), QPointF(56, 52)); p.drawLine(QPointF(56, 36), QPointF(40, 52))
    elif name == "image":
        p.drawRoundedRect(QRectF(8, 12, 48, 40), 4, 4); p.drawEllipse(QPointF(22, 25), 4, 4)
        path = QPainterPath(QPointF(10, 48)); path.lineTo(26, 34); path.lineTo(36, 42); path.lineTo(44, 32)
        path.lineTo(54, 44); p.drawPath(path)
    elif name in ("highlight", "underline", "strike", "squiggly"):
        p.drawLine(QPointF(14, 44), QPointF(26, 12)); p.drawLine(QPointF(26, 12), QPointF(38, 44))
        p.drawLine(QPointF(18, 34), QPointF(34, 34))
        if name == "highlight":
            p.save(); hl = QColor(255, 210, 0, 150); p.setPen(Qt.PenStyle.NoPen); p.setBrush(hl)
            p.drawRect(QRectF(8, 46, 48, 10)); p.restore()
        elif name == "underline":
            p.drawLine(QPointF(10, 54), QPointF(54, 54))
        elif name == "strike":
            p.drawLine(QPointF(8, 28), QPointF(48, 28))
        else:
            path = QPainterPath(QPointF(8, 54))
            for i in range(6):
                path.lineTo(14 + i * 8, 50 if i % 2 == 0 else 56)
            p.drawPath(path)
    elif name == "note":
        path = QPainterPath(QPointF(10, 10)); path.lineTo(54, 10); path.lineTo(54, 42); path.lineTo(30, 42)
        path.lineTo(18, 54); path.lineTo(18, 42); path.lineTo(10, 42); path.closeSubpath(); p.drawPath(path)
    elif name == "textbox":
        p.drawRect(QRectF(8, 14, 48, 36)); p.drawLine(QPointF(18, 24), QPointF(46, 24))
        p.drawLine(QPointF(32, 24), QPointF(32, 42))
    elif name == "rect":
        p.drawRect(QRectF(10, 16, 44, 32))
    elif name == "ellipse":
        p.drawEllipse(QRectF(8, 14, 48, 36))
    elif name == "line":
        p.drawLine(QPointF(10, 54), QPointF(54, 10))
    elif name == "arrow":
        p.drawLine(QPointF(10, 54), QPointF(52, 12)); p.drawLine(QPointF(52, 12), QPointF(36, 14))
        p.drawLine(QPointF(52, 12), QPointF(50, 28))
    elif name == "pen":
        path = QPainterPath(QPointF(8, 46)); path.cubicTo(18, 20, 28, 60, 38, 34); path.cubicTo(44, 20, 50, 30, 56, 22)
        p.drawPath(path)
    elif name == "stamp":
        p.drawRoundedRect(QRectF(22, 8, 20, 22), 6, 6); p.drawLine(QPointF(32, 30), QPointF(32, 40))
        p.drawRect(QRectF(10, 40, 44, 10)); p.drawLine(QPointF(10, 56), QPointF(54, 56))
    elif name == "eraser":
        path = QPainterPath(QPointF(10, 40)); path.lineTo(34, 14); path.lineTo(54, 34); path.lineTo(36, 52)
        path.lineTo(22, 52); path.closeSubpath(); p.drawPath(path); p.drawLine(QPointF(22, 28), QPointF(42, 48))
    elif name == "redact":
        p.save(); p.setBrush(color); p.drawRect(QRectF(8, 22, 48, 18)); p.restore()
        p.drawLine(QPointF(8, 12), QPointF(30, 12)); p.drawLine(QPointF(8, 52), QPointF(40, 52))
    elif name == "watermark":
        p.drawRect(QRectF(12, 6, 40, 52)); p.drawLine(QPointF(18, 46), QPointF(46, 18))
    elif name == "analysis":
        p.drawLine(QPointF(10, 54), QPointF(54, 54)); p.drawLine(QPointF(10, 54), QPointF(10, 10))
        for x, h in ((18, 20), (30, 34), (42, 26)):
            p.drawRect(QRectF(x, 54 - h, 8, h))
    elif name == "app":
        p.drawRoundedRect(QRectF(12, 6, 40, 52), 5, 5)
        for y in (22, 32, 42):
            p.drawLine(QPointF(20, y), QPointF(44, y))
    else:  # unknown -> small square, never crash
        p.drawRect(QRectF(16, 16, 32, 32))


def make_icon(name: str, color: QColor) -> QIcon:
    icon = QIcon()
    for scale in (1, 2):
        pix = QPixmap(_SIZE * scale, _SIZE * scale)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(scale, scale)
        _draw(name, p, color)
        p.end()
        icon.addPixmap(pix)
        disabled = QColor(color); disabled.setAlphaF(0.35)
        pix_d = QPixmap(_SIZE * scale, _SIZE * scale)
        pix_d.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix_d)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(scale, scale)
        _draw(name, p, disabled)
        p.end()
        icon.addPixmap(pix_d, QIcon.Mode.Disabled)
    return icon
