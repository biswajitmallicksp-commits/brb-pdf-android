# Bank Statement Analyzer

Turns PDF bank statements into a 365-day ledger. It is a single HTML page that runs on your phone or computer.
**It uses no API, no API key and no internet service.** The PDF is read on the device by
[pdf.js](https://mozilla.github.io/pdf.js/) (bundled in `web/vendor/`), and the statements are saved in the
browser's database on that device.

## What it does

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

- **Android app (offline):** download `BRB-Statement-Analyzer.apk` from this repository's **Releases** page on your phone
  and install it. GitHub Actions builds and publishes a new APK on every push. The app has no internet permission.
- **Any browser:** open `web/index.html` through any static web host (GitHub Pages, Netlify...).

## Development

```
cd tests && npm ci && npm test          # parser + ledger tests on sample statements
python3 tests/make_fixtures.py          # regenerate the sample PDFs (needs reportlab)
./gradlew assembleRelease               # build the APK (needs the Android SDK)
```

- `web/statement-parser.js`: PDF text → transactions and statement details; 365-day ledger; CSV.
- `web/index.html`: the app UI (upload, review, statements database, ledger, export).
- `app/`: the Android WebView shell that serves `web/` from inside the APK.
