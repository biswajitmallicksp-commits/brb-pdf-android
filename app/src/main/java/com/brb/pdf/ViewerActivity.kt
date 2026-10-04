package com.brb.pdf

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.print.PageRange
import android.print.PrintAttributes
import android.print.PrintDocumentAdapter
import android.print.PrintDocumentInfo
import android.print.PrintManager
import android.text.InputType
import android.view.Gravity
import android.view.KeyEvent
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import com.artifex.mupdf.fitz.PDFAnnotation
import com.artifex.mupdf.fitz.PDFDocument
import com.artifex.mupdf.fitz.PDFPage
import com.artifex.mupdf.fitz.Point
import com.artifex.mupdf.fitz.Rect
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import kotlin.math.floor
import kotlin.math.max

/**
 * The reading and editing screen.
 *
 * The document is opened from a private working copy; the original file is
 * never changed unless the user picks "Save (replace original)" and confirms.
 */
class ViewerActivity : Activity(), PageView.Listener {

    private var engine: PdfEngine? = null
    private var sourceUri: Uri? = null

    private lateinit var pv: PageView
    private lateinit var pageLabel: TextView
    private lateinit var hint: TextView
    private lateinit var searchBar: LinearLayout
    private lateinit var searchEdit: EditText
    private lateinit var searchInfo: TextView
    private lateinit var toolScroll: HorizontalScrollView
    private lateinit var toolRow: LinearLayout
    private lateinit var selBar: LinearLayout
    private lateinit var annotBar: LinearLayout
    private lateinit var annotTitle: TextView
    private lateinit var inkBar: LinearLayout
    private lateinit var loading: TextView

    private val toolChips = HashMap<PageView.Tool, TextView>()
    private var placeChip: TextView? = null
    private var undoChip: TextView? = null
    private var pictureChip: TextView? = null
    private var redoChip: TextView? = null
    private var annotating = false
    private var placeAction: ((Int, Point) -> Unit)? = null
    private var penColor = floatArrayOf(0.85f, 0.1f, 0.1f)
    private var markColor = floatArrayOf(1f, 0.85f, 0f)

    // ------------------------------------------------------------------ setup
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        val uri = intentUri(intent)
        if (uri == null) { toast("No PDF was given to open."); finish(); return }
        val shared = DocStore.engine
        if (shared != null && !shared.closed && DocStore.sourceUri == uri) attach(shared, uri)
        else openDocument(uri, null, null)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val uri = intentUri(intent) ?: return
        if (uri == sourceUri) return
        // another PDF: open it in a new screen so nothing unsaved is lost here
        startActivity(Intent(this, ViewerActivity::class.java).setData(uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_MULTIPLE_TASK or Intent.FLAG_ACTIVITY_NEW_DOCUMENT))
    }

    @Suppress("DEPRECATION")
    private fun intentUri(i: Intent): Uri? = i.data ?: (i.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))

    private fun buildUi() {
        pv = PageView(this).apply { listener = this@ViewerActivity }
        pageLabel = label("", 13f, color = Color.WHITE).apply {
            setPadding(dp(12), dp(5), dp(12), dp(5))
            background = android.graphics.drawable.GradientDrawable().apply {
                cornerRadius = dp(14).toFloat(); setColor(Color.argb(150, 0, 0, 0))
            }
            setOnClickListener { askGoTo() }
        }
        hint = label("", 13f, color = Color.WHITE).apply {
            setPadding(dp(12), dp(6), dp(12), dp(6)); gravity = Gravity.CENTER
            setBackgroundColor(Color.argb(200, 47, 111, 219)); visibility = View.GONE
        }
        loading = label("Opening...", 16f).apply { gravity = Gravity.CENTER }

        // search bar
        searchEdit = EditText(this).apply {
            hint = "Search text"; isSingleLine = true; imeOptions = EditorInfo.IME_ACTION_SEARCH
            inputType = InputType.TYPE_CLASS_TEXT
            setOnEditorActionListener { _, id, ev ->
                if (id == EditorInfo.IME_ACTION_SEARCH || ev?.keyCode == KeyEvent.KEYCODE_ENTER) { runSearch(); true } else false
            }
        }
        searchInfo = label("", 13f)
        searchBar = hbox().apply {
            setPadding(dp(8), 0, dp(4), 0)
            addView(searchEdit, lp(0, -2, 1f))
            addView(searchInfo)
            addView(smallButton("<") { stepHit(-1) })
            addView(smallButton(">") { stepHit(1) })
            addView(smallButton("X") { closeSearch() })
            visibility = View.GONE
            setBackgroundColor(if (isNight()) Color.rgb(40, 43, 48) else Color.rgb(245, 247, 250))
        }

        // tool strip
        toolRow = hbox().apply { setPadding(dp(6), dp(6), dp(6), dp(6)) }
        toolScroll = HorizontalScrollView(this).apply {
            addView(toolRow); isHorizontalScrollBarEnabled = false; visibility = View.GONE
            setBackgroundColor(if (isNight()) Color.rgb(40, 43, 48) else Color.rgb(245, 247, 250))
        }
        buildTools()

        selBar = barOf(
            "Copy" to { copySelection() }, "Highlight" to { markSelection(PDFAnnotation.TYPE_HIGHLIGHT) },
            "Underline" to { markSelection(PDFAnnotation.TYPE_UNDERLINE) },
            "Strike" to { markSelection(PDFAnnotation.TYPE_STRIKE_OUT) },
            "Mark for redaction" to { redactSelection() }, "Close" to { clearSelection() })
        annotTitle = label("", 14f, bold = true).apply { setPadding(dp(8), 0, dp(8), 0) }
        annotBar = barOf("Edit text" to { editAnnotText() }, "Colour" to { recolorAnnot() },
            "Delete" to { deleteAnnot() }, "Done" to { onAnnotTapped(null) })
        (annotBar.tag as LinearLayout).addView(annotTitle, 0)
        inkBar = barOf("Undo stroke" to { pv.undoInkStroke() }, "Save drawing" to { finishInk() },
            "Cancel" to { pv.takeInk(); setTool(PageView.Tool.INK) })

        val bottom = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(selBar); addView(annotBar); addView(inkBar); addView(toolScroll)
        }
        val frame = FrameLayout(this).apply {
            addView(loading, FrameLayout.LayoutParams(-1, -1))
            addView(pv, FrameLayout.LayoutParams(-1, -1))
            addView(hint, FrameLayout.LayoutParams(-1, -2, Gravity.TOP))
            addView(pageLabel, FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL).apply {
                bottomMargin = dp(14)
            })
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(searchBar, lp())
            addView(frame, lp(-1, 0, 1f))
            addView(bottom, lp())
        }
        setContentView(root)
        pv.visibility = View.INVISIBLE
        pageLabel.visibility = View.GONE
        pv.nightMode = Store.get(this, "night", "0") == "1"
    }

    private fun smallButton(text: String, action: () -> Unit) = TextView(this).apply {
        this.text = text; textSize = 16f; gravity = Gravity.CENTER
        setPadding(dp(12), dp(10), dp(12), dp(10)); setOnClickListener { action() }
    }

    /** A bar of chips inside a horizontal scroll. The chip row is kept in `tag`. */
    private fun barOf(vararg items: Pair<String, () -> Unit>): LinearLayout {
        val row = hbox().apply { setPadding(dp(6), dp(6), dp(6), dp(6)) }
        for ((name, action) in items) {
            row.addView(chip(name) { action() }, lp(-2, -2).apply { marginEnd = dp(6) })
        }
        val sc = HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(row) }
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(sc)
            tag = row
            visibility = View.GONE
            setBackgroundColor(if (isNight()) Color.rgb(33, 36, 41) else Color.rgb(236, 240, 246))
        }
    }

    private fun buildTools() {
        fun add(name: String, action: (TextView) -> Unit): TextView {
            val c = chip(name) { action(it as TextView) }
            toolRow.addView(c, lp(-2, -2).apply { marginEnd = dp(6) })
            return c
        }
        undoChip = add("Undo") { undo() }
        redoChip = add("Redo") { redo() }
        for ((name, tool) in listOf("Select text" to PageView.Tool.SELECT, "Highlight" to PageView.Tool.HIGHLIGHT,
            "Underline" to PageView.Tool.UNDERLINE, "Strike" to PageView.Tool.STRIKE)) {
            toolChips[tool] = add(name) { setTool(if (pv.tool == tool) PageView.Tool.PAN else tool) }
        }
        add("Note") { startPlace(it, "Tap where the note should go") { p, at -> askNote(p, at) } }
        add("Text") { startPlace(it, "Tap where the text should start") { p, at -> askTextBox(p, at) } }
        add("Stamp") { chooseStamp(it) }
        add("Sign") { chooseSignature(it) }
        pictureChip = add("Picture") { pickPicture() }
        for ((name, tool) in listOf("Rectangle" to PageView.Tool.RECT, "Ellipse" to PageView.Tool.ELLIPSE,
            "Line" to PageView.Tool.LINE, "Arrow" to PageView.Tool.ARROW, "Draw" to PageView.Tool.INK,
            "Redact area" to PageView.Tool.REDACT)) {
            toolChips[tool] = add(name) { setTool(if (pv.tool == tool) PageView.Tool.PAN else tool) }
        }
        add("Pen colour") { askColor("Pen colour") { c -> penColor = c; pv.drawColor = c } }
        add("Highlight colour") { askColor("Highlight colour") { c -> markColor = c } }
        add("Close tools") { toggleAnnotate(false) }
    }

    // ------------------------------------------------------------ opening
    private fun openDocument(uri: Uri, password: String?, work: File?) {
        Thread {
            var copy = work
            try {
                val name = Files.displayName(this, uri)
                if (copy == null) copy = Files.copyToWork(this, uri, name)
                val eng = PdfEngine.open(copy, name, password)
                runOnUiThread { if (alive()) attach(eng, uri) else eng.close() }
            } catch (e: PdfEngine.PasswordNeeded) {
                runOnUiThread { askPassword(uri, copy, e.wrong) }
            } catch (e: Throwable) {
                runOnUiThread {
                    if (!alive()) return@runOnUiThread
                    showError("Could not open the PDF", e)
                    loading.text = "This file could not be opened."
                }
            }
        }.start()
    }

    private fun askPassword(uri: Uri, work: File?, wrong: Boolean) {
        if (!alive()) return
        val edit = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val box = vbox(20).apply {
            addView(label(if (wrong) "That password is not correct. Try again." else
                "This PDF is protected. Enter its password to open it.", 14f))
            addView(edit)
        }
        AlertDialog.Builder(this).setTitle("Password").setView(box).setCancelable(false)
            .setPositiveButton("Open") { _, _ -> openDocument(uri, edit.text.toString(), work) }
            .setNegativeButton("Cancel") { _, _ -> finish() }.show()
    }

    private fun attach(eng: PdfEngine, uri: Uri) {
        engine = eng
        sourceUri = uri
        shownRevision = eng.revision
        DocStore.engine = eng
        DocStore.sourceUri = uri
        title = eng.displayName
        actionBar?.subtitle = "${eng.pageCount} pages"
        pv.engine = eng
        pv.drawColor = penColor
        pv.visibility = View.VISIBLE
        loading.visibility = View.GONE
        pageLabel.visibility = View.VISIBLE
        val last = Store.lastPage(this, uri)
        Store.addRecent(this, uri, eng.displayName)
        if (last in 1 until eng.pageCount) pv.goToPage(last)
        onPageChanged(pv.currentPage)
        refreshTitle()
        if (!eng.canAnnotate || !eng.canModify) {
            info("Restricted document", "The owner of this PDF has limited what may be changed in it. " +
                "Tools that are not allowed are switched off. (BRB PDF does not get around these limits.)")
        }
        // gentle tip for scanned documents
        eng.async({ eng.pageNeedsOcr(minOf(pv.currentPage, eng.pageCount - 1)) }) { scanned, _ ->
            if (scanned == true && alive()) showHint("This page looks scanned. Use menu > OCR to make the text searchable.", 5000)
        }
    }

    override fun onResume() {
        super.onResume()
        val eng = engine ?: return
        // the Pages screen may have changed the document
        if (eng.revision != shownRevision) { pv.refresh(true); shownRevision = eng.revision; refreshTitle() }
        if (DocStore.gotoPage >= 0) { pv.goToPage(DocStore.gotoPage); DocStore.gotoPage = -1 }
    }

    private var shownRevision = -1

    override fun onPause() {
        super.onPause()
        val eng = engine ?: return
        shownRevision = eng.revision
        sourceUri?.let { Store.setLastPage(this, it, pv.currentPage) }
    }

    override fun onDestroy() {
        super.onDestroy()
        val eng = engine
        if (eng != null && isFinishing) {
            if (DocStore.engine === eng) { DocStore.engine = null; DocStore.sourceUri = null }
            pv.release()
            eng.close()
            eng.file.delete()
        }
    }

    @Deprecated("Deprecated in Java")
    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        when {
            searchBar.visibility == View.VISIBLE -> closeSearch()
            pv.selectedAnnot != null -> onAnnotTapped(null)
            pv.selection != null -> clearSelection()
            pv.tool != PageView.Tool.PAN -> setTool(PageView.Tool.PAN)
            annotating -> toggleAnnotate(false)
            engine?.dirty == true -> askUnsaved { super.onBackPressed() }
            else -> super.onBackPressed()
        }
    }

    private fun askUnsaved(leave: () -> Unit) {
        AlertDialog.Builder(this).setTitle("Unsaved changes")
            .setMessage("You have changes that are not saved. The original file has not been changed.")
            .setPositiveButton("Save a copy") { _, _ -> saveCopy() }
            .setNegativeButton("Discard changes") { _, _ -> leave() }
            .setNeutralButton("Cancel", null).show()
    }

    private fun refreshTitle() {
        val eng = engine ?: return
        title = (if (eng.dirty) "* " else "") + eng.displayName
        actionBar?.subtitle = "${eng.pageCount} pages"
        undoChip?.alpha = if (eng.undoLabel != null) 1f else 0.4f
        redoChip?.alpha = if (eng.redoLabel != null) 1f else 0.4f
        invalidateOptionsMenu()
    }

    private fun showHint(text: String, millis: Long = 0) {
        hint.text = text
        hint.visibility = View.VISIBLE
        hint.removeCallbacks(hideHint)
        if (millis > 0) hint.postDelayed(hideHint, millis)
    }

    private val hideHint = Runnable { hint.visibility = View.GONE }

    // ---------------------------------------------------------------- menu
    private object M {
        const val SEARCH = 1; const val EDIT = 2; const val UNDO = 3; const val REDO = 4; const val PAGES = 5
        const val OCR = 6; const val COPY_TEXT = 7; const val SAVE_COPY = 8; const val SAVE_OVER = 9; const val SHARE = 10
        const val PRINT = 11; const val PASSWORD = 12; const val REDACT = 13; const val OUTLINE = 14; const val GOTO = 15
        const val NIGHT = 16; const val INFO = 17; const val ZOOM_FIT = 18
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, M.SEARCH, 0, "Search").setIcon(android.R.drawable.ic_menu_search)
            .setShowAsAction(MenuItem.SHOW_AS_ACTION_ALWAYS)
        menu.add(0, M.EDIT, 1, "Annotate").setIcon(android.R.drawable.ic_menu_edit)
            .setShowAsAction(MenuItem.SHOW_AS_ACTION_ALWAYS)
        menu.add(0, M.UNDO, 2, "Undo")
        menu.add(0, M.REDO, 3, "Redo")
        menu.add(0, M.PAGES, 4, "Pages (rotate, delete, move, split...)")
        menu.add(0, M.OCR, 5, "OCR - make scanned text searchable")
        menu.add(0, M.COPY_TEXT, 6, "Copy text of this page")
        menu.add(0, M.SAVE_COPY, 7, "Save a copy...")
        menu.add(0, M.SAVE_OVER, 8, "Save (replace original)")
        menu.add(0, M.SHARE, 9, "Share")
        menu.add(0, M.PRINT, 10, "Print")
        menu.add(0, M.PASSWORD, 11, "Password protect...")
        menu.add(0, M.REDACT, 12, "Apply redactions...")
        menu.add(0, M.OUTLINE, 13, "Bookmarks")
        menu.add(0, M.GOTO, 14, "Go to page...")
        menu.add(0, M.ZOOM_FIT, 15, "Fit page width")
        menu.add(0, M.NIGHT, 16, "Night reading").setCheckable(true)
        menu.add(0, M.INFO, 17, "Document info")
        return true
    }

    override fun onPrepareOptionsMenu(menu: Menu): Boolean {
        val eng = engine
        val open = eng != null
        for (i in 0 until menu.size()) menu.getItem(i).isEnabled = open
        if (eng != null) {
            menu.findItem(M.UNDO).apply { isEnabled = eng.undoLabel != null; title = eng.undoLabel?.let { "Undo: $it" } ?: "Undo" }
            menu.findItem(M.REDO).apply { isEnabled = eng.redoLabel != null; title = eng.redoLabel?.let { "Redo: $it" } ?: "Redo" }
            menu.findItem(M.EDIT).isEnabled = eng.canAnnotate
            menu.findItem(M.OCR).isEnabled = eng.canModify
            menu.findItem(M.PRINT).isEnabled = eng.canPrint
            menu.findItem(M.COPY_TEXT).isEnabled = eng.canCopy
            menu.findItem(M.PASSWORD).isEnabled = eng.canModify
            menu.findItem(M.SAVE_OVER).isEnabled = eng.dirty
            menu.findItem(M.PASSWORD).title = if (eng.password.isNullOrEmpty()) "Password protect..." else "Change / remove password..."
        }
        menu.findItem(M.NIGHT).isChecked = pv.nightMode
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            M.SEARCH -> openSearch()
            M.EDIT -> toggleAnnotate(!annotating)
            M.UNDO -> undo()
            M.REDO -> redo()
            M.PAGES -> engine?.let {
                if (!it.canAssemble) info("Not allowed", "The owner of this PDF does not allow changing its pages.")
                else startActivity(Intent(this, OrganizeActivity::class.java))
            }
            M.OCR -> startOcr()
            M.COPY_TEXT -> copyPageText()
            M.SAVE_COPY -> saveCopy()
            M.SAVE_OVER -> saveOver()
            M.SHARE -> share()
            M.PRINT -> print()
            M.PASSWORD -> passwordMenu()
            M.REDACT -> applyRedactions()
            M.OUTLINE -> showOutline()
            M.GOTO -> askGoTo()
            M.ZOOM_FIT -> pv.setZoom(1f)
            M.NIGHT -> { pv.nightMode = !pv.nightMode; Store.put(this, "night", if (pv.nightMode) "1" else "0") }
            M.INFO -> showInfo()
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }

    // ------------------------------------------------------------- editing
    /** Run one undoable change, then refresh the screen. */
    private fun edit(label: String, structure: Boolean = false, block: (PDFDocument, PdfEngine) -> Unit,
                     after: (() -> Unit)? = null) {
        val eng = engine ?: return
        if (!eng.canAnnotate) { info("Not allowed", "The owner of this PDF does not allow adding comments."); return }
        eng.edit(label, structure, { pdf -> block(pdf, eng) }) { _, err ->
            if (!alive()) return@edit
            if (err != null) { showError("Could not ${label.lowercase()}", err); return@edit }
            pv.refresh(structure)
            shownRevision = eng.revision
            refreshTitle()
            after?.invoke()
        }
    }

    private fun page(eng: PdfEngine, i: Int): PDFPage = eng.pageOnEngine(i)

    private fun undo() {
        val eng = engine ?: return
        pv.selectedAnnot = null; hideBars()
        eng.undo { label ->
            if (label == null) { toast("Nothing to undo."); return@undo }
            pv.refresh(true); shownRevision = eng.revision; refreshTitle()
            toast("Undone: $label")
        }
    }

    private fun redo() {
        val eng = engine ?: return
        pv.selectedAnnot = null; hideBars()
        eng.redo { label ->
            if (label == null) { toast("Nothing to redo."); return@redo }
            pv.refresh(true); shownRevision = eng.revision; refreshTitle()
            toast("Redone: $label")
        }
    }

    private fun toggleAnnotate(on: Boolean) {
        val eng = engine ?: return
        if (on && !eng.canAnnotate) { info("Not allowed", "The owner of this PDF does not allow adding comments."); return }
        annotating = on
        toolScroll.visibility = if (on) View.VISIBLE else View.GONE
        if (!on) setTool(PageView.Tool.PAN)
        refreshTitle()
    }

    private fun setTool(tool: PageView.Tool) {
        pv.tool = tool
        placeAction = null
        placeChip?.setChipSelected(false); placeChip = null
        for ((t, c) in toolChips) c.setChipSelected(t == tool)
        pv.drawColor = penColor
        inkBar.visibility = View.GONE
        clearSelection()
        when (tool) {
            PageView.Tool.PAN -> hint.visibility = View.GONE
            PageView.Tool.SELECT -> showHint("Drag over text to select it. Two fingers scroll.")
            PageView.Tool.HIGHLIGHT, PageView.Tool.UNDERLINE, PageView.Tool.STRIKE ->
                showHint("Drag over the words. Two fingers scroll.")
            PageView.Tool.RECT, PageView.Tool.ELLIPSE -> showHint("Drag to draw. Two fingers scroll.")
            PageView.Tool.LINE, PageView.Tool.ARROW -> showHint("Drag from start to end. Two fingers scroll.")
            PageView.Tool.INK -> { showHint("Draw with one finger. Two fingers scroll."); inkBar.visibility = View.VISIBLE }
            PageView.Tool.REDACT -> showHint("Drag over what must be removed. It is removed only when you choose " +
                "menu > Apply redactions.")
            PageView.Tool.PLACE -> {}
        }
    }

    private fun startPlace(chip: TextView, message: String, action: (Int, Point) -> Unit) {
        setTool(PageView.Tool.PLACE)
        placeAction = action
        placeChip = chip
        chip.setChipSelected(true)
        showHint(message)
    }

    private fun hideBars() {
        selBar.visibility = View.GONE
        annotBar.visibility = View.GONE
    }

    // ---------------------------------------------------- PageView events
    override fun onPageChanged(page: Int) {
        val n = engine?.pageCount ?: 0
        pageLabel.text = "${page + 1} / $n"
    }

    override fun onTapEmpty() {
        if (annotating) return
        if (actionBar?.isShowing == true) actionBar?.hide() else actionBar?.show()
    }

    override fun onSelection(sel: PdfEngine.Selection?, finished: Boolean) {
        if (!finished) return
        when (pv.tool) {
            PageView.Tool.HIGHLIGHT -> sel?.let { applyMarkup(PDFAnnotation.TYPE_HIGHLIGHT, it) }
            PageView.Tool.UNDERLINE -> sel?.let { applyMarkup(PDFAnnotation.TYPE_UNDERLINE, it) }
            PageView.Tool.STRIKE -> sel?.let { applyMarkup(PDFAnnotation.TYPE_STRIKE_OUT, it) }
            else -> {
                annotBar.visibility = View.GONE
                selBar.visibility = if (sel != null) View.VISIBLE else View.GONE
                if (sel != null && sel.text.isEmpty()) toast("No text here. If this is a scanned page, run OCR first.")
            }
        }
    }

    override fun onPlace(page: Int, at: Point) {
        val action = placeAction ?: return
        setTool(PageView.Tool.PAN)
        action(page, at)
    }

    override fun onRect(page: Int, rect: Rect) {
        val color = penColor
        when (pv.tool) {
            PageView.Tool.RECT -> edit("Add rectangle", block = { _, e -> Annots.shape(page(e, page), PDFAnnotation.TYPE_SQUARE, rect, color, 2f, null) })
            PageView.Tool.ELLIPSE -> edit("Add ellipse", block = { _, e -> Annots.shape(page(e, page), PDFAnnotation.TYPE_CIRCLE, rect, color, 2f, null) })
            PageView.Tool.REDACT -> edit("Mark for redaction", block = { _, e -> Annots.redactMark(page(e, page), rect) }) {
                showHint("Marked. Choose menu > Apply redactions to remove it for good.", 4000)
            }
            else -> {}
        }
    }

    override fun onLine(page: Int, a: Point, b: Point) {
        val arrow = pv.tool == PageView.Tool.ARROW
        val color = penColor
        edit(if (arrow) "Add arrow" else "Add line", block = { _, e -> Annots.line(page(e, page), a, b, color, 2f, arrow) })
    }

    override fun onInkChanged(strokes: Int) {}

    private fun finishInk() {
        val (page, strokes) = pv.takeInk() ?: run { toast("Draw something first."); return }
        val color = penColor
        edit("Add drawing", block = { _, e -> Annots.ink(page(e, page), strokes, color, 2f) })
    }

    override fun onAnnotTapped(info: PdfEngine.AnnotInfo?) {
        pv.selectedAnnot = info
        if (info == null) { annotBar.visibility = View.GONE; return }
        selBar.visibility = View.GONE
        annotTitle.text = info.label + if (info.contents.isNotBlank()) ": " + info.contents.take(30) else ""
        val row = annotBar.tag as LinearLayout
        row.getChildAt(1).visibility = if (info.hasText) View.VISIBLE else View.GONE
        annotBar.visibility = View.VISIBLE
        if (info.type == PDFAnnotation.TYPE_REDACT) showHint("Redaction mark - not removed until menu > Apply redactions.", 4000)
        else if (info.movable) showHint(if (info.resizable) "Drag to move. Drag the round handle to resize." else "Drag to move.", 3000)
    }

    override fun onAnnotMoved(info: PdfEngine.AnnotInfo, dx: Float, dy: Float) {
        edit("Move ${info.label.lowercase()}", block = { _, e -> Annots.move(e.annotOnEngine(info.page, info.id), dx, dy) }) {
            reselect(info)
        }
    }

    override fun onAnnotResized(info: PdfEngine.AnnotInfo, rect: Rect) {
        edit("Resize ${info.label.lowercase()}", block = { _, e -> Annots.resize(e.annotOnEngine(info.page, info.id), rect) }) {
            reselect(info)
        }
    }

    private fun reselect(info: PdfEngine.AnnotInfo) {
        val eng = engine ?: return
        eng.async({ eng.annotations(info.page).firstOrNull { it.id == info.id } }) { a, _ ->
            pv.selectedAnnot = a
            if (a == null) annotBar.visibility = View.GONE
        }
    }

    override fun onLink(hit: PdfEngine.LinkHit) {
        if (hit.page >= 0) { pv.goToPage(hit.page); return }
        val uri = hit.uri ?: return
        confirm("Open link?", "This opens the link in another app:\n\n$uri", "Open") {
            try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(uri))) } catch (e: Exception) { toast("No app can open this link.") }
        }
    }

    // ------------------------------------------------- selection actions
    private fun clearSelection() {
        pv.selection = null
        selBar.visibility = View.GONE
    }

    private fun copySelection() {
        val sel = pv.selection ?: return
        if (engine?.canCopy == false) { info("Not allowed", "The owner of this PDF does not allow copying text."); return }
        copyToClipboard(sel.text)
        clearSelection()
    }

    private fun copyToClipboard(text: String) {
        if (text.isBlank()) { toast("No text found."); return }
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("PDF text", text))
        toast("Copied ${text.length} characters.")
    }

    private fun markSelection(type: Int) {
        val sel = pv.selection ?: return
        applyMarkup(type, sel)
    }

    private fun applyMarkup(type: Int, sel: PdfEngine.Selection) {
        val color = if (type == PDFAnnotation.TYPE_HIGHLIGHT) markColor else penColor
        val opacity = if (type == PDFAnnotation.TYPE_HIGHLIGHT) 0.5f else 1f
        val name = when (type) { PDFAnnotation.TYPE_HIGHLIGHT -> "Highlight"; PDFAnnotation.TYPE_UNDERLINE -> "Underline"; else -> "Strikethrough" }
        edit("Add ${name.lowercase()}", block = { _, e -> Annots.markup(page(e, sel.page), type, sel.quads, color, opacity) }) {
            clearSelection()
        }
    }

    private fun redactSelection() {
        val sel = pv.selection ?: return
        edit("Mark for redaction", block = { _, e ->
            val pg = page(e, sel.page)
            // one mark per line of text
            for (q in sel.quads) {
                val r = Rect(q)
                if (r.x1 - r.x0 >= 2 && r.y1 - r.y0 >= 2) Annots.redactMark(pg, r)
            }
        }) {
            clearSelection()
            showHint("Marked. Choose menu > Apply redactions to remove it for good.", 4000)
        }
    }

    // --------------------------------------------------- comment actions
    private fun editAnnotText() {
        val a = pv.selectedAnnot ?: return
        askText(if (a.type == PDFAnnotation.TYPE_TEXT) "Note" else "Text", a.contents, multiLine = true) { text ->
            if (a.type == PDFAnnotation.TYPE_FREE_TEXT && SignaturePad.needsPicture(text)) {
                info("Bengali / Hindi text", "Text boxes in Bengali or Hindi are added as pictures. Delete this box and use " +
                    "the Text tool again to add it.")
                return@askText
            }
            edit("Edit text", block = { _, e -> Annots.setText(e.annotOnEngine(a.page, a.id), text) }) { reselect(a) }
        }
    }

    private fun recolorAnnot() {
        val a = pv.selectedAnnot ?: return
        askColor { c -> edit("Change colour", block = { _, e -> Annots.recolor(e.annotOnEngine(a.page, a.id), c) }) { reselect(a) } }
    }

    private fun deleteAnnot() {
        val a = pv.selectedAnnot ?: return
        edit("Delete ${a.label.lowercase()}", block = { _, e ->
            page(e, a.page).deleteAnnotation(e.annotOnEngine(a.page, a.id))
        }) {
            pv.selectedAnnot = null
            annotBar.visibility = View.GONE
        }
    }

    // ------------------------------------------------------- adding things
    private fun askNote(page: Int, at: Point) {
        askText("Note", multiLine = true) { text ->
            if (text.isBlank()) return@askText
            val color = markColor
            edit("Add note", block = { _, e -> Annots.note(page(e, page), at, text, color) })
        }
    }

    private fun askTextBox(page: Int, at: Point) {
        val sizes = listOf(9f, 11f, 12f, 14f, 18f, 24f)
        askText("Text (English, Bengali or Hindi)", multiLine = true) { text ->
            if (text.isBlank()) return@askText
            askChoice("Text size", sizes.map { "${it.toInt()} pt" }) { k ->
                val size = sizes[k]
                val color = penColor
                val pageW = engine?.sizes?.getOrNull(page)?.let { it.x0 + it.w } ?: 595f
                if (SignaturePad.needsPicture(text)) {
                    // the standard PDF fonts have no Bengali/Hindi letters: draw it with the phone's fonts
                    val bmp = SignaturePad.textPicture(text, size, color.toArgb(), max(60f, pageW - at.x - 10f))
                    val rect = Rect(at.x, at.y, at.x + bmp.width / 4f, at.y + bmp.height / 4f)
                    edit("Add text", block = { _, e -> Annots.imageStamp(page(e, page), rect, bmp, "Text") })
                } else {
                    val lines = text.lines()
                    val w = (lines.maxOf { it.length } * size * 0.55f + 10f).coerceAtMost(max(60f, pageW - at.x - 10f))
                    val wrapped = lines.sumOf { maxOf(1, Math.ceil((it.length * size * 0.55 / (w - 10f))).toInt()) }
                    val rect = Rect(at.x, at.y, at.x + w, at.y + wrapped * size * 1.25f + 6f)
                    edit("Add text", block = { _, e -> Annots.textBox(page(e, page), rect, text, size, color, false) })
                }
            }
        }
    }

    private fun chooseStamp(chip: TextView) {
        val names = Annots.OFFICE_STAMPS + listOf("Custom text...")
        askChoice("Stamp", names) { k ->
            fun place(name: String) {
                askChoice("Add today's date?", listOf("Yes, with date", "No date")) { d ->
                    startPlace(chip, "Tap where the stamp should go") { p, at ->
                        val color = floatArrayOf(0.8f, 0.05f, 0.05f)
                        if (SignaturePad.needsPicture(name)) {
                            val text = if (d == 0) name + "\n" + java.text.SimpleDateFormat("dd-MM-yyyy", java.util.Locale.US).format(java.util.Date()) else name
                            val bmp = SignaturePad.textPicture(text, 16f, color.toArgb(), 300f)
                            edit("Add stamp", block = { _, e ->
                                Annots.imageStamp(page(e, p), Rect(at.x, at.y, at.x + bmp.width / 4f, at.y + bmp.height / 4f), bmp, "Stamp")
                            })
                        } else edit("Add stamp", block = { _, e -> Annots.officeStamp(page(e, p), at, name, d == 0, color) })
                    }
                }
            }
            if (k < Annots.OFFICE_STAMPS.size) place(Annots.OFFICE_STAMPS[k])
            else askText("Stamp text") { t -> if (t.isNotBlank()) place(t.trim().uppercase()) }
        }
    }

    private fun chooseSignature(chip: TextView) {
        SignaturePad.ask(this) { bmp ->
            startPlace(chip, "Tap where the signature should go (picture of a signature, not a digital signature)") { p, at ->
                val w = 150f
                val h = w * bmp.height / max(1, bmp.width)
                edit("Add signature picture", block = { _, e ->
                    Annots.imageStamp(page(e, p), Rect(at.x, at.y, at.x + w, at.y + h), bmp, "Signature (image)")
                })
            }
        }
    }

    private fun pickPicture() {
        val i = Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/*")
        try { startActivityForResult(i, REQ_IMAGE) } catch (e: Exception) { toast("No app to pick a picture.") }
    }

    private fun placePicture(uri: Uri) {
        val bmp = try { decodeScaled(uri, 2000) } catch (e: Exception) { null }
        if (bmp == null) { toast("That picture could not be read."); return }
        val chip = pictureChip ?: return
        startPlace(chip, "Tap where the picture should go") { p, at ->
            val w = 200f
            val h = w * bmp.height / max(1, bmp.width)
            edit("Add picture", block = { _, e -> Annots.imageStamp(page(e, p), Rect(at.x, at.y, at.x + w, at.y + h), bmp, "Image") })
        }
    }

    private fun decodeScaled(uri: Uri, maxSide: Int): Bitmap? {
        val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
        var sample = 1
        while (max(opts.outWidth, opts.outHeight) / sample > maxSide) sample *= 2
        val real = BitmapFactory.Options().apply { inSampleSize = sample }
        return contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, real) }
    }

    // ------------------------------------------------------------- search
    private var hits = ArrayList<Pair<Int, Rect>>()
    private var searchToken = 0

    private fun openSearch() {
        searchBar.visibility = View.VISIBLE
        searchEdit.requestFocus()
        (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(searchEdit, 0)
    }

    private fun closeSearch() {
        searchToken++
        searchBar.visibility = View.GONE
        hits = ArrayList(); pv.searchHits = hits; pv.currentHit = -1
        (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(searchEdit.windowToken, 0)
    }

    private fun runSearch() {
        val eng = engine ?: return
        val q = searchEdit.text.toString().trim()
        if (q.isEmpty()) return
        (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(searchEdit.windowToken, 0)
        val token = ++searchToken
        hits = ArrayList(); pv.searchHits = hits; pv.currentHit = -1
        searchInfo.text = "..."
        val start = pv.currentPage
        val n = eng.pageCount
        fun step(k: Int) {
            if (k >= n || token != searchToken) {
                if (token == searchToken) {
                    searchInfo.text = if (hits.isEmpty()) "0" else "${pv.currentHit + 1}/${hits.size}"
                    if (hits.isEmpty()) toast("Not found. Scanned pages need OCR before they can be searched.")
                }
                return
            }
            val i = (start + k) % n
            eng.async({ eng.search(i, q) }) { found, _ ->
                if (token != searchToken) return@async
                if (!found.isNullOrEmpty()) {
                    hits.addAll(found.map { i to it })
                    pv.searchHits = ArrayList(hits)
                    if (pv.currentHit < 0) { pv.currentHit = 0; pv.showRect(i, found[0]) }
                }
                searchInfo.text = if (hits.isEmpty()) "p${i + 1}" else "${pv.currentHit + 1}/${hits.size}"
                step(k + 1)
            }
        }
        step(0)
    }

    private fun stepHit(d: Int) {
        if (hits.isEmpty()) { runSearch(); return }
        val k = ((pv.currentHit + d) % hits.size + hits.size) % hits.size
        pv.currentHit = k
        pv.showRect(hits[k].first, hits[k].second)
        searchInfo.text = "${k + 1}/${hits.size}"
    }

    // ------------------------------------------------------------ navigation
    private fun askGoTo() {
        val n = engine?.pageCount ?: return
        askText("Go to page (1-$n)", number = true) { t ->
            val p = t.trim().toIntOrNull()
            if (p == null || p < 1 || p > n) toast("Enter a number from 1 to $n.") else pv.goToPage(p - 1)
        }
    }

    private fun showOutline() {
        val eng = engine ?: return
        eng.async({ eng.outline() }) { items, _ ->
            if (items.isNullOrEmpty()) { info("Bookmarks", "This PDF has no bookmarks."); return@async }
            askChoice("Bookmarks", items.map { "    ".repeat(it.first) + it.second + if (it.third >= 0) "  (${it.third + 1})" else "" }) { k ->
                val p = items[k].third
                if (p >= 0) pv.goToPage(p)
            }
        }
    }

    private fun showInfo() {
        val eng = engine ?: return
        eng.async({ eng.info() }) { rows, _ ->
            val perms = listOf("Printing" to eng.canPrint, "Copying text" to eng.canCopy,
                "Comments" to eng.canAnnotate, "Changes" to eng.canModify)
                .joinToString("\n") { "${it.first}: " + if (it.second) "allowed" else "not allowed" }
            info("Document info", (rows ?: emptyList()).joinToString("\n") { "${it.first}: ${it.second}" } + "\n\n" + perms)
        }
    }

    private fun copyPageText() {
        val eng = engine ?: return
        val p = pv.currentPage
        eng.async({ eng.pageText(p) }) { text, _ ->
            if (text.isNullOrBlank()) info("No text", "Page ${p + 1} has no text. If it is a scanned page, run OCR first.")
            else copyToClipboard(text)
        }
    }

    // ----------------------------------------------------------------- OCR
    private fun startOcr() {
        val eng = engine ?: return
        if (!eng.canModify) { info("Not allowed", "The owner of this PDF does not allow changes."); return }
        val installed = Ocr.installedLanguages(this)
        if (installed.isEmpty()) {
            info("OCR languages missing", "The OCR language files were not included when this app was built.\n\n" +
                "On the PC, copy eng.traineddata, ben.traineddata and hin.traineddata into\n" +
                "app/src/main/assets/tessdata\nof the Android project and build the app again (see README).")
            return
        }
        val names = installed.map { code -> Ocr.LANGUAGES.first { it.first == code }.second }
        val remembered = Store.get(this, "ocr_langs", "eng,ben,hin").split(',')
        val checked = BooleanArray(installed.size) { installed[it] in remembered }
        if (checked.none { it }) checked[0] = true
        askChecks("Languages in this document", names, checked) { chosen ->
            val langs = installed.filterIndexed { k, _ -> chosen[k] }
            if (langs.isEmpty()) { toast("Choose at least one language."); return@askChecks }
            Store.put(this, "ocr_langs", langs.joinToString(","))
            val wait = Progress(this, "OCR")
            wait.message("Looking for scanned pages...")
            eng.async({ eng.scannedPages() }) { scanned, _ ->
                wait.close()
                val s = scanned ?: emptyList()
                val options = ArrayList<Pair<String, () -> List<Int>?>>()
                if (s.isNotEmpty()) options.add("Scanned pages only (${describePages(s)})" to { s })
                options.add("This page (${pv.currentPage + 1})" to { listOf(pv.currentPage) })
                options.add("All pages (1-${eng.pageCount})" to { (0 until eng.pageCount).toList() })
                options.add("Choose pages..." to { null })
                askChoice("Which pages?", options.map { it.first }) { k ->
                    val pages = options[k].second()
                    if (pages != null) confirmOcr(pages, langs, s)
                    else askText("Pages to read", hint = "e.g. 1-3, 7") { t ->
                        try { confirmOcr(parsePageRange(t, eng.pageCount), langs, s) } catch (e: UserError) { showError("Pages", e) }
                    }
                }
            }
        }
    }

    private fun confirmOcr(pages: List<Int>, langs: List<String>, scanned: List<Int>) {
        val withText = pages.filter { it !in scanned }
        if (withText.isNotEmpty() && pages.size <= 50) {
            confirm("Pages already have text", "Pages ${describePages(withText)} already contain text. Reading them again " +
                "adds a second hidden text layer. Continue?", "Continue") { runOcr(pages, langs) }
        } else runOcr(pages, langs)
    }

    private fun runOcr(pages: List<Int>, langs: List<String>) {
        val eng = engine ?: return
        val stopFlag = java.util.concurrent.atomic.AtomicBoolean(false)
        val sessionRef = java.util.concurrent.atomic.AtomicReference<Ocr.Session?>(null)
        val prog = Progress(this, "OCR", cancellable = true) { stopFlag.set(true); sessionRef.get()?.stop() }
        Thread {
            val results = ArrayList<Pair<Int, List<TextLayer.Word>>>()
            var error: Throwable? = null
            try {
                val dir = Ocr.prepare(this, langs) { m -> runOnUiThread { prog.message(m) } }
                val s = Ocr.Session(dir, langs)
                sessionRef.set(s)
                try {
                    for ((k, i) in pages.withIndex()) {
                        if (stopFlag.get()) break
                        runOnUiThread { prog.update(k, pages.size, "Reading page ${i + 1} (${k + 1} of ${pages.size})...") }
                        val size = eng.sizes[i]
                        var scale = 300f / 72f
                        val longest = max(size.w, size.h)
                        if (longest * scale > 3600f) scale = 3600f / longest
                        val bmp = eng.render(i, scale)
                        val x0 = floor(size.x0 * scale) / scale
                        val y0 = floor(size.y0 * scale) / scale
                        val words = try { s.recognize(bmp, scale, x0, y0) } finally { bmp.recycle() }
                        if (!stopFlag.get()) results.add(i to words)
                    }
                } finally {
                    s.close()
                }
            } catch (t: Throwable) {
                error = t
            }
            runOnUiThread {
                prog.close()
                if (!alive()) return@runOnUiThread
                val err = error
                if (err != null) { showError("OCR failed", if (err is OutOfMemoryError) UserError("Not enough memory for this page.") else err); return@runOnUiThread }
                val total = results.sumOf { it.second.size }
                if (total == 0) {
                    info("OCR", if (stopFlag.get()) "Cancelled." else "No text was recognised. Check that the right languages were chosen " +
                        "and that the scan is clear.")
                    return@runOnUiThread
                }
                writeOcr(results, stopFlag.get())
            }
        }.start()
    }

    private fun writeOcr(results: List<Pair<Int, List<TextLayer.Word>>>, partial: Boolean) {
        val eng = engine ?: return
        val ctx = this
        eng.edit("OCR text layer", false, { pdf ->
            val font = Ocr.glyphlessFont(ctx)
            for ((i, words) in results) if (words.isNotEmpty()) TextLayer.write(pdf, eng.pageOnEngine(i), TextLayer.groupRows(words), font)
        }) { _, err ->
            if (!alive()) return@edit
            if (err != null) { showError("Could not add the OCR text", err); return@edit }
            pv.refresh(false); shownRevision = eng.revision; refreshTitle()
            val text = results.joinToString("\n\n") { (i, w) -> "--- Page ${i + 1} ---\n" + TextLayer.rowsToText(TextLayer.groupRows(w)) }
            val msg = (if (partial) "Stopped early. " else "") + "Recognised text was added to ${results.size} page(s). " +
                "The pages look the same, but the text can now be searched, selected and copied. " +
                "Remember to save (menu > Save a copy).\n\nPlease check important figures against the page: OCR can make mistakes."
            AlertDialog.Builder(this).setTitle("OCR finished").setMessage(msg)
                .setPositiveButton("OK", null)
                .setNeutralButton("Copy all text") { _, _ -> copyToClipboard(text) }
                .setNegativeButton("Share as .txt") { _, _ -> shareText(text) }
                .show()
        }
    }

    private fun shareText(text: String) {
        val eng = engine ?: return
        val f = File(ShareProvider.shareDir(this), Files.stem(eng.displayName) + "_text.txt")
        f.writeText(text)
        val i = Intent(Intent.ACTION_SEND).setType("text/plain")
            .putExtra(Intent.EXTRA_STREAM, ShareProvider.uriFor(f)).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivity(Intent.createChooser(i, "Share text"))
    }

    // ------------------------------------------------------- redaction
    private fun applyRedactions() {
        val eng = engine ?: return
        if (!eng.canModify) { info("Not allowed", "The owner of this PDF does not allow changes."); return }
        eng.async({
            (0 until eng.pageCount).filter { i -> eng.annotations(i).any { it.type == PDFAnnotation.TYPE_REDACT } }
        }) { pages, _ ->
            if (pages.isNullOrEmpty()) {
                info("Apply redactions", "Nothing is marked yet.\n\nUse Annotate > Redact area (or select text > Mark for " +
                    "redaction) first.\n\nNote: drawing a black rectangle does NOT hide anything - the text underneath " +
                    "can still be copied. Only applied redactions remove it.")
                return@async
            }
            confirm("Apply redactions", "Everything under the marked areas on page(s) ${describePages(pages)} will be " +
                "removed for good - text, pictures and drawings - and replaced by black boxes.\n\nAfter you save, it " +
                "cannot be recovered from the saved file. Save it as a new copy to keep the original.", "Remove") {
                edit("Apply redactions", block = { _, e ->
                    for (i in pages) page(e, i).applyRedactions(true, PDFPage.REDACT_IMAGE_PIXELS,
                        PDFPage.REDACT_LINE_ART_REMOVE_IF_COVERED, PDFPage.REDACT_TEXT_REMOVE)
                }) { toast("Redactions applied. Save a copy to keep the result.") }
            }
        }
    }

    // ------------------------------------------------------------ saving
    private var pendingPassword: String? = null
    private var pendingUsePassword = false

    /** Write the current document to a private temporary file. */
    private fun writeTemp(name: String, password: String?, usePassword: Boolean): File {
        val eng = engine ?: throw UserError("No document.")
        val out = Files.tempFile(this, name)
        if (!eng.dirty && !usePassword) {
            eng.file.copyTo(out, overwrite = true)          // unchanged: exact copy of the original bytes
        } else {
            val pw = if (usePassword) password else eng.password
            eng.call { PageOps.save(eng.docOnEngine(), out, pw) }
        }
        return out
    }

    private fun saveCopy(password: String? = null, usePassword: Boolean = false) {
        val eng = engine ?: return
        pendingPassword = password
        pendingUsePassword = usePassword
        val suffix = when { usePassword && password.isNullOrEmpty() -> "_unlocked"; usePassword -> "_protected"; eng.dirty -> "_edited"; else -> "_copy" }
        val i = Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf")
            .putExtra(Intent.EXTRA_TITLE, Files.stem(eng.displayName) + suffix + ".pdf")
        try { startActivityForResult(i, REQ_SAVE) } catch (e: Exception) { toast("No app to choose where to save.") }
    }

    private fun writeTo(target: Uri, replacing: Boolean) {
        val eng = engine ?: return
        val prog = Progress(this, "Saving")
        val pw = pendingPassword; val usePw = pendingUsePassword
        Thread {
            var err: Throwable? = null
            try {
                val tmp = writeTemp("save_" + System.currentTimeMillis() + ".pdf", pw, usePw)
                try { Files.copyFileToUri(this, tmp, target) } finally { tmp.delete() }
            } catch (t: Throwable) { err = t }
            runOnUiThread {
                prog.close()
                if (!alive()) return@runOnUiThread
                val e = err
                if (e != null) {
                    showError("Could not save", if (replacing) UserError("The original file cannot be written " +
                        "(it may be read-only, e.g. opened from WhatsApp or e-mail). Use 'Save a copy' instead.\n\n${e.message}") else e)
                    return@runOnUiThread
                }
                if (!usePw) eng.markSaved()
                refreshTitle()
                toast(if (replacing) "Original file updated." else "Saved.")
                if (!replacing) {
                    Files.takePermission(this, target, true)
                    Store.addRecent(this, target, Files.displayName(this, target))
                }
            }
        }.start()
    }

    private fun saveOver() {
        val eng = engine ?: return
        val uri = sourceUri ?: return
        if (!eng.dirty) { toast("No changes to save."); return }
        AlertDialog.Builder(this).setTitle("Replace the original file?")
            .setMessage("This overwrites \"${eng.displayName}\" with your changes. The old version cannot be " +
                "recovered.\n\nTo keep the original, choose Save a copy instead.")
            .setPositiveButton("Replace original") { _, _ -> pendingPassword = null; pendingUsePassword = false; writeTo(uri, true) }
            .setNeutralButton("Save a copy") { _, _ -> saveCopy() }
            .setNegativeButton("Cancel", null).show()
    }

    private fun passwordMenu() {
        val eng = engine ?: return
        val items = arrayListOf("Save a copy with a new password")
        if (!eng.password.isNullOrEmpty()) items.add("Save a copy without a password")
        askChoice("Password", items) { k ->
            if (k == 1) {
                confirm("Remove password", "The copy will open without a password. Anyone with the file can read it.", "Continue") {
                    saveCopy(null, true)
                }
                return@askChoice
            }
            val a = EditText(this).apply { hint = "New password"; inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD }
            val b = EditText(this).apply { hint = "Repeat password"; inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD }
            val box = vbox(20).apply {
                addView(a); addView(b)
                addView(label("The copy is encrypted (AES-256). Keep the password safe: it cannot be recovered.", 12f))
            }
            AlertDialog.Builder(this).setTitle("New password").setView(box)
                .setPositiveButton("Save copy") { _, _ ->
                    val p = a.text.toString()
                    when {
                        p.length < 4 -> toast("Use at least 4 characters.")
                        p != b.text.toString() -> toast("The two passwords are different.")
                        p.contains(',') -> toast("Please do not use a comma in the password.")
                        else -> saveCopy(p, true)
                    }
                }.setNegativeButton("Cancel", null).show()
        }
    }

    private fun share() {
        val eng = engine ?: return
        val prog = Progress(this, "Preparing")
        Thread {
            var err: Throwable? = null
            var file: File? = null
            try {
                val out = File(ShareProvider.shareDir(this), eng.displayName.ifBlank { "document.pdf" }
                    .replace(Regex("[\\\\/:*?\"<>|]"), "_").let { if (it.lowercase().endsWith(".pdf")) it else "$it.pdf" })
                val tmp = writeTemp("share.pdf", null, false)
                tmp.copyTo(out, overwrite = true); tmp.delete()
                file = out
            } catch (t: Throwable) { err = t }
            runOnUiThread {
                prog.close()
                val f = file
                if (err != null || f == null) { showError("Could not share", err); return@runOnUiThread }
                val i = Intent(Intent.ACTION_SEND).setType("application/pdf")
                    .putExtra(Intent.EXTRA_STREAM, ShareProvider.uriFor(f)).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                startActivity(Intent.createChooser(i, "Share PDF"))
            }
        }.start()
    }

    private fun print() {
        val eng = engine ?: return
        if (!eng.canPrint) { info("Not allowed", "The owner of this PDF does not allow printing."); return }
        val prog = Progress(this, "Preparing")
        Thread {
            var err: Throwable? = null
            var file: File? = null
            try { file = writeTemp("print.pdf", null, false) } catch (t: Throwable) { err = t }
            runOnUiThread {
                prog.close()
                val f = file
                if (err != null || f == null) { showError("Could not print", err); return@runOnUiThread }
                val pm = getSystemService(Context.PRINT_SERVICE) as PrintManager
                pm.print(eng.displayName, FilePrintAdapter(f, eng.displayName, eng.pageCount), PrintAttributes.Builder().build())
            }
        }.start()
    }

    /** Hands an already finished PDF file to Android's printing. */
    private class FilePrintAdapter(val file: File, val name: String, val pages: Int) : PrintDocumentAdapter() {
        override fun onLayout(old: PrintAttributes?, new: PrintAttributes?, cancel: CancellationSignal?,
                              callback: LayoutResultCallback, extras: Bundle?) {
            if (cancel?.isCanceled == true) { callback.onLayoutCancelled(); return }
            callback.onLayoutFinished(PrintDocumentInfo.Builder(name)
                .setContentType(PrintDocumentInfo.CONTENT_TYPE_DOCUMENT).setPageCount(pages).build(), true)
        }

        override fun onWrite(range: Array<out PageRange>?, dest: ParcelFileDescriptor, cancel: CancellationSignal?,
                             callback: WriteResultCallback) {
            try {
                FileInputStream(file).use { i -> FileOutputStream(dest.fileDescriptor).use { o -> i.copyTo(o) } }
                callback.onWriteFinished(arrayOf(PageRange.ALL_PAGES))
            } catch (e: Exception) {
                callback.onWriteFailed(e.message)
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) return
        when (requestCode) {
            REQ_SAVE -> writeTo(uri, false)
            REQ_IMAGE -> placePicture(uri)
        }
    }

    companion object {
        private const val REQ_SAVE = 11
        private const val REQ_IMAGE = 12
    }
}
