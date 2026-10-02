package com.brb.statementanalyzer.ledger

import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeFormatterBuilder
import java.util.Locale

object DateParse {
    private val patterns = listOf(
        "yyyy-MM-dd", "dd/MM/yyyy", "dd-MM-yyyy", "dd.MM.yyyy", "d/M/yyyy", "d-M-yyyy",
        "dd MMM yyyy", "dd-MMM-yyyy", "d MMM yyyy", "dd MMM yy", "dd-MMM-yy", "dd/MM/yy", "dd-MM-yy",
        "MMM dd, yyyy", "d MMMM yyyy", "dd MMMM yyyy",
    ).map {
        DateTimeFormatterBuilder().parseCaseInsensitive().appendPattern(it).toFormatter(Locale.ENGLISH)
    }

    fun parse(text: String?): LocalDate? {
        val s = text?.trim()?.takeIf { it.isNotEmpty() && it.lowercase() != "null" } ?: return null
        for (f in patterns) {
            try {
                val d = LocalDate.parse(s, f)
                // Two-digit years parse as 20xx, which is what statements mean.
                return d
            } catch (_: Exception) {
            }
        }
        return null
    }

    val display: DateTimeFormatter = DateTimeFormatter.ofPattern("dd-MMM-yyyy", Locale.ENGLISH)
}
