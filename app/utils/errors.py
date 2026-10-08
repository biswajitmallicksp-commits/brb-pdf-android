"""Error types and helpers that turn exceptions into clear user messages.

Rule for the whole application: an unusual PDF must never crash the app.
Every PDF operation either succeeds or raises one of the errors below,
which the UI shows in a message box while the rest of the app keeps working.
"""
from __future__ import annotations

import logging
import traceback

log = logging.getLogger("pdfworkbench.errors")


class WorkbenchError(Exception):
    """Base class for expected, user-facing errors."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


class PdfOpenError(WorkbenchError):
    """The file could not be opened as a PDF."""


class PasswordRequired(WorkbenchError):
    """The PDF is encrypted and needs a password."""


class WrongPassword(WorkbenchError):
    """The supplied password was not accepted."""


class PdfSaveError(WorkbenchError):
    """Saving failed. The original file is untouched."""


class RenderError(WorkbenchError):
    """A page could not be drawn."""


def describe(exc: BaseException) -> tuple[str, str]:
    """Return (short message, technical detail) for any exception."""
    if isinstance(exc, WorkbenchError):
        return exc.message, exc.detail or ""
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return f"Unexpected error: {exc}", detail


def log_exception(context: str, exc: BaseException) -> None:
    if isinstance(exc, WorkbenchError):          # expected problem: short log line
        log.warning("%s: %s %s", context, exc.message.replace("\n", " "), exc.detail.replace("\n", " "))
    else:
        log.error("%s failed: %s", context, exc, exc_info=(type(exc), exc, exc.__traceback__))
