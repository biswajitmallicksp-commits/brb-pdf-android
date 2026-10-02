package com.brb.statementanalyzer.ledger

import com.brb.statementanalyzer.model.Ledger
import com.brb.statementanalyzer.model.LedgerRow
import com.brb.statementanalyzer.model.RowKind
import com.brb.statementanalyzer.model.Statement
import com.brb.statementanalyzer.model.Txn
import java.time.LocalDate
import kotlin.math.round

object LedgerBuilder {
    const val DAYS = 365

    /** The 365-day window starts on the earliest statement's first date. */
    fun defaultStart(statements: List<Statement>, txns: List<Txn>): LocalDate? =
        statements.mapNotNull { it.periodStart }.minOrNull() ?: txns.minOfOrNull { it.date }

    /**
     * Merges all statements of one account into a day-by-day ledger of [days] days.
     *
     * - Every day appears at least once.
     * - A day with several transactions gets one row per transaction; only the last
     *   row carries the day-end balance.
     * - A covered day without transactions gets one row with 0 debit/credit and the
     *   previous day's balance carried forward.
     * - A day outside every uploaded statement is marked NOT_COVERED.
     * - Transactions repeated in overlapping statements are counted once.
     */
    fun build(statements: List<Statement>, txns: List<Txn>, start: LocalDate, days: Int = DAYS): Ledger {
        val end = start.plusDays(days - 1L)
        val ordered = statements.sortedWith(
            compareBy<Statement, LocalDate?>(nullsLast()) { it.periodStart }.thenBy { it.importedAt }
        )
        val txnsByStatement = txns.groupBy { it.statementId }

        // Merge statements in period order, dropping transactions already seen in an earlier statement.
        val merged = ArrayList<Txn>()
        val seen = HashSet<String>()
        val ranges = ArrayList<ClosedRange<LocalDate>>()
        for (s in ordered) {
            val own = txnsByStatement[s.id].orEmpty().sortedBy { it.seq }
            val from = s.periodStart ?: own.minOfOrNull { it.date }
            val to = s.periodEnd ?: own.maxOfOrNull { it.date }
            if (from != null && to != null && !to.isBefore(from)) ranges += from..to
            val keys = own.map(::dedupeKey)
            own.forEachIndexed { i, t -> if (keys[i] !in seen) merged += t }
            seen += keys
        }
        // sortedBy is stable, so same-day transactions keep their statement order.
        val sorted = merged.sortedBy { it.date }

        var balance: Double? = ordered.firstOrNull()?.openingBalance
        fun apply(t: Txn) {
            if (balance == null) balance = t.balance?.let { it - t.credit + t.debit } ?: 0.0
            balance = t.balance ?: (balance!! + t.credit - t.debit)
        }

        var i = 0
        while (i < sorted.size && sorted[i].date.isBefore(start)) apply(sorted[i++])
        if (balance == null && i < sorted.size) {
            val t = sorted[i]
            balance = t.balance?.let { it - t.credit + t.debit }
        }
        val opening = balance

        val rows = ArrayList<LedgerRow>(days + sorted.size)
        var covered = 0
        var totalDebit = 0.0
        var totalCredit = 0.0
        var lastCoveredBalance: Double? = null
        var firstMissing: LocalDate? = null
        var day = start
        while (!day.isAfter(end)) {
            val dayTxns = ArrayList<Txn>()
            while (i < sorted.size && sorted[i].date == day) dayTxns += sorted[i++]
            val inStatement = dayTxns.isNotEmpty() || ranges.any { day in it }
            when {
                dayTxns.isNotEmpty() -> dayTxns.forEachIndexed { idx, t ->
                    apply(t)
                    totalDebit += t.debit
                    totalCredit += t.credit
                    rows += LedgerRow(
                        date = day,
                        description = t.description,
                        debit = t.debit,
                        credit = t.credit,
                        dayEndBalance = if (idx == dayTxns.lastIndex) round2(balance) else null,
                        kind = RowKind.TRANSACTION,
                    )
                }
                inStatement -> rows += LedgerRow(day, "No transaction", 0.0, 0.0, round2(balance), RowKind.NO_TRANSACTION)
                else -> {
                    if (firstMissing == null) firstMissing = day
                    rows += LedgerRow(day, "Statement not uploaded", 0.0, 0.0, null, RowKind.NOT_COVERED)
                }
            }
            if (inStatement) {
                covered++
                lastCoveredBalance = balance
            }
            day = day.plusDays(1)
        }

        return Ledger(
            rows = rows,
            start = start,
            end = end,
            daysCovered = covered,
            totalDays = days,
            totalDebit = round2(totalDebit)!!,
            totalCredit = round2(totalCredit)!!,
            openingBalance = round2(opening),
            closingBalance = round2(lastCoveredBalance),
            firstMissingDate = firstMissing,
        )
    }

    private fun dedupeKey(t: Txn) =
        "${t.date}|${t.description.lowercase().filter(Char::isLetterOrDigit)}|${round2(t.debit)}|${round2(t.credit)}|${round2(t.balance)}"

    private fun round2(v: Double?): Double? = v?.let { round(it * 100) / 100 }
}
