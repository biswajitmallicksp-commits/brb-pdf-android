"""PDF analysis tests.

Run:  .venv\\Scripts\\python -m unittest tests.test_analysis -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pdf_analysis.analyzer import analyze_file, paper_name  # noqa: E402

SCAN = ROOT / "tests" / "data" / "multilingual_scan.png"


def build(path: Path) -> None:
    doc = fitz.open()
    # 1: text page with a link, a comment and form fields
    p = doc.new_page(width=595, height=842)
    p.insert_text((72, 80), "Account statement for June 2025, opening balance 1,25,430.50", fontsize=11)
    p.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 70, 200, 85), "uri": "https://example.com"})
    p.add_highlight_annot(fitz.Rect(72, 70, 200, 85))
    w = fitz.Widget()
    w.field_name, w.field_type, w.rect, w.field_value = "customer_name", fitz.PDF_WIDGET_TYPE_TEXT, \
        fitz.Rect(72, 120, 300, 140), "Biswajit"
    p.add_widget(w)
    s = fitz.Widget()
    s.field_name, s.field_type, s.rect = "manager_sign", fitz.PDF_WIDGET_TYPE_SIGNATURE, fitz.Rect(72, 700, 250, 760)
    p.add_widget(s)
    # 2: scanned page (image only)
    p2 = doc.new_page(width=842, height=595)
    p2.insert_image(p2.rect, filename=str(SCAN))
    # 3: blank page
    doc.new_page(width=612, height=792)
    doc.set_toc([[1, "Statement", 1], [1, "Scan", 2]])
    doc.embfile_add("notes.txt", b"hello attachment")
    doc.set_metadata({"title": "Test statement", "author": "Bank"})
    doc.save(path)
    doc.close()


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "mixed.pdf"
        build(cls.path)
        cls.report = analyze_file(str(cls.path), detect_tables=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_paper_names(self):
        self.assertEqual(paper_name(595, 842), "A4")
        self.assertEqual(paper_name(842, 595), "A4")
        self.assertEqual(paper_name(612, 1008), "Legal")
        self.assertEqual(paper_name(500, 500), "Custom")

    def test_pages(self):
        r = self.report
        self.assertEqual([p.status for p in r.pages], ["Text", "Scanned - needs OCR", "Blank"])
        self.assertEqual([p.paper for p in r.pages], ["A4", "A4", "Letter"])
        self.assertEqual(r.pages[1].orientation, "Landscape")
        self.assertEqual(r.pages[0].links, 1)
        self.assertEqual(r.pages[0].comments, 1)
        self.assertEqual(r.pages[0].fields, 2)
        self.assertIsNotNone(r.pages[0].tables)

    def test_structure(self):
        r = self.report
        self.assertEqual(len(r.bookmarks), 2)
        self.assertEqual(r.links, 1)
        self.assertEqual(r.comments["Highlight"], 1)
        names = [f[1] for f in r.form_fields]
        self.assertIn("customer_name", names)
        self.assertEqual(len(r.signatures), 1)
        self.assertFalse(r.signatures[0]["signed"])
        self.assertEqual(r.attachments[0][0], "notes.txt")
        basic = dict(r.basic)
        self.assertEqual(basic["Title"], "Test statement")
        self.assertEqual(basic["Pages"], "3")

    def test_findings_and_exports(self):
        r = self.report
        text = " ".join(t for _l, t in r.findings)
        self.assertIn("scanned page(s) have no searchable text", text)
        self.assertIn("blank page", text)
        self.assertIn("NOT checked", text)            # never claims a signature is valid
        csv_text = r.to_csv()
        self.assertTrue(csv_text.startswith("Page,"))
        self.assertEqual(len(csv_text.strip().splitlines()), 4)
        self.assertIn("<table>", r.to_html())
        self.assertIn("PDF ANALYSIS REPORT", r.to_text())


if __name__ == "__main__":
    unittest.main()
