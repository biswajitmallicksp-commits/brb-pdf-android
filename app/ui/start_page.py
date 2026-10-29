"""The start screen shown when no document is open: PDF and Word tasks plus recent files."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from app import config

TILE = ("QPushButton {{ text-align:left; padding:14px 16px; border:1px solid #d0d4da; border-radius:8px;"
        " background:palette(base); font-size:13px; }}"
        " QPushButton:hover {{ border-color:{c}; background:{bg}; }}")


class StartPage(QWidget):
    """Signals carry what the user picked; the main window does the work."""
    openPdf = Signal()
    newWord = Signal()
    openWord = Signal()
    pdfToWord = Signal()
    openRecent = Signal(str)

    def __init__(self, recent_files, parent=None):
        super().__init__(parent)
        self._recent_files = recent_files              # callable -> list[str]
        outer = QHBoxLayout(self)
        outer.addStretch(1)
        col = QVBoxLayout()
        outer.addLayout(col, 3)
        outer.addStretch(1)
        col.addStretch(1)
        title = QLabel(f"<span style='font-size:24px; font-weight:600'>{config.APP_NAME}</span>"
                       "<span style='color:gray'>  -  PDF and Word, on this computer</span>")
        col.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(12)
        tiles = [
            ("Open PDF", "View, edit, sign, OCR, organise pages", "#2f6fdb", "#eef3fc", self.openPdf),
            ("Convert PDF to Word", "Turn a PDF (even a scanned one) into an editable document",
             "#2b8a3e", "#ecf7ef", self.pdfToWord),
            ("New Word document", "A blank page - write, format, add tables and pictures",
             "#185abd", "#eaf1fb", self.newWord),
            ("Open Word document", "Open and edit a .docx file, save as Word or PDF", "#185abd", "#eaf1fb",
             self.openWord),
        ]
        self.buttons: dict[str, QPushButton] = {}
        for i, (name, sub, colour, bg, signal) in enumerate(tiles):
            b = QPushButton(f"{name}\n{sub}")
            b.setStyleSheet(TILE.format(c=colour, bg=bg))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(70)
            b.clicked.connect(signal.emit)
            grid.addWidget(b, i // 2, i % 2)
            self.buttons[name] = b
        col.addLayout(grid)
        col.addSpacing(10)
        col.addWidget(QLabel("<b>Recent</b>"))
        self.recent = QListWidget()
        self.recent.setMaximumHeight(240)
        self.recent.itemActivated.connect(lambda it: self.openRecent.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.recent.itemClicked.connect(lambda it: self.openRecent.emit(it.data(Qt.ItemDataRole.UserRole)))
        col.addWidget(self.recent)
        hint = QLabel("<span style='color:gray'>Drag PDF or Word files onto this window to open them. "
                      "Everything is processed on this computer - nothing is uploaded.</span>")
        hint.setWordWrap(True)
        col.addWidget(hint)
        col.addStretch(2)
        self.refresh()

    def refresh(self) -> None:
        self.recent.clear()
        try:
            files = self._recent_files()
        except Exception:
            files = []
        for path in files[:12]:
            p = Path(path)
            if not p.exists():
                continue
            kind = "Word" if p.suffix.lower() == ".docx" else "PDF "
            it = QListWidgetItem(f"[{kind}]  {p.name}    -    {p.parent}")
            it.setData(Qt.ItemDataRole.UserRole, str(p))
            it.setToolTip(str(p))
            self.recent.addItem(it)
        if not self.recent.count():
            it = QListWidgetItem("(no recent files yet)")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(it)

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)
