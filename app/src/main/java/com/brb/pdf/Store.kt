package com.brb.pdf

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Recent files and small settings, kept only on this phone. */
object Store {
    private const val PREFS = "brbpdf"
    private const val MAX_RECENT = 25

    data class Recent(val uri: String, val name: String, val time: Long, val lastPage: Int)

    fun recents(ctx: Context): List<Recent> {
        val raw = ctx.getSharedPreferences(PREFS, 0).getString("recent", "[]") ?: "[]"
        val arr = try { JSONArray(raw) } catch (e: Exception) { JSONArray() }
        return (0 until arr.length()).mapNotNull {
            val o = arr.optJSONObject(it) ?: return@mapNotNull null
            Recent(o.optString("uri"), o.optString("name"), o.optLong("time"), o.optInt("page"))
        }
    }

    fun addRecent(ctx: Context, uri: Uri, name: String, page: Int = -1) {
        val list = recents(ctx).toMutableList()
        val old = list.firstOrNull { it.uri == uri.toString() }
        list.removeAll { it.uri == uri.toString() }
        list.add(0, Recent(uri.toString(), name, System.currentTimeMillis(), if (page >= 0) page else old?.lastPage ?: 0))
        save(ctx, list.take(MAX_RECENT))
    }

    fun setLastPage(ctx: Context, uri: Uri, page: Int) {
        val list = recents(ctx).map { if (it.uri == uri.toString()) it.copy(lastPage = page) else it }
        save(ctx, list)
    }

    fun lastPage(ctx: Context, uri: Uri): Int = recents(ctx).firstOrNull { it.uri == uri.toString() }?.lastPage ?: 0

    fun removeRecent(ctx: Context, uri: String) = save(ctx, recents(ctx).filter { it.uri != uri })

    fun clearRecents(ctx: Context) = save(ctx, emptyList())

    private fun save(ctx: Context, list: List<Recent>) {
        val arr = JSONArray()
        for (r in list) arr.put(JSONObject().put("uri", r.uri).put("name", r.name).put("time", r.time).put("page", r.lastPage))
        ctx.getSharedPreferences(PREFS, 0).edit().putString("recent", arr.toString()).apply()
    }

    fun get(ctx: Context, key: String, def: String): String = ctx.getSharedPreferences(PREFS, 0).getString(key, def) ?: def
    fun put(ctx: Context, key: String, value: String) = ctx.getSharedPreferences(PREFS, 0).edit().putString(key, value).apply()
}

/** File helpers for Android's content:// documents. */
object Files {
    fun displayName(ctx: Context, uri: Uri): String {
        try {
            ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val name = c.getString(0)
                    if (!name.isNullOrBlank()) return name
                }
            }
        } catch (_: Exception) { }
        return uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "document.pdf"
    }

    /** Copy a document into the app's private working folder. */
    fun copyToWork(ctx: Context, uri: Uri, name: String): File {
        val dir = File(ctx.cacheDir, "work").apply { mkdirs() }
        val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), "_").ifBlank { "document.pdf" }
        val out = File(dir, "${System.currentTimeMillis()}_$safe")
        val input = ctx.contentResolver.openInputStream(uri) ?: throw UserError("The file could not be read.")
        input.use { i -> out.outputStream().use { i.copyTo(it, 1 shl 16) } }
        if (out.length() == 0L) throw UserError("The file is empty.")
        return out
    }

    fun copyFileToUri(ctx: Context, file: File, uri: Uri) {
        val os = ctx.contentResolver.openOutputStream(uri, "wt") ?: throw UserError("Cannot write to that location.")
        os.use { o -> file.inputStream().use { it.copyTo(o, 1 shl 16) } }
    }

    fun tempFile(ctx: Context, name: String): File {
        val dir = File(ctx.cacheDir, "out").apply { mkdirs() }
        return File(dir, name.replace(Regex("[\\\\/:*?\"<>|]"), "_"))
    }

    /** Delete old working copies (older than a day) to save space. */
    fun cleanup(ctx: Context) {
        val limit = System.currentTimeMillis() - 24L * 3600 * 1000
        for (d in listOf("work", "out", "share")) {
            File(ctx.cacheDir, d).listFiles()?.forEach { if (it.lastModified() < limit) it.delete() }
        }
    }

    fun takePermission(ctx: Context, uri: Uri, write: Boolean) {
        try {
            val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or (if (write) Intent.FLAG_GRANT_WRITE_URI_PERMISSION else 0)
            ctx.contentResolver.takePersistableUriPermission(uri, flags)
        } catch (_: Exception) {
            if (write) try { ctx.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) } catch (_: Exception) { }
        }
    }

    fun stem(name: String) = name.substringBeforeLast('.', name)
}
