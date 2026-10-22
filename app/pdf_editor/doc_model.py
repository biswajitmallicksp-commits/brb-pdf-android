"""Turn PDF pages into an editable 'Word-like' document model.

Works with normal text PDFs and with OCR results (the invisible text layer).
Each page becomes a list of paragraphs that keep the look of the page:

  * position: left indent and the space above each line;
  * table rows: a line with wide gaps (date | description | amount) keeps its
    pieces at their original x positions (tab stops);
  * text: font size, bold, italic, colour, and a font family (sans / serif / mono);
  * running text: consecutive lines of one paragraph are joined so the text
    re-flows when you edit it;
  * centred titles stay centred.

Coordinates are points in the page's VISIBLE space (rotation applied).
Nothing here touches files: the model lives in memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf as fitz

BOLD, ITALIC, MONO, SERIF = 16, 2, 8, 4


@dataclass
class Run:
    text: str
    size: float
    bold: bool = False
    italic: bool = False
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    family: str = "sans"            # "sans" | "serif" | "mono"


@dataclass
class Seg:
    x: float                        # left edge on the page (points)
    runs: list[Run] = field(default_factory=list)
    x1: float = 0.0                 # right edge

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @property
    def size(self) -> float:
        sizes = [r.size for r in self.runs if r.text.strip()]
        return max(set(sizes), key=sizes.count) if sizes else (self.runs[0].size if self.runs else 10.0)


@dataclass
class Para:
    segs: list[Seg]
    top: float                      # top of the first line on the page
    bottom: float
    baseline: float
    align: str = "left"            # "left" | "center"
    space_before: float = 0.0      # points of empty space above (set by build_pages)

    @property
    def is_row(self) -> bool:
        return len(self.segs) > 1

    @property
    def x(self) -> float:
        return self.segs[0].x

    @property
    def text(self) -> str:
        return "\t".join(s.text for s in self.segs)


@dataclass
class PageModel:
    index: int
    width: float
    height: float
    paras: list[Para] = field(default_factory=list)
    has_text: bool = True


def _family(font: str, flags: int) -> str:
    f = (font or "").lower()
    if flags & MONO or "courier" in f or "mono" in f or "consol" in f:
        return "mono"
    if flags & SERIF or any(k in f for k in ("times", "roman", "georgia", "garamond", "cambria", "book")) \
            or ("serif" in f and "sans" not in f):
        return "serif"
    return "sans"


def _rgb(color: int) -> tuple[float, float, float]:
    return ((color >> 16 & 255) / 255, (color >> 8 & 255) / 255, (color & 255) / 255)


def _is_ocr_font(font: str) -> bool:
    return "glyphless" in (font or "").lower()


def _row_segments(spans_chars: list[tuple[dict, dict, fitz.Rect]], gap_factor: float) -> list[Seg]:
    """Cut a visual line into pieces at wide gaps; each piece keeps its styled runs."""
    segs: list[Seg] = []
    cur: Seg | None = None
    last_right = None
    for span, ch, box in spans_chars:
        c = ch["c"]
        size = span["size"]
        if cur is not None and c.strip() and last_right is not None and box.x0 - last_right > gap_factor * size:
            segs.append(cur)
            cur = None
        if cur is None:
            if not c.strip():
                continue
            cur = Seg(box.x0)
        bold = bool(span["flags"] & BOLD) or any(k in span["font"].lower() for k in ("bold", "black", "heavy"))
        italic = bool(span["flags"] & ITALIC) or any(k in span["font"].lower() for k in ("italic", "oblique"))
        fam = "sans" if _is_ocr_font(span["font"]) else _family(span["font"], span["flags"])
        color = (0.0, 0.0, 0.0) if _is_ocr_font(span["font"]) else _rgb(span["color"])
        r = cur.runs[-1] if cur.runs else None
        if r is not None and (r.bold, r.italic, r.family, r.color) == (bold, italic, fam, color) \
                and abs(r.size - size) < 0.6:
            r.text += c
        else:
            cur.runs.append(Run(c, round(size * 2) / 2, bold, italic, color, fam))
        if c.strip():
            last_right = box.x1
            cur.x1 = max(cur.x1, box.x1)
    if cur is not None and cur.runs:
        segs.append(cur)
    for s in segs:                              # no trailing spaces
        while s.runs and not s.runs[-1].text.strip():
            s.runs.pop()
        if s.runs:
            s.runs[-1].text = s.runs[-1].text.rstrip()
    return [s for s in segs if s.text.strip()]


def page_model(page: fitz.Page, gap_factor: float = 1.6) -> PageModel:
    """Paragraphs of one page (see module docstring)."""
    vis = page.rotation_matrix
    rot = fitz.Matrix(vis)
    rot.e = rot.f = 0
    data = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP)
    lines = []              # (baseline, top, bottom, [(span, ch, box)])
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            d = fitz.Point(line.get("dir", (1, 0))) * rot
            if abs(d.y) > 0.05 or d.x <= 0:
                continue                                   # sideways text is left out
            items = []
            base = None
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    box = fitz.Rect(ch["bbox"]) * vis
                    box.normalize()
                    items.append((span, ch, box))
                    if base is None and ch["c"].strip():
                        base = (fitz.Point(ch["origin"]) * vis).y
            ink = [b for _s, c, b in items if c["c"].strip()]
            if not ink or base is None:
                continue
            lines.append((base, min(b.y0 for b in ink), max(b.y1 for b in ink), items))
    pm = PageModel(page.number, page.rect.width, page.rect.height)
    if not lines:
        pm.has_text = False
        return pm
    # merge pieces that sit on the same baseline (table columns come as separate lines)
    lines.sort(key=lambda t: (t[0], min(b.x0 for *_r, b in t[3])))
    rows: list[list] = []
    for ln in lines:
        h = ln[2] - ln[1]
        if rows and abs(rows[-1][0] - ln[0]) < max(1.5, 0.35 * h):
            rows[-1][3] = rows[-1][3] + ln[3]
            rows[-1][1] = min(rows[-1][1], ln[1])
            rows[-1][2] = max(rows[-1][2], ln[2])
        else:
            rows.append(list(ln))
    paras: list[Para] = []
    for base, top, bottom, items in rows:
        items.sort(key=lambda t: t[2].x0)
        segs = _row_segments(items, gap_factor)
        if segs:
            paras.append(Para(segs, top, bottom, base))
    _centre_titles(paras, pm.width)
    pm.paras = _join_lines(paras, pm.width)
    return pm


def _centre_titles(paras: list[Para], width: float) -> None:
    for p in paras:
        if p.is_row:
            continue
        s = p.segs[0]
        mid = (s.x + s.x1) / 2
        if abs(mid - width / 2) < 20 and s.x > width * 0.18:
            p.align = "center"


def _join_lines(paras: list[Para], width: float) -> list[Para]:
    """Join the lines of running text into one paragraph (so it re-flows when edited)."""
    if not paras:
        return paras
    right = max(p.segs[-1].x1 for p in paras)
    out: list[Para] = [paras[0]]
    for p in paras[1:]:
        prev = out[-1]
        if prev.is_row or p.is_row or prev.align != "left" or p.align != "left":
            out.append(p)
            continue
        a, b = prev.segs[0], p.segs[0]
        size = a.size
        line_gap = p.top - prev.bottom
        prev_last_line_end = getattr(prev, "_last_x1", a.x1)
        same_column = abs(b.x - a.x) < 4 or (b.x < a.x and a.x - b.x < 25)      # first-line indent allowed
        if (same_column and abs(b.size - size) < 0.6 and line_gap < 0.65 * size
                and prev_last_line_end > right - 0.22 * (right - a.x) and a.text.rstrip()[-1:] not in ":"):
            # same paragraph: append with a space
            joined = Seg(a.x, a.runs + [Run(" ", b.runs[0].size, b.runs[0].bold, b.runs[0].italic,
                                             b.runs[0].color, b.runs[0].family)] + b.runs, b.x1)
            out[-1] = Para([joined], prev.top, p.bottom, prev.baseline, "left")
            out[-1]._last_x1 = b.x1                                   # type: ignore[attr-defined]
        else:
            out.append(p)
    return out


def build_pages(doc: fitz.Document, pages: list[int] | None = None) -> list[PageModel]:
    """Page models for `pages` (default: all), with the space above each paragraph filled in."""
    out = []
    for i in (range(doc.page_count) if pages is None else pages):
        pm = page_model(doc[i])
        prev_bottom = None
        for p in pm.paras:
            top_margin = 36.0
            p.space_before = max(0.0, p.top - (prev_bottom if prev_bottom is not None else top_margin))
            prev_bottom = p.bottom
        out.append(pm)
    return out
