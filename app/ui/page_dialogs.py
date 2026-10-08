"""Dialogs for page management: insert, extract, split, merge, replace, move, page ranges."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from app.pdf_pages import operations as ops
from app.utils.pages import describe_pages, parse_page_range

OPEN_FILTER = "PDF and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp);;All files (*)"


def _range_text(pages: list[int]) -> str:
    return describe_pages(pages, limit=10_000)


class PositionPicker(QWidget):
    """'At the beginning / Before page N / After page N / At the end' -> insert-before index."""

    def __init__(self, page_count: int, default_after: int, parent=None):
        super().__init__(parent)
        self.page_count = page_count
        self.where = QComboBox()
        self.where.addItems(["At the beginning", "Before page", "After page", "At the end"])
        self.page = QSpinBox()
        self.page.setRange(1, max(1, page_count))
        self.page.setValue(min(page_count, default_after + 1))
        self.where.setCurrentIndex(2)
        self.where.currentIndexChanged.connect(lambda i: self.page.setEnabled(i in (1, 2)))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.where)
        lay.addWidget(self.page)
        lay.addStretch(1)

    def insert_before(self) -> int:
        i = self.where.currentIndex()
        if i == 0:
            return 0
        if i == 3:
            return self.page_count
        n = self.page.value() - 1
        return n if i == 1 else n + 1


def _pick_file(parent, edit: QLineEdit, start: str, filt: str = OPEN_FILTER) -> None:
    path, _ = QFileDialog.getOpenFileName(parent, "Choose a file", start, filt)
    if path:
        edit.setText(path)


def _warn(parent, text: str) -> None:
    QMessageBox.warning(parent, "Pages", text)


# ===================================================================== range
class PageRangeDialog(QDialog):
    """Ask for a set of pages (pre-filled with the current selection)."""

    def __init__(self, title: str, prompt: str, page_count: int, default: list[int], ok_text: str = "OK",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.page_count = page_count
        self.edit = QLineEdit(_range_text(default))
        hint = QLabel(f"Examples: 3   1-5, 8   10-   odd   even   all   (document has {page_count} pages)")
        hint.setStyleSheet("color: gray")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(prompt))
        lay.addWidget(self.edit)
        lay.addWidget(hint)
        lay.addWidget(buttons)
        self.pages: list[int] = []

    def _accept(self) -> None:
        try:
            self.pages = parse_page_range(self.edit.text(), self.page_count)
        except ValueError as exc:
            _warn(self, str(exc))
            return
        self.accept()


# ==================================================================== insert
class InsertDialog(QDialog):
    def __init__(self, page_count: int, current: int, current_size: tuple[float, float],
                 start_dir: str, from_file: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert pages")
        self.setMinimumWidth(520)
        self.current_size = current_size

        self.rb_blank = QRadioButton("Blank pages")
        self.rb_file = QRadioButton("Pages from a file (PDF or image)")
        group = QButtonGroup(self)
        group.addButton(self.rb_blank)
        group.addButton(self.rb_file)
        (self.rb_file if from_file else self.rb_blank).setChecked(True)

        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.size = QComboBox()
        self.size.addItem("Same as the current page", None)
        for name, wh in ops.PAPER_SIZES.items():
            self.size.addItem(f"{name} ({wh[0] / 72 * 25.4:.0f} x {wh[1] / 72 * 25.4:.0f} mm)", wh)
        self.landscape = QCheckBox("Landscape")
        blank_box = QWidget()
        bl = QHBoxLayout(blank_box)
        bl.setContentsMargins(24, 0, 0, 0)
        bl.addWidget(QLabel("Number:"))
        bl.addWidget(self.count)
        bl.addWidget(QLabel("Size:"))
        bl.addWidget(self.size, 1)
        bl.addWidget(self.landscape)

        self.file_edit = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: _pick_file(self, self.file_edit, start_dir))
        self.file_pages = QLineEdit()
        self.file_pages.setPlaceholderText("all pages (or e.g. 1-3, 5)")
        file_box = QWidget()
        fl = QGridLayout(file_box)
        fl.setContentsMargins(24, 0, 0, 0)
        fl.addWidget(QLabel("File:"), 0, 0)
        fl.addWidget(self.file_edit, 0, 1)
        fl.addWidget(browse, 0, 2)
        fl.addWidget(QLabel("Pages:"), 1, 0)
        fl.addWidget(self.file_pages, 1, 1, 1, 2)
        self.file_edit.textEdited.connect(lambda _t: self.rb_file.setChecked(True))

        self.position = PositionPicker(page_count, current)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Insert")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.rb_blank)
        lay.addWidget(blank_box)
        lay.addWidget(self.rb_file)
        lay.addWidget(file_box)
        form = QFormLayout()
        form.addRow("Insert:", self.position)
        lay.addLayout(form)
        lay.addWidget(buttons)

    @property
    def blank(self) -> bool:
        return self.rb_blank.isChecked()

    def blank_size(self) -> tuple[float, float]:
        wh = self.size.currentData() or self.current_size
        w, h = min(wh), max(wh)
        if self.size.currentData() is None:
            return wh                          # keep the current page exactly
        return (h, w) if self.landscape.isChecked() else (w, h)

    def _accept(self) -> None:
        if not self.blank:
            path = self.file_edit.text().strip()
            if not path or not Path(path).is_file():
                _warn(self, "Choose the file to insert.")
                return
        self.accept()


# =================================================================== extract
class ExtractDialog(QDialog):
    def __init__(self, page_count: int, default: list[int], doc_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Extract pages to a new PDF")
        self.setMinimumWidth(560)
        self.page_count = page_count
        self.doc_path = doc_path
        self.pages_edit = QLineEdit(_range_text(default))
        self.separate = QCheckBox("Save each page as a separate PDF")
        self.delete_after = QCheckBox("Delete these pages from this document afterwards (can be undone)")
        self.open_after = QCheckBox("Open the new PDF")
        self.open_after.setChecked(True)
        self.output = QLineEdit(str(ops.unique_path(doc_path.with_name(f"{doc_path.stem}_extract.pdf"))))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        self.separate.toggled.connect(self._separate_toggled)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output, 1)
        out_row.addWidget(browse)
        self.out_label = QLabel("Save as:")
        form = QFormLayout()
        form.addRow("Pages:", self.pages_edit)
        form.addRow(self.out_label, out_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Extract")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.separate)
        lay.addWidget(self.delete_after)
        lay.addWidget(self.open_after)
        lay.addWidget(buttons)
        self.pages: list[int] = []

    def _separate_toggled(self, on: bool) -> None:
        self.out_label.setText("Folder:" if on else "Save as:")
        self.open_after.setEnabled(not on)
        self.output.setText(str(self.doc_path.parent if on else
                                ops.unique_path(self.doc_path.with_name(f"{self.doc_path.stem}_extract.pdf"))))

    def _browse(self) -> None:
        if self.separate.isChecked():
            path = QFileDialog.getExistingDirectory(self, "Folder for the pages", self.output.text())
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Save extracted pages", self.output.text(), "PDF (*.pdf)")
            if path and not path.lower().endswith(".pdf"):
                path += ".pdf"
        if path:
            self.output.setText(path)

    def _accept(self) -> None:
        try:
            self.pages = parse_page_range(self.pages_edit.text(), self.page_count)
        except ValueError as exc:
            _warn(self, str(exc))
            return
        if self.delete_after.isChecked() and len(self.pages) >= self.page_count:
            _warn(self, "You cannot delete every page. Untick 'Delete these pages'.")
            return
        out = Path(self.output.text().strip())
        if not self.separate.isChecked():
            if out.suffix.lower() != ".pdf":
                _warn(self, "Choose a .pdf file name.")
                return
            if out.resolve() == self.doc_path.resolve():
                _warn(self, "Choose a different name: the original file is not overwritten here.")
                return
            if out.exists() and QMessageBox.question(self, "Extract", f"{out.name} exists. Replace it?") \
                    != QMessageBox.StandardButton.Yes:
                return
        self.accept()


# ===================================================================== split
class SplitDialog(QDialog):
    def __init__(self, page_count: int, has_bookmarks: bool, doc_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Split PDF into several files")
        self.setMinimumWidth(560)
        self.page_count = page_count
        self.rb_every = QRadioButton("Every")
        self.every = QSpinBox()
        self.every.setRange(1, max(1, page_count))
        self.every.setValue(min(10, max(1, page_count)))
        self.rb_ranges = QRadioButton("Page ranges, one file each:")
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("e.g. 1-3, 4-10, 11-")
        self.rb_single = QRadioButton("One file per page")
        self.rb_bookmarks = QRadioButton("One file per top-level bookmark")
        self.rb_bookmarks.setEnabled(has_bookmarks)
        if not has_bookmarks:
            self.rb_bookmarks.setText(self.rb_bookmarks.text() + "  (this document has no bookmarks)")
        self.rb_every.setChecked(True)
        group = QButtonGroup(self)
        for rb in (self.rb_every, self.rb_ranges, self.rb_single, self.rb_bookmarks):
            group.addButton(rb)
        self.ranges.textEdited.connect(lambda _t: self.rb_ranges.setChecked(True))
        self.every.valueChanged.connect(lambda _v: self.rb_every.setChecked(True))
        box = QGroupBox("How to split")
        g = QGridLayout(box)
        row = QHBoxLayout()
        row.addWidget(self.rb_every)
        row.addWidget(self.every)
        row.addWidget(QLabel("pages"))
        row.addStretch(1)
        g.addLayout(row, 0, 0, 1, 2)
        g.addWidget(self.rb_ranges, 1, 0)
        g.addWidget(self.ranges, 1, 1)
        g.addWidget(self.rb_single, 2, 0, 1, 2)
        g.addWidget(self.rb_bookmarks, 3, 0, 1, 2)

        self.folder = QLineEdit(str(doc_path.parent / f"{doc_path.stem}_split"))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        self.stem = QLineEdit(doc_path.stem)
        out_row = QHBoxLayout()
        out_row.addWidget(self.folder, 1)
        out_row.addWidget(browse)
        form = QFormLayout()
        form.addRow("Save in folder:", out_row)
        form.addRow("File names start with:", self.stem)
        self.open_folder = QCheckBox("Open the folder when finished")
        self.open_folder.setChecked(True)
        note = QLabel("Files are named like  name_01_p1-10.pdf.  Existing files are never overwritten. "
                      "The original PDF is not changed.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Split")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addLayout(form)
        lay.addWidget(self.open_folder)
        lay.addWidget(note)
        lay.addWidget(buttons)

    def mode(self) -> tuple[str, str | int]:
        if self.rb_every.isChecked():
            return "every", self.every.value()
        if self.rb_ranges.isChecked():
            return "ranges", self.ranges.text()
        if self.rb_single.isChecked():
            return "single", ""
        return "bookmarks", ""

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder for the split files", self.folder.text())
        if path:
            self.folder.setText(path)

    def _accept(self) -> None:
        if not self.folder.text().strip() or not self.stem.text().strip():
            _warn(self, "Choose a folder and a file name.")
            return
        if self.rb_ranges.isChecked() and not self.ranges.text().strip():
            _warn(self, "Enter the page ranges, for example 1-3, 4-10")
            return
        self.accept()


# ===================================================================== merge
class MergeDialog(QDialog):
    """Pick and order the files to combine."""

    def __init__(self, start_dir: str, initial: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Combine files into one PDF")
        self.resize(640, 480)
        self.start_dir = start_dir
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setAlternatingRowColors(True)
        for p in initial or []:
            self._add(p)
        add = QPushButton("Add files...")
        remove = QPushButton("Remove")
        up = QPushButton("Move up")
        down = QPushButton("Move down")
        add.clicked.connect(self._add_files)
        remove.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._shift(-1))
        down.clicked.connect(lambda: self._shift(1))
        side = QVBoxLayout()
        for b in (add, remove, up, down):
            side.addWidget(b)
        side.addStretch(1)
        top = QHBoxLayout()
        top.addWidget(self.list, 1)
        top.addLayout(side)

        default_out = Path(initial[0]).with_name("Combined.pdf") if initial else Path(start_dir) / "Combined.pdf"
        self.output = QLineEdit(str(ops.unique_path(default_out)))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output, 1)
        out_row.addWidget(browse)
        self.bookmarks = QCheckBox("Add a bookmark for each file")
        self.bookmarks.setChecked(True)
        self.open_after = QCheckBox("Open the combined PDF")
        self.open_after.setChecked(True)
        hint = QLabel("Drag files in the list (or use Move up/down) to set the order. PDFs and images "
                      "(JPG, PNG, TIFF...) can be combined.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Combine")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Save as:", out_row)
        lay = QVBoxLayout(self)
        lay.addLayout(top, 1)
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addWidget(self.bookmarks)
        lay.addWidget(self.open_after)
        lay.addWidget(buttons)

    def files(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _add(self, path: str) -> None:
        item = QListWidgetItem(f"{Path(path).name}    ({Path(path).parent})")
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list.addItem(item)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", self.start_dir, OPEN_FILTER)
        for p in paths:
            self._add(p)
        if paths:
            self.start_dir = str(Path(paths[0]).parent)

    def _remove(self) -> None:
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def _shift(self, delta: int) -> None:
        row = self.list.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(new, item)
        self.list.setCurrentRow(new)

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save combined PDF", self.output.text(), "PDF (*.pdf)")
        if path:
            self.output.setText(path if path.lower().endswith(".pdf") else path + ".pdf")

    def _accept(self) -> None:
        files = self.files()
        if len(files) < 1:
            _warn(self, "Add the files to combine.")
            return
        out = Path(self.output.text().strip())
        if out.suffix.lower() != ".pdf":
            _warn(self, "Choose a .pdf file name for the result.")
            return
        if any(Path(f).resolve() == out.resolve() for f in files):
            _warn(self, "The result must have a different name from the files being combined.")
            return
        if out.exists() and QMessageBox.question(self, "Combine", f"{out.name} exists. Replace it?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.accept()


# =================================================================== replace
class ReplaceDialog(QDialog):
    def __init__(self, page_count: int, default: list[int], start_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Replace pages")
        self.setMinimumWidth(520)
        self.page_count = page_count
        self.pages_edit = QLineEdit(_range_text(default))
        self.file_edit = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: _pick_file(self, self.file_edit, start_dir))
        self.src_pages = QLineEdit()
        self.src_pages.setPlaceholderText("all pages (or e.g. 2-4)")
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(browse)
        form = QFormLayout()
        form.addRow("Replace pages:", self.pages_edit)
        form.addRow("With pages from:", file_row)
        form.addRow("Using its pages:", self.src_pages)
        note = QLabel("The new pages go where the first replaced page was. Use Edit > Undo to go back.")
        note.setStyleSheet("color: gray")
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Replace")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(buttons)
        self.pages: list[int] = []

    def _accept(self) -> None:
        try:
            self.pages = parse_page_range(self.pages_edit.text(), self.page_count)
        except ValueError as exc:
            _warn(self, str(exc))
            return
        if not Path(self.file_edit.text().strip()).is_file():
            _warn(self, "Choose the file that contains the new pages.")
            return
        self.accept()


# ====================================================================== move
class MoveDialog(QDialog):
    def __init__(self, page_count: int, default: list[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Move pages")
        self.page_count = page_count
        self.pages_edit = QLineEdit(_range_text(default))
        self.position = PositionPicker(page_count, (default[-1] if default else 0) + 1)
        form = QFormLayout()
        form.addRow("Pages to move:", self.pages_edit)
        form.addRow("Move them:", self.position)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Move")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel("Tip: in Organise Pages you can simply drag pages to a new place."))
        lay.addWidget(buttons)
        self.pages: list[int] = []

    def _accept(self) -> None:
        try:
            self.pages = parse_page_range(self.pages_edit.text(), self.page_count)
        except ValueError as exc:
            _warn(self, str(exc))
            return
        self.accept()


class SaveChangesBox:
    """Ask how to save an edited document. Returns 'new', 'overwrite', 'discard' or 'cancel'."""

    @staticmethod
    def ask(parent, title: str, closing: bool = False) -> str:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Save changes")
        box.setText(f"<b>{title}</b> has unsaved page changes." if closing else
                    f"How do you want to save the changes to <b>{title}</b>?")
        box.setInformativeText("Saving as a new file keeps your original PDF unchanged.")
        new_btn = box.addButton("Save as new file...", QMessageBox.ButtonRole.AcceptRole)
        over_btn = box.addButton("Overwrite original", QMessageBox.ButtonRole.DestructiveRole)
        discard_btn = box.addButton("Discard changes", QMessageBox.ButtonRole.DestructiveRole) if closing else None
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(new_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is new_btn:
            return "new"
        if clicked is over_btn:
            return "overwrite"
        if discard_btn is not None and clicked is discard_btn:
            return "discard"
        return "cancel"
