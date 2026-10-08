"""Dialogs for editing: add/edit text, note text, stamps, watermark, header & footer, redaction."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from app.pdf_annotation import annots
from app.pdf_editor import content, fonts
from app.ui.widgets import ColorButton
from app.utils.pages import parse_page_range

PAGE_SCOPES = [("all", "All pages"), ("current", "Current page"), ("first", "First page only"),
               ("odd", "Odd pages"), ("even", "Even pages"), ("range", "Pages:")]


def _buttons(dlg: QDialog, ok_text: str) -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    b.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


class PageScope(QWidget):
    """Which pages: all / current / first / odd / even / a range."""

    def __init__(self, page_count: int, current: int, parent=None):
        super().__init__(parent)
        self.page_count = page_count
        self.current = current
        self.combo = QComboBox()
        for key, label in PAGE_SCOPES:
            self.combo.addItem(label, key)
        self.range = QLineEdit()
        self.range.setPlaceholderText("e.g. 1-5, 8")
        self.range.setEnabled(False)
        self.combo.currentIndexChanged.connect(lambda _i: self.range.setEnabled(self.combo.currentData() == "range"))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.combo)
        lay.addWidget(self.range, 1)

    def pages(self) -> list[int]:
        key = self.combo.currentData()
        n = self.page_count
        if key == "all":
            return list(range(n))
        if key == "current":
            return [self.current]
        if key == "first":
            return [0]
        if key == "odd":
            return list(range(0, n, 2))
        if key == "even":
            return list(range(1, n, 2))
        return parse_page_range(self.range.text(), n)


# ===================================================================== text
class TextDialog(QDialog):
    """Type new text (any language) and choose its look. Used by Add Text and Edit Text."""

    def __init__(self, title: str, text: str, style: content.TextStyle, note: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 360)
        self.edit = QPlainTextEdit(text)
        f = self.edit.font()
        f.setPointSizeF(max(10.0, f.pointSizeF() * 1.15))
        self.edit.setFont(f)
        self.family = QComboBox()
        for fam in fonts.font_families():
            self.family.addItem(fam.label, fam.key)
        idx = self.family.findData(style.family)
        self.family.setCurrentIndex(max(0, idx))
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 144)
        self.size.setDecimals(1)
        self.size.setValue(style.size)
        self.bold = QCheckBox("Bold")
        self.bold.setChecked(style.bold)
        self.italic = QCheckBox("Italic")
        self.italic.setChecked(style.italic)
        self.color = ColorButton(style.color)
        self.align = QComboBox()
        for a in ("left", "center", "right"):
            self.align.addItem(a.capitalize(), a)
        self.align.setCurrentIndex(max(0, self.align.findData(style.align)))
        row = QHBoxLayout()
        for w in (QLabel("Font:"), self.family, QLabel("Size:"), self.size, self.bold, self.italic,
                  QLabel("Colour:"), self.color, QLabel("Align:"), self.align):
            row.addWidget(w)
        row.addStretch(1)
        hint = QLabel(note or "Bengali and Hindi text uses the Nirmala UI font automatically.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(self.edit, 1)
        lay.addWidget(hint)
        lay.addWidget(_buttons(self, "OK"))
        self.edit.setFocus()
        self.edit.selectAll()

    @property
    def text(self) -> str:
        return self.edit.toPlainText()

    def style(self) -> content.TextStyle:
        return content.TextStyle(self.family.currentData(), self.size.value(), self.color.color(),
                                 self.bold.isChecked(), self.italic.isChecked(), self.align.currentData())


class CommentTextDialog(QDialog):
    def __init__(self, title: str, text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 240)
        self.edit = QPlainTextEdit(text)
        lay = QVBoxLayout(self)
        lay.addWidget(self.edit)
        lay.addWidget(_buttons(self, "OK"))
        self.edit.setFocus()

    @property
    def text(self) -> str:
        return self.edit.toPlainText().strip()


# =================================================================== stamps
class StampDialog(QDialog):
    def __init__(self, current: str = "PAID", with_date: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose a stamp")
        self.resize(380, 420)
        self.list = QListWidget()
        for name in annots.OFFICE_STAMPS:
            self.list.addItem(name)
        for name in annots.STANDARD_STAMPS:
            self.list.addItem(annots._stamp_label(name).title() + "  (standard)")
            self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole, name)
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) is None:
                it.setData(Qt.ItemDataRole.UserRole, it.text())
            if it.data(Qt.ItemDataRole.UserRole) == current:
                self.list.setCurrentRow(i)
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("or type your own, e.g. CHECKED BY BM")
        self.with_date = QCheckBox("Add today's date (office stamps)")
        self.with_date.setChecked(with_date)
        lay = QVBoxLayout(self)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.custom)
        lay.addWidget(self.with_date)
        lay.addWidget(QLabel("Then click on the page where the stamp should go."))
        lay.addWidget(_buttons(self, "Choose"))
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())

    @property
    def stamp(self) -> str:
        if self.custom.text().strip():
            return self.custom.text().strip().upper()
        return self.list.currentItem().data(Qt.ItemDataRole.UserRole)


# ================================================================ watermark
class WatermarkDialog(QDialog):
    def __init__(self, page_count: int, current: int, start_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add watermark")
        self.setMinimumWidth(520)
        self.rb_text = QRadioButton("Text")
        self.rb_image = QRadioButton("Image")
        self.rb_text.setChecked(True)
        g = QButtonGroup(self)
        g.addButton(self.rb_text)
        g.addButton(self.rb_image)
        self.text = QLineEdit("CONFIDENTIAL")
        self.fontsize = QSpinBox()
        self.fontsize.setRange(8, 300)
        self.fontsize.setValue(60)
        self.color = ColorButton((0.6, 0.6, 0.6))
        self.angle = QSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setValue(45)
        self.angle.setSuffix("°")
        self.image = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self._pick(start_dir))
        self.scale = QSpinBox()
        self.scale.setRange(5, 100)
        self.scale.setValue(50)
        self.scale.setSuffix(" % of page width")
        self.opacity = QSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setValue(30)
        self.opacity.setSuffix(" %")
        self.position = QComboBox()
        for pos in content.POSITIONS:
            self.position.addItem(pos.replace("-", " ").capitalize(), pos)
        self.position.setCurrentIndex(content.POSITIONS.index("center"))
        self.behind = QCheckBox("Behind the page content")
        self.scope = PageScope(page_count, current)

        tbox = QGroupBox()
        tl = QGridLayout(tbox)
        tl.addWidget(self.rb_text, 0, 0)
        tl.addWidget(self.text, 0, 1, 1, 3)
        tl.addWidget(QLabel("Size:"), 1, 1)
        tl.addWidget(self.fontsize, 1, 2)
        tl.addWidget(QLabel("Colour:"), 2, 1)
        tl.addWidget(self.color, 2, 2)
        tl.addWidget(QLabel("Angle:"), 3, 1)
        tl.addWidget(self.angle, 3, 2)
        tl.addWidget(self.rb_image, 4, 0)
        tl.addWidget(self.image, 4, 1, 1, 2)
        tl.addWidget(browse, 4, 3)
        tl.addWidget(QLabel("Size:"), 5, 1)
        tl.addWidget(self.scale, 5, 2)
        self.text.textEdited.connect(lambda _t: self.rb_text.setChecked(True))
        self.image.textEdited.connect(lambda _t: self.rb_image.setChecked(True))
        form = QFormLayout()
        form.addRow("Opacity:", self.opacity)
        form.addRow("Position:", self.position)
        form.addRow("", self.behind)
        form.addRow("Pages:", self.scope)
        note = QLabel("Text watermarks use English letters. A watermark is added to the page content "
                      "(Edit > Undo removes it).")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addWidget(tbox)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(_buttons(self, "Add watermark"))

    def _pick(self, start: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Watermark image", start,
                                              "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)")
        if path:
            self.image.setText(path)
            self.rb_image.setChecked(True)

    def accept(self) -> None:
        try:
            self.scope.pages()
        except ValueError as exc:
            QMessageBox.warning(self, "Watermark", str(exc))
            return
        if self.rb_text.isChecked() and not self.text.text().strip():
            QMessageBox.warning(self, "Watermark", "Enter the watermark text.")
            return
        if self.rb_image.isChecked() and not Path(self.image.text()).is_file():
            QMessageBox.warning(self, "Watermark", "Choose the image file.")
            return
        super().accept()


# ======================================================== header / footer
class HeaderFooterDialog(QDialog):
    SLOTS = ["top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"]

    def __init__(self, page_count: int, current: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add header and footer")
        self.setMinimumWidth(620)
        self.fields: dict[str, QLineEdit] = {}
        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Left</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Centre</b>"), 0, 2)
        grid.addWidget(QLabel("<b>Right</b>"), 0, 3)
        grid.addWidget(QLabel("Header"), 1, 0)
        grid.addWidget(QLabel("Footer"), 2, 0)
        for k, slot in enumerate(self.SLOTS):
            e = QLineEdit()
            self.fields[slot] = e
            grid.addWidget(e, 1 + k // 3, 1 + k % 3)
        self.fields["bottom-center"].setText("Page {page} of {pages}")
        tokens = QLabel("Codes: {page} page number, {pages} total pages, {date} today, {file} file name")
        tokens.setStyleSheet("color: gray")
        self.fontsize = QDoubleSpinBox()
        self.fontsize.setRange(5, 36)
        self.fontsize.setValue(9)
        self.color = ColorButton((0.2, 0.2, 0.2))
        self.margin = QSpinBox()
        self.margin.setRange(4, 144)
        self.margin.setValue(24)
        self.margin.setSuffix(" pt")
        self.start = QSpinBox()
        self.start.setRange(-1000, 100000)
        self.start.setValue(1)
        self.scope = PageScope(page_count, current)
        form = QFormLayout()
        form.addRow("Font size:", self.fontsize)
        form.addRow("Colour:", self.color)
        form.addRow("Distance from edge:", self.margin)
        form.addRow("First page number:", self.start)
        form.addRow("Pages:", self.scope)
        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addWidget(tokens)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "Add"))

    def items(self) -> list[content.HeaderFooterItem]:
        return [content.HeaderFooterItem(slot, e.text()) for slot, e in self.fields.items() if e.text().strip()]

    def accept(self) -> None:
        if not self.items():
            QMessageBox.warning(self, "Header and footer", "Type the text for at least one position.")
            return
        try:
            self.scope.pages()
        except ValueError as exc:
            QMessageBox.warning(self, "Header and footer", str(exc))
            return
        super().accept()


# ================================================================ redaction
class RedactTextDialog(QDialog):
    def __init__(self, page_count: int, current: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mark text for redaction")
        self.text = QLineEdit()
        self.text.setPlaceholderText("e.g. an account number, PAN, phone number, name")
        self.scope = PageScope(page_count, current)
        form = QFormLayout()
        form.addRow("Find and mark:", self.text)
        form.addRow("In:", self.scope)
        note = QLabel("Every occurrence is MARKED (red boxes). Nothing is removed until you choose "
                      "Tools > Apply Redactions.")
        note.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(_buttons(self, "Mark"))


class ApplyRedactionsDialog(QDialog):
    def __init__(self, marks: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apply redactions")
        self.setMinimumWidth(480)
        warn = QLabel(
            f"<p><b>{marks} area(s) are marked for redaction.</b></p>"
            "<p>Applying PERMANENTLY removes the text, picture pixels and drawings under each mark "
            "and replaces them with a filled box. This is real redaction - unlike drawing a black "
            "rectangle, the hidden information is gone from the file.</p>"
            "<p>You can still Undo before saving. Save the result as a NEW file and keep the "
            "original safe.</p>")
        warn.setWordWrap(True)
        self.metadata = QCheckBox("Also remove document information (title, author, creation tool...)")
        lay = QVBoxLayout(self)
        lay.addWidget(warn)
        lay.addWidget(self.metadata)
        lay.addWidget(_buttons(self, "Apply redactions"))


def mono_font() -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f
