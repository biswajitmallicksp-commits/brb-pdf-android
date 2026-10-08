"""Headless UI smoke test: opens the main window without showing it on screen.

Run:  .venv\\Scripts\\python tests\\test_ui_smoke.py
(set QT_QPA_PLATFORM=offscreen to run on a machine without a display)
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


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from app.database.db import AppDatabase
    from app.ui.main_window import MainWindow
    from tests.make_sample_pdf import OUT, make_large, make_scanned

    OUT.mkdir(parents=True, exist_ok=True)
    big = OUT / "sample_600_pages.pdf"
    if not big.exists():
        make_large(big, 600)
    scanned = OUT / "sample_scanned.pdf"
    if not scanned.exists():
        make_scanned(scanned)
    shots = OUT / "screenshots"
    shots.mkdir(exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.TemporaryDirectory()
    db = AppDatabase(Path(tmp.name) / "ui.sqlite3")
    win = MainWindow(db)
    win.resize(1400, 900)
    win.show()
    pump(app, 0.3)
    win.grab().save(str(shots / "0_empty.png"))

    t0 = time.time()
    tab = win.open_file(str(big))
    assert tab is not None, "open failed"
    open_s = time.time() - t0
    pump(app, 1.5)
    win.grab().save(str(shots / "1_opened.png"))
    assert tab.doc.page_count == 600

    # navigation
    tab.view.goto_page(299)
    pump(app, 0.8)
    assert tab.view.current_page == 299, tab.view.current_page
    assert win.page_spin.value() == 300

    # search
    tab.show_search("EMI HOME LOAN")
    for _ in range(300):
        pump(app, 0.05)
        if tab.search._worker is None:
            break
    n_hits = len(tab.search.hits)
    assert n_hits > 0, "no search hits"
    pump(app, 0.8)
    win.grab().save(str(shots / "2_search.png"))

    # zoom, two-page, rotate, dark
    tab.view.set_zoom(2.0)
    pump(app, 0.5)
    assert abs(tab.view.zoom - 2.0) < 1e-6
    win.actions["mode_two"].trigger()
    tab.view.fit_page()
    pump(app, 1.0)
    win.grab().save(str(shots / "3_two_page.png"))
    win.actions["rotate_cw"].trigger()
    win.actions["dark"].setChecked(True)
    win.toggle_dark()
    win.actions["mode_cont"].trigger()
    tab.view.fit_width()
    pump(app, 1.0)
    win.grab().save(str(shots / "4_dark_rotated.png"))

    # text selection on current page
    win.actions["rotate_ccw"].trigger()
    pump(app, 0.3)
    text = tab.view.select_all_on_page()
    assert "Sample Bank Ltd" in text, text[:100]

    # a second document in another tab + a scanned page (no text)
    tab2 = win.open_file(str(scanned))
    assert tab2 is not None and win.tabs.count() == 2
    pump(app, 0.5)
    assert tab2.view.select_all_on_page() == ""

    # a broken file must not crash
    broken = Path(tmp.name) / "broken.pdf"
    broken.write_bytes(b"garbage")
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.exec = lambda self: 0          # auto-dismiss error boxes in this test
    assert win.open_file(str(broken)) is None

    rss = ""
    try:
        import resource
        rss = f", peak memory {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB"
    except Exception:
        pass
    print(f"OK: opened 600 pages in {open_s:.2f}s, {n_hits} search hits, "
          f"cache {tab.page_cache.used_bytes / 1e6:.0f} MB{rss}")
    win.close()
    db.close()
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
