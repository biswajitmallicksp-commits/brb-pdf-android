"""Generate assets/ocr_glyphless.ttf - the invisible font used for the OCR text layer.

Every supported character maps to its own EMPTY glyph (no outline), so the text is
never drawn, but copy/search/extraction return the correct Unicode text in any PDF
reader. One distinct glyph per character keeps the reverse mapping (ToUnicode) exact.
Covers Latin, Bengali, Devanagari, Vedic extensions, currency symbols (incl. Rupee).

Only needed by developers (requires: pip install fonttools). The generated font is
already included in assets/.
"""
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

RANGES = [
    (0x0020, 0x007E), (0x00A0, 0x024F),          # Latin + Latin-1 + Latin Extended
    (0x0900, 0x097F), (0xA8E0, 0xA8FF),          # Devanagari (+ extended)
    (0x0980, 0x09FF),                            # Bengali
    (0x1CD0, 0x1CFF),                            # Vedic extensions
    (0x2000, 0x206F),                            # punctuation, ZWJ/ZWNJ
    (0x20A0, 0x20CF),                            # currency symbols (Rupee U+20B9)
    (0x2100, 0x214F), (0x2190, 0x21FF),          # letter-like symbols, arrows
]
ADVANCE = 500
UPEM = 1000


def build(out: Path) -> None:
    codepoints = [cp for a, b in RANGES for cp in range(a, b + 1)]
    names = [".notdef"] + [f"u{cp:04X}" for cp in codepoints]
    fb = FontBuilder(UPEM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({cp: f"u{cp:04X}" for cp in codepoints})
    empty = TTGlyphPen(None).glyph()
    fb.setupGlyf({n: empty for n in names})
    fb.setupHorizontalMetrics({n: (ADVANCE, 0) for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "PDFWorkbench OCR Glyphless", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    fb.save(str(out))
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(codepoints)} characters)")


if __name__ == "__main__":
    build(Path(__file__).resolve().parent.parent / "assets" / "ocr_glyphless.ttf")
