"""Headless test of the Analysis window.

Run:  .venv\\Scripts\\python tests\\test_analysis_ui.py
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
    from PySide6.QtWidgets import QApplication

    from app.database.db import AppDatabase
    from app.ui.main_window import MainWindow
    from tests.test_analysis import build

    shots = ROOT / "tests" / "samples" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "mixed.pdf"
    build(path)
    app = QApplication.instance() or QApplication(sys.argv)
    db = AppDatabase(Path(tmp.name) / "ui.sqlite3")
    win = MainWindow(db)
    win.resize(1300, 850)
    win.show()
    tab = win.open_file(str(path))
    win.actions["analyse"].trigger()
    aw = tab.analysis_window
    aw.resize(1000, 640)
    pump(app, 30, until=lambda: aw.report is not None)
    assert aw.report is not None, "analysis did not finish"
    assert aw.pages.rowCount() == 3
    pump(app, 0.5)
    aw.grab().save(str(shots / "analysis_1_summary.png"))
    aw.tabs.setCurrentWidget(aw.pages)
    pump(app, 0.3)
    aw.grab().save(str(shots / "analysis_2_pages.png"))
    assert aw.pages.item(0, 0).data(0) == 1           # page order
    aw._row_activated(1, 0)
    pump(app, 0.5)
    assert tab.view.current_page == 1, tab.view.current_page
    out = Path(tmp.name) / "a.csv"
    out.write_text(aw.report.to_csv(), encoding="utf-8-sig")

    # a 600-page document finishes without freezing the window
    big = ROOT / "tests" / "samples" / "sample_600_pages.pdf"
    if big.exists():
        t2 = win.open_file(str(big))
        win.actions["analyse"].trigger()
        aw2 = t2.analysis_window
        t0 = time.time()
        pump(app, 60, until=lambda: aw2.report is not None)
        assert aw2.report is not None and len(aw2.report.pages) == 600
        print(f"600 pages analysed in {time.time() - t0:.1f}s")
    print("OK: analysis window works")
    win.close()
    db.close()
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
