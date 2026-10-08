"""Light and dark themes (Qt Fusion style + palette + a small stylesheet)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = QColor("#2f6fdb")


def _light() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#f3f4f6"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#1f2328"))
    p.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#f6f8fa"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#1f2328"))
    p.setColor(QPalette.ColorRole.Text, QColor("#1f2328"))
    p.setColor(QPalette.ColorRole.Button, QColor("#f3f4f6"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#1f2328"))
    p.setColor(QPalette.ColorRole.Highlight, ACCENT)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a9099"))
    p.setColor(QPalette.ColorRole.Mid, QColor("#d0d4da"))
    p.setColor(QPalette.ColorRole.Dark, QColor("#c3c8cf"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#a0a6ae"))
    return p


def _dark() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#23262b"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#e6e8eb"))
    p.setColor(QPalette.ColorRole.Base, QColor("#1b1d21"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#26292e"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2c3036"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#e6e8eb"))
    p.setColor(QPalette.ColorRole.Text, QColor("#e6e8eb"))
    p.setColor(QPalette.ColorRole.Button, QColor("#2c3036"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#e6e8eb"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#3d7cf0"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7d838c"))
    p.setColor(QPalette.ColorRole.Mid, QColor("#3a3f46"))
    p.setColor(QPalette.ColorRole.Dark, QColor("#15171a"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6b717a"))
    return p


_STYLE = """
QToolBar { spacing: 2px; padding: 3px 6px; border: none; }
QToolBar QToolButton { padding: 4px; border-radius: 6px; }
QToolBar QToolButton:checked { background: palette(highlight); color: palette(highlighted-text); }
QTabWidget#docTabs::pane { border: none; }
QTabBar::tab { padding: 6px 12px; }
QTabWidget#sidePanel QTabBar::tab { padding: 5px 7px; }
QStatusBar QLabel { padding: 0 8px; }
QListWidget#thumbs { border: none; }
QListWidget#thumbs::item:selected, QListWidget#organizer::item:selected {
    background: rgba(47, 111, 219, 55); color: palette(text);
    border: 2px solid #2f6fdb; border-radius: 6px; }
QListWidget#organizer { border: none; }
QLineEdit#searchBox { padding: 4px 8px; border-radius: 6px; min-width: 200px; }
"""


def apply_theme(app: QApplication, dark: bool) -> None:
    app.setStyle("Fusion")
    app.setPalette(_dark() if dark else _light())
    app.setStyleSheet(_STYLE)


def viewer_background(dark: bool) -> QColor:
    return QColor("#3a3d42") if dark else QColor("#d9dce1")


def icon_color(dark: bool) -> QColor:
    return QColor("#dfe2e6") if dark else QColor("#3b4048")
