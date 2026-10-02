package com.brb.statementanalyzer.pdf

import android.content.Context
import com.tom_roush.pdfbox.android.PDFBoxResourceLoader
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.pdmodel.encryption.InvalidPasswordException
import java.io.ByteArrayOutputStream

/** Many banks e-mail password-protected statements; Gemini can only read unlocked PDFs. */
object PdfUnlocker {
    fun init(context: Context) = PDFBoxResourceLoader.init(context.applicationContext)

    /**
     * Returns the PDF bytes with encryption removed, the original bytes if it was not
     * encrypted (or PDFBox could not parse it), or null if a (different) password is needed.
     */
    fun unlock(bytes: ByteArray, password: String?): ByteArray? = try {
        PDDocument.load(bytes, password ?: "").use { doc ->
            if (!doc.isEncrypted) {
                bytes
            } else {
                doc.setAllSecurityToBeRemoved(true)
                ByteArrayOutputStream().also { doc.save(it) }.toByteArray()
            }
        }
    } catch (e: InvalidPasswordException) {
        null
    } catch (e: Exception) {
        bytes
    }
}
