"""Headless test of the OCR workflow in the real window (no screen needed).

Run:  .venv\\Scripts\\python tests\\test_ocr_ui.py
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


def main() -> int:
    import pymupdf as fitz
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from app.database.db import AppDatabase
    from app.ui import main_window as mw
    from app.ui.ocr_ui import OcrDialog, OcrTextDialog
    from tests.test_ocr import SCAN

    shots = ROOT / "tests" / "samples" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory()
    folder = Path(tmp.name)

    # 3 scanned pages + 1 text page
    src = folder / "statement_scan.pdf"
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page(width=400, height=240)
        page.insert_image(page.rect, filename=str(SCAN))
    doc.new_page(width=400, height=240).insert_text((40, 60), "Real text page", fontsize=12)
    doc.save(src)
    doc.close()

    app = QApplication.instance() or QApplication(sys.argv)
    db = AppDatabase(folder / "ui.sqlite3")
    win = mw.MainWindow(db)
    win.resize(1300, 850)
    win.show()

    tab = win.open_file(str(src))
    pump(app, 10, until=lambda: tab.scanned_pages is not None)
    assert tab.scanned_pages == [0, 1, 2], tab.scanned_pages
    assert tab.banner.isVisible()
    pump(app, 1.0)
    win.grab().save(str(shots / "ocr_1_banner.png"))

    # the dialog: screenshot it, then accept with defaults (all pages, eng+ben+hin)
    dlg = OcrDialog(tab.doc, 0, tab.scanned_pages, db, win)
    dlg.resize(600, 560)
    dlg.show()
    pump(app, 0.5)
    dlg.grab().save(str(shots / "ocr_2_dialog.png"))
    assert set(dlg.languages) == {"eng", "ben", "hin"}
    dlg.close()

    QMessageBox.exec = lambda self: 0                   # auto-close result boxes
    OcrDialog.exec = lambda self: QDialog.DialogCode.Accepted
    win.run_ocr()
    job = win._ocr_job
    assert job is not None
    pump(app, 300, until=lambda: win._ocr_job is None)
    assert win._ocr_job is None, "OCR did not finish"
    out = folder / "statement_scan_OCR.pdf"
    assert out.exists(), "no output"
    new_tab = win.current_tab()
    assert new_tab.doc.path == out, new_tab.doc.path
    pump(app, 10, until=lambda: new_tab.scanned_pages is not None)
    assert new_tab.scanned_pages == [], new_tab.scanned_pages
    assert not new_tab.banner.isVisible()

    # search in the OCR result, in Bengali
    new_tab.show_search("সোনার বাংলা")
    pump(app, 10, until=lambda: new_tab.search._worker is None and new_tab.search.hits)
    assert len(new_tab.search.hits) == 3, len(new_tab.search.hits)
    pump(app, 1.0)
    win.grab().save(str(shots / "ocr_3_result_search.png"))

    # selection / copy of OCR text
    text = new_tab.view.select_all_on_page()
    assert "EMI HOME LOAN" in text and "আমার সোনার বাংলা" in text, text

    # recognise current page -> text dialog
    shown = {}

    def fake_exec(self):
        shown["text"] = self.edit.toPlainText()
        self.resize(760, 420)
        self.show()
        pump(app, 0.3)
        self.grab().save(str(shots / "ocr_4_page_text.png"))
        return 0

    OcrTextDialog.exec = fake_exec
    win.tabs.setCurrentWidget(tab)
    win.ocr_current_page()
    pump(app, 120, until=lambda: "text" in shown)
    assert "भारतीय स्टेट" in shown.get("text", ""), shown

    print(f"OK: OCR UI flow works. Output {out.stat().st_size // 1024} KB; screenshots in {shots}")
    win.close()
    db.close()
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
