"""Right-hand panel: style of the current tool, or properties of the selected annotation.
Also the 'Comments' list for the left panel."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSpinBox,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.pdf_annotation import annots
from app.ui.widgets import ColorButton

# default look of each tool
DEFAULT_STYLES = {
    "highlight": annots.AnnotStyle(stroke=(1.0, 0.85, 0.0), opacity=0.5),
    "underline": annots.AnnotStyle(stroke=(0.1, 0.35, 0.9)),
    "strike": annots.AnnotStyle(stroke=(0.85, 0.1, 0.1)),
    "squiggly": annots.AnnotStyle(stroke=(0.85, 0.1, 0.1)),
    "note": annots.AnnotStyle(stroke=(1.0, 0.8, 0.0)),
    "textbox": annots.AnnotStyle(stroke=(0.1, 0.1, 0.1), width=1.0, fontsize=11, text_color=(0.1, 0.1, 0.1)),
    "rect": annots.AnnotStyle(stroke=(0.85, 0.1, 0.1), width=1.5),
    "ellipse": annots.AnnotStyle(stroke=(0.85, 0.1, 0.1), width=1.5),
    "line": annots.AnnotStyle(stroke=(0.85, 0.1, 0.1), width=1.5),
    "arrow": annots.AnnotStyle(stroke=(0.85, 0.1, 0.1), width=1.5),
    "pen": annots.AnnotStyle(stroke=(0.1, 0.3, 0.85), width=2.0),
    "stamp": annots.AnnotStyle(stroke=(0.8, 0.05, 0.05)),
    "redact": annots.AnnotStyle(stroke=(0, 0, 0), fill=(0, 0, 0)),
}
TOOL_HELP = {
    "select": "Click a comment to select it: drag to move, drag the blue corner to resize, "
              "Delete to remove, double-click to change its text.",
    "hand": "Drag to scroll the page.",
    "highlight": "Drag over text to highlight it.", "underline": "Drag over text to underline it.",
    "strike": "Drag over text to strike it through.", "squiggly": "Drag over text for a wavy underline.",
    "note": "Click where the sticky note should go.", "textbox": "Drag a box, then type the comment.",
    "rect": "Drag to draw a rectangle.", "ellipse": "Drag to draw an ellipse or circle.",
    "line": "Drag to draw a line.", "arrow": "Drag to draw an arrow.", "pen": "Draw freehand.",
    "stamp": "Click where the stamp should go.", "eraser": "Click a comment, shape or stamp to delete it.",
    "redact": "Drag over areas to MARK them; Tools > Apply Redactions removes them for good.",
    "add_text": "Click or drag a box where the new text should go.",
    "edit_text": "Click a line of text to change it.",
    "delete_text": "Drag over the words to delete.",
    "add_image": "Click or drag a box where the picture should go.",
    "delete_image": "Drag over a picture to delete it.",
}
TOOL_NAMES = {
    "select": "Select", "hand": "Hand", "highlight": "Highlight", "underline": "Underline",
    "strike": "Strikethrough", "squiggly": "Squiggly underline", "note": "Sticky note", "textbox": "Text box",
    "rect": "Rectangle", "ellipse": "Ellipse", "line": "Line", "arrow": "Arrow", "pen": "Pen",
    "stamp": "Stamp", "eraser": "Eraser", "redact": "Redact", "add_text": "Add text",
    "edit_text": "Edit text", "delete_text": "Delete text", "add_image": "Add picture",
    "delete_image": "Delete picture",
}


def style_to_json(style: annots.AnnotStyle) -> str:
    return json.dumps(style.__dict__)


def style_from_json(text: str, default: annots.AnnotStyle) -> annots.AnnotStyle:
    try:
        data = json.loads(text)
        return annots.AnnotStyle(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in data.items()})
    except Exception:
        return default


class PropertiesPanel(QWidget):
    toolStyleChanged = Signal(str, object)          # tool, AnnotStyle
    applyToAnnot = Signal(object, object, object)   # AnnotInfo, AnnotStyle, contents (str or None)
    deleteAnnot = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(230)
        self._tool = "select"
        self._annot: annots.AnnotInfo | None = None
        self._loading = False

        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setStyleSheet("color: gray")
        self.color = ColorButton()
        self.fill = ColorButton((1, 1, 1))
        self.no_fill = QCheckBox("No fill")
        self.no_fill.setChecked(True)
        self.width = QDoubleSpinBox()
        self.width.setRange(0, 20)
        self.width.setSingleStep(0.5)
        self.opacity = QSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setSuffix(" %")
        self.fontsize = QDoubleSpinBox()
        self.fontsize.setRange(4, 96)
        self.text_color = ColorButton()
        fill_row = QHBoxLayout()
        fill_row.addWidget(self.fill)
        fill_row.addWidget(self.no_fill)
        fill_row.addStretch(1)
        self.fill_row = fill_row
        self.form = QFormLayout()
        self.form.addRow("Colour:", self.color)
        self.form.addRow("Fill:", fill_row)
        self.form.addRow("Line width:", self.width)
        self.form.addRow("Opacity:", self.opacity)
        self.form.addRow("Font size:", self.fontsize)
        self.form.addRow("Text colour:", self.text_color)
        self.contents = QPlainTextEdit()
        self.contents.setPlaceholderText("Comment text")
        self.contents.setMaximumHeight(120)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: gray")
        self.apply_btn = QPushButton("Apply changes")
        self.delete_btn = QPushButton("Delete")
        btns = QHBoxLayout()
        btns.addWidget(self.apply_btn)
        btns.addWidget(self.delete_btn)

        lay = QVBoxLayout(self)
        lay.addWidget(self.title)
        lay.addWidget(self.help)
        lay.addLayout(self.form)
        lay.addWidget(self.contents)
        lay.addWidget(self.info)
        lay.addLayout(btns)
        lay.addStretch(1)

        for sig in (self.color.colorChanged, self.fill.colorChanged, self.text_color.colorChanged):
            sig.connect(lambda _v: self._edited())
        for w in (self.width, self.opacity, self.fontsize):
            w.valueChanged.connect(lambda _v: self._edited())
        self.no_fill.toggled.connect(lambda _v: self._edited())
        self.apply_btn.clicked.connect(self._apply)
        self.delete_btn.clicked.connect(lambda: self._annot and self.deleteAnnot.emit(self._annot))
        self.show_tool("select", None)

    # --------------------------------------------------------------- views
    def _show_rows(self, color=True, fill=False, width=False, fontsize=False, text_color=False,
                   opacity=True) -> None:
        self.form.setRowVisible(self.color, color)
        self.form.setRowVisible(self.fill_row, fill)
        self.form.setRowVisible(self.width, width)
        self.form.setRowVisible(self.opacity, opacity)
        self.form.setRowVisible(self.fontsize, fontsize)
        self.form.setRowVisible(self.text_color, text_color)

    def _load_style(self, style: annots.AnnotStyle) -> None:
        self._loading = True
        self.color.set_color(style.stroke or (0, 0, 0))
        self.no_fill.setChecked(style.fill is None)
        if style.fill is not None:
            self.fill.set_color(style.fill)
        self.width.setValue(style.width)
        self.opacity.setValue(int(round((style.opacity or 1) * 100)))
        self.fontsize.setValue(style.fontsize)
        self.text_color.set_color(style.text_color or (0, 0, 0))
        self._loading = False

    def current_style(self) -> annots.AnnotStyle:
        return annots.AnnotStyle(stroke=self.color.color(), fill=None if self.no_fill.isChecked() else self.fill.color(),
                                 width=self.width.value(), opacity=self.opacity.value() / 100,
                                 fontsize=self.fontsize.value(), text_color=self.text_color.color())

    def show_tool(self, tool: str, style: annots.AnnotStyle | None) -> None:
        self._tool = tool
        self._annot = None
        self.title.setText(TOOL_NAMES.get(tool, tool))
        self.help.setText(TOOL_HELP.get(tool, ""))
        has_style = style is not None
        if has_style:
            self._load_style(style)
        shapes = tool in ("rect", "ellipse")
        self._show_rows(color=has_style and tool not in ("redact", "textbox"),
                        fill=has_style and (shapes or tool in ("redact", "textbox")),
                        width=has_style and tool in ("rect", "ellipse", "line", "arrow", "pen", "textbox"),
                        fontsize=has_style and tool == "textbox", text_color=has_style and tool == "textbox",
                        opacity=has_style and tool != "redact")
        self.contents.setVisible(False)
        self.info.setText("")
        self.apply_btn.setVisible(False)
        self.delete_btn.setVisible(False)

    def show_annot(self, info: annots.AnnotInfo | None) -> None:
        if info is None:
            self.show_tool(self._tool, None if self._tool in ("select", "hand") else self._last_tool_style)
            return
        self._annot = info
        self.title.setText(info.label)
        self.help.setText("Change the settings and click Apply changes. Drag on the page to move it.")
        style = annots.AnnotStyle(stroke=info.stroke or (0, 0, 0), fill=info.fill, width=info.width,
                                  opacity=info.opacity, fontsize=info.fontsize,
                                  text_color=info.text_color or (0, 0, 0))
        self._load_style(style)
        kind = info.kind
        self._show_rows(color=kind not in ("Redact", "FreeText"),
                        fill=kind in ("Square", "Circle", "Polygon", "FreeText"),
                        width=kind in ("Square", "Circle", "Line", "Ink", "Polygon", "PolyLine", "FreeText"),
                        fontsize=kind == "FreeText", text_color=kind == "FreeText", opacity=kind != "Redact")
        self.contents.setVisible(info.kind not in ("Redact",))
        self.contents.setPlainText(info.contents)
        when = info.modified[2:10] if info.modified.startswith("D:") else ""
        when = f"{when[6:8]}-{when[4:6]}-{when[0:4]}" if len(when) == 8 else ""
        self.info.setText(f"Page {info.page + 1}" + (f"  -  by {info.author}" if info.author else "")
                          + (f"  -  {when}" if when else ""))
        self.apply_btn.setVisible(True)
        self.delete_btn.setVisible(True)

    _last_tool_style: annots.AnnotStyle | None = None

    def set_tool_style(self, style: annots.AnnotStyle | None) -> None:
        self._last_tool_style = style

    # ------------------------------------------------------------- signals
    def _edited(self) -> None:
        if self._loading or self._annot is not None:
            return
        if self._tool not in ("select", "hand"):
            style = self.current_style()
            self._last_tool_style = style
            self.toolStyleChanged.emit(self._tool, style)

    def _apply(self) -> None:
        if self._annot is None:
            return
        text = self.contents.toPlainText() if self.contents.isVisible() else None
        if text is not None and text == self._annot.contents:
            text = None
        self.applyToAnnot.emit(self._annot, self.current_style(), text)


class CommentsPanel(QTreeWidget):
    """All comments (annotations) of the document, grouped by page. Click one to go there."""

    activated = Signal(int, int)        # page, xref

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Comment", "Text"])
        self.setRootIsDecorated(True)
        self.setColumnWidth(0, 130)
        self.itemClicked.connect(self._clicked)

    def load(self, doc) -> None:
        def read(d):
            out = []
            for pno in range(d.page_count):
                page = d[pno]
                if page.first_annot is None:
                    continue
                infos = [i for i in annots.list_annots(page) if i.kind not in ("Popup", "Link", "Widget")]
                if infos:
                    out.append((pno, infos))
            return out
        try:
            data = doc.run_read(read)
        except Exception:
            data = []
        self.clear()
        total = 0
        for pno, infos in data:
            parent = QTreeWidgetItem([f"Page {pno + 1}", f"{len(infos)} item(s)"])
            self.addTopLevelItem(parent)
            for info in infos:
                item = QTreeWidgetItem([info.label, info.contents.replace("\n", " ")[:80]])
                item.setData(0, Qt.ItemDataRole.UserRole, (pno, info.xref))
                item.setToolTip(1, info.contents)
                parent.addChild(item)
                total += 1
            parent.setExpanded(True)
        if total == 0:
            empty = QTreeWidgetItem(["No comments", "Use the comment tools to add some."])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addTopLevelItem(empty)

    def _clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            self.activated.emit(*data)
