"""Headless test of editing and comment tools with real mouse drags in the window.

Run:  .venv\\Scripts\\python tests\\test_edit_ui.py
Saves screenshots to tests\\samples\\screenshots\\.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pump(app, seconds: float, until=None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.02)


def main() -> int:  # noqa: C901 - one long scenario
    import pymupdf as fitz
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from app.database.db import AppDatabase
    from app.pdf_annotation import annots as A
    from app.ui import edit_dialogs as ed
    from app.ui import main_window as mw
    from tests.test_editing import statement_page

    shots = ROOT / "tests" / "samples" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory()
    folder = Path(tmp.name)
    src = folder / "statement.pdf"
    d = fitz.open()
    statement_page(d)
    statement_page(d)
    d.save(src)
    d.close()

    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.exec = lambda self: 0
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: 0)
    errors = []
    QMessageBox.warning = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a) or 0)
    db = AppDatabase(folder / "ui.sqlite3")
    win = mw.MainWindow(db)
    win.resize(1300, 900)
    win.show()
    tab = win.open_file(str(src))
    doc, view = tab.doc, tab.view
    view.set_zoom(1.0)
    pump(app, 0.8)

    def vp(page: int, x: float, y: float) -> QPoint:
        """Viewport position of a page-space point."""
        v = fitz.Point(x, y) * view._matrix(page)
        r = view._page_rect[page]
        return view._content_to_viewport(QPointF(r.left() + v.x, r.top() + v.y)).toPoint()

    def drag(page, a, b, steps=6):
        w = view.viewport()
        QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vp(page, *a))
        for k in range(1, steps + 1):
            x = a[0] + (b[0] - a[0]) * k / steps
            y = a[1] + (b[1] - a[1]) * k / steps
            QTest.mouseMove(w, vp(page, x, y))
        QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vp(page, *b))
        pump(app, 0.15)

    def click(page, x, y):
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vp(page, x, y))
        pump(app, 0.15)

    def kinds(page=0):
        return [i.kind for i in doc.run_read(lambda dd: A.list_annots(dd[page]))]

    def text(page=0):
        flags = fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_PRESERVE_LIGATURES
        return " ".join(doc.run_read(lambda dd: dd[page].get_text(flags=flags)).split())

    original = text()
    view.goto_page(0)
    pump(app, 0.3)

    def word_box(word: str, page: int = 0):
        return doc.run_read(lambda dd: next(fitz.Rect(x[:4]) for x in dd[page].get_text("words") if x[4] == word))

    # 1. highlight by dragging over the first line
    first = word_box("Opening")
    mid_y = (first.y0 + first.y1) / 2
    win.actions["tool_highlight"].trigger()
    drag(0, (first.x0 - 3, mid_y), (300, mid_y))
    assert kinds() == ["Highlight"], kinds()

    # 2. rectangle, 3. pen
    win.actions["tool_rect"].trigger()
    drag(0, (80, 200), (220, 260))
    win.actions["tool_pen"].trigger()
    drag(0, (300, 200), (380, 240), steps=10)
    assert kinds() == ["Highlight", "Square", "Ink"], kinds()
    sq = doc.run_read(lambda dd: A.list_annots(dd[0]))[1]
    assert abs(sq.rect.x0 - 80) < 3 and abs(sq.rect.y1 - 260) < 3, sq.rect

    # 4. select, move, resize, properties, delete + undo
    win.actions["tool_select"].trigger()
    click(0, 150, 230)
    assert view.selected_annot is not None and view.selected_annot.kind == "Square"
    drag(0, (150, 230), (170, 280))
    moved = view.selected_annot.rect
    assert abs(moved.x0 - 100) < 4 and abs(moved.y0 - 250) < 4, moved
    vr = view._to_view_rect(0, moved).normalized().adjusted(-3, -3, 3, 3)
    handle = view._handle_rect(vr).center()
    r0 = view._page_rect[0]
    start = view._content_to_viewport(QPointF(r0.left() + handle.x(), r0.top() + handle.y())).toPoint()
    w = view.viewport()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(w, start + QPoint(40, 30))
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(40, 30))
    pump(app, 0.2)
    assert view.selected_annot.rect.width > moved.width + 30, (view.selected_annot.rect, moved)
    win.props.color.set_color((0, 0.6, 0))
    win.props.width.setValue(3)
    win.props._apply()
    pump(app, 0.2)
    sel = view.selected_annot
    assert sel.width == 3 and abs(sel.stroke[1] - 0.6) < 0.05, (sel.width, sel.stroke)
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    pump(app, 0.2)
    assert kinds() == ["Highlight", "Ink"], kinds()
    win.actions["undo"].trigger()
    assert kinds() == ["Highlight", "Ink", "Square"] or "Square" in kinds(), kinds()

    # 5. sticky note, 6. text box, 7. stamp
    ed.CommentTextDialog.exec = lambda self: (self.edit.setPlainText("Check this entry"), QDialog.DialogCode.Accepted)[1]
    win.actions["tool_note"].trigger()
    click(0, 450, 300)
    assert view.tool == "select" and view.selected_annot.kind == "Text", view.tool
    win.actions["tool_textbox"].trigger()
    drag(0, (80, 320), (300, 370))
    ed.StampDialog.exec = lambda self: QDialog.DialogCode.Accepted
    win.actions["tool_stamp"].trigger()
    click(0, 350, 450)
    k = kinds()
    assert k.count("FreeText") == 2 and "Text" in k, k

    # 8. add text (Bengali + English), 9. edit a line, 10. delete a word
    def add_text_exec(self):
        self.edit.setPlainText("Verified by BM - যাচাই করা হয়েছে")
        return QDialog.DialogCode.Accepted
    ed.TextDialog.exec = add_text_exec
    win.actions["tool_add_text"].trigger()
    click(0, 80, 600)
    assert "Verified by BM" in text(), text()

    def edit_exec(self):
        assert self.text.startswith("Opening balance"), self.text
        self.edit.setPlainText("Opening balance 2,00,000.00 as on 01-06-2025")
        return QDialog.DialogCode.Accepted
    ed.TextDialog.exec = edit_exec
    win.actions["tool_edit_text"].trigger()
    click(0, 150, mid_y)
    assert "2,00,000.00" in text() and "1,25,430.50" not in text(), text()
    win.actions["tool_delete_text"].trigger()
    w_acc = doc.run_read(lambda dd: next(fitz.Rect(x[:4]) for x in dd[0].get_text("words") if x[4] == "EMI"))
    drag(0, (w_acc.x0 + 1, (w_acc.y0 + w_acc.y1) / 2), (w_acc.x1 - 1, (w_acc.y0 + w_acc.y1) / 2 + 1))
    assert " EMI " not in f" {text()} ", text()

    # 11. redaction: mark the account number, apply
    win.actions["tool_redact"].trigger()
    acc = doc.run_read(lambda dd: dd[0].search_for("1234567890")[0])
    drag(0, (acc.x0 - 2, acc.y0 - 1), (acc.x1 + 2, acc.y1 + 1))
    ed.ApplyRedactionsDialog.exec = lambda self: QDialog.DialogCode.Accepted
    win.apply_redactions()
    assert "1234567890" not in text(), text()

    # 12. watermark, 13. header/footer (all pages)
    ed.WatermarkDialog.exec = lambda self: QDialog.DialogCode.Accepted
    win.add_watermark()
    ed.HeaderFooterDialog.exec = lambda self: QDialog.DialogCode.Accepted
    win.add_header_footer()
    assert "CONFIDENTIAL" in text(1) and "Page 2 of 2" in text(1), text(1)
    pump(app, 1.0)
    win.actions["tool_select"].trigger()
    click(0, 120, 340)
    pump(app, 0.8)
    win.grab().save(str(shots / "edit_1_page.png"))

    # 14. comments list
    tab.side.setCurrentWidget(tab.comments)
    pump(app, 0.3)
    assert tab.comments.topLevelItemCount() >= 1
    win.grab().save(str(shots / "edit_2_comments.png"))

    # 15. save as new file and reopen
    out = folder / "statement - edited.pdf"
    mw.SaveChangesBox.ask = staticmethod(lambda *a, **k: "new")
    mw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out), ""))
    win.save()
    with fitz.open(out) as dd:
        assert len(A.list_annots(dd[0])) >= 5
        assert "2,00,000.00" in dd[0].get_text() and "1234567890" not in dd[0].get_text()

    # 16. undo everything -> back to the original text, no comments
    while doc.undo_label:
        win.actions["undo"].trigger()
    assert text() == original, (text(), original)
    assert kinds() == [], kinds()
    assert not errors, errors

    print("OK: editing works (highlight, shapes, pen, select/move/resize/properties/delete, note, text box, "
          "stamp, add/edit/delete text, redaction, watermark, header/footer, comments list, save, undo)")
    mw.SaveChangesBox.ask = staticmethod(lambda *a, **k: "discard")
    win.close()
    db.close()
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
