"""Page operations (no Qt in this file).

Two kinds of functions:

* EDITS change a PyMuPDF document in memory (rotate, delete, duplicate, move,
  insert, replace). The UI runs them through ``PdfDocument.apply_edit`` which
  keeps an undo snapshot, so nothing is written to disk until the user saves.
* OUTPUTS write new files (extract, split, merge) and never touch the source.

All page numbers are 0-based here.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import pymupdf as fitz

log = logging.getLogger("pdfworkbench.pages")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".jxr", ".jpx"}

PAPER_SIZES = {                      # points (1/72 inch), portrait
    "A4": (595.0, 842.0),
    "A3": (842.0, 1191.0),
    "A5": (420.0, 595.0),
    "Letter": (612.0, 792.0),
    "Legal": (612.0, 1008.0),
}


class PageOpError(Exception):
    """A page operation could not be done; the message is shown to the user."""


# ================================================================= opening
def open_source(path: str | os.PathLike, password: str | None = None) -> fitz.Document:
    """Open a PDF or an image file as a PDF document (images become one page each)."""
    path = Path(path)
    if not path.is_file():
        raise PageOpError(f"File not found:\n{path}")
    try:
        if path.suffix.lower() in IMAGE_SUFFIXES:
            img = fitz.open(str(path))
            data = img.convert_to_pdf()
            img.close()
            return fitz.open("pdf", data)
        doc = fitz.open(str(path))
    except Exception as exc:
        raise PageOpError(f"Could not open {path.name}:\n{exc}") from exc
    if doc.needs_pass:
        if password is None or not doc.authenticate(password):
            doc.close()
            raise PageOpError(f"{path.name} is password protected." if password is None
                              else f"The password for {path.name} is not correct.")
    if not doc.is_pdf:
        data = doc.convert_to_pdf()
        doc.close()
        doc = fitz.open("pdf", data)
    return doc


def needs_password(path: str | os.PathLike) -> bool:
    try:
        if Path(path).suffix.lower() in IMAGE_SUFFIXES:
            return False
        with fitz.open(str(path)) as d:
            return bool(d.needs_pass)
    except Exception:
        return False


def _check_pages(doc: fitz.Document, pages: Iterable[int]) -> list[int]:
    pages = sorted(set(int(p) for p in pages))
    if not pages:
        raise PageOpError("No pages selected.")
    if pages[0] < 0 or pages[-1] >= doc.page_count:
        raise PageOpError("A selected page does not exist.")
    return pages


# =================================================================== edits
def rotate_pages(doc: fitz.Document, pages: Iterable[int], degrees: int) -> None:
    """Turn pages by +90 / -90 / 180 (permanent, saved in the file)."""
    if degrees % 90:
        raise PageOpError("Pages can only be rotated in steps of 90 degrees.")
    for i in _check_pages(doc, pages):
        page = doc[i]
        page.set_rotation((page.rotation + degrees) % 360)


def delete_pages(doc: fitz.Document, pages: Iterable[int]) -> None:
    pages = _check_pages(doc, pages)
    if len(pages) >= doc.page_count:
        raise PageOpError("A PDF must keep at least one page. To remove everything, close the file instead.")
    doc.delete_pages(pages)


def duplicate_pages(doc: fitz.Document, pages: Iterable[int]) -> list[int]:
    """Insert a copy right after each page. Returns the new pages' positions."""
    pages = _check_pages(doc, pages)
    for i in reversed(pages):
        doc.fullcopy_page(i, i + 1 if i + 1 < doc.page_count else -1)
    return [p + k + 1 for k, p in enumerate(pages)]


def move_order(page_count: int, pages: Sequence[int], before: int) -> list[int]:
    """New page order after moving `pages` (kept in their order) so they come just
    before original page `before` (page_count = to the end)."""
    sel = sorted(set(pages))
    rest = [p for p in range(page_count) if p not in sel]
    insert_at = sum(1 for p in rest if p < before)
    return rest[:insert_at] + sel + rest[insert_at:]


def move_pages(doc: fitz.Document, pages: Sequence[int], before: int) -> list[int]:
    """Move pages to just before page `before`. Returns the moved pages' new positions."""
    pages = _check_pages(doc, pages)
    if not 0 <= before <= doc.page_count:
        raise PageOpError("Invalid target position.")
    order = move_order(doc.page_count, pages, before)
    if order == list(range(doc.page_count)):
        return pages
    doc.select(order)
    return [order.index(p) for p in pages]


def reorder_pages(doc: fitz.Document, order: Sequence[int]) -> None:
    order = list(order)
    if sorted(order) != list(range(doc.page_count)):
        raise PageOpError("The new order must contain every page exactly once.")
    if order != list(range(doc.page_count)):
        doc.select(order)


def reverse_pages(doc: fitz.Document, pages: Iterable[int] | None = None) -> None:
    pages = list(range(doc.page_count)) if pages is None else _check_pages(doc, pages)
    order = list(range(doc.page_count))
    for src, dst in zip(pages, reversed(pages)):
        order[src] = dst
    reorder_pages(doc, order)


def insert_blank_pages(doc: fitz.Document, at: int, count: int = 1,
                       size: tuple[float, float] | None = None) -> list[int]:
    """Insert `count` blank pages before position `at` (page_count = at the end).
    `size` defaults to the size of the neighbouring page."""
    if not 0 <= at <= doc.page_count:
        raise PageOpError("Invalid position.")
    if size is None:
        ref = doc[min(at, doc.page_count - 1)] if doc.page_count else None
        size = (ref.rect.width, ref.rect.height) if ref is not None else PAPER_SIZES["A4"]
    for k in range(count):
        doc.new_page(pno=at + k if at + k < doc.page_count else -1, width=size[0], height=size[1])
    return list(range(at, at + count))


def insert_document(doc: fitz.Document, src: fitz.Document, at: int,
                    src_pages: Sequence[int] | None = None) -> list[int]:
    """Insert pages of another document before position `at`. Returns new positions."""
    if not 0 <= at <= doc.page_count:
        raise PageOpError("Invalid position.")
    pages = list(range(src.page_count)) if src_pages is None else _check_order(src, src_pages)
    pos = at
    for run in _runs(pages):
        doc.insert_pdf(src, from_page=run[0], to_page=run[-1], start_at=pos if pos < doc.page_count else -1)
        pos += len(run)
    return list(range(at, at + len(pages)))


def replace_pages(doc: fitz.Document, pages: Sequence[int], src: fitz.Document,
                  src_pages: Sequence[int] | None = None) -> list[int]:
    """Replace `pages` by pages of `src` (inserted where the first replaced page was)."""
    pages = _check_pages(doc, pages)
    new = list(range(src.page_count)) if src_pages is None else _check_order(src, src_pages)
    at = pages[0]
    # insert first, then delete the old pages (shifted), so the doc never becomes empty
    insert_document(doc, src, at, new)
    doc.delete_pages([p + len(new) if p >= at else p for p in pages])
    return list(range(at, at + len(new)))


def _check_order(doc: fitz.Document, pages: Sequence[int]) -> list[int]:
    """Validate page numbers but keep the order (and repeats) the user chose."""
    pages = [int(p) for p in pages]
    if not pages:
        raise PageOpError("No pages selected.")
    if min(pages) < 0 or max(pages) >= doc.page_count:
        raise PageOpError("A selected page does not exist.")
    return pages


def _runs(pages: Sequence[int]) -> list[list[int]]:
    """[1,2,3,7,8,4] -> [[1,2,3],[7,8],[4]] (keeps order, groups consecutive pages)."""
    runs: list[list[int]] = []
    for p in pages:
        if runs and p == runs[-1][-1] + 1:
            runs[-1].append(p)
        else:
            runs.append([p])
    return runs


# ================================================================= outputs
def extract_document(doc: fitz.Document, pages: Sequence[int]) -> fitz.Document:
    """A new in-memory document with copies of `pages` (in the given order)."""
    pages = _check_order(doc, pages)
    new = fitz.open()
    for run in _runs(pages):
        new.insert_pdf(doc, from_page=run[0], to_page=run[-1])
    try:
        meta = dict(doc.metadata or {})
        new.set_metadata({k: meta.get(k, "") for k in ("title", "author", "subject", "keywords")})
    except Exception:
        pass
    return new


def save_new(doc: fitz.Document, path: str | os.PathLike, password: str | None = None) -> Path:
    """Save to a temporary file first, then move into place (never leaves a half-written file).
    With `password`, the file is protected (AES-256) with that password."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=str(path.parent))
    os.close(fd)
    try:
        if password:
            doc.save(tmp, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_AES_256,
                     user_pw=password, owner_pw=password)
        else:
            doc.save(tmp, garbage=3, deflate=True)
        os.replace(tmp, path)
    except Exception as exc:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise PageOpError(f"Could not save {path.name}:\n{exc}") from exc
    return path


def extract_to_file(doc: fitz.Document, pages: Sequence[int], output: str | os.PathLike,
                    password: str | None = None) -> Path:
    new = extract_document(doc, pages)
    try:
        return save_new(new, output, password)
    finally:
        new.close()


@dataclass
class SplitPart:
    label: str
    pages: list[int]


def split_plan(doc: fitz.Document, mode: str, value: str | int = "") -> list[SplitPart]:
    """Decide how to split.

    mode 'every'     : every N pages (value = N)
    mode 'ranges'    : one file per range, e.g. '1-3, 4-10, 11-' (value = text)
    mode 'single'    : one file per page
    mode 'bookmarks' : one file per top-level bookmark
    """
    from app.utils.pages import parse_range_groups

    n = doc.page_count
    if mode == "every":
        size = int(value)
        if size < 1:
            raise PageOpError("Number of pages per file must be at least 1.")
        return [SplitPart(f"p{a + 1}-{min(a + size, n)}", list(range(a, min(a + size, n))))
                for a in range(0, n, size)]
    if mode == "single":
        return [SplitPart(f"p{i + 1}", [i]) for i in range(n)]
    if mode == "ranges":
        try:
            groups = parse_range_groups(str(value), n)
        except ValueError as exc:
            raise PageOpError(str(exc)) from exc
        return [SplitPart(f"p{g[0] + 1}-{g[-1] + 1}" if len(g) > 1 else f"p{g[0] + 1}", g) for g in groups]
    if mode == "bookmarks":
        toc = [(title, page - 1) for level, title, page, *_ in doc.get_toc(simple=False) if level == 1 and page > 0]
        if not toc:
            raise PageOpError("This document has no bookmarks to split by.")
        toc.sort(key=lambda t: t[1])
        parts = []
        if toc[0][1] > 0:
            parts.append(SplitPart("start", list(range(0, toc[0][1]))))
        for k, (title, start) in enumerate(toc):
            end = toc[k + 1][1] if k + 1 < len(toc) else n
            if end > start:
                parts.append(SplitPart(title, list(range(start, end))))
        return parts
    raise PageOpError(f"Unknown split mode: {mode}")


def safe_filename(text: str, limit: int = 60) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .")
    return (text or "part")[:limit]


def split_to_files(doc: fitz.Document, parts: list[SplitPart], folder: str | os.PathLike, stem: str,
                   password: str | None = None,
                   progress: Callable[[int, int], bool] | None = None) -> list[Path]:
    """Write each part to `folder` as '<stem>_01_<label>.pdf'. Existing files are not overwritten
    (a number is added)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(len(parts))))
    written = []
    for k, part in enumerate(parts, start=1):
        if progress is not None and progress(k - 1, len(parts)) is False:
            break
        name = f"{safe_filename(stem)}_{k:0{width}d}_{safe_filename(part.label)}.pdf"
        written.append(extract_to_file(doc, part.pages, unique_path(folder / name), password))
    return written


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 10000):
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
    raise PageOpError(f"Too many files named {path.name}")


@dataclass
class MergeSource:
    path: str
    password: str | None = None
    pages: list[int] | None = None       # None = all pages


def merge_files(sources: Sequence[MergeSource], output: str | os.PathLike, add_bookmarks: bool = True,
                progress: Callable[[int, int], bool] | None = None) -> Path:
    """Combine PDFs and images into one new PDF. Optionally one bookmark per source file,
    with that file's own bookmarks nested beneath it."""
    if not sources:
        raise PageOpError("Add at least one file to combine.")
    out = fitz.open()
    toc: list[list] = []
    try:
        for k, srcinfo in enumerate(sources):
            if progress is not None and progress(k, len(sources)) is False:
                raise PageOpError("Cancelled.")
            src = open_source(srcinfo.path, srcinfo.password)
            try:
                start = out.page_count
                pages = list(range(src.page_count)) if srcinfo.pages is None else srcinfo.pages
                insert_document(out, src, out.page_count, pages)
                if add_bookmarks:
                    toc.append([1, Path(srcinfo.path).stem, start + 1])
                    if srcinfo.pages is None:
                        for level, title, page, *_ in src.get_toc(simple=True):
                            if page > 0:
                                toc.append([level + 1, title, start + page])
            finally:
                src.close()
        if add_bookmarks and toc:
            try:
                out.set_toc(_fix_toc_levels(toc))
            except Exception as exc:          # bookmarks are a nice-to-have
                log.warning("Bookmarks for merged file skipped: %s", exc)
        return save_new(out, output)
    finally:
        out.close()


def _fix_toc_levels(toc: list[list]) -> list[list]:
    """PyMuPDF requires each level to be at most one deeper than the previous."""
    fixed, prev = [], 0
    for level, title, page in toc:
        level = max(1, min(level, prev + 1))
        fixed.append([level, title, page])
        prev = level
    return fixed
