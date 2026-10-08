"""Offline OCR engine (no Qt in this file).

How it works
------------
* Recognition uses the Tesseract engine that is built into MuPDF/PyMuPDF.
  No separate Tesseract installation is needed: only the language model files
  (``*.traineddata``) in a local ``tessdata`` folder. Nothing goes online.
* Each page is rendered UPRIGHT (the page's /Rotate applied) at the chosen
  resolution, in colour (MuPDF's OCR returns nothing for greyscale images),
  and recognised. Words come back with their boxes.
* A searchable PDF is made by adding an INVISIBLE text layer on top of the
  original page: the page's appearance is not changed at all. The layer uses
  ``assets/ocr_glyphless.ttf``, a font whose glyphs are empty, so any
  Unicode text (English, Bengali, Hindi, ...) can be stored exactly. Every
  word is written separately, with a real space after it, so copy and search
  work correctly in this and every other PDF reader. (MuPDF's own OCR output
  drops spaces between Bengali/Devanagari words; this approach avoids that.)
* Recognition runs in separate processes (one per CPU core, max 6), because
  OCR is CPU-heavy and would otherwise freeze the window.
* The original file is never modified: the result is saved as a new file.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import multiprocessing
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import pymupdf as fitz

from app import config

log = logging.getLogger("pdfworkbench.ocr")

LANGUAGE_NAMES = {
    "eng": "English",
    "ben": "Bengali",
    "hin": "Hindi",
    "asm": "Assamese",
    "ori": "Odia",
    "tam": "Tamil",
    "tel": "Telugu",
    "kan": "Kannada",
    "mal": "Malayalam",
    "guj": "Gujarati",
    "pan": "Punjabi",
    "mar": "Marathi",
    "urd": "Urdu",
    "nep": "Nepali",
    "san": "Sanskrit",
}

QUALITY_DPI = {"fast": 200, "standard": 300, "high": 400}

# page classification thresholds
MIN_TEXT_CHARS = 30          # fewer characters than this = "no real text"
MIN_IMAGE_COVERAGE = 0.20    # images cover at least 20 % of the page


# ============================================================ language data
def tessdata_candidates() -> list[Path]:
    """Folders searched for *.traineddata, in order of preference."""
    return [
        config.app_dir() / "tessdata",          # next to PDFWorkbench.exe / project root
        config.resource_dir() / "tessdata",     # bundled inside the build
        config.DATA_DIR / "tessdata",           # user's own folder
    ]


def find_tessdata() -> Path | None:
    for folder in tessdata_candidates():
        if (folder / "eng.traineddata").is_file():
            return folder
    for folder in tessdata_candidates():
        if folder.is_dir() and any(folder.glob("*.traineddata")):
            return folder
    return None


def available_languages(tessdata: Path | None = None) -> list[str]:
    tessdata = tessdata or find_tessdata()
    if tessdata is None:
        return []
    codes = sorted(p.stem for p in tessdata.glob("*.traineddata") if p.stem not in ("osd", "equ"))
    order = {c: i for i, c in enumerate(LANGUAGE_NAMES)}       # English, Bengali, Hindi first
    return sorted(codes, key=lambda c: (order.get(c, 999), c))


def language_label(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def glyphless_font_path() -> Path:
    return config.asset_path("ocr_glyphless.ttf")


class OcrUnavailable(RuntimeError):
    pass


def check_ready(languages: Iterable[str]) -> Path:
    """Return the tessdata folder, or raise OcrUnavailable with a clear reason."""
    tessdata = find_tessdata()
    if tessdata is None:
        places = "\n".join(f"  {p}" for p in tessdata_candidates())
        raise OcrUnavailable("OCR language files were not found. Expected a 'tessdata' folder in one of:\n" + places)
    missing = [l for l in languages if not (tessdata / f"{l}.traineddata").is_file()]
    if missing:
        raise OcrUnavailable(f"Language file(s) missing: {', '.join(missing)} (looked in {tessdata}).")
    if not glyphless_font_path().is_file():
        raise OcrUnavailable(f"OCR font missing: {glyphless_font_path()}")
    return tessdata


# ====================================================== page classification
@dataclass
class PageInfo:
    index: int
    text_chars: int
    image_count: int
    image_coverage: float      # 0..1 of page area covered by images
    needs_ocr: bool
    blank: bool

    @property
    def status(self) -> str:
        if self.blank:
            return "Blank"
        if self.needs_ocr:
            return "Scanned - needs OCR"
        return "Has text"


def classify_page(page: fitz.Page) -> PageInfo:
    try:
        chars = len("".join(page.get_text("text").split()))
    except Exception:
        chars = 0
    area = abs(page.rect) or 1.0
    covered = 0.0
    count = 0
    try:
        for info in page.get_image_info():
            count += 1
            r = fitz.Rect(info["bbox"]) & page.rect
            if not r.is_empty:
                covered += abs(r)
    except Exception:
        pass
    coverage = min(1.0, covered / area)
    needs = chars < MIN_TEXT_CHARS and coverage >= MIN_IMAGE_COVERAGE
    blank = chars == 0 and coverage < 0.02 and not _has_drawings(page)
    return PageInfo(page.number, chars, count, coverage, needs, blank)


def _has_drawings(page: fitz.Page) -> bool:
    try:
        return len(page.get_drawings()) > 0
    except Exception:
        return False


def pages_needing_ocr(doc: fitz.Document) -> list[int]:
    return [i for i in range(doc.page_count) if classify_page(doc[i]).needs_ocr]


# =============================================================== recognition
@dataclass
class OcrWord:
    rect: tuple[float, float, float, float]   # page VIEW coordinates (rotation applied), points
    text: str


@dataclass
class OcrPage:
    index: int
    rows: list[list[OcrWord]] = field(default_factory=list)   # reading order, row by row
    error: str = ""
    seconds: float = 0.0

    @property
    def word_count(self) -> int:
        return sum(len(r) for r in self.rows)

    def text(self, layout: bool = True) -> str:
        """Plain text, one line per row. With `layout`, wide gaps become several spaces
        so table columns (e.g. bank statements) stay apart."""
        lines = []
        for row in self.rows:
            parts = []
            prev = None
            for w in row:
                if prev is not None:
                    gap = w.rect[0] - prev.rect[2]
                    char_w = max(1.0, (prev.rect[2] - prev.rect[0]) / max(1, len(prev.text)))
                    parts.append("    " if layout and gap > 2 * char_w else " ")
                parts.append(w.text)
                prev = w
            lines.append("".join(parts))
        return "\n".join(lines)


def _render_upright(page: fitz.Page, dpi: int) -> fitz.Pixmap:
    # colour is required: MuPDF's OCR silently returns nothing for greyscale pixmaps
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    pix.set_dpi(dpi, dpi)
    return pix


def recognize_pixmap(pix: fitz.Pixmap, languages: str, tessdata: str, view_size: tuple[float, float]) -> list[list[OcrWord]]:
    """OCR a pixmap; return rows of words in view coordinates of size `view_size`."""
    data = pix.pdfocr_tobytes(language=languages, tessdata=tessdata)
    ocr_doc = fitz.open("pdf", data)
    try:
        ocr_page = ocr_doc[0]
        sx = view_size[0] / (ocr_page.rect.width or 1)
        sy = view_size[1] / (ocr_page.rect.height or 1)
        words = _words_from_ocr_page(ocr_page, sx, sy)
    finally:
        ocr_doc.close()
    return group_rows(words)


def _words_from_ocr_page(ocr_page: fitz.Page, sx: float, sy: float) -> list[OcrWord]:
    """Each OCR word is its own span; split spans at spaces just in case."""
    raw = ocr_page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    words: list[OcrWord] = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                current: list = []
                for ch in span.get("chars", []) + [None]:
                    if ch is None or ch["c"].isspace():
                        if current:
                            text = "".join(c["c"] for c in current)
                            r = fitz.Rect(current[0]["bbox"])
                            for c in current[1:]:
                                r |= fitz.Rect(c["bbox"])
                            if text.strip() and r.width > 0 and r.height > 0:
                                words.append(OcrWord((r.x0 * sx, r.y0 * sy, r.x1 * sx, r.y1 * sy), text))
                        current = []
                    else:
                        current.append(ch)
    return words


def group_rows(words: list[OcrWord]) -> list[list[OcrWord]]:
    """Group words into visual rows (top to bottom), each row left to right."""
    rows: list[list[OcrWord]] = []
    bounds: list[list[float]] = []      # [y0, y1] per row
    for w in sorted(words, key=lambda w: ((w.rect[1] + w.rect[3]) / 2, w.rect[0])):
        cy = (w.rect[1] + w.rect[3]) / 2
        h = w.rect[3] - w.rect[1]
        if bounds and bounds[-1][0] - 0.1 * h <= cy <= bounds[-1][1] + 0.1 * h:
            rows[-1].append(w)
            bounds[-1][0] = min(bounds[-1][0], w.rect[1])
            bounds[-1][1] = max(bounds[-1][1], w.rect[3])
        else:
            rows.append([w])
            bounds.append([w.rect[1], w.rect[3]])
    for row in rows:
        row.sort(key=lambda w: w.rect[0])
    return rows


def ocr_page_from_file(path: str, password: str | None, index: int, languages: str,
                       dpi: int, tessdata: str) -> OcrPage:
    """Recognise one page. Runs inside a worker process; never raises."""
    t0 = time.time()
    result = OcrPage(index)
    try:
        doc = fitz.open(path)
        if doc.needs_pass and not doc.authenticate(password or ""):
            raise RuntimeError("password not accepted")
        page = doc[index]
        pix = _render_upright(page, dpi)
        result.rows = recognize_pixmap(pix, languages, tessdata, (page.rect.width, page.rect.height))
        doc.close()
    except Exception as exc:          # one bad page must not stop the job
        result.error = f"{type(exc).__name__}: {exc}"
    result.seconds = time.time() - t0
    return result


# ====================================================== invisible text layer
FONT_NAME = "PWOcrGlyphless"


def add_text_layer(page: fitz.Page, rows: list[list[OcrWord]], fontfile: str | None = None) -> int:
    """Write the recognised words onto `page` as invisible, selectable text.

    Word boxes are in view coordinates (page.rect space); they are converted to
    the page's unrotated space and the text is rotated to match, so the layer
    lines up with the image on pages that carry a /Rotate value.
    Returns the number of words written.
    """
    fontfile = fontfile or str(glyphless_font_path())
    font = fitz.Font(fontfile=fontfile)
    rot = page.rotation % 360
    derot = page.derotation_matrix
    written = 0
    for row in rows:
        for i, w in enumerate(row):
            r = fitz.Rect(w.rect)
            if r.is_empty or not w.text.strip():
                continue
            fontsize = max(1.0, r.height * 0.85)
            natural = font.text_length(w.text, fontsize=fontsize)
            if natural <= 0:
                continue
            stretch = r.width / natural
            text = w.text + (" " if i < len(row) - 1 else "")
            origin = fitz.Point(r.x0, r.y1 - 0.2 * fontsize) * derot
            scale = fitz.Matrix(stretch, 1) if rot in (0, 180) else fitz.Matrix(1, stretch)
            page.insert_text(origin, text, fontsize=fontsize, fontname=FONT_NAME, fontfile=fontfile,
                             render_mode=3, rotate=rot, morph=(origin, scale))
            written += 1
    return written


# ============================================================ job runner
@dataclass
class OcrJobResult:
    output: Path | None
    pages_done: list[int] = field(default_factory=list)
    pages_failed: dict[int, str] = field(default_factory=dict)
    pages_skipped: list[int] = field(default_factory=list)     # already had text
    cancelled: bool = False
    seconds: float = 0.0
    words: int = 0


def worker_count() -> int:
    return max(1, min(6, (os.cpu_count() or 2) - 1))


def _executor(workers: int) -> cf.ProcessPoolExecutor:
    return cf.ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))


def recognize_pages(path: str, password: str | None, pages: list[int], languages: list[str], dpi: int,
                    on_page: Callable[[OcrPage, int, int], None] | None = None,
                    is_cancelled: Callable[[], bool] | None = None,
                    workers: int | None = None) -> tuple[list[OcrPage], bool]:
    """OCR `pages` in parallel worker processes.

    `on_page(result, done, total)` is called as each page finishes (in any order).
    Returns (results sorted by page, cancelled).
    """
    tessdata = str(check_ready(languages))
    lang = "+".join(languages)
    workers = workers or worker_count()
    results: list[OcrPage] = []
    cancelled = False
    total = len(pages)
    if total == 0:
        return results, False
    try:
        with _executor(min(workers, total)) as pool:
            futures = {pool.submit(ocr_page_from_file, path, password, i, lang, dpi, tessdata): i for i in pages}
            for fut in cf.as_completed(futures):
                res = fut.result()
                results.append(res)
                if on_page:
                    on_page(res, len(results), total)
                if is_cancelled and is_cancelled():
                    cancelled = True
                    for f in futures:
                        f.cancel()
                    break
    except cf.process.BrokenProcessPool as exc:
        # Worker processes could not start (e.g. blocked by security software):
        # fall back to doing the work here, one page at a time.
        log.warning("OCR worker processes unavailable (%s); running in-process", exc)
        done_pages = {r.index for r in results if not r.error}
        results = [r for r in results if not r.error]
        for i in pages:
            if i in done_pages:
                continue
            if is_cancelled and is_cancelled():
                cancelled = True
                break
            res = ocr_page_from_file(path, password, i, lang, dpi, tessdata)
            results.append(res)
            if on_page:
                on_page(res, len(results), total)
    results.sort(key=lambda r: r.index)
    return results, cancelled


def make_searchable(path: str, password: str | None, output: str, languages: list[str], dpi: int = 300,
                    pages: list[int] | None = None,
                    progress: Callable[[int, int, str], None] | None = None,
                    is_cancelled: Callable[[], bool] | None = None,
                    workers: int | None = None) -> OcrJobResult:
    """Create `output`: a copy of `path` with an invisible OCR text layer.

    `pages` = pages to consider (default: all). Pages that already contain text
    are skipped, so running OCR twice never duplicates text.
    """
    t0 = time.time()
    fontfile = str(glyphless_font_path())
    out_path = Path(output)
    if out_path.resolve() == Path(path).resolve():
        raise ValueError("The OCR result must be saved as a new file, not over the original.")

    doc = fitz.open(path)
    if doc.needs_pass and not doc.authenticate(password or ""):
        doc.close()
        raise RuntimeError("The password was not accepted.")
    try:
        candidates = list(range(doc.page_count)) if pages is None else [p for p in pages if 0 <= p < doc.page_count]
        todo, skipped = [], []
        for i in candidates:
            (todo if classify_page(doc[i]).needs_ocr else skipped).append(i)
        result = OcrJobResult(None, pages_skipped=skipped)
        if progress:
            progress(0, len(todo), f"{len(todo)} page(s) to recognise, {len(skipped)} already have text")

        def on_page(res: OcrPage, done: int, total: int) -> None:
            if res.error:
                result.pages_failed[res.index] = res.error
                log.warning("OCR failed on page %d: %s", res.index + 1, res.error)
            else:
                result.words += add_text_layer(doc[res.index], res.rows, fontfile)
                result.pages_done.append(res.index)
            if progress:
                progress(done, total, f"Recognised page {res.index + 1}  ({done} of {total})")

        _, cancelled = recognize_pages(path, password, todo, languages, dpi, on_page, is_cancelled, workers)
        result.cancelled = cancelled
        if cancelled:
            result.seconds = time.time() - t0
            return result

        # write to a temporary file first; move into place only on success
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=str(out_path.parent))
        os.close(fd)
        try:
            if password:
                perms = doc.permissions if doc.permissions not in (None, -1) else -1
                doc.save(tmp, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_AES_256,
                         user_pw=password, owner_pw=password, permissions=perms)
            else:
                doc.save(tmp, garbage=3, deflate=True)
            os.replace(tmp, out_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        result.output = out_path
        result.pages_done.sort()
        result.seconds = time.time() - t0
        log.info("OCR %s -> %s: %d pages, %d words, %.1fs", path, out_path, len(result.pages_done),
                 result.words, result.seconds)
        return result
    finally:
        doc.close()


def recognize_single_page(path: str, password: str | None, index: int, languages: list[str],
                          dpi: int = 300) -> OcrPage:
    """OCR one page (any page, with or without existing text) in a worker process."""
    results, _ = recognize_pages(path, password, [index], languages, dpi, workers=1)
    return results[0] if results else OcrPage(index, error="no result")


def default_output_path(path: str | Path) -> Path:
    p = Path(path)
    return p.with_name(f"{p.stem}_OCR.pdf")


def in_worker_process() -> bool:
    return multiprocessing.current_process().name != "MainProcess"


__all__ = [
    "LANGUAGE_NAMES", "QUALITY_DPI", "OcrUnavailable", "PageInfo", "OcrWord", "OcrPage", "OcrJobResult",
    "find_tessdata", "available_languages", "language_label", "check_ready", "classify_page",
    "pages_needing_ocr", "recognize_pixmap", "group_rows", "add_text_layer", "recognize_pages",
    "make_searchable", "recognize_single_page", "default_output_path", "worker_count",
]
