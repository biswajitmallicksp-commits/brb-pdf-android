package com.brb.pdf

import android.graphics.Bitmap
import android.graphics.Color
import com.artifex.mupdf.fitz.Font
import com.artifex.mupdf.fitz.Image
import com.artifex.mupdf.fitz.Matrix
import com.artifex.mupdf.fitz.PDFAnnotation
import com.artifex.mupdf.fitz.PDFDocument
import com.artifex.mupdf.fitz.PDFObject
import com.artifex.mupdf.fitz.PDFPage
import com.artifex.mupdf.fitz.Point
import com.artifex.mupdf.fitz.Quad
import com.artifex.mupdf.fitz.Rect
import com.artifex.mupdf.fitz.StructuredTextWalker
import java.io.ByteArrayOutputStream
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction

/**
 * Real text editing: delete or rewrite a line (or a piece of a line) of a PDF page.
 *
 * How it works (runs on the engine thread inside one undoable edit):
 *  1. the old words are REMOVED from the page content (a text-only redaction, so
 *     pictures, table lines and other text stay exactly as they were);
 *  2. the new words are written at the same place, same size and colour, in the
 *     closest standard PDF font (Helvetica / Times / Courier, normal or bold).
 *     Text with letters those fonts lack (Bengali, Hindi, the Rupee sign...) is
 *     written as a sharp picture drawn with the phone's fonts.
 * Coordinates are MuPDF page space (as seen on screen).
 */
object TextEdit {

    /** One editable piece of text: a line, or a part of a line separated by a wide gap (table columns). */
    data class Seg(
        val id: Int, val page: Int, val text: String, val rect: Rect,
        val baseX: Float, val baseY: Float, val size: Float,
        val bold: Boolean, val italic: Boolean, val serif: Boolean, val mono: Boolean,
        val color: Int, val editable: Boolean,
    )

    data class Change(val seg: Seg, val newText: String)

    private class C(val c: Int, val q: Quad, val origin: Point, val size: Float, val font: Font, val argb: Int)

    /** Read the page's text as editable pieces (engine thread). */
    fun segments(page: PDFPage, pageNo: Int): List<Seg> {
        val st = page.toStructuredText("preserve-whitespace")
        val out = ArrayList<Seg>()
        try {
            var line = ArrayList<C>()
            var dir = Point(1f, 0f)
            st.walk(object : StructuredTextWalker {
                override fun onImageBlock(bbox: Rect, transform: Matrix, image: Image) {}
                override fun beginTextBlock(bbox: Rect, flags: Int) {}
                override fun endTextBlock() {}
                override fun beginLine(bbox: Rect, wmode: Int, d: Point) { line = ArrayList(); dir = d }
                override fun endLine() { split(line, dir, pageNo, out) }
                override fun onChar(c: Int, origin: Point, font: Font, size: Float, q: Quad, argb: Int, flags: Int, bidi: Int) {
                    line.add(C(c, q, origin, size, font, argb))
                }
                override fun beginStruct(standard: String?, raw: String?, index: Int) {}
                override fun endStruct() {}
                override fun onVector(bbox: Rect, info: StructuredTextWalker.VectorInfo, argb: Int) {}
            })
        } finally {
            st.destroy()
        }
        return out
    }

    private fun split(chars: List<C>, dir: Point, pageNo: Int, out: MutableList<Seg>) {
        val horizontal = Math.abs(dir.y) < 0.05f && dir.x > 0
        var cur = ArrayList<C>()
        fun flush() {
            val ink = cur.filter { !Character.isWhitespace(it.c) }
            // invisible OCR text (our glyphless font) is not part of the visible page
            if (ink.isNotEmpty() && ink.none { it.font.name.contains("Glyphless", true) }) {
                val first = ink.first()
                val trimmed = cur.dropWhile { Character.isWhitespace(it.c) }.dropLastWhile { Character.isWhitespace(it.c) }
                val text = String(trimmed.map { it.c }.toIntArray(), 0, trimmed.size)
                val r = Rect(first.q)
                for (ch in ink) r.union(Rect(ch.q))
                val f = first.font
                val name = f.name ?: ""
                val bold = f.isBold || name.contains("Bold", true) || name.contains("Black", true) || name.contains("Heavy", true)
                val italic = f.isItalic || name.contains("Italic", true) || name.contains("Oblique", true)
                val mono = f.isMono || name.contains("Courier", true) || name.contains("Mono", true)
                val serif = !mono && (f.isSerif || name.contains("Times", true) || name.contains("Roman", true) ||
                    (name.contains("Serif", true) && !name.contains("Sans", true)) || name.contains("Georgia", true) ||
                    name.contains("Cambria", true) || name.contains("Garamond", true) || name.contains("Book", true))
                val size = ink.groupingBy { Math.round(it.size * 2) / 2f }.eachCount().maxByOrNull { it.value }?.key ?: first.size
                out.add(Seg(out.size, pageNo, text, r, first.origin.x, first.origin.y, size, bold, italic, serif, mono,
                    first.argb, horizontal))
            }
            cur = ArrayList()
        }
        var prev: C? = null
        for (ch in chars) {
            val p = prev
            if (p != null && horizontal) {
                val gap = Math.min(ch.q.ul_x, ch.q.ll_x) - Math.max(p.q.ur_x, p.q.lr_x)
                if (gap > 1.6f * Math.max(p.size, ch.size)) flush()        // a different column
            }
            cur.add(ch)
            prev = ch
        }
        flush()
    }

    // ---------------------------------------------------------------- apply
    private val CP1252: Charset = Charset.forName("windows-1252")

    private fun base14(s: Seg): String {
        val family = when { s.mono -> "Courier"; s.serif -> "Times"; else -> "Helvetica" }
        return when (family) {
            "Times" -> when { s.bold && s.italic -> "Times-BoldItalic"; s.bold -> "Times-Bold"; s.italic -> "Times-Italic"; else -> "Times-Roman" }
            else -> family + when { s.bold && s.italic -> "-BoldOblique"; s.bold -> "-Bold"; s.italic -> "-Oblique"; else -> "" }
        }
    }

    private fun encode1252(text: String): ByteArray? = try {
        CP1252.newEncoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
            .encode(java.nio.CharBuffer.wrap(text)).let { b -> ByteArray(b.remaining()).also { b.get(it) } }
    } catch (e: Exception) { null }

    /**
     * Apply the changes to one page. `picture` draws text the standard fonts cannot show
     * (returns a bitmap at 4 pixels per point).
     */
    fun apply(pdf: PDFDocument, page: PDFPage, changes: List<Change>,
              picture: (String, Float, Int) -> Bitmap): Int {
        if (changes.isEmpty()) return 0
        // 1. keep the user's own redaction marks out of the way
        val marks = ArrayList<Rect>()
        for (a in page.annotations ?: emptyArray()) {
            if (a.type == PDFAnnotation.TYPE_REDACT) { marks.add(Rect(a.rect)); page.deleteAnnotation(a) }
        }
        // 2. remove the old words (text only)
        for (ch in changes) {
            val r = Rect(ch.seg.rect)
            val h = r.y1 - r.y0
            r.y0 += 0.2f * h; r.y1 -= 0.2f * h
            r.x0 += 0.1f; r.x1 -= 0.1f
            val a = page.createAnnotation(PDFAnnotation.TYPE_REDACT)
            a.rect = r
            a.update()
        }
        page.applyRedactions(false, PDFPage.REDACT_IMAGE_NONE, PDFPage.REDACT_LINE_ART_NONE, PDFPage.REDACT_TEXT_REMOVE)

        // 3. write the new words
        val pageObj = page.getObject()
        val ctm = page.transform
        val inv = TextLayer.invert(floatArrayOf(ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f))
        val res = resources(pdf, pageObj)
        val sb = StringBuilder()
        var written = 0
        val usedFonts = HashMap<String, Pair<String, Font>>()
        for ((k, ch) in changes.withIndex()) {
            val text = ch.newText.replace('\n', ' ').trimEnd()
            if (text.isBlank()) continue
            val s = ch.seg
            val rgb = floatArrayOf(Color.red(s.color) / 255f, Color.green(s.color) / 255f, Color.blue(s.color) / 255f)
            val bytes = encode1252(text)
            if (bytes != null) {
                val name = base14(s)
                val (key, font) = usedFonts.getOrPut(name) {
                    val f = Font(name)
                    val key = "BRBE" + name.replace("-", "")
                    dict(pdf, res, "Font").put(key, pdf.addSimpleFont(f, 0))
                    key to f
                }
                var natural = 0f
                for (cp in text.codePoints().toArray()) natural += font.advanceGlyph(Math.max(0, font.encodeCharacter(cp)), false)
                natural *= s.size
                val orig = s.rect.x1 - s.rect.x0
                val hscale = if (natural > orig * 1.02f && orig > 0f) Math.max(0.7f, orig / natural) else 1f
                val g = floatArrayOf(s.size * hscale, 0f, 0f, -s.size, s.baseX, s.baseY)
                val m = TextLayer.concat(g, inv)
                sb.append("BT ").append(f(rgb[0])).append(' ').append(f(rgb[1])).append(' ').append(f(rgb[2]))
                    .append(" rg /").append(key).append(" 1 Tf ")
                for (v in m) sb.append(f(v)).append(' ')
                sb.append("Tm <")
                for (b in bytes) sb.append(String.format("%02X", b.toInt() and 0xFF))
                sb.append("> Tj ET\n")
            } else {
                // letters the standard fonts do not have: draw them as a picture
                val bmp = picture(text, s.size, s.color)
                val w = bmp.width / 4f; val h = bmp.height / 4f
                val top = s.baseY - s.size * 0.95f
                val bytesPng = ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
                val key = "BRBEImg${System.nanoTime() % 1000000}_$k"
                dict(pdf, res, "XObject").put(key, pdf.addImage(Image(bytesPng)))
                // unit square -> page rectangle (y flipped), then -> PDF space
                val g = floatArrayOf(w, 0f, 0f, -h, s.baseX, top + h)
                val m = TextLayer.concat(g, inv)
                sb.append("q ")
                for (v in m) sb.append(f(v)).append(' ')
                sb.append("cm /").append(key).append(" Do Q\n")
            }
            written++
        }
        if (sb.isNotEmpty()) TextLayer.appendContent(pdf, pageObj, sb.toString())

        // 4. put the user's redaction marks back
        for (r in marks) Annots.redactMark(page, r)
        page.update()
        return written
    }

    private fun resources(pdf: PDFDocument, pageObj: PDFObject): PDFObject {
        var res = pageObj.getInheritable("Resources")
        if (res == null || res.isNull) { res = pdf.newDictionary(); pageObj.put("Resources", res) }
        else if (pageObj.get("Resources").isNull) {
            // inherited from a parent: give this page its own copy before changing it
            val own = pdf.newDictionary()
            for (k in res) own.put(k, res.get(k))
            pageObj.put("Resources", own); res = own
        }
        return res
    }

    private fun dict(pdf: PDFDocument, parent: PDFObject, key: String): PDFObject {
        var d = parent.get(key)
        if (d == null || d.isNull) { d = pdf.newDictionary(); parent.put(key, d) }
        return d.resolve()
    }

    private fun f(v: Float): String = String.format(java.util.Locale.US, "%.4f", v)
}
