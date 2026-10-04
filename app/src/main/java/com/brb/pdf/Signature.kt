package com.brb.pdf

import android.app.AlertDialog
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.net.Uri
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import android.view.MotionEvent
import android.view.View
import android.widget.LinearLayout
import java.io.File
import kotlin.math.max
import kotlin.math.min

/** The document the viewer has open, shared with the Pages screen. */
object DocStore {
    var engine: PdfEngine? = null
    var sourceUri: Uri? = null
    /** Page the Pages screen asked the viewer to show (-1 = none). */
    var gotoPage = -1
}

/**
 * Finger signature pad. The result is a PICTURE of a signature (with a clear
 * background). It is NOT a digital / cryptographic signature and the app
 * never says it is.
 */
class SignaturePad(context: Context) : View(context) {
    private val strokes = ArrayList<Path>()
    private var current: Path? = null
    private val bounds = RectF()
    private var hasInk = false
    private var hasBounds = false
    var inkColor = Color.rgb(15, 40, 140)
        set(v) { field = v; paint.color = v; invalidate() }
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
        strokeWidth = context.dp(3).toFloat(); color = inkColor
    }
    private val guide = Paint().apply { color = Color.rgb(170, 170, 170); strokeWidth = context.dp(1).toFloat() }

    val isEmpty get() = !hasInk

    fun clear() { strokes.clear(); current = null; hasInk = false; hasBounds = false; bounds.setEmpty(); invalidate() }

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(Color.WHITE)
        val y = height * 0.75f
        canvas.drawLine(width * 0.06f, y, width * 0.94f, y, guide)
        for (s in strokes) canvas.drawPath(s, paint)
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        parent?.requestDisallowInterceptTouchEvent(true)
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                current = Path().apply { moveTo(e.x, e.y) }
                strokes.add(current!!)
                grow(e.x, e.y)
            }
            MotionEvent.ACTION_MOVE -> {
                for (h in 0 until e.historySize) { current?.lineTo(e.getHistoricalX(h), e.getHistoricalY(h)); grow(e.getHistoricalX(h), e.getHistoricalY(h)) }
                current?.lineTo(e.x, e.y); grow(e.x, e.y); hasInk = true
            }
            MotionEvent.ACTION_UP -> { current?.lineTo(e.x + 0.1f, e.y + 0.1f); hasInk = true; current = null }
        }
        invalidate()
        return true
    }

    private fun grow(x: Float, y: Float) {
        if (!hasBounds) { bounds.set(x, y, x + 1, y + 1); hasBounds = true }
        else bounds.union(x, y)
    }

    /** The signature cut to its own size, transparent background. */
    fun toBitmap(): Bitmap {
        val pad = paint.strokeWidth * 2
        val l = max(0f, bounds.left - pad); val t = max(0f, bounds.top - pad)
        val r = min(width.toFloat(), bounds.right + pad); val b = min(height.toFloat(), bounds.bottom + pad)
        val k = 2f            // draw at double resolution for a sharp print
        val bmp = Bitmap.createBitmap(max(1, ((r - l) * k).toInt()), max(1, ((b - t) * k).toInt()), Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        c.scale(k, k); c.translate(-l, -t)
        for (s in strokes) c.drawPath(s, paint)
        return bmp
    }

    companion object {
        fun savedFile(ctx: Context) = File(ctx.filesDir, "my_signature.png")

        fun loadSaved(ctx: Context): Bitmap? = savedFile(ctx).takeIf { it.exists() }?.let { BitmapFactory.decodeFile(it.absolutePath) }

        /**
         * Ask for a signature. Offers the saved one (if any), or a pad to draw a new one.
         * `done` gets the picture.
         */
        fun ask(ctx: Context, done: (Bitmap) -> Unit) {
            val saved = loadSaved(ctx)
            if (saved != null) {
                ctx.askChoice("Signature", listOf("Use my saved signature", "Draw a new signature", "Delete saved signature")) { k ->
                    when (k) {
                        0 -> done(saved)
                        1 -> draw(ctx, done)
                        2 -> { savedFile(ctx).delete(); ctx.toast("Saved signature deleted.") }
                    }
                }
            } else draw(ctx, done)
        }

        private fun draw(ctx: Context, done: (Bitmap) -> Unit) {
            val pad = SignaturePad(ctx)
            val remember = ctx.checkBox("Remember this signature on this phone", true)
            val note = ctx.label("This places a picture of your signature on the page. It is not a digital " +
                "(cryptographic) signature and does not by itself make the document legally signed.", 12f,
                color = Color.rgb(120, 120, 120))
            val colors = ctx.hbox()
            for ((name, c) in listOf("Blue" to Color.rgb(15, 40, 140), "Black" to Color.BLACK)) {
                colors.addView(ctx.button(name) { pad.inkColor = c })
            }
            colors.addView(ctx.button("Clear") { pad.clear() })
            val box = ctx.vbox(12).apply {
                addView(pad, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, ctx.dp(200)))
                addView(colors, lp())
                addView(remember, lp())
                addView(note, lp())
            }
            val dlg = AlertDialog.Builder(ctx).setTitle("Sign with your finger").setView(box)
                .setPositiveButton("Use", null).setNegativeButton("Cancel", null).create()
            dlg.setOnShowListener {
                dlg.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                    if (pad.isEmpty) { ctx.toast("Draw your signature first."); return@setOnClickListener }
                    val bmp = pad.toBitmap()
                    if (remember.isChecked) try {
                        savedFile(ctx).outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
                    } catch (_: Exception) { }
                    dlg.dismiss()
                    done(bmp)
                }
            }
            dlg.show()
        }

        /**
         * Draw text (any language - Bengali and Hindi included, using the phone's fonts)
         * into a transparent picture. Used for text boxes in scripts the built-in PDF
         * fonts cannot show.
         */
        fun textPicture(text: String, sizePt: Float, color: Int, maxWidthPt: Float): Bitmap {
            val k = 4f                         // pixels per point, sharp when printed
            val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = sizePt * k; this.color = color }
            val natural = text.lines().maxOf { paint.measureText(it) }
            val w = min(natural, maxWidthPt * k).toInt().coerceAtLeast(1) + 2
            val layout = StaticLayout.Builder.obtain(text, 0, text.length, paint, w)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL).setIncludePad(true).build()
            val bmp = Bitmap.createBitmap(w, max(1, layout.height), Bitmap.Config.ARGB_8888)
            layout.draw(Canvas(bmp))
            return bmp
        }

        /** True when the text has letters the standard PDF fonts cannot show (Bengali, Hindi...). */
        fun needsPicture(text: String): Boolean =
            text.any { it.code > 0x24F && !it.isWhitespace() && it.code !in 0x2000..0x206F && it.code != 0x20AC }
    }
}
