"""Generates synthetic bank statements in three common Indian layouts for parser tests.

Run: pip install reportlab && python3 tests/make_fixtures.py
Writes tests/fixtures/*.pdf plus the expected transactions as *.json.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "fixtures"
OUT.mkdir(exist_ok=True)
NARRATIONS = [
    ["UPI/DR/512345678901/SWIGGY", "/YESB/swiggy@yesbank/Payment"],
    ["NEFT CR-HDFC0000123-ACME TECHNOLOGIES PVT", "LTD-SALARY JUN"],
    ["ATM WDL ATM CASH 4521 PARK STREET KOLKATA"],
    ["UPI/CR/523456789012/RAHUL DAS/SBIN/rent share"],
    ["ACH D- TP ACH LIC OF INDIA-1234567"],
    ["POS 4321XXXXXXXX9876 BIG BAZAAR SALT LAKE"],
    ["IMPS-523498761234-MOTHER-SBIN-XXXXXXX4321", "-family support"],
    ["ELECTRICITY BILL CESC 1100223344"],
    ["INTEREST CREDITED"],
]


def money(v):
    s = f"{abs(v):,.2f}"
    whole, frac = s.split(".")
    digits = whole.replace(",", "")
    if len(digits) > 3:  # Indian grouping 12,34,567.00
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{whole}.{frac}"


def make_txns(start, days, opening, seed):
    rnd = random.Random(seed)
    bal = opening
    txns = []
    d = start
    for _ in range(days):
        for _ in range(rnd.choice([0, 0, 1, 1, 2, 3])):
            n = rnd.choice(NARRATIONS)
            credit = "CR" in n[0] or "INTEREST" in n[0] or "SALARY" in "".join(n)
            amt = round(rnd.uniform(50, 25000 if credit else 6000), 2)
            if not credit and amt > bal:
                credit = True
            bal = round(bal + amt if credit else bal - amt, 2)
            txns.append(dict(date=d.isoformat(), lines=n, debit=0.0 if credit else amt,
                             credit=amt if credit else 0.0, balance=bal,
                             ref=str(rnd.randint(10**9, 10**10 - 1))))
        d += timedelta(days=1)
    return txns, bal


def write_expected(name, meta, txns):
    exp = dict(meta=meta, txns=[dict(date=t["date"], description=" ".join(t["lines"]),
                                     debit=t["debit"], credit=t["credit"], balance=t["balance"]) for t in txns])
    (OUT / f"{name}.json").write_text(json.dumps(exp, indent=1))


def sbi(name, encrypt=None):
    start, opening = date(2025, 6, 1), 10000.0
    txns, closing = make_txns(start, 30, opening, 1)
    c = canvas.Canvas(str(OUT / f"{name}.pdf"), pagesize=A4, encrypt=encrypt)
    W, H = A4

    def header(y):
        c.setFont("Helvetica-Bold", 8)
        for x, t in [(30, "Txn Date"), (85, "Value Date"), (140, "Description"), (330, "Ref No./Cheque No."),
                     (440, "Debit"), (495, "Credit"), (550, "Balance")]:
            if t in ("Debit", "Credit", "Balance"):
                c.drawRightString(x + 30, y, t)
            else:
                c.drawString(x, y, t)
        c.setFont("Helvetica", 8)
        return y - 16

    c.setFont("Helvetica-Bold", 14)
    c.drawString(30, H - 40, "State Bank of India")
    c.setFont("Helvetica", 9)
    c.drawString(30, H - 60, "Account Name : Mr. BISWAJIT MALLICK")
    c.drawString(30, H - 72, "Address : 12 Lake Road, Kolkata 700029")
    c.drawString(30, H - 84, "Account Number : 00000039876543210")
    c.drawString(30, H - 96, "Branch : PARK STREET   IFSC : SBIN0001234")
    c.drawString(30, H - 108, "Account Statement from 1 Jun 2025 to 30 Jun 2025")
    c.drawString(30, H - 124, f"Balance as on 1 Jun 2025 : {money(opening)}")
    y = header(H - 150)
    for t in txns:
        need = 12 * len(t["lines"]) + 4
        if y - need < 60:
            c.drawString(30, 30, f"Page {c.getPageNumber()}  This is a computer generated statement.")
            c.showPage()
            y = header(H - 50)
        d = date.fromisoformat(t["date"])
        ds = f"{d.day} {d.strftime('%b %Y')}"
        c.drawString(30, y, ds)
        c.drawString(85, y, ds)
        for i, line in enumerate(t["lines"]):
            c.drawString(140, y - 12 * i, line[:38] if i == 0 else line)
        if len(t["lines"][0]) > 38:
            pass
        c.drawString(330, y, t["ref"])
        if t["debit"]:
            c.drawRightString(470, y, money(t["debit"]))
        if t["credit"]:
            c.drawRightString(525, y, money(t["credit"]))
        c.drawRightString(580, y, money(t["balance"]))
        y -= need
    c.drawString(30, y - 10, f"Closing Balance : {money(closing)}")
    c.drawString(30, 30, f"Page {c.getPageNumber()}  This is a computer generated statement.")
    c.save()
    # Narration lines are truncated at 38 chars on the first line in this layout.
    for t in txns:
        t["lines"] = [t["lines"][0][:38]] + t["lines"][1:]
    write_expected(name, dict(bankName="State Bank of India", accountHolder="BISWAJIT MALLICK",
                              accountNumber="00000039876543210", periodStart="2025-06-01", periodEnd="2025-06-30",
                              openingBalance=opening, closingBalance=closing), txns)


def hdfc():
    start, opening = date(2025, 7, 1), 52340.55
    txns, closing = make_txns(start, 31, opening, 2)
    c = canvas.Canvas(str(OUT / "hdfc_style.pdf"), pagesize=A4)
    W, H = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(30, H - 40, "HDFC BANK LIMITED")
    c.setFont("Helvetica", 8.5)
    c.drawString(30, H - 58, "MR SOUMYA BANERJEE")
    c.drawString(30, H - 70, "FLAT 3B, SUNRISE APARTMENTS, HOWRAH")
    c.drawString(330, H - 58, "Account No : 50100123456789")
    c.drawString(330, H - 70, "Cust ID : 87654321")
    c.drawString(330, H - 82, "Statement From : 01/07/2025 To : 31/07/2025")

    def header(y):
        c.setFont("Helvetica-Bold", 7.5)
        for x, t in [(30, "Date"), (75, "Narration"), (285, "Chq./Ref.No."), (360, "Value Dt")]:
            c.drawString(x, y, t)
        c.drawRightString(465, y, "Withdrawal Amt.")
        c.drawRightString(520, y, "Deposit Amt.")
        c.drawRightString(580, y, "Closing Balance")
        c.setFont("Helvetica", 7.5)
        return y - 14

    y = header(H - 110)
    for t in txns:
        need = 10 * len(t["lines"]) + 3
        if y - need < 50:
            c.drawString(30, 30, "Page No.: %d" % c.getPageNumber())
            c.showPage()
            y = header(H - 50)
        d = date.fromisoformat(t["date"]).strftime("%d/%m/%y")
        c.drawString(30, y, d)
        for i, line in enumerate(t["lines"]):
            c.drawString(75, y - 10 * i, line)
        c.drawString(285, y, t["ref"][:10])
        c.drawString(360, y, d)
        if t["debit"]:
            c.drawRightString(465, y, money(t["debit"]))
        if t["credit"]:
            c.drawRightString(520, y, money(t["credit"]))
        c.drawRightString(580, y, money(t["balance"]))
        y -= need
    y -= 14
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(30, y, "STATEMENT SUMMARY :-")
    c.drawString(30, y - 12, "Opening Balance   Dr Count   Cr Count   Debits   Credits   Closing Bal")
    c.setFont("Helvetica", 7.5)
    deb = sum(t["debit"] for t in txns)
    cre = sum(t["credit"] for t in txns)
    c.drawString(30, y - 24, f"{money(opening)}   {sum(1 for t in txns if t['debit'])}   "
                             f"{sum(1 for t in txns if t['credit'])}   {money(deb)}   {money(cre)}   {money(closing)}")
    c.save()
    write_expected("hdfc_style", dict(bankName="HDFC Bank", accountHolder="SOUMYA BANERJEE",
                                      accountNumber="50100123456789", periodStart="2025-07-01",
                                      periodEnd="2025-07-31", openingBalance=None, closingBalance=None), txns)


def icici():
    start, opening = date(2025, 8, 1), 8000.0
    txns, closing = make_txns(start, 31, opening, 3)
    c = canvas.Canvas(str(OUT / "icici_style.pdf"), pagesize=A4)
    W, H = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(30, H - 40, "ICICI Bank")
    c.setFont("Helvetica", 9)
    c.drawString(30, H - 60, "Customer Name: Ms. ANKITA SEN")
    c.drawString(30, H - 72, "A/C No: XXXXXXXX4321")
    c.drawString(30, H - 84, "Period: 01-08-2025 - 31-08-2025")
    c.setFont("Helvetica-Bold", 8)
    y = H - 110
    c.drawString(30, y, "S No.")
    c.drawString(60, y, "Transaction Date")
    c.drawString(140, y, "Particulars")
    c.drawRightString(450, y, "Amount")
    c.drawString(465, y, "Dr/Cr")
    c.drawRightString(580, y, "Balance")
    c.setFont("Helvetica", 8)
    y -= 16
    c.drawString(140, y, "OPENING BALANCE")
    c.drawRightString(580, y, money(opening) + " Cr")
    y -= 14
    for n, t in enumerate(txns, 1):
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 8)
            y = H - 50
        d = date.fromisoformat(t["date"]).strftime("%d-%b-%Y")
        c.drawString(30, y, str(n))
        c.drawString(60, y, d)
        c.drawString(140, y, " ".join(t["lines"])[:60])
        amt = t["debit"] or t["credit"]
        c.drawRightString(450, y, money(amt))
        c.drawString(465, y, "DR" if t["debit"] else "CR")
        c.drawRightString(580, y, money(t["balance"]) + " Cr")
        y -= 14
    c.save()
    for t in txns:
        t["lines"] = [" ".join(t["lines"])[:60]]
    write_expected("icici_style", dict(bankName="ICICI Bank", accountHolder="ANKITA SEN",
                                       accountNumber="XXXXXXXX4321", periodStart="2025-08-01",
                                       periodEnd="2025-08-31", openingBalance=opening, closingBalance=None), txns)


sbi("sbi_style")
sbi("sbi_style_locked", encrypt="mallick123")
hdfc()
icici()
print("fixtures written to", OUT)
