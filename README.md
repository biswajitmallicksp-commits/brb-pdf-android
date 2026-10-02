# Statement Analyzer (Android)

Android app that turns PDF bank statements into a 365-day ledger.

1. **Upload** one or more PDF statements: pick them from Google Drive (or phone storage) with the **Upload PDF** button, or use *Send a copy* / *Open with* in the Google Drive app.
2. **Gemini reads the PDF**: the bank name, account holder, account number, statement period, opening and closing balances, and every transaction. Password-protected PDFs are unlocked on the phone first.
3. **Saved to a database**: each statement is stored in an on-device SQLite database with its metadata (bank, account name, account number, statement span) and its transactions.
4. **365-day ledger**: starts on the first date of the earliest statement and has these columns:

| Date | Description of Transaction | Debit Amount | Credit Amount | Day End Balance |
|---|---|---|---|---|
| 01-Jun-2025 | UPI/… | 100.00 | 0.00 | 0 |
| 01-Jun-2025 | Salary | 0.00 | 500.00 | 1,400.00 |
| 02-Jun-2025 | No transaction | 0.00 | 0.00 | 1,400.00 |
| … | | | | |
| 01-Aug-2025 | Statement not uploaded | 0.00 | 0.00 | — |

   - A day with several transactions gets one row per transaction. Only the **last** row shows the day-end balance; the other rows show 0.
   - A day with no transactions shows 0 debit, 0 credit and the previous day's balance.
   - If the uploaded statements don't cover all 365 days, the app tells you which date the next statement should start from. Upload it and the ledger fills in. Overlapping statements are de-duplicated.
   - You can change the start date, and switch between accounts if you upload statements for more than one.
   - **Export** (share icon) saves the ledger as a CSV file that opens in Excel or Google Sheets. You can save it straight to Google Drive.

## Install on your phone

Each push builds the APK on GitHub Actions and publishes it under **Releases**.

1. On your phone, open this repository's **Releases** page and download `BRB-Statement-Analyzer.apk` from the latest release.
2. Open the file and allow *Install unknown apps* for your browser when Android asks.
3. In the app, go to **Settings**, tap **Get a free API key** (Google AI Studio), paste the key and tap **Save**.

New releases install over the old app and keep your saved statements, because every build is signed with the same key (`app/signing/`).

## Build locally

```
./gradlew assembleRelease   # needs the Android SDK (ANDROID_HOME)
```

## Code map

- `ai/GeminiClient.kt`: sends the PDF to the Gemini API (`gemini-2.5-flash` by default) and requests structured JSON.
- `pdf/PdfUnlocker.kt`: removes PDF passwords with PdfBox-Android.
- `data/StatementDb.kt`: the SQLite database (`statements` and `transactions` tables).
- `ledger/LedgerBuilder.kt`: builds the 365-day ledger (unit-tested in `app/src/test`).
- `ui/`: the Jetpack Compose screens (Ledger, Statements, Settings).
