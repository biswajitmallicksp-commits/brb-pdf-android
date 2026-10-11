"""Headless test of the AI Assistant panel in the real window (stand-in model server).

Run:  .venv\\Scripts\\python tests\\test_ai_ui.py
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


def main() -> int:  # noqa: C901
    import pymupdf as fitz
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

    from app.ai import engine as E
    from app.database.db import AppDatabase
    from app.ui import ai_panel as AP
    from app.ui import main_window as mw
    from tests.test_ai import FAKE, book, flat_form, source_doc

    shots = ROOT / "tests" / "samples" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    folder = Path(tmp.name)
    bpath, spath, fpath = folder / "loan_book.pdf", folder / "profile.pdf", folder / "form.pdf"
    book().save(bpath)
    source_doc().save(spath)
    flat_form().save(fpath)

    app = QApplication.instance() or QApplication(sys.argv)
    errors = []
    QMessageBox.warning = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a) or 0)
    QMessageBox.information = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a) or 0)
    db = AppDatabase(folder / "ui.sqlite3")

    # ---------- 1. quick mode (no model installed)
    E.set_model(None)
    win = mw.MainWindow(db)
    win.resize(1400, 900)
    win.show()
    tab = win.open_file(str(bpath))
    pump(app, 0.5)
    win.actions["ai_panel"].trigger()
    pump(app, 0.3)
    panel = win.ai_panel
    assert win.ai_dock.isVisible()
    assert "Quick mode" in panel.engine_label.text()
    scopes = [panel.scope.itemText(i) for i in range(panel.scope.count())]
    assert any("Chapter 2 Interest" in s for s in scopes), scopes
    panel.scope.setCurrentIndex(next(i for i, s in enumerate(scopes) if "Chapter 2" in s))
    panel.sum_btn.click()
    pump(app, 10, until=lambda: panel.job is None)
    text = panel.output.toPlainText()
    assert "quick mode" in text and "interest rate" in text.lower(), text
    assert "p. 3" in text or "p. 4" in text, text

    # ---------- 2. with the (stand-in) local model
    model = E.LocalModel(Path(sys.executable), Path(sys.executable), launcher=[sys.executable, str(FAKE)])
    E.set_model(model)
    panel.refresh_engine()
    assert "Local AI" in panel.engine_label.text()
    panel.prompt.setPlainText("What is the interest rate?")
    panel.send_btn.click()
    pump(app, 20, until=lambda: panel.job is None)
    text = panel.output.toPlainText()
    assert "ANSWER to 'What is the interest rate?'" in text, text
    # page numbers in the answer are links that open the page
    html = panel.output.toHtml()
    assert 'href="page:' in html, html[:500]
    import re
    n = int(re.search(r'href="page:(\d+)"', html).group(1))
    panel._link(QUrl(f"page:{n}"))
    pump(app, 0.3)
    assert tab.view.current_page == n - 1

    panel.prompt.setPlainText("Summarise chapter 3 in short")
    panel.send_btn.click()
    pump(app, 20, until=lambda: panel.job is None)
    assert "SUMMARY" in panel.output.toPlainText()

    # Stop button during a slow answer
    slow = E.LocalModel(Path(sys.executable), Path(sys.executable), launcher=[sys.executable, str(FAKE), "--slow"])
    E.set_model(slow)
    panel.prompt.setPlainText("What are the charges?")
    panel.send_btn.click()
    pump(app, 8, until=lambda: len(panel._answer_buf) > 10)
    panel.stop_btn.click()
    pump(app, 10, until=lambda: panel.job is None)
    assert "Stopped" in panel.output.toPlainText(), panel.output.toPlainText()[-200:]
    E.set_model(model)
    win.grab().save(str(shots / "ai_panel.png"))

    # ---------- 3. fill a form from the open profile
    tab2 = win.open_file(str(spath))
    pump(app, 0.5)
    out = folder / "form_filled.pdf"
    seen = {}

    def review_exec(dlg):
        seen["rows"] = {dlg.table.item(r, 0).text(): dlg.table.item(r, 1).text() for r in range(dlg.table.rowCount())}
        # the user corrects one value before saving
        r = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())].index("Nominee Name")
        dlg.table.item(r, 1).setText("SITA SHARMA")
        return QDialog.DialogCode.Accepted
    AP.FormReviewDialog.exec = review_exec
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out), "PDF (*.pdf)"))
    panel.fill_form(tab2, str(fpath))
    pump(app, 20, until=lambda: panel.job is None)
    pump(app, 1.0, until=lambda: out.exists())
    assert not errors, errors
    rows = seen["rows"]
    assert rows["Full Name"] == "RAMESH KUMAR SHARMA" and rows["PAN No"] == "ABCPS1234K", rows
    assert rows["Nominee Name"] == "", rows                      # nobody else's name is copied in
    assert out.exists()
    t = fitz.open(out)[0].get_text()
    assert "RAMESH KUMAR SHARMA" in t and "SITA SHARMA" in t and "SBIN0001234" in t, t
    assert fitz.open(fpath)[0].get_text().count("RAMESH") == 0     # original form unchanged
    assert win.current_tab().doc.path.name == "form_filled.pdf"     # the filled form opens

    win.close()
    pump(app, 0.3)
    assert not model.running(), "the local AI program must stop when the window closes"
    print("AI Assistant UI test: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
