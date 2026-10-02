package com.brb.statementanalyzer.ui

import android.app.DatePickerDialog
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.IntentCompat
import com.brb.statementanalyzer.ledger.DateParse
import com.brb.statementanalyzer.model.Ledger
import com.brb.statementanalyzer.model.LedgerRow
import com.brb.statementanalyzer.model.RowKind
import java.text.NumberFormat
import java.time.LocalDate
import java.util.Locale

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handleShare(intent)
        setContent { AppTheme { App(vm) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
    }

    /** PDFs shared or opened from Google Drive, Gmail or Files land here. */
    private fun handleShare(intent: Intent?) {
        val uris = when (intent?.action) {
            Intent.ACTION_SEND -> listOfNotNull(IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java))
            Intent.ACTION_SEND_MULTIPLE ->
                IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
            Intent.ACTION_VIEW -> listOfNotNull(intent.data)
            else -> emptyList()
        }
        vm.import(uris)
    }
}

@Composable
private fun AppTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val context = LocalContext.current
    val scheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        dark -> darkColorScheme()
        else -> lightColorScheme(primary = Color(0xFF0B5CAD))
    }
    MaterialTheme(colorScheme = scheme, content = content)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun App(vm: MainViewModel) {
    var tab by rememberSaveable { mutableIntStateOf(if (vm.apiKey.isBlank()) 2 else 0) }
    val pickPdfs = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { vm.import(it) }
    val saveCsv = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        uri?.let(vm::exportCsv)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(listOf("365-Day Ledger", "Statements", "Settings")[tab]) },
                actions = {
                    if (tab == 0 && vm.ledger != null) {
                        IconButton(onClick = { saveCsv.launch(vm.suggestedCsvName()) }) {
                            Icon(Icons.Default.Share, contentDescription = "Export CSV")
                        }
                    }
                },
            )
        },
        floatingActionButton = {
            if (tab != 2) {
                ExtendedFloatingActionButton(
                    onClick = { pickPdfs.launch(arrayOf("application/pdf")) },
                    icon = { Icon(Icons.Default.Add, null) },
                    text = { Text("Upload PDF") },
                )
            }
        },
        bottomBar = {
            NavigationBar {
                NavigationBarItem(tab == 0, { tab = 0 }, { Icon(Icons.Default.DateRange, null) }, label = { Text("Ledger") })
                NavigationBarItem(tab == 1, { tab = 1 }, { Icon(Icons.Default.List, null) }, label = { Text("Statements") })
                NavigationBarItem(tab == 2, { tab = 2 }, { Icon(Icons.Default.Settings, null) }, label = { Text("Settings") })
            }
        },
    ) { padding ->
        Box(Modifier.padding(padding).fillMaxSize()) {
            when (tab) {
                0 -> LedgerScreen(vm)
                1 -> StatementsScreen(vm)
                else -> SettingsScreen(vm)
            }
        }
    }

    vm.progress?.let { ProgressDialog(it) }
    vm.passwordRequest?.let { PasswordDialog(it, vm::answerPassword) }
    vm.message?.let { msg ->
        AlertDialog(
            onDismissRequest = { vm.message = null },
            confirmButton = { TextButton(onClick = { vm.message = null }) { Text("OK") } },
            text = { Text(msg) },
        )
    }
}

// ---------- Ledger ----------

private val money: NumberFormat = NumberFormat.getNumberInstance(Locale("en", "IN")).apply {
    minimumFractionDigits = 2
    maximumFractionDigits = 2
}

private fun fmt(v: Double?) = v?.let(money::format) ?: "—"

private val colWidths = listOf(104.dp, 230.dp, 104.dp, 104.dp, 124.dp)
private val headers = listOf("Date", "Description of Transaction", "Debit Amount", "Credit Amount", "Day End Balance")

@Composable
private fun LedgerScreen(vm: MainViewModel) {
    val ledger = vm.ledger
    if (vm.accounts.isEmpty() || ledger == null) {
        EmptyState("No statements yet", "Tap \"Upload PDF\" and pick a bank statement from Google Drive or your phone.")
        return
    }
    Column(Modifier.fillMaxSize()) {
        LedgerHeader(vm, ledger)
        val hScroll = rememberScrollState()
        Column(Modifier.fillMaxSize().horizontalScroll(hScroll)) {
            val tableWidth = colWidths.fold(0.dp) { a, b -> a + b }
            Row(Modifier.width(tableWidth).background(MaterialTheme.colorScheme.primaryContainer)) {
                headers.forEachIndexed { i, h ->
                    Cell(h, colWidths[i], bold = true, alignEnd = i >= 2)
                }
            }
            LazyColumn(Modifier.width(tableWidth).weight(1f)) {
                items(ledger.rows) { row -> LedgerRowView(row) }
                item { Spacer(Modifier.height(88.dp)) }
            }
        }
    }
}

@Composable
private fun LedgerHeader(vm: MainViewModel, ledger: Ledger) {
    val context = LocalContext.current
    var menu by remember { mutableStateOf(false) }
    Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Box {
            AssistChip(
                onClick = { menu = true },
                label = { Text(vm.accounts.firstOrNull { it.key == vm.selectedAccount }?.label ?: "Select account", maxLines = 1) },
            )
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                vm.accounts.forEach { a ->
                    DropdownMenuItem(text = { Text(a.label) }, onClick = { menu = false; vm.selectAccount(a.key) })
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = {
                val d = ledger.start
                DatePickerDialog(context, { _, y, m, day -> vm.setStart(LocalDate.of(y, m + 1, day)) }, d.year, d.monthValue - 1, d.dayOfMonth).show()
            }) { Text("From ${ledger.start.format(DateParse.display)}") }
            Text("to ${ledger.end.format(DateParse.display)}", style = MaterialTheme.typography.bodyMedium)
            if (vm.startOverride != null) TextButton(onClick = { vm.setStart(null) }) { Text("Reset") }
        }
        Text(
            "Opening ${fmt(ledger.openingBalance)} · Closing ${fmt(ledger.closingBalance)}\n" +
                "Total debit ${fmt(ledger.totalDebit)} · Total credit ${fmt(ledger.totalCredit)}",
            style = MaterialTheme.typography.bodySmall,
        )
        val missing = ledger.firstMissingDate
        Text(
            "${ledger.daysCovered} of ${ledger.totalDays} days covered" +
                (missing?.let { " · upload the statement starting ${it.format(DateParse.display)} to continue" } ?: " ✓"),
            style = MaterialTheme.typography.bodySmall,
            color = if (missing != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
        )
    }
}

@Composable
private fun LedgerRowView(row: LedgerRow) {
    val bg = when (row.kind) {
        RowKind.TRANSACTION -> Color.Transparent
        RowKind.NO_TRANSACTION -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f)
        RowKind.NOT_COVERED -> MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.35f)
    }
    val balance = when {
        row.kind == RowKind.NOT_COVERED -> "—"
        row.dayEndBalance == null -> "0"
        else -> fmt(row.dayEndBalance)
    }
    Row(Modifier.background(bg)) {
        Cell(row.date.format(DateParse.display), colWidths[0])
        Cell(row.description, colWidths[1], dim = row.kind != RowKind.TRANSACTION)
        Cell(fmt(row.debit), colWidths[2], alignEnd = true, dim = row.debit == 0.0)
        Cell(fmt(row.credit), colWidths[3], alignEnd = true, dim = row.credit == 0.0)
        Cell(balance, colWidths[4], alignEnd = true, bold = row.dayEndBalance != null)
    }
    HorizontalDivider(thickness = 0.5.dp)
}

@Composable
private fun Cell(text: String, width: Dp, bold: Boolean = false, alignEnd: Boolean = false, dim: Boolean = false) {
    Text(
        text,
        modifier = Modifier.width(width).padding(horizontal = 6.dp, vertical = 8.dp),
        fontSize = 12.sp,
        fontWeight = if (bold) FontWeight.SemiBold else FontWeight.Normal,
        textAlign = if (alignEnd) TextAlign.End else TextAlign.Start,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis,
        color = if (dim) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
    )
}

// ---------- Statements ----------

@Composable
private fun StatementsScreen(vm: MainViewModel) {
    if (vm.statements.isEmpty()) {
        EmptyState("Database is empty", "Every uploaded PDF is stored here with its bank, account and statement period.")
        return
    }
    var confirmDelete by remember { mutableStateOf<Long?>(null) }
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp, 12.dp, 12.dp, 96.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(vm.statements, key = { it.id }) { s ->
            Card(Modifier.fillMaxWidth()) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(s.bankName, style = MaterialTheme.typography.titleMedium)
                        Text("Account name: ${s.accountHolder}", style = MaterialTheme.typography.bodyMedium)
                        Text("Account no: ${s.accountNumber.ifBlank { "—" }}", style = MaterialTheme.typography.bodyMedium)
                        Text(
                            "Span: ${s.periodStart?.format(DateParse.display) ?: "?"} → ${s.periodEnd?.format(DateParse.display) ?: "?"}",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Text(
                            "${s.txnCount} transactions · Opening ${fmt(s.openingBalance)} · Closing ${fmt(s.closingBalance)} ${s.currency}",
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text(s.fileName, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    IconButton(onClick = { confirmDelete = s.id }) { Icon(Icons.Default.Delete, contentDescription = "Delete") }
                }
            }
        }
    }
    confirmDelete?.let { id ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Delete statement?") },
            text = { Text("Its transactions will be removed from the ledger.") },
            confirmButton = { TextButton(onClick = { vm.deleteStatement(id); confirmDelete = null }) { Text("Delete") } },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Cancel") } },
        )
    }
}

// ---------- Settings ----------

@Composable
private fun SettingsScreen(vm: MainViewModel) {
    var key by rememberSaveable { mutableStateOf(vm.apiKey) }
    var model by rememberSaveable { mutableStateOf(vm.model) }
    val context = LocalContext.current
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Gemini API key", style = MaterialTheme.typography.titleMedium)
        Text(
            "The app uses Google Gemini to read your PDF statements. Get a free key at aistudio.google.com/apikey " +
                "and paste it below. The key and your statements' data stay on this phone; PDFs are only sent to Google's Gemini API for reading.",
            style = MaterialTheme.typography.bodyMedium,
        )
        OutlinedButton(onClick = {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://aistudio.google.com/apikey")))
        }) { Text("Get a free API key") }
        OutlinedTextField(
            value = key,
            onValueChange = { key = it },
            label = { Text("API key") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = model,
            onValueChange = { model = it },
            label = { Text("Gemini model") },
            supportingText = { Text("Default: gemini-2.5-flash. Use gemini-2.5-pro for hard-to-read statements.") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(onClick = { vm.saveSettings(key, model) }, modifier = Modifier.fillMaxWidth()) { Text("Save") }
        HorizontalDivider()
        Text("Uploading from Google Drive", style = MaterialTheme.typography.titleMedium)
        Text(
            "• Tap \"Upload PDF\", open the menu (☰) and choose Drive, then select one or more statements.\n" +
                "• Or, in the Google Drive app, tap ⋮ on a statement → Send a copy / Open with → Statement Analyzer.\n" +
                "• Password-protected PDFs are unlocked on the phone after you enter the password.\n" +
                "• Re-uploading the same statement replaces it; overlapping statements are de-duplicated.",
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

// ---------- Shared ----------

@Composable
private fun EmptyState(title: String, body: String) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(title, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
        Spacer(Modifier.height(8.dp))
        Text(body, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
    }
}

@Composable
private fun ProgressDialog(text: String) {
    AlertDialog(
        onDismissRequest = {},
        confirmButton = {},
        text = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator()
                Spacer(Modifier.width(16.dp))
                Text(text)
            }
        },
    )
}

@Composable
private fun PasswordDialog(request: PasswordRequest, onAnswer: (String?) -> Unit) {
    var password by remember(request) { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { onAnswer(null) },
        title = { Text("PDF password") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    (if (request.wrongAttempt) "Wrong password. " else "") +
                        "${request.fileName} is password protected. Banks often use a mix of your name, date of birth or customer ID."
                )
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    label = { Text("Password") },
                )
            }
        },
        confirmButton = { TextButton(onClick = { onAnswer(password) }) { Text("Unlock") } },
        dismissButton = { TextButton(onClick = { onAnswer(null) }) { Text("Skip file") } },
    )
}
