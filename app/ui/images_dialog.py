"""Images to PDF: choose photos / pictures (JPG, PNG, ...), put them in order, make one PDF (one picture a page)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from app.pdf_pages import operations as ops

IMAGE_FILTER = "Pictures (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;All files (*)"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")


class ImagesToPdfDialog(QDialog):
    def __init__(self, start_dir: str, initial: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Images to PDF")
        self.resize(760, 560)
        self.setAcceptDrops(True)
        self.start_dir = start_dir
        self._out_edited = False

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(110, 110))
        self.list.setGridSize(QSize(140, 150))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Snap)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setWordWrap(True)
        self.list.model().rowsMoved.connect(lambda *a: self._renumber())

        add = QPushButton("Add pictures...")
        remove = QPushButton("Remove")
        left = QPushButton("Move earlier")
        right = QPushButton("Move later")
        sort = QPushButton("Sort by name")
        add.clicked.connect(self._add_files)
        remove.clicked.connect(self._remove)
        left.clicked.connect(lambda: self._shift(-1))
        right.clicked.connect(lambda: self._shift(1))
        sort.clicked.connect(self._sort)
        side = QVBoxLayout()
        for b in (add, remove, left, right, sort):
            side.addWidget(b)
        side.addStretch(1)
        top = QHBoxLayout()
        top.addWidget(self.list, 1)
        top.addLayout(side)

        self.page_size = QComboBox()
        for text, key in (("A4", "a4"), ("Letter", "letter"), ("Legal", "legal"), ("Same size as each picture", "fit")):
            self.page_size.addItem(text, key)
        self.margin = QComboBox()
        for text, key in (("None", "none"), ("Small", "small"), ("Normal", "normal")):
            self.margin.addItem(text, key)
        self.margin.setCurrentIndex(1)
        self.page_size.currentIndexChanged.connect(
            lambda _i: self.margin.setEnabled(self.page_size.currentData() != "fit"))
        self.quality = QComboBox()
        self.quality.addItem("Original quality", False)
        self.quality.addItem("Smaller file (good for email / WhatsApp)", True)

        self.output = QLineEdit()
        self.output.textEdited.connect(lambda _t: setattr(self, "_out_edited", True))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output, 1)
        out_row.addWidget(browse)
        self.open_after = QCheckBox("Open the PDF when it is made")
        self.open_after.setChecked(True)
        hint = QLabel("One picture per page, in this order. Drag pictures in the list (or drop files onto this "
                      "window) to change the order. Wide pictures get a landscape page; camera photos are turned "
                      "the right way up.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        form = QFormLayout()
        form.addRow("Page size:", self.page_size)
        form.addRow("Margin:", self.margin)
        form.addRow("File size:", self.quality)
        form.addRow("Save as:", out_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create PDF")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(top, 1)
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addWidget(self.open_after)
        lay.addWidget(buttons)
        for p in initial or []:
            self._add(p)
        self._suggest_output()
        if not initial:
            QTimer.singleShot(0, self._add_files)

    # ------------------------------------------------------------ list
    def files(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def options(self) -> dict:
        return {"page_size": self.page_size.currentData(), "margin": self.margin.currentData(),
                "smaller": bool(self.quality.currentData())}

    def _add(self, path: str) -> None:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > 300:
            reader.setScaledSize(size.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio))
        img = reader.read()
        item = QListWidgetItem(Path(path).name)
        if img.isNull():
            item.setText(f"{Path(path).name}\n(cannot be read)")
        else:
            item.setIcon(QIcon(QPixmap.fromImage(img)))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list.addItem(item)
        self._renumber()
        self._suggest_output()

    def _renumber(self) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setText(f"{i + 1}. {Path(it.data(Qt.ItemDataRole.UserRole)).name}")

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add pictures", self.start_dir, IMAGE_FILTER)
        for p in paths:
            self._add(p)
        if paths:
            self.start_dir = str(Path(paths[0]).parent)

    def _remove(self) -> None:
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._renumber()

    def _shift(self, delta: int) -> None:
        row = self.list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(new, item)
        self.list.setCurrentRow(new)
        self._renumber()

    def _sort(self) -> None:
        items = [self.list.takeItem(0) for _ in range(self.list.count())]
        items.sort(key=lambda it: Path(it.data(Qt.ItemDataRole.UserRole)).name.lower())
        for it in items:
            self.list.addItem(it)
        self._renumber()

    def _suggest_output(self) -> None:
        if self._out_edited:
            return
        files = self.files()
        if files:
            first = Path(files[0])
            name = first.stem + (".pdf" if len(files) == 1 else f" ({len(files)} pages).pdf")
            self.output.setText(str(ops.unique_path(first.with_name(name))))
        else:
            self.output.setText(str(ops.unique_path(Path(self.start_dir) / "Pictures.pdf")))

    # ------------------------------------------------------------ drag and drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(IMAGE_EXT)
                                              for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for u in event.mimeData().urls():
            f = u.toLocalFile()
            if f.lower().endswith(IMAGE_EXT):
                self._add(f)

    # ------------------------------------------------------------ finish
    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF", self.output.text(), "PDF (*.pdf)")
        if path:
            self.output.setText(path if path.lower().endswith(".pdf") else path + ".pdf")
            self._out_edited = True

    def _accept(self) -> None:
        if not self.files():
            QMessageBox.warning(self, "Images to PDF", "Add the pictures to put in the PDF.")
            return
        out = Path(self.output.text().strip())
        if out.suffix.lower() != ".pdf":
            QMessageBox.warning(self, "Images to PDF", "Choose a .pdf file name for the result.")
            return
        if out.exists() and QMessageBox.question(self, "Images to PDF", f"{out.name} exists. Replace it?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.accept()
