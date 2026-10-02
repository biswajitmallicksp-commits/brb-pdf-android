package com.brb.statementanalyzer.ai

import android.util.Base64
import com.brb.statementanalyzer.ledger.DateParse
import com.brb.statementanalyzer.model.Statement
import com.brb.statementanalyzer.model.Txn
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class ParsedStatement(val statement: Statement, val txns: List<Txn>)

/** Sends a PDF to the Gemini API and turns its structured JSON answer into a statement. */
class GeminiClient(private val apiKey: String, private val model: String) {

    private val http = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(2, TimeUnit.MINUTES)
        .readTimeout(6, TimeUnit.MINUTES)
        .build()

    fun parse(pdf: ByteArray, fileName: String): ParsedStatement {
        if (pdf.size > 19 * 1024 * 1024) throw IOException("PDF is larger than 19 MB; split it into smaller files.")
        val body = JSONObject()
            .put("contents", JSONArray().put(JSONObject().put("parts", JSONArray()
                .put(JSONObject().put("inline_data", JSONObject()
                    .put("mime_type", "application/pdf")
                    .put("data", Base64.encodeToString(pdf, Base64.NO_WRAP))))
                .put(JSONObject().put("text", PROMPT)))))
            .put("generationConfig", JSONObject()
                .put("temperature", 0)
                .put("maxOutputTokens", 65536)
                .put("responseMimeType", "application/json")
                .put("responseSchema", SCHEMA))

        val request = Request.Builder()
            .url("https://generativelanguage.googleapis.com/v1beta/models/${model.trim()}:generateContent")
            .header("x-goog-api-key", apiKey.trim())
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()

        val responseText = http.newCall(request).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                val msg = runCatching { JSONObject(text).getJSONObject("error").getString("message") }.getOrNull()
                throw IOException("Gemini error ${resp.code}: ${msg ?: text.take(300)}")
            }
            text
        }

        val candidate = JSONObject(responseText).optJSONArray("candidates")?.optJSONObject(0)
            ?: throw IOException("Gemini returned no answer (the PDF may have been blocked or unreadable).")
        if (candidate.optString("finishReason") == "MAX_TOKENS") {
            throw IOException("Statement is too long for one request; split the PDF into smaller parts.")
        }
        val parts = candidate.optJSONObject("content")?.optJSONArray("parts") ?: JSONArray()
        val json = buildString {
            for (i in 0 until parts.length()) {
                val p = parts.getJSONObject(i)
                if (!p.optBoolean("thought")) append(p.optString("text"))
            }
        }
        return toStatement(JSONObject(json), fileName)
    }

    private fun toStatement(o: JSONObject, fileName: String): ParsedStatement {
        val arr = o.optJSONArray("transactions") ?: JSONArray()
        val txns = (0 until arr.length()).mapNotNull { i ->
            val t = arr.getJSONObject(i)
            val date = DateParse.parse(t.optStringOrNull("date")) ?: return@mapNotNull null
            Txn(
                seq = i,
                date = date,
                description = t.optStringOrNull("description")?.replace(Regex("\\s+"), " ")?.trim().orEmpty(),
                debit = num(t, "debit") ?: 0.0,
                credit = num(t, "credit") ?: 0.0,
                balance = num(t, "balance"),
            )
        }
        if (txns.isEmpty() && arr.length() > 0) throw IOException("Could not read the transaction dates.")
        val statement = Statement(
            bankName = o.optStringOrNull("bank_name") ?: "Unknown bank",
            accountHolder = o.optStringOrNull("account_holder_name") ?: "Unknown",
            accountNumber = o.optStringOrNull("account_number") ?: "",
            periodStart = DateParse.parse(o.optStringOrNull("statement_start_date")) ?: txns.minOfOrNull { it.date },
            periodEnd = DateParse.parse(o.optStringOrNull("statement_end_date")) ?: txns.maxOfOrNull { it.date },
            openingBalance = num(o, "opening_balance"),
            closingBalance = num(o, "closing_balance"),
            currency = o.optStringOrNull("currency") ?: "INR",
            fileName = fileName,
            importedAt = System.currentTimeMillis(),
        )
        return ParsedStatement(statement, txns)
    }

    private fun JSONObject.optStringOrNull(key: String): String? =
        if (!has(key) || isNull(key)) null else optString(key).trim().takeIf { it.isNotEmpty() && it != "null" }

    private fun num(o: JSONObject, key: String): Double? {
        if (!o.has(key) || o.isNull(key)) return null
        return when (val v = o.get(key)) {
            is Number -> v.toDouble()
            is String -> {
                val negative = v.contains("Dr", ignoreCase = true) || v.trim().startsWith("-")
                v.replace(Regex("[^0-9.]"), "").toDoubleOrNull()?.let { if (negative) -it else it }
            }
            else -> null
        }
    }

    companion object {
        const val DEFAULT_MODEL = "gemini-2.5-flash"

        private val PROMPT = """
            You are a precise bank statement parser. Read this bank statement PDF and extract its metadata
            and EVERY transaction, in the exact order printed (top to bottom, across all pages).
            Rules:
            - All dates as YYYY-MM-DD. Indian and UK statements print DD/MM/YYYY; use the statement period to
              resolve day/month ambiguity.
            - debit = money going out (withdrawal / Dr). credit = money coming in (deposit / Cr). Use 0 when empty.
              Amounts are plain positive numbers without commas or currency symbols.
            - balance = the running balance printed on that transaction's line, or null if none is printed.
              If the balance is overdrawn (marked Dr or negative), return it as a negative number.
            - Do NOT return "Opening balance", "Balance brought forward", "Closing balance", totals or summary
              lines as transactions; use them for opening_balance and closing_balance instead.
            - description = the full narration/particulars joined into one line (include cheque/ref numbers).
            - statement_start_date / statement_end_date = the statement period printed on the statement; if it
              is not printed, use the first and last transaction dates.
            - account_holder_name = the customer's name; bank_name = the bank's name (e.g. "State Bank of India").
            - currency = ISO code such as INR or USD.
        """.trimIndent()

        private fun prop(type: String, nullable: Boolean = false) =
            JSONObject().put("type", type).apply { if (nullable) put("nullable", true) }

        private val SCHEMA: JSONObject = JSONObject()
            .put("type", "OBJECT")
            .put("properties", JSONObject()
                .put("bank_name", prop("STRING"))
                .put("account_holder_name", prop("STRING"))
                .put("account_number", prop("STRING"))
                .put("currency", prop("STRING"))
                .put("statement_start_date", prop("STRING"))
                .put("statement_end_date", prop("STRING"))
                .put("opening_balance", prop("NUMBER", nullable = true))
                .put("closing_balance", prop("NUMBER", nullable = true))
                .put("transactions", JSONObject()
                    .put("type", "ARRAY")
                    .put("items", JSONObject()
                        .put("type", "OBJECT")
                        .put("properties", JSONObject()
                            .put("date", prop("STRING"))
                            .put("description", prop("STRING"))
                            .put("debit", prop("NUMBER"))
                            .put("credit", prop("NUMBER"))
                            .put("balance", prop("NUMBER", nullable = true)))
                        .put("required", JSONArray(listOf("date", "description", "debit", "credit", "balance")))
                        .put("propertyOrdering", JSONArray(listOf("date", "description", "debit", "credit", "balance"))))))
            .put("required", JSONArray(listOf(
                "bank_name", "account_holder_name", "account_number", "currency",
                "statement_start_date", "statement_end_date", "opening_balance", "closing_balance", "transactions",
            )))
            .put("propertyOrdering", JSONArray(listOf(
                "bank_name", "account_holder_name", "account_number", "currency", "statement_start_date",
                "statement_end_date", "opening_balance", "closing_balance", "transactions",
            )))
    }
}
