"""Diagnostic logging to a rotating file in the user's data folder.

Logs never contain document text; they record file paths, operations and
error tracebacks only. Nothing is sent anywhere.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys

from app import config

_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    root = logging.getLogger()
    if _configured:
        return logging.getLogger("pdfworkbench")
    config.ensure_dirs()
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_DIR / "pdfworkbench.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if sys.stderr is not None:          # stderr is None in a windowed .exe
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(fmt)
        root.addHandler(console)

    root.setLevel(level)
    _configured = True
    log = logging.getLogger("pdfworkbench")
    log.info("---- %s %s starting ----", config.APP_NAME, config.APP_VERSION)
    return log
