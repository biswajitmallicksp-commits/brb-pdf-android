package com.brb.statementanalyzer

import android.annotation.SuppressLint
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.IntentCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * Hosts the offline HTML app (web/index.html, bundled as assets) in a WebView.
 * The app makes no network requests: PDFs are read on the device by pdf.js and
 * statements are stored in the WebView's IndexedDB.
 */
class MainActivity : ComponentActivity() {
    private lateinit var web: WebView
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var pendingSave: String? = null
    private var pageReady = false
    private val pendingShares = ArrayList<Uri>()

    private val pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val callback = fileCallback ?: return@registerForActivityResult
        fileCallback = null
        val data = result.data
        val uris = if (result.resultCode != RESULT_OK || data == null) {
            null
        } else {
            data.clipData?.let { clip -> Array(clip.itemCount) { clip.getItemAt(it).uri } } ?: data.data?.let { arrayOf(it) }
        }
        callback.onReceiveValue(uris)
    }

    private val createDocument = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val content = pendingSave ?: return@registerForActivityResult
        pendingSave = null
        val uri = result.data?.data
        if (result.resultCode != RESULT_OK || uri == null) return@registerForActivityResult
        try {
            contentResolver.openOutputStream(uri)?.use { it.write(content.toByteArray()) }
            Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "Could not save: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val night = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        val container = FrameLayout(this).apply { setBackgroundColor(Color.parseColor(if (night) "#0e1614" else "#f3f6f5")) }
        web = WebView(this)
        container.addView(web, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        setContentView(container)
        ViewCompat.setOnApplyWindowInsetsListener(container) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
        }
        web.addJavascriptInterface(Bridge(), "AndroidBridge")

        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
        web.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val url = request.url
                if (url.host == APP_HOST && url.path == "/assets/index.html") {
                    // index.html is written as a page body (the same file is published as a web page),
                    // so wrap it in a full document here.
                    val body = assets.open("index.html").bufferedReader().use { it.readText() }
                    val html = "<!doctype html><html><head><meta charset=\"utf-8\">" +
                        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head><body style=\"margin:0\">" +
                        body + "</body></html>"
                    return WebResourceResponse("text/html", "utf-8", html.byteInputStream())
                }
                if (url.host == APP_HOST) return assetLoader.shouldInterceptRequest(url)
                // Block every other request: the app works fully offline.
                return WebResourceResponse("text/plain", "utf-8", 403, "Offline", emptyMap(), "".byteInputStream())
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == APP_HOST) return false
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, request.url)) }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                pageReady = true
                flushShares()
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    val types = params.acceptTypes.filter { it.contains('/') }
                    type = types.firstOrNull() ?: "*/*"
                    if (types.size > 1) putExtra(Intent.EXTRA_MIME_TYPES, types.toTypedArray())
                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.mode == FileChooserParams.MODE_OPEN_MULTIPLE)
                }
                return try {
                    pickFiles.launch(intent)
                    true
                } catch (e: Exception) {
                    fileCallback = null
                    false
                }
            }
        }

        if (savedInstanceState == null) collectShares(intent)
        web.loadUrl("https://$APP_HOST/assets/index.html")
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        collectShares(intent)
        flushShares()
    }

    /** PDFs shared or opened from Google Drive, Gmail or Files. */
    private fun collectShares(intent: Intent?) {
        when (intent?.action) {
            Intent.ACTION_SEND ->
                IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)?.let { pendingShares += it }
            Intent.ACTION_SEND_MULTIPLE ->
                IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)?.let { pendingShares += it }
            Intent.ACTION_VIEW -> intent.data?.let { pendingShares += it }
        }
    }

    private fun flushShares() {
        if (!pageReady || pendingShares.isEmpty()) return
        val uris = pendingShares.toList()
        pendingShares.clear()
        thread {
            for (uri in uris) {
                try {
                    val name = displayName(uri)
                    val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: continue
                    val b64 = Base64.encodeToString(bytes, Base64.NO_WRAP)
                    runOnUiThread { web.evaluateJavascript("window.importSharedPdf(${JSONObject.quote(name)}, '$b64')", null) }
                } catch (e: Exception) {
                    runOnUiThread { Toast.makeText(this, "Could not open file: ${e.message}", Toast.LENGTH_LONG).show() }
                }
            }
        }
    }

    private fun displayName(uri: Uri): String = runCatching {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    }.getOrNull() ?: uri.lastPathSegment ?: "statement.pdf"

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    /** Lets the page save CSV exports and backups through Android's "Save to" picker (Drive included). */
    inner class Bridge {
        @JavascriptInterface
        fun saveFile(name: String, mime: String, content: String) {
            runOnUiThread {
                pendingSave = content
                createDocument.launch(
                    Intent(Intent.ACTION_CREATE_DOCUMENT)
                        .addCategory(Intent.CATEGORY_OPENABLE)
                        .setType(mime)
                        .putExtra(Intent.EXTRA_TITLE, name)
                )
            }
        }
    }

    companion object {
        private const val APP_HOST = "appassets.androidplatform.net"
    }
}
