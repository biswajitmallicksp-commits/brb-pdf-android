package com.brb.statementanalyzer.data

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.brb.statementanalyzer.model.Statement
import com.brb.statementanalyzer.model.Txn
import java.time.LocalDate

/** On-device SQLite database: one row per statement (metadata) plus its transactions. */
class StatementDb(context: Context) : SQLiteOpenHelper(context, "statements.db", null, 1) {

    override fun onConfigure(db: SQLiteDatabase) {
        db.setForeignKeyConstraintsEnabled(true)
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE statements(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bank_name TEXT NOT NULL,
                account_holder TEXT NOT NULL,
                account_number TEXT NOT NULL,
                period_start TEXT,
                period_end TEXT,
                opening_balance REAL,
                closing_balance REAL,
                currency TEXT NOT NULL,
                file_name TEXT NOT NULL,
                imported_at INTEGER NOT NULL)"""
        )
        db.execSQL(
            """CREATE TABLE transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                debit REAL NOT NULL,
                credit REAL NOT NULL,
                balance REAL)"""
        )
        db.execSQL("CREATE INDEX idx_txn_statement ON transactions(statement_id)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    /**
     * Saves a statement and its transactions. Re-importing the same account and
     * period replaces the earlier copy instead of duplicating it.
     */
    fun insert(statement: Statement, txns: List<Txn>): Long {
        val db = writableDatabase
        db.beginTransaction()
        try {
            listStatements()
                .filter {
                    it.accountKey == statement.accountKey &&
                        it.periodStart == statement.periodStart && it.periodEnd == statement.periodEnd
                }
                .forEach { db.delete("statements", "id = ?", arrayOf(it.id.toString())) }

            val id = db.insertOrThrow("statements", null, ContentValues().apply {
                put("bank_name", statement.bankName)
                put("account_holder", statement.accountHolder)
                put("account_number", statement.accountNumber)
                put("period_start", statement.periodStart?.toString())
                put("period_end", statement.periodEnd?.toString())
                put("opening_balance", statement.openingBalance)
                put("closing_balance", statement.closingBalance)
                put("currency", statement.currency)
                put("file_name", statement.fileName)
                put("imported_at", statement.importedAt)
            })
            txns.forEach { t ->
                db.insertOrThrow("transactions", null, ContentValues().apply {
                    put("statement_id", id)
                    put("seq", t.seq)
                    put("date", t.date.toString())
                    put("description", t.description)
                    put("debit", t.debit)
                    put("credit", t.credit)
                    put("balance", t.balance)
                })
            }
            db.setTransactionSuccessful()
            return id
        } finally {
            db.endTransaction()
        }
    }

    fun listStatements(): List<Statement> = readableDatabase.rawQuery(
        """SELECT s.*, (SELECT COUNT(*) FROM transactions t WHERE t.statement_id = s.id) AS txn_count
           FROM statements s ORDER BY s.period_start, s.imported_at""",
        null,
    ).use { c ->
        buildList {
            while (c.moveToNext()) add(
                Statement(
                    id = c.long("id"),
                    bankName = c.str("bank_name")!!,
                    accountHolder = c.str("account_holder")!!,
                    accountNumber = c.str("account_number")!!,
                    periodStart = c.str("period_start")?.let(LocalDate::parse),
                    periodEnd = c.str("period_end")?.let(LocalDate::parse),
                    openingBalance = c.dbl("opening_balance"),
                    closingBalance = c.dbl("closing_balance"),
                    currency = c.str("currency")!!,
                    fileName = c.str("file_name")!!,
                    importedAt = c.long("imported_at"),
                    txnCount = c.long("txn_count").toInt(),
                )
            )
        }
    }

    fun transactionsFor(statementIds: Collection<Long>): List<Txn> {
        if (statementIds.isEmpty()) return emptyList()
        val placeholders = statementIds.joinToString(",") { "?" }
        return readableDatabase.rawQuery(
            "SELECT * FROM transactions WHERE statement_id IN ($placeholders) ORDER BY statement_id, seq",
            statementIds.map(Long::toString).toTypedArray(),
        ).use { c ->
            buildList {
                while (c.moveToNext()) add(
                    Txn(
                        id = c.long("id"),
                        statementId = c.long("statement_id"),
                        seq = c.long("seq").toInt(),
                        date = LocalDate.parse(c.str("date")),
                        description = c.str("description")!!,
                        debit = c.dbl("debit") ?: 0.0,
                        credit = c.dbl("credit") ?: 0.0,
                        balance = c.dbl("balance"),
                    )
                )
            }
        }
    }

    fun delete(statementId: Long) {
        writableDatabase.delete("statements", "id = ?", arrayOf(statementId.toString()))
    }

    private fun Cursor.idx(name: String) = getColumnIndexOrThrow(name)
    private fun Cursor.str(name: String): String? = idx(name).let { if (isNull(it)) null else getString(it) }
    private fun Cursor.long(name: String): Long = getLong(idx(name))
    private fun Cursor.dbl(name: String): Double? = idx(name).let { if (isNull(it)) null else getDouble(it) }
}
