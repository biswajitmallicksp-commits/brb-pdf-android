package com.brb.pdf

import com.artifex.mupdf.fitz.Document
import com.artifex.mupdf.fitz.PDFDocument
import com.artifex.mupdf.fitz.Rect
import java.io.File

/**
 * Page operations. Functions taking a PDFDocument run on the engine thread inside
 * PdfEngine.edit { } (undoable). Functions that create new files never touch the
 * open document.
 */
object PageOps {

    fun rotate(pdf: PDFDocument, pages: List<Int>, degrees: Int) {
        for (i in pages) {
            val obj = pdf.findPage(i)
            val old = obj.getInheritable("Rotate").let { if (it == null || it.isNull) 0 else it.asInteger() }
            obj.put("Rotate", ((old + degrees) % 360 + 360) % 360)
        }
    }

    fun delete(pdf: PDFDocument, pages: List<Int>) {
        if (pages.size >= pdf.countPages()) throw UserError("A PDF must keep at least one page.")
        for (i in pages.sortedDescending()) pdf.deletePage(i)
    }

    /** New order after moving `pages` (kept in order) to just before page `before`. */
    fun moveOrder(count: Int, pages: List<Int>, before: Int): IntArray {
        val sel = pages.toSortedSet()
        val rest = (0 until count).filter { it !in sel }
        val at = rest.count { it < before }
        return (rest.take(at) + sel + rest.drop(at)).toIntArray()
    }

    fun move(pdf: PDFDocument, pages: List<Int>, before: Int): List<Int> {
        val order = moveOrder(pdf.countPages(), pages, before)
        if (order.toList() != (0 until pdf.countPages()).toList()) pdf.rearrangePages(order)
        return pages.sorted().map { p -> order.indexOf(p) }
    }

    /** Copy of each page right after it (copied through a temporary document, so the copy
     *  is fully independent of the original). Returns the new pages' positions. */
    fun duplicate(pdf: PDFDocument, pages: List<Int>): List<Int> {
        val tmp = PDFDocument()
        try {
            val sorted = pages.sorted()
            for ((k, p) in sorted.withIndex()) tmp.graftPage(k, pdf, p)
            val out = ArrayList<Int>()
            for ((k, p) in sorted.withIndex().reversed()) pdf.graftPage(p + 1, tmp, k)
            for ((k, p) in sorted.withIndex()) out.add(p + 1 + k)
            return out
        } finally {
            tmp.destroy()
        }
    }

    fun insertBlank(pdf: PDFDocument, at: Int, w: Float, h: Float): Int {
        val page = pdf.addPage(Rect(0f, 0f, w, h), 0, pdf.newDictionary(), "")
        pdf.insertPage(if (at >= pdf.countPages()) -1 else at, page)
        return at
    }

    fun insertFrom(pdf: PDFDocument, src: PDFDocument, at: Int): List<Int> {
        val n = src.countPages()
        for (k in 0 until n) {
            val to = at + k
            pdf.graftPage(if (to >= pdf.countPages()) -1 else to, src, k)
        }
        return (at until at + n).toList()
    }

    /** Open another PDF to take pages from. */
    fun openSource(file: File, password: String?): PDFDocument {
        val doc = try { Document.openDocument(file.absolutePath) } catch (e: Exception) {
            throw UserError("Could not open the file: ${e.message}")
        }
        if (doc !is PDFDocument) { doc.destroy(); throw UserError("That file is not a PDF.") }
        if (doc.needsPassword() && (password == null || !doc.authenticatePassword(password))) {
            doc.destroy()
            throw PdfEngine.PasswordNeeded(password != null)
        }
        return doc
    }

    /** New file with copies of `pages` of `pdf` (in the given order). */
    fun extract(pdf: PDFDocument, pages: List<Int>, out: File, password: String?) {
        val doc = PDFDocument()
        try {
            for ((k, p) in pages.withIndex()) doc.graftPage(k, pdf, p)
            save(doc, out, password)
        } finally {
            doc.destroy()
        }
    }

    fun save(doc: PDFDocument, out: File, password: String?) {
        val opts = if (password.isNullOrEmpty()) "garbage=compact,compress"
        else "garbage=compact,compress,encrypt=aes-256,user-password=$password,owner-password=$password"
        doc.save(out.absolutePath, opts)
    }

    /** Split plan: groups of pages. mode "every" (value = N) or "ranges" (value = "1-3, 4-10"). */
    fun splitPlan(count: Int, mode: String, value: String): List<List<Int>> = when (mode) {
        "every" -> {
            val n = value.trim().toIntOrNull() ?: throw UserError("Enter a number of pages.")
            if (n < 1) throw UserError("Enter a number of pages of at least 1.")
            (0 until count step n).map { a -> (a until minOf(count, a + n)).toList() }
        }
        "single" -> (0 until count).map { listOf(it) }
        else -> value.split(',', ';').filter { it.isNotBlank() }.map { parsePageRange(it, count) }
            .ifEmpty { throw UserError("Enter page ranges, for example 1-3, 4-10") }
    }

    /** Combine several PDF files into one new file. */
    fun merge(files: List<Pair<File, String?>>, out: File, progress: (Int, Int) -> Boolean) {
        val doc = PDFDocument()
        try {
            for ((k, pair) in files.withIndex()) {
                if (!progress(k, files.size)) throw UserError("Cancelled.")
                val src = openSource(pair.first, pair.second)
                try {
                    for (p in 0 until src.countPages()) doc.graftPage(-1, src, p)
                } finally {
                    src.destroy()
                }
            }
            save(doc, out, null)
        } finally {
            doc.destroy()
        }
    }
}
