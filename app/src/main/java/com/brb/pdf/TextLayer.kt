package com.brb.pdf

import com.artifex.mupdf.fitz.Font
import com.artifex.mupdf.fitz.PDFDocument
import com.artifex.mupdf.fitz.PDFObject
import com.artifex.mupdf.fitz.PDFPage

/**
 * Writes recognised (OCR) words onto a page as INVISIBLE text, so the page looks
 * exactly the same but can be searched, selected and copied - in this app and in
 * every other PDF reader.
 *
 * Same method as the Windows version: a "glyphless" font (assets/ocr_glyphless.ttf,
 * every character has an empty shape) covering English, Bengali and Devanagari,
 * each word written separately and stretched to its box, followed by a real space.
 * Runs on the engine thread inside an edit operation.
 */
object TextLayer {
    data class Word(val x0: Float, val y0: Float, val x1: Float, val y1: Float, val text: String)

    private const val FONT_KEY = "BRBOCR"

    /** `rows`: words grouped in visual lines, left to right, in page space (points). */
    fun write(pdf: PDFDocument, page: PDFPage, rows: List<List<Word>>, font: Font): Int {
        if (rows.isEmpty()) return 0
        val pageObj = page.getObject()

        // ---- font resource
        var res = pageObj.getInheritable("Resources")
        if (res == null || res.isNull) {
            res = pdf.newDictionary()
            pageObj.put("Resources", res)
        }
        var fonts = res.get("Font")
        if (fonts == null || fonts.isNull) {
            fonts = pdf.newDictionary()
            res.put("Font", fonts)
        }
        fonts.put(FONT_KEY, pdf.addFont(font))

        // ---- page space -> PDF space
        val ctm = page.transform
        val inv = invert(floatArrayOf(ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f))
        val space = font.encodeCharacter(' '.code)

        val sb = StringBuilder()
        sb.append("BT 3 Tr /").append(FONT_KEY).append(" 1 Tf\n")
        var words = 0
        for (row in rows) {
            for ((k, w) in row.withIndex()) {
                if (w.text.isBlank()) continue
                val gids = ArrayList<Int>()
                val cps = w.text.codePoints().toArray()
                for (cp in cps) gids.add(maxOf(0, font.encodeCharacter(cp)))
                if (gids.isEmpty()) continue
                val h = w.y1 - w.y0
                val width = w.x1 - w.x0
                if (h <= 0f || width <= 0f) continue
                val fs = h * 0.85f
                var natural = 0f
                for (g in gids) natural += font.advanceGlyph(g, false)
                natural *= fs
                if (natural <= 0f) continue
                val stretch = width / natural
                val baseY = w.y1 - 0.2f * fs
                // glyph space -> page space (y flipped), then -> PDF space
                val g = floatArrayOf(stretch * fs, 0f, 0f, -fs, w.x0, baseY)
                val m = concat(g, inv)
                sb.append(fmt(m[0])).append(' ').append(fmt(m[1])).append(' ').append(fmt(m[2])).append(' ')
                    .append(fmt(m[3])).append(' ').append(fmt(m[4])).append(' ').append(fmt(m[5])).append(" Tm <")
                for (gid in gids) sb.append(hex4(gid))
                if (k < row.size - 1) sb.append(hex4(maxOf(0, space)))
                sb.append("> Tj\n")
                words++
            }
        }
        sb.append("ET\n")
        if (words == 0) return 0

        // ---- keep the original drawing state intact: q <original> Q <ours>
        val contents = pageObj.get("Contents")
        val arr = pdf.newArray()
        arr.push(pdf.addStream("q\n"))
        if (contents != null && !contents.isNull) {
            val resolved: PDFObject = contents.resolve()
            if (resolved.isArray) {
                for (i in 0 until resolved.size()) arr.push(resolved.get(i))
            } else {
                arr.push(contents)
            }
        }
        arr.push(pdf.addStream("Q\n$sb"))
        pageObj.put("Contents", arr)
        return words
    }

    /** Group words into visual rows (top to bottom), each row left to right. */
    fun groupRows(words: List<Word>): List<List<Word>> {
        val rows = ArrayList<MutableList<Word>>()
        val bounds = ArrayList<FloatArray>()
        for (w in words.sortedWith(compareBy({ (it.y0 + it.y1) / 2 }, { it.x0 }))) {
            val cy = (w.y0 + w.y1) / 2
            val h = w.y1 - w.y0
            val last = bounds.lastOrNull()
            if (last != null && cy >= last[0] - 0.1f * h && cy <= last[1] + 0.1f * h) {
                rows.last().add(w)
                last[0] = minOf(last[0], w.y0); last[1] = maxOf(last[1], w.y1)
            } else {
                rows.add(mutableListOf(w)); bounds.add(floatArrayOf(w.y0, w.y1))
            }
        }
        for (r in rows) r.sortBy { it.x0 }
        return rows
    }

    /** Plain text of rows; wide gaps become several spaces so table columns stay apart. */
    fun rowsToText(rows: List<List<Word>>, keepColumns: Boolean = true): String = rows.joinToString("\n") { row ->
        val sb = StringBuilder()
        var prev: Word? = null
        for (w in row) {
            val p = prev
            if (p != null) {
                val gap = w.x0 - p.x1
                val charW = maxOf(1f, (p.x1 - p.x0) / maxOf(1, p.text.length))
                sb.append(if (keepColumns && gap > 2 * charW) "    " else " ")
            }
            sb.append(w.text)
            prev = w
        }
        sb.toString()
    }

    private fun hex4(v: Int) = String.format("%04X", v and 0xFFFF)

    private fun fmt(v: Float): String = String.format(java.util.Locale.US, "%.4f", v)

    /** Row-vector affine matrices [a b c d e f]: first `x`, then `y`. */
    fun concat(x: FloatArray, y: FloatArray): FloatArray = floatArrayOf(
        x[0] * y[0] + x[1] * y[2], x[0] * y[1] + x[1] * y[3],
        x[2] * y[0] + x[3] * y[2], x[2] * y[1] + x[3] * y[3],
        x[4] * y[0] + x[5] * y[2] + y[4], x[4] * y[1] + x[5] * y[3] + y[5],
    )

    fun invert(m: FloatArray): FloatArray {
        val det = m[0] * m[3] - m[1] * m[2]
        if (det == 0f) return floatArrayOf(1f, 0f, 0f, 1f, 0f, 0f)
        val a = m[3] / det; val b = -m[1] / det; val c = -m[2] / det; val d = m[0] / det
        return floatArrayOf(a, b, c, d, -m[4] * a - m[5] * c, -m[4] * b - m[5] * d)
    }
}
