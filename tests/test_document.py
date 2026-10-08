"""Core tests - no window needed.

Run:  .venv\\Scripts\\python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import AppDatabase  # noqa: E402
from app.pdf_viewer.document import PdfDocument  # noqa: E402
from app.pdf_viewer.render_cache import RenderCache  # noqa: E402
from app.utils.errors import PasswordRequired, PdfOpenError, WrongPassword  # noqa: E402


class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        doc = fitz.open()
        for i in range(30):
            p = doc.new_page()
            p.insert_text((72, 100), f"Page {i + 1} opening balance 1,234.56", fontsize=12)
            p.insert_text((72, 130), "UPI transfer to grocery", fontsize=12)
        doc[5].set_rotation(90)
        doc.set_toc([[1, "Start", 1], [2, "Middle", 15]])
        doc.set_metadata({"title": "Test", "author": "Tester"})
        cls.plain = cls.dir / "plain.pdf"
        doc.save(cls.plain)
        cls.locked = cls.dir / "locked.pdf"
        doc.save(cls.locked, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="own")
        doc.close()
        cls.broken = cls.dir / "broken.pdf"
        cls.broken.write_bytes(b"this is not really a pdf")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_open_and_basics(self):
        d = PdfDocument(self.plain)
        self.assertEqual(d.page_count, 30)
        self.assertEqual(d.page_size(0), (595.0, 842.0))
        self.assertEqual(d.page_size(5), (842.0, 595.0))      # /Rotate applied
        self.assertEqual(d.outline()[1], (2, "Middle", 14))
        d.close()

    def test_render(self):
        d = PdfDocument(self.plain)
        r = d.render(0, 1.0)
        self.assertEqual((r.width, r.height), (595, 842))
        self.assertEqual(len(r.samples), r.stride * r.height)
        r90 = d.render(0, 0.5, 90)
        self.assertEqual((r90.width, r90.height), (421, 298))
        d.close()

    def test_search(self):
        d = PdfDocument(self.plain)
        hits = d.search("grocery")
        self.assertEqual(len(hits), 30)
        self.assertIn("grocery", hits[0].snippet.lower())
        self.assertEqual(len(d.search_page(3, "Page 4 ")), 1)
        d.close()

    def test_selection_and_mapping_on_rotated_page(self):
        d = PdfDocument(self.plain)
        hit = d.search_page(5, "UPI")[0]
        m = d.view_matrix(5, 1.0, 0)
        view_rect = hit.rect * m
        # map back and select: must get the same word
        back = view_rect * ~m
        sel = d.words_in_rect(5, back)
        self.assertEqual(sel.text, "UPI")
        # the word must land inside the rotated page's pixel area
        w, h = d.page_size(5)
        self.assertTrue(0 <= view_rect.x0 <= w and 0 <= view_rect.y1 <= h)
        d.close()

    def test_properties(self):
        d = PdfDocument(self.plain)
        props = dict(d.properties())
        self.assertEqual(props["Pages"], "30")
        self.assertEqual(props["Title"], "Test")
        self.assertIn("Encryption", props)
        d.close()

    def test_password(self):
        with self.assertRaises(PasswordRequired):
            PdfDocument(self.locked)
        with self.assertRaises(WrongPassword):
            PdfDocument(self.locked, "nope")
        d = PdfDocument(self.locked, "secret")
        self.assertEqual(d.page_count, 30)
        self.assertTrue(d.is_encrypted)
        d.close()

    def test_broken_file_gives_clear_error(self):
        with self.assertRaises(PdfOpenError):
            PdfDocument(self.broken)
        with self.assertRaises(PdfOpenError):
            PdfDocument(self.dir / "missing.pdf")

    def test_save_as_copy_and_overwrite(self):
        d = PdfDocument(self.plain)
        copy = d.save_as(self.dir / "copy.pdf")
        self.assertEqual(PdfDocument(copy).page_count, 30)
        # overwrite the open file safely, then keep working with it
        own = self.dir / "own.pdf"
        own.write_bytes(self.plain.read_bytes())
        d2 = PdfDocument(own)
        d2.save_as(own)
        self.assertEqual(d2.page_count, 30)
        self.assertEqual(len(d2.search_page(0, "grocery")), 1)
        d.close()
        d2.close()

    def test_save_keeps_password(self):
        d = PdfDocument(self.locked, "secret")
        out = d.save_as(self.dir / "locked_copy.pdf")
        with self.assertRaises(PasswordRequired):
            PdfDocument(out)
        d.close()


class CacheTests(unittest.TestCase):
    def test_lru_budget(self):
        c = RenderCache(1, size_of=len)          # 1 MB
        for i in range(10):
            c.put(i, b"x" * 300_000)
        self.assertLessEqual(c.used_bytes, 1024 * 1024)
        self.assertIsNone(c.get(0))
        self.assertIsNotNone(c.get(9))


class DatabaseTests(unittest.TestCase):
    def test_recent_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = AppDatabase(Path(tmp) / "t.sqlite3")
            db.add_recent("C:/a.pdf")
            db.add_recent("C:/b.pdf", 7)
            self.assertEqual(db.recent_files()[0], "C:/b.pdf")
            self.assertEqual(db.last_page("C:/b.pdf"), 7)
            db.set_setting("theme", "dark")
            self.assertEqual(db.get_setting("theme"), "dark")
            db.close()


if __name__ == "__main__":
    unittest.main()
