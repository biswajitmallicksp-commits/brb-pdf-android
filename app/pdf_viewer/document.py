"""PdfDocument: the single entry point for reading a PDF.

This module contains NO user-interface code. It wraps PyMuPDF (MuPDF) and
adds:
  * a lock, because MuPDF documents must not be used by two threads at once
    (the renderer and the search run in background threads);
  * clear errors instead of crashes for broken or encrypted files;
  * coordinate helpers used by the viewer (page space <-> screen space).

Coordinate spaces
-----------------
* "page space"  : PDF points of the UNROTATED page (what PyMuPDF text
                  extraction and search return).
* "view space"  : pixels of the page as drawn at a given scale and view
                  rotation, origin at the page's top-left corner.
`view_matrix()` converts page space -> view space; its inverse goes back.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import pymupdf as fitz

from app.utils.errors import (
    PasswordRequired, PdfOpenError, PdfSaveError, RenderError, WrongPassword,
)

log = logging.getLogger("pdfworkbench.document")

# Text extraction flags: ligatures such as "ﬁ" are returned as normal letters ("fi"), so
# searching and copying "Verified" works whichever program produced the PDF.
SEARCH_FLAGS = fitz.TEXTFLAGS_SEARCH & ~fitz.TEXT_PRESERVE_LIGATURES
WORD_FLAGS = fitz.TEXTFLAGS_WORDS & ~fitz.TEXT_PRESERVE_LIGATURES
TEXT_FLAGS = fitz.TEXTFLAGS_TEXT & ~fitz.TEXT_PRESERVE_LIGATURES

# Quieter MuPDF: its warnings go to our log instead of the console.
try:
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:  # pragma: no cover - older PyMuPDF
    pass


@dataclass
class RenderedPage:
    width: int
    height: int
    stride: int
    samples: bytes          # packed RGB, 3 bytes per pixel


@dataclass
class SearchHit:
    page: int
    rect: fitz.Rect         # page space
    snippet: str = ""


@dataclass
class TextSelection:
    page: int
    rects: list = field(default_factory=list)   # word rects, page space
    text: str = ""


class PdfDocument:
    """A PDF opened for viewing. Thread-safe for concurrent read access."""

    def __init__(self, path: str | os.PathLike, password: str | None = None):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._doc: fitz.Document | None = None
        self.password: str | None = None
        self._page_sizes: list[tuple[float, float]] = []
        self.modified = False
        # Bumped whenever pages change, so cached images of old pages are never shown.
        self.revision = 0
        # Undo/redo: (label, PDF bytes before the change). Snapshots are kept in memory.
        self._undo: list[tuple[str, bytes]] = []
        self._redo: list[tuple[str, bytes]] = []
        self._clean_depth = 0          # undo depth that matches the file on disk (-1 = none)
        self._permissions = -1
        self._open(password)

    # ------------------------------------------------------------------ open
    def _open(self, password: str | None) -> None:
        if not self.path.exists():
            raise PdfOpenError(f"File not found:\n{self.path}")
        try:
            doc = fitz.open(str(self.path))
        except Exception as exc:
            raise PdfOpenError(
                f"This file could not be opened as a PDF:\n{self.path.name}",
                f"{type(exc).__name__}: {exc}\n\nThe file may be damaged or not a PDF. "
                "A repair tool will be available in a later phase.",
            ) from exc
        if not doc.is_pdf:
            doc.close()
            raise PdfOpenError(f"{self.path.name} is not a PDF document.")
        if doc.needs_pass:
            if password is None:
                doc.close()
                raise PasswordRequired(f"{self.path.name} is password protected.")
            if not doc.authenticate(password):
                doc.close()
                raise WrongPassword("The password is not correct.")
            self.password = password
        try:
            self._permissions = doc.permissions
        except Exception:
            self._permissions = -1
        self._doc = doc
        self._page_sizes = self._read_page_sizes()
        log.info("Opened %s (%d pages)", self.path, len(self._page_sizes))

    def _read_page_sizes(self) -> list[tuple[float, float]]:
        sizes: list[tuple[float, float]] = []
        with self._lock:
            for i in range(self._doc.page_count):
                try:
                    r = self._doc[i].rect           # includes the page's own /Rotate
                    sizes.append((max(r.width, 1.0), max(r.height, 1.0)))
                except Exception as exc:            # damaged page: keep A4 placeholder
                    log.warning("Page %d size unreadable: %s", i + 1, exc)
                    sizes.append((595.0, 842.0))
        return sizes

    def close(self) -> None:
        with self._lock:
            if self._doc is not None:
                try:
                    self._doc.close()
                finally:
                    self._doc = None

    @property
    def is_open(self) -> bool:
        return self._doc is not None

    # ----------------------------------------------------------- editing
    MAX_UNDO_STEPS = 30
    MAX_UNDO_BYTES = 600 * 1024 * 1024

    def apply_edit(self, label: str, func):
        """Run `func(fitz_document)` as one undoable change and return its result.

        A snapshot of the document is taken first; if `func` fails, the snapshot is
        restored so a failed operation never leaves a half-changed document.
        """
        with self._lock:
            before = self._doc.tobytes(garbage=0)
            try:
                result = func(self._doc)
            except Exception:
                self._restore(before)
                raise
            if len(self._undo) < self._clean_depth:
                self._clean_depth = -1          # the saved state can no longer be reached by undo
            self._undo.append((label, before))
            self._redo.clear()
            self._trim_undo()
            self._after_change()
            return result

    def undo(self) -> str | None:
        """Undo the last change. Returns its label, or None if there is nothing to undo."""
        with self._lock:
            if not self._undo:
                return None
            label, data = self._undo.pop()
            self._redo.append((label, self._doc.tobytes(garbage=0)))
            self._restore(data)
            self._after_change()
            return label

    def redo(self) -> str | None:
        with self._lock:
            if not self._redo:
                return None
            label, data = self._redo.pop()
            self._undo.append((label, self._doc.tobytes(garbage=0)))
            self._restore(data)
            self._after_change()
            return label

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1][0] if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1][0] if self._redo else None

    def _restore(self, data: bytes) -> None:
        old = self._doc
        self._doc = fitz.open("pdf", data)
        if old is not None:
            old.close()

    def _after_change(self) -> None:
        self._page_sizes = self._read_page_sizes()
        self.revision += 1
        self.modified = len(self._undo) != self._clean_depth

    def _trim_undo(self) -> None:
        total = sum(len(d) for _, d in self._undo)
        while self._undo and (len(self._undo) > self.MAX_UNDO_STEPS or total > self.MAX_UNDO_BYTES):
            _, d = self._undo.pop(0)
            total -= len(d)
            # the saved state's position in the undo list shifts down by one
            self._clean_depth = -1 if self._clean_depth <= 0 else self._clean_depth - 1

    def run_read(self, func):
        """Run `func(fitz_document)` under the document lock without changing it
        (used for exports such as Extract and Split)."""
        with self._lock:
            return func(self._doc)

    # ----------------------------------------------------------------- basics
    @property
    def page_count(self) -> int:
        return len(self._page_sizes)

    @property
    def title(self) -> str:
        return self.path.name

    def page_size(self, index: int) -> tuple[float, float]:
        """Width, height in points as the page is displayed (page /Rotate applied)."""
        return self._page_sizes[index]

    @property
    def is_encrypted(self) -> bool:
        with self._lock:
            return bool(self._doc.is_encrypted) or self.password is not None

    # -------------------------------------------------------------- rendering
    def render(self, index: int, scale: float, view_rotation: int = 0) -> RenderedPage:
        """Render one page to RGB pixels. `scale` = pixels per point."""
        try:
            with self._lock:
                page = self._doc[index]
                matrix = fitz.Matrix(scale, scale).prerotate(view_rotation)
                pix = page.get_pixmap(matrix=matrix, alpha=False, annots=True)
                return RenderedPage(pix.width, pix.height, pix.stride, bytes(pix.samples))
        except Exception as exc:
            raise RenderError(f"Page {index + 1} could not be rendered.", str(exc)) from exc

    def view_matrix(self, index: int, scale: float, view_rotation: int = 0) -> fitz.Matrix:
        """Matrix mapping page space (unrotated points) to view pixels."""
        with self._lock:
            page = self._doc[index]
            m = fitz.Matrix(scale, scale).prerotate(view_rotation)
            bbox = page.rect * m
            return page.rotation_matrix * m * fitz.Matrix(1, 0, 0, 1, -bbox.x0, -bbox.y0)

    # ------------------------------------------------------------------- text
    def page_text(self, index: int) -> str:
        with self._lock:
            return self._doc[index].get_text("text", sort=True, flags=TEXT_FLAGS)

    def words_in_rect(self, index: int, rect: fitz.Rect) -> TextSelection:
        """Words whose box intersects `rect` (page space), in reading order."""
        with self._lock:
            words = self._doc[index].get_text("words", sort=True, flags=WORD_FLAGS)
        chosen = [w for w in words if fitz.Rect(w[:4]).intersects(rect)]
        sel = TextSelection(page=index)
        lines: list[str] = []
        last_key = None
        for w in chosen:
            sel.rects.append(fitz.Rect(w[:4]))
            key = (w[5], w[6])                         # (block, line)
            if key != last_key:
                lines.append(w[4])
                last_key = key
            else:
                lines[-1] += " " + w[4]
        sel.text = "\n".join(lines)
        return sel

    def all_words(self, index: int) -> TextSelection:
        return self.words_in_rect(index, fitz.Rect(-1e5, -1e5, 1e5, 1e5))

    def search_page(self, index: int, needle: str) -> list[SearchHit]:
        """Case-insensitive search on one page.

        The page text is extracted once and reused for both matching and the
        result snippets (extracting per hit is ~100x slower).
        """
        with self._lock:
            page = self._doc[index]
            textpage = page.get_textpage(flags=SEARCH_FLAGS)
            rects = page.search_for(needle, textpage=textpage)
            if not rects:
                return []
            words = textpage.extractWORDS()
        hits = []
        for r in rects:
            mid = (r.y0 + r.y1) / 2
            line = sorted((w for w in words if w[1] <= mid <= w[3]), key=lambda w: w[0])
            snippet = " ".join(w[4] for w in line) or needle
            hits.append(SearchHit(index, fitz.Rect(r), snippet[:160]))
        return hits

    def search(self, needle: str, progress: Callable[[int], bool] | None = None) -> list[SearchHit]:
        """Search every page. `progress(page)` may return False to cancel."""
        hits: list[SearchHit] = []
        for i in range(self.page_count):
            if progress is not None and progress(i) is False:
                break
            try:
                hits.extend(self.search_page(i, needle))
            except Exception as exc:
                log.warning("Search skipped page %d: %s", i + 1, exc)
        return hits

    def classify_page(self, index: int):
        """Text / scanned / blank status of a page (see app.pdf_ocr.engine.PageInfo)."""
        from app.pdf_ocr.engine import classify_page
        with self._lock:
            return classify_page(self._doc[index])

    # ---------------------------------------------------------------- outline
    def outline(self) -> list[tuple[int, str, int]]:
        """[(level, title, page_index)] from the document's bookmarks."""
        try:
            with self._lock:
                toc = self._doc.get_toc(simple=True)
        except Exception as exc:
            log.warning("Bookmarks unreadable: %s", exc)
            return []
        return [(lvl, title, max(0, page - 1)) for lvl, title, page in toc]

    # --------------------------------------------------------------- metadata
    def properties(self) -> list[tuple[str, str]]:
        """Human-readable document properties, in display order."""
        with self._lock:
            meta = dict(self._doc.metadata or {})
            perms = self._permissions
            enc = meta.get("encryption") or ("Yes" if self.password else "None")
            try:
                is_tagged = "Yes" if self._doc.pdf_catalog() and b"/StructTreeRoot" in (
                    self._doc.xref_object(self._doc.pdf_catalog()).encode()) else "No"
            except Exception:
                is_tagged = "Unknown"
            has_forms = "Yes" if self._doc.is_form_pdf else "No"
            embedded = self._doc.embfile_count()
        size = self.path.stat().st_size if self.path.exists() else 0
        w, h = self._page_sizes[0] if self._page_sizes else (0, 0)
        same = all(abs(s[0] - w) < 1 and abs(s[1] - h) < 1 for s in self._page_sizes)

        def fmt_date(value: str) -> str:
            v = (value or "").strip()
            if v.startswith("D:") and len(v) >= 16:
                return f"{v[2:6]}-{v[6:8]}-{v[8:10]} {v[10:12]}:{v[12:14]}:{v[14:16]}"
            return v or "-"

        return [
            ("File name", self.path.name),
            ("Location", str(self.path.parent)),
            ("File size", _human_size(size) + f"  ({size:,} bytes)"),
            ("Pages", str(self.page_count)),
            ("PDF version", meta.get("format") or "-"),
            ("Page size (first page)", f"{w:.0f} x {h:.0f} pt  ({w / 72 * 25.4:.0f} x {h / 72 * 25.4:.0f} mm)"
                                        + ("" if same else "  - pages vary in size")),
            ("Title", meta.get("title") or "-"),
            ("Author", meta.get("author") or "-"),
            ("Subject", meta.get("subject") or "-"),
            ("Keywords", meta.get("keywords") or "-"),
            ("Creator", meta.get("creator") or "-"),
            ("Producer", meta.get("producer") or "-"),
            ("Created", fmt_date(meta.get("creationDate", ""))),
            ("Modified", fmt_date(meta.get("modDate", ""))),
            ("Encryption", enc),
            ("Permissions", _describe_permissions(perms)),
            ("Form fields", has_forms),
            ("Tagged PDF", is_tagged),
            ("Embedded files", str(embedded)),
        ]

    # ------------------------------------------------------------------ saving
    def save_as(self, target: str | os.PathLike, switch: bool = True) -> Path:
        """Write the document (with any page changes) to `target`.

        * The file is written to a temporary file first and only moved into place
          when the write succeeded, so a failure never destroys an existing file.
        * Password protection is kept.
        * With `switch` (default), the open document now refers to `target`
          (like "Save As" in any editor). Undo history is kept.
        """
        target = Path(target)
        same_file = target.exists() and target.resolve() == self.path.resolve()
        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".pdf", dir=str(target.parent))
        os.close(tmp_fd)
        with self._lock:      # background renderer/search wait until we are done
            current: bytes | None = None
            try:
                self._doc.save(tmp_name, **self._save_options())
                if same_file:
                    # MuPDF keeps the file open; release it before replacing (needed on Windows)
                    current = self._doc.tobytes(garbage=0)
                    self._doc.close()
                    self._doc = None
                    os.replace(tmp_name, target)
                    self._open(self.password)
                else:
                    os.replace(tmp_name, target)
            except Exception as exc:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
                if self._doc is None and current is not None:   # keep the user's work in memory
                    self._doc = fitz.open("pdf", current)
                    self._page_sizes = self._read_page_sizes()
                raise PdfSaveError(f"Could not save to\n{target}", str(exc)) from exc
            if switch or same_file:
                self.path = target
                self._clean_depth = len(self._undo)
                self.modified = False
        log.info("Saved %s", target)
        return target

    def _save_options(self) -> dict:
        if not self.password:
            return dict(garbage=3, deflate=True)
        # Protect the saved file again with the same password (AES-256) and the same
        # permissions. (MuPDF's "keep encryption" does not survive page changes.)
        perms = self._permissions if self._permissions not in (None, -1) else -1
        return dict(garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_AES_256,
                    user_pw=self.password, owner_pw=self.password, permissions=perms)

    def save_copy(self, target: str | os.PathLike) -> Path:
        """Save a copy without switching the open document to it."""
        return self.save_as(target, switch=False)


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} bytes"


def _describe_permissions(perms: int) -> str:
    if perms is None or perms == -1:
        return "All allowed"
    checks = [
        (fitz.PDF_PERM_PRINT, "print"),
        (fitz.PDF_PERM_COPY, "copy text"),
        (fitz.PDF_PERM_MODIFY, "modify"),
        (fitz.PDF_PERM_ANNOTATE, "annotate"),
        (fitz.PDF_PERM_FORM, "fill forms"),
    ]
    denied = [name for bit, name in checks if not perms & bit]
    return "All allowed" if not denied else "Restricted: no " + ", no ".join(denied)


def open_document(path: str | os.PathLike, password: str | None = None) -> PdfDocument:
    return PdfDocument(path, password)


def iter_pdf_paths(paths: Iterable[str]) -> list[str]:
    return [p for p in paths if str(p).lower().endswith(".pdf")]
