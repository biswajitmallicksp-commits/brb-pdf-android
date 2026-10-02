package com.brb.statementanalyzer.model

import java.time.LocalDate

/** Metadata for one imported PDF statement. */
data class Statement(
    val id: Long = 0,
    val bankName: String,
    val accountHolder: String,
    val accountNumber: String,
    val periodStart: LocalDate?,
    val periodEnd: LocalDate?,
    val openingBalance: Double?,
    val closingBalance: Double?,
    val currency: String,
    val fileName: String,
    val importedAt: Long,
    val txnCount: Int = 0,
) {
    val accountKey: String get() = accountKeyOf(bankName, accountNumber)
}

/**
 * Statements of the same account are grouped by bank name plus the last four
 * digits of the account number, because banks mask numbers differently
 * (e.g. "XXXXXX1234" in one month and "00012341234" in another).
 */
fun accountKeyOf(bankName: String, accountNumber: String): String {
    val digits = accountNumber.filter(Char::isDigit)
    val tail = if (digits.length >= 4) digits.takeLast(4) else accountNumber.trim().lowercase()
    return "${bankName.trim().lowercase()}|$tail"
}

data class Txn(
    val id: Long = 0,
    val statementId: Long = 0,
    val seq: Int,
    val date: LocalDate,
    val description: String,
    val debit: Double,
    val credit: Double,
    /** Running balance printed on the statement, if any. */
    val balance: Double?,
)

enum class RowKind { TRANSACTION, NO_TRANSACTION, NOT_COVERED }

data class LedgerRow(
    val date: LocalDate,
    val description: String,
    val debit: Double,
    val credit: Double,
    /** Set only on the last row of a covered day; null on other rows or uncovered days. */
    val dayEndBalance: Double?,
    val kind: RowKind,
)

data class Ledger(
    val rows: List<LedgerRow>,
    val start: LocalDate,
    val end: LocalDate,
    val daysCovered: Int,
    val totalDays: Int,
    val totalDebit: Double,
    val totalCredit: Double,
    val openingBalance: Double?,
    val closingBalance: Double?,
    /** First date that has no statement uploaded, if any. */
    val firstMissingDate: LocalDate?,
)
