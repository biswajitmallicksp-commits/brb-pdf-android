"""Fonts used when writing new text into a PDF.

The application ships no fonts of its own for visible text. It uses the fonts
that are already installed on the computer (on Windows: Arial, Times New Roman,
Courier New, Calibri, and Nirmala UI for Bengali / Hindi). Only the characters
used are embedded in the PDF.

If none of those files exist, the PDF standard fonts (Helvetica, Times,
Courier) are used; they cover English/Latin text only.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

INDIC_RANGES = ((0x0900, 0x097F), (0x0980, 0x09FF), (0x0A00, 0x0DFF), (0xA8E0, 0xA8FF))


def needs_indic_font(text: str) -> bool:
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in INDIC_RANGES)


@dataclass
class FontFamily:
    key: str                    # stable id, saved in settings
    label: str                  # shown to the user
    files: dict = field(default_factory=dict)   # 'regular'/'bold'/'italic'/'bolditalic' -> path
    base14: str = ""            # fallback PDF standard font family: helv / tiro / cour
    indic: bool = False         # covers Bengali + Devanagari

    @property
    def available(self) -> bool:
        # sans / serif / mono always exist (PDF standard fonts); others need their font file
        return bool(self.files.get("regular")) or self.key in ("sans", "serif", "mono")

    def file_for(self, bold: bool, italic: bool) -> str | None:
        style = ("bold" if bold else "") + ("italic" if italic else "") or "regular"
        return self.files.get(style) or self.files.get("bold" if bold else "regular") or self.files.get("regular")


def _font_dirs() -> list[Path]:
    dirs = []
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(Path(windir) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        for d in ("/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
                  "/Library/Fonts", "/System/Library/Fonts"):
            dirs.append(Path(d))
    return [d for d in dirs if d.is_dir()]


def _find(names: list[str]) -> str | None:
    lower = [n.lower() for n in names]
    for d in _font_dirs():
        try:
            for path in d.rglob("*"):
                if path.name.lower() in lower:
                    return str(path)
        except OSError:
            continue
    return None


# candidates: (key, label, base14, indic, {style: [file names]})
_CANDIDATES = [
    ("sans", "Arial / Sans-serif", "helv", False, {
        "regular": ["arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf", "FreeSans.ttf"],
        "bold": ["arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf", "FreeSansBold.ttf"],
        "italic": ["ariali.ttf", "LiberationSans-Italic.ttf", "DejaVuSans-Oblique.ttf", "FreeSansOblique.ttf"],
        "bolditalic": ["arialbi.ttf", "LiberationSans-BoldItalic.ttf", "DejaVuSans-BoldOblique.ttf",
                       "FreeSansBoldOblique.ttf"]}),
    ("serif", "Times New Roman / Serif", "tiro", False, {
        "regular": ["times.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf", "FreeSerif.ttf"],
        "bold": ["timesbd.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf", "FreeSerifBold.ttf"],
        "italic": ["timesi.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif-Italic.ttf", "FreeSerifItalic.ttf"],
        "bolditalic": ["timesbi.ttf", "LiberationSerif-BoldItalic.ttf", "FreeSerifBoldItalic.ttf"]}),
    ("mono", "Courier New / Monospace", "cour", False, {
        "regular": ["cour.ttf", "LiberationMono-Regular.ttf", "DejaVuSansMono.ttf", "FreeMono.ttf"],
        "bold": ["courbd.ttf", "LiberationMono-Bold.ttf", "DejaVuSansMono-Bold.ttf", "FreeMonoBold.ttf"]}),
    ("calibri", "Calibri", "helv", False, {
        "regular": ["calibri.ttf"], "bold": ["calibrib.ttf"], "italic": ["calibrii.ttf"],
        "bolditalic": ["calibriz.ttf"]}),
    ("indic", "Nirmala UI (Bengali, Hindi, English)", "", True, {
        "regular": ["Nirmala.ttf", "Nirmala.ttc", "NirmalaUI.ttf", "FreeSans.ttf"],
        "bold": ["NirmalaB.ttf", "NirmalaUI-Bold.ttf", "FreeSansBold.ttf"]}),
]


@lru_cache(maxsize=1)
def font_families() -> tuple[FontFamily, ...]:
    fams = []
    for key, label, base14, indic, styles in _CANDIDATES:
        files = {style: _find(names) for style, names in styles.items()}
        files = {k: v for k, v in files.items() if v}
        fam = FontFamily(key, label, files, base14, indic)
        if fam.available:
            fams.append(fam)
    return tuple(fams)


def family(key: str) -> FontFamily:
    for f in font_families():
        if f.key == key:
            return f
    return font_families()[0]


def indic_family() -> FontFamily | None:
    for f in font_families():
        if f.indic:
            return f
    return None


def guess_family(font_name: str, flags: int = 0) -> str:
    """Pick the closest family for text that is being edited, from its PDF font name."""
    n = (font_name or "").lower()
    if "courier" in n or "mono" in n or flags & 8:
        return "mono"
    if "times" in n or "serif" in n and "sans" not in n or "roman" in n or "georgia" in n or flags & 4:
        return "serif"
    if "calibri" in n and any(f.key == "calibri" for f in font_families()):
        return "calibri"
    return "sans"


def style_from_font(font_name: str, flags: int = 0) -> tuple[bool, bool]:
    n = (font_name or "").lower()
    bold = "bold" in n or "black" in n or "heavy" in n or bool(flags & 16)
    italic = "italic" in n or "oblique" in n or bool(flags & 2)
    return bold, italic
