"""PDF Workbench - entry point.

Run from source:   run.bat          (or: python main.py [file.pdf | file.docx ...])
Word only:         PDFWorkbench.exe --word   (a new Word document, without the PDF window)
Built program:     dist\\PDFWorkbench\\PDFWorkbench.exe
"""
from __future__ import annotations

import logging
import sys
import traceback


def ocr_command(args: list[str]) -> int:
    """PDFWorkbench.exe --ocr input.pdf output.pdf [--lang eng+ben+hin] [--dpi 300] [--password PW]

    Runs OCR without opening a window. Exit code 0 = success. Details go to the log.
    """
    import argparse

    from app.pdf_ocr import engine
    from app.utils.logging_setup import setup_logging

    log = setup_logging()
    parser = argparse.ArgumentParser(prog="PDFWorkbench --ocr")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--lang", default="eng+ben+hin")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--password", default=None)
    ns = parser.parse_args(args)
    try:
        result = engine.make_searchable(ns.input, ns.password, ns.output, ns.lang.split("+"), ns.dpi)
    except Exception as exc:
        log.error("OCR command failed: %s", exc)
        return 2
    log.info("OCR command: %d pages done, %d skipped, %d failed", len(result.pages_done),
             len(result.pages_skipped), len(result.pages_failed))
    return 1 if result.pages_failed else 0


def selftest(folder: str) -> int:
    """Used by the build machine: check the packaged program can write Word and PDF files."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path

    import pymupdf as fitz
    from PySide6.QtWidgets import QApplication

    from app.pdf_editor import doc_export, doc_model

    QApplication.instance() or QApplication(sys.argv[:1])
    d = fitz.open()
    p = d.new_page()
    p.insert_text((50, 80), "Self test 01-04-2025   12,500.00", fontsize=11)
    qd = doc_export.build_document(doc_model.build_pages(d))
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    doc_export.save_docx(qd, out / "selftest.docx")
    doc_export.save_pdf(qd, out / "selftest.pdf")
    ok = "Self test" in fitz.open(out / "selftest.pdf")[0].get_text()
    # Word editor: open the .docx again, save it, export a PDF
    from app.word import docx_io, pdf_out
    wd = docx_io.load_docx(out / "selftest.docx")
    docx_io.save_docx(wd, out / "selftest2.docx")
    pdf_out.save_pdf(docx_io.load_docx(out / "selftest2.docx"), out / "selftest2.pdf")
    ok = ok and "Self test" in fitz.open(out / "selftest2.pdf")[0].get_text()
    (out / "selftest.txt").write_text("OK" if ok else "FAILED", encoding="utf-8")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--ocr":
        return ocr_command(sys.argv[2:])
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2])
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app import config
    from app.database.db import AppDatabase
    from app.utils.logging_setup import setup_logging

    log = setup_logging()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.APP_ID)
    app.setApplicationVersion(config.APP_VERSION)

    # Any unexpected error: log it and tell the user, but keep the app running.
    def handle_exception(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.error("Unhandled error", exc_info=(exc_type, exc, tb))
        try:
            box = QMessageBox(QMessageBox.Icon.Warning, config.APP_NAME,
                              f"Something went wrong: {exc}\n\nThe application is still running. "
                              "Details were written to the log (Help > Open Log Folder).")
            box.setDetailedText("".join(traceback.format_exception(exc_type, exc, tb)))
            box.exec()
        except Exception:
            pass

    sys.excepthook = handle_exception

    try:
        db = AppDatabase()
    except Exception as exc:  # corrupt settings database: start with a fresh one
        log.error("Settings database unusable (%s); starting with a new one", exc)
        broken = config.DB_PATH.with_suffix(".broken")
        try:
            config.DB_PATH.replace(broken)
        except OSError:
            pass
        db = AppDatabase()

    from app.ui.main_window import MainWindow

    window = MainWindow(db)
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    word_only = "--word" in sys.argv or (files and all(f.lower().endswith((".docx", ".doc")) for f in files))
    if word_only:
        # "BRB PDF Word" shortcut or a Word file double-clicked: just the Word window
        if files:
            QTimer.singleShot(0, lambda: window.open_files(files))
        else:
            QTimer.singleShot(0, window.new_word_document)
        QTimer.singleShot(1500, lambda: window.show() if not window._doc_windows else None)
    else:
        window.show()
        if files:
            QTimer.singleShot(0, lambda: window.open_files(files))
    code = app.exec()
    db.close()
    logging.getLogger("pdfworkbench").info("Exited with code %s", code)
    return code


if __name__ == "__main__":
    # OCR uses worker processes; in the built .exe each worker is a new copy of the
    # program, and this call turns it into a worker instead of opening a window.
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
