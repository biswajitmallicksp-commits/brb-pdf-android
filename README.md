# BRB PDF: offline PDF editor + bank statement analyzer

One app with two parts. It is a single HTML page that runs on your phone or computer.
**It uses no API, no API key and no internet service.** PDFs are read on the device by
[pdf.js](https://mozilla.github.io/pdf.js/) and written by [pdf-lib](https://pdf-lib.js.org/) (both bundled in
`web/vendor/`), so you don't need Acrobat or any other PDF app.

## PDF editor

Open any PDF (file picker, or **Open with → BRB PDF** from Files, Google Drive or Gmail on Android) and:

| Tool | What it does |
|---|---|
| **Read** | Scroll through the pages, zoom with the − / + buttons, **Find** text, **Copy text** of a page. |
| **Edit text** | Tap a line of existing text to rewrite it. The old text is covered with the page's background colour and your new text is written in a matching size, font style and colour. |
| **Add text** | Tap anywhere to type new text. Change font (Helvetica, Times, Courier), size, bold and colour. Drag a text box to move it. |
| **Draw / sign** | Draw or sign with your finger, in any colour and width. |
| **Highlight** | Tap a line to highlight it, or drag over an area. |
| **White-out** | Drag over anything to cover it. |
| **Erase edit** | Tap one of your own edits to remove it. **Undo / Redo** work for every change. |

Pages: move up / down, rotate, delete, add a blank page, or add the pages of another PDF (merge).
**Save PDF** opens Android's "Save to" picker (phone storage or Drive); the original file is never changed.

Notes:
- Edited and added text uses the standard PDF fonts, which cover English and other Latin-script text
  (₹ is written as "Rs."). Text in other scripts can't be typed in yet.
- Password-protected PDFs open after you type the password. When saving, their pages are stored as images
  (the protection prevents copying the original page content), with your edits on top.
- Scanned pages have no text to rewrite; use White-out and Add text on them instead.

## Bank statement analyzer

Turns PDF bank statements into a 365-day ledger, with the statements saved in the browser's database on the device.
In the editor, **⋯ → Read as bank statement** sends the open PDF here.

### What it does

1. **Upload** one or more PDF statements, for example from Google Drive through the file picker.
   Password-protected PDFs ask for their password.
2. **Reading** finds the transaction table (date, description, debit, credit, balance) and the statement details
   (bank name, account name, account number, statement period, opening balance). It uses the column headers
   and checks every row against the printed running balance.
3. **Review** shows what was read. You can correct any detail, then tap **Save to database**.
4. **Database** stores each statement with its details. Re-uploading the same statement replaces it.
5. **365-day ledger** starts on the first date of the earliest statement:

| Date | Description of Transaction | Debit Amount | Credit Amount | Day End Balance |
|---|---|---|---|---|
| 01-Jun-2025 | UPI/… | 100.00 | 0.00 | 0 |
| 01-Jun-2025 | Salary | 0.00 | 500.00 | 1,400.00 |
| 02-Jun-2025 | No transaction | 0.00 | 0.00 | 1,400.00 |
| 01-Aug-2025 | Statement not uploaded | 0.00 | 0.00 | — |

   - A day with several transactions shows the day end balance on its last row only; the other rows show 0.
   - A day without transactions shows 0 / 0 and the previous day's balance.
   - If the statements don't cover 365 days, the app tells you which date the next statement must start from.
     Overlapping statements are de-duplicated.
   - **Export CSV** (opens in Excel or Google Sheets) or **Copy table**. Statements can be backed up and restored as JSON.

Works with text PDFs downloaded from net banking. Scanned or photographed statements need OCR, which is not included.

## Ways to use it

- **Android app (offline, app name "BRB PDF"):** download `BRB-Statement-Analyzer.apk` from this repository's **Releases** page on your phone
  and install it. GitHub Actions builds and publishes a new APK on every push. The app has no internet permission.
- **Any browser:** open `web/index.html` through any static web host (GitHub Pages, Netlify...).

## Development

```
cd tests && npm ci && npm test          # parser, ledger and PDF editor tests
python3 tests/make_fixtures.py          # regenerate the sample PDFs (needs reportlab)
./gradlew assembleRelease               # build the APK (needs the Android SDK)
```

- `web/statement-parser.js`: PDF text → transactions and statement details; 365-day ledger; CSV.
- `web/index.html`: the app UI (mode switch, statement upload, review, statements database, ledger, export).
- `web/pdf-editor.js`: the PDF editor UI (rendering, tools, pages).
- `web/pdf-editor-core.js`: page geometry and writing the edited PDF with pdf-lib (tested in Node).
- `app/`: the Android WebView shell that serves `web/` from inside the APK.
