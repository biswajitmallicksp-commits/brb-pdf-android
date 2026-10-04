package com.brb.pdf

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File
import java.io.FileNotFoundException

/**
 * Lets other apps (WhatsApp, Gmail, printers...) read a file the user chose to
 * share - and only files in the app's private "share" folder.
 */
class ShareProvider : ContentProvider() {
    companion object {
        const val AUTHORITY = "com.brb.pdf.share"

        fun shareDir(ctx: Context) = File(ctx.cacheDir, "share").apply { mkdirs() }

        fun uriFor(file: File): Uri = Uri.Builder().scheme("content").authority(AUTHORITY)
            .appendPath(file.name).build()
    }

    private fun fileFor(uri: Uri): File {
        val name = uri.lastPathSegment ?: throw FileNotFoundException()
        val dir = shareDir(context!!)
        val f = File(dir, name)
        if (f.parentFile?.canonicalPath != dir.canonicalPath || !f.exists()) throw FileNotFoundException(name)
        return f
    }

    override fun onCreate() = true

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor =
        ParcelFileDescriptor.open(fileFor(uri), ParcelFileDescriptor.MODE_READ_ONLY)

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?,
                       sortOrder: String?): Cursor {
        val f = fileFor(uri)
        val cols = projection ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        val row = cols.map { if (it == OpenableColumns.SIZE) f.length() else if (it == OpenableColumns.DISPLAY_NAME) f.name else null }
        return MatrixCursor(cols).apply { addRow(row.toTypedArray()) }
    }

    override fun getType(uri: Uri): String = if (uri.toString().endsWith(".txt")) "text/plain" else "application/pdf"
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
}
