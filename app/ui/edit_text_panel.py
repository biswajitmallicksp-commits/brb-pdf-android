"""Edit Text panel: every line of the current page in a list at the side.

Type over a line to rewrite it, or press X to delete it, then Apply Changes.
The old words are really removed from the PDF and the new words written in the
same place, size and colour (closest font). Clicking a line on the page jumps to
it in the list; clicking a row shows the line on the page.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from app.pdf_editor import content
from app.pdf_viewer.document import SearchHit

CHANGED = "background:#fff4cc;"
DELETED = "background:#ffd9d9; color:#9a9a9a; text-decoration:line-through;"


class _Row(QWidget):
    changed = Signal()
    focused = Signal(object)

    def __init__(self, line: content.TextLine, parent=None):
        super().__init__(parent)
        self.line = line
        self.edit = QLineEdit(line.text)
        f = QFont(self.edit.font())
        f.setBold(line.style().bold)
        self.edit.setFont(f)
        self.edit.setEnabled(line.editable)
        if not line.editable:
            self.edit.setToolTip("Sideways or slanted text cannot be edited here.")
        self.edit.textChanged.connect(self._on_change)
        self.edit.installEventFilter(self)
        self.delete = QToolButton()
        self.delete.setText("✕")
        self.delete.setToolTip("Delete this line (press again to bring it back)")
        self.delete.setEnabled(line.editable)
        self.delete.clicked.connect(self._toggle_delete)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(4)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.delete)

    @property
    def new_text(self) -> str:
        return self.edit.text()

    @property
    def is_changed(self) -> bool:
        return self.edit.text() != self.line.text

    def _toggle_delete(self) -> None:
        self.edit.setText(self.line.text if not self.edit.text() else "")
        self.focused.emit(self)

    def _on_change(self) -> None:
        if not self.is_changed:
            self.edit.setStyleSheet("")
            self.edit.setPlaceholderText("")
        elif not self.edit.text():
            self.edit.setStyleSheet(DELETED)
            self.edit.setPlaceholderText(f"(deleted) {self.line.text}")
        else:
            self.edit.setStyleSheet(CHANGED)
        self.changed.emit()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.edit and event.type() == event.Type.FocusIn:
            self.focused.emit(self)
        return False


class EditTextPanel(QWidget):
    """Lives in a dock at the right of the main window."""
    applyRequested = Signal(int, list)          # page, [(TextLine, new text)]
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tab = None
        self.page = -1
        self.rows: list[_Row] = []
        self._pending_page: int | None = None

        self.title = QLabel("<b>Edit Text</b>")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.banner = QPushButton("")
        self.banner.setVisible(False)
        self.banner.setStyleSheet("text-align:left; padding:6px; background:#2f6fdb; color:white; border:none;")
        self.banner.clicked.connect(self._load_pending)
        self.apply_btn = QPushButton("Apply Changes")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self._apply)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Undo the changes typed in this list (not yet applied)")
        self.reset_btn.clicked.connect(self.reload)

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_layout.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.list_widget)

        help_text = QLabel("Type over a line to change it, or press ✕ to delete it, then <b>Apply Changes</b>. "
                           "Click a line on the page to find it here. Edit &gt; Undo reverses an applied change.")
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color:gray;")

        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_btn, 1)
        buttons.addWidget(self.reset_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self.title)
        lay.addWidget(help_text)
        lay.addWidget(self.status)
        lay.addWidget(self.banner)
        lay.addWidget(self.scroll, 1)
        lay.addLayout(buttons)
        self._refresh_buttons()

    # ------------------------------------------------------------ loading
    def show_page(self, tab, page: int, force: bool = False) -> None:
        """Show the lines of `page` of `tab` (asks first if typed changes would be lost)."""
        if tab is None:
            self.tab, self.page = None, -1
            self._clear()
            self.status.setText("Open a PDF to edit its text.")
            return
        if not force and tab is self.tab and page == self.page:
            return                                   # already showing this page
        if not force and tab is self.tab and page != self.page and self.pending_count():
            self._pending_page = page
            self.banner.setText(f"You are now on page {page + 1}. Apply your changes first, or click here to "
                                f"edit page {page + 1} (changes not applied will be lost).")
            self.banner.setVisible(True)
            return
        self.tab, self.page = tab, page
        self.reload()

    def _load_pending(self) -> None:
        if self._pending_page is not None and self.tab is not None:
            self.show_page(self.tab, self._pending_page, force=True)

    def reload(self) -> None:
        self.banner.setVisible(False)
        self._pending_page = None
        self._clear()
        if self.tab is None or self.page < 0:
            return
        page = self.page
        try:
            lines = self.tab.doc.run_read(lambda d: content.page_lines(d[page]))
        except Exception as exc:  # pragma: no cover - shown to the user
            self.status.setText(f"Could not read the text: {exc}")
            return
        self.title.setText(f"<b>Edit Text - page {page + 1}</b>")
        if not lines:
            self.status.setText("No editable text on this page. A scanned page is a picture: its words "
                                "cannot be changed (OCR only adds invisible text for searching).")
        else:
            self.status.setText(f"{len(lines)} lines")
        for ln in lines:
            row = _Row(ln)
            row.changed.connect(self._refresh_buttons)
            row.focused.connect(self._show_on_page)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self.rows.append(row)
        self._refresh_buttons()

    def _clear(self) -> None:
        for r in self.rows:
            r.setParent(None)
            r.deleteLater()
        self.rows = []
        self._refresh_buttons()
        if self.tab is not None:
            self.tab.view.clear_search()

    # ------------------------------------------------------------ state
    def pending_count(self) -> int:
        return sum(1 for r in self.rows if r.is_changed)

    def _refresh_buttons(self) -> None:
        n = self.pending_count()
        self.apply_btn.setEnabled(n > 0)
        self.apply_btn.setText(f"Apply Changes ({n})" if n else "Apply Changes")
        self.reset_btn.setEnabled(n > 0)

    def _show_on_page(self, row: _Row) -> None:
        if self.tab is None:
            return
        hit = SearchHit(row.line.page, row.line.rect)
        self.tab.view.set_search_hits([hit])
        self.tab.view.show_hit(hit)

    def pick(self, page: int, point) -> bool:
        """A click on the page: select the line under it in the list. Returns False if no text there."""
        if page != self.page:
            self.show_page(self.tab, page)
            if page != self.page:
                return True
        best = None
        for r in self.rows:
            box = r.line.rect
            if box.x0 - 2 <= point.x <= box.x1 + 2 and box.y0 - 2 <= point.y <= box.y1 + 2:
                if best is None or abs(box) < abs(best.line.rect):
                    best = r
        if best is None:
            return False
        self._show_on_page(best)
        self.scroll.ensureWidgetVisible(best)
        # after the page view has finished handling the click, move the keyboard to the row
        def focus(edit=best.edit):
            edit.setFocus(Qt.FocusReason.MouseFocusReason)
            edit.selectAll()
        QTimer.singleShot(0, focus)
        return True

    def _apply(self) -> None:
        changes = [(r.line, r.new_text) for r in self.rows if r.is_changed]
        if changes and self.page >= 0:
            self.applyRequested.emit(self.page, changes)

    def discard_ok(self) -> bool:
        """True when nothing typed would be lost."""
        return self.pending_count() == 0
