package com.brb.pdf

import android.graphics.Bitmap
import com.artifex.mupdf.fitz.Image
import com.artifex.mupdf.fitz.PDFAnnotation
import com.artifex.mupdf.fitz.PDFPage
import com.artifex.mupdf.fitz.Point
import com.artifex.mupdf.fitz.Quad
import com.artifex.mupdf.fitz.Rect
import java.io.ByteArrayOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Creating and changing comments (PDF annotations). These run on the engine
 * thread, inside PdfEngine.edit { } so every change is undoable.
 * Coordinates: page space (points, as seen on screen).
 */
object Annots {
    const val AUTHOR = "BRB PDF"

    val OFFICE_STAMPS = listOf("PAID", "RECEIVED", "VERIFIED", "ORIGINAL SEEN", "APPROVED", "REJECTED",
        "COPY", "CONFIDENTIAL", "DRAFT")

    private fun finish(a: PDFAnnotation, opacity: Float = 1f, contents: String? = null) {
        a.author = AUTHOR
        a.modificationDate = Date()
        if (contents != null) a.contents = contents
        if (opacity < 1f) a.opacity = opacity
        a.update()
    }

    private fun rgb(c: FloatArray) = floatArrayOf(c[0], c[1], c[2])

    fun markup(page: PDFPage, type: Int, quads: List<Quad>, color: FloatArray, opacity: Float): Int {
        if (quads.isEmpty()) throw UserError("No text was selected. Drag over the words.")
        val a = page.createAnnotation(type)
        a.quadPoints = quads.toTypedArray()
        a.color = rgb(color)
        finish(a, opacity)
        return a.getObject().asIndirect()
    }

    fun note(page: PDFPage, at: Point, text: String, color: FloatArray): Int {
        val a = page.createAnnotation(PDFAnnotation.TYPE_TEXT)
        a.rect = Rect(at.x, at.y, at.x + 20f, at.y + 20f)
        a.icon = "Comment"
        a.color = rgb(color)
        finish(a, 1f, text)
        return a.getObject().asIndirect()
    }

    /** A typed text box (English / Latin letters). */
    fun textBox(page: PDFPage, rect: Rect, text: String, size: Float, color: FloatArray, border: Boolean): Int {
        val a = page.createAnnotation(PDFAnnotation.TYPE_FREE_TEXT)
        a.rect = rect
        a.contents = text
        a.setDefaultAppearance("Helv", size, rgb(color))
        a.borderWidth = if (border) 1f else 0f
        finish(a, 1f, text)
        return a.getObject().asIndirect()
    }

    /** Office stamp: red framed text with today's date, e.g. PAID 01-10-2026. */
    fun officeStamp(page: PDFPage, at: Point, name: String, withDate: Boolean, color: FloatArray): Int {
        val text = if (withDate) "$name\n" + SimpleDateFormat("dd-MM-yyyy", Locale.US).format(Date()) else name
        val size = 16f
        val w = maxOf(120f, name.length * size * 0.62f + 24f)
        val h = if (withDate) size * 2.9f else size * 1.9f
        val a = page.createAnnotation(PDFAnnotation.TYPE_FREE_TEXT)
        a.rect = Rect(at.x, at.y, at.x + w, at.y + h)
        a.contents = text
        a.setDefaultAppearance("Helv", size, rgb(color))
        a.quadding = 1                       // centred
        a.borderWidth = 2.5f
        a.subject = "Stamp"
        finish(a, 1f, text)
        return a.getObject().asIndirect()
    }

    /** A picture placed as a stamp (signature, seal, or text in Bengali/Hindi drawn as a picture). */
    fun imageStamp(page: PDFPage, rect: Rect, bitmap: Bitmap, subject: String): Int {
        val bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        val a = page.createAnnotation(PDFAnnotation.TYPE_STAMP)
        a.rect = rect
        a.setStampImage(Image(bytes))
        a.subject = subject
        finish(a)
        return a.getObject().asIndirect()
    }

    fun shape(page: PDFPage, type: Int, rect: Rect, color: FloatArray, width: Float, fill: FloatArray?): Int {
        if (rect.x1 - rect.x0 < 2 || rect.y1 - rect.y0 < 2) throw UserError("Drag to draw the shape.")
        val a = page.createAnnotation(type)
        a.rect = rect
        a.color = rgb(color)
        a.interiorColor = fill?.let { rgb(it) } ?: FloatArray(0)
        a.borderWidth = width
        finish(a)
        return a.getObject().asIndirect()
    }

    fun line(page: PDFPage, p1: Point, p2: Point, color: FloatArray, width: Float, arrow: Boolean): Int {
        val a = page.createAnnotation(PDFAnnotation.TYPE_LINE)
        a.setLine(p1, p2)
        a.color = rgb(color)
        a.interiorColor = rgb(color)
        a.borderWidth = width
        if (arrow) a.setLineEndingStyles(PDFAnnotation.LINE_ENDING_NONE, PDFAnnotation.LINE_ENDING_CLOSED_ARROW)
        finish(a)
        return a.getObject().asIndirect()
    }

    fun ink(page: PDFPage, strokes: List<List<Point>>, color: FloatArray, width: Float): Int {
        val good = strokes.filter { it.size >= 2 }
        if (good.isEmpty()) throw UserError("Draw with your finger.")
        val a = page.createAnnotation(PDFAnnotation.TYPE_INK)
        a.inkList = good.map { it.toTypedArray() }.toTypedArray()
        a.color = rgb(color)
        a.borderWidth = width
        finish(a)
        return a.getObject().asIndirect()
    }

    fun redactMark(page: PDFPage, rect: Rect): Int {
        if (rect.x1 - rect.x0 < 2 || rect.y1 - rect.y0 < 2) throw UserError("Drag over the area to redact.")
        val a = page.createAnnotation(PDFAnnotation.TYPE_REDACT)
        a.rect = rect
        finish(a)
        return a.getObject().asIndirect()
    }

    // ----------------------------------------------------------------- change
    fun move(a: PDFAnnotation, dx: Float, dy: Float) {
        when (a.type) {
            PDFAnnotation.TYPE_HIGHLIGHT, PDFAnnotation.TYPE_UNDERLINE, PDFAnnotation.TYPE_STRIKE_OUT,
            PDFAnnotation.TYPE_SQUIGGLY -> throw UserError("Highlights belong to their text and cannot be moved.")
            PDFAnnotation.TYPE_INK -> {
                val list = a.inkList.map { s -> s.map { Point(it.x + dx, it.y + dy) }.toTypedArray() }.toTypedArray()
                a.inkList = list
            }
            PDFAnnotation.TYPE_LINE -> {
                val l = a.line
                a.setLine(Point(l[0].x + dx, l[0].y + dy), Point(l[1].x + dx, l[1].y + dy))
            }
            PDFAnnotation.TYPE_POLYGON, PDFAnnotation.TYPE_POLY_LINE -> {
                a.vertices = a.vertices.map { Point(it.x + dx, it.y + dy) }.toTypedArray()
            }
            else -> {
                val r = a.rect
                a.rect = Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)
            }
        }
        a.modificationDate = Date()
        a.update()
    }

    fun resize(a: PDFAnnotation, rect: Rect) {
        if (rect.x1 - rect.x0 < 6 || rect.y1 - rect.y0 < 6) throw UserError("Too small.")
        a.rect = rect
        a.modificationDate = Date()
        a.update()
    }

    fun recolor(a: PDFAnnotation, color: FloatArray) {
        if (a.type == PDFAnnotation.TYPE_FREE_TEXT) {
            val da = a.defaultAppearance
            a.setDefaultAppearance(da?.font ?: "Helv", if (da != null && da.size > 0) da.size else 11f, rgb(color))
        } else {
            a.color = rgb(color)
            if (a.type == PDFAnnotation.TYPE_LINE) a.interiorColor = rgb(color)
        }
        a.update()
    }

    fun setText(a: PDFAnnotation, text: String) {
        a.contents = text
        a.modificationDate = Date()
        a.update()
    }
}
