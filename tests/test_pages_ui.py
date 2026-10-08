"""Headless test of page management in the real window (no screen needed).

Run:  .venv\\Scripts\\python tests\\test_pages_ui.py
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
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

    from app.database.db import AppDatabase
    from app.ui import main_window as mw
    from app.ui import page_dialogs as pd
    from tests.test_pages import labels, make_pdf

    shots = ROOT / "tests" / "samples" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory()
    folder = Path(tmp.name)
    src = make_pdf(folder / "statement.pdf", 12, bookmarks=True)
    other = make_pdf(folder / "annexure.pdf", 3, prefix="X")

    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.exec = lambda self: 0                      # auto-close message boxes
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: 0)
    QMessageBox.warning = staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError(a[2] if len(a) > 2 else a)))
    mw.QDesktopServices.openUrl = staticmethod(lambda *a: True)
    db = AppDatabase(folder / "ui.sqlite3")
    win = mw.MainWindow(db)
    win.resize(1300, 850)
    win.show()

    tab = win.open_file(str(src))
    doc = tab.doc
    pump(app, 1.0)

    def state() -> list[str]:
        return doc.run_read(labels)

    # --- organiser view, select pages 2-3, rotate clockwise
    win.actions["organize"].trigger()
    assert tab.organizer_visible and win.actions["organize"].isChecked()
    tab.organizer.select_pages([1, 2])
    win.actions["pg_rotate_cw"].trigger()
    assert doc.run_read(lambda d: [d[i].rotation for i in range(4)]) == [0, 90, 90, 0]
    assert doc.modified and win.tabs.tabText(0).startswith("* ")
    assert tab.organizer.selected_pages() == [1, 2]

    # --- drag pages 2-3 to the end (what a drop does)
    tab.organizer.movePages.emit([1, 2], doc.page_count)
    assert state()[-2:] == ["P2", "P3"], state()
    assert tab.organizer.selected_pages() == [10, 11]

    # --- delete (Delete key in the organiser = no dialog)
    tab.organizer.select_pages([0])
    tab.organizer.deletePressed.emit()
    assert state()[0] == "P4" and doc.page_count == 11

    # --- undo x3, redo x1
    for _ in range(3):
        win.actions["undo"].trigger()
    assert state() == [f"P{i}" for i in range(1, 13)], state()
    assert not doc.modified and not win.tabs.tabText(0).startswith("*")
    win.actions["redo"].trigger()
    assert doc.modified

    # --- duplicate, insert blank, insert from file via dialogs
    tab.organizer.select_pages([0])
    win.actions["pg_duplicate"].trigger()
    assert state()[:2] == ["P1", "P1"]

    def insert_exec(self):
        if self.rb_file.isChecked():
            self.file_edit.setText(str(other))
            self.file_pages.setText("3, 1")
        self.position.where.setCurrentIndex(0)            # at the beginning
        return QDialog.DialogCode.Accepted
    pd.InsertDialog.exec = insert_exec
    win.insert_pages(True)
    assert state()[:3] == ["X3", "X1", "P1"], state()[:4]
    win.insert_pages(False)
    assert state()[0] == "-"
    pump(app, 1.0)
    win.grab().save(str(shots / "pages_1_organizer.png"))

    # --- files dropped from Explorer into the organiser
    tab.organizer.filesDropped.emit([str(other)], 2)
    assert state()[2:5] == ["X1", "X2", "X3"], state()

    # --- extract to a new file (and open it)
    out = folder / "extract.pdf"

    def extract_exec(self):
        self.pages_edit.setText("1-3")
        self.output.setText(str(out))
        self.open_after.setChecked(False)
        self._accept()
        return self.result()
    pd.ExtractDialog.exec = extract_exec
    win.extract_pages()
    with fitz.open(out) as d:
        assert labels(d) == state()[:3], labels(d)

    # --- split the (edited) document every 5 pages
    def split_exec(self):
        self.every.setValue(5)
        self.folder.setText(str(folder / "split"))
        return QDialog.DialogCode.Accepted
    pd.SplitDialog.exec = split_exec
    n_pages = doc.page_count
    win.split_document()
    parts = sorted((folder / "split").glob("*.pdf"))
    assert len(parts) == (n_pages + 4) // 5, parts

    # --- combine two files into one
    merged = folder / "combined.pdf"

    def merge_exec(self):
        self.list.clear()
        self._add(str(other))
        self._add(str(src))
        self.output.setText(str(merged))
        self.open_after.setChecked(False)
        return QDialog.DialogCode.Accepted
    mw.MergeDialog.exec = merge_exec
    win.merge_files()
    with fitz.open(merged) as d:
        assert d.page_count == 15 and labels(d)[:4] == ["X1", "X2", "X3", "P1"], labels(d)

    # --- viewer mode: rotate current page, then Save -> "save as new file"
    win.actions["organize"].trigger()
    assert not tab.organizer_visible
    tab.view.goto_page(4)
    pump(app, 0.3)
    win.actions["pg_rotate_ccw"].trigger()
    assert doc.run_read(lambda d: d[4].rotation) == 270
    pump(app, 1.0)
    win.grab().save(str(shots / "pages_2_viewer_rotated.png"))
    saved = folder / "statement - edited.pdf"
    mw.SaveChangesBox.ask = staticmethod(lambda *a, **k: "new")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(saved), ""))
    expected = state()
    win.save()
    assert not doc.modified and doc.path == saved, (doc.modified, doc.path)
    with fitz.open(saved) as d:
        assert labels(d) == expected
    with fitz.open(src) as d:                                # original untouched
        assert labels(d) == [f"P{i}" for i in range(1, 13)]

    # --- close with unsaved changes: Cancel keeps the tab open
    win.actions["pg_rotate_180"].trigger()
    mw.SaveChangesBox.ask = staticmethod(lambda *a, **k: "cancel")
    assert win.close_tab(0) is False and win.tabs.count() == 1
    mw.SaveChangesBox.ask = staticmethod(lambda *a, **k: "discard")
    assert win.close_tab(0) is True and win.tabs.count() == 0

    # --- dialog screenshots
    for name, dlg in (("pages_3_insert", pd.InsertDialog(10, 2, (595, 842), str(folder))),
                      ("pages_4_split", pd.SplitDialog(10, True, src)),
                      ("pages_5_merge", mw.MergeDialog(str(folder), [str(src), str(other)]))):
        dlg.show()
        pump(app, 0.3)
        dlg.grab().save(str(shots / f"{name}.png"))
        dlg.close()

    print("OK: page management works (rotate, move, delete, undo/redo, duplicate, insert, drop, "
          "extract, split, combine, save as, close prompt)")
    win.close()
    db.close()
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
