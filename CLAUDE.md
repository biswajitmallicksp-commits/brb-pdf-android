# Project rules

- **No external APIs.** Do not use Gemini, OpenAI, Claude or any other API, API key or cloud service.
  All processing (PDF reading, parsing, database, ledger, export) must run locally in HTML/JavaScript.
- The app is the HTML page in `web/` (`index.html` + `statement-parser.js` + `pdf-editor-core.js` + `pdf-editor.js`,
  with bundled pdf.js and pdf-lib in `web/vendor/`).
  The Android APK (`app/`) only wraps that page in an offline WebView; keep logic in the HTML/JS, not in Kotlin.
- `web/index.html` is written as a page body (no `<html>`/`<head>`); the Android app and the published page add the skeleton.
- Tests: `cd tests && npm ci && npm test` (parser fixtures come from `tests/make_fixtures.py`; editor save tests in `tests/editor.test.js`).
