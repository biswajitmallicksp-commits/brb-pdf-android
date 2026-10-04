package com.brb.pdf

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.provider.DocumentsContract
import android.view.Gravity
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.FrameLayout
import android.widget.GridView
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import com.artifex.mupdf.fitz.PDFDocument
import java.io.File

/**
 * Page tools: tap pages to select them, then rotate, delete, duplicate, move,
 * extract, split, or insert pages. Every change can be undone. Changes go into
 * the open document (save it from the viewer); Extract and Split write new files
 * and never change the open document.
 */
class OrganizeActivity : Activity() {

    private var engine: PdfEngine? = null
    private lateinit var grid: GridView
    private lateinit var status: TextView
    private val selected = sortedSetOf<Int>()
    private val thumbs = HashMap<Int, Bitmap>()
    private val pending = HashSet<Int>()
    private var thumbRevision = -1
    private var thumbW = 0

    private val adapter = object : BaseAdapter() {
        override fun getCount() = engine?.pageCount ?: 0
        override fun getItem(position: Int): Any = position
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View = cell(position, convertView)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val eng = DocStore.engine
        if (eng == null || eng.closed) { finish(); return }
        engine = eng
        thumbW = (resources.displayMetrics.widthPixels - dp(16)) / columns() - dp(12)

        grid = GridView(this).apply {
            numColumns = columns()
            verticalSpacing = dp(8); horizontalSpacing = dp(8)
            setPadding(dp(8), dp(8), dp(8), dp(8)); clipToPadding = false
            adapter = this@OrganizeActivity.adapter
            setOnItemClickListener { _, _, pos, _ -> toggle(pos) }
            setOnItemLongClickListener { _, _, pos, _ ->
                askChoice("Page ${pos + 1}", listOf("Show this page", "Select pages ${pos + 1} to end", "Select only this page")) { k ->
                    when (k) {
                        0 -> { DocStore.gotoPage = pos; finish() }
                        1 -> { selected.addAll(pos until eng.pageCount); changed() }
                        2 -> { selected.clear(); selected.add(pos); changed() }
                    }
                }
                true
            }
        }
        status = label("", 13f).apply { setPadding(dp(12), dp(6), dp(12), dp(6)) }

        val row = hbox().apply { setPadding(dp(6), dp(6), dp(6), dp(6)) }
        fun add(name: String, action: () -> Unit) = row.addView(chip(name) { action() }, lp(-2, -2).apply { marginEnd = dp(6) })
        add("Select all") { if (selected.size == eng.pageCount) selected.clear() else selected.addAll(0 until eng.pageCount); changed() }
        add("Rotate left") { rotate(-90) }
        add("Rotate right") { rotate(90) }
        add("Delete") { delete() }
        add("Duplicate") { duplicate() }
        add("Move to...") { move() }
        add("Extract...") { extract() }
        add("Split...") { split() }
        add("Insert blank") { insertBlank() }
        add("Insert PDF...") { pickInsertPdf() }
        add("Undo") { undo() }
        add("Redo") { redo() }
        val tools = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false; addView(row)
            setBackgroundColor(if (isNight()) Color.rgb(40, 43, 48) else Color.rgb(245, 247, 250))
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(status, lp())
            addView(grid, lp(-1, 0, 1f))
            addView(tools, lp())
        }
        setContentView(root)
        actionBar?.setDisplayHomeAsUpEnabled(true)
        changed()
    }

    private fun columns() = if (resources.configuration.screenWidthDp >= 600) 5 else 3

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == android.R.id.home) { finish(); return true }
        return super.onOptionsItemSelected(item)
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean = true

    override fun onDestroy() {
        super.onDestroy()
        for (b in thumbs.values) b.recycle()
        thumbs.clear()
    }

    // ------------------------------------------------------------ grid
    private fun cell(pos: Int, convert: View?): View {
        val frame = (convert as? FrameLayout) ?: FrameLayout(this).apply {
            val img = ImageView(this@OrganizeActivity).apply {
                scaleType = ImageView.ScaleType.FIT_CENTER
                adjustViewBounds = true
                id = 1
            }
            val num = label("", 13f, bold = true, color = Color.WHITE).apply {
                id = 2; setPadding(dp(8), dp(2), dp(8), dp(2))
                background = GradientDrawable().apply { cornerRadius = dp(10).toFloat(); setColor(Color.argb(170, 0, 0, 0)) }
            }
            addView(img, FrameLayout.LayoutParams(-1, -2))
            addView(num, FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL).apply { bottomMargin = dp(6) })
            setPadding(dp(4), dp(4), dp(4), dp(4))
        }
        val img = frame.findViewById<ImageView>(1)
        val num = frame.findViewById<TextView>(2)
        val eng = engine ?: return frame
        val sel = pos in selected
        num.text = if (sel) "✓ ${pos + 1}" else "${pos + 1}"
        frame.background = GradientDrawable().apply {
            cornerRadius = dp(6).toFloat()
            setColor(if (sel) Color.rgb(47, 111, 219) else Color.TRANSPARENT)
        }
        val s = eng.sizes.getOrNull(pos)
        img.minimumHeight = if (s != null) (thumbW * s.h / s.w).toInt() else thumbW
        val bmp = thumbs[pos]
        if (bmp != null && !bmp.isRecycled) img.setImageBitmap(bmp) else {
            img.setImageDrawable(GradientDrawable().apply { setColor(Color.WHITE) })
            requestThumb(pos)
        }
        return frame
    }

    private fun requestThumb(i: Int) {
        val eng = engine ?: return
        if (eng.revision != thumbRevision) {
            for (b in thumbs.values) b.recycle()
            thumbs.clear(); pending.clear()
            thumbRevision = eng.revision
        }
        if (i in pending || i >= eng.pageCount) return
        pending.add(i)
        val rev = eng.revision
        val scale = thumbW.toFloat() / eng.sizes[i].w
        eng.async({ eng.render(i, scale) }) { bmp, _ ->
            pending.remove(i)
            if (bmp == null) return@async
            if (rev != eng.revision || isDestroyed) { bmp.recycle(); return@async }
            thumbs.put(i, bmp)?.recycle()
            adapter.notifyDataSetChanged()
        }
    }

    private fun toggle(pos: Int) {
        if (!selected.remove(pos)) selected.add(pos)
        changed()
    }

    private fun changed() {
        val eng = engine ?: return
        selected.removeAll { it >= eng.pageCount }
        title = "Pages"
        status.text = if (selected.isEmpty()) "${eng.pageCount} pages - tap pages to select them"
        else "${selected.size} selected: ${describePages(selected)}"
        adapter.notifyDataSetChanged()
    }

    private fun needSelection(): List<Int>? {
        if (selected.isEmpty()) { toast("Tap one or more pages first."); return null }
        return selected.toList()
    }

    // --------------------------------------------------------- page edits
    private fun edit(label: String, block: (PDFDocument, PdfEngine) -> List<Int>?, after: ((List<Int>?) -> Unit)? = null) {
        val eng = engine ?: return
        eng.edit(label, true, { pdf -> block(pdf, eng) }) { r, err ->
            if (!alive()) return@edit
            if (err is PdfEngine.PasswordNeeded) { after?.invoke(null); return@edit }
            if (err != null) { showError("Could not ${label.lowercase()}", err); return@edit }
            if (r != null) { selected.clear(); selected.addAll(r) }
            changed()
            toast(label)
            after?.invoke(r)
        }
    }

    private fun rotate(deg: Int) {
        val pages = needSelection() ?: return
        edit(if (deg > 0) "Rotate right" else "Rotate left", { pdf, _ -> PageOps.rotate(pdf, pages, deg); pages })
    }

    private fun delete() {
        val pages = needSelection() ?: return
        val eng = engine ?: return
        if (pages.size >= eng.pageCount) { info("Delete pages", "A PDF must keep at least one page."); return }
        confirm("Delete pages", "Delete page(s) ${describePages(pages)}? (You can undo this.)", "Delete") {
            edit("Delete pages", { pdf, _ -> PageOps.delete(pdf, pages); emptyList() })
        }
    }

    private fun duplicate() {
        val pages = needSelection() ?: return
        edit("Duplicate pages", { pdf, _ -> PageOps.duplicate(pdf, pages) })
    }

    private fun move() {
        val pages = needSelection() ?: return
        val eng = engine ?: return
        val n = eng.pageCount
        askChoice("Move page(s) ${describePages(pages)}", listOf("To the beginning", "To the end", "Before page...")) { k ->
            fun go(before: Int) = edit("Move pages", { pdf, _ -> PageOps.move(pdf, pages, before) })
            when (k) {
                0 -> go(0)
                1 -> go(n)
                else -> askText("Move before page (1-$n, or ${n + 1} for the end)", number = true) { t ->
                    val p = t.trim().toIntOrNull()
                    if (p == null || p < 1 || p > n + 1) toast("Enter a number from 1 to ${n + 1}.") else go(p - 1)
                }
            }
        }
    }

    private fun askPosition(title: String, then: (Int) -> Unit) {
        val eng = engine ?: return
        val n = eng.pageCount
        val opts = ArrayList<Pair<String, Int>>()
        if (selected.isNotEmpty()) {
            opts.add("Before page ${selected.first() + 1}" to selected.first())
            opts.add("After page ${selected.last() + 1}" to selected.last() + 1)
        }
        opts.add("At the beginning" to 0)
        opts.add("At the end" to n)
        askChoice(title, opts.map { it.first }) { k -> then(opts[k].second) }
    }

    private fun insertBlank() {
        val eng = engine ?: return
        askPosition("Insert a blank page") { at ->
            val ref = eng.sizes.getOrNull(if (at > 0) at - 1 else 0)
            val w = ref?.w ?: 595f; val h = ref?.h ?: 842f
            edit("Insert blank page", { pdf, _ -> listOf(PageOps.insertBlank(pdf, at, w, h)) })
        }
    }

    private var insertAt = 0
    private var insertFile: File? = null

    private fun pickInsertPdf() {
        askPosition("Insert pages from another PDF") { at ->
            insertAt = at
            val i = Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf")
            try { startActivityForResult(i, REQ_INSERT) } catch (e: Exception) { toast("No app to pick a file.") }
        }
    }

    private fun insertPdf(file: File, password: String?) {
        val at = insertAt
        edit("Insert pages", { pdf, _ ->
            val src = PageOps.openSource(file, password)
            try { PageOps.insertFrom(pdf, src, minOf(at, pdf.countPages())) } finally { src.destroy() }
        }) { r ->
            if (r == null) {
                // the other PDF needs a password
                askText("Password of the PDF to insert", password = true) { pw -> insertPdf(file, pw) }
            } else file.delete()
        }
    }

    private fun undo() {
        val eng = engine ?: return
        eng.undo { l -> if (l == null) toast("Nothing to undo.") else { selected.clear(); changed(); toast("Undone: $l") } }
    }

    private fun redo() {
        val eng = engine ?: return
        eng.redo { l -> if (l == null) toast("Nothing to redo.") else { selected.clear(); changed(); toast("Redone: $l") } }
    }

    // ------------------------------------------------------ new files
    private var extractPages: List<Int> = emptyList()
    private var splitGroups: List<List<Int>> = emptyList()

    private fun extract() {
        val pages = needSelection() ?: return
        val eng = engine ?: return
        extractPages = pages
        val i = Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf")
            .putExtra(Intent.EXTRA_TITLE, Files.stem(eng.displayName) + "_pages_" +
                describePages(pages).replace(", ", "_").replace("...", "") + ".pdf")
        try { startActivityForResult(i, REQ_EXTRACT) } catch (e: Exception) { toast("No app to choose where to save.") }
    }

    private fun writeExtract(target: Uri) {
        val eng = engine ?: return
        val pages = extractPages
        val prog = Progress(this, "Extracting")
        Thread {
            var err: Throwable? = null
            try {
                val tmp = Files.tempFile(this, "extract_${System.currentTimeMillis()}.pdf")
                eng.call { PageOps.extract(eng.docOnEngine(), pages, tmp, eng.password) }
                try { Files.copyFileToUri(this, tmp, target) } finally { tmp.delete() }
            } catch (t: Throwable) { err = t }
            runOnUiThread {
                prog.close()
                if (err != null) showError("Could not extract", err)
                else toast("Saved ${pages.size} page(s) as a new PDF.")
            }
        }.start()
    }

    private fun split() {
        val eng = engine ?: return
        val n = eng.pageCount
        askChoice("Split into several files", listOf("Every page as its own file", "Every N pages...", "By page ranges...")) { k ->
            fun plan(mode: String, value: String) {
                try {
                    val groups = PageOps.splitPlan(n, mode, value)
                    if (groups.size > 200) { info("Split", "That would make ${groups.size} files. Please choose bigger parts."); return }
                    splitGroups = groups
                    info("Split", "${groups.size} files will be made. Next, choose the folder to save them in.") {
                        try { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), REQ_SPLIT) }
                        catch (e: Exception) { toast("No app to choose a folder.") }
                    }
                } catch (e: UserError) { showError("Split", e) }
            }
            when (k) {
                0 -> plan("single", "")
                1 -> askText("Pages per file", number = true) { plan("every", it) }
                else -> askText("Page ranges (one file each)", hint = "e.g. 1-3, 4-10, 11-$n") { plan("ranges", it) }
            }
        }
    }

    private fun writeSplit(tree: Uri) {
        val eng = engine ?: return
        val groups = splitGroups
        val stem = Files.stem(eng.displayName)
        val stop = java.util.concurrent.atomic.AtomicBoolean(false)
        val prog = Progress(this, "Splitting", cancellable = true) { stop.set(true) }
        Thread {
            var err: Throwable? = null
            var made = 0
            try {
                val dir = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
                for ((k, g) in groups.withIndex()) {
                    if (stop.get()) break
                    runOnUiThread { prog.update(k, groups.size, "File ${k + 1} of ${groups.size}") }
                    val name = "${stem}_part${k + 1}_p${g.first() + 1}-${g.last() + 1}.pdf"
                    val tmp = Files.tempFile(this, "split.pdf")
                    eng.call { PageOps.extract(eng.docOnEngine(), g, tmp, eng.password) }
                    val doc = DocumentsContract.createDocument(contentResolver, dir, "application/pdf", name)
                        ?: throw UserError("Could not create $name in that folder.")
                    try { Files.copyFileToUri(this, tmp, doc) } finally { tmp.delete() }
                    made++
                }
            } catch (t: Throwable) { err = t }
            runOnUiThread {
                prog.close()
                if (err != null) showError("Split stopped after $made file(s)", err)
                else toast("Made $made file(s).")
            }
        }.start()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) return
        when (requestCode) {
            REQ_EXTRACT -> writeExtract(uri)
            REQ_SPLIT -> writeSplit(uri)
            REQ_INSERT -> {
                val prog = Progress(this, "Reading")
                Thread {
                    try {
                        val f = Files.copyToWork(this, uri, Files.displayName(this, uri))
                        runOnUiThread { prog.close(); insertPdf(f, null) }
                    } catch (t: Throwable) {
                        runOnUiThread { prog.close(); showError("Could not read that file", t) }
                    }
                }.start()
            }
        }
    }

    companion object {
        private const val REQ_EXTRACT = 21
        private const val REQ_SPLIT = 22
        private const val REQ_INSERT = 23
    }
}
