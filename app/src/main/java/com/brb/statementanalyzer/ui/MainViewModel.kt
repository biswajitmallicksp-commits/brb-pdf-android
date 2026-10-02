package com.brb.statementanalyzer.ui

import android.app.Application
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.brb.statementanalyzer.ai.GeminiClient
import com.brb.statementanalyzer.data.StatementDb
import com.brb.statementanalyzer.ledger.DateParse
import com.brb.statementanalyzer.ledger.LedgerBuilder
import com.brb.statementanalyzer.model.Ledger
import com.brb.statementanalyzer.model.RowKind
import com.brb.statementanalyzer.model.Statement
import com.brb.statementanalyzer.pdf.PdfUnlocker
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.util.Locale

data class Account(val key: String, val label: String)

class PasswordRequest(val fileName: String, val wrongAttempt: Boolean) {
    val answer = CompletableDeferred<String?>()
}

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val db = StatementDb(app)
    private val prefs = app.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private val importLock = Mutex()

    var apiKey by mutableStateOf(prefs.getString("api_key", "") ?: "")
        private set
    var model by mutableStateOf(prefs.getString("model", GeminiClient.DEFAULT_MODEL) ?: GeminiClient.DEFAULT_MODEL)
        private set

    var statements by mutableStateOf<List<Statement>>(emptyList())
        private set
    var accounts by mutableStateOf<List<Account>>(emptyList())
        private set
    var selectedAccount by mutableStateOf<String?>(null)
        private set
    /** User-chosen first day of the 365-day window; null means "earliest statement date". */
    var startOverride by mutableStateOf<LocalDate?>(null)
        private set
    var ledger by mutableStateOf<Ledger?>(null)
        private set
    var progress by mutableStateOf<String?>(null)
        private set
    var message by mutableStateOf<String?>(null)
    var passwordRequest by mutableStateOf<PasswordRequest?>(null)
        private set

    init {
        PdfUnlocker.init(app)
        refresh()
    }

    fun saveSettings(key: String, modelName: String) {
        apiKey = key.trim()
        model = modelName.trim().ifEmpty { GeminiClient.DEFAULT_MODEL }
        prefs.edit().putString("api_key", apiKey).putString("model", model).apply()
        message = "Settings saved"
    }

    fun selectAccount(key: String) {
        selectedAccount = key
        startOverride = null
        refresh()
    }

    fun setStart(date: LocalDate?) {
        startOverride = date
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            val all = withContext(Dispatchers.IO) { db.listStatements() }
            statements = all
            accounts = all.groupBy { it.accountKey }.map { (key, list) ->
                val s = list.first()
                val tail = s.accountNumber.filter(Char::isDigit).takeLast(4).ifEmpty { s.accountNumber }
                Account(key, "${s.bankName} • ${s.accountHolder} • ••$tail")
            }
            if (selectedAccount !in accounts.map { it.key }) selectedAccount = accounts.firstOrNull()?.key
            val key = selectedAccount
            ledger = if (key == null) null else withContext(Dispatchers.Default) {
                val chosen = all.filter { it.accountKey == key }
                val txns = db.transactionsFor(chosen.map { it.id })
                val start = startOverride ?: LedgerBuilder.defaultStart(chosen, txns)
                start?.let { LedgerBuilder.build(chosen, txns, it) }
            }
        }
    }

    fun deleteStatement(id: Long) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { db.delete(id) }
            refresh()
        }
    }

    fun answerPassword(password: String?) {
        passwordRequest?.answer?.complete(password)
        passwordRequest = null
    }

    fun import(uris: List<Uri>) {
        if (uris.isEmpty()) return
        if (apiKey.isBlank()) {
            message = "Add your free Gemini API key in Settings first."
            return
        }
        viewModelScope.launch {
            importLock.withLock {
                val results = mutableListOf<String>()
                uris.forEachIndexed { index, uri ->
                    val name = displayName(uri)
                    results += try {
                        progress = "Reading $name (${index + 1}/${uris.size})"
                        val raw = withContext(Dispatchers.IO) {
                            getApplication<Application>().contentResolver.openInputStream(uri)?.use { it.readBytes() }
                        } ?: error("Cannot open file")
                        val pdf = unlock(raw, name) ?: error("skipped, no password entered")
                        progress = "Gemini is reading $name (${index + 1}/${uris.size})…\nThis can take a minute for long statements."
                        val parsed = withContext(Dispatchers.IO) { GeminiClient(apiKey, model).parse(pdf, name) }
                        withContext(Dispatchers.IO) { db.insert(parsed.statement, parsed.txns) }
                        selectedAccount = parsed.statement.accountKey
                        startOverride = null
                        val s = parsed.statement
                        "$name: ${s.bankName}, ${parsed.txns.size} transactions " +
                            "(${s.periodStart?.format(DateParse.display)} to ${s.periodEnd?.format(DateParse.display)})"
                    } catch (e: Exception) {
                        "$name: failed – ${e.message ?: e.javaClass.simpleName}"
                    }
                }
                progress = null
                message = results.joinToString("\n")
                refresh()
            }
        }
    }

    private suspend fun unlock(raw: ByteArray, name: String): ByteArray? {
        var password: String? = null
        var attempt = 0
        while (true) {
            withContext(Dispatchers.IO) { PdfUnlocker.unlock(raw, password) }?.let { return it }
            progress = null
            val request = PasswordRequest(name, wrongAttempt = attempt > 0)
            passwordRequest = request
            password = request.answer.await() ?: return null
            attempt++
        }
    }

    private fun displayName(uri: Uri): String = runCatching {
        getApplication<Application>().contentResolver
            .query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    }.getOrNull() ?: uri.lastPathSegment ?: "statement.pdf"

    fun suggestedCsvName(): String {
        val l = ledger ?: return "ledger.csv"
        val account = accounts.firstOrNull { it.key == selectedAccount }?.label?.substringBefore(" •") ?: "ledger"
        return "${account.replace(Regex("[^A-Za-z0-9]+"), "_")}_${l.start}_to_${l.end}.csv"
    }

    fun exportCsv(uri: Uri) {
        val l = ledger ?: return
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openOutputStream(uri)?.bufferedWriter()?.use { w ->
                        w.write("Date,Description of Transaction,Debit Amount,Credit Amount,Day End Balance\n")
                        for (r in l.rows) {
                            val balance = when {
                                r.kind == RowKind.NOT_COVERED -> ""
                                r.dayEndBalance == null -> "0"
                                else -> amount(r.dayEndBalance)
                            }
                            w.write(listOf(r.date.format(DateParse.display), csv(r.description), amount(r.debit), amount(r.credit), balance).joinToString(","))
                            w.write("\n")
                        }
                    } ?: error("Cannot write file")
                }
                message = "Exported ${l.rows.size} rows."
            } catch (e: Exception) {
                message = "Export failed: ${e.message}"
            }
        }
    }

    private fun amount(v: Double) = String.format(Locale.US, "%.2f", v)
    private fun csv(s: String) = "\"" + s.replace("\"", "\"\"") + "\""
}
