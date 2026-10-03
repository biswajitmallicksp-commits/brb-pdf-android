/*
 * Statement parser and 365-day ledger builder.
 *
 * Runs entirely on the device: pdf.js extracts the text with positions, and the
 * rules below find the transaction table, the amounts and the statement details.
 * No network calls, no API keys.
 *
 * Works in the browser (window.StatementParser) and in Node (module.exports) so
 * the same code is unit-tested in tests/.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.StatementParser = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ---------------------------------------------------------------- dates

  const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, sept: 9, oct: 10, nov: 11, dec: 12 };
  const MON = "(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\\.?";
  const DATE_SRC =
    "(?:\\d{4}-\\d{1,2}-\\d{1,2}" +
    "|\\d{1,2}[\\/\\-.]\\d{1,2}[\\/\\-.]\\d{2,4}" +
    "|\\d{1,2}(?:st|nd|rd|th)?[\\s\\-\\/]*" + MON + "[\\s\\-\\/,']*\\d{2,4}" +
    "|" + MON + "\\s+\\d{1,2},?\\s+\\d{4})";
  const DATE_AT_START = new RegExp("^(?:\\d{1,4}\\s+)??(" + DATE_SRC + ")(?![\\d])", "i");
  const DATE_ANY = new RegExp(DATE_SRC, "gi");

  const pad = (n) => String(n).padStart(2, "0");
  function iso(y, m, d) {
    if (y < 100) y += 2000;
    if (m < 1 || m > 12 || d < 1 || d > 31) return null;
    const dt = new Date(Date.UTC(y, m - 1, d));
    if (dt.getUTCMonth() !== m - 1) return null;
    return `${y}-${pad(m)}-${pad(d)}`;
  }

  /** Parses the date formats used on Indian/UK/US statements into YYYY-MM-DD (day-first by default). */
  function parseDate(text) {
    if (!text) return null;
    const s = String(text).trim().toLowerCase().replace(/(\d)(st|nd|rd|th)\b/, "$1");
    let m;
    if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) return iso(+m[1], +m[2], +m[3]);
    if ((m = s.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})$/))) {
      let a = +m[1], b = +m[2];
      if (b > 12 && a <= 12) [a, b] = [b, a]; // month-first statement
      return iso(+m[3], b, a);
    }
    if ((m = s.match(/^(\d{1,2})[\s\-\/]*([a-z]{3,9})\.?[\s\-\/,']*(\d{2,4})$/))) {
      const mon = MONTHS[m[2].slice(0, 4)] || MONTHS[m[2].slice(0, 3)];
      return mon ? iso(+m[3], mon, +m[1]) : null;
    }
    if ((m = s.match(/^([a-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$/))) {
      const mon = MONTHS[m[1].slice(0, 4)] || MONTHS[m[1].slice(0, 3)];
      return mon ? iso(+m[3], mon, +m[2]) : null;
    }
    return null;
  }

  const DAY_MS = 86400000;
  const toDay = (isoDate) => Date.parse(isoDate + "T00:00:00Z") / DAY_MS;
  const fromDay = (n) => new Date(n * DAY_MS).toISOString().slice(0, 10);
  const addDays = (isoDate, n) => fromDay(toDay(isoDate) + n);

  // ---------------------------------------------------------------- amounts

  const AMOUNT_RE = /^\(?-?(?:rs\.?|inr|₹|\$)?\s*(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+\.\d{2})\)?(cr|dr|c|d)?\.?$/i;
  const MARK_RE = /^\(?(cr|dr)\.?\)?$/i;

  function parseAmount(token) {
    const m = String(token).trim().match(AMOUNT_RE);
    if (!m) return null;
    let v = parseFloat(m[1].replace(/,/g, ""));
    if (/^\(|^-/.test(token.trim())) v = -v;
    const mark = m[2] ? (m[2][0].toLowerCase() === "d" ? "dr" : "cr") : null;
    return { value: v, mark };
  }

  const round2 = (v) => (v == null ? null : Math.round(v * 100) / 100);
  const near = (a, b) => Math.abs(a - b) < 0.015;

  // ---------------------------------------------------------------- pdf text -> lines

  /**
   * Reads every page with pdf.js and groups text into visual lines.
   * Each line: { page, y, text, tokens: [{ s, x, x2 }] } with tokens left to right.
   */
  async function extractLines(pdf) {
    const lines = [];
    for (let p = 1; p <= pdf.numPages; p++) {
      const page = await pdf.getPage(p);
      const content = await page.getTextContent();
      const tokens = [];
      for (const it of content.items) {
        if (!it.str || !it.str.trim()) continue;
        const x = it.transform[4], y = it.transform[5];
        const h = Math.abs(it.transform[3]) || Math.abs(it.height) || 8;
        const w = it.width || it.str.length * h * 0.5;
        const cw = w / Math.max(1, it.str.length);
        const re = /\S+/g;
        let m;
        while ((m = re.exec(it.str))) {
          tokens.push({ s: m[0], x: x + m.index * cw, x2: x + (m.index + m[0].length) * cw, y, h });
        }
      }
      tokens.sort((a, b) => b.y - a.y || a.x - b.x);
      const pageLines = [];
      for (const t of tokens) {
        const tol = Math.max(2, t.h * 0.45);
        const line = pageLines.find((l) => Math.abs(l.y - t.y) <= tol);
        if (line) line.tokens.push(t);
        else pageLines.push({ page: p, y: t.y, tokens: [t] });
      }
      pageLines.sort((a, b) => b.y - a.y);
      for (const l of pageLines) {
        l.tokens.sort((a, b) => a.x - b.x);
        l.text = l.tokens.map((t) => t.s).join(" ");
        lines.push(l);
      }
    }
    return lines;
  }

  // ---------------------------------------------------------------- statement details

  const BANKS = [
    "State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank", "Punjab National Bank",
    "Bank of Baroda", "Canara Bank", "Union Bank of India", "Bank of India", "Indian Bank", "Central Bank of India",
    "Indian Overseas Bank", "UCO Bank", "Bank of Maharashtra", "Punjab & Sind Bank", "IDBI Bank", "IDFC First Bank",
    "Yes Bank", "IndusInd Bank", "Federal Bank", "South Indian Bank", "Karur Vysya Bank", "City Union Bank",
    "Karnataka Bank", "RBL Bank", "Bandhan Bank", "AU Small Finance Bank", "Equitas Small Finance Bank",
    "Ujjivan Small Finance Bank", "DBS Bank", "Standard Chartered", "HSBC", "Citibank", "Paytm Payments Bank",
    "Airtel Payments Bank", "India Post Payments Bank", "Jammu & Kashmir Bank", "Tamilnad Mercantile Bank",
    "DCB Bank", "Dhanlaxmi Bank", "CSB Bank", "Saraswat Bank", "Cosmos Bank",
  ];
  const BANK_ALIASES = [
    [/\bsbi\b|state bank of india/i, "State Bank of India"],
    [/\bhdfc\b/i, "HDFC Bank"],
    [/\bicici\b/i, "ICICI Bank"],
    [/\baxis\b/i, "Axis Bank"],
    [/\bkotak\b/i, "Kotak Mahindra Bank"],
    [/\bpnb\b/i, "Punjab National Bank"],
    [/\bidfc\b/i, "IDFC First Bank"],
  ];
  const LABEL_STOP =
    /\s+(?:branch|address|account|a\/c|ifsc|micr|customer|cust|cif|date|period|statement|phone|mobile|email|e-mail|nominee|type|currency|joint|from|ckyc|product|scheme)\b.*$/i;

  function detectBank(text) {
    const head = text.slice(0, 3000);
    let best = null;
    for (const name of BANKS) {
      const i = head.toLowerCase().indexOf(name.toLowerCase());
      if (i >= 0 && (!best || i < best.i)) best = { i, name };
    }
    if (best) return best.name;
    for (const [re, name] of BANK_ALIASES) if (re.test(head)) return name;
    const line = head.split("\n").find((l) => /\bbank\b/i.test(l) && l.length < 60);
    return line ? line.trim() : "";
  }

  function cleanName(s) {
    return s
      .replace(LABEL_STOP, "")
      .replace(/^(mr|mrs|ms|miss|m\/s|shri|smt|dr)\.?\s+/i, "")
      .replace(/[^A-Za-z .'&]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function detectHolder(lines) {
    const labelled = /(?:account\s*(?:holder'?s?)?\s*name|customer\s*name|name\s*of\s*(?:the\s*)?(?:customer|account\s*holder)|a\/c\s*name|^name)\s*[:\-]?\s*(.+)$/i;
    for (const l of lines.slice(0, 60)) {
      const m = l.text.match(labelled);
      if (m) {
        const n = cleanName(m[1]);
        if (n.length >= 3) return n;
      }
    }
    for (const l of lines.slice(0, 40)) {
      const m = l.text.match(/(?:^|\s)((?:mr|mrs|ms|miss|m\/s|shri|smt)\.?\s+[A-Za-z][A-Za-z .']{2,60})/i);
      if (m) {
        const n = cleanName(m[1]);
        if (n.length >= 3) return n;
      }
    }
    return "";
  }

  function detectAccountNumber(text) {
    const m = text.match(/(?:account|a\/c|acct)\.?\s*(?:no|number|num)?\.?\s*[:\-]?\s*([0-9Xx*][0-9Xx* \-]{3,24}\d)/i);
    return m ? m[1].replace(/[\s\-]/g, "") : "";
  }

  function detectPeriod(text) {
    const re = new RegExp(
      "(?:from|period|between|for)\\b[^\\n\\d]{0,30}?(" + DATE_SRC + ")\\s*(?:to|-|–|till|until|and)\\s*(?:[a-z ]{0,6}:\\s*)?(" + DATE_SRC + ")",
      "i"
    );
    const m = text.match(re);
    if (!m) return [null, null];
    return [parseDate(m[1]), parseDate(m[2])];
  }

  // ---------------------------------------------------------------- table

  const HEAD = {
    date: /^(txn|tran|transaction|value|post|posting)?\.?\s*date$|^date$|^dt\.?$/i,
    desc: /^(narration|description|particulars|details|remarks|transaction|transactions)$/i,
    debit: /^(withdrawals?|debits?|dr\.?|paid|out|withdrawal\(dr\))$/i,
    credit: /^(deposits?|credits?|cr\.?|received|in|deposit\(cr\))$/i,
    amount: /^amount$|^amt\.?$/i,
    drcr: /^dr\/cr$|^cr\/dr$|^type$/i,
    balance: /^balance$|^bal\.?$/i,
  };

  /** Recognises the transaction table's header row and returns column positions, or null. */
  function readHeader(line, nextLine) {
    const t = line.text.toLowerCase();
    if (!/\bdate\b|\bdt\b/.test(t) || !/balance|\bbal\b/.test(t)) return null;
    if (!/withdraw|debit|deposit|credit|amount|\bdr\b|\bcr\b/.test(t)) return null;
    if (DATE_AT_START.test(line.text)) return null;
    const tokens = line.tokens.slice();
    if (nextLine && Math.abs(nextLine.y - line.y) < 14 && nextLine.page === line.page && !DATE_AT_START.test(nextLine.text) &&
        !nextLine.tokens.some((k) => parseAmount(k.s))) {
      tokens.push(...nextLine.tokens);
    }
    const cols = {};
    for (const tok of tokens) {
      const w = tok.s.replace(/[.:]+$/, "").toLowerCase();
      for (const key of Object.keys(HEAD)) {
        if (HEAD[key].test(w) || HEAD[key].test(tok.s.toLowerCase())) {
          if (key === "date" && cols.date) continue; // keep the first date column (transaction date)
          if (key === "debit" && w === "dr" && cols.drcr) continue;
          cols[key] = cols[key] || { x: tok.x, x2: tok.x2, c: (tok.x + tok.x2) / 2 };
        }
      }
    }
    if (!cols.balance) return null;
    if (!cols.debit && !cols.credit && !cols.amount) return null;
    return { cols, usedNext: tokens.length > line.tokens.length };
  }

  const SKIP_LINE = /page\s*(no\.?)?\s*:?\s*\d+|computer generated|does not require|statement summary|^total\b|^grand total|carried forward|\bc\/f\b|end of statement|this is a system/i;
  const OPENING = /opening\s*balance|balance\s*(b\/f|brought\s*forward|as\s*on|forward)|^b\/f\b|brought\s*forward/i;
  const CLOSING = /closing\s*balance|balance\s*c\/f/i;

  /**
   * Turns the extracted lines into statement details and transactions.
   * Returns { meta, txns, warnings, mismatches }.
   */
  function parseStatement(lines) {
    const fullText = lines.map((l) => l.text).join("\n");
    const meta = {
      bankName: detectBank(fullText),
      accountHolder: detectHolder(lines),
      accountNumber: detectAccountNumber(fullText),
      periodStart: null,
      periodEnd: null,
      openingBalance: null,
      closingBalance: null,
      currency: /\bUSD\b|US\$/.test(fullText) ? "USD" : "INR",
    };
    [meta.periodStart, meta.periodEnd] = detectPeriod(fullText);

    let header = null;
    let seenHeader = false;
    const txns = [];
    let cur = null;
    let skipNext = false;

    for (let i = 0; i < lines.length; i++) {
      if (skipNext) { skipNext = false; continue; }
      const line = lines[i];
      const h = readHeader(line, lines[i + 1]);
      if (h) {
        header = h.cols;
        seenHeader = true;
        skipNext = h.usedNext;
        cur = null;
        continue;
      }
      const text = line.text;

      if (OPENING.test(text) && meta.openingBalance == null) {
        const amts = line.tokens.map((t) => parseAmount(t.s)).filter(Boolean);
        if (amts.length) {
          const a = amts[amts.length - 1];
          meta.openingBalance = a.mark === "dr" ? -a.value : a.value;
        }
        if (!seenHeader || !DATE_AT_START.test(text) || amts.length) { cur = null; continue; }
      }
      if (CLOSING.test(text)) {
        const amts = line.tokens.map((t) => parseAmount(t.s)).filter(Boolean);
        if (amts.length) {
          const a = amts[amts.length - 1];
          meta.closingBalance = a.mark === "dr" ? -a.value : a.value;
        }
        cur = null;
        continue;
      }
      if (SKIP_LINE.test(text)) { cur = null; continue; }

      const dm = text.match(DATE_AT_START);
      const date = dm ? parseDate(dm[1]) : null;
      const split = splitAmounts(line);

      if (date && (seenHeader || split.amounts.length)) {
        cur = { date, desc: [], amounts: split.amounts, page: line.page };
        let rest = split.descTokens.map((t) => t.s).join(" ");
        rest = rest.slice(rest.indexOf(dm[1]) + dm[1].length).trim();
        const second = rest.match(new RegExp("^(" + DATE_SRC + ")(?![\\d])", "i"));
        if (second) rest = rest.slice(second[0].length).trim();
        rest = rest.replace(new RegExp("\\s(" + DATE_SRC + ")$", "i"), "").trim(); // trailing value date
        if (rest) cur.desc.push(rest);
        txns.push(cur);
        continue;
      }
      if (!cur) continue;
      if (split.amounts.length) {
        if (!cur.amounts.length) {
          cur.amounts = split.amounts;
          const extra = split.descTokens.map((t) => t.s).join(" ").trim();
          if (extra) cur.desc.push(extra);
        } else {
          cur = null;
        }
        continue;
      }
      // Wrapped narration line: only text in the description area, close below the transaction.
      const left = line.tokens[0].x;
      const inDescArea = !header || !header.debit || left < Math.min(...["debit", "credit", "amount"].filter((k) => header[k]).map((k) => header[k].x)) - 10;
      if (inDescArea && cur.desc.join(" ").length < 300 && line.page === cur.page) {
        cur.desc.push(text.replace(new RegExp("\\s?(" + DATE_SRC + ")$", "i"), "").trim());
      }
    }

    const result = assign(txns, header, meta.openingBalance);
    if (!meta.periodStart && result.txns.length) meta.periodStart = result.txns[0].date;
    if (!meta.periodEnd && result.txns.length) meta.periodEnd = result.txns[result.txns.length - 1].date;
    if (meta.closingBalance == null && result.txns.length) meta.closingBalance = result.txns[result.txns.length - 1].balance;
    return { meta, txns: result.txns, warnings: result.warnings, mismatches: result.mismatches };

    function splitAmounts(line) {
      // Amounts sit at the right end of the line; walk back over amounts, Dr/Cr marks and "-" placeholders.
      const toks = line.tokens;
      let j = toks.length;
      const amounts = [];
      while (j > 0) {
        const t = toks[j - 1];
        const a = parseAmount(t.s);
        if (a) {
          amounts.unshift({ ...a, x: t.x, x2: t.x2 });
          j--;
        } else if (MARK_RE.test(t.s) && j > 1 && parseAmount(toks[j - 2].s)) {
          const prev = parseAmount(toks[j - 2].s);
          amounts.unshift({ ...prev, mark: t.s.toLowerCase().includes("d") ? "dr" : "cr", x: toks[j - 2].x, x2: t.x2 });
          j -= 2;
        } else if (/^[-–—]$|^0?\.00$|^nil$/i.test(t.s)) {
          j--;
        } else break;
      }
      return { amounts, descTokens: toks.slice(0, j) };
    }
  }

  /** Decides debit / credit / balance for each raw transaction and checks running balances. */
  function assign(raw, header, opening) {
    const warnings = [];
    const txns = [];
    let prev = opening;
    let mismatches = 0;
    for (const r of raw) {
      if (!r.amounts.length) continue;
      const amts = r.amounts.slice();
      let balance = null;
      let balTok = null;
      if (amts.length >= 2 || (header && header.balance && amts.length === 1 && closest(amts[0], header) === "balance")) {
        balTok = amts.pop();
        balance = balTok.mark === "dr" ? -balTok.value : balTok.value;
      }
      let debit = 0, credit = 0;
      for (const a of amts) {
        let side = a.mark === "dr" ? "debit" : a.mark === "cr" ? "credit" : null;
        if (!side && header) {
          const c = closest(a, header);
          if (c === "debit" || c === "credit") side = c;
        }
        if (!side && prev != null && balance != null) {
          side = near(prev - a.value, balance) ? "debit" : near(prev + a.value, balance) ? "credit" : null;
        }
        if (!side) side = "debit";
        if (side === "debit") debit += Math.abs(a.value);
        else credit += Math.abs(a.value);
      }
      // Use the printed running balance to correct a misread side.
      if (prev != null && balance != null && !near(prev - debit + credit, balance)) {
        if (near(prev + debit - credit, balance)) [debit, credit] = [credit, debit];
        else mismatches++;
      }
      const desc = r.desc.join(" ").replace(/\s+/g, " ").trim();
      txns.push({ date: r.date, description: desc, debit: round2(debit), credit: round2(credit), balance: round2(balance) });
      prev = balance != null ? balance : prev != null ? round2(prev - debit + credit) : null;
    }
    if (!txns.length) warnings.push("No transactions were found. The PDF may be a scanned image rather than text.");
    if (mismatches) warnings.push(`${mismatches} transaction(s) don't match the running balance. Please check them.`);
    return { txns, warnings, mismatches };
  }

  function closest(a, header) {
    let best = null, bestD = Infinity;
    for (const key of ["debit", "credit", "amount", "balance"]) {
      const c = header[key];
      if (!c) continue;
      const d = Math.min(Math.abs(c.x2 - a.x2), Math.abs(c.c - (a.x + a.x2) / 2));
      if (d < bestD) { bestD = d; best = key; }
    }
    return best;
  }

  // ---------------------------------------------------------------- ledger

  function accountKey(s) {
    const digits = (s.accountNumber || "").replace(/\D/g, "");
    const tail = digits.length >= 4 ? digits.slice(-4) : (s.accountNumber || "").trim().toLowerCase();
    return `${(s.bankName || "").trim().toLowerCase()}|${tail}`;
  }

  function defaultStart(statements) {
    const starts = statements.map((s) => s.periodStart || (s.txns[0] && s.txns[0].date)).filter(Boolean).sort();
    return starts[0] || null;
  }

  /**
   * Builds the day-by-day ledger for one account.
   * - every day appears at least once; days with several transactions get one row each,
   *   and only the last row of the day carries the day-end balance (others show 0);
   * - covered days without transactions get one row with 0 / 0 and the carried balance;
   * - days outside every uploaded statement are marked "notCovered";
   * - transactions repeated in overlapping statements are counted once.
   */
  function buildLedger(statements, start, days = 365) {
    const end = addDays(start, days - 1);
    const ordered = statements.slice().sort((a, b) =>
      (a.periodStart || "9999").localeCompare(b.periodStart || "9999") || (a.importedAt || 0) - (b.importedAt || 0));
    const merged = [];
    const seen = new Set();
    const ranges = [];
    ordered.forEach((s, si) => {
      const own = s.txns || [];
      const from = s.periodStart || (own[0] && own.map((t) => t.date).sort()[0]);
      const to = s.periodEnd || (own.length && own.map((t) => t.date).sort().pop());
      if (from && to && from <= to) ranges.push([from, to]);
      const keys = own.map((t) => [t.date, t.description.toLowerCase().replace(/[^a-z0-9]/g, ""), round2(t.debit), round2(t.credit), round2(t.balance)].join("|"));
      own.forEach((t, i) => { if (!seen.has(keys[i])) merged.push({ ...t, _o: si * 1e6 + i }); });
      keys.forEach((k) => seen.add(k));
    });
    merged.sort((a, b) => a.date.localeCompare(b.date) || a._o - b._o);

    let balance = ordered.length && ordered[0].openingBalance != null ? ordered[0].openingBalance : null;
    const apply = (t) => {
      if (balance == null) balance = t.balance != null ? t.balance - t.credit + t.debit : 0;
      balance = t.balance != null ? t.balance : round2(balance + t.credit - t.debit);
    };
    let i = 0;
    while (i < merged.length && merged[i].date < start) apply(merged[i++]);
    if (balance == null && i < merged.length && merged[i].balance != null) {
      const t = merged[i];
      balance = round2(t.balance - t.credit + t.debit);
    }
    const opening = balance;

    const rows = [];
    let covered = 0, totalDebit = 0, totalCredit = 0, lastBalance = null, firstMissing = null;
    for (let d = start; d <= end; d = addDays(d, 1)) {
      const dayTx = [];
      while (i < merged.length && merged[i].date === d) dayTx.push(merged[i++]);
      const inStatement = dayTx.length > 0 || ranges.some(([a, b]) => d >= a && d <= b);
      if (dayTx.length) {
        dayTx.forEach((t, k) => {
          apply(t);
          totalDebit += t.debit;
          totalCredit += t.credit;
          rows.push({ date: d, description: t.description, debit: t.debit, credit: t.credit,
            dayEndBalance: k === dayTx.length - 1 ? round2(balance) : null, kind: "txn" });
        });
      } else if (inStatement) {
        rows.push({ date: d, description: "No transaction", debit: 0, credit: 0, dayEndBalance: round2(balance), kind: "none" });
      } else {
        if (!firstMissing) firstMissing = d;
        rows.push({ date: d, description: "Statement not uploaded", debit: 0, credit: 0, dayEndBalance: null, kind: "missing" });
      }
      if (inStatement) { covered++; lastBalance = balance; }
    }
    return {
      rows, start, end, days, daysCovered: covered,
      totalDebit: round2(totalDebit), totalCredit: round2(totalCredit),
      openingBalance: round2(opening), closingBalance: round2(lastBalance), firstMissing,
    };
  }

  // ---------------------------------------------------------------- export

  const MON_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDate(isoDate) {
    if (!isoDate) return "";
    const [y, m, d] = isoDate.split("-");
    return `${d}-${MON_NAMES[+m - 1]}-${y}`;
  }

  function ledgerToCsv(ledger) {
    const q = (s) => '"' + String(s).replace(/"/g, '""') + '"';
    const out = ["Date,Description of Transaction,Debit Amount,Credit Amount,Day End Balance"];
    for (const r of ledger.rows) {
      const bal = r.kind === "missing" ? "" : r.dayEndBalance == null ? "0" : r.dayEndBalance.toFixed(2);
      out.push([fmtDate(r.date), q(r.description), r.debit.toFixed(2), r.credit.toFixed(2), bal].join(","));
    }
    return out.join("\r\n") + "\r\n";
  }

  return { parseDate, parseAmount, extractLines, parseStatement, buildLedger, defaultStart, accountKey, addDays, fmtDate, ledgerToCsv };
});
