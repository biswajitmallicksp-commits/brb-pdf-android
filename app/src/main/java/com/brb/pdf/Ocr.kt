package com.brb.pdf

import android.content.Context
import android.graphics.Bitmap
import com.artifex.mupdf.fitz.Font
import com.googlecode.tesseract.android.TessBaseAPI
import java.io.File

/**
 * Offline OCR with Tesseract (English, Bengali, Hindi). Nothing leaves the phone.
 *
 * The language files (eng/ben/hin .traineddata) are packed inside the app
 * (app/src/main/assets/tessdata) and copied to the app's private storage the
 * first time OCR is used.
 */
object Ocr {
    val LANGUAGES = listOf("eng" to "English", "ben" to "Bengali", "hin" to "Hindi")

    fun installedLanguages(ctx: Context): List<String> {
        val inAssets = try { ctx.assets.list("tessdata")?.toList() ?: emptyList() } catch (e: Exception) { emptyList() }
        return LANGUAGES.map { it.first }.filter { "$it.traineddata" in inAssets }
    }

    /** Copy language files from the app package to private storage (once). Returns the folder
     *  that CONTAINS "tessdata" (what Tesseract wants). */
    fun prepare(ctx: Context, langs: List<String>, progress: (String) -> Unit): File {
        val base = File(ctx.filesDir, "ocr")
        val dir = File(base, "tessdata").apply { mkdirs() }
        for (lang in langs) {
            val target = File(dir, "$lang.traineddata")
            val asset = "tessdata/$lang.traineddata"
            val size = try { ctx.assets.openFd(asset).use { it.length } } catch (e: Exception) { -1L }
            if (target.exists() && (size < 0 || target.length() == size)) continue
            progress("Preparing ${LANGUAGES.firstOrNull { it.first == lang }?.second ?: lang} (first time only)...")
            val tmp = File(dir, "$lang.tmp")
            ctx.assets.open(asset).use { input -> tmp.outputStream().use { input.copyTo(it, 1 shl 16) } }
            tmp.renameTo(target)
        }
        return base
    }

    fun glyphlessFont(ctx: Context): Font {
        val f = File(ctx.filesDir, "ocr_glyphless.ttf")
        if (!f.exists()) ctx.assets.open("ocr_glyphless.ttf").use { i -> f.outputStream().use { i.copyTo(it) } }
        return Font(f.absolutePath)
    }

    class Session(dataDir: File, langs: List<String>) {
        private val api = TessBaseAPI()

        init {
            val path = dataDir.absolutePath.trimEnd('/') + "/"
            if (!api.init(path, langs.joinToString("+"), TessBaseAPI.OEM_LSTM_ONLY)) {
                api.recycle()
                throw UserError("OCR could not start. The language files may be missing or damaged.")
            }
            api.setPageSegMode(TessBaseAPI.PageSegMode.PSM_AUTO)
        }

        /** Recognise a page picture. `scale` = pixels per point used to render it; `x0`,`y0` = page
         *  bounds origin. Returns words in page space. */
        fun recognize(bitmap: Bitmap, scale: Float, x0: Float, y0: Float): List<TextLayer.Word> {
            api.setImage(bitmap)
            api.getUTF8Text()                     // runs the recognition
            val words = ArrayList<TextLayer.Word>()
            val it = api.resultIterator ?: return words
            try {
                val level = TessBaseAPI.PageIteratorLevel.RIL_WORD
                it.begin()
                do {
                    val text = it.getUTF8Text(level)?.trim() ?: continue
                    if (text.isEmpty()) continue
                    val r = it.getBoundingRect(level) ?: continue
                    words.add(TextLayer.Word(x0 + r.left / scale, y0 + r.top / scale,
                        x0 + r.right / scale, y0 + r.bottom / scale, text))
                } while (it.next(level))
            } finally {
                it.delete()
            }
            api.clear()
            return words
        }

        fun stop() = try { api.stop() } catch (_: Throwable) { }

        fun close() = try { api.recycle() } catch (_: Throwable) { }
    }
}
