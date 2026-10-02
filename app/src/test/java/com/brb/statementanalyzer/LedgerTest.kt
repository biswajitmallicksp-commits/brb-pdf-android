package com.brb.statementanalyzer

import com.brb.statementanalyzer.ledger.*
import com.brb.statementanalyzer.model.*
import java.time.LocalDate
import kotlin.test.*

class LedgerTest {
    val d = { s: String -> LocalDate.parse(s) }
    val june = Statement(1, "SBI", "Biswajit", "XXXX1234", d("2025-06-01"), d("2025-06-30"), 1000.0, null, "INR", "june.pdf", 1)
    val julyOverlap = Statement(2, "SBI", "Biswajit", "0001234", d("2025-06-30"), d("2025-07-31"), null, null, "INR", "july.pdf", 2)
    val txns = listOf(
        Txn(statementId = 1, seq = 0, date = d("2025-06-01"), description = "UPI A", debit = 100.0, credit = 0.0, balance = 900.0),
        Txn(statementId = 1, seq = 1, date = d("2025-06-01"), description = "Salary", debit = 0.0, credit = 500.0, balance = 1400.0),
        Txn(statementId = 1, seq = 2, date = d("2025-06-30"), description = "ATM", debit = 400.0, credit = 0.0, balance = 1000.0),
        Txn(statementId = 2, seq = 0, date = d("2025-06-30"), description = "ATM", debit = 400.0, credit = 0.0, balance = 1000.0),
        Txn(statementId = 2, seq = 1, date = d("2025-07-05"), description = "Shop", debit = 50.0, credit = 0.0, balance = null),
    )

    @Test fun ledger() {
        val start = LedgerBuilder.defaultStart(listOf(julyOverlap, june), txns)!!
        assertEquals(d("2025-06-01"), start)
        val l = LedgerBuilder.build(listOf(julyOverlap, june), txns, start)
        assertEquals(d("2026-05-31"), l.end)
        assertEquals(365, l.rows.map { it.date }.distinct().size)
        assertEquals(366, l.rows.size) // one extra row for the 2-transaction day
        assertEquals(l.rows[0].dayEndBalance, null)
        assertEquals(1400.0, l.rows[1].dayEndBalance)
        assertEquals(RowKind.NO_TRANSACTION, l.rows[2].kind)
        assertEquals(1400.0, l.rows[2].dayEndBalance)
        assertEquals(1, l.rows.count { it.description == "ATM" })
        val shop = l.rows.first { it.description == "Shop" }
        assertEquals(950.0, shop.dayEndBalance)
        assertEquals(950.0, l.rows.first { it.date == d("2025-07-31") }.dayEndBalance)
        assertEquals(RowKind.NOT_COVERED, l.rows.first { it.date == d("2025-08-01") }.kind)
        assertEquals(d("2025-08-01"), l.firstMissingDate)
        assertEquals(61, l.daysCovered)
        assertEquals(1000.0, l.openingBalance); assertEquals(950.0, l.closingBalance)
        assertEquals(550.0, l.totalDebit); assertEquals(500.0, l.totalCredit)
        assertEquals(june.accountKey, julyOverlap.accountKey)
    }

    @Test fun midStartAndDerivedOpening() {
        val noOpening = june.copy(openingBalance = null)
        val l = LedgerBuilder.build(listOf(noOpening), txns.filter { it.statementId == 1L }, d("2025-06-01"))
        assertEquals(1000.0, l.openingBalance)
        val mid = LedgerBuilder.build(listOf(june), txns.filter { it.statementId == 1L }, d("2025-06-10"), 30)
        assertEquals(1400.0, mid.openingBalance)
        assertEquals(1400.0, mid.rows[0].dayEndBalance)
    }

    @Test fun dates() {
        assertEquals(d("2025-06-01"), DateParse.parse("01/06/2025"))
        assertEquals(d("2025-06-01"), DateParse.parse("01-Jun-2025"))
        assertEquals(d("2025-06-01"), DateParse.parse("01 JUN 25"))
        assertEquals(d("2025-06-01"), DateParse.parse("2025-06-01"))
        assertNull(DateParse.parse("null"))
    }
}
