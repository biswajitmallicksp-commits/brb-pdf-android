# Changelog

## 0.5.0 - Edit Text panel (2026-10-07)

### Added
- **Edit Text Panel** (Ctrl+Shift+E, toolbar button "Edit Text Panel", Edit menu): a side panel listing every line of the current page; table columns (date | description | amount) appear as separate pieces. Type over a line to rewrite it or press X to delete it, then **Apply Changes**: the old words are truly removed (drawings and pictures kept) and the new words written at the same place, size, colour and closest font. Clicking a line on the page jumps to it in the panel; clicking a row shows it on the page. Rotated pages supported. Undo/Redo work as usual.
- Moving to another page with typed but not applied changes shows a banner instead of losing them; closing the panel asks first.
- Invisible OCR text is not listed (it is not part of what the page shows).
- `content.page_lines()` and `content.replace_lines()`; tests in `test_editing.py` (all rotations) and `tests/test_text_panel_ui.py` (whole workflow in the window).

## 0.4.0 - Editing, comments, redaction and analysis (2026-10-01)

### Added
- Second toolbar row with editing and comment tools; Properties panel (F6); Comments tab.
- Add Text (any language; Bengali/Hindi shaped correctly with Nirmala UI; English written without ligatures so search/copy are exact), Edit Text (line by line, nearest font/size/colour, works on rotated pages), Delete Text (true removal, drawings kept), Add / Delete Picture, Extract Pictures.
- Comments: highlight, underline, strikethrough, squiggly, sticky note, text box, rectangle, ellipse, line, arrow, pen, office stamps (PAID, RECEIVED, VERIFIED... with date) and standard stamps, eraser. Select, move, resize, change colour/fill/width/opacity/font size/text, delete.
- True redaction: mark areas or every occurrence of a text, apply (removes text, image pixels and drawings), optional removal of document information.
- Watermark (text or image; opacity, angle, position, behind/in front, page selection) and Header & Footer (six positions, page/date/file codes).
- Delete All Comments, Flatten Comments.
- Analysis > Analyse Document: findings, basic information, per-page table (paper size, orientation, text/scanned/OCR/blank status, images, comments, links, fields, ruled tables, fonts), structure (bookmarks, form fields, signature fields, attachments, JavaScript), fonts; CSV / HTML / text export; jump to page.
- Tests: `test_editing.py`, `test_edit_ui.py` (real mouse drags), `test_analysis.py`, `test_analysis_ui.py`.

### Changed
- Search and copy treat ligatures (ﬁ, ﬂ) as normal letters.
- Page-content edits keep the scroll position.

### Fixed
- Selecting text with a perfectly horizontal drag selected nothing.

## 0.3.0 - Page management (2026-10-01)

### Added
- Organise Pages view: large thumbnail grid with multi-select, drag-and-drop reordering (insertion bar), drag files from Explorer to insert, right-click menu, Delete key, double-click to open.
- Rotate pages permanently (90 / -90 / 180), delete, duplicate, move, reverse.
- Insert blank pages (current size or A4/A3/A5/Letter/Legal, portrait/landscape) and pages from other PDFs or images, at any position, in the order typed.
- Replace pages with pages from another file.
- Extract pages to a new PDF or one PDF per page, optionally removing them afterwards.
- Split: every N pages, by ranges, one file per page, or by top-level bookmarks; never overwrites existing files.
- Combine files (PDFs and images) in a chosen order, with one bookmark per file plus each file's own bookmarks.
- Undo / Redo (Ctrl+Z / Ctrl+Y, 30 steps) for every page change; failed operations roll back automatically.
- Save asks "Save as new file" (default) or "Overwrite original"; closing a changed document asks Save / Discard / Cancel; `*` marks unsaved tabs.
- Password-protected documents stay protected when saved, extracted or split.
- Tests: `tests/test_pages.py` (operations, undo), `tests/test_pages_ui.py` (whole workflow in the window).

### Changed
- Save As now switches the open document to the new file (like other editors).
- Thumbnails are framed, centred and aligned whatever the page shape.
- OCR on a document with unsaved page changes asks you to save first.

### Fixed
- Edited password-protected files could be saved without their password (MuPDF's "keep encryption" does not survive page changes); files are now re-protected with AES-256.

## 0.2.0 - Offline OCR (2026-10-01)

### Added
- Offline OCR in English, Bengali and Hindi using the Tesseract engine built into MuPDF and bundled `tessdata_best` language models. No extra software to install.
- Automatic detection of scanned pages when a PDF opens: yellow banner and status-bar note.
- OCR > Make Searchable PDF (Ctrl+Shift+O, toolbar button): all pages / current page / range, language choice, Fast / Standard / High quality, progress with Cancel, result opened in a new tab. The original file is never changed.
- Invisible text layer with correct spaces between Bengali and Devanagari words (works for search and copy in any PDF reader); correct placement on rotated pages; pages that already have text are skipped; password protection is kept.
- OCR > Recognise Text on This Page (Ctrl+Shift+R): editable text window with Copy all, Save as TXT and a "keep table columns apart" option.
- OCR > OCR Languages: shows installed languages and the folder for adding more.
- Parallel OCR in worker processes (keeps the window responsive); automatic fallback to single-process mode.
- Command line: `PDFWorkbench.exe --ocr in.pdf out.pdf --lang eng+ben+hin --dpi 300`.
- `assets/ocr_glyphless.ttf` (generated by `tools/make_glyphless_font.py`).
- Tests: `tests/test_ocr.py`, `tests/test_ocr_ui.py`.

### Changed
- `build.bat` copies the `tessdata` folder next to `PDFWorkbench.exe` and stops if it is missing.
- Python 3.12-3.14 supported.

## 0.1.0 - Phase 1: Foundation (2026-09-30)

### Added
- Windows desktop application (Python 3.12, PySide6, PyMuPDF), fully offline.
- PDF viewer with tabs for multiple documents, drag-and-drop, recent files (reopens at the last page), command-line opening.
- Lazy background rendering with a memory-limited cache; tested with 600-page documents.
- Continuous, single-page and two-page layouts; zoom 10-800 %, fit width, fit page, Ctrl+wheel zoom; view rotation; full screen.
- Page thumbnails (lazy), bookmarks panel, page navigation and go-to-page.
- Full-text search with highlighted matches, results list with context, F3 / Shift+F3.
- Text selection (drag, double-click word, select page) and copy to clipboard.
- Printing through the Windows print dialog with page ranges, current page, copies; auto-rotate and fit to paper.
- Save As, and safe overwrite (temporary file + swap) that keeps password protection.
- Password-protected PDF support (prompts; never bypasses security).
- Document properties dialog.
- Light and dark themes; original icons drawn in code.
- SQLite storage with versioned migrations; rotating diagnostic log.
- Clear error messages for damaged or non-PDF files; the application keeps running.
- Placeholder packages and disabled menus for Phases 2-7; `AIProvider` interface for optional local AI.
- `run.bat`, `build.bat` (PyInstaller), unit tests and a headless UI smoke test.
