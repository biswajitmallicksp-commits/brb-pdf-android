package com.brb.pdf

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.Menu
import android.view.MenuItem
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.artifex.mupdf.fitz.Image
import com.artifex.mupdf.fitz.PDFDocument
import com.artifex.mupdf.fitz.Rect
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale
import kotlin.math.max
import kotlin.math.min

/**
 * Images to PDF: choose photos / pictures (PNG, JPG, WEBP...), put them in order, and make one PDF with one
 * picture per page. Also opens from the gallery's Share button. Everything stays on the phone.
 */
class ImagesActivity : Activity() {

    private class Item(val uri: Uri, val name: String, var thumb: Bitmap? = null)

    private val items = ArrayList<Item>()
    private lateinit var listBox: LinearLayout
    private lateinit var summary: TextView
    private var pageSize = 0        // 0 A4, 1 Letter, 2 same size as the picture
    private var margin = 1          // 0 none, 1 small, 2 normal
    private var quality = 1         // 0 original, 1 smaller file

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Images to PDF"
        pageSize = Store.get(this, "img_page", "0").toIntOrNull() ?: 0
        margin = Store.get(this, "img_margin", "1").toIntOrNull() ?: 1
        quality = Store.get(this, "img_quality", "1").toIntOrNull() ?: 1
        val root = vbox(12)
        summary = label("", 14f, color = Color.GRAY)
        root.addView(summary, lp())
        val row = hbox().apply { setPadding(0, dp(8), 0, dp(8)) }
        row.addView(button("+ Add pictures") { pick() }, lp(0, -2, 1f))
        row.addView(button("Options") { options() }, lp(0, -2, 1f))
        root.addView(row, lp())
        listBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(ScrollView(this).apply { addView(listBox) }, lp(-1, 0, 1f))
        root.addView(button("Create PDF") { create() }.apply { textSize = 17f }, lp())
        setContentView(root)
        addFrom(intent)
        if (items.isEmpty() && savedInstanceState == null) pick()
        refresh()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        addFrom(intent)
        refresh()
    }

    /** Pictures shared from the gallery (one or many). */
    @Suppress("DEPRECATION")
    private fun addFrom(i: Intent?) {
        if (i == null) return
        val uris = ArrayList<Uri>()
        when (i.action) {
            Intent.ACTION_SEND -> (i.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))?.let { uris.add(it) }
            Intent.ACTION_SEND_MULTIPLE -> i.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.addAll(it) }
        }
        i.data?.let { if (i.action == Intent.ACTION_VIEW) uris.add(it) }
        add(uris)
    }

    private fun add(uris: List<Uri>) {
        for (u in uris) items.add(Item(u, Files.displayName(this, u)))
        loadThumbs()
    }

    private fun pick() {
        val i = Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/*")
            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        try { startActivityForResult(i, REQ_PICK) } catch (e: Exception) {
            try { startActivityForResult(Intent(Intent.ACTION_GET_CONTENT).setType("image/*")
                .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true), REQ_PICK) } catch (e2: Exception) { toast("No app to pick pictures.") }
        }
    }

    private fun loadThumbs() {
        val todo = items.filter { it.thumb == null }
        if (todo.isEmpty()) return
        Thread {
            for (it in todo) {
                val b = try { decode(it.uri, 240) } catch (_: Throwable) { null }
                runOnUiThread { it.thumb = b; if (alive()) refresh() }
            }
        }.start()
    }

    // ------------------------------------------------------------ list
    private fun refresh() {
        val sizes = listOf("A4", "Letter", "same as picture")
        val margins = listOf("no margin", "small margin", "normal margin")
        summary.text = if (items.isEmpty()) "Add the photos or pictures to put in the PDF (one per page)."
        else "${items.size} picture(s) - page: ${sizes[pageSize]}, ${margins[margin]}" +
            (if (quality == 1) ", smaller file" else ", original quality") + ".\nThe PDF follows this order."
        listBox.removeAllViews()
        for ((k, it) in items.withIndex()) {
            val row = hbox().apply { gravity = Gravity.CENTER_VERTICAL; setPadding(0, dp(6), 0, dp(6)) }
            row.addView(label("${k + 1}", 15f, bold = true).apply { minWidth = dp(28) })
            row.addView(ImageView(this).apply {
                scaleType = ImageView.ScaleType.CENTER_CROP
                setBackgroundColor(Color.rgb(220, 223, 228))
                it.thumb?.let { b -> setImageBitmap(b) }
            }, LinearLayout.LayoutParams(dp(64), dp(64)).apply { marginEnd = dp(10) })
            row.addView(label(it.name, 13f).apply { maxLines = 2 }, lp(0, -2, 1f))
            row.addView(chip("↑") { move(k, -1) })
            row.addView(chip("↓") { move(k, 1) })
            row.addView(chip("✕") { items.removeAt(k); refresh() })
            listBox.addView(row, lp())
        }
    }

    private fun move(k: Int, d: Int) {
        val to = k + d
        if (to < 0 || to >= items.size) return
        val x = items.removeAt(k)
        items.add(to, x)
        refresh()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "Sort by name")
        menu.add(0, 2, 1, "Reverse order")
        menu.add(0, 3, 2, "Remove all")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> { items.sortWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.name }); refresh() }
            2 -> { items.reverse(); refresh() }
            3 -> { items.clear(); refresh() }
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }

    private fun options() {
        askChoice("Page size", listOf("A4", "Letter", "Same size as each picture")) { s ->
            pageSize = s
            val next = {
                askChoice("File size", listOf("Original quality (larger file)", "Smaller file (good for email / WhatsApp)")) { q ->
                    quality = q
                    Store.put(this, "img_page", "$pageSize"); Store.put(this, "img_margin", "$margin")
                    Store.put(this, "img_quality", "$quality")
                    refresh()
                }
            }
            if (s == 2) { margin = 0; next() }
            else askChoice("Margin around the picture", listOf("None", "Small", "Normal")) { m -> margin = m; next() }
        }
    }

    // ------------------------------------------------------------ make the PDF
    private fun create() {
        if (items.isEmpty()) { toast("Add at least one picture."); return }
        val first = Files.stem(items.first().name).ifBlank { "Pictures" }
        val i = Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf")
            .putExtra(Intent.EXTRA_TITLE, if (items.size == 1) "$first.pdf" else "$first (${items.size} pages).pdf")
        try { startActivityForResult(i, REQ_SAVE) } catch (e: Exception) { toast("No app to choose where to save.") }
    }

    private fun build(target: Uri) {
        val list = ArrayList(items)
        val prog = Progress(this, "Images to PDF")
        Thread {
            var err: Throwable? = null
            val skipped = ArrayList<String>()
            val tmp = Files.tempFile(this, "images_${System.currentTimeMillis()}.pdf")
            try {
                val pdf = PDFDocument()
                try {
                    for ((k, it) in list.withIndex()) {
                        runOnUiThread { prog.update(k, list.size, "Adding picture ${k + 1} of ${list.size}...") }
                        val bmp = try { decode(it.uri, if (quality == 1) 2000 else 4200) } catch (_: OutOfMemoryError) {
                            try { decode(it.uri, 1600) } catch (_: Throwable) { null }
                        }
                        if (bmp == null) { skipped.add(it.name); continue }
                        try { addPage(pdf, bmp) } finally { bmp.recycle() }
                    }
                    if (pdf.countPages() == 0) throw UserError("None of the pictures could be read.")
                    pdf.save(tmp.absolutePath, "compress,garbage")
                } finally {
                    pdf.destroy()
                }
                Files.copyFileToUri(this, tmp, target)
            } catch (t: Throwable) {
                err = if (t is OutOfMemoryError) UserError("Not enough memory. Choose \"Smaller file\" in Options.") else t
            } finally {
                tmp.delete()
            }
            runOnUiThread {
                prog.close()
                if (!alive()) return@runOnUiThread
                val e = err
                if (e != null) { showError("Could not make the PDF", e); return@runOnUiThread }
                Files.takePermission(this, target, true)
                val name = Files.displayName(this, target)
                Store.addRecent(this, target, name)
                val msg = "Saved $name (${list.size - skipped.size} page(s))." +
                    (if (skipped.isNotEmpty()) "\n\nThese could not be read and were left out:\n" + skipped.joinToString("\n") else "")
                AlertDialog.Builder(this).setTitle("PDF created").setMessage(msg)
                    .setPositiveButton("Open it") { _, _ ->
                        startActivity(Intent(this, ViewerActivity::class.java).setData(target)
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION))
                        finish()
                    }
                    .setNegativeButton("Done") { _, _ -> finish() }
                    .show()
            }
        }.start()
    }

    /** One page with the picture, fitted and centred. */
    private fun addPage(pdf: PDFDocument, bmp: Bitmap) {
        val out = ByteArrayOutputStream()
        val png = bmp.hasAlpha()
        bmp.compress(if (png) Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG,
            if (quality == 1) 80 else 95, out)
        val img = pdf.addImage(Image(out.toByteArray()))
        // picture size in points (assume 150 dpi for phone photos so pages stay a sensible size)
        val iw = bmp.width.toFloat(); val ih = bmp.height.toFloat()
        val landscape = iw > ih
        val (pw, ph) = when (pageSize) {
            0 -> if (landscape) 841.89f to 595.28f else 595.28f to 841.89f
            1 -> if (landscape) 792f to 612f else 612f to 792f
            else -> {
                val scale = min(1f, 1190f / max(iw * 72f / 150f, ih * 72f / 150f))   // at most A3-size pages
                (iw * 72f / 150f * scale) to (ih * 72f / 150f * scale)
            }
        }
        val m = if (pageSize == 2) 0f else listOf(0f, 18f, 36f)[margin]
        val s = min((pw - 2 * m) / iw, (ph - 2 * m) / ih)
        val w = iw * s; val h = ih * s
        val x = (pw - w) / 2; val y = (ph - h) / 2
        val res = pdf.newDictionary()
        val xo = pdf.newDictionary()
        xo.put("Im0", img)
        res.put("XObject", xo)
        val content = String.format(Locale.US, "q %.3f 0 0 %.3f %.3f %.3f cm /Im0 Do Q", w, h, x, y)
        val page = pdf.addPage(Rect(0f, 0f, pw, ph), 0, res, content)
        pdf.insertPage(-1, page)
    }

    /** Read a picture at most `maxSide` pixels, turned the right way up (camera photos). */
    private fun decode(uri: Uri, maxSide: Int): Bitmap? {
        val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
        if (opts.outWidth <= 0) return null
        var sample = 1
        while (max(opts.outWidth, opts.outHeight) / sample > maxSide * 2) sample *= 2
        val bmp = contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: return null
        var out = bmp
        val longest = max(bmp.width, bmp.height)
        if (longest > maxSide) {
            val f = maxSide.toFloat() / longest
            out = Bitmap.createScaledBitmap(bmp, max(1, (bmp.width * f).toInt()), max(1, (bmp.height * f).toInt()), true)
            if (out !== bmp) bmp.recycle()
        }
        val rotation = try {
            contentResolver.openInputStream(uri)?.use {
                when (ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
                    ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                    ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                    ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                    else -> 0f
                }
            } ?: 0f
        } catch (_: Exception) { 0f }
        if (rotation != 0f) {
            val r = Bitmap.createBitmap(out, 0, 0, out.width, out.height, Matrix().apply { postRotate(rotation) }, true)
            if (r !== out) out.recycle()
            out = r
        }
        return out
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null) {
            if (requestCode == REQ_PICK && items.isEmpty()) refresh()
            return
        }
        when (requestCode) {
            REQ_PICK -> {
                val uris = ArrayList<Uri>()
                val clip: ClipData? = data.clipData
                if (clip != null) for (k in 0 until clip.itemCount) clip.getItemAt(k).uri?.let { uris.add(it) }
                else data.data?.let { uris.add(it) }
                for (u in uris) try { contentResolver.takePersistableUriPermission(u, Intent.FLAG_GRANT_READ_URI_PERMISSION) } catch (_: Exception) { }
                add(uris)
                refresh()
            }
            REQ_SAVE -> data.data?.let { build(it) }
        }
    }

    companion object {
        private const val REQ_PICK = 31
        private const val REQ_SAVE = 32
    }
}
