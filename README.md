# PDF Workbench

An offline PDF reader, editor and analysis workbench for Windows, built for day-to-day
office work with financial documents and bank statements.

**Status: version 0.4.0.** A fast PDF viewer; offline OCR in English, Bengali and Hindi;
page management; text and picture editing; comments (highlight, notes, shapes, stamps);
true redaction; watermarks, headers and footers; and PDF analysis. Table extraction and
bank-statement analysis arrive next (see *Roadmap* below).

## Privacy

- Every document is processed **on this computer only**.
- The application makes **no network connections** while running. It has no accounts,
  no registration, no analytics and no update checks.
- Internet is needed **once**, only when `run.bat` or `build.bat` downloads the Python
  packages. The finished program in `dist\PDFWorkbench` never needs internet.
- Settings, recent-file list and logs are stored in `%LOCALAPPDATA%\PDFWorkbench\`.
  Logs contain file paths and errors, never document text.

## Features

| Area | What you can do |
| --- | --- |
| Opening | Open one or many PDFs (Ctrl+O), drag-and-drop onto the window, Open Recent, open from the command line. Each document gets its own tab. Password-protected PDFs ask for the password. |
| Viewing | Continuous scroll, single page, two pages side by side. Zoom 10-800 %, Fit width, Fit page, Ctrl+mouse wheel zoom. Rotate the view. Full screen (F11). Light and dark mode. |
| Navigation | Page thumbnails, bookmarks (outline), first / previous / next / last page, type a page number, Go to page (Ctrl+G). Reopens each file at the page you left. |
| Search | Search the whole document (Ctrl+F or the search box), all matches highlighted, results list with context, F3 / Shift+F3 for next / previous. |
| Text | Select text by dragging with the Select tool (V), double-click selects a word, Ctrl+A selects the page's text, Ctrl+C copies. Hand tool (H) drags the page. |
| Output | Print with the Windows print dialog (all pages, current page, ranges like `1-3,7`, copies, orientation, paper). Save As a copy. |
| Information | Document properties (Ctrl+D): size, pages, PDF version, page size, title, author, dates, producer, encryption, permissions, forms, embedded files. |
| Robustness | Damaged or non-PDF files show a clear message; the app keeps running. Every error is logged (Help > Open Log Folder). |
| OCR | See *OCR (scanned PDFs)* below. |
| Pages | See *Page management* below. |
| Editing | See *Editing text and pictures* below. |
| Comments | See *Comments and markup* below. |
| Analysis | See *PDF analysis* below. |
| Performance | Only visible pages are rendered, in a background thread, into a memory-limited cache. Tested with 600 pages: opens in under 0.1 s, full-text search in under 2 s. |

## Page management

**Pages > Organise Pages** (Ctrl+Shift+P, or the grid button on the toolbar) shows every
page as a large thumbnail.

- **Select** pages with click, Ctrl+click, Shift+click or Ctrl+A.
- **Drag** selected pages to a new place to reorder them (a blue bar shows where they go).
- **Drag PDF or image files from Explorer** onto the grid to insert them at that spot.
- **Right-click** for the page menu; the **Delete** key deletes the selection;
  **double-click** a page to open it in the reader.

In the normal reading view, the same commands apply to the current page (or ask which pages).

| Command | What it does |
| --- | --- |
| Rotate Pages (Ctrl+R / Ctrl+L / 180°) | Turns pages permanently (saved in the file). *View > Rotate View* only turns the screen. |
| Delete Pages (Ctrl+Del) | Removes pages, e.g. `2, 5-7`. |
| Duplicate Pages | Inserts a copy after each selected page. |
| Move Pages | Moves pages to the beginning, end, or before/after a page. |
| Reverse Page Order | For back-to-front scans. |
| Insert Blank Pages | Same size as the current page, or A4/A3/A5/Letter/Legal, portrait or landscape. |
| Insert Pages from File (Ctrl+I) | From another PDF (all pages or e.g. `3, 1`) or from images (JPG, PNG, TIFF...). |
| Replace Pages | Swap pages for pages from another file (e.g. a corrected page). |
| Extract Pages (Ctrl+E) | Save chosen pages as a new PDF, or one PDF per page; optionally remove them afterwards. |
| Split Document | Every N pages, by ranges (`1-3, 4-10, 11-`), one file per page, or by top-level bookmarks. |
| Combine Files (Ctrl+M) | Merge PDFs and images, in the order you choose, into one PDF, with a bookmark per file. |

**Safety:**
- Page changes happen in memory. **Edit > Undo** (Ctrl+Z) and **Redo** (Ctrl+Y) work for
  every change (the last 30 steps). The tab shows `*` while there are unsaved changes.
- **File > Save** asks: *Save as new file* (default - the original stays unchanged) or
  *Overwrite original*. Closing a changed document asks the same, plus *Discard*.
- Extract, Split and Combine always create **new files** and never overwrite existing ones
  without asking. Split adds `(2)`, `(3)`... instead of overwriting.
- Password-protected documents stay protected: saved, extracted and split files get the
  same password.

## Editing text and pictures

The second toolbar row holds the editing tools (also in the **Edit** menu). After using a
tool, press **Esc** (or click the arrow) to return to Select.

| Tool | How to use it |
| --- | --- |
| **Add Text** | Click (or drag a box) where the text should go, type it, choose font, size, bold/italic, colour and alignment. Any language: Bengali and Hindi automatically use the Nirmala UI font that comes with Windows. |
| **Edit Text Panel** (Ctrl+Shift+E) | Opens a panel at the right with every line of the current page (table columns as separate pieces). Click a line on the page to find it in the panel. Type over it to change it, or press **✕** to delete it - change as many lines as you like - then press **Apply Changes**. The old words are really removed and the new ones written in the same place, size and colour. Ctrl+Z undoes it. Moving to another page shows that page's lines. |
| **Edit Text** | Move over the page - the line under the mouse is outlined. Click it, change the words (e.g. a figure or a name), OK. The line is rewritten in the closest matching font, size and colour. Leave it empty to delete the line. |
| **Delete Text** | Drag over the words to remove. They are truly removed from the file; pictures and lines underneath stay. |
| **Add Picture** | Click or drag a box, choose a JPG/PNG (e.g. a signature image, logo or seal). |
| **Delete Picture** | Drag over a picture to remove it. |
| Edit > Extract Pictures | Saves every picture of the document as image files. |
| Edit > Watermark | Text (e.g. CONFIDENTIAL, COPY) or image, opacity, angle, position, behind/in front, and which pages. |
| Edit > Header & Footer | Six positions; codes `{page}`, `{pages}`, `{date}`, `{file}`; font size, colour, margin, first number, pages. |

Notes on editing existing text: PDF files do not store paragraphs, only positioned
characters, and usually embed only the letters they use. So *Edit Text* works line by
line and writes the new text in the nearest installed font; the result is very close but
may not be pixel-identical. Scanned pages are pictures - their text cannot be edited
(use Redact to remove, and Add Text to write).

## Comments and markup

Comment tools (second toolbar row and **Tools > Comment**): Highlight, Underline,
Strikethrough, Squiggly, Sticky Note, Text Box, Rectangle, Ellipse, Line, Arrow, Pen,
Stamp (PAID, RECEIVED, VERIFIED, ORIGINAL SEEN, APPROVED... with today's date, or your own
text), and Eraser.

- Comments stay **editable**: with the Select tool click one to select it, **drag** to move,
  drag the **blue corner** to resize, press **Delete** to remove, **double-click** a note or
  text box to change its text.
- The **Properties panel** (right side, F6) sets colour, fill, line width, opacity and font
  size - for the next items you draw, or for the selected comment (*Apply changes*).
- The **Comments** tab in the left panel lists all comments by page; click to jump there.
- Tools > *Delete All Comments*, *Flatten Comments* (make them part of the page).
- Comments are standard PDF annotations: Adobe Reader, Chrome, Edge etc. show them too.

## Redaction (removing confidential information)

Drawing a black box over text does **not** remove it - the text is still underneath and
can be copied. PDF Workbench does real redaction:

1. **Redact** tool: drag over areas, or **Tools > Redact > Mark Text for Redaction** to mark
   every occurrence of e.g. an account or PAN number. Marks show as red boxes.
2. **Apply Redactions**: everything under the marks (text, picture pixels, drawings) is
   permanently removed and replaced by a black box. Optionally also remove the document
   information (author, title, software).
3. Save as a **new file**; keep the original safe.

## PDF analysis

**Analysis > Analyse Document** (Ctrl+Shift+A, toolbar chart button) opens a report while you
keep working:

- **Summary:** findings (scanned pages without OCR, blank pages, fonts not embedded,
  signature fields, JavaScript, attachments, damaged/repaired file, edited-after-creation)
  and basic information (size, pages, PDF version, page sizes, title, author, creator,
  producer, dates, encryption, permissions).
- **Pages:** one row per page - size, paper (A4/Letter/Legal...), orientation, rotation,
  content type (Text / Scanned - needs OCR / Scanned with OCR text / Blank / Mixed),
  characters, words, images, image cover, comments, links, form fields, ruled tables.
  Double-click a row to go to that page.
- **Structure:** bookmarks, form fields and values, signature fields, attachments, scanned
  and blank page lists.
- **Fonts:** every font, embedded or not, and where it is used.
- **Export pages** to CSV (opens in Excel), **Save report** as a web page (HTML) or text.
  Digital signatures are listed but their validity is **not** claimed (verification is a
  later phase).

## OCR (scanned PDFs)

Scanned statements are pictures of text, so they cannot be searched or copied. OCR
(optical character recognition) reads the text in the picture.

- **Fully offline.** The recognition engine (Tesseract, built into MuPDF) and the language
  files (`tessdata` folder: English, Bengali, Hindi) are part of the program. No document
  is ever sent anywhere.
- **Automatic detection.** When you open a PDF, scanned pages are found in the background.
  A yellow bar says how many, with a **Make searchable (OCR)** button; the status bar shows
  it too.
- **Make Searchable PDF** (OCR menu, toolbar button, or Ctrl+Shift+O): choose all pages,
  the current page or a range (e.g. `1-5, 8`); tick the languages in the document; pick
  quality (Fast 200 dpi / Standard 300 dpi / High 400 dpi). The result is saved as a **new
  file** (`<name>_OCR.pdf`) and opened in a new tab. It looks exactly like the original -
  an invisible text layer is added on top of each scanned page - so you can search
  (also in Bengali and Hindi), select and copy text in this program, Adobe Reader, Chrome
  or any other PDF reader.
- **The original is never changed.** Pages that already contain text are skipped, so
  running OCR twice never doubles the text. Password-protected files stay protected.
- **Recognise Text on This Page** (Ctrl+Shift+R): reads the current page and shows the
  text in a window where you can correct it, **Copy all**, or **Save as TXT**. "Keep table
  columns apart" spaces out columns, useful for pasting bank statements into Excel.
- **Speed:** about 2-5 seconds per page per CPU core (more languages = slower). Several
  pages are recognised at once on multi-core computers, and you can keep reading while OCR runs.
- **More languages:** OCR > OCR Languages shows the language folder. Copy any extra
  `.traineddata` file (Tamil, Odia, Gujarati...) from the *tesseract-ocr/tessdata_best*
  project into it and restart.
- **Command line** (for many files at once):
  `PDFWorkbench.exe --ocr "in.pdf" "out.pdf" --lang eng+ben+hin --dpi 300`

Tips for best accuracy: tick only the languages that are really in the document; use High
quality for small or faint print; pages must be the right way up (upside-down scans can be
fixed with the page-rotation tools in the next phase).

## Installation (first time)

1. **Install Python 3.12, 3.13 or 3.14 (64-bit)** from <https://www.python.org/downloads/windows/>.
   On the first installer screen tick **"Add python.exe to PATH"**, then click *Install Now*.
2. **Unzip** this project to a simple folder, for example `C:\PDFWorkbench`.
   (Avoid folders synced by OneDrive; they can slow the build.)
3. **Double-click `run.bat`.** The first time it creates a `.venv` folder and downloads
   the packages (about 150 MB, needs internet, takes 2-5 minutes). The application
   window then opens. Every later start is offline and takes a few seconds.

## Running during development

```bat
cd C:\PDFWorkbench
run.bat
run.bat "D:\Statements\June 2025.pdf"
```

## Building the Windows program (.exe)

Double-click **`build.bat`**. It will:

1. create/reuse the `.venv` and install the build tools,
2. run the automatic tests (the build stops if a test fails),
3. build the program with PyInstaller,
4. put the result in **`dist\PDFWorkbench\PDFWorkbench.exe`**.

Copy the whole `dist\PDFWorkbench` folder wherever you like (for example
`C:\Program Files\PDFWorkbench` or a USB stick) and create a desktop shortcut to
`PDFWorkbench.exe`. A proper installer with Start-menu shortcut and uninstaller comes
in Phase 8.

To open PDFs by double-clicking them in Explorer: right-click a PDF > *Open with* >
*Choose another app* > *More apps* > *Look for another app on this PC* > select
`PDFWorkbench.exe`.

## How to test

1. Create test files (a 600-page statement-style PDF, a password-protected PDF and an
   image-only "scanned" PDF):

   ```bat
   .venv\Scripts\python tests\make_sample_pdf.py
   ```

   They appear in `tests\samples\`. The protected file's password is `test123`.
2. Run the automatic tests:

   ```bat
   .venv\Scripts\python -m unittest discover -s tests -v
   .venv\Scripts\python tests\test_ui_smoke.py
   .venv\Scripts\python tests\test_ocr_ui.py
   .venv\Scripts\python tests\test_pages_ui.py
   .venv\Scripts\python tests\test_edit_ui.py
   .venv\Scripts\python tests\test_analysis_ui.py
   ```

3. Manual checklist:
   - [ ] Open `sample_600_pages.pdf`; scroll quickly from page 1 to 600 - no freezing.
   - [ ] Click thumbnails and bookmarks; the view jumps to the right page.
   - [ ] Type `300` in the page box and press Enter.
   - [ ] Zoom with Ctrl+wheel, the zoom box, Fit width and Fit page.
   - [ ] Switch continuous / single page / two pages; rotate left and right.
   - [ ] Search `EMI HOME LOAN`; press F3 and Shift+F3; matches are highlighted.
   - [ ] Drag over a few rows with the Select tool, press Ctrl+C, paste into Notepad.
   - [ ] Open `sample_protected.pdf`: enter a wrong password, then `test123`.
   - [ ] Open `sample_scanned.pdf`: a yellow bar says the page is scanned. Click
         **Make searchable (OCR)**, keep English ticked, Start OCR. A new tab opens with
         `sample_scanned_OCR.pdf`; search `Phase` - it is found and highlighted.
   - [ ] Open one of your own scanned statements and run OCR with English + Bengali/Hindi as needed.
   - [ ] On a scanned page press Ctrl+Shift+R; copy the text into Notepad or Excel.
   - [ ] Rename any .txt file to `.pdf` and open it: you get a clear error, the app keeps running.
   - [ ] File > Print, choose *Microsoft Print to PDF*, pages `1-3`.
   - [ ] File > Save As; open the copy.
   - [ ] Ctrl+D shows properties; toggle dark mode; F11 full screen, Esc to leave.
   - [ ] Open several of your own bank statements in tabs.
   - [ ] Close and reopen the app: Open Recent lists your files and reopens at the last page.
   - [ ] Pages > Organise Pages: select pages 2-3 (Shift+click), drag them after page 6.
   - [ ] Rotate a page (Ctrl+R), delete a page (Delete key), then Ctrl+Z three times - all undone.
   - [ ] Drag a PDF or JPG from Explorer onto the page grid - its pages are inserted there.
   - [ ] Extract pages 1-3 (Ctrl+E) - the new PDF opens.
   - [ ] Split a statement every 1 page into a folder; Combine two statements (Ctrl+M).
   - [ ] Make a change, press Ctrl+S, choose *Save as new file*; the original is unchanged.
   - [ ] Make a change and close the tab: you are asked to save, discard or cancel.
   - [ ] Edit Text: click a figure in a statement line, change it, OK. Search finds the new figure.
   - [ ] Edit Text Panel (Ctrl+Shift+E): click a line on the page, change it; delete another with ✕; Apply Changes. Ctrl+Z brings both back. Go to page 2: the panel shows page 2's lines.
   - [ ] Add Text in Bengali and in English; Delete Text over a word; Add Picture (a signature image).
   - [ ] Highlight a line, add a sticky note and a PAID stamp; select the stamp and drag it.
   - [ ] Draw a rectangle, change its colour in the Properties panel, Apply; press Delete; Ctrl+Z.
   - [ ] Redact an account number with *Mark Text for Redaction*, Apply, save as new file, then
         search for the number in the new file: not found.
   - [ ] Watermark "COPY" on all pages; Header & Footer "Page {page} of {pages}".
   - [ ] Analysis > Analyse Document on a scanned statement: it lists the pages needing OCR.

## Keyboard shortcuts

| Action | Keys |
| --- | --- |
| Open / Save As / Print | Ctrl+O / Ctrl+Shift+S / Ctrl+P |
| Close tab / all tabs | Ctrl+W / Ctrl+Shift+W |
| Find / next / previous | Ctrl+F / F3 / Shift+F3 |
| Copy / select page text | Ctrl+C / Ctrl+A |
| Zoom in / out / 100 % | Ctrl++ / Ctrl+- / Ctrl+1 |
| Fit width / Fit page | Ctrl+2 / Ctrl+0 |
| Continuous / single / two pages | Ctrl+4 / Ctrl+5 / Ctrl+6 |
| Rotate view | Ctrl+Shift+= / Ctrl+Shift+- |
| First / last page | Ctrl+Home / Ctrl+End (Home / End inside the page) |
| Go to page | Ctrl+G |
| Select tool / Hand tool | V / H |
| Side panel / full screen / dark mode | F4 / F11 / Ctrl+Shift+D |
| Properties | Ctrl+D |
| Undo / Redo | Ctrl+Z / Ctrl+Y |
| Organise pages | Ctrl+Shift+P |
| Rotate pages right / left | Ctrl+R / Ctrl+L |
| Delete pages / Insert from file / Extract | Ctrl+Del (Delete in organiser) / Ctrl+I / Ctrl+E |
| Combine files | Ctrl+M |
| OCR / OCR this page | Ctrl+Shift+O / Ctrl+Shift+R |
| Analyse document | Ctrl+Shift+A |
| Properties panel | F6 |
| Back to Select tool / cancel | Esc |
| Delete selected comment | Delete |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Python was not found` | Reinstall Python 3.12 and tick "Add python.exe to PATH". Close and reopen the folder window, then run `run.bat` again. |
| Package installation fails | Check internet access (company proxies can block `pip`). Delete the `.venv` folder and run `run.bat` again. |
| Windows SmartScreen warns about `PDFWorkbench.exe` | Normal for self-built programs that are not code-signed. Click *More info* > *Run anyway*. |
| Antivirus quarantines the .exe | Some antivirus tools distrust PyInstaller programs. Add an exception for the `dist\PDFWorkbench` folder. |
| A PDF shows a pink "could not be displayed" page | That page is damaged. Other pages still work. Details are in the log (Help > Open Log Folder). |
| Search finds nothing in a scanned statement | Run OCR > Make Searchable PDF, then search in the `_OCR.pdf` copy. |
| Edited text looks slightly different | The original font was not reusable; the nearest installed font is used. Choose another font in the Edit Text window if needed. |
| Bengali/Hindi text shows boxes | Windows 10/11 include Nirmala UI. If it was removed, install a Bengali/Devanagari font (e.g. Noto Sans Bengali) and restart. |
| A comment cannot be moved | Highlights and underlines belong to their text; delete and re-create them. |
| OCR says "save first" | OCR reads the saved file. Save your page changes (Ctrl+S), then run OCR. |
| "OCR language files were not found" | The `tessdata` folder must sit next to `PDFWorkbench.exe` (build.bat copies it). Re-run `build.bat`, or copy the project's `tessdata` folder into `dist\PDFWorkbench`. |
| OCR text has mistakes | Tick only the languages in the document; try High quality; make sure the page is upright. Poor, blurred or stamped scans always give some errors - check important figures. |
| OCR is slow | Untick unused languages (each extra language adds time); use Fast quality for clear, large print. |
| Blurry pages on a 4K / 150 % screen | Rendering follows Windows scaling automatically; zoom once to refresh. Report it with a screenshot if it persists. |
| Anything else | Help > Open Log Folder, and send `pdfworkbench.log`. |

## Project layout

See `ARCHITECTURE.md`. In short: `app\ui` is the interface, `app\pdf_viewer` is the PDF
logic, `app\database` is local storage, and one folder per future module
(`pdf_ocr`, `bank_statement`, ...) is already in place.

## Roadmap

- Phase 1 - Foundation viewer: **done** (0.1.0).
- Offline OCR (from Phase 4, brought forward): **done** (0.2.0).
- Phase 2 - Page management: **done** (0.3.0).
- Phase 3 - Editing, comments, redaction, watermark, header/footer: **done** (0.4.0).
- Phase 5 - PDF analysis: **done** (0.4.0).
- Phase 4 - Text and table extraction (with preview and correction).
- Phase 6 - Bank statements: Bank Format Library, transaction parsing, monthly analysis, EMI / bounce / UPI / NEFT detection, Excel export.
- Phase 7 - Advanced: compare, compress, repair, forms, digital signatures, security, batch processing.
- Phase 8 - Packaging: Windows installer with shortcuts and uninstaller.

## Dependencies and licences

| Package | Version | Licence |
| --- | --- | --- |
| Python | 3.12 - 3.14 | PSF |
| PySide6 (Qt 6) | 6.11.2 | LGPL-3.0 |
| PyMuPDF (MuPDF) | 1.28.2 | AGPL-3.0 (commercial licence available from Artifex) |
| Tesseract OCR engine (inside MuPDF) | - | Apache-2.0 |
| Tesseract language models (tessdata_best: eng, ben, hin) | - | Apache-2.0 |
| PyInstaller (build only) | 6.22.3 | GPL-2.0 with bootloader exception |

PyMuPDF's AGPL licence is fully fine for personal and in-house use. If this program is
ever sold or distributed to others as closed source, a commercial MuPDF licence is
required, or the source must be published under the AGPL. Details:
`THIRD_PARTY_LICENSES.md`.

No Adobe code, icons, names or other assets are used. Icons are drawn in code
(`app\ui\icons.py`); the invisible OCR font (`assets\ocr_glyphless.ttf`) was generated for
this project by `tools\make_glyphless_font.py`.
