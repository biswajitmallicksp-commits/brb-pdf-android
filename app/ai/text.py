"""Text helpers for the offline AI features (no model needed).

- pages_text / chapters: what to read (whole document, a chapter from the bookmarks, pages)
- chunks: split long text into pieces a small local model can read
- Bm25: find the passages that best match a question or a form label
- extractive_summary: "quick mode" summary that picks the most important sentences
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import pymupdf as fitz


# ------------------------------------------------------------------ reading
@dataclass
class Passage:
    page: int          # 0-based
    text: str


@dataclass
class Chapter:
    title: str
    first: int         # 0-based, inclusive
    last: int          # 0-based, inclusive
    level: int = 1

    @property
    def label(self) -> str:
        pages = f"p. {self.first + 1}" if self.first == self.last else f"pp. {self.first + 1}-{self.last + 1}"
        return f"{'    ' * (self.level - 1)}{self.title}  ({pages})"


def _clean(text: str) -> str:
    text = text.replace("­", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _layout_text(page: fitz.Page) -> str:
    """Page text line by line, top to bottom; a wide gap between words (table columns,
    'Name: X     PAN: Y') is kept as several spaces so label/value pairs stay apart."""
    ws = page.get_text("words", sort=True)
    rows: list[list] = []
    for w in ws:
        mid = (w[1] + w[3]) / 2
        if rows and abs(((rows[-1][0][1] + rows[-1][0][3]) / 2) - mid) < (w[3] - w[1]) * 0.45:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for r in rows:
        r.sort(key=lambda w: w[0])
        parts = [r[0][4]]
        for a, b in zip(r, r[1:]):
            gap = b[0] - a[2]
            h = max(1.0, a[3] - a[1])
            parts.append("    " if gap > h * 0.9 else " ")
            parts.append(b[4])
        lines.append("".join(parts))
    return "\n".join(lines)


def pages_text(doc: fitz.Document, pages: list[int]) -> list[Passage]:
    """Text of the given pages (in reading order); empty pages are skipped."""
    out = []
    for i in pages:
        if 0 <= i < doc.page_count:
            t = _clean_keep_gaps(_layout_text(doc[i]))
            if t:
                out.append(Passage(i, t))
    return out


def _clean_keep_gaps(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chapters(doc: fitz.Document, max_level: int = 2) -> list[Chapter]:
    """Chapters from the bookmarks (table of contents), each with its page range."""
    toc = [(lvl, title.strip(), page - 1) for lvl, title, page, *_ in doc.get_toc(simple=False)
           if lvl <= max_level and page >= 1 and title.strip()]
    out: list[Chapter] = []
    for k, (lvl, title, first) in enumerate(toc):
        last = doc.page_count - 1
        for lvl2, _t, first2 in toc[k + 1:]:
            if lvl2 <= lvl:
                last = max(first, first2 - 1) if first2 > first else first
                break
        out.append(Chapter(title, first, min(last, doc.page_count - 1), lvl))
    return out


def find_chapter(chs: list[Chapter], words: str) -> Chapter | None:
    """'chapter 3', '3', 'interest rates' -> the best matching chapter."""
    w = words.strip().lower()
    if not w or not chs:
        return None
    m = re.fullmatch(r"(?:chapter|ch\.?|section|part)?\s*(\d+)", w)
    if m:
        n = int(m.group(1))
        numbered = [c for c in chs if re.match(rf"\s*(chapter|section|part)?\s*{n}\b", c.title, re.I)]
        if numbered:
            return numbered[0]
        top = [c for c in chs if c.level == 1]
        if 1 <= n <= len(top):
            return top[n - 1]
    best, score = None, 0.0
    qw = set(re.findall(r"\w+", w))
    for c in chs:
        tw = set(re.findall(r"\w+", c.title.lower()))
        s = len(qw & tw) / max(1, len(qw))
        if s > score:
            best, score = c, s
    return best if score >= 0.5 else None


# ------------------------------------------------------------------ chunks
def approx_tokens(text: str) -> int:
    """Rough token count (about 4 characters per token for English; more for Indic scripts)."""
    indic = sum(1 for ch in text if "ऀ" <= ch <= "෿")
    return int((len(text) - indic) / 3.8 + indic / 1.5) + 1


def chunks(passages: list[Passage], max_tokens: int = 2200) -> list[list[Passage]]:
    """Group consecutive pages into pieces of at most `max_tokens`; very long pages are cut."""
    out: list[list[Passage]] = []
    cur: list[Passage] = []
    size = 0
    for p in passages:
        pieces = [p]
        if approx_tokens(p.text) > max_tokens:
            pieces = []
            paras = re.split(r"\n\s*\n|\n", p.text)
            buf = ""
            for para in paras:
                if buf and approx_tokens(buf + "\n" + para) > max_tokens:
                    pieces.append(Passage(p.page, buf))
                    buf = para
                else:
                    buf = (buf + "\n" + para) if buf else para
                while approx_tokens(buf) > max_tokens:            # one enormous paragraph
                    cut = int(max_tokens * 3.5)
                    pieces.append(Passage(p.page, buf[:cut]))
                    buf = buf[cut:]
            if buf:
                pieces.append(Passage(p.page, buf))
        for piece in pieces:
            t = approx_tokens(piece.text)
            if cur and size + t > max_tokens:
                out.append(cur)
                cur, size = [], 0
            cur.append(piece)
            size += t
    if cur:
        out.append(cur)
    return out


def with_pages(group: list[Passage]) -> str:
    return "\n\n".join(f"[Page {p.page + 1}]\n{p.text}" for p in group)


# ------------------------------------------------------------------ search
_WORD = re.compile(r"[\wऀ-෿]+", re.UNICODE)
STOP = set("""a an the and or of to in on for by with at from as is are was were be been being this that these
those it its into than then there their they them he she his her you your we our i me my not no but if so
do does did done have has had will would shall should can could may might must also any all each per
""".split())


def words(text: str) -> list[str]:
    return [w for w in (m.group(0).lower() for m in _WORD.finditer(text)) if w not in STOP and len(w) > 1]


class Bm25:
    """Classic BM25 ranking over small passages (sentences grouped per page)."""

    def __init__(self, passages: list[Passage], k1: float = 1.4, b: float = 0.75):
        self.items: list[Passage] = []
        for p in passages:
            # windows of ~6 lines so answers point at a precise place
            lines = [ln for ln in p.text.split("\n") if ln.strip()]
            for k in range(0, len(lines), 4):
                self.items.append(Passage(p.page, "\n".join(lines[k:k + 6])))
        self.docs = [words(p.text) for p in self.items]
        self.k1, self.b = k1, b
        self.avg = sum(len(d) for d in self.docs) / max(1, len(self.docs))
        df: Counter = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def search(self, query: str, top: int = 6) -> list[tuple[float, Passage]]:
        q = words(query)
        scored = []
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i])
            s = 0.0
            for w in q:
                f = tf.get(w)
                if f:
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / max(1, self.avg)))
            if s > 0:
                scored.append((s, self.items[i]))
        scored.sort(key=lambda x: -x[0])
        # avoid near-duplicate windows from the same page
        out, seen = [], set()
        for s, p in scored:
            key = (p.page, p.text[:60])
            if key in seen:
                continue
            seen.add(key)
            out.append((s, p))
            if len(out) >= top:
                break
        return out


# --------------------------------------------------------------- summaries
_SENT = re.compile(r"(?<=[.!?।])\s+|\n(?=[A-Z0-9ऀ-෿])")


def sentences(text: str) -> list[str]:
    out = []
    for s in _SENT.split(text.replace("\n", " \n")):
        s = " ".join(s.split())
        if 25 <= len(s) <= 500 and sum(ch.isalpha() for ch in s) > len(s) * 0.5:
            out.append(s)
    return out


def extractive_summary(passages: list[Passage], n_sentences: int = 8) -> list[tuple[int, str]]:
    """Quick summary without a model: the sentences that carry the document's most frequent
    important words, in their original order. Returns (page, sentence)."""
    sents: list[tuple[int, str]] = []
    for p in passages:
        sents += [(p.page, s) for s in sentences(p.text)]
    if not sents:
        return []
    freq = Counter(w for _, s in sents for w in words(s))
    if not freq:
        return sents[:n_sentences]
    top = freq.most_common(1)[0][1]
    scores = []
    for k, (_, s) in enumerate(sents):
        ws = words(s)
        if not ws:
            continue
        score = sum(freq[w] / top for w in ws) / (len(ws) ** 0.6)
        if k < 3:
            score *= 1.15                         # opening lines usually say what the document is
        scores.append((score, k))
    chosen = sorted(k for _, k in sorted(scores, reverse=True)[:n_sentences])
    # drop near-duplicates
    out, seen = [], set()
    for k in chosen:
        key = " ".join(words(sents[k][1])[:8])
        if key not in seen:
            seen.add(key)
            out.append(sents[k])
    return out
