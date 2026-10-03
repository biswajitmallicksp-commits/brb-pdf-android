const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const pdfjs = require("pdfjs-dist/legacy/build/pdf.js");
const P = require("../web/statement-parser.js");

async function parseFile(name, password) {
  const data = new Uint8Array(fs.readFileSync(path.join(__dirname, "fixtures", name + ".pdf")));
  const pdf = await pdfjs.getDocument({ data, password, isEvalSupported: false, verbosity: 0 }).promise;
  return P.parseStatement(await P.extractLines(pdf));
}

for (const [name, password] of [["sbi_style"], ["sbi_style_locked", "mallick123"], ["hdfc_style"], ["icici_style"]]) {
  test(`parses ${name}`, async () => {
    const expected = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", name + ".json"), "utf8"));
    const got = await parseFile(name, password);
    const m = expected.meta;
    assert.equal(got.meta.bankName, m.bankName);
    assert.equal(got.meta.accountHolder, m.accountHolder);
    assert.equal(got.meta.accountNumber, m.accountNumber);
    assert.equal(got.meta.periodStart, m.periodStart);
    assert.equal(got.meta.periodEnd, m.periodEnd);
    if (m.openingBalance != null) assert.equal(got.meta.openingBalance, m.openingBalance);
    assert.equal(got.mismatches, 0, got.warnings.join("; "));
    assert.equal(got.txns.length, expected.txns.length);
    got.txns.forEach((t, i) => {
      const e = expected.txns[i];
      assert.deepEqual([t.date, t.debit, t.credit, t.balance], [e.date, e.debit, e.credit, e.balance], `row ${i}`);
      // Reference numbers stay in the description; compare the narration text without them.
      const norm = (s) => s.replace(/\b\d{10}\b/g, " ").replace(/\s+/g, " ").trim();
      assert.equal(norm(t.description), norm(e.description), `row ${i} description`);
    });
  });
}

test("wrong password is rejected", async () => {
  await assert.rejects(parseFile("sbi_style_locked", "nope"), /password/i);
});

test("dates", () => {
  assert.equal(P.parseDate("01/06/2025"), "2025-06-01");
  assert.equal(P.parseDate("01-Jun-2025"), "2025-06-01");
  assert.equal(P.parseDate("1 JUN 25"), "2025-06-01");
  assert.equal(P.parseDate("06/25/2025"), "2025-06-25");
  assert.equal(P.parseDate("June 1, 2025"), "2025-06-01");
  assert.equal(P.parseDate("31/02/2025"), null);
});

test("ledger: 365 days, day-end balance on last row, carry forward, gaps, overlap", () => {
  const june = { id: 1, bankName: "SBI", accountNumber: "XXXX1234", periodStart: "2025-06-01", periodEnd: "2025-06-30", openingBalance: 1000, importedAt: 1,
    txns: [
      { date: "2025-06-01", description: "UPI A", debit: 100, credit: 0, balance: 900 },
      { date: "2025-06-01", description: "Salary", debit: 0, credit: 500, balance: 1400 },
      { date: "2025-06-30", description: "ATM", debit: 400, credit: 0, balance: 1000 },
    ] };
  const july = { id: 2, bankName: "SBI", accountNumber: "0001234", periodStart: "2025-06-30", periodEnd: "2025-07-31", openingBalance: null, importedAt: 2,
    txns: [
      { date: "2025-06-30", description: "ATM", debit: 400, credit: 0, balance: 1000 },
      { date: "2025-07-05", description: "Shop", debit: 50, credit: 0, balance: null },
    ] };
  assert.equal(P.accountKey(june), P.accountKey(july));
  const start = P.defaultStart([july, june]);
  assert.equal(start, "2025-06-01");
  const l = P.buildLedger([july, june], start);
  assert.equal(l.end, "2026-05-31");
  assert.equal(new Set(l.rows.map((r) => r.date)).size, 365);
  assert.equal(l.rows.length, 366);
  assert.equal(l.rows[0].dayEndBalance, null);
  assert.equal(l.rows[1].dayEndBalance, 1400);
  assert.deepEqual([l.rows[2].kind, l.rows[2].debit, l.rows[2].credit, l.rows[2].dayEndBalance], ["none", 0, 0, 1400]);
  assert.equal(l.rows.filter((r) => r.description === "ATM").length, 1);
  assert.equal(l.rows.find((r) => r.description === "Shop").dayEndBalance, 950);
  assert.equal(l.rows.find((r) => r.date === "2025-07-31").dayEndBalance, 950);
  assert.equal(l.rows.find((r) => r.date === "2025-08-01").kind, "missing");
  assert.equal(l.firstMissing, "2025-08-01");
  assert.equal(l.daysCovered, 61);
  assert.deepEqual([l.openingBalance, l.closingBalance, l.totalDebit, l.totalCredit], [1000, 950, 550, 500]);
  const csv = P.ledgerToCsv(l).split("\r\n");
  assert.equal(csv[0], "Date,Description of Transaction,Debit Amount,Credit Amount,Day End Balance");
  assert.equal(csv[1], '01-Jun-2025,"UPI A",100.00,0.00,0');
  assert.equal(csv[2], '01-Jun-2025,"Salary",0.00,500.00,1400.00');
  assert.equal(csv[3], '02-Jun-2025,"No transaction",0.00,0.00,1400.00');
});
