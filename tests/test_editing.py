"""Editing and annotation engine tests (no window).

Run:  .venv\\Scripts\\python -m unittest tests.test_editing -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pdf_annotation import annots as A  # noqa: E402
from app.pdf_editor import content as C  # noqa: E402
from app.pdf_editor import fonts  # noqa: E402
from app.pdf_pages.operations import PageOpError  # noqa: E402


def statement_page(doc: fitz.Document, rotation: int = 0) -> fitz.Page:
    page = doc.new_page(width=595, height=842)
    page.set_rotation(rotation)
    # write upright (as seen on screen) whatever the rotation
    C.add_text(page, fitz.Rect(72, 90, 520, 120) * page.derotation_matrix,
               "Opening balance 1,25,430.50 as on 01-06-2025", C.TextStyle("serif", 12))
    C.add_text(page, fitz.Rect(72, 115, 520, 145) * page.derotation_matrix,
               "Account No 1234567890 EMI HOME LOAN", C.TextStyle("sans", 12))
    page.draw_rect(fitz.Rect(60, 80, 540, 150), color=(0, 0, 1))
    return page


def word(page: fitz.Page, text: str) -> fitz.Rect:
    return next(fitz.Rect(w[:4]) for w in page.get_text("words") if w[4] == text)


class ContentTests(unittest.TestCase):
    def test_fonts_found(self):
        keys = [f.key for f in fonts.font_families()]
        self.assertIn("sans", keys)
        self.assertTrue(fonts.needs_indic_font("আমার"))
        self.assertFalse(fonts.needs_indic_font("Total 45,000"))

    def test_add_edit_delete_all_rotations(self):
        for rot in (0, 90, 180, 270):
            with self.subTest(rotation=rot):
                doc = fitz.open()
                page = statement_page(doc, rot)
                drawings = len(page.get_drawings())
                # edit a line
                w = word(page, "Opening")
                line = C.text_line_at(page, fitz.Point((w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2))
                self.assertEqual(line.text, "Opening balance 1,25,430.50 as on 01-06-2025")
                self.assertEqual(line.style().family, "serif")
                before = fitz.Rect(line.rect) * page.rotation_matrix
                C.replace_line(page, line, "Opening balance 9,99,999.00 as on 01-06-2025")
                text = page.get_text()
                self.assertIn("9,99,999.00", text)
                self.assertNotIn("1,25,430.50", text)
                self.assertIn("Account No 1234567890", " ".join(text.split()))   # next line untouched
                after = word(page, "Opening") * page.rotation_matrix
                self.assertLess(abs(after.x0 - before.x0), 3)
                self.assertLess(abs(after.y0 - before.y0), 4)
                # delete one word
                C.delete_text_in(page, word(page, "1234567890"))
                self.assertNotIn("1234567890", page.get_text())
                self.assertIn("EMI", page.get_text())
                self.assertEqual(len(page.get_drawings()), drawings)          # the frame stays
                doc.close()

    def test_add_indic_text(self):
        doc = fitz.open()
        page = doc.new_page()
        C.add_text(page, fitz.Rect(72, 72, 500, 200), "জমা राशि Total", C.TextStyle("sans", 12))
        text = page.get_text()
        self.assertIn("Total", text)
        self.assertIn("राश", text)
        fams = {f[3] for f in page.get_fonts()}
        self.assertTrue(fams)

    def test_errors_are_clear(self):
        doc = fitz.open()
        page = doc.new_page()
        with self.assertRaises(PageOpError):
            C.delete_text_in(page, fitz.Rect(0, 0, 50, 50))
        with self.assertRaises(PageOpError):
            C.add_text(page, fitz.Rect(10, 10, 100, 100), "   ", C.TextStyle())

    def test_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "logo.png"
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 30), False)
            pix.clear_with(120)
            pix.save(img)
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 300), "keep me", fontsize=12)
            C.add_image(page, fitz.Rect(100, 100, 220, 160), str(img))
            img2 = Path(tmp) / "seal.png"
            pix2 = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
            pix2.clear_with(30)
            pix2.save(img2)
            C.add_image(page, fitz.Rect(300, 100, 420, 160), str(img2), opacity=0.4)
            self.assertEqual(len(C.image_boxes(page)), 2)
            files = C.extract_images(doc, [0], tmp, "x")
            self.assertGreaterEqual(len(files), 1)
            C.delete_images_in(page, fitz.Rect(110, 110, 120, 120))
            self.assertEqual(len(C.image_boxes(page)), 1)
            self.assertIn("keep me", page.get_text())

    def test_watermark_and_header_footer(self):
        for rot in (0, 90):
            doc = fitz.open()
            for _ in range(3):
                doc.new_page().set_rotation(rot)
            for p in doc:
                C.add_text_watermark(p, "CONFIDENTIAL", opacity=0.2)
                C.add_header_footer(p, [C.HeaderFooterItem("bottom-center", "Page {page} of {pages}"),
                                        C.HeaderFooterItem("top-right", "{file}")], doc.page_count, "stmt.pdf")
            self.assertIn("Page 2 of 3", doc[1].get_text())
            self.assertIn("CONFIDENTIAL", doc[2].get_text())
            # footer sits near the visible bottom of the page
            r = doc[1].search_for("Page 2 of 3")[0] * doc[1].rotation_matrix
            self.assertGreater(r.y0, doc[1].rect.height - 60)


class AnnotTests(unittest.TestCase):
    def test_create_list_move_update_delete(self):
        doc = fitz.open()
        page = statement_page(doc)
        st = A.AnnotStyle()
        A.add_text_markup(page, "Highlight", [word(page, "Opening")], A.AnnotStyle(stroke=(1, 0.9, 0)))
        A.add_note(page, fitz.Point(400, 300), "Check", st)
        tb = A.add_text_box(page, fitz.Rect(72, 200, 300, 250), "Please verify", st)
        sq = A.add_shape(page, "Square", fitz.Rect(72, 300, 200, 340), st)
        A.add_shape(page, "Circle", fitz.Rect(220, 300, 300, 340), A.AnnotStyle(fill=(0.9, 0.9, 1)))
        ln = A.add_line(page, fitz.Point(72, 400), fitz.Point(200, 430), st, arrow=True)
        A.add_ink(page, [[fitz.Point(72, 500), fitz.Point(90, 520), fitz.Point(120, 500)]], st)
        A.add_stamp(page, fitz.Rect(350, 600, 520, 660), "PAID", st)
        A.add_stamp(page, fitz.Rect(350, 700, 520, 760), "Approved", st)
        kinds = [i.kind for i in A.list_annots(page)]
        self.assertEqual(kinds, ["Highlight", "Text", "FreeText", "Square", "Circle", "Line", "Ink",
                                 "FreeText", "Stamp"])
        self.assertEqual(A.annot_at(page, fitz.Point(100, 320)).xref, sq)
        A.move_annot(page, sq, 10, 20)
        self.assertEqual(A.annot_at(page, fitz.Point(110, 340)).xref, sq)
        new_line = A.move_annot(page, ln, 0, 50)
        line_info = next(i for i in A.list_annots(page) if i.xref == new_line)
        self.assertAlmostEqual(line_info.vertices[0][1], 450)
        A.update_annot(page, tb, A.AnnotStyle(fontsize=14, text_color=(0, 0, 1), width=1), "Please verify NOW")
        tb_info = next(i for i in A.list_annots(page) if i.xref == tb)
        self.assertEqual(tb_info.contents, "Please verify NOW")
        self.assertEqual(tb_info.fontsize, 14)
        A.resize_annot(page, tb, fitz.Rect(72, 200, 340, 260))
        with self.assertRaises(PageOpError):
            A.move_annot(page, A.list_annots(page)[0].xref, 5, 5)     # highlights stay with their text
        A.delete_annot(page, sq)
        self.assertEqual(len(A.list_annots(page)), 8)
        # survives saving
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.pdf"
            doc.save(out)
            with fitz.open(out) as d:
                self.assertEqual(len(A.list_annots(d[0])), 8)

    def test_redaction_removes_text(self):
        doc = fitz.open()
        page = statement_page(doc)
        n = A.mark_text_redactions(doc, "1234567890")
        self.assertEqual(n, 1)
        self.assertIn("1234567890", page.get_text())        # marked only, not removed yet
        A.mark_redaction(page, fitz.Rect(72, 300, 200, 340))
        self.assertEqual(A.count_redaction_marks(doc), 2)
        A.apply_redactions(doc, remove_metadata=True)
        self.assertNotIn("1234567890", page.get_text())
        self.assertIn("Opening", page.get_text())
        self.assertEqual(A.count_redaction_marks(doc), 0)
        with self.assertRaises(PageOpError):
            A.apply_redactions(doc)

    def test_rotated_page_annotations(self):
        doc = fitz.open()
        page = statement_page(doc, 90)
        A.add_stamp(page, fitz.Rect(100, 100, 160, 270), "Approved", A.AnnotStyle())  # office style on rotated
        A.add_text_box(page, fitz.Rect(300, 100, 350, 300), "Rotated comment", A.AnnotStyle())
        self.assertEqual([i.kind for i in A.list_annots(page)], ["FreeText", "FreeText"])

    def test_flatten(self):
        doc = fitz.open()
        page = statement_page(doc)
        A.add_text_box(page, fitz.Rect(72, 200, 300, 250), "Final remark", A.AnnotStyle())
        A.flatten_annots(doc)
        page = doc[0]
        self.assertEqual(len(A.list_annots(page)), 0)
        self.assertIn("Final remark", page.get_text())


class PanelEngineTests(unittest.TestCase):
    """Engine behind the Edit Text panel: list lines (columns apart) and replace several at once."""

    def test_page_lines_and_replace_lines_all_rotations(self):
        for rot in (0, 90, 180, 270):
            with self.subTest(rotation=rot):
                doc = fitz.open()
                page = doc.new_page(width=595, height=842)
                page.set_rotation(rot)
                for x, y, t, f in ((50, 100, "Opening balance 12,500.00", "helv"),
                                   (50, 113, "NEFT credit ABC Ltd", "hebo"),
                                   (300, 113, "5,000.00", "helv"), (400, 113, "17,500.00", "helv")):
                    page.insert_text(fitz.Point(x, y) * page.derotation_matrix, t, fontsize=11, fontname=f, rotate=rot)
                page.draw_rect(fitz.Rect(40, 85, 500, 125) * page.derotation_matrix, color=(0, 0, 1))
                lines = C.page_lines(page)
                self.assertEqual([ln.text for ln in lines],
                                 ["Opening balance 12,500.00", "NEFT credit ABC Ltd", "5,000.00", "17,500.00"])
                self.assertTrue(all(ln.editable for ln in lines))
                self.assertTrue(lines[1].style().bold)
                n = C.replace_lines(page, [(lines[1], "NEFT credit XYZ Pvt Ltd"), (lines[2], "")])
                self.assertEqual(n, 2)
                after = [ln.text for ln in C.page_lines(page)]
                self.assertIn("NEFT credit XYZ Pvt Ltd", after)
                self.assertNotIn("5,000.00", after)
                self.assertNotIn("NEFT credit ABC Ltd", after)
                self.assertIn("Opening balance 12,500.00", after)
                self.assertIn("17,500.00", after)
                self.assertEqual(len(page.get_drawings()), 1)          # the box is kept
                new = next(ln for ln in C.page_lines(page) if ln.text.startswith("NEFT"))
                v_old = fitz.Rect(lines[1].rect) * page.rotation_matrix
                v_new = fitz.Rect(new.rect) * page.rotation_matrix
                v_old.normalize(); v_new.normalize()
                self.assertLess(abs(v_old.x0 - v_new.x0), 2)
                self.assertLess(abs(v_old.y1 - v_new.y1), 3)

    def test_ocr_layer_is_not_listed(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 100), "Visible words", fontsize=11)
        font = fitz.Font(fontfile=str(ROOT / "assets" / "ocr_glyphless.ttf"))
        tw = fitz.TextWriter(page.rect)
        tw.append((50, 200), "Hidden OCR words", font=font, fontsize=11)
        tw.write_text(page, render_mode=3)
        self.assertEqual([ln.text for ln in C.page_lines(page)], ["Visible words"])


if __name__ == "__main__":
    unittest.main()
