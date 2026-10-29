package com.brb.pdf

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.print.PrintAttributes
import android.print.PrintManager
import android.util.Base64
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale
import java.util.UUID

/**
 * BRB PDF Word: open, edit and create Word (.docx) documents on the phone or tablet, and edit the text of a
 * PDF as a Word document. Everything stays on the device (no internet permission).
 *
 * The page is an editable web page inside the app (WebView, offline); [Docx] reads and writes the .docx.
 */
class WordActivity : Activity() {

    private lateinit var web: WebView
    private val chips = HashMap<String, TextView>()
    private var docUri: Uri? = null          // the .docx being edited; Save writes here
    private var docName = "Document.docx"
    private var page = Docx.Page()
    private var baseFont = "Calibri"
    private var baseSize = 11f
    private var modified = false
    private var loaded = false
    private var fromPdf = false
    private val waiting = HashMap<String, (String) -> Unit>()
    private var afterSave: (() -> Unit)? = null
    private var editFile: File? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        val i = intent
        val htmlPath = i.getStringExtra(EXTRA_HTML_FILE)
        val uri = i.data ?: @Suppress("DEPRECATION") i.getParcelableExtra(Intent.EXTRA_STREAM)
        when {
            htmlPath != null -> {
                fromPdf = true
                docName = i.getStringExtra(EXTRA_TITLE) ?: "Document.docx"
                page = Docx.Page(i.getFloatExtra("pw", 595.3f), i.getFloatExtra("ph", 841.9f),
                    i.getFloatExtra("ml", 36f), 36f, i.getFloatExtra("mr", 36f), 36f)
                baseFont = "Arial"; baseSize = 10f
                show(File(htmlPath).readText())
                File(htmlPath).delete()
                modified = true                       // a converted PDF is not saved anywhere yet
            }
            uri != null -> open(uri)
            else -> { docName = "Document.docx"; show("<p><br></p>") }
        }
        refreshTitle()
    }

    // ================================================================ screen
    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    private fun buildUi() {
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.allowFileAccess = true
            settings.useWideViewPort = true
            settings.loadWithOverviewMode = true
            settings.builtInZoomControls = true
            settings.displayZoomControls = false
            settings.setSupportZoom(true)
            settings.textZoom = 100
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView?, url: String?) = true   // never leave the page
            }
            webChromeClient = WebChromeClient()
            addJavascriptInterface(Bridge(), "BRB")
        }
        val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(dp(6), dp(6), dp(6), dp(6)) }
        fun chip(key: String, text: String, action: (View) -> Unit) {
            val c = chip(text, action).apply { isFocusable = false; isFocusableInTouchMode = false }
            bar.addView(c, LinearLayout.LayoutParams(-2, -2).apply { marginEnd = dp(6) })
            chips[key] = c
        }
        chip("style", "Style ▾") { pickStyle() }
        chip("font", "Font ▾") { pickFont() }
        chip("size", "Size ▾") { pickSize() }
        chip("b", "B") { js("cmd('bold')") }
        chip("i", "I") { js("cmd('italic')") }
        chip("u", "U") { js("cmd('underline')") }
        chip("s", "S") { js("cmd('strikeThrough')") }
        chip("color", "Colour") { askColor("Font colour") { js("cmd('foreColor','#${hex(it)}')") } }
        chip("hl", "Highlight") { pickHighlight() }
        chip("align", "Align ▾") { pickAlign() }
        chip("ul", "• List") { js("cmd('insertUnorderedList')") }
        chip("ol", "1. List") { js("cmd('insertOrderedList')") }
        chip("in", "Indent →") { js("cmd('indent')") }
        chip("out", "← Indent") { js("cmd('outdent')") }
        chip("sp", "Spacing ▾") { pickSpacing() }
        chip("table", "Table ▾") { tableMenu() }
        chip("pic", "Picture") { pickPicture() }
        chip("picsize", "Picture size") { pictureSize() }
        chip("pb", "Page break") { js("pageBreak()") }
        chip("undo", "Undo") { js("cmd('undo')") }
        chip("redo", "Redo") { js("cmd('redo')") }
        val scroll = HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(bar) }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(if (isNight()) Color.rgb(30, 32, 36) else Color.rgb(243, 244, 246))
            addView(scroll, lp())
            addView(web, lp(-1, 0, 1f))
        }
        setContentView(root)
    }

    private fun hex(c: FloatArray) = String.format("%06X", c.toArgb() and 0xFFFFFF)

    private fun refreshTitle() {
        title = (if (modified) "* " else "") + docName
        actionBar?.subtitle = when {
            fromPdf && docUri == null -> "from PDF - not saved yet"
            docUri == null -> "new document - not saved yet"
            else -> "Word document"
        }
    }

    // ============================================================== JS bridge
    private inner class Bridge {
        @JavascriptInterface fun changed() = runOnUiThread { if (!modified) { modified = true; refreshTitle() } }

        @JavascriptInterface fun state(json: String) = runOnUiThread {
            try {
                val o = JSONObject(json)
                for (k in listOf("b", "i", "u", "s", "ul", "ol")) chips[k]?.setChipSelected(o.optBoolean(k))
            } catch (_: Exception) { }
        }

        @JavascriptInterface fun deliver(tag: String, json: String) = runOnUiThread { waiting.remove(tag)?.invoke(json) }
    }

    private fun js(code: String, result: ((String?) -> Unit)? = null) {
        if (!loaded) { toast("The document is still opening..."); return }
        web.evaluateJavascript(code) { result?.invoke(it) }
    }

    private fun q(s: String): String = JSONObject.quote(s)

    /** Get the document from the page as JSON (for saving). */
    private fun withDocument(action: (String) -> Unit) {
        val tag = UUID.randomUUID().toString()
        waiting[tag] = action
        js("deliver('$tag')")
    }

    // ================================================================ open
    private fun open(uri: Uri) {
        docUri = uri
        docName = Files.displayName(this, uri).let { if (it.contains('.')) it else "$it.docx" }
        val prog = Progress(this, "Opening")
        prog.message(docName)
        Thread {
            var err: Throwable? = null
            var doc: Docx.Loaded? = null
            try {
                val input = contentResolver.openInputStream(uri) ?: throw UserError("The file could not be read.")
                doc = input.use { Docx.read(it, docName) }
            } catch (t: Throwable) { err = t }
            runOnUiThread {
                prog.close()
                if (!alive()) return@runOnUiThread
                val d = doc
                if (d == null) {
                    showError("Could not open", if (err is OutOfMemoryError) UserError("This document is too large for this phone.") else err)
                    web.postDelayed({ finish() }, 300)
                    return@runOnUiThread
                }
                page = d.page; baseFont = d.baseFont; baseSize = d.baseSize
                Store.addRecent(this, uri, docName)
                show(d.html)
                refreshTitle()
            }
        }.start()
    }

    private fun show(content: String) {
        val template = assets.open("word/editor.html").use { it.readBytes().toString(Charsets.UTF_8) }
        val html = Docx.editorPage(template, content, page, baseFont, baseSize)
        val dir = File(cacheDir, "word").apply { mkdirs() }
        dir.listFiles()?.forEach { if (it.name.startsWith("edit_")) it.delete() }
        val f = File(dir, "edit_${System.currentTimeMillis()}.html")
        f.writeText(html)
        editFile = f
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, url: String?) = true
            override fun onPageFinished(view: WebView?, url: String?) { loaded = true }
        }
        web.loadUrl(Uri.fromFile(f).toString())
    }

    // ================================================================ menu
    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, M_SAVE, 0, "Save").setShowAsAction(MenuItem.SHOW_AS_ACTION_ALWAYS or MenuItem.SHOW_AS_ACTION_WITH_TEXT)
        menu.add(0, M_SAVE_AS, 1, "Save as Word (.docx)...")
        menu.add(0, M_PDF, 2, "Save as PDF / Print...")
        menu.add(0, M_SHARE, 3, "Share as Word")
        menu.add(0, M_FIND, 4, "Find and replace...")
        menu.add(0, M_PAGE, 5, "Page setup...")
        menu.add(0, M_NEW, 6, "New Word document")
        menu.add(0, M_HELP, 7, "What is kept")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            M_SAVE -> save()
            M_SAVE_AS -> saveAs()
            M_PDF -> printPdf()
            M_SHARE -> shareDocx()
            M_FIND -> findReplace()
            M_PAGE -> pageSetup()
            M_NEW -> startActivity(Intent(this, WordActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_DOCUMENT or Intent.FLAG_ACTIVITY_MULTIPLE_TASK))
            M_HELP -> info("Word documents", "Kept when opening and saving: text, fonts, sizes, bold / italic / underline / " +
                "strike, colours, highlight, Title and Heading styles, alignment, indents, spacing, bulleted and numbered " +
                "lists, tables (merged cells, column widths), pictures, page breaks, page size and margins.\n\n" +
                "Not kept: headers and footers, footnotes, text boxes, comments and tracked changes. Old .doc files " +
                "cannot be opened - save them as .docx first.\n\nEverything stays on this device.")
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }

    // ================================================================ save
    private fun save(then: (() -> Unit)? = null) {
        val target = docUri
        if (target == null) { afterSave = then; saveAs(); return }
        writeDocx(target, then) { _ ->
            // no permission to write the original (e.g. opened from another app): choose where
            info("Choose where to save", "This app may not change the file where it was opened from. " +
                "Choose a folder and name for the Word document.") { afterSave = then; saveAs() }
        }
    }

    private fun saveAs() {
        val name = Files.stem(docName) + ".docx"
        val i = Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(Docx.MIME)
            .putExtra(Intent.EXTRA_TITLE, name)
        try { startActivityForResult(i, REQ_SAVE_AS) } catch (e: Exception) { toast("No app to choose where to save.") }
    }

    private fun writeDocx(uri: Uri, then: (() -> Unit)?, denied: ((Throwable) -> Unit)? = null) {
        withDocument { json ->
            val prog = Progress(this, "Saving")
            prog.message(Files.displayName(this, uri))
            Thread {
                var err: Throwable? = null
                try {
                    val bytes = Docx.writeBytes(json)          // build it first: the old file stays intact on errors
                    val os = contentResolver.openOutputStream(uri, "wt") ?: throw UserError("Cannot write to that location.")
                    os.use { it.write(bytes) }
                } catch (t: Throwable) { err = t }
                runOnUiThread {
                    prog.close()
                    if (!alive()) return@runOnUiThread
                    val e = err
                    if (e != null) {
                        if (denied != null && (e is SecurityException || e is java.io.FileNotFoundException ||
                                e is UnsupportedOperationException || e is IllegalArgumentException)) denied(e)
                        else showError("Could not save", e)
                        return@runOnUiThread
                    }
                    docUri = uri
                    docName = Files.displayName(this, uri)
                    modified = false
                    fromPdf = false
                    Store.addRecent(this, uri, docName)
                    refreshTitle()
                    toast("Saved: $docName")
                    then?.invoke()
                }
            }.start()
        }
    }

    private fun shareDocx() {
        withDocument { json ->
            Thread {
                var err: Throwable? = null
                var f: File? = null
                try {
                    f = File(ShareProvider.shareDir(this), Files.stem(docName) + ".docx").also { it.writeBytes(Docx.writeBytes(json)) }
                } catch (t: Throwable) { err = t }
                runOnUiThread {
                    val file = f
                    if (file == null) { showError("Could not share", err); return@runOnUiThread }
                    val i = Intent(Intent.ACTION_SEND).setType(Docx.MIME)
                        .putExtra(Intent.EXTRA_STREAM, ShareProvider.uriFor(file)).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    startActivity(Intent.createChooser(i, "Share Word document"))
                }
            }.start()
        }
    }

    /** Android's own print screen: choose "Save as PDF" to make a PDF (real, searchable text), or a printer. */
    private fun printPdf() {
        if (!loaded) return
        js("if (lastImg) lastImg.classList.remove('sel')")
        val name = Files.stem(docName)
        val pm = getSystemService(Context.PRINT_SERVICE) as PrintManager
        val portrait = page.h >= page.w
        val short = minOf(page.w, page.h); val long = maxOf(page.w, page.h)
        var media = when {
            Math.abs(short - 612f) < 3 && Math.abs(long - 792f) < 3 -> PrintAttributes.MediaSize.NA_LETTER
            Math.abs(short - 612f) < 3 && Math.abs(long - 1008f) < 3 -> PrintAttributes.MediaSize.NA_LEGAL
            else -> PrintAttributes.MediaSize.ISO_A4
        }
        if (!portrait) media = media.asLandscape()
        pm.print(name, web.createPrintDocumentAdapter(name),
            PrintAttributes.Builder().setMediaSize(media).setMinMargins(PrintAttributes.Margins.NO_MARGINS).build())
        toast("To make a PDF, choose \"Save as PDF\" at the top of the next screen.")
    }

    // ================================================================ tools
    private fun pickStyle() {
        val names = listOf("Normal", "Title", "Heading 1", "Heading 2", "Heading 3")
        val tags = listOf("p", "h1", "h2", "h3", "h4")
        askChoice("Style", names) { js("block('${tags[it]}')") }
    }

    private fun pickFont() {
        val fonts = listOf("Calibri", "Arial", "Times New Roman", "Cambria", "Georgia", "Verdana", "Courier New")
        askChoice("Font", fonts) { js("cmd('fontName', ${q(fonts[it])})") }
    }

    private fun pickSize() {
        val sizes = listOf(8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72)
        askChoice("Font size", sizes.map { "$it" }) { js("fontSize(${sizes[it]})") }
    }

    private fun pickHighlight() {
        val opts = listOf("Yellow" to "#ffff00", "Green" to "#00ff00", "Turquoise" to "#00ffff", "Pink" to "#ff00ff",
            "Light grey" to "#d9d9d9", "No highlight" to "transparent")
        askChoice("Highlight", opts.map { it.first }) { js("cmd('hiliteColor','${opts[it].second}')") }
    }

    private fun pickAlign() {
        val opts = listOf("Left" to "justifyLeft", "Centre" to "justifyCenter", "Right" to "justifyRight", "Justify" to "justifyFull")
        askChoice("Align", opts.map { it.first }) { js("cmd('${opts[it].second}')") }
    }

    private fun pickSpacing() {
        val opts = listOf(1.0f, 1.15f, 1.5f, 2.0f)
        askChoice("Line spacing", opts.map { String.format(Locale.US, "%.2f", it).trimEnd('0').trimEnd('.') }) {
            js("lineSpacing(${opts[it]})")
        }
    }

    private fun tableMenu() {
        val opts = listOf("Insert table..." to "", "Add row above" to "rowAbove", "Add row below" to "rowBelow",
            "Add column left" to "colLeft", "Add column right" to "colRight", "Merge with the cell on the right" to "merge",
            "Delete row" to "delRow", "Delete column" to "delCol", "Delete table" to "delTable",
            "Show / hide borders" to "borders")
        askChoice("Table", opts.map { it.first }) { k ->
            if (k == 0) insertTable()
            else js("tableOp('${opts[k].second}')") { r ->
                when (r?.trim('"')) {
                    "nocell" -> toast("Tap inside a table cell first.")
                    "nonext" -> toast("There is no cell on the right to merge with.")
                }
            }
        }
    }

    private fun insertTable() {
        val rows = EditText(this).apply { setText("3"); inputType = android.text.InputType.TYPE_CLASS_NUMBER }
        val cols = EditText(this).apply { setText("3"); inputType = android.text.InputType.TYPE_CLASS_NUMBER }
        val box = vbox(20).apply {
            addView(label("Rows", 13f)); addView(rows, lp()); addView(label("Columns", 13f)); addView(cols, lp())
        }
        AlertDialog.Builder(this).setTitle("Insert table").setView(box)
            .setPositiveButton("Insert") { _, _ ->
                val r = rows.text.toString().toIntOrNull()?.coerceIn(1, 200) ?: 3
                val c = cols.text.toString().toIntOrNull()?.coerceIn(1, 20) ?: 3
                js("insertTable($r,$c)")
            }.setNegativeButton("Cancel", null).show()
    }

    private fun pickPicture() {
        val i = Intent(Intent.ACTION_GET_CONTENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/*")
        try { startActivityForResult(i, REQ_IMAGE) } catch (e: Exception) { toast("No app to pick a picture.") }
    }

    private fun insertPicture(uri: Uri) {
        Thread {
            var data: String? = null
            var w = 0f; var h = 0f
            try {
                val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
                var sample = 1
                while (maxOf(opts.outWidth, opts.outHeight) / sample > 1800) sample *= 2
                val bmp = contentResolver.openInputStream(uri)?.use {
                    BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
                } ?: throw UserError("This picture could not be read.")
                val out = ByteArrayOutputStream()
                val png = bmp.hasAlpha()
                bmp.compress(if (png) Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG, 88, out)
                data = "data:image/${if (png) "png" else "jpeg"};base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
                val maxW = page.w - page.ml - page.mr
                w = minOf(maxW, bmp.width * 0.75f)
                h = w * bmp.height / bmp.width
                bmp.recycle()
            } catch (t: Throwable) {
                runOnUiThread { showError("Picture", if (t is OutOfMemoryError) UserError("This picture is too large.") else t) }
            }
            val d = data ?: return@Thread
            runOnUiThread { js("insertImage(${q(d)}, $w, $h)") }
        }.start()
    }

    private fun pictureSize() {
        val opts = listOf(25, 50, 75, 90, 110, 125, 150, 200)
        askChoice("Picture size (tap the picture first)", opts.map { "$it %" }) { k ->
            js("resizeImage(${opts[k] / 100f})") { r -> if (r != "true") toast("Tap a picture first, then choose its size.") }
        }
    }

    private fun findReplace() {
        val find = EditText(this).apply { hint = "Find" }
        val repl = EditText(this).apply { hint = "Replace with" }
        val box = vbox(20).apply { addView(find, lp()); addView(repl, lp()) }
        val dlg = AlertDialog.Builder(this).setTitle("Find and replace").setView(box)
            .setPositiveButton("Replace all", null)
            .setNeutralButton("Find next", null)
            .setNegativeButton("Close", null).create()
        dlg.setOnShowListener {
            dlg.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                js("findNext(${q(find.text.toString())})") { r -> if (r != "true") toast("Not found.") }
            }
            dlg.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                js("replaceAll(${q(find.text.toString())}, ${q(repl.text.toString())})") { r -> toast("${r ?: 0} replaced.") }
            }
        }
        dlg.show()
    }

    private fun pageSetup() {
        val sizes = listOf("A4" to (595.3f to 841.9f), "Letter" to (612f to 792f), "Legal" to (612f to 1008f))
        val sizeGroup = RadioGroup(this)
        val short = minOf(page.w, page.h); val long = maxOf(page.w, page.h)
        for ((k, s) in sizes.withIndex()) sizeGroup.addView(RadioButton(this).apply {
            id = 100 + k; text = s.first
            isChecked = Math.abs(s.second.first - short) < 3 && Math.abs(s.second.second - long) < 3
        })
        if (sizeGroup.checkedRadioButtonId == -1) sizeGroup.check(100)
        val orient = RadioGroup(this).apply { orientation = RadioGroup.HORIZONTAL }
        orient.addView(RadioButton(this).apply { id = 200; text = "Portrait" })
        orient.addView(RadioButton(this).apply { id = 201; text = "Landscape" })
        orient.check(if (page.w > page.h) 201 else 200)
        fun cm(v: Float) = EditText(this).apply {
            setText(String.format(Locale.US, "%.2f", v / 72f * 2.54f))
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
        }
        val ml = cm(page.ml); val mt = cm(page.mt); val mr = cm(page.mr); val mb = cm(page.mb)
        val box = vbox(20).apply {
            addView(label("Paper", 13f, bold = true)); addView(sizeGroup)
            addView(label("Orientation", 13f, bold = true)); addView(orient)
            addView(label("Margins (cm): left, top, right, bottom", 13f, bold = true))
            val row = hbox()
            for (e in listOf(ml, mt, mr, mb)) row.addView(e, lp(0, -2, 1f))
            addView(row, lp())
        }
        AlertDialog.Builder(this).setTitle("Page setup").setView(android.widget.ScrollView(this).apply { addView(box) })
            .setPositiveButton("OK") { _, _ ->
                val s = sizes[(sizeGroup.checkedRadioButtonId - 100).coerceIn(0, 2)].second
                val land = orient.checkedRadioButtonId == 201
                fun v(e: EditText, d: Float) = (e.text.toString().replace(',', '.').toFloatOrNull()?.let { it / 2.54f * 72f } ?: d).coerceIn(0f, 200f)
                page = Docx.Page(if (land) s.second else s.first, if (land) s.first else s.second,
                    v(ml, page.ml), v(mt, page.mt), v(mr, page.mr), v(mb, page.mb))
                js(String.format(Locale.US, "setPage({w:%.2f,h:%.2f,ml:%.2f,mt:%.2f,mr:%.2f,mb:%.2f}); changed()",
                    page.w, page.h, page.ml, page.mt, page.mr, page.mb))
            }.setNegativeButton("Cancel", null).show()
    }

    // ================================================================ leaving
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (!modified || !loaded) { @Suppress("DEPRECATION") super.onBackPressed(); return }
        AlertDialog.Builder(this).setTitle(docName)
            .setMessage(if (docUri == null) "This document is not saved yet. Save it?" else "Save your changes?")
            .setPositiveButton("Save") { _, _ -> save { finish() } }
            .setNeutralButton("Don't save") { _, _ -> modified = false; finish() }
            .setNegativeButton("Cancel", null).show()
    }

    override fun onDestroy() {
        editFile?.delete()
        web.destroy()
        super.onDestroy()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) { if (requestCode == REQ_SAVE_AS) afterSave = null; return }
        when (requestCode) {
            REQ_SAVE_AS -> {
                Files.takePermission(this, uri, true)
                val then = afterSave
                afterSave = null
                writeDocx(uri, then)
            }
            REQ_IMAGE -> insertPicture(uri)
        }
    }

    companion object {
        const val EXTRA_HTML_FILE = "brb.word.html"
        const val EXTRA_TITLE = "brb.word.title"
        private const val REQ_SAVE_AS = 21
        private const val REQ_IMAGE = 22
        private const val M_SAVE = 1
        private const val M_SAVE_AS = 2
        private const val M_PDF = 3
        private const val M_SHARE = 4
        private const val M_FIND = 5
        private const val M_PAGE = 6
        private const val M_NEW = 7
        private const val M_HELP = 8

        fun isWordName(name: String) = name.lowercase(Locale.US).let { it.endsWith(".docx") || it.endsWith(".doc") }
    }
}
