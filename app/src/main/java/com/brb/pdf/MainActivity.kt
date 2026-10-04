package com.brb.pdf

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.text.format.DateUtils
import android.view.Gravity
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.File

/** Start screen: open a PDF, combine PDFs, recent files. */
class MainActivity : Activity() {

    private lateinit var recentBox: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Files.cleanup(this)
        val blue = Color.rgb(47, 111, 219)
        val root = vbox(16)
        root.addView(label("BRB PDF", 26f, bold = true, color = blue))
        root.addView(label("Read, annotate, sign, OCR and organise PDFs. Everything stays on this phone.", 14f).apply {
            setPadding(0, dp(4), 0, dp(16))
        })
        root.addView(bigButton("Open a PDF", "From phone storage, Downloads, Drive...") { openPicker() })
        root.addView(bigButton("Combine PDFs", "Join several PDF files into one") { pickMerge() })
        root.addView(label("Recent files", 17f, bold = true).apply { setPadding(0, dp(20), 0, dp(6)) })
        recentBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(recentBox, lp())
        setContentView(ScrollView(this).apply { addView(root) })
    }

    override fun onResume() {
        super.onResume()
        showRecents()
    }

    private fun bigButton(title: String, sub: String, action: () -> Unit): View {
        val box = vbox(14).apply {
            background = GradientDrawable().apply {
                cornerRadius = dp(12).toFloat()
                setColor(if (isNight()) Color.rgb(44, 48, 55) else Color.rgb(232, 239, 252))
            }
            addView(label(title, 18f, bold = true))
            addView(label(sub, 13f, color = Color.GRAY))
            setOnClickListener { action() }
            isClickable = true
        }
        return box.also { it.layoutParams = lp().apply { bottomMargin = dp(10) } }
    }

    private fun showRecents() {
        recentBox.removeAllViews()
        val list = Store.recents(this)
        if (list.isEmpty()) {
            recentBox.addView(label("Files you open will appear here.", 14f, color = Color.GRAY))
            return
        }
        for (r in list) {
            val row = vbox(10).apply {
                addView(label(r.name, 15f, bold = true).apply { maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.MIDDLE })
                addView(label(DateUtils.getRelativeTimeSpanString(r.time).toString() +
                    if (r.lastPage > 0) "  -  page ${r.lastPage + 1}" else "", 12f, color = Color.GRAY))
                setOnClickListener { openUri(Uri.parse(r.uri)) }
                setOnLongClickListener {
                    askChoice(r.name, listOf("Remove from list")) { Store.removeRecent(this@MainActivity, r.uri); showRecents() }
                    true
                }
            }
            recentBox.addView(row, lp())
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "Clear recent files")
        menu.add(0, 2, 1, "Privacy")
        menu.add(0, 3, 2, "About")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> confirm("Clear recent files", "Remove all files from the list? (The files themselves are not deleted.)", "Clear") {
                Store.clearRecents(this); showRecents()
            }
            2 -> info("Privacy", "BRB PDF works offline. It has no internet permission, no account, no ads and no " +
                "analytics. Your documents are processed only on this phone and are never uploaded.\n\n" +
                "Files you open are copied to the app's private storage while you work on them; the original is " +
                "changed only if you choose 'Save (replace original)'. Temporary copies are deleted automatically.")
            3 -> info("About", "BRB PDF 1.0\n\nUses MuPDF (AGPL-3.0, Artifex Software) and Tesseract OCR " +
                "(Apache-2.0) through Tesseract4Android (Apache-2.0). See README / THIRD_PARTY_LICENSES.\n\n" +
                "Signatures added with this app are pictures of a signature. They are not digital (cryptographic) " +
                "signatures.")
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }

    // ------------------------------------------------------------- open
    private fun openPicker() {
        val i = Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf")
        try { startActivityForResult(i, REQ_OPEN) } catch (e: Exception) { toast("No app to pick files.") }
    }

    private fun openUri(uri: Uri) {
        val i = Intent(this, ViewerActivity::class.java).setData(uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        startActivity(i)
    }

    // ------------------------------------------------------------ merge
    private val mergeList = ArrayList<Pair<Uri, String>>()

    private fun pickMerge() {
        val i = Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf")
            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        try { startActivityForResult(i, REQ_MERGE_PICK) } catch (e: Exception) { toast("No app to pick files.") }
    }

    /** Show the chosen files; the user can change the order, add more, then combine. */
    private fun showMergeList() {
        val box = vbox(12)
        fun rebuild() {
            box.removeAllViews()
            if (mergeList.isEmpty()) box.addView(label("No files yet.", 14f))
            for ((k, item) in mergeList.withIndex()) {
                val row = hbox()
                row.addView(label("${k + 1}. ${item.second}", 14f).apply { maxLines = 2 }, lp(0, -2, 1f))
                fun small(t: String, a: () -> Unit) = TextView(this).apply {
                    text = t; textSize = 18f; gravity = Gravity.CENTER; setPadding(dp(10), dp(6), dp(10), dp(6))
                    setOnClickListener { a(); rebuild() }
                }
                row.addView(small("↑") { if (k > 0) { val x = mergeList.removeAt(k); mergeList.add(k - 1, x) } })
                row.addView(small("↓") { if (k < mergeList.size - 1) { val x = mergeList.removeAt(k); mergeList.add(k + 1, x) } })
                row.addView(small("✕") { mergeList.removeAt(k) })
                box.addView(row, lp())
            }
        }
        rebuild()
        AlertDialog.Builder(this).setTitle("Combine in this order").setView(ScrollView(this).apply { addView(box) })
            .setPositiveButton("Combine") { _, _ ->
                if (mergeList.size < 2) toast("Choose at least two PDF files.") else askMergeTarget()
            }
            .setNeutralButton("Add files") { _, _ -> pickMerge() }
            .setNegativeButton("Cancel") { _, _ -> mergeList.clear() }
            .show()
    }

    private fun askMergeTarget() {
        val i = Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/pdf")
            .putExtra(Intent.EXTRA_TITLE, "combined.pdf")
        try { startActivityForResult(i, REQ_MERGE_SAVE) } catch (e: Exception) { toast("No app to choose where to save.") }
    }

    private fun runMerge(target: Uri, passwords: Map<Int, String> = emptyMap()) {
        val items = ArrayList(mergeList)
        val stop = java.util.concurrent.atomic.AtomicBoolean(false)
        val prog = Progress(this, "Combining", cancellable = true) { stop.set(true) }
        Thread {
            val copies = ArrayList<File>()
            var err: Throwable? = null
            var needPw = -1
            try {
                for ((k, it) in items.withIndex()) {
                    runOnUiThread { prog.update(k, items.size * 2, "Reading ${it.second}") }
                    copies.add(Files.copyToWork(this, it.first, it.second))
                }
                val out = Files.tempFile(this, "combined_${System.currentTimeMillis()}.pdf")
                try {
                    PageOps.merge(copies.mapIndexed { k, f -> f to passwords[k] }, out) { k, n ->
                        needPw = k
                        runOnUiThread { prog.update(n + k, n * 2, "Adding ${items[k].second}") }
                        !stop.get()
                    }
                    needPw = -1
                    Files.copyFileToUri(this, out, target)
                } finally { out.delete() }
            } catch (t: Throwable) { err = t }
            for (f in copies) f.delete()
            runOnUiThread {
                prog.close()
                if (!alive()) return@runOnUiThread
                val e = err
                when {
                    e is PdfEngine.PasswordNeeded && needPw >= 0 ->
                        askText("Password for ${items[needPw].second}", password = true) { pw ->
                            runMerge(target, passwords + (needPw to pw))
                        }
                    e != null -> showError("Could not combine", e)
                    else -> {
                        mergeList.clear()
                        Files.takePermission(this, target, true)
                        Store.addRecent(this, target, Files.displayName(this, target))
                        confirm("Done", "The PDFs were combined into one file.", "Open it") { openUri(target) }
                    }
                }
            }
        }.start()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null) {
            if (requestCode == REQ_MERGE_PICK && mergeList.isNotEmpty()) showMergeList()
            return
        }
        when (requestCode) {
            REQ_OPEN -> data.data?.let { uri ->
                Files.takePermission(this, uri, true)
                Store.addRecent(this, uri, Files.displayName(this, uri))
                openUri(uri)
            }
            REQ_MERGE_PICK -> {
                val uris = ArrayList<Uri>()
                val clip = data.clipData
                if (clip != null) for (k in 0 until clip.itemCount) uris.add(clip.getItemAt(k).uri)
                else data.data?.let { uris.add(it) }
                for (u in uris) mergeList.add(u to Files.displayName(this, u))
                showMergeList()
            }
            REQ_MERGE_SAVE -> data.data?.let { runMerge(it) }
        }
    }

    companion object {
        private const val REQ_OPEN = 1
        private const val REQ_MERGE_PICK = 2
        private const val REQ_MERGE_SAVE = 3
    }
}
