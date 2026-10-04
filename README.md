# BRB PDF for Android (version 1.0)

An offline PDF app for Android phones and tablets. It can:

- **Read:** smooth scrolling, pinch to zoom, double-tap to zoom, search, bookmarks, go to page, night reading, remembers your last page. You can also make it the phone's default PDF app.
- **OCR (English, Bengali, Hindi):** makes scanned pages searchable and copyable. The page looks the same, with a hidden text layer added, and you can copy or share the text.
- **Page tools:** rotate, delete, duplicate, move, insert blank pages, insert pages from another PDF, extract pages to a new PDF, split into several files, and combine several PDFs.
- **Annotate and sign:**
  - Mark up text: highlight, underline, strike-through.
  - Add notes, text boxes (including Bengali and Hindi), office stamps (PAID, RECEIVED, VERIFIED…, with the date) and pictures.
  - Draw rectangles, ellipses, lines, arrows and freehand.
  - Sign with your finger.
  - Redact (true removal).
  - Undo and redo.
- **Save safely:** saves a new copy, or replaces the original only after you confirm. You can also share, print and password-protect (AES-256).

**Privacy:** the app has **no internet permission**, no account and no analytics. Documents never leave the phone.

---

## What you need

| | |
|---|---|
| A Windows PC | 8 GB RAM or more recommended, about 15 GB free disk space |
| Internet on the PC | Needed **only once**, while Android Studio downloads its tools and the two libraries |
| An Android phone | Android 8.0 or newer, plus a USB cable (or use the emulator built into Android Studio) |
| The OCR language files | They are in the `tessdata` folder of your Windows PDFWorkbench program |

---

## Step-by-step: build and install

### Step 1: Install Android Studio (one time)
1. Download it from **https://developer.android.com/studio** and run the installer.
2. Keep all the default choices. Click **Next** until it finishes.
3. The first time Android Studio opens, it runs the **Setup Wizard**. Choose **Standard**, accept the licences, and wait. It downloads the Android SDK, which takes 10–20 minutes.

### Step 2: Unzip the project
Unzip `BRBPdfAndroid.zip` to a **short path without spaces**, for example:

```
C:\BRBPdfAndroid
```

Avoid OneDrive folders and very long paths. Gradle can fail there.

### Step 3: Copy the OCR language files (one time)
Double-click **`copy_ocr_languages.bat`** in the `C:\BRBPdfAndroid` folder.
- It looks for your PDFWorkbench `tessdata` folder on the Desktop.
- If it cannot find it, drag the `tessdata` folder (the folder containing `eng.traineddata`) into the black window and press **Enter**.

At the end you should see `eng`, `ben` and `hin` with **OK**.
(To do it by hand instead, copy the 3 `.traineddata` files into `C:\BRBPdfAndroid\app\src\main\assets\tessdata\`.)

If you skip this step the app still works, but OCR shows "OCR languages missing".

### Step 4: Open the project in Android Studio
1. Android Studio → **File → Open** (or **Open** on the welcome screen) → select `C:\BRBPdfAndroid` → **OK**.
2. If asked "Trust project?", click **Trust Project**.
3. Wait for **Gradle sync** to finish. Watch the progress bar at the bottom. The first time it downloads Gradle and the libraries (MuPDF and Tesseract), which takes a few minutes.
   If a yellow bar offers to "upgrade the Android Gradle Plugin", click **Don't ask for this project** (the project is already set up correctly).

### Step 5a: Run it on your phone (USB)
1. On the phone, turn on Developer options:
   - Open **Settings → About phone** and tap **Build number** 7 times.
   - Then open **Settings → System → Developer options** and turn on **USB debugging**.
2. Connect the phone with the USB cable and tap **Allow** on the phone.
3. In Android Studio, your phone appears in the device box at the top. Click the green **▶ Run** button.
4. The app installs and opens. The icon is **BRB PDF**.

### Step 5b: Or make an APK file to install on any phone
1. Android Studio → **Build → Build App Bundle(s) / APK(s) → Build APK(s)**.
2. When it finishes, click **locate**. The file is:
   ```
   C:\BRBPdfAndroid\app\build\outputs\apk\debug\app-debug.apk
   ```
3. Copy this file to the phone (USB, Bluetooth or WhatsApp to yourself), tap it, and allow "Install unknown apps" when asked.

> For a permanent office installation you can make a *signed release* APK with **Build → Generate Signed App Bundle / APK → APK**. Create a new key store, keep the key file and password safe, and choose **release**. Later updates must be signed with the same key.

### Step 6: Make BRB PDF the phone's default PDF app
1. Open any PDF in the phone's **Files** app (or from WhatsApp or Gmail).
2. Choose **BRB PDF**, then **Always**.

If another app is already the default:
1. Go to **Settings → Apps → (that app) → Open by default → Clear defaults**.
2. Open a PDF again and choose BRB PDF.

---

## How to use

| To… | Do this |
|---|---|
| Open a PDF | Start screen → **Open a PDF**, or open a PDF from Files/WhatsApp/Gmail |
| Zoom | Pinch, or double-tap |
| Select a word | Long-press it. Keep the finger down and move to select more |
| Search | 🔍 at the top. Use `<` and `>` to step through the results |
| Highlight / underline / strike | **Annotate** (pencil icon) → choose the tool → drag over the words |
| Add a note / text / stamp / picture | **Annotate** → choose it → tap where it should go |
| Sign | **Annotate → Sign** → draw your signature → tap where it goes |
| Draw / shapes | **Annotate → Draw / Rectangle / Ellipse / Line / Arrow**. One finger draws, two fingers scroll |
| Move, resize, recolour or delete a comment | Tap it (with no tool selected). Drag it to move it, or drag the round handle to resize it. Use the bar at the bottom for the rest |
| Undo / Redo | In the Annotate bar or the ⋮ menu. Every change can be undone until you close the file |
| OCR a scanned PDF | ⋮ → **OCR** → choose the languages → choose the pages. Then save a copy |
| Pages: rotate, delete, move, extract, split, insert | ⋮ → **Pages** → tap pages to select them → use the buttons at the bottom |
| Combine PDFs | Start screen → **Combine PDFs** → pick the files → set the order → **Combine** |
| Remove confidential text | **Annotate → Redact area** (or select text → **Mark for redaction**), then ⋮ → **Apply redactions** |
| Save | ⋮ → **Save a copy…** (safe), or **Save (replace original)**, which asks first |
| Password | ⋮ → **Password protect…** saves a protected copy |

### Important notes
- **Signatures:** **Sign** places a *picture* of your signature. It is **not** a digital (cryptographic) signature and does not by itself make a document legally signed.
- **Redaction:** a black rectangle drawn with the Rectangle tool **hides nothing**, because the text under it can still be copied. Only **Apply redactions** really removes the content.
- **The original is safe:** the app works on a private copy. Your file changes only if you choose **Save (replace original)** and confirm.
- **Restricted PDFs:** if the PDF's owner does not allow editing, printing or copying, those tools are switched off. The app does not get around PDF security.
- **OCR:** OCR can make mistakes. Check important figures (amounts, dates, account numbers) against the page.
- **Languages:** text boxes and stamps in **Bengali or Hindi** are added as sharp pictures, because the standard PDF fonts have no Indic letters.

---

## Test checklist (please try these and tell me what happens)

1. [ ] Open a normal PDF from the start screen. Scroll, pinch-zoom and double-tap. Text stays sharp when zoomed.
2. [ ] Open a PDF from WhatsApp or Files with **Open with → BRB PDF**.
3. [ ] Open a password-protected PDF. You are asked for the password, and a wrong password is refused.
4. [ ] Search for a word. The results are highlighted, and `<` and `>` move between them.
5. [ ] Long-press a word, extend the selection, then **Copy** and paste it into WhatsApp.
6. [ ] Annotate: highlight a line, add a note, add a text box in English and one in Bengali or Hindi, add a PAID stamp with the date, and sign.
7. [ ] Draw a rectangle and an arrow. Tap a comment, move it, change its colour and delete it. Then use **Undo** and **Redo**.
8. [ ] **Save a copy…**, then open the copy in another PDF app (for example Chrome or Drive). Your comments are there.
9. [ ] OCR a scanned page (English, then Bengali or Hindi). Then search a word on that page and copy its text.
10. [ ] Pages:
    - [ ] rotate a page
    - [ ] delete a page, then undo
    - [ ] duplicate a page
    - [ ] move a page to the beginning
    - [ ] extract 2 pages to a new file
    - [ ] split a file every 1 page into a folder
    - [ ] insert a blank page
    - [ ] insert another PDF
11. [ ] Combine 3 PDFs in a chosen order.
12. [ ] Redact a line of text, apply it, save a copy, and check that the text can no longer be found or copied.
13. [ ] Share the PDF to WhatsApp, and print it (or Save as PDF from the print screen).
14. [ ] Night reading on and off. Rotate the phone while reading.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Gradle sync: "Could not resolve com.artifex.mupdf:fitz" or "tesseract4android" | The PC needs internet during the first sync. Check the internet connection or proxy, then **File → Sync Project with Gradle Files**. |
| "SDK location not found" | Open **File → Project Structure → SDK Location** and let Android Studio choose its SDK, or simply close and reopen the project. |
| "Unsupported Java" / JDK error | **File → Settings → Build, Execution, Deployment → Build Tools → Gradle → Gradle JDK** → choose **jbr-17** or **jbr-21** (bundled with Android Studio). |
| Phone not shown in Android Studio | Turn **USB debugging** on, change the USB mode to **File transfer**, and accept the "Allow USB debugging?" message on the phone. |
| OCR says "languages missing" | Run `copy_ocr_languages.bat` again, then rebuild (**Build → Rebuild Project**) and run. |
| OCR is slow | That is normal: 5–20 seconds per page depending on the phone. Choosing only the languages actually in the document makes it faster. |
| "Original file cannot be written" | Files opened from WhatsApp or e-mail are read-only. Use **Save a copy…**. |

---

## Project layout (for reference)

```
app/src/main/java/com/brb/pdf/
  MainActivity.kt      start screen: open, combine PDFs, recent files
  ViewerActivity.kt    reading, search, annotate, sign, OCR, save/share/print, redaction
  PageView.kt          page display: zoom, scroll, drawing tools, selection
  OrganizeActivity.kt  page tools (rotate, delete, move, extract, split, insert)
  PdfEngine.kt         one open PDF (all MuPDF work on one background thread; undo/redo)
  Annots.kt            creating and changing comments
  PageOps.kt           page operations and merging
  Ocr.kt, TextLayer.kt offline OCR and the invisible searchable text layer
  Signature.kt         finger signature pad, Bengali/Hindi text pictures
  Store.kt             recent files and file helpers
  ShareProvider.kt     shares only the files you choose to share
app/src/main/assets/
  ocr_glyphless.ttf    invisible font for the OCR text layer
  tessdata/            OCR language files (copied in step 3)
```

## Licences
- **MuPDF** (PDF engine): GNU AGPL-3.0, © Artifex Software. Using the app inside your own office is fine. If you **give the app to other people or companies**, the AGPL requires you to also offer them this source code (or buy a commercial MuPDF licence from Artifex).
- **Tesseract OCR** and **Tesseract4Android**: Apache-2.0. **tessdata_best** language models: Apache-2.0.
- No Adobe code, names or branding are used.
