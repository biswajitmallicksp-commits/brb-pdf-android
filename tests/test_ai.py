"""Tests of the offline AI features (with a stand-in model server; no real model needed).

Run:  .venv\\Scripts\\python -m unittest tests.test_ai
"""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ai import engine as E  # noqa: E402
from app.ai import forms as F  # noqa: E402
from app.ai import tasks as K  # noqa: E402
from app.ai import text as T  # noqa: E402

FAKE = ROOT / "tests" / "fake_llama_server.py"

PROFILE = ["CUSTOMER PROFILE", "Name of Applicant: RAMESH KUMAR SHARMA", "Father's Name: SURESH SHARMA",
           "Date of Birth: 14-08-1985", "PAN: ABCPS1234K", "Mobile: 9876543210",
           "Email: ramesh.sharma@example.com", "Address: 12 Park Street, Kolkata, West Bengal", "PIN Code: 700016",
           "Bank Account Number: 123456789012", "IFSC Code: SBIN0001234",
           "The applicant runs a small textile business since 2015."]


def source_doc() -> fitz.Document:
    d = fitz.open()
    p = d.new_page()
    y = 60
    for line in PROFILE:
        p.insert_text((50, y), line, fontsize=11)
        y += 18
    # a second page in a table layout: label and value far apart
    p2 = d.new_page()
    p2.insert_text((50, 80), "Annual Income", fontsize=11)
    p2.insert_text((300, 80), "Rs. 8,40,000", fontsize=11)
    p2.insert_text((50, 100), "Loan Amount", fontsize=11)
    p2.insert_text((300, 100), "Rs. 15,00,000", fontsize=11)
    return d


def flat_form() -> fitz.Document:
    d = fitz.open()
    q = d.new_page()
    y = 80
    for lab in ["1. Full Name: ______________________________", "Date of Birth ....................", "PAN No:",
                "Mobile Number: __________________", "IFSC: ____________", "Account No.: __________________",
                "Annual Income: ______________", "Nominee Name: ______________"]:
        q.insert_text((50, y), lab, fontsize=11)
        y += 30
    return d


def fillable_form() -> fitz.Document:
    d = fitz.open()
    pg = d.new_page()
    y = 80
    for lab, name in (("Applicant name", "applicant_name"), ("PAN", "pan_no"), ("E-mail", "email"),
                      ("Branch", "branch")):
        pg.insert_text((50, y + 12), lab, fontsize=11)
        w = fitz.Widget()
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_name = name
        w.rect = fitz.Rect(180, y, 450, y + 18)
        pg.add_widget(w)
        y += 30
    return d


def book() -> fitz.Document:
    d = fitz.open()
    paras = {
        "Chapter 1 Introduction": "This agreement explains the home loan offered by the bank. ",
        "Chapter 2 Interest and Repayment": "The interest rate is 8.5 percent per year, fixed for three years. "
                                            "The loan is repaid in 240 monthly instalments. ",
        "Chapter 3 Charges": "A processing fee of one percent is charged. Late payment attracts a penalty. ",
    }
    toc = []
    for title, body in paras.items():
        for k in range(2):
            p = d.new_page()
            if k == 0:
                toc.append([1, title, d.page_count])
                p.insert_text((50, 60), title, fontsize=16)
            tw = fitz.TextWriter(p.rect)
            tw.fill_textbox(fitz.Rect(50, 90, 545, 800), (body * 8).strip(), fontsize=11)
            tw.write_text(p)
    d.set_toc(toc)
    return d


class TextTests(unittest.TestCase):
    def test_chapters_and_routing(self):
        d = book()
        chs = T.chapters(d)
        self.assertEqual([(c.first, c.last) for c in chs], [(0, 1), (2, 3), (4, 5)])
        self.assertEqual(T.find_chapter(chs, "chapter 2").title, "Chapter 2 Interest and Repayment")
        self.assertEqual(T.find_chapter(chs, "charges").first, 4)
        r = K.route("Summarise chapter 2 in short", d.page_count, 0, chs)
        self.assertEqual((r.kind, r.scope, r.pages, r.length), ("summary", "chapter", [2, 3], "short"))
        r = K.route("give me a detailed summary of pages 2 to 4 in Hindi", d.page_count, 0, chs)
        self.assertEqual((r.scope, r.pages, r.length), ("pages", [1, 2, 3], "detailed"))
        self.assertIn("Hindi", K._extra(r.instruction))
        self.assertEqual(K.route("summary of this page", 6, 3, chs).pages, [3])
        self.assertEqual(K.route("summarise", 6, 0, chs).pages, list(range(6)))
        self.assertEqual(K.route("What is the interest rate?", 6, 0, chs).kind, "ask")

    def test_chunks_cover_everything(self):
        d = book()
        ps = T.pages_text(d, list(range(d.page_count)))
        groups = T.chunks(ps, max_tokens=300)
        self.assertGreater(len(groups), 2)
        joined = "".join(p.text for g in groups for p in g)
        self.assertEqual(len(joined.replace("\n", "")), len("".join(p.text for p in ps).replace("\n", "")))
        for g in groups:
            self.assertLessEqual(sum(T.approx_tokens(p.text) for p in g), 300 + 5)

    def test_search_and_quick_answers(self):
        d = book()
        ps = T.pages_text(d, list(range(d.page_count)))
        hits = T.Bm25(ps).search("interest rate per year")
        self.assertIn(hits[0][1].page, (2, 3))
        a = K.answer(None, ps, "What is the processing fee?", K.Job())
        self.assertIn("p. 5", a)
        s = K.summarise(None, ps, K.Request("summary", pages=list(range(6))), K.Job())
        self.assertIn("quick mode", s)
        self.assertIn("(p.", s)

    def test_scanned_or_empty(self):
        self.assertIn("OCR", K.summarise(None, [], K.Request("summary", pages=[0]), K.Job()))
        self.assertIn("OCR", K.answer(None, [], "anything", K.Job()))


class FormTests(unittest.TestCase):
    def setUp(self):
        self.src = T.pages_text(source_doc(), [0, 1])

    def test_flat_form_detect_find_fill(self):
        form = flat_form()
        fields = F.detect_fields(form)
        self.assertEqual([f.label for f in fields],
                         ["Full Name", "Date of Birth", "PAN No", "Mobile Number", "IFSC", "Account No",
                          "Annual Income", "Nominee Name"])
        F.find_values(fields, self.src)
        got = {f.label: f.value for f in fields}
        self.assertEqual(got["Full Name"], "RAMESH KUMAR SHARMA")
        self.assertEqual(got["Date of Birth"], "14-08-1985")
        self.assertEqual(got["PAN No"], "ABCPS1234K")
        self.assertEqual(got["Mobile Number"], "9876543210")
        self.assertEqual(got["IFSC"], "SBIN0001234")
        self.assertEqual(got["Account No"], "123456789012")
        self.assertEqual(got["Annual Income"], "Rs. 8,40,000")     # from the two-column table
        self.assertEqual(got["Nominee Name"], "")                  # not in the document: left empty
        self.assertEqual(next(f for f in fields if f.label == "Annual Income").source_page, 1)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "filled.pdf"
            n = F.fill(flat_form(), fields, str(out))
            self.assertEqual(n, 7)
            text = fitz.open(out)[0].get_text()
            for v in ("RAMESH KUMAR SHARMA", "ABCPS1234K", "SBIN0001234", "8,40,000"):
                self.assertIn(v, text)
            # each value is written on its own line, next to its label
            pan = fitz.open(out)[0].search_for("ABCPS1234K")[0]
            label = fitz.open(out)[0].search_for("PAN No")[0]
            self.assertLess(abs((pan.y0 + pan.y1) / 2 - (label.y0 + label.y1) / 2), 6)
            self.assertGreater(pan.x0, label.x1)

    def test_fillable_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "form.pdf"
            fillable_form().save(path)
            fields = F.detect_fields(fitz.open(path))
            self.assertEqual([f.label for f in fields], ["Applicant name", "PAN", "E-mail", "Branch"])
            F.find_values(fields, self.src)
            out = Path(tmp) / "filled.pdf"
            F.fill(fitz.open(path), fields, str(out))
            vals = {w.field_name: w.field_value for w in fitz.open(out)[0].widgets()}
            self.assertEqual(vals["applicant_name"], "RAMESH KUMAR SHARMA")
            self.assertEqual(vals["pan_no"], "ABCPS1234K")
            self.assertEqual(vals["email"], "ramesh.sharma@example.com")
            self.assertEqual(vals["branch"], "")
            # the original form is untouched
            self.assertEqual({w.field_value for w in fitz.open(path)[0].widgets()}, {""})

    def test_concepts(self):
        self.assertEqual(F.concept("Applicant's Name"), "name")
        self.assertEqual(F.concept("A/C No."), "account")
        self.assertEqual(F.concept("Date of Birth (DD-MM-YYYY)"), "dob")
        self.assertIsNone(F.concept("Nominee relation"))
        # someone else's details never take the applicant's values
        self.assertIsNone(F.concept("Nominee Name"))
        self.assertIsNone(F.concept("Guarantor PAN"))
        self.assertEqual(F.concept("Full Name"), "name")
        self.assertEqual(F.concept("Mobile No. (self)"), "mobile")


class ModelTests(unittest.TestCase):
    """The real program flow with a stand-in llama-server."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        model = Path(cls.tmp.name) / "fake.gguf"
        model.write_bytes(b"0")
        cls.model = E.LocalModel(Path(sys.executable), model, launcher=[sys.executable, str(FAKE)])

    @classmethod
    def tearDownClass(cls):
        cls.model.stop()
        cls.tmp.cleanup()

    def test_chat_streams(self):
        pieces = []
        out = self.model.chat([{"role": "user", "content": "[Page 3]\nhello"}], on_token=pieces.append)
        self.assertTrue(out.startswith("SUMMARY"))
        self.assertGreater(len(pieces), 3)
        self.assertEqual("".join(pieces), out)
        self.assertTrue(self.model.running())

    def test_long_summary_uses_parts(self):
        d = book()
        ps = T.pages_text(d, list(range(d.page_count)))
        msgs = []
        job = K.Job(progress=msgs.append)
        old = T.chunks
        T.chunks = lambda p, max_tokens=2200: old(p, max_tokens=150)    # force several parts
        try:
            out = K.summarise(self.model, ps, K.Request("summary", pages=list(range(6))), job)
        finally:
            T.chunks = old
        self.assertTrue(out.startswith("SUMMARY"))
        self.assertTrue(any(m.startswith("Reading part") for m in msgs))

    def test_answer(self):
        ps = T.pages_text(book(), list(range(6)))
        out = K.answer(self.model, ps, "What is the interest rate?", K.Job())
        self.assertIn("ANSWER", out)

    def test_form_values_from_model_must_be_in_document(self):
        fields = [F.FormField("a", "Father Name", 0, fitz.Rect(0, 0, 10, 10)),
                  F.FormField("b", "Nominee Name", 0, fitz.Rect(0, 0, 10, 10))]
        src = T.pages_text(source_doc(), [0, 1])
        F._ask_model(fields, src, self.model, K.Job())
        self.assertEqual(fields[0].value, "SURESH SHARMA")
        self.assertEqual(fields[0].source, "AI")
        self.assertEqual(fields[1].value, "")

    def test_cancel(self):
        slow = E.LocalModel(Path(sys.executable), self.model.model, launcher=[sys.executable, str(FAKE), "--slow"])
        try:
            job = K.Job()
            got = []

            def tok(p):
                got.append(p)
                if len(got) == 2:
                    job.cancel.set()
            job.token = tok
            with self.assertRaises(E.Cancelled):
                slow.chat([{"role": "user", "content": "x" * 50}], on_token=job.token, cancel=job.cancel)
        finally:
            slow.stop()
        self.assertFalse(slow.running())

    def test_no_model_installed(self):
        E.set_model(None)
        self.assertIsNone(E.get_model())


if __name__ == "__main__":
    unittest.main()
