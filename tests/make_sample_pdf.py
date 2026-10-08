"""Create test PDFs for trying out the viewer.

Usage (from the project folder):
    .venv\\Scripts\\python tests\\make_sample_pdf.py

Creates in tests\\samples\\:
    sample_600_pages.pdf   600 pages, bookmarks, a mix of portrait/landscape,
                           bank-statement-like tables to search in
    sample_protected.pdf   password protected, password: test123
    sample_scanned.pdf     an image-only page (no text layer; OCR comes in Phase 4)
"""
from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

import pymupdf as fitz

OUT = Path(__file__).resolve().parent / "samples"


def make_large(path: Path, pages: int = 600) -> None:
    rnd = random.Random(42)
    doc = fitz.open()
    toc = []
    balance = 125000.00
    day = dt.date(2025, 6, 1)
    narrations = ["UPI/{r}/GROCERY MART", "NEFT CR SALARY ACME LTD", "ATM WDL KOLKATA",
                  "IMPS/{r}/RENT", "EMI HOME LOAN 11223", "CHQ DEP 004512", "CASH DEPOSIT BRANCH",
                  "RTGS CR SUPPLIER PAYMENT", "CHQ RETURN INSUFFICIENT FUNDS", "UPI/{r}/ELECTRICITY"]
    for i in range(pages):
        landscape = (i % 97 == 50)
        w, h = (842, 595) if landscape else (595, 842)
        page = doc.new_page(width=w, height=h)
        if i % 25 == 0:
            toc.append([1, f"Section {i // 25 + 1}", i + 1])
        if i % 25 == 5:
            toc.append([2, f"Statement month {i // 25 + 1}", i + 1])
        page.insert_text((50, 60), f"Sample Bank Ltd - Account Statement   Page {i + 1} of {pages}",
                         fontsize=13, fontname="helv")
        page.insert_text((50, 80), "Date        Description                          Debit       Credit      Balance",
                         fontsize=9, fontname="cour")
        y = 100
        while y < h - 60:
            debit = credit = 0.0
            text = rnd.choice(narrations).format(r=rnd.randint(100000, 999999))
            if "CR" in text or "DEP" in text:
                credit = round(rnd.uniform(500, 50000), 2)
            else:
                debit = round(rnd.uniform(100, 20000), 2)
            balance += credit - debit
            line = (f"{day:%d-%m-%Y}  {text[:34]:<34} {debit:>11,.2f} {credit:>11,.2f} {balance:>12,.2f}")
            page.insert_text((50, y), line, fontsize=8.5, fontname="cour")
            y += 14
            if rnd.random() < 0.3:
                day += dt.timedelta(days=1)
        page.insert_text((50, h - 30), "This is a generated test document. Not a real statement.",
                         fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
    doc.set_toc(toc)
    doc.set_metadata({"title": "Sample 600 page statement", "author": "PDF Workbench test generator",
                      "subject": "Viewer performance test", "keywords": "test, sample"})
    doc.save(path, garbage=3, deflate=True)
    doc.close()


def make_protected(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "This document is password protected. Password: test123", fontsize=14)
    doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="test123", owner_pw="owner123",
             permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY)
    doc.close()


def make_scanned(path: Path) -> None:
    src = fitz.open()
    page = src.new_page()
    page.insert_text((72, 120), "This page was turned into an image.", fontsize=18)
    page.insert_text((72, 150), "Search will not find this text until OCR (Phase 4).", fontsize=12)
    pix = page.get_pixmap(dpi=150)
    doc = fitz.open()
    out = doc.new_page(width=page.rect.width, height=page.rect.height)
    out.insert_image(out.rect, pixmap=pix)
    doc.save(path)
    doc.close()
    src.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    make_large(OUT / f"sample_{pages}_pages.pdf", pages)
    make_protected(OUT / "sample_protected.pdf")
    make_scanned(OUT / "sample_scanned.pdf")
    print(f"Created test files in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
