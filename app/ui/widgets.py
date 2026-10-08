"""Small reusable widgets."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton


def to_qcolor(rgb) -> QColor:
    if rgb is None:
        return QColor(0, 0, 0, 0)
    r, g, b = (tuple(rgb) + (0, 0, 0))[:3]
    if max(r, g, b) <= 1:
        return QColor.fromRgbF(float(r), float(g), float(b))
    return QColor(int(r), int(g), int(b))


def from_qcolor(c: QColor) -> tuple[float, float, float]:
    return (round(c.redF(), 4), round(c.greenF(), 4), round(c.blueF(), 4))


class ColorButton(QPushButton):
    """A button showing a colour; click to choose another."""

    colorChanged = Signal(tuple)

    def __init__(self, rgb=(0, 0, 0), parent=None, title: str = "Choose colour"):
        super().__init__(parent)
        self._title = title
        self.setFixedSize(46, 24)
        self.clicked.connect(self._choose)
        self.set_color(rgb)

    def color(self) -> tuple[float, float, float]:
        return self._rgb

    def set_color(self, rgb) -> None:
        self._rgb = from_qcolor(to_qcolor(rgb))
        c = to_qcolor(self._rgb)
        self.setStyleSheet(f"QPushButton {{ background: {c.name()}; border: 1px solid #888; border-radius: 4px; }}")
        self.setToolTip(c.name())

    def _choose(self) -> None:
        c = QColorDialog.getColor(to_qcolor(self._rgb), self, self._title)
        if c.isValid():
            self.set_color(from_qcolor(c))
            self.colorChanged.emit(self._rgb)
