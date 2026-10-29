package com.brb.pdf

import com.artifex.mupdf.fitz.Font
import com.artifex.mupdf.fitz.Image
import com.artifex.mupdf.fitz.Matrix
import com.artifex.mupdf.fitz.PDFPage
import com.artifex.mupdf.fitz.Point
import com.artifex.mupdf.fitz.Quad
import com.artifex.mupdf.fitz.Rect
import com.artifex.mupdf.fitz.StructuredTextWalker
import java.util.Locale

/**
 * The text of PDF pages as an editable Word-like document (HTML for the editor):
 * same sizes, bold / italic, colours, centred titles, indents; running lines are joined into paragraphs
 * (so they re-flow when edited) and column rows (bank statements, forms) become tables.
 * Includes OCR text. Runs on the engine thread.
 */
object PdfToWord {

    private class Ch(val c: Int, val q: Quad, val size: Float, val font: Font, val argb: Int)

    private class Run(val text: String, val size: Float, val bold: Boolean, val italic: Boolean,
                      val family: String, val color: Int)

    private class Seg(val x0: Float, val x1: Float, val runs: List<Run>) {
        val text get() = runs.joinToString("") { it.text }
        val size get() = runs.maxOf { it.size }
    }

    private class Line(val y: Float, val segs: MutableList<Seg>) {
        val x0 get() = segs.first().x0
        val x1 get() = segs.last().x1
        val size get() = segs.maxOf { it.size }
    }

    class Result(val html: String, val page: Docx.Page, val emptyPages: List<Int>)

    fun convert(pages: List<PDFPage>, numbers: List<Int>): Result {
        val all = pages.map { lines(it) }
        val first = pages.firstOrNull()?.bounds ?: Rect(0f, 0f, 595f, 842f)
        val pw = first.x1 - first.x0
        val ph = first.y1 - first.y0
        val lefts = all.flatten().map { it.x0 - first.x0 }
        val rights = all.flatten().map { first.x1 - it.x1 }
        val ml = (lefts.minOrNull() ?: 72f).coerceIn(18f, 90f)
        val mr = (rights.minOrNull() ?: 72f).coerceIn(18f, 90f)
        val page = Docx.Page(pw, ph, ml, 36f, mr, 36f)
        val html = StringBuilder()
        val empty = ArrayList<Int>()
        for ((k, lines) in all.withIndex()) {
            if (k > 0) html.append("<hr class=\"pb\">")
            val b = pages[k].bounds
            if (lines.isEmpty()) {
                empty.add(numbers[k])
                html.append("<p style=\"color:#a03c00\">[Page ${numbers[k] + 1} has no text. If it is a scanned page, " +
                    "run OCR on the PDF first.]</p>")
                continue
            }
            pageHtml(lines, b.x0 + ml, b.x1 - mr, (b.x0 + b.x1) / 2, html)
        }
        if (html.isEmpty()) html.append("<p><br></p>")
        return Result(html.toString(), page, empty)
    }

    // ------------------------------------------------------------ reading
    private fun lines(page: PDFPage): List<Line> {
        val st = page.toStructuredText("preserve-whitespace")
        val out = ArrayList<Line>()
        try {
            var cur = ArrayList<Ch>()
            var horizontal = true
            st.walk(object : StructuredTextWalker {
                override fun onImageBlock(bbox: Rect, transform: Matrix, image: Image) {}
                override fun beginTextBlock(bbox: Rect, flags: Int) {}
                override fun endTextBlock() {}
                override fun beginLine(bbox: Rect, wmode: Int, dir: Point) {
                    cur = ArrayList(); horizontal = Math.abs(dir.y) < 0.05f && dir.x > 0
                }
                override fun endLine() { if (horizontal) line(cur)?.let { out.add(it) } }
                override fun onChar(c: Int, origin: Point, font: Font, size: Float, q: Quad, argb: Int, flags: Int, bidi: Int) {
                    cur.add(Ch(c, q, size, font, argb))
                }
                override fun beginStruct(standard: String?, raw: String?, index: Int) {}
                override fun endStruct() {}
                override fun onVector(bbox: Rect, info: StructuredTextWalker.VectorInfo, argb: Int) {}
            })
        } finally {
            st.destroy()
        }
        // pieces on the same baseline (MuPDF may give table columns as separate lines) form one row
        out.sortWith(compareBy({ it.y }, { it.x0 }))
        val rows = ArrayList<Line>()
        for (l in out) {
            val last = rows.lastOrNull()
            if (last != null && Math.abs(last.y - l.y) < 0.35f * Math.max(last.size, l.size)) {
                last.segs.addAll(l.segs); last.segs.sortBy { it.x0 }
            } else rows.add(l)
        }
        return rows
    }

    private fun sizeOf(ch: Ch): Float {
        val h = Math.abs(ch.q.ll_y - ch.q.ul_y)
        return if (ch.font.name?.contains("Glyphless", true) == true) Math.max(4f, h * 0.8f) else ch.size
    }

    private fun line(chars: List<Ch>): Line? {
        if (chars.none { !Character.isWhitespace(it.c) }) return null
        val segs = ArrayList<Seg>()
        var cur = ArrayList<Ch>()
        fun flush() {
            val t = cur.dropWhile { Character.isWhitespace(it.c) }.dropLastWhile { Character.isWhitespace(it.c) }
            if (t.isNotEmpty()) segs.add(Seg(Math.min(t.first().q.ul_x, t.first().q.ll_x),
                Math.max(t.last().q.ur_x, t.last().q.lr_x), runs(t)))
            cur = ArrayList()
        }
        var prev: Ch? = null
        for (ch in chars) {
            val p = prev
            if (p != null) {
                val gap = Math.min(ch.q.ul_x, ch.q.ll_x) - Math.max(p.q.ur_x, p.q.lr_x)
                if (gap > 1.6f * Math.max(sizeOf(p), sizeOf(ch))) flush()
            }
            cur.add(ch); prev = ch
        }
        flush()
        if (segs.isEmpty()) return null
        val base = chars.filter { !Character.isWhitespace(it.c) }.map { Math.max(it.q.ll_y, it.q.lr_y) }.sorted()
        return Line(base[base.size / 2], segs)
    }

    private fun runs(chars: List<Ch>): List<Run> {
        val out = ArrayList<Run>()
        var sb = StringBuilder()
        var key: Run? = null
        for (ch in chars) {
            val f = ch.font
            val name = f.name ?: ""
            val bold = f.isBold || name.contains("Bold", true) || name.contains("Black", true) || name.contains("Heavy", true)
            val italic = f.isItalic || name.contains("Italic", true) || name.contains("Oblique", true)
            val mono = f.isMono || name.contains("Courier", true) || name.contains("Mono", true)
            val serif = !mono && (f.isSerif || name.contains("Times", true) || name.contains("Roman", true) ||
                (name.contains("Serif", true) && !name.contains("Sans", true)) || name.contains("Georgia", true) ||
                name.contains("Cambria", true) || name.contains("Garamond", true))
            val fam = when { mono -> "Courier New"; serif -> "Times New Roman"; else -> "Arial" }
            val size = Math.round(sizeOf(ch) * 2) / 2f
            val color = ch.argb and 0xFFFFFF
            val k = key
            if (k == null || k.size != size || k.bold != bold || k.italic != italic || k.family != fam || k.color != color) {
                if (k != null && sb.isNotEmpty()) out.add(Run(sb.toString(), k.size, k.bold, k.italic, k.family, k.color))
                sb = StringBuilder()
                key = Run("", size, bold, italic, fam, color)
            }
            sb.appendCodePoint(ch.c)
        }
        key?.let { if (sb.isNotEmpty()) out.add(Run(sb.toString(), it.size, it.bold, it.italic, it.family, it.color)) }
        return out
    }

    // ------------------------------------------------------------ writing
    private fun f(v: Float) = String.format(Locale.US, "%.1f", v).removeSuffix(".0")

    private fun span(r: Run): String {
        val css = StringBuilder("font-size:${f(r.size)}pt;font-family:'${r.family}';")
        if (r.bold) css.append("font-weight:bold;")
        if (r.italic) css.append("font-style:italic;")
        if (r.color != 0) css.append(String.format("color:#%06X;", r.color))
        return "<span style=\"$css\">${Docx.esc(r.text)}</span>"
    }

    private fun pageHtml(lines: List<Line>, left: Float, right: Float, center: Float, out: StringBuilder) {
        var k = 0
        var prevBottom = lines.first().y - lines.first().size
        while (k < lines.size) {
            // a run of rows with several columns -> a table
            if (lines[k].segs.size >= 2) {
                var e = k
                while (e < lines.size && lines[e].segs.size >= 2 &&
                    (e == k || lines[e].y - lines[e - 1].y < 3.2f * lines[e].size)) e++
                if (e - k >= 2) {
                    val gapPt = (lines[k].y - lines[k].size - prevBottom).coerceIn(0f, 24f)
                    table(lines.subList(k, e), left, right, gapPt, out)
                    prevBottom = lines[e - 1].y + lines[e - 1].size * 0.25f
                    k = e
                    continue
                }
            }
            // a paragraph: following lines join while they continue it
            val first = lines[k]
            val centred = isCentred(first, left, right, center)
            val para = arrayListOf(first)
            var e = k + 1
            while (e < lines.size && !centred) {
                val p = para.last(); val n = lines[e]
                val sameLook = Math.abs(n.size - p.size) < 0.6f && n.segs.size == 1 && p.segs.size == 1
                val close = n.y - p.y < 1.75f * p.size
                val fullPrev = p.x1 > right - 4f * p.size
                val aligned = Math.abs(n.x0 - first.x0) < 3f * p.size || (para.size == 1 && n.x0 < first.x0)
                if (sameLook && close && fullPrev && aligned && !isCentred(n, left, right, center)) { para.add(n); e++ } else break
            }
            val gap = (first.y - first.size - prevBottom).coerceIn(0f, 24f)
            val style = StringBuilder("margin-top:${f(gap * 0.8f)}pt;")
            if (centred) style.append("text-align:center;")
            else {
                val ind = para.map { it.x0 }.minOrNull()!! - left
                if (ind > 3f) style.append("margin-left:${f(ind)}pt;")
                if (para.size > 1 && first.x0 - para[1].x0 > 3f) style.append("text-indent:${f(first.x0 - para[1].x0)}pt;")
            }
            val tag = if (first.size >= 15f && para.size == 1) "h2" else "p"
            out.append("<$tag style=\"$style\">")
            for ((j, l) in para.withIndex()) {
                if (j > 0) out.append(" ")
                for ((s, seg) in l.segs.withIndex()) {
                    if (s > 0) out.append("\t")
                    for (r in seg.runs) out.append(span(r))
                }
            }
            out.append("</$tag>")
            prevBottom = para.last().y + para.last().size * 0.25f
            k = e
        }
    }

    private fun isCentred(l: Line, left: Float, right: Float, center: Float): Boolean {
        val mid = (l.x0 + l.x1) / 2
        return l.segs.size == 1 && Math.abs(mid - center) < 20f && l.x0 > left + 30f && l.x1 < right - 30f
    }

    private fun table(rows: List<Line>, left: Float, right: Float, gap: Float, out: StringBuilder) {
        // column starts: cluster every piece's left edge
        val xs = rows.flatMap { r -> r.segs.map { it.x0 } }.sorted()
        val starts = ArrayList<Float>()
        for (x in xs) if (starts.isEmpty() || x - starts.last() > 14f) starts.add(x)
        val tableLeft = Math.min(starts.first(), left)
        val bounds = starts.toMutableList().also { it[0] = tableLeft }
        val widths = bounds.indices.map { i -> ((if (i + 1 < bounds.size) bounds[i + 1] else right) - bounds[i]).coerceAtLeast(14f) }
        out.append("<table class=\"t nb\" style=\"margin-top:${f(gap * 0.8f)}pt\"><colgroup>")
        for (w in widths) out.append("<col style=\"width:${f(w)}pt\">")
        out.append("</colgroup>")
        for (r in rows) {
            val cells = Array(bounds.size) { ArrayList<Seg>() }
            for (s in r.segs) {
                var c = 0
                for (i in bounds.indices) if (bounds[i] <= s.x0 + 6f) c = i
                cells[c].add(s)
            }
            out.append("<tr>")
            for (c in cells) {
                out.append("<td><p>")
                if (c.isEmpty()) out.append("<br>")
                for ((j, s) in c.withIndex()) {
                    if (j > 0) out.append(" ")
                    for (run in s.runs) out.append(span(run))
                }
                out.append("</p></td>")
            }
            out.append("</tr>")
        }
        out.append("</table>")
    }
}
