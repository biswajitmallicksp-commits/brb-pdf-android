"""Images to PDF: several pictures (PNG, JPG, a rotated camera photo) into one PDF, plus the dialog.

Run:  .venv\\Scripts\\python tests\\test_images_pdf.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    import pymupdf as fitz
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication, QDialog

    from app.pdf_pages import operations as ops
    from app.ui import images_dialog as D

    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    folder = Path(tmp.name)
    tall = folder / "b_tall.png"
    img = QImage(400, 600, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 255, 200))
    img.save(str(tall))
    wide = folder / "a_wide.jpg"
    img = QImage(1200, 800, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    img.save(str(wide), "JPEG", 90)
    # a JPEG with EXIF orientation 6 (camera held upright): 300x200 stored, shown 200x300
    rotated = folder / "c_camera.jpg"
    raw = bytearray(fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 200), False).tobytes("jpeg"))
    exif = (b"Exif\x00\x00" b"MM\x00\x2a\x00\x00\x00\x08" b"\x00\x01" b"\x01\x12\x00\x03\x00\x00\x00\x01\x00\x06\x00\x00"
            b"\x00\x00\x00\x00")
    app1 = b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif
    rotated.write_bytes(bytes(raw[:2]) + app1 + bytes(raw[2:]))
    broken = folder / "d_broken.png"
    broken.write_bytes(b"not a picture")

    out = folder / "pictures.pdf"
    result, skipped = ops.images_to_pdf([str(tall), str(wide), str(rotated), str(broken)], out, "a4", "small")
    doc = fitz.open(result)
    assert doc.page_count == 3 and skipped == ["d_broken.png"], (doc.page_count, skipped)
    assert round(doc[0].rect.width) == 595 and round(doc[0].rect.height) == 842          # portrait for a tall picture
    assert round(doc[1].rect.width) == 842 and round(doc[1].rect.height) == 595          # landscape for a wide one
    assert round(doc[2].rect.width) == 595, "the camera photo is turned upright (portrait page)"
    for p in doc:
        assert len(p.get_images()) == 1
        r = p.get_image_rects(p.get_images()[0][0])[0]
        assert r.x0 >= 17 and r.y0 >= 17 and r.x1 <= p.rect.width - 17, r
    info = doc[2].get_image_info()[0]
    assert info["width"] == 200 and info["height"] == 300, info
    # same size as the picture, smaller file
    out2 = folder / "fit.pdf"
    result2, _ = ops.images_to_pdf([str(wide)], out2, "fit", smaller=True)
    p = fitz.open(result2)[0]
    assert abs(p.rect.width - 1200 * 72 / 150) < 1 and abs(p.rect.height - 800 * 72 / 150) < 1, p.rect
    try:
        ops.images_to_pdf([str(broken)], folder / "x.pdf")
        raise AssertionError("no readable pictures must fail")
    except ops.PageOpError:
        pass

    # the dialog: order, sort, output name
    dlg = D.ImagesToPdfDialog(str(folder), [str(tall), str(wide), str(rotated)])
    assert dlg.files() == [str(tall), str(wide), str(rotated)]
    assert dlg.output.text().endswith("b_tall (3 pages).pdf"), dlg.output.text()
    dlg.list.setCurrentRow(2)
    dlg._shift(-1)
    assert dlg.files()[1] == str(rotated) and dlg.list.item(1).text().startswith("2. c_camera")
    dlg._sort()
    assert dlg.files() == [str(wide), str(tall), str(rotated)]
    dlg.page_size.setCurrentIndex(3)
    assert dlg.options() == {"page_size": "fit", "margin": "small", "smaller": False} and not dlg.margin.isEnabled()
    dlg.output.setText(str(folder / "made.pdf"))
    dlg._accept()
    assert dlg.result() == QDialog.DialogCode.Accepted
    print("Images to PDF test: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
