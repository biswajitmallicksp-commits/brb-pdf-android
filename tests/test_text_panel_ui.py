"""Headless test of the Edit Text panel in the real window.

Run:  .venv\\Scripts\\python tests\\test_text_panel_ui.py
Saves a screenshot to tests\\samples\\screenshots\\text_panel.png
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


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    import pymupdf as fitz
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.database.db import AppDatabase
    from app.ui import main_window as mw

    shots = ROOT / "tests" / "samples" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory()
    folder = Path(tmp.name)
    src = folder / "statement.pdf"
    d = fitz.open()
    for _ in range(2):
        p = d.new_page(width=595, height=842)
        for x, y, t, f in ((60, 100, "Opening balance 12,500.00", "helv"),
                           (60, 120, "NEFT credit ABC Ltd", "hebo"),
                           (330, 120, "5,000.00", "helv"), (440, 120, "17,500.00", "helv"),
                           (60, 140, "ATM withdrawal", "helv"), (330, 140, "2,000.00", "helv")):
            p.insert_text((x, y), t, fontsize=11, fontname=f)
        p.draw_rect(fitz.Rect(50, 85, 540, 150), color=(0, 0, 1))
    d.save(src)
    d.close()

    app = QApplication.instance() or QApplication(sys.argv)
    errors = []
    QMessageBox.warning = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a) or 0)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    db = AppDatabase(folder / "ui.sqlite3")
    win = mw.MainWindow(db)
    win.resize(1400, 900)
    win.show()
    tab = win.open_file(str(src))
    doc, view = tab.doc, tab.view
    view.set_zoom(1.0)
    view.goto_page(0)
    pump(app, 0.8)
    panel = win.text_panel

    def text(page=0):
        return doc.run_read(lambda dd: dd[page].get_text())

    def vp(page: int, x: float, y: float):
        v = fitz.Point(x, y) * view._matrix(page)
        r = view._page_rect[page]
        return view._content_to_viewport(QPointF(r.left() + v.x, r.top() + v.y)).toPoint()

    # 1. open the panel: every line of page 1, columns apart
    win.actions["text_panel"].trigger()
    pump(app, 0.4)
    assert win.text_dock.isVisible()
    assert view.tool == "edit_text", view.tool
    texts = [r.line.text for r in panel.rows]
    assert texts == ["Opening balance 12,500.00", "NEFT credit ABC Ltd", "5,000.00", "17,500.00",
                     "ATM withdrawal", "2,000.00"], texts
    assert not panel.apply_btn.isEnabled()

    # 2. click a line on the page -> its row gets the focus
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vp(0, 80, 117))
    pump(app, 0.3)
    row = next(r for r in panel.rows if r.line.text == "NEFT credit ABC Ltd")
    assert QApplication.focusWidget() is row.edit, QApplication.focusWidget()

    # 3. rewrite one line, delete another, apply
    row.edit.setText("NEFT credit XYZ Pvt Ltd")
    del_row = next(r for r in panel.rows if r.line.text == "5,000.00")
    del_row.delete.click()
    pump(app, 0.1)
    assert panel.pending_count() == 2 and panel.apply_btn.isEnabled()
    panel.apply_btn.click()
    pump(app, 0.6)
    assert not errors, errors
    t = text()
    assert "NEFT credit XYZ Pvt Ltd" in t and "ABC" not in t and "5,000.00" not in t, t
    assert "17,500.00" in t and "2,000.00" in t and "Opening balance" in t, t
    assert "ABC Ltd" in text(1), "page 2 must not change"
    assert doc.run_read(lambda dd: len(dd[0].get_drawings())) == 1
    assert [r.line.text for r in panel.rows][1] == "NEFT credit XYZ Pvt Ltd", [r.line.text for r in panel.rows]
    assert tab.doc.modified
    view.viewport().grab().save(str(shots / "text_panel_page.png"))
    win.grab().save(str(shots / "text_panel.png"))

    # 4. undo brings the old text back and the panel follows
    win.actions["undo"].trigger()
    pump(app, 0.5)
    assert "ABC Ltd" in text() and "5,000.00" in text()
    assert "NEFT credit ABC Ltd" in [r.line.text for r in panel.rows]

    # 5. moving to page 2 with typed (not applied) changes shows the banner instead of losing them
    panel.rows[0].edit.setText("changed but not applied")
    view.goto_page(1)
    pump(app, 0.4)
    assert panel.page == 0 and panel.banner.isVisible()
    panel.banner.click()
    pump(app, 0.3)
    assert panel.page == 1 and panel.pending_count() == 0

    # 6. close the panel -> back to the select tool
    win.actions["text_panel"].trigger()
    pump(app, 0.3)
    assert not win.text_dock.isVisible() and view.tool != "edit_text"

    win.close()
    pump(app, 0.2)
    print("Edit Text panel UI test: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
