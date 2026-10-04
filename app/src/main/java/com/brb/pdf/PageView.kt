package com.brb.pdf

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.os.Handler
import android.os.Looper
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.widget.OverScroller
import com.artifex.mupdf.fitz.Point
import com.artifex.mupdf.fitz.Quad
import com.artifex.mupdf.fitz.Rect
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Shows all pages one under the other: scroll with one finger, pinch to zoom,
 * double-tap to zoom in/out. Pages are drawn when they come into view; when
 * zoomed in, the visible part is re-drawn sharply after scrolling stops.
 *
 * In a tool mode (highlight, draw, rectangle...) one finger draws and two
 * fingers still scroll and zoom.
 */
class PageView(context: Context) : View(context) {

    enum class Tool { PAN, SELECT, HIGHLIGHT, UNDERLINE, STRIKE, PLACE, RECT, ELLIPSE, LINE, ARROW, INK, REDACT;
        val isText get() = this == SELECT || this == HIGHLIGHT || this == UNDERLINE || this == STRIKE
        val isDrag get() = this == RECT || this == ELLIPSE || this == REDACT
        val isLine get() = this == LINE || this == ARROW
    }

    interface Listener {
        fun onPageChanged(page: Int)
        fun onTapEmpty()
        fun onSelection(sel: PdfEngine.Selection?, finished: Boolean)
        fun onPlace(page: Int, at: Point)
        fun onRect(page: Int, rect: Rect)
        fun onLine(page: Int, a: Point, b: Point)
        fun onInkChanged(strokes: Int)
        fun onAnnotTapped(info: PdfEngine.AnnotInfo?)
        fun onAnnotMoved(info: PdfEngine.AnnotInfo, dx: Float, dy: Float)
        fun onAnnotResized(info: PdfEngine.AnnotInfo, rect: Rect)
        fun onLink(hit: PdfEngine.LinkHit)
    }

    var engine: PdfEngine? = null
        set(v) { field = v; clearBitmaps(); relayout(keepPosition = false); invalidate() }
    var listener: Listener? = null
    var tool: Tool = Tool.PAN
        set(v) { field = v; draft = null; if (v != Tool.INK) inkStrokes.clear(); invalidate() }
    var drawColor: FloatArray = floatArrayOf(0.85f, 0.1f, 0.1f)
    var nightMode = false
        set(v) { field = v; bmpPaint.colorFilter = if (v) INVERT else null; invalidate() }

    // overlays (set by the screen)
    var selection: PdfEngine.Selection? = null
        set(v) { field = v; invalidate() }
    var selectedAnnot: PdfEngine.AnnotInfo? = null
        set(v) { field = v; annotDrag = null; invalidate() }
    var searchHits: List<Pair<Int, Rect>> = emptyList()
        set(v) { field = v; invalidate() }
    var currentHit = -1
        set(v) { field = v; invalidate() }

    // ------------------------------------------------------------- layout
    private val gap = context.dp(8).toFloat()
    private val side = context.dp(6).toFloat()
    var zoom = 1f; private set
    private var scrollPosX = 0f
    private var scrollPosY = 0f
    private var tops = FloatArray(0)
    private var widthPx = 0f          // page width on screen (same for every page)
    private var contentH = 0f
    private var laidOutFor = -1       // view width the layout was made for
    var currentPage = 0; private set

    private fun sizes() = engine?.sizes ?: emptyList()
    private fun scaleOf(i: Int): Float = widthPx / sizes()[i].w
    private fun baseScaleOf(i: Int): Float = (width - 2 * side) / sizes()[i].w
    private fun pageH(i: Int): Float = sizes()[i].h * scaleOf(i)

    private fun relayout(keepPosition: Boolean) {
        val s = sizes()
        if (width == 0 || s.isEmpty()) { tops = FloatArray(0); contentH = 0f; return }
        // remember the point at the top of the screen
        var anchorPage = -1; var anchorFrac = 0f; var anchorX = 0f
        if (keepPosition && tops.size == s.size + 1 && widthPx > 0) {
            anchorPage = pageAtContentY(scrollPosY + height / 2f)
            anchorFrac = (scrollPosY + height / 2f - tops[anchorPage]) / max(1f, pageH(anchorPage))
            anchorX = (scrollPosX + width / 2f - side) / max(1f, widthPx)
        }
        widthPx = (width - 2 * side) * zoom
        tops = FloatArray(s.size + 1)
        var y = gap
        for (i in s.indices) { tops[i] = y; y += s[i].h * (widthPx / s[i].w) + gap }
        tops[s.size] = y
        contentH = y
        laidOutFor = width
        if (anchorPage >= 0 && anchorPage < s.size) {
            scrollPosY = tops[anchorPage] + anchorFrac * pageH(anchorPage) - height / 2f
            scrollPosX = side + anchorX * widthPx - width / 2f
        }
        clampScroll()
    }

    private fun clampScroll() {
        val maxX = max(0f, widthPx + 2 * side - width)
        val maxY = max(0f, contentH - height)
        scrollPosX = scrollPosX.coerceIn(0f, maxX)
        scrollPosY = scrollPosY.coerceIn(0f, maxY)
        val p = pageAtContentY(scrollPosY + height / 3f)
        if (p != currentPage && p >= 0) { currentPage = p; listener?.onPageChanged(p) }
    }

    private fun pageAtContentY(y: Float): Int {
        val n = sizes().size
        if (n == 0) return 0
        var lo = 0; var hi = n - 1
        while (lo < hi) {
            val mid = (lo + hi + 1) / 2
            if (tops[mid] - gap / 2 <= y) lo = mid else hi = mid - 1
        }
        return lo
    }

    /** Screen rectangle of page i. */
    private fun pageRectOnScreen(i: Int): RectF {
        val left = side - scrollPosX
        val top = tops[i] - scrollPosY
        return RectF(left, top, left + widthPx, top + pageH(i))
    }

    /** Page point -> screen. */
    private fun toScreenX(i: Int, x: Float) = side - scrollPosX + (x - sizes()[i].x0) * scaleOf(i)
    private fun toScreenY(i: Int, y: Float) = tops[i] - scrollPosY + (y - sizes()[i].y0) * scaleOf(i)
    private fun toScreen(i: Int, r: Rect) = RectF(toScreenX(i, r.x0), toScreenY(i, r.y0), toScreenX(i, r.x1), toScreenY(i, r.y1))

    /** Screen -> (page, page point). Points between pages snap to the nearest page. */
    private fun toPage(sx: Float, sy: Float, page: Int = -1): Pair<Int, Point>? {
        if (sizes().isEmpty() || tops.isEmpty()) return null
        val i = if (page >= 0) page else pageAtContentY(sy + scrollPosY)
        val sc = scaleOf(i)
        val s = sizes()[i]
        val x = s.x0 + (sx + scrollPosX - side) / sc
        val y = s.y0 + (sy + scrollPosY - tops[i]) / sc
        return i to Point(x, y)
    }

    private fun insidePage(sx: Float, sy: Float): Boolean {
        val i = pageAtContentY(sy + scrollPosY)
        return tops.isNotEmpty() && pageRectOnScreen(i).contains(sx, sy)
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (w != laidOutFor) { clearBitmaps(); relayout(keepPosition = true) } else clampScroll()
        pendingGoTo?.let { goToPage(it) }
        pendingGoTo = null
        invalidate()
    }

    // ---------------------------------------------------------- navigation
    private var pendingGoTo: Int? = null

    fun goToPage(i: Int) {
        if (width == 0 || tops.isEmpty()) { pendingGoTo = i; return }
        val p = i.coerceIn(0, sizes().size - 1)
        scroller.forceFinished(true)
        scrollPosY = tops[p] - gap
        clampScroll()
        if (currentPage != p) { currentPage = p; listener?.onPageChanged(p) }
        scheduleHq(); invalidate()
    }

    /** Make a page rectangle visible (search results). */
    fun showRect(i: Int, r: Rect) {
        if (tops.isEmpty() || i >= sizes().size) return
        val sr = toScreen(i, r)
        if (sr.top < height * 0.15f || sr.bottom > height * 0.85f) scrollPosY += sr.centerY() - height / 2f
        if (sr.left < 0 || sr.right > width) scrollPosX += sr.centerX() - width / 2f
        clampScroll(); scheduleHq(); invalidate()
    }

    fun setZoom(newZoom: Float, fx: Float = width / 2f, fy: Float = height / 2f) {
        val z = newZoom.coerceIn(1f, 8f)
        if (abs(z - zoom) < 0.001f || tops.isEmpty()) return
        val focus = toPage(fx, fy) ?: return
        zoom = z
        relayout(keepPosition = false)
        // keep the point under the fingers where it was
        val (i, p) = focus
        scrollPosX = side + (p.x - sizes()[i].x0) * scaleOf(i) - fx
        scrollPosY = tops[i] + (p.y - sizes()[i].y0) * scaleOf(i) - fy
        clampScroll()
        dropHq()
        invalidate()
    }

    /** Re-read the document after a change. `structure` = page count/sizes changed. */
    fun refresh(structure: Boolean) {
        if (structure) { clearBitmaps(); relayout(keepPosition = true) }
        dropHq()
        invalidate()
        scheduleHq()
    }

    // ============================================================ rendering
    private class PageBmp(val bmp: Bitmap, val revision: Int, val widthPx: Int)
    private val bitmaps = HashMap<Int, PageBmp>()
    private val pending = HashSet<Int>()
    private var generation = 0                 // bumps when bitmaps are thrown away

    private class Hq(val page: Int, val zoom: Float, val rect: android.graphics.Rect, val bmp: Bitmap, val revision: Int)
    private val hq = ArrayList<Hq>()
    private var hqToken = 0
    private val handler = Handler(Looper.getMainLooper())
    private val hqRunnable = Runnable { requestHq() }

    private fun clearBitmaps() {
        generation++
        for (b in bitmaps.values) b.bmp.recycle()
        bitmaps.clear(); pending.clear()
        dropHq()
    }

    private fun dropHq() {
        hqToken++
        for (h in hq) h.bmp.recycle()
        hq.clear()
    }

    private fun scheduleHq() {
        handler.removeCallbacks(hqRunnable)
        handler.postDelayed(hqRunnable, 180)
    }

    private fun requestBase(i: Int) {
        val eng = engine ?: return
        if (i in pending || eng.closed) return
        val have = bitmaps[i]
        val target = (width - 2 * side).toInt()
        if (have != null && have.revision == eng.revision && have.widthPx == target) return
        pending.add(i)
        val gen = generation
        var scale = baseScaleOf(i)
        val sz = sizes()[i]
        val pixels = sz.w * sz.h * scale * scale
        if (pixels > MAX_BASE_PIXELS) scale *= Math.sqrt((MAX_BASE_PIXELS / pixels).toDouble()).toFloat()  // very long pages
        val rev = eng.revision
        eng.async({ eng.render(i, scale) }) { bmp, err ->
            pending.remove(i)
            if (bmp == null) { if (err != null) android.util.Log.w(TAG, "render $i", err); return@async }
            if (gen != generation || i >= sizes().size) { bmp.recycle(); return@async }
            bitmaps.put(i, PageBmp(bmp, rev, target))?.bmp?.recycle()
            invalidate()
        }
    }

    private fun requestHq() {
        val eng = engine ?: return
        if (zoom < 1.15f || tops.isEmpty() || dragging || scaling || !scroller.isFinished) return
        dropHq()
        val token = hqToken
        val rev = eng.revision
        for (i in visiblePages()) {
            val pr = pageRectOnScreen(i)
            val vis = RectF(max(0f, pr.left), max(0f, pr.top), min(width.toFloat(), pr.right), min(height.toFloat(), pr.bottom))
            if (vis.width() < 2 || vis.height() < 2) continue
            val patch = android.graphics.Rect((vis.left - pr.left).toInt(), (vis.top - pr.top).toInt(),
                (vis.right - pr.left).toInt() + 1, (vis.bottom - pr.top).toInt() + 1)
            val scale = scaleOf(i)
            val z = zoom
            eng.async({ eng.render(i, scale, patch) }) { bmp, _ ->
                if (bmp == null) return@async
                if (token != hqToken || z != zoom) { bmp.recycle(); return@async }
                hq.add(Hq(i, z, patch, bmp, rev))
                invalidate()
            }
        }
    }

    private fun visiblePages(): List<Int> {
        if (tops.isEmpty() || sizes().isEmpty()) return emptyList()
        val first = pageAtContentY(scrollPosY)
        val last = pageAtContentY(scrollPosY + height)
        return (first..last).toList()
    }

    private val bmpPaint = Paint(Paint.FILTER_BITMAP_FLAG)
    private val pageBg = Paint().apply { color = Color.WHITE }
    private val nightBg = Paint().apply { color = Color.BLACK }
    private val shadow = Paint().apply { color = Color.argb(40, 0, 0, 0) }
    private val selPaint = Paint().apply { color = Color.argb(90, 47, 111, 219) }
    private val hitPaint = Paint().apply { color = Color.argb(90, 255, 200, 0) }
    private val curHitPaint = Paint().apply { color = Color.argb(140, 255, 120, 0) }
    private val outline = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = context.dp(2).toFloat(); color = Color.rgb(47, 111, 219)
        pathEffect = DashPathEffect(floatArrayOf(context.dp(6).toFloat(), context.dp(4).toFloat()), 0f)
    }
    private val handlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(47, 111, 219) }
    private val draftPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = context.dp(2).toFloat(); strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val redactPaint = Paint().apply { color = Color.argb(110, 0, 0, 0) }
    private val bgColor = if (context.isNight()) Color.rgb(30, 32, 36) else Color.rgb(214, 218, 224)

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(bgColor)
        val eng = engine ?: return
        if (tops.isEmpty() || eng.closed) return
        if (width != laidOutFor) relayout(true)
        val visible = visiblePages()
        for (i in visible) {
            val r = pageRectOnScreen(i)
            canvas.drawRect(r.left + 3, r.top + 3, r.right + 3, r.bottom + 3, shadow)
            canvas.drawRect(r, if (nightMode) nightBg else pageBg)
            val b = bitmaps[i]
            if (b != null && !b.bmp.isRecycled) canvas.drawBitmap(b.bmp, null, r, bmpPaint)
            requestBase(i)
            for (h in hq) if (h.page == i && h.zoom == zoom && h.revision == eng.revision && !h.bmp.isRecycled) {
                canvas.drawBitmap(h.bmp, r.left + h.rect.left, r.top + h.rect.top, bmpPaint)
            }
        }
        // keep neighbours ready, drop far-away pages to save memory
        visible.firstOrNull()?.let { if (it > 0) requestBase(it - 1) }
        visible.lastOrNull()?.let { if (it + 1 < sizes().size) requestBase(it + 1) }
        val keep = if (visible.isEmpty()) IntRange.EMPTY else (visible.first() - 3)..(visible.last() + 3)
        val drop = bitmaps.keys.filter { it !in keep }
        for (k in drop) bitmaps.remove(k)?.bmp?.recycle()

        drawOverlays(canvas, visible)
    }

    private fun drawOverlays(canvas: Canvas, visible: List<Int>) {
        // search results
        for ((k, hit) in searchHits.withIndex()) {
            if (hit.first !in visible) continue
            canvas.drawRect(toScreen(hit.first, hit.second), if (k == currentHit) curHitPaint else hitPaint)
        }
        // text selection
        selection?.let { s ->
            if (s.page in visible) for (q in s.quads) canvas.drawPath(quadPath(s.page, q), selPaint)
        }
        // selected comment
        selectedAnnot?.let { a ->
            if (a.page in visible) {
                val d = annotDrag
                val r = toScreen(a.page, a.rect)
                if (d != null) {
                    if (d.resize) { r.right = max(r.left + 12, r.right + d.dx); r.bottom = max(r.top + 12, r.bottom + d.dy) }
                    else r.offset(d.dx, d.dy)
                }
                val pad = context.dp(4).toFloat()
                r.inset(-pad, -pad)
                canvas.drawRect(r, outline)
                if (a.resizable) canvas.drawCircle(r.right, r.bottom, context.dp(9).toFloat(), handlePaint)
            }
        }
        // drawing in progress
        draftPaint.color = drawColor.toArgb()
        draft?.let { d ->
            if (d.page !in visible) return@let
            val a = PointF2(toScreenX(d.page, d.a.x), toScreenY(d.page, d.a.y))
            val b = PointF2(toScreenX(d.page, d.b.x), toScreenY(d.page, d.b.y))
            val r = RectF(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))
            when (tool) {
                Tool.RECT -> canvas.drawRect(r, draftPaint)
                Tool.ELLIPSE -> canvas.drawOval(r, draftPaint)
                Tool.REDACT -> { canvas.drawRect(r, redactPaint); canvas.drawRect(r, outline) }
                Tool.LINE, Tool.ARROW -> canvas.drawLine(a.x, a.y, b.x, b.y, draftPaint)
                else -> {}
            }
        }
        if (inkStrokes.isNotEmpty() && inkPage in visible) {
            val sc = scaleOf(inkPage)
            draftPaint.strokeWidth = max(2f, 2f * sc)
            for (s in inkStrokes) {
                if (s.isEmpty()) continue
                val path = Path()
                path.moveTo(toScreenX(inkPage, s[0].x), toScreenY(inkPage, s[0].y))
                for (p in s.drop(1)) path.lineTo(toScreenX(inkPage, p.x), toScreenY(inkPage, p.y))
                canvas.drawPath(path, draftPaint)
            }
            draftPaint.strokeWidth = context.dp(2).toFloat()
        }
    }

    private data class PointF2(val x: Float, val y: Float)

    private fun quadPath(i: Int, q: Quad) = Path().apply {
        moveTo(toScreenX(i, q.ul_x), toScreenY(i, q.ul_y))
        lineTo(toScreenX(i, q.ur_x), toScreenY(i, q.ur_y))
        lineTo(toScreenX(i, q.lr_x), toScreenY(i, q.lr_y))
        lineTo(toScreenX(i, q.ll_x), toScreenY(i, q.ll_y))
        close()
    }

    // ============================================================= touch
    private val scroller = OverScroller(context)
    private var dragging = false
    private var scaling = false

    private val gestures = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(e: MotionEvent): Boolean { scroller.forceFinished(true); return true }

        override fun onScroll(e1: MotionEvent?, e2: MotionEvent, dx: Float, dy: Float): Boolean {
            if (scaling) return true
            dragging = true
            scrollPosX += dx; scrollPosY += dy
            clampScroll(); invalidate()
            return true
        }

        override fun onFling(e1: MotionEvent?, e2: MotionEvent, vx: Float, vy: Float): Boolean {
            scroller.fling(scrollPosX.toInt(), scrollPosY.toInt(), -vx.toInt(), -vy.toInt(),
                0, max(0, (widthPx + 2 * side - width).toInt()), 0, max(0, (contentH - height).toInt()))
            postInvalidateOnAnimation()
            return true
        }

        override fun onDoubleTap(e: MotionEvent): Boolean {
            setZoom(if (zoom < 1.6f) 2.5f else 1f, e.x, e.y)
            scheduleHq()
            return true
        }

        override fun onSingleTapConfirmed(e: MotionEvent): Boolean { handleTap(e.x, e.y); return true }

        override fun onLongPress(e: MotionEvent) {
            if (scaling || tool != Tool.PAN || !insidePage(e.x, e.y)) return
            val (i, p) = toPage(e.x, e.y) ?: return
            val eng = engine ?: return
            extendPage = i
            extendAnchor = null
            eng.async({ eng.wordAt(i, p) }) { sel, _ ->
                if (sel == null) return@async
                performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS)
                selection = sel
                // keep extending while the finger moves
                extendAnchor = sel.quads.firstOrNull()?.let { Point(it.ul_x + 0.5f, (it.ul_y + it.ll_y) / 2) } ?: p
                listener?.onSelection(sel, false)
            }
            extending = true
        }
    })

    private val scaleDetector = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScaleBegin(d: ScaleGestureDetector): Boolean {
            scaling = true; draft = null; textDrag = null; invalidate(); return true
        }
        override fun onScale(d: ScaleGestureDetector): Boolean { setZoom(zoom * d.scaleFactor, d.focusX, d.focusY); return true }
        override fun onScaleEnd(d: ScaleGestureDetector) { scheduleHq() }
    })

    override fun computeScroll() {
        if (scroller.computeScrollOffset()) {
            scrollPosX = scroller.currX.toFloat(); scrollPosY = scroller.currY.toFloat()
            clampScroll(); postInvalidateOnAnimation()
            if (scroller.isFinished) scheduleHq()
        }
    }

    // tool gestures
    private class Draft(val page: Int, val a: Point, var b: Point)
    private var draft: Draft? = null
    private class TextDrag(val page: Int, val a: Point)
    private var textDrag: TextDrag? = null
    private val inkStrokes = ArrayList<ArrayList<Point>>()
    private var inkPage = -1
    private var extending = false
    private var extendPage = -1
    private var extendAnchor: Point? = null
    private var selBusy = false
    private var selNext: Triple<Int, Point, Point>? = null
    private var multiTouch = false

    private class AnnotDrag(val resize: Boolean, val x0: Float, val y0: Float, var dx: Float = 0f, var dy: Float = 0f)
    private var annotDrag: AnnotDrag? = null

    val inkStrokeCount get() = inkStrokes.size
    fun takeInk(): Pair<Int, List<List<Point>>>? {
        if (inkStrokes.isEmpty()) return null
        val out = inkPage to inkStrokes.map { it.toList() }
        inkStrokes.clear(); invalidate()
        return out
    }
    fun undoInkStroke() { if (inkStrokes.isNotEmpty()) inkStrokes.removeAt(inkStrokes.size - 1); listener?.onInkChanged(inkStrokes.size); invalidate() }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        if (engine == null || tops.isEmpty()) return true
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> { multiTouch = false; dragging = false }
            MotionEvent.ACTION_POINTER_DOWN -> {
                multiTouch = true
                // second finger: cancel what one finger was drawing
                draft = null; textDrag = null; annotDrag = null
                if (inkStrokes.isNotEmpty() && inkStrokes.last().size < 3) inkStrokes.removeAt(inkStrokes.size - 1)
                invalidate()
            }
        }

        // long press then move: extend the text selection
        if (extending) {
            when (e.actionMasked) {
                MotionEvent.ACTION_MOVE -> {
                    val a = extendAnchor
                    val hit = toPage(e.x, e.y, extendPage)
                    if (a != null && hit != null) requestSelection(extendPage, a, hit.second, false)
                    return true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    extending = false
                    selection?.let { listener?.onSelection(it, true) }
                    return true
                }
            }
        }

        if (!multiTouch && handleToolTouch(e)) return true

        scaleDetector.onTouchEvent(e)
        gestures.onTouchEvent(e)
        if (e.actionMasked == MotionEvent.ACTION_UP || e.actionMasked == MotionEvent.ACTION_CANCEL) {
            if (dragging || scaling) scheduleHq()
            dragging = false; scaling = false
        }
        return true
    }

    /** One-finger drawing for the active tool. Returns true when the event was used. */
    private fun handleToolTouch(e: MotionEvent): Boolean {
        // moving / resizing the selected comment (any tool)
        val sel = selectedAnnot
        if (sel != null && sel.movable && tool == Tool.PAN) {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    val r = toScreen(sel.page, sel.rect)
                    val pad = context.dp(14).toFloat()
                    val nearHandle = sel.resizable && abs(e.x - r.right) < pad * 1.6f && abs(e.y - r.bottom) < pad * 1.6f
                    if (nearHandle || RectF(r.left - pad, r.top - pad, r.right + pad, r.bottom + pad).contains(e.x, e.y)) {
                        annotDrag = AnnotDrag(nearHandle, e.x, e.y)
                        gestures.onTouchEvent(e)     // still allow tap
                        return true
                    }
                }
                MotionEvent.ACTION_MOVE -> annotDrag?.let { d ->
                    d.dx = e.x - d.x0; d.dy = e.y - d.y0
                    if (abs(d.dx) > 4 || abs(d.dy) > 4) {
                        val cancel = MotionEvent.obtain(e).apply { action = MotionEvent.ACTION_CANCEL }
                        gestures.onTouchEvent(cancel); cancel.recycle()
                    }
                    invalidate(); return true
                }
                MotionEvent.ACTION_UP -> annotDrag?.let { d ->
                    annotDrag = null
                    val sc = scaleOf(sel.page)
                    if (abs(d.dx) > 6 || abs(d.dy) > 6) {
                        if (d.resize) {
                            val r = sel.rect
                            listener?.onAnnotResized(sel, Rect(r.x0, r.y0, r.x1 + d.dx / sc, r.y1 + d.dy / sc))
                        } else listener?.onAnnotMoved(sel, d.dx / sc, d.dy / sc)
                        invalidate()
                    } else gestures.onTouchEvent(e)
                    return true
                }
                MotionEvent.ACTION_CANCEL -> { annotDrag = null; invalidate() }
            }
        }

        val t = tool
        if (t == Tool.PAN || t == Tool.PLACE) return false
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                if (!insidePage(e.x, e.y)) return false
                val (i, p) = toPage(e.x, e.y) ?: return false
                when {
                    t.isText -> { textDrag = TextDrag(i, p); selection = null }
                    t.isDrag || t.isLine -> draft = Draft(i, p, p)
                    t == Tool.INK -> {
                        if (inkStrokes.isNotEmpty() && i != inkPage) return true   // one page at a time
                        inkPage = i
                        inkStrokes.add(arrayListOf(p))
                    }
                }
                invalidate(); return true
            }
            MotionEvent.ACTION_MOVE -> {
                textDrag?.let { d ->
                    val p = toPage(e.x, e.y, d.page)?.second ?: return true
                    requestSelection(d.page, d.a, p, false); return true
                }
                draft?.let { d -> d.b = toPage(e.x, e.y, d.page)?.second ?: d.b; invalidate(); return true }
                if (t == Tool.INK && inkStrokes.isNotEmpty()) {
                    val p = toPage(e.x, e.y, inkPage)?.second ?: return true
                    inkStrokes.last().add(p); invalidate(); return true
                }
                return false
            }
            MotionEvent.ACTION_UP -> {
                textDrag?.let { d ->
                    textDrag = null
                    val p = toPage(e.x, e.y, d.page)?.second ?: return true
                    requestSelection(d.page, d.a, p, true); return true
                }
                draft?.let { d ->
                    draft = null; invalidate()
                    val a = d.a; val b = d.b
                    if (t.isLine) {
                        if (abs(a.x - b.x) + abs(a.y - b.y) > 3) listener?.onLine(d.page, a, b)
                    } else {
                        val r = Rect(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))
                        if (r.x1 - r.x0 > 3 && r.y1 - r.y0 > 3) listener?.onRect(d.page, r)
                    }
                    return true
                }
                if (t == Tool.INK && inkStrokes.isNotEmpty()) {
                    if (inkStrokes.last().size < 2) inkStrokes.removeAt(inkStrokes.size - 1)
                    listener?.onInkChanged(inkStrokes.size); invalidate(); return true
                }
                return false
            }
            MotionEvent.ACTION_CANCEL -> { textDrag = null; draft = null; invalidate(); return true }
        }
        return false
    }

    /** Ask the engine for the selection between two points (one request at a time while dragging). */
    private var selSeq = 0
    private var finalSeq = -1

    private fun requestSelection(page: Int, a: Point, b: Point, finished: Boolean) {
        val eng = engine ?: return
        if (selBusy && !finished) { selNext = Triple(page, a, b); return }
        val seq = ++selSeq
        if (finished) { selNext = null; finalSeq = seq }
        selBusy = true
        eng.async({ eng.selectText(page, a, b) }) { s, _ ->
            if (seq < finalSeq) return@async          // an older drag result: the final one follows
            selBusy = false
            selection = s?.takeIf { it.quads.isNotEmpty() }
            if (finished) { listener?.onSelection(selection, true); return@async }
            listener?.onSelection(selection, false)
            val next = selNext
            selNext = null
            if (next != null) requestSelection(next.first, next.second, next.third, false)
        }
    }

    private fun handleTap(x: Float, y: Float) {
        val eng = engine ?: return
        if (!insidePage(x, y)) {
            if (selectedAnnot != null) listener?.onAnnotTapped(null) else listener?.onTapEmpty()
            return
        }
        val (i, p) = toPage(x, y) ?: return
        if (tool == Tool.PLACE) { listener?.onPlace(i, p); return }
        if (tool != Tool.PAN) return
        if (selection != null) { selection = null; listener?.onSelection(null, true); return }
        val tol = context.dp(10) / scaleOf(i)
        eng.async({ val a = eng.annotAt(i, p, tol); a to (if (a == null) eng.linkAt(i, p) else null) }) { r, _ ->
            val annot = r?.first
            val link = r?.second
            when {
                annot != null -> listener?.onAnnotTapped(annot)
                selectedAnnot != null -> listener?.onAnnotTapped(null)
                link != null -> listener?.onLink(link)
                else -> listener?.onTapEmpty()
            }
        }
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        handler.removeCallbacks(hqRunnable)
    }

    fun release() {
        clearBitmaps()
        engine = null
    }

    companion object {
        private const val MAX_BASE_PIXELS = 8_000_000f
        private val INVERT = ColorMatrixColorFilter(ColorMatrix(floatArrayOf(
            -1f, 0f, 0f, 0f, 255f,
            0f, -1f, 0f, 0f, 255f,
            0f, 0f, -1f, 0f, 255f,
            0f, 0f, 0f, 1f, 0f)))
    }
}
