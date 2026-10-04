package com.brb.pdf

import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.artifex.mupdf.fitz.Document
import com.artifex.mupdf.fitz.Link
import com.artifex.mupdf.fitz.Matrix
import com.artifex.mupdf.fitz.PDFAnnotation
import com.artifex.mupdf.fitz.PDFDocument
import com.artifex.mupdf.fitz.PDFPage
import com.artifex.mupdf.fitz.Point
import com.artifex.mupdf.fitz.Quad
import com.artifex.mupdf.fitz.Rect
import com.artifex.mupdf.fitz.StructuredText
import com.artifex.mupdf.fitz.android.AndroidDrawDevice
import java.io.File
import java.util.concurrent.Callable
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.Future

/**
 * One open PDF.
 *
 * MuPDF documents must only be used from one thread, so EVERY call into MuPDF
 * runs on this engine's own single background thread. The screen never waits
 * for MuPDF except for tiny reads; results come back to the main thread
 * through callbacks.
 *
 * All page coordinates are MuPDF "page space": points, the page as seen on
 * screen (its /Rotate applied), origin at the top-left of the page bounds.
 *
 * Every change runs inside a MuPDF journal operation, so Undo / Redo work for
 * all edits (annotations, page changes, OCR, redaction...). Nothing is written
 * to disk until the user saves.
 */
class PdfEngine private constructor(
    val file: File,                 // private working copy of the document
    val displayName: String,
    val password: String?,
    private val pdf: PDFDocument,
) {
    data class PageSize(val x0: Float, val y0: Float, val w: Float, val h: Float)

    private val exec: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "mupdf").apply { priority = Thread.NORM_PRIORITY + 1 }
    }
    private val main = Handler(Looper.getMainLooper())
    private val pages = HashMap<Int, PDFPage>()           // engine thread only
    private val stextCache = HashMap<Int, StructuredText>() // engine thread only

    @Volatile var sizes: List<PageSize> = emptyList(); private set
    @Volatile var revision = 0; private set
    @Volatile var dirty = false; private set
    @Volatile var undoLabel: String? = null; private set
    @Volatile var redoLabel: String? = null; private set
    @Volatile var closed = false; private set
    private var savedPosition = 0

    /** What the document's owner allows (respected - never bypassed). */
    var canAnnotate = true; private set
    var canModify = true; private set
    var canAssemble = true; private set
    var canCopy = true; private set
    var canPrint = true; private set
    val pageCount: Int get() = sizes.size

    companion object {
        /** Open a PDF file. Must not be called on the main thread (it reads the whole page tree). */
        fun open(file: File, displayName: String, password: String?): PdfEngine {
            val doc = try {
                Document.openDocument(file.absolutePath)
            } catch (e: Exception) {
                throw UserError("This file could not be opened as a PDF.\n\n${e.message ?: ""}")
            }
            if (doc !is PDFDocument) {
                doc.destroy()
                throw UserError("$displayName is not a PDF document.")
            }
            if (doc.needsPassword()) {
                if (password == null) { doc.destroy(); throw PasswordNeeded(false) }
                if (!doc.authenticatePassword(password)) { doc.destroy(); throw PasswordNeeded(true) }
            }
            val engine = PdfEngine(file, displayName, password, doc)
            engine.call {
                doc.enableJournal()
                engine.canAnnotate = doc.hasPermission(Document.PERMISSION_ANNOTATE)
                engine.canModify = doc.hasPermission(Document.PERMISSION_EDIT)
                engine.canAssemble = doc.hasPermission(Document.PERMISSION_ASSEMBLE) || engine.canModify
                engine.canCopy = doc.hasPermission(Document.PERMISSION_COPY)
                engine.canPrint = doc.hasPermission(Document.PERMISSION_PRINT)
                engine.readSizes()
                engine.savedPosition = doc.undoRedoPosition()
                engine.updateState()
            }
            return engine
        }
    }

    class PasswordNeeded(val wrong: Boolean) : Exception(if (wrong) "Wrong password" else "Password required")

    // ================================================================ threading
    /** Run on the engine thread and wait for the result (call from background threads only). */
    fun <T> call(block: () -> T): T {
        if (Thread.currentThread().name == "mupdf") return block()
        return exec.submit(Callable { block() }).get()
    }

    fun <T> submit(block: () -> T): Future<T> = exec.submit(Callable { block() })

    /** Run on the engine thread; `done` gets the result (or the error) on the main thread. */
    fun <T> async(block: () -> T, done: (T?, Throwable?) -> Unit) {
        if (closed) return
        exec.execute {
            var result: T? = null
            var error: Throwable? = null
            try { result = block() } catch (t: Throwable) { error = t; Log.w(TAG, "engine task failed", t) }
            main.post { done(result, error) }
        }
    }

    fun close() {
        if (closed) return
        closed = true
        exec.execute {
            try {
                for (p in pages.values) p.destroy()
                for (t in stextCache.values) t.destroy()
                pages.clear(); stextCache.clear()
                pdf.destroy()
            } catch (_: Throwable) { }
        }
        exec.shutdown()
    }

    // ============================================================ engine-thread
    private fun page(i: Int): PDFPage = pages.getOrPut(i) { pdf.loadPage(i) as PDFPage }

    private fun stext(i: Int): StructuredText = stextCache.getOrPut(i) { page(i).toStructuredText("preserve-whitespace") }

    private fun forgetPages() {
        for (p in pages.values) try { p.destroy() } catch (_: Throwable) { }
        for (t in stextCache.values) try { t.destroy() } catch (_: Throwable) { }
        pages.clear(); stextCache.clear()
    }

    private fun readSizes() {
        val n = pdf.countPages()
        val list = ArrayList<PageSize>(n)
        for (i in 0 until n) {
            val b = try { page(i).bounds } catch (e: Exception) { Rect(0f, 0f, 595f, 842f) }
            list.add(PageSize(b.x0, b.y0, maxOf(1f, b.x1 - b.x0), maxOf(1f, b.y1 - b.y0)))
        }
        sizes = list
    }

    private fun updateState() {
        val pos = pdf.undoRedoPosition()
        val steps = pdf.undoRedoSteps()
        undoLabel = if (pos > 0) pdf.undoRedoStep(pos - 1) else null
        redoLabel = if (pos < steps) pdf.undoRedoStep(pos) else null
        dirty = pos != savedPosition
    }

    private fun afterChange(structure: Boolean) {
        forgetPages()
        if (structure) readSizes() else sizes = ArrayList(sizes)
        revision++
        updateState()
    }

    // =============================================================== rendering
    /** Render page `i` at `scale` pixels per point. With `patch` (pixel rectangle of the full
     *  page bitmap at that scale) only that part is drawn - used for sharp zoomed-in views. */
    fun render(i: Int, scale: Float, patch: android.graphics.Rect? = null): Bitmap = call {
        val pg = page(i)
        val ctm = Matrix(scale)
        val b = pg.bounds
        val ix0 = Math.floor((b.x0 * scale).toDouble()).toInt()
        val iy0 = Math.floor((b.y0 * scale).toDouble()).toInt()
        val iw = maxOf(1, Math.ceil(((b.x1 - b.x0) * scale).toDouble()).toInt())
        val ih = maxOf(1, Math.ceil(((b.y1 - b.y0) * scale).toDouble()).toInt())
        val r = patch ?: android.graphics.Rect(0, 0, iw, ih)
        val bmp = Bitmap.createBitmap(maxOf(1, r.width()), maxOf(1, r.height()), Bitmap.Config.ARGB_8888)
        bmp.eraseColor(android.graphics.Color.WHITE)
        val dev = AndroidDrawDevice(bmp, ix0 + r.left, iy0 + r.top, false)
        try {
            pg.run(dev, ctm, null)
            dev.close()
        } finally {
            dev.destroy()
        }
        bmp
    }

    // ==================================================================== text
    data class Selection(val page: Int, val quads: List<Quad>, val text: String)

    fun selectText(i: Int, a: Point, b: Point): Selection = call {
        val st = stext(i)
        val quads = st.highlight(a, b)?.toList() ?: emptyList()
        val text = if (quads.isEmpty()) "" else st.copy(a, b) ?: ""
        Selection(i, quads, text.trim())
    }

    /** The word under a point, as a selection. */
    fun wordAt(i: Int, p: Point): Selection? = call {
        val st = stext(i)
        for (block in st.blocks ?: emptyArray()) {
            for (line in block.lines ?: emptyArray()) {
                val chars = line.chars ?: continue
                var k = 0
                while (k < chars.size) {
                    if (chars[k].isWhitespace) { k++; continue }
                    var e = k
                    while (e + 1 < chars.size && !chars[e + 1].isWhitespace) e++
                    val r = Rect(chars[k].quad)
                    for (j in k + 1..e) r.union(Rect(chars[j].quad))
                    if (r.contains(p.x, p.y)) {
                        val text = String(IntArray(e - k + 1) { chars[k + it].c }, 0, e - k + 1)
                        return@call Selection(i, (k..e).map { chars[it].quad }, text)
                    }
                    k = e + 1
                }
            }
        }
        null
    }

    fun pageText(i: Int): String = call { stext(i).asText() ?: "" }

    /** Link under a point: page number (internal link) or web/e-mail address (external). */
    data class LinkHit(val page: Int, val uri: String?)

    fun linkAt(i: Int, p: Point): LinkHit? = call {
        val links = try { page(i).links } catch (e: Exception) { null } ?: return@call null
        for (l in links) {
            val b = l.bounds
            if (!b.contains(p.x, p.y)) continue
            val uri = l.uri ?: continue
            if (Link.isExternal(uri)) return@call LinkHit(-1, uri)
            val target = try { pdf.pageNumberFromLocation(pdf.resolveLink(uri)) } catch (e: Exception) { -1 }
            if (target >= 0) return@call LinkHit(target, null)
        }
        null
    }

    fun search(i: Int, needle: String): List<Rect> = call {
        val hits = try { page(i).search(needle) } catch (e: Exception) { null }
        hits?.map { quads -> Rect(quads[0]).also { r -> for (q in quads.drop(1)) r.union(Rect(q)) } } ?: emptyList()
    }

    /** Pages that look scanned: almost no text but pictures. */
    fun scannedPages(): List<Int> = call {
        val out = ArrayList<Int>()
        for (i in 0 until pdf.countPages()) if (pageNeedsOcr(i)) out.add(i)
        out
    }

    fun pageNeedsOcr(i: Int): Boolean = call {
        val st = page(i).toStructuredText("preserve-images")
        try {
            var chars = 0
            var imageArea = 0f
            st.walk(object : com.artifex.mupdf.fitz.StructuredTextWalker {
                override fun onImageBlock(bbox: Rect, transform: Matrix, image: com.artifex.mupdf.fitz.Image) {
                    imageArea += (bbox.x1 - bbox.x0) * (bbox.y1 - bbox.y0)
                }
                override fun beginTextBlock(bbox: Rect, flags: Int) {}
                override fun endTextBlock() {}
                override fun beginLine(bbox: Rect, wmode: Int, dir: Point) {}
                override fun endLine() {}
                override fun onChar(c: Int, origin: Point, font: com.artifex.mupdf.fitz.Font, size: Float, q: Quad,
                                    argb: Int, flags: Int, bidi: Int) {
                    if (!Character.isWhitespace(c)) chars++
                }
                override fun beginStruct(standard: String?, raw: String?, index: Int) {}
                override fun endStruct() {}
                override fun onVector(bbox: Rect, info: com.artifex.mupdf.fitz.StructuredTextWalker.VectorInfo, argb: Int) {}
            })
            val s = sizes[i]
            chars < 30 && imageArea >= 0.2f * s.w * s.h
        } finally {
            st.destroy()
        }
    }

    fun outline(): List<Triple<Int, String, Int>> = call {
        val out = ArrayList<Triple<Int, String, Int>>()
        fun walk(items: Array<com.artifex.mupdf.fitz.Outline>?, level: Int) {
            for (o in items ?: return) {
                val page = try { pdf.pageNumberFromLocation(pdf.resolveLink(o)) } catch (e: Exception) { -1 }
                out.add(Triple(level, o.title ?: "", page))
                walk(o.down, level + 1)
            }
        }
        try { walk(pdf.loadOutline(), 0) } catch (_: Exception) { }
        out
    }

    fun info(): List<Pair<String, String>> = call {
        fun m(k: String) = try { pdf.getMetaData(k)?.takeIf { it.isNotBlank() } ?: "-" } catch (e: Exception) { "-" }
        val s = sizes.firstOrNull()
        listOf(
            "File" to displayName,
            "Pages" to pageCount.toString(),
            "Page size" to (s?.let { "%.0f x %.0f mm".format(it.w / 72 * 25.4, it.h / 72 * 25.4) } ?: "-"),
            "PDF version" to m("format"),
            "Title" to m("info:Title"),
            "Author" to m("info:Author"),
            "Subject" to m("info:Subject"),
            "Creator" to m("info:Creator"),
            "Producer" to m("info:Producer"),
            "Created" to pdfDate(m("info:CreationDate")),
            "Modified" to pdfDate(m("info:ModDate")),
            "Encryption" to m("encryption"),
            "File size" to "%.1f MB".format(file.length() / 1048576.0),
        )
    }

    private fun pdfDate(v: String): String =
        if (v.startsWith("D:") && v.length >= 10) "${v.substring(8, 10)}-${v.substring(6, 8)}-${v.substring(2, 6)}" else v

    // ================================================================== edits
    /** Run `block` as one undoable change. `structure` = pages added/removed/rotated/moved. */
    fun <T> edit(label: String, structure: Boolean, block: (PDFDocument) -> T, done: (T?, Throwable?) -> Unit) {
        async({
            pdf.beginOperation(label)
            try {
                val r = block(pdf)
                for (p in pages.values) try { p.update() } catch (_: Throwable) { }
                pdf.endOperation()
                afterChange(structure)
                r
            } catch (t: Throwable) {
                try { pdf.abandonOperation() } catch (_: Throwable) { }
                afterChange(true)
                throw t
            }
        }, done)
    }

    fun undo(done: (String?) -> Unit) = async({
        val label = undoLabel
        if (pdf.canUndo()) { pdf.undo(); afterChange(true); label } else null
    }) { r, _ -> done(r) }

    fun redo(done: (String?) -> Unit) = async({
        val label = redoLabel
        if (pdf.canRedo()) { pdf.redo(); afterChange(true); label } else null
    }) { r, _ -> done(r) }

    /** Save the current state to `target` (never the working copy itself). */
    fun saveTo(target: File) = call {
        val opts = if (password.isNullOrEmpty()) "garbage=compact,compress"
        else "garbage=compact,compress,encrypt=aes-256,user-password=$password,owner-password=$password"
        pdf.save(target.absolutePath, opts)
    }

    fun markSaved() = call {
        savedPosition = pdf.undoRedoPosition()
        updateState()
    }

    /** Page access for helpers that already run on the engine thread (inside edit/call blocks). */
    fun pageOnEngine(i: Int): PDFPage = page(i)
    fun docOnEngine(): PDFDocument = pdf

    // ============================================================ annotations
    data class AnnotInfo(val page: Int, val id: Int, val type: Int, val rect: Rect, val contents: String,
                         val color: FloatArray?) {
        val label: String get() = when (type) {
            PDFAnnotation.TYPE_HIGHLIGHT -> "Highlight"; PDFAnnotation.TYPE_UNDERLINE -> "Underline"
            PDFAnnotation.TYPE_STRIKE_OUT -> "Strikethrough"; PDFAnnotation.TYPE_TEXT -> "Note"
            PDFAnnotation.TYPE_FREE_TEXT -> "Text"; PDFAnnotation.TYPE_SQUARE -> "Rectangle"
            PDFAnnotation.TYPE_CIRCLE -> "Ellipse"; PDFAnnotation.TYPE_LINE -> "Line"
            PDFAnnotation.TYPE_INK -> "Drawing"; PDFAnnotation.TYPE_STAMP -> "Stamp / signature"
            PDFAnnotation.TYPE_REDACT -> "Redaction mark"; else -> "Comment"
        }
        val movable: Boolean get() = type !in setOf(PDFAnnotation.TYPE_HIGHLIGHT, PDFAnnotation.TYPE_UNDERLINE,
            PDFAnnotation.TYPE_STRIKE_OUT, PDFAnnotation.TYPE_SQUIGGLY, PDFAnnotation.TYPE_WIDGET,
            PDFAnnotation.TYPE_LINK, PDFAnnotation.TYPE_POPUP)
        val resizable: Boolean get() = type in setOf(PDFAnnotation.TYPE_SQUARE, PDFAnnotation.TYPE_CIRCLE,
            PDFAnnotation.TYPE_FREE_TEXT, PDFAnnotation.TYPE_STAMP, PDFAnnotation.TYPE_REDACT)
        val hasText: Boolean get() = type == PDFAnnotation.TYPE_TEXT || type == PDFAnnotation.TYPE_FREE_TEXT
    }

    fun annotations(i: Int): List<AnnotInfo> = call {
        val out = ArrayList<AnnotInfo>()
        for (a in page(i).annotations ?: emptyArray()) {
            val t = a.type
            if (t == PDFAnnotation.TYPE_POPUP || t == PDFAnnotation.TYPE_LINK || t == PDFAnnotation.TYPE_WIDGET) continue
            val color = try { a.color } catch (e: Exception) { null }
            out.add(AnnotInfo(i, a.getObject().asIndirect(), t, Rect(a.bounds), a.contents ?: "", color))
        }
        out
    }

    fun annotAt(i: Int, p: Point, tolerance: Float): AnnotInfo? {
        val hits = annotations(i).filter {
            val r = it.rect
            p.x >= r.x0 - tolerance && p.x <= r.x1 + tolerance && p.y >= r.y0 - tolerance && p.y <= r.y1 + tolerance
        }
        return hits.minByOrNull { (it.rect.x1 - it.rect.x0) * (it.rect.y1 - it.rect.y0) }
    }

    /** Find an annotation object by id on the engine thread. */
    fun annotOnEngine(i: Int, id: Int): PDFAnnotation =
        page(i).annotations?.firstOrNull { it.getObject().asIndirect() == id }
            ?: throw UserError("That item no longer exists.")
}
