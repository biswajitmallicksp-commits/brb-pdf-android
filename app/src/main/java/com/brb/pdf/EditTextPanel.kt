package com.brb.pdf

import android.app.Activity
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.artifex.mupdf.fitz.PDFDocument
import com.artifex.mupdf.fitz.Point

/**
 * The "Edit text" side panel. It lists every line of the current page (table
 * columns as separate pieces). Change a line, or tap X to delete it, then tap
 * Apply: the old words are removed from the PDF and the new ones written in
 * their place. Tapping a line on the page jumps to it in the list.
 */
class EditTextPanel(
    private val act: Activity,
    private val pv: PageView,
    private val engine: () -> PdfEngine?,
    private val runEdit: (label: String, block: (PDFDocument, PdfEngine) -> Unit, after: () -> Unit) -> Unit,
    private val onClosed: () -> Unit,
) : LinearLayout(act) {

    private val title = act.label("Edit text", 16f, bold = true)
    private val status = act.label("", 12f, color = Color.GRAY)
    private val banner = act.label("", 13f, color = Color.WHITE).apply {
        setPadding(act.dp(10), act.dp(8), act.dp(10), act.dp(8))
        setBackgroundColor(Color.rgb(47, 111, 219)); visibility = View.GONE
    }
    private val list = LinearLayout(act).apply { orientation = VERTICAL }
    private val scroll = ScrollView(act).apply { addView(list) }
    private val applyButton: TextView

    private var page = -1
    private var segs: List<TextEdit.Seg> = emptyList()
    private val rows = ArrayList<Pair<TextEdit.Seg, EditText>>()
    private var bannerPage = -1
    private var loading = false

    val isOpen get() = visibility == View.VISIBLE

    init {
        orientation = VERTICAL
        setBackgroundColor(if (act.isNight()) Color.rgb(36, 39, 44) else Color.rgb(248, 249, 251))
        val pad = act.dp(10)
        setPadding(pad, pad, pad, pad)
        applyButton = act.chip("Apply changes") { apply() }
        val head = act.hbox().apply {
            addView(title, lp(0, -2, 1f))
            addView(applyButton, lp(-2, -2).apply { marginEnd = act.dp(6) })
            addView(act.chip("Close") { close() })
        }
        addView(head, lp())
        addView(status, lp().apply { topMargin = act.dp(4); bottomMargin = act.dp(6) })
        addView(banner, lp().apply { bottomMargin = act.dp(6) })
        addView(scroll, lp(-1, 0, 1f))
        banner.setOnClickListener { if (bannerPage >= 0) load(bannerPage) }
        visibility = View.GONE
        refreshButtons()
    }

    // ------------------------------------------------------------ open / close
    fun open(pageNo: Int) {
        val eng = engine() ?: return
        if (!eng.canModify) { act.info("Not allowed", "The owner of this PDF does not allow changing its text."); return }
        visibility = View.VISIBLE
        pv.tool = PageView.Tool.PLACE          // taps on the page pick a line
        if (Store.get(act, "textedit_tip", "0") != "1") {
            Store.put(act, "textedit_tip", "1")
            act.info("Edit text", "Change a line in the list (or tap X to delete it), then tap Apply changes.\n\n" +
                "The old words are really removed from the PDF and the new words are written in the same place, " +
                "size and colour, in the closest standard font (Helvetica, Times or Courier), so the letters may " +
                "look slightly different. Bengali/Hindi text and special symbols are written as a sharp picture.\n\n" +
                "Tap a line on the page to find it in the list. Undo works until you close the file. Save a copy to keep " +
                "the result.")
        }
        load(pageNo)
    }

    fun close(force: Boolean = false) {
        if (!force && pendingCount() > 0) {
            act.confirm("Discard changes?", "${pendingCount()} line(s) were changed but not applied.", "Discard") { close(true) }
            return
        }
        visibility = View.GONE
        rows.clear(); list.removeAllViews()
        page = -1
        pv.searchHits = emptyList(); pv.currentHit = -1
        if (pv.tool == PageView.Tool.PLACE) pv.tool = PageView.Tool.PAN
        hideKeyboard()
        onClosed()
    }

    /** Re-read the page (after undo / redo). */
    fun reload() { if (isOpen && page >= 0) { rows.clear(); load(page) } }

    private fun load(pageNo: Int) {
        val eng = engine() ?: return
        if (loading) return
        loading = true
        banner.visibility = View.GONE
        status.text = "Reading page ${pageNo + 1}..."
        eng.async({ eng.textSegments(pageNo) }) { result, err ->
            loading = false
            if (!act.alive() || !isOpen) return@async
            if (err != null) { act.showError("Could not read the text", err); return@async }
            page = pageNo
            segs = result ?: emptyList()
            build()
        }
    }

    private fun build() {
        rows.clear(); list.removeAllViews()
        title.text = "Edit text - page ${page + 1}"
        pv.searchHits = emptyList(); pv.currentHit = -1
        if (segs.isEmpty()) {
            status.text = "No editable text on this page."
            list.addView(act.label("This page has no text that can be edited. A scanned page is a picture: " +
                "its words cannot be changed (OCR only adds invisible text for searching). You can cover parts " +
                "with Annotate tools instead.", 14f))
            refreshButtons(); return
        }
        status.text = "${segs.size} lines. Change or delete, then Apply. Tap a line on the page to find it."
        for (s in segs) {
            val edit = EditText(act).apply {
                setText(s.text)
                textSize = 14f
                isSingleLine = true
                imeOptions = EditorInfo.IME_ACTION_DONE
                setTypeface(when { s.mono -> Typeface.MONOSPACE; s.serif -> Typeface.SERIF; else -> Typeface.SANS_SERIF },
                    if (s.bold) Typeface.BOLD else Typeface.NORMAL)
                isEnabled = s.editable
                setOnFocusChangeListener { _, has -> if (has) highlight(s) }
                addTextChangedListener(object : TextWatcher {
                    override fun beforeTextChanged(a: CharSequence?, b: Int, c: Int, d: Int) {}
                    override fun onTextChanged(a: CharSequence?, b: Int, c: Int, d: Int) {}
                    override fun afterTextChanged(e: Editable?) { markRow(this@apply, s); refreshButtons() }
                })
            }
            val del = TextView(act).apply {
                text = "✕"; textSize = 18f; gravity = Gravity.CENTER
                setPadding(act.dp(10), act.dp(6), act.dp(10), act.dp(6))
                contentDescription = "Delete this line"
                isEnabled = s.editable
                setOnClickListener {
                    if (edit.text.isEmpty()) edit.setText(s.text) else edit.setText("")
                    highlight(s)
                }
            }
            val row = act.hbox().apply {
                addView(edit, lp(0, -2, 1f))
                addView(del)
            }
            if (!s.editable) row.alpha = 0.5f
            list.addView(row, lp())
            rows.add(s to edit)
        }
        refreshButtons()
    }

    private fun markRow(edit: EditText, s: TextEdit.Seg) {
        val changed = edit.text.toString() != s.text
        edit.setBackgroundColor(if (!changed) Color.TRANSPARENT
            else if (edit.text.isEmpty()) Color.argb(60, 220, 40, 40) else Color.argb(60, 255, 190, 0))
        edit.hint = if (edit.text.isEmpty() && changed) "(deleted) ${s.text}" else null
        edit.paintFlags = edit.paintFlags and Paint.STRIKE_THRU_TEXT_FLAG.inv()
    }

    private fun pendingCount() = rows.count { (s, e) -> e.text.toString() != s.text }

    private fun refreshButtons() {
        val n = pendingCount()
        applyButton.text = if (n > 0) "Apply changes ($n)" else "Apply changes"
        applyButton.alpha = if (n > 0) 1f else 0.4f
    }

    private fun highlight(s: TextEdit.Seg) {
        pv.searchHits = listOf(s.page to s.rect)
        pv.currentHit = 0
        pv.showRect(s.page, s.rect)
    }

    // ------------------------------------------------------- page events
    fun onPageChanged(p: Int) {
        if (!isOpen || p == page || loading) return
        if (pendingCount() == 0) { load(p); return }
        bannerPage = p
        banner.text = "You are now on page ${p + 1}. Apply your changes first, or tap here to edit page ${p + 1} " +
            "(changes not applied will be lost)."
        banner.visibility = View.VISIBLE
    }

    /** A tap on the page: find the line under the finger. */
    fun pickAt(p: Int, at: Point) {
        if (p != page) { onPageChanged(p); return }
        val tol = 3f
        val k = rows.indexOfFirst { (s, _) ->
            at.x >= s.rect.x0 - tol && at.x <= s.rect.x1 + tol && at.y >= s.rect.y0 - tol && at.y <= s.rect.y1 + tol
        }
        if (k < 0) { act.toast("No text there."); return }
        val (s, edit) = rows[k]
        highlight(s)
        scroll.post { scroll.smoothScrollTo(0, (edit.parent as View).top) }
        edit.requestFocus()
        edit.setSelection(edit.text.length)
    }

    // ------------------------------------------------------------- apply
    private fun apply() {
        val changes = rows.filter { (s, e) -> e.text.toString() != s.text }.map { (s, e) -> TextEdit.Change(s, e.text.toString()) }
        if (changes.isEmpty()) { act.toast("Change or delete a line first."); return }
        hideKeyboard()
        val p = page
        val deleted = changes.count { it.newText.isBlank() }
        val label = when {
            deleted == changes.size -> "Delete ${changes.size} line(s)"
            deleted == 0 -> "Rewrite ${changes.size} line(s)"
            else -> "Edit ${changes.size} line(s)"
        }
        runEdit(label, { pdf, eng ->
            TextEdit.apply(pdf, eng.pageOnEngine(p), changes) { text, size, color ->
                SignaturePad.textPicture(text, size, color, 2000f)
            }
        }) {
            act.toast("$label done. Save a copy to keep it.")
            rows.clear()
            load(p)
        }
    }

    private fun hideKeyboard() {
        val imm = act.getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager
        imm.hideSoftInputFromWindow(windowToken, 0)
    }
}
