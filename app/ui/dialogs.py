"""Small dialogs: password, document properties, go to page."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QInputDialog, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


def ask_password(parent: QWidget, file_name: str, retry: bool) -> str | None:
    label = (f"The password was not correct. Try again for:\n{file_name}" if retry
             else f"This document is password protected:\n{file_name}\n\nEnter the password to open it.")
    text, ok = QInputDialog.getText(parent, "Password required", label, QLineEdit.EchoMode.Password)
    return text if ok else None


def ask_page(parent: QWidget, current: int, total: int) -> int | None:
    value, ok = QInputDialog.getInt(parent, "Go to page", f"Page number (1 - {total}):",
                                    current + 1, 1, max(1, total))
    return value - 1 if ok else None


class PropertiesDialog(QDialog):
    def __init__(self, properties: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Document properties")
        self.resize(640, 560)
        self._props = properties
        table = QTableWidget(len(properties), 2)
        table.setHorizontalHeaderLabels(["Property", "Value"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        for row, (key, value) in enumerate(properties):
            k = QTableWidgetItem(key)
            k.setFlags(k.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, k)
            table.setItem(row, 1, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.resizeRowsToContents()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = QPushButton("Copy all")
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(self._copy)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(table)
        lay.addWidget(buttons)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText("\n".join(f"{k}\t{v}" for k, v in self._props))
