"""One 'Save' window for edited / OCR documents.

Asks:
  * format   - Word (.docx), PDF, or both
  * where    - the same folder as the original PDF, or another folder
  * name     - the file name (without extension)
  * original - keep the original PDF (default) or move it to the Recycle Bin after saving
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFile
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QRadioButton, QVBoxLayout,
)


@dataclass
class SaveChoice:
    targets: list[Path]             # files to write (.docx and/or .pdf)
    delete_original: bool


def free_name(folder: Path, stem: str, ext: str) -> Path:
    p = folder / f"{stem}{ext}"
    k = 2
    while p.exists():
        p = folder / f"{stem} ({k}){ext}"
        k += 1
    return p


class SaveOptionsDialog(QDialog):
    def __init__(self, original: Path | None, stem: str, formats=("word", "pdf"), default_format: str = "word",
                 parent=None, title: str = "Save"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.original = Path(original) if original else None
        self.choice: SaveChoice | None = None
        start_folder = self.original.parent if self.original else Path.home()

        # format
        fmt_box = QGroupBox("Save as")
        self.rb_word = QRadioButton("Word document (.docx) - edit later in Word")
        self.rb_pdf = QRadioButton("PDF (.pdf)")
        self.rb_both = QRadioButton("Both Word and PDF")
        g = QButtonGroup(self)
        fl = QVBoxLayout(fmt_box)
        for rb, key in ((self.rb_word, "word"), (self.rb_pdf, "pdf"), (self.rb_both, "both")):
            g.addButton(rb)
            fl.addWidget(rb)
            rb.setVisible(key in formats or (key == "both" and len(formats) > 1))
            rb.toggled.connect(self._update_preview)
        {"word": self.rb_word, "pdf": self.rb_pdf, "both": self.rb_both}.get(default_format, self.rb_word).setChecked(True)

        # where
        where_box = QGroupBox("Where")
        self.rb_same = QRadioButton(f"Same folder as the original PDF:  {start_folder}")
        self.rb_other = QRadioButton("Another folder:")
        self.folder_edit = QLineEdit(str(start_folder))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        g2 = QButtonGroup(self)
        g2.addButton(self.rb_same)
        g2.addButton(self.rb_other)
        self.rb_same.setChecked(True)
        self.rb_same.setVisible(self.original is not None)
        if self.original is None:
            self.rb_other.setChecked(True)
        wl = QVBoxLayout(where_box)
        wl.addWidget(self.rb_same)
        row = QHBoxLayout()
        row.addWidget(self.rb_other)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        wl.addLayout(row)
        self.folder_edit.textEdited.connect(lambda _t: self.rb_other.setChecked(True))
        for w in (self.rb_same, self.rb_other):
            w.toggled.connect(self._update_preview)
        self.folder_edit.textChanged.connect(self._update_preview)

        # name
        self.name_edit = QLineEdit(stem)
        self.name_edit.textChanged.connect(self._update_preview)
        form = QFormLayout()
        form.addRow("File name:", self.name_edit)

        # original
        orig_box = QGroupBox("The original PDF")
        self.keep = QRadioButton("Keep it (recommended)")
        self.delete = QRadioButton("Delete it after saving (it goes to the Recycle Bin, so it can be restored)")
        g3 = QButtonGroup(self)
        g3.addButton(self.keep)
        g3.addButton(self.delete)
        self.keep.setChecked(True)
        ol = QVBoxLayout(orig_box)
        if self.original is not None:
            ol.addWidget(QLabel(f"<b>{self.original.name}</b>  in  {self.original.parent}"))
        ol.addWidget(self.keep)
        ol.addWidget(self.delete)
        orig_box.setVisible(self.original is not None and self.original.exists())

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color: gray")

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(fmt_box)
        lay.addWidget(where_box)
        lay.addLayout(form)
        lay.addWidget(orig_box)
        lay.addWidget(self.preview)
        lay.addWidget(bb)
        self._update_preview()

    # --------------------------------------------------------------------
    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder", self.folder_edit.text())
        if d:
            self.folder_edit.setText(d)
            self.rb_other.setChecked(True)

    def folder(self) -> Path:
        if self.rb_same.isChecked() and self.original is not None:
            return self.original.parent
        return Path(self.folder_edit.text().strip() or ".")

    def exts(self) -> list[str]:
        if self.rb_both.isChecked():
            return [".docx", ".pdf"]
        return [".pdf"] if self.rb_pdf.isChecked() else [".docx"]

    def _targets(self) -> list[Path]:
        stem = self.name_edit.text().strip().rstrip(".") or "document"
        for bad in '\\/:*?"<>|':
            stem = stem.replace(bad, "_")
        return [self.folder() / f"{stem}{ext}" for ext in self.exts()]

    def _update_preview(self) -> None:
        if not hasattr(self, "preview") or not hasattr(self, "name_edit"):
            return                                   # still building the window
        names = ", ".join(str(t) for t in self._targets())
        self.preview.setText(f"Will save: {names}")

    def _accept(self) -> None:
        folder = self.folder()
        if not folder.is_dir():
            QMessageBox.warning(self, "Save", f"The folder does not exist:\n{folder}")
            return
        targets = self._targets()
        if self.original is not None and any(t.resolve() == self.original.resolve() for t in targets):
            QMessageBox.warning(self, "Save", "That is the original PDF's own name. Choose another name - the "
                                "original can be deleted separately with the option below.")
            return
        existing = [t for t in targets if t.exists()]
        if existing:
            ans = QMessageBox.question(self, "Save", "These files already exist:\n" +
                                       "\n".join(t.name for t in existing) + "\n\nReplace them?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        delete = self.delete.isChecked() and self.original is not None
        if delete:
            ans = QMessageBox.question(self, "Delete the original?",
                                       f"After saving, {self.original.name} will be moved to the Recycle Bin.\n\n"
                                       "Continue?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.choice = SaveChoice(targets, delete)
        self.accept()


def move_to_recycle_bin(path: Path) -> tuple[bool, str]:
    """Move a file to the Recycle Bin (never a permanent delete). Returns (ok, message)."""
    try:
        if not path.exists():
            return True, "already gone"
        ok = QFile.moveToTrash(str(path))
        if isinstance(ok, tuple):          # PySide6 returns (bool, newPath) on some versions
            ok = ok[0]
        return (True, "") if ok else (False, "Windows did not allow moving it to the Recycle Bin.")
    except Exception as exc:  # pragma: no cover
        return False, str(exc)
