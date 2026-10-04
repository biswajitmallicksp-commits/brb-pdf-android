package com.brb.pdf

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.InputType
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast

/** Small helpers for building screens in code (no XML layouts needed). */

const val TAG = "BRBPdf"

fun Context.dp(v: Float): Int = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics).toInt()
fun Context.dp(v: Int): Int = dp(v.toFloat())

fun Context.isNight(): Boolean =
    (resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK) ==
        android.content.res.Configuration.UI_MODE_NIGHT_YES

fun Context.toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()

fun Activity.alive(): Boolean = !isFinishing && !isDestroyed

fun Context.showError(title: String, e: Throwable?) {
    Log.e(TAG, title, e)
    val msg = when (e) {
        null -> "Unknown error"
        is UserError -> e.message ?: ""
        else -> (e.message ?: e.javaClass.simpleName) + "\n\nThe document was not changed."
    }
    if (this is Activity && !alive()) return
    AlertDialog.Builder(this).setTitle(title).setMessage(msg).setPositiveButton("OK", null).show()
}

fun Context.info(title: String, msg: String, then: (() -> Unit)? = null) {
    if (this is Activity && !alive()) return
    AlertDialog.Builder(this).setTitle(title).setMessage(msg)
        .setPositiveButton("OK") { _, _ -> then?.invoke() }.show()
}

fun Context.confirm(title: String, msg: String, yes: String = "OK", action: () -> Unit) {
    if (this is Activity && !alive()) return
    AlertDialog.Builder(this).setTitle(title).setMessage(msg)
        .setPositiveButton(yes) { _, _ -> action() }
        .setNegativeButton("Cancel", null).show()
}

/** An error whose message is meant for the user as it is. */
class UserError(msg: String) : Exception(msg)

fun Context.label(text: String, sizeSp: Float = 15f, bold: Boolean = false, color: Int? = null): TextView =
    TextView(this).apply {
        this.text = text
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp)
        if (bold) typeface = Typeface.DEFAULT_BOLD
        if (color != null) setTextColor(color)
    }

fun Context.vbox(pad: Int = 16): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL
    val p = dp(pad)
    setPadding(p, p, p, p)
}

fun Context.hbox(): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.HORIZONTAL
    gravity = Gravity.CENTER_VERTICAL
}

fun Context.button(text: String, onClick: () -> Unit): Button = Button(this).apply {
    this.text = text
    isAllCaps = false
    setOnClickListener { onClick() }
}

/** A rounded, tinted "chip" button used in tool strips. */
fun Context.chip(text: String, onClick: (View) -> Unit): TextView = TextView(this).apply {
    this.text = text
    setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
    gravity = Gravity.CENTER
    val h = dp(14); val v = dp(9)
    setPadding(h, v, h, v)
    setOnClickListener { onClick(it) }
    setChipSelected(false)
}

fun TextView.setChipSelected(selected: Boolean) {
    val night = context.isNight()
    val bg = GradientDrawable().apply {
        cornerRadius = context.dp(18).toFloat()
        setColor(if (selected) Color.rgb(47, 111, 219) else if (night) Color.rgb(52, 56, 62) else Color.rgb(232, 236, 242))
    }
    background = bg
    setTextColor(if (selected) Color.WHITE else if (night) Color.rgb(230, 232, 235) else Color.rgb(30, 35, 40))
    tag = selected
}

fun lp(w: Int = ViewGroup.LayoutParams.MATCH_PARENT, h: Int = ViewGroup.LayoutParams.WRAP_CONTENT, weight: Float = 0f) =
    LinearLayout.LayoutParams(w, h, weight)

/** Ask for one line (or several lines) of text. */
fun Context.askText(title: String, initial: String = "", hint: String = "", multiLine: Boolean = false,
                    password: Boolean = false, number: Boolean = false, ok: String = "OK",
                    onOk: (String) -> Unit) {
    val edit = EditText(this).apply {
        setText(initial)
        this.hint = hint
        inputType = when {
            password -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            number -> InputType.TYPE_CLASS_NUMBER
            multiLine -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            else -> InputType.TYPE_CLASS_TEXT
        }
        if (multiLine) { minLines = 3; gravity = Gravity.TOP or Gravity.START }
        setSelection(text.length)
    }
    val box = vbox(20).apply { addView(edit) }
    AlertDialog.Builder(this).setTitle(title).setView(box)
        .setPositiveButton(ok) { _, _ -> onOk(edit.text.toString()) }
        .setNegativeButton("Cancel", null).show()
    edit.requestFocus()
}

/** Pick several items with check boxes. */
fun Context.askChecks(title: String, items: List<String>, checked: BooleanArray, onOk: (BooleanArray) -> Unit) {
    val values = checked.copyOf()
    AlertDialog.Builder(this).setTitle(title)
        .setMultiChoiceItems(items.toTypedArray(), values) { _, i, on -> values[i] = on }
        .setPositiveButton("OK") { _, _ -> onOk(values) }
        .setNegativeButton("Cancel", null).show()
}

/** Pick one item. */
fun Context.askChoice(title: String, items: List<String>, onPick: (Int) -> Unit) {
    AlertDialog.Builder(this).setTitle(title)
        .setItems(items.toTypedArray()) { _, i -> onPick(i) }
        .setNegativeButton("Cancel", null).show()
}

/** A simple colour palette dialog. */
val PALETTE = listOf(
    "Yellow" to floatArrayOf(1f, 0.85f, 0f), "Green" to floatArrayOf(0.2f, 0.75f, 0.3f),
    "Blue" to floatArrayOf(0.15f, 0.4f, 0.9f), "Red" to floatArrayOf(0.85f, 0.1f, 0.1f),
    "Orange" to floatArrayOf(1f, 0.55f, 0f), "Purple" to floatArrayOf(0.55f, 0.25f, 0.8f),
    "Black" to floatArrayOf(0f, 0f, 0f), "Grey" to floatArrayOf(0.5f, 0.5f, 0.5f),
)

fun Context.askColor(title: String = "Colour", onPick: (FloatArray) -> Unit) {
    val names = PALETTE.map { it.first }
    AlertDialog.Builder(this).setTitle(title)
        .setItems(names.toTypedArray()) { _, i -> onPick(PALETTE[i].second) }
        .setNegativeButton("Cancel", null).show()
}

fun FloatArray.toArgb(alpha: Int = 255): Int =
    Color.argb(alpha, (this[0] * 255).toInt(), (this.getOrElse(1) { 0f } * 255).toInt(), (this.getOrElse(2) { 0f } * 255).toInt())

/** A progress dialog with a bar, a message and an optional Cancel button. */
class Progress(ctx: Context, title: String, cancellable: Boolean = false, onCancel: (() -> Unit)? = null) {
    private val text = ctx.label("Starting...", 14f)
    private val bar = ProgressBar(ctx, null, android.R.attr.progressBarStyleHorizontal).apply { isIndeterminate = true }
    private val dialog: AlertDialog

    init {
        val box = ctx.vbox(20).apply {
            addView(text, lp())
            addView(bar, lp())
        }
        val b = AlertDialog.Builder(ctx).setTitle(title).setView(box).setCancelable(false)
        if (cancellable) b.setNegativeButton("Cancel") { _, _ -> onCancel?.invoke() }
        dialog = b.create()
        if (ctx !is Activity || ctx.alive()) dialog.show()
    }

    fun update(done: Int, total: Int, message: String) {
        text.text = message
        if (total > 0) {
            bar.isIndeterminate = false
            bar.max = total
            bar.progress = done
        }
    }

    fun message(message: String) { text.text = message }

    fun close() { try { dialog.dismiss() } catch (_: Exception) { } }
}

fun Context.checkBox(text: String, checked: Boolean): CheckBox = CheckBox(this).apply {
    this.text = text
    isChecked = checked
}

/** "1-3, 7, 10-" -> 0-based page list. */
fun parsePageRange(text: String, pageCount: Int, keepOrder: Boolean = false): List<Int> {
    val t = text.trim().lowercase()
    if (t.isEmpty()) throw UserError("Enter the pages, for example 1-5, 8, 10-12")
    if (t == "all") return (0 until pageCount).toList()
    if (t == "odd") return (0 until pageCount step 2).toList()
    if (t == "even") return (1 until pageCount step 2).toList()
    val out = ArrayList<Int>()
    for (raw in t.split(',', ';')) {
        val part = raw.trim().replace("last", pageCount.toString())
        if (part.isEmpty()) continue
        val m = Regex("""(\d*)\s*-\s*(\d*)""").matchEntire(part)
        val (a, b) = when {
            m != null -> (m.groupValues[1].toIntOrNull() ?: 1) to (m.groupValues[2].toIntOrNull() ?: pageCount)
            part.all { it.isDigit() } -> part.toInt() to part.toInt()
            else -> throw UserError("'$part' is not a page number or range")
        }
        if (a < 1 || b > pageCount || a > b) throw UserError("'$part' is outside 1-$pageCount")
        for (p in a..b) out.add(p - 1)
    }
    if (out.isEmpty()) throw UserError("No pages selected")
    return if (keepOrder) out else out.toSortedSet().toList()
}

/** [0,1,2,5] -> "1-3, 6" */
fun describePages(pages: Collection<Int>, limit: Int = 12): String {
    val s = pages.toSortedSet().toList()
    if (s.isEmpty()) return "none"
    val ranges = ArrayList<String>()
    var start = s[0]; var prev = s[0]
    for (p in s.drop(1) + listOf(-10)) {
        if (p == prev + 1) { prev = p; continue }
        ranges.add(if (start == prev) "${start + 1}" else "${start + 1}-${prev + 1}")
        start = p; prev = p
    }
    val text = ranges.take(limit).joinToString(", ")
    return if (ranges.size > limit) "$text, ..." else text
}
