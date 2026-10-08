"""Page management tests (no window needed).

Run:  .venv\\Scripts\\python -m unittest tests.test_pages -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pdf_pages import operations as ops  # noqa: E402
from app.pdf_viewer.document import PdfDocument  # noqa: E402
from app.utils.pages import describe_pages, parse_page_range, parse_range_groups  # noqa: E402


def labels(doc: fitz.Document) -> list[str]:
    """Each test page carries its label 'P1', 'P2', ... as text."""
    return [p.get_text().split()[0] if p.get_text().strip() else "-" for p in doc]


def make_pdf(path: Path, n: int, prefix: str = "P", bookmarks: bool = False) -> Path:
    doc = fitz.open()
    for i in range(n):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"{prefix}{i + 1}", fontsize=20)
    if bookmarks:
        doc.set_toc([[1, "Intro", 1], [1, "Chapter A", 3], [2, "A.1", 4], [1, "Chapter B", 6]])
    doc.save(path)
    doc.close()
    return path


class RangeTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_page_range("1-3, 7", 10), [0, 1, 2, 6])
        self.assertEqual(parse_page_range("8-", 10), [7, 8, 9])
        self.assertEqual(parse_page_range("odd", 5), [0, 2, 4])
        self.assertEqual(parse_page_range("last", 5), [4])
        with self.assertRaises(ValueError):
            parse_page_range("0-3", 10)
        with self.assertRaises(ValueError):
            parse_page_range("abc", 10)
        self.assertEqual(parse_range_groups("1-2; 5", 6), [[0, 1], [4]])
        self.assertEqual(describe_pages([0, 1, 2, 5]), "1-3, 6")


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.doc = fitz.open(make_pdf(self.dir / "ten.pdf", 10))

    def tearDown(self):
        self.doc.close()
        self.tmp.cleanup()

    def test_rotate(self):
        ops.rotate_pages(self.doc, [0, 2], 90)
        ops.rotate_pages(self.doc, [2], 90)
        self.assertEqual([self.doc[i].rotation for i in range(3)], [90, 0, 180])
        ops.rotate_pages(self.doc, [0], -90)
        self.assertEqual(self.doc[0].rotation, 0)

    def test_delete(self):
        ops.delete_pages(self.doc, [0, 4, 9])
        self.assertEqual(labels(self.doc), ["P2", "P3", "P4", "P6", "P7", "P8", "P9"])
        with self.assertRaises(ops.PageOpError):
            ops.delete_pages(self.doc, range(self.doc.page_count))

    def test_duplicate(self):
        ops.duplicate_pages(self.doc, [1, 9])
        self.assertEqual(labels(self.doc)[:4], ["P1", "P2", "P2", "P3"])
        self.assertEqual(labels(self.doc)[-2:], ["P10", "P10"])

    def test_move(self):
        new_pos = ops.move_pages(self.doc, [7, 8], 1)          # before P2
        self.assertEqual(labels(self.doc)[:5], ["P1", "P8", "P9", "P2", "P3"])
        self.assertEqual(new_pos, [1, 2])
        ops.move_pages(self.doc, [0], self.doc.page_count)     # to the end
        self.assertEqual(labels(self.doc)[-1], "P1")

    def test_reverse_and_reorder(self):
        ops.reverse_pages(self.doc)
        self.assertEqual(labels(self.doc)[0], "P10")
        with self.assertRaises(ops.PageOpError):
            ops.reorder_pages(self.doc, [0, 0, 1])

    def test_insert_blank_and_document(self):
        ops.insert_blank_pages(self.doc, 2, count=2, size=ops.PAPER_SIZES["A3"])
        self.assertEqual(labels(self.doc)[:5], ["P1", "P2", "-", "-", "P3"])
        self.assertAlmostEqual(self.doc[2].rect.width, 842)
        other = fitz.open(make_pdf(self.dir / "x.pdf", 3, prefix="X"))
        ops.insert_document(self.doc, other, 0, [2, 0])
        self.assertEqual(labels(self.doc)[:3], ["X3", "X1", "P1"])
        ops.insert_document(self.doc, other, self.doc.page_count)
        self.assertEqual(labels(self.doc)[-3:], ["X1", "X2", "X3"])

    def test_insert_image_file(self):
        img = self.dir / "photo.png"
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 100), False)
        pix.clear_with(200)
        pix.save(img)
        src = ops.open_source(img)
        ops.insert_document(self.doc, src, 1)
        self.assertEqual(self.doc.page_count, 11)
        self.assertEqual(len(self.doc[1].get_images()), 1)

    def test_replace(self):
        other = fitz.open(make_pdf(self.dir / "y.pdf", 2, prefix="Y"))
        ops.replace_pages(self.doc, [3, 4, 5], other)
        self.assertEqual(labels(self.doc), ["P1", "P2", "P3", "Y1", "Y2", "P7", "P8", "P9", "P10"])

    def test_extract(self):
        out = ops.extract_to_file(self.doc, [4, 0], self.dir / "ex.pdf")
        with fitz.open(out) as d:
            self.assertEqual(labels(d), ["P5", "P1"])
        self.assertEqual(self.doc.page_count, 10)       # source unchanged

    def test_extract_with_password(self):
        out = ops.extract_to_file(self.doc, [0], self.dir / "pw.pdf", password="abc")
        with fitz.open(out) as d:
            self.assertTrue(d.needs_pass)
            self.assertTrue(d.authenticate("abc"))

    def test_split_modes(self):
        self.assertEqual([p.pages for p in ops.split_plan(self.doc, "every", 4)],
                         [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]])
        self.assertEqual(len(ops.split_plan(self.doc, "single")), 10)
        self.assertEqual([p.pages for p in ops.split_plan(self.doc, "ranges", "1-2, 3-5, 9-")],
                         [[0, 1], [2, 3, 4], [8, 9]])
        files = ops.split_to_files(self.doc, ops.split_plan(self.doc, "every", 4), self.dir / "out", "ten")
        self.assertEqual([f.name for f in files], ["ten_01_p1-4.pdf", "ten_02_p5-8.pdf", "ten_03_p9-10.pdf"])
        # running again never overwrites
        again = ops.split_to_files(self.doc, ops.split_plan(self.doc, "every", 4), self.dir / "out", "ten")
        self.assertEqual(again[0].name, "ten_01_p1-4 (2).pdf")

    def test_split_by_bookmarks(self):
        doc = fitz.open(make_pdf(self.dir / "bm.pdf", 8, bookmarks=True))
        parts = ops.split_plan(doc, "bookmarks")
        self.assertEqual([(p.label, p.pages) for p in parts],
                         [("Intro", [0, 1]), ("Chapter A", [2, 3, 4]), ("Chapter B", [5, 6, 7])])
        with self.assertRaises(ops.PageOpError):
            ops.split_plan(self.doc, "bookmarks")

    def test_merge(self):
        a = make_pdf(self.dir / "a.pdf", 2, prefix="A")
        b = make_pdf(self.dir / "b.pdf", 8, prefix="B", bookmarks=True)
        locked = self.dir / "locked.pdf"
        fitz.open(make_pdf(self.dir / "c.pdf", 1, prefix="C")).save(
            locked, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
        out = ops.merge_files([ops.MergeSource(str(a)), ops.MergeSource(str(b), pages=[0, 7]),
                               ops.MergeSource(str(locked), password="pw")], self.dir / "merged.pdf")
        with fitz.open(out) as d:
            self.assertEqual(labels(d), ["A1", "A2", "B1", "B8", "C1"])
            self.assertEqual([t[1] for t in d.get_toc()], ["a", "b", "locked"])
        with self.assertRaises(ops.PageOpError):
            ops.merge_files([ops.MergeSource(str(locked))], self.dir / "bad.pdf")   # no password


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = make_pdf(self.dir / "doc.pdf", 5)

    def tearDown(self):
        self.tmp.cleanup()

    def test_edit_undo_redo_save(self):
        doc = PdfDocument(self.path)
        rev = doc.revision
        doc.apply_edit("Delete page", lambda d: ops.delete_pages(d, [0]))
        self.assertEqual(doc.page_count, 4)
        self.assertTrue(doc.modified)
        self.assertGreater(doc.revision, rev)
        doc.apply_edit("Rotate page", lambda d: ops.rotate_pages(d, [0], 90))
        self.assertEqual(doc.page_size(0), (842.0, 595.0))
        self.assertEqual(doc.undo(), "Rotate page")
        self.assertEqual(doc.page_size(0), (595.0, 842.0))
        self.assertEqual(doc.undo(), "Delete page")
        self.assertEqual(doc.page_count, 5)
        self.assertFalse(doc.modified)                  # back to the saved state
        self.assertEqual(doc.redo(), "Delete page")
        self.assertTrue(doc.modified)
        # the file on disk is untouched until saved
        with fitz.open(self.path) as d:
            self.assertEqual(d.page_count, 5)
        out = doc.save_as(self.dir / "edited.pdf")
        self.assertFalse(doc.modified)
        self.assertEqual(doc.path, out)
        with fitz.open(out) as d:
            self.assertEqual(labels(d), ["P2", "P3", "P4", "P5"])
        doc.close()

    def test_failed_edit_rolls_back(self):
        doc = PdfDocument(self.path)

        def bad(d):
            ops.delete_pages(d, [0])
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            doc.apply_edit("Bad", bad)
        self.assertEqual(doc.page_count, 5)
        self.assertIsNone(doc.undo_label)
        doc.close()

    def test_overwrite_original_after_edit(self):
        doc = PdfDocument(self.path)
        doc.apply_edit("Delete", lambda d: ops.delete_pages(d, [4]))
        doc.save_as(self.path)                          # explicit overwrite
        self.assertFalse(doc.modified)
        with fitz.open(self.path) as d:
            self.assertEqual(d.page_count, 4)
        self.assertEqual(doc.search_page(0, "P1")[0].page, 0)   # still usable
        doc.close()

    def test_encrypted_document_stays_protected_after_edit(self):
        locked = self.dir / "locked.pdf"
        with fitz.open(self.path) as d:
            d.save(locked, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="own")
        doc = PdfDocument(locked, "pw")
        doc.apply_edit("Delete", lambda d: ops.delete_pages(d, [0]))
        out = doc.save_as(self.dir / "locked_edit.pdf")
        with fitz.open(out) as d:
            self.assertTrue(d.needs_pass)
            self.assertTrue(d.authenticate("pw"))
            self.assertEqual(d.page_count, 4)
        doc.close()


if __name__ == "__main__":
    unittest.main()
