# Architecture

## Layers

```
UI layer (app/ui)            PySide6 widgets. No PDF logic.
      |  calls; long jobs on QThread workers
Feature modules (app/*)      Plain Python. No Qt widgets. Unit-testable.
      |  calls
Engines                      PyMuPDF (MuPDF). Later: Tesseract, pdfplumber, pikepdf, pyHanko, pandas.

Local services               SQLite (app/database), logs (app/utils), optional local AI (app/ai).
```

Rules:

1. **The UI never touches the PDF engine directly.** Widgets call `PdfDocument` (and
   later module functions). Engines can be swapped and a batch/CLI mode added without
   touching the UI.
2. **Modules never import Qt widgets.** `pdf_viewer/printing.py` uses Qt painting
   classes but no widgets; its dialog lives in the UI.
3. **Long work runs in threads.** `RenderWorker` renders pages; `SearchWorker` searches.
   Later OCR, extraction and batch jobs follow the same pattern (progress + cancel).
4. **One lock per document.** MuPDF documents are not thread-safe, so every access goes
   through `PdfDocument`, which holds an `RLock`. Work is split per page so threads
   interleave and the window never freezes.
5. **Never destroy the original.** Save As writes a copy. Overwriting writes to a
   temporary file first and swaps it in only after success. From Phase 3, edits happen
   on the in-memory document with an undo stack; the file changes only on Save.
6. **Never crash on a bad PDF.** `PdfDocument` converts engine errors into
   `WorkbenchError` subclasses with a clear message; a bad page renders as a
   "could not be displayed" placeholder; a global exception hook logs and reports
   anything unexpected while the app keeps running.

## Modules

| File | Responsibility |
| --- | --- |
| `main.py` | Starts Qt, logging, database, exception hook; opens files from the command line. |
| `app/config.py` | Name, version, data folders, viewer constants. |
| `app/pdf_viewer/document.py` | `PdfDocument`: open (with password), page sizes, render, text, words-in-rectangle, search, outline, properties, safe save. Coordinate conversion page space <-> view space. |
| `app/pdf_viewer/render_cache.py` | Thread-safe LRU cache with a memory budget (300 MB pages, 60 MB thumbnails). |
| `app/pdf_viewer/printing.py` | Render pages at printer resolution (max 300 dpi), fit to paper, auto-rotate. |
| `app/ui/main_window.py` | Menus, toolbar, tabs, status bar, recent files, drag-and-drop, print/save flows, theme. |
| `app/ui/document_tab.py` | One document: owns its renderer thread, caches, viewer and side panels. |
| `app/ui/page_view.py` | Custom viewer: lazy painting of visible pages, 3 layouts, zoom/fit, rotation, search highlights, text selection, hand tool. |
| `app/ui/thumbnail_panel.py` | Lazy thumbnails for visible rows only. |
| `app/ui/side_panels.py` | Bookmarks tree, search panel. |
| `app/ui/workers.py` | `RenderWorker`, `SearchWorker` threads. |
| `app/ui/dialogs.py` | Password, go-to-page, properties dialogs. |
| `app/ui/icons.py`, `theme.py` | Original icons drawn in code; light/dark palettes. |
| `app/database/db.py` | SQLite with versioned migrations: recent files (with last page), settings. |
| `app/utils/errors.py`, `logging_setup.py` | Error types, user messages, rotating log. |
| `app/pdf_ocr/engine.py` | OCR: language data discovery, page classification, recognition in worker processes, invisible text layer, searchable-PDF job. |
| `app/pdf_pages/operations.py` | Page edits (rotate, delete, duplicate, move, insert, replace, reverse) and new-file outputs (extract, split, combine). |
| `app/ui/page_organizer.py`, `app/ui/page_dialogs.py` | Organiser grid with drag-and-drop; insert / extract / split / combine / replace / move dialogs; save-changes prompt. |
| `app/utils/pages.py` | Page-range parsing (`1-3, 7, 10-`, odd, even, last) and formatting. |
| `app/pdf_editor/content.py`, `fonts.py` | Add/edit/delete text, pictures, watermark, header/footer; font discovery (Windows fonts, Nirmala UI for Indic). |
| `app/pdf_annotation/annots.py` | Comments (create, list, hit-test, move, resize, update, delete, flatten) and redaction. |
| `app/pdf_analysis/analyzer.py` | Document/page analysis, findings, CSV/HTML/text export. |
| `app/ui/edit_dialogs.py`, `properties_panel.py`, `widgets.py`, `analysis_ui.py` | Editing dialogs, Properties and Comments panels, colour button, Analysis window. |
| `app/ui/ocr_ui.py` | OCR dialog, scanned-page banner, background jobs, recognised-text window, languages dialog. |
| `app/ai/__init__.py` | `AIProvider` interface; default `NullProvider` (no model). |

## Page management (`app/pdf_pages/operations.py`, UI in `app/ui/page_organizer.py`, `page_dialogs.py`)

```
Organiser / menus --> DocumentTab.run_edit(label, func)
                        --> PdfDocument.apply_edit: snapshot bytes -> func(fitz doc) -> revision += 1
                            (on error: restore snapshot, nothing changed)
                        --> refresh(): viewer layout, thumbnails, organiser, bookmarks, search reset,
                            scanned-page check
Undo / Redo -----------> PdfDocument.undo()/redo(): swap in a snapshot (30 steps, 600 MB cap)
Save -------------------> PdfDocument.save_as(): temp file -> rename; re-protect with password
Extract / Split / Combine -> operations.* write NEW files only (PdfDocument.run_read under the lock)
```

- Edits are pure functions on a PyMuPDF document; the UI never manipulates pages itself.
- Render-cache keys include `PdfDocument.revision`, so an image of an old page is never
  shown for a new one after pages move.
- Snapshot-based undo is simple and exact (every change, including rotation and inserted
  files, is undoable) at the cost of memory, capped at 30 steps / 600 MB.
- Saving over the original happens only when the user explicitly chooses *Overwrite*;
  MuPDF's open file handle is released before the replacement (required on Windows).

## Editing and comments (`app/pdf_editor`, `app/pdf_annotation`, UI in `page_view.py`, `properties_panel.py`, `edit_dialogs.py`)

```
PageView tool (drag / click)  --signal with page-space geometry-->  MainWindow handler
    --> DocumentTab.run_edit(label, func)   (undo snapshot; light refresh keeps the scroll position)
         func = content.add_text / replace_line / delete_text_in / add_image / watermark ...
              or annots.add_shape / add_text_markup / move_annot / update_annot / mark_redaction ...
```

- The viewer never edits: it reports what was drawn (rectangles, points, strokes, word boxes)
  in unrotated page space; handlers call pure functions that take a PyMuPDF page.
- Text is written as real page content: Latin text with `insert_textbox` (no ligatures, exact
  search/copy); Bengali/Devanagari with `insert_htmlbox` (HarfBuzz shaping) using the system's
  Nirmala UI font. Rotated pages are handled by writing in unrotated space with the page's rotation.
- Editing an existing line = text-only redaction of that line + writing the new text at the
  same baseline with the nearest font family, size, colour, bold/italic.
- Comments are standard PDF annotations (editable in any reader). Lines, ink and polygons are
  moved by re-creating them shifted (their points live in the PDF).
- Redaction uses MuPDF's apply_redactions (text removed, image pixels blanked, line art removed).

## Analysis (`app/pdf_analysis/analyzer.py`, UI in `app/ui/analysis_ui.py`)

- `analyze(with_doc, ...)` reads one page at a time through `PdfDocument.run_read`, so the viewer
  keeps rendering during long analyses (600 pages in about 5-7 s); runs in a QThread with progress
  and Stop.
- Page status uses visible vs. invisible text (`get_texttrace`, render mode 3 = OCR layer) and
  image coverage. Signature fields are listed; validity is never claimed.

## OCR module (`app/pdf_ocr/engine.py`, UI in `app/ui/ocr_ui.py`)

```
open PDF --> ScanCheckWorker (thread) --> classify_page(): text chars + image coverage
                                          --> banner "N pages are scanned"
OCR dialog --> OcrJobWorker (thread) --> make_searchable()
                 |-- ProcessPoolExecutor (1 process per core, max 6)
                 |     ocr_page_from_file(): render page upright, RGB, at 200/300/400 dpi
                 |     --> MuPDF Tesseract (pdfocr) --> words with boxes, grouped in rows
                 |-- add_text_layer(): invisible words (render mode 3, glyphless font,
                 |     real spaces, rotated to match /Rotate) on a copy of the document
                 '-- save to temp file --> rename to <name>_OCR.pdf
```

Design decisions:

- **No separate Tesseract install.** PyMuPDF ships MuPDF with Tesseract compiled in; only
  `*.traineddata` files are needed. They live in `tessdata/` next to the exe (user can add
  languages), with fallbacks in the bundle and `%LOCALAPPDATA%\PDFWorkbench\tessdata`.
- **Own text layer instead of MuPDF's OCR page.** MuPDF's OCR output omits spaces between
  Bengali/Devanagari words and would duplicate the page image. We take only the word boxes
  and write each word (plus a real space) in an invisible font whose glyphs are empty but
  whose character map covers Latin, Bengali, Devanagari and currency symbols. Result: the
  page looks unchanged, file size grows only a few KB per page, and extraction is exact.
- **Rotation.** Pages are rendered upright (with /Rotate applied) for recognition; word
  boxes are mapped back with the page's derotation matrix and text is written rotated.
- **Colour pixmaps only.** MuPDF's OCR silently returns no text for greyscale pixmaps.
- **Processes, not threads.** MuPDF calls hold Python's GIL; OCR in a thread would freeze
  the window. `main.py` calls `multiprocessing.freeze_support()` so the frozen .exe can
  start workers; if workers cannot start, OCR falls back to running in-process.
- **Idempotent.** Pages with real text are skipped, so OCR never doubles text.

## How rendering stays fast on big files

1. At open, only page **sizes** are read, so layout is instant.
2. `PageView.paintEvent` draws what is already cached; for missing pages it draws a
   blank page (or the previous zoom level, stretched) and asks `RenderWorker` for the
   visible pages plus a small look-ahead.
3. `RenderWorker.request_pages` **replaces** its queue on every paint, so fast
   scrolling drops pages you have already scrolled past.
4. Rendered images go into the LRU cache; the oldest are evicted at 300 MB.
5. Images are rendered at the screen's device-pixel ratio, so 4K / 150 % screens are sharp.

## Coordinate spaces

- **Page space**: PDF points of the unrotated page (what text extraction and search return).
- **View space**: pixels of the page as drawn, after the page's own `/Rotate`, the view
  rotation and zoom. `PdfDocument.view_matrix()` maps page -> view; its inverse maps back.
  This keeps highlights and selections aligned on rotated pages
  (covered by `test_selection_and_mapping_on_rotated_page`).

## Extension points for later phases

- **Modules**: each future feature has its own package (`pdf_pages`, `pdf_ocr`,
  `bank_statement`, ...). A module exposes plain functions/classes; the UI adds a menu
  entry and a panel. The disabled menu items already show where each will appear.
- **Database**: add a new SQL script to `MIGRATIONS` in `db.py`; existing databases
  upgrade automatically (planned tables: favourites, tags, analysis history, OCR
  settings, bank formats).
- **Bank Format Library** (Phase 6): bank formats stored as editable rules (JSON in
  SQLite): column positions/headers, date formats, Dr/Cr rules, header/footer patterns,
  so new banks are added without code changes.
- **OCR languages**: drop another `.traineddata` file into `tessdata/`; it appears in the
  OCR dialog automatically. `engine.recognize_pages()` is reusable by table extraction,
  bank-statement parsing and batch processing.
- **Local AI**: implement `AIProvider` (for example an Ollama client limited to
  `127.0.0.1`) and call `set_provider()`. Everything works without it.
