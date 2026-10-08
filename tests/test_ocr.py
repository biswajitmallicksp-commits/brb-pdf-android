"""OCR tests (offline). Uses tests/data/multilingual_scan.png: English, Bengali and Hindi
text saved only as an image, i.e. a 'scanned' page.

Run:  .venv\\Scripts\\python -m unittest tests.test_ocr -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pdf_ocr import engine  # noqa: E402

SCAN = ROOT / "tests" / "data" / "multilingual_scan.png"


def make_scanned_pdf(path: Path, rotation: int = 0, extra_text_page: bool = False) -> None:
    """One scanned page (image only), optionally stored sideways with /Rotate so it
    still DISPLAYS upright, plus optionally a normal text page."""
    doc = fitz.open()
    w, h = 400.0, 240.0
    if rotation in (90, 270):
        page = doc.new_page(width=h, height=w)
        # store the image turned so that /Rotate brings it upright again
        page.insert_image(page.rect, filename=str(SCAN), rotate=rotation)
        page.set_rotation(rotation)
    else:
        page = doc.new_page(width=w, height=h)
        page.insert_image(page.rect, filename=str(SCAN))
    if extra_text_page:
        p2 = doc.new_page(width=w, height=h)
        p2.insert_text((40, 60), "This page already has real text: opening balance", fontsize=11)
    doc.save(path)
    doc.close()


@unittest.skipUnless(engine.find_tessdata(), "OCR language files not installed")
class OcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_languages_installed(self):
        langs = engine.available_languages()
        for code in ("eng", "ben", "hin"):
            self.assertIn(code, langs)

    def test_classification(self):
        src = self.dir / "classify.pdf"
        make_scanned_pdf(src, extra_text_page=True)
        doc = fitz.open(src)
        self.assertTrue(engine.classify_page(doc[0]).needs_ocr)
        self.assertFalse(engine.classify_page(doc[1]).needs_ocr)
        doc.close()

    def _check_output(self, out: Path) -> str:
        doc = fitz.open(out)
        page = doc[0]
        text = page.get_text()
        # English, Bengali and Hindi, with spaces between words
        for needle in ("EMI HOME LOAN", "1,06,691.07", "সোনার বাংলা", "ভালোবাসি", "जमा राशि"):
            self.assertTrue(page.search_for(needle), f"{needle!r} not found in:\n{text}")
        # appearance is unchanged: the original image is still the only image
        self.assertEqual(len(page.get_images()), 1)
        # running OCR again must not add a second text layer
        self.assertFalse(engine.classify_page(page).needs_ocr)
        doc.close()
        return text

    def test_make_searchable_all_languages(self):
        src = self.dir / "scan.pdf"
        out = self.dir / "scan_OCR.pdf"
        make_scanned_pdf(src, extra_text_page=True)
        result = engine.make_searchable(str(src), None, str(out), ["eng", "ben", "hin"], dpi=300)
        self.assertEqual(result.pages_done, [0])
        self.assertEqual(result.pages_skipped, [1])
        self.assertFalse(result.pages_failed)
        self._check_output(out)
        # the original is untouched
        self.assertTrue(engine.classify_page(fitz.open(src)[0]).needs_ocr)

    def test_rotated_page(self):
        src = self.dir / "rotated.pdf"
        out = self.dir / "rotated_OCR.pdf"
        make_scanned_pdf(src, rotation=90)
        result = engine.make_searchable(str(src), None, str(out), ["eng", "ben", "hin"], dpi=300)
        self.assertEqual(result.pages_done, [0])
        self._check_output(out)
        # highlight boxes must fall inside the visible page
        doc = fitz.open(out)
        page = doc[0]
        hit = page.search_for("EMI")[0] * page.rotation_matrix
        self.assertTrue(page.rect.contains(hit), (hit, page.rect))
        doc.close()

    def test_password_protected(self):
        src = self.dir / "plain.pdf"
        make_scanned_pdf(src)
        locked = self.dir / "locked.pdf"
        fitz.open(src).save(locked, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw1", owner_pw="own")
        out = self.dir / "locked_OCR.pdf"
        engine.make_searchable(str(locked), "pw1", str(out), ["eng"], dpi=200)
        doc = fitz.open(out)
        self.assertTrue(doc.needs_pass)          # protection kept
        self.assertTrue(doc.authenticate("pw1"))
        self.assertTrue(doc[0].search_for("STATE BANK"))
        doc.close()

    def test_single_page_text(self):
        src = self.dir / "single.pdf"
        make_scanned_pdf(src)
        res = engine.recognize_single_page(str(src), None, 0, ["eng", "ben", "hin"])
        self.assertEqual(res.error, "")
        text = res.text()
        self.assertIn("EMI HOME LOAN", text)
        self.assertIn("আমার সোনার বাংলা", text)

    def test_refuses_to_overwrite_original(self):
        src = self.dir / "same.pdf"
        make_scanned_pdf(src)
        with self.assertRaises(ValueError):
            engine.make_searchable(str(src), None, str(src), ["eng"])


if __name__ == "__main__":
    unittest.main()
