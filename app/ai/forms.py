"""Fill a form with information found in the open PDF.

1. detect_fields(form)   - the blanks of the form:
      * real form fields (fillable PDF), or
      * printed blanks: "Name: ________", "Date of birth ..........", "PAN:" followed by empty space
2. find_values(fields, source) - look for each value in the source document:
      * "Label: value" lines and table rows whose label matches the field
      * well-known patterns (PAN, IFSC, GSTIN, e-mail, mobile, PIN code, dates, amounts, account numbers)
      * the local AI model (if installed) for everything still missing
   The user checks every value before anything is written.
3. fill(form, fields, out_path) - writes the values into a NEW file; the form itself is never changed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pymupdf as fitz

from app.ai import text as T
from app.ai.engine import LocalModel


@dataclass
class FormField:
    key: str
    label: str
    page: int
    rect: fitz.Rect                 # where the value goes (unrotated page space)
    kind: str = "flat"              # "widget" | "flat"
    widget_name: str = ""
    widget_xref: int = 0
    value: str = ""
    source: str = ""                # how the value was found: "label", "pattern", "AI", "" (not found)
    source_page: int | None = None  # 0-based page of the source document

    @property
    def found(self) -> bool:
        return bool(self.value.strip())


# ================================================================ detection
_BLANK = re.compile(r"^[_\.…\-]{3,}$|^_{2,}.*_{2,}$")
_LABEL_END = re.compile(r"[:：]$")


def _humanize(name: str) -> str:
    n = re.sub(r"[_\.\-]+", " ", name)
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)
    n = re.sub(r"\[\d+\]", "", n)
    return " ".join(n.split()).strip().capitalize()


def _clean_label(words: list[str]) -> str:
    label = " ".join(words).strip()
    label = re.sub(r"^[\d\.\)\(]+\s*", "", label)                 # "3. Name" -> "Name"
    label = re.sub(r"[:：\-_\.…\s]+$", "", label)
    return label.strip()


def _label_near(page: fitz.Page, rect: fitz.Rect, words: list) -> str:
    """Printed text just left of (or just above) a form field."""
    left = [w for w in words if abs((w[1] + w[3]) / 2 - (rect.y0 + rect.y1) / 2) < max(6, rect.height * 0.6)
            and w[2] <= rect.x0 + 2 and rect.x0 - w[2] < 220]
    left.sort(key=lambda w: w[0])
    if left:
        # the words of the closest phrase (stop at a big gap)
        phrase = [left[-1]]
        for w in reversed(left[:-1]):
            if phrase[0][0] - w[2] > 18:
                break
            phrase.insert(0, w)
        lab = _clean_label([w[4] for w in phrase])
        if lab:
            return lab
    above = [w for w in words if 0 < rect.y0 - w[3] < 16 and w[0] < rect.x1 and w[2] > rect.x0 - 10]
    above.sort(key=lambda w: w[0])
    return _clean_label([w[4] for w in above])


def detect_fields(doc: fitz.Document) -> list[FormField]:
    fields: list[FormField] = []
    for page in doc:
        words = page.get_text("words")
        widgets = [w for w in page.widgets() if w.field_type in (fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_COMBOBOX)]
        for w in widgets:
            if w.field_flags & 1:                         # read-only
                continue
            label = (w.field_label or "").strip() or _label_near(page, w.rect, words) or _humanize(w.field_name or "")
            fields.append(FormField(f"w{w.xref}", label, page.number, fitz.Rect(w.rect), "widget",
                                    w.field_name or "", w.xref, (w.field_value or "").strip()))
        if widgets:
            continue                                      # a fillable page: its printed lines are labels
        fields += _flat_fields(page, words)
    # identical labels on the same page: number them so they stay apart
    seen: dict[str, int] = {}
    for f in fields:
        k = f.label.lower()
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1:
            f.label = f"{f.label} ({seen[k]})"
    return [f for f in fields if f.label]


def _flat_fields(page: fitz.Page, words: list) -> list[FormField]:
    """Printed blanks: 'Label ____', 'Label: .....', 'Label:' followed by empty space."""
    out: list[FormField] = []
    lines: dict[tuple, list] = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)
    right_margin = page.rect.x1 - 36
    for (_b, _l), ws in sorted(lines.items(), key=lambda kv: (round(kv[1][0][1]), kv[1][0][0])):
        ws.sort(key=lambda w: w[0])
        label_words: list = []
        k = 0
        while k < len(ws):
            w = ws[k]
            txt = w[4]
            # "Name:_____" glued together
            glued = re.match(r"^(.*?[^_\.])([_\.…]{3,})$", txt)
            if _BLANK.match(txt) or glued:
                if glued:
                    label_words.append(glued.group(1))
                    bx0 = w[0] + (w[2] - w[0]) * len(glued.group(1)) / max(1, len(txt))
                else:
                    bx0 = w[0]
                # merge neighbouring blank pieces
                bx1 = w[2]
                while k + 1 < len(ws) and _BLANK.match(ws[k + 1][4]) and ws[k + 1][0] - bx1 < 8:
                    k += 1
                    bx1 = ws[k][2]
                label = _clean_label([x[4] if isinstance(x, tuple) else x for x in label_words])
                if label:
                    h = w[3] - w[1]
                    out.append(FormField(f"p{page.number}_{len(out)}", label, page.number,
                                         fitz.Rect(bx0 + 2, w[3] - max(h, 11) * 1.25, bx1, w[3] + 1.5)))
                label_words = []
            elif _LABEL_END.search(txt):
                label_words.append(w)
                nxt = ws[k + 1] if k + 1 < len(ws) else None
                gap_end = nxt[0] if nxt is not None else right_margin
                if gap_end - w[2] > 45 and (nxt is None or not _BLANK.match(nxt[4])):
                    label = _clean_label([x[4] for x in label_words])
                    if label and len(label) <= 60:
                        h = w[3] - w[1]
                        out.append(FormField(f"p{page.number}_{len(out)}", label, page.number,
                                             fitz.Rect(w[2] + 6, w[1] - 1, min(gap_end - 6, w[2] + 260), w[3] + 1)))
                    label_words = []
            else:
                if label_words and isinstance(label_words[-1], tuple) and w[0] - label_words[-1][2] > 30:
                    label_words = []                       # a far-away word starts a new label
                label_words.append(w)
            k += 1
    return out


# ================================================================== values
SYNONYMS = {
    "name": ["name", "full name", "applicant name", "name of applicant", "customer name", "account holder",
             "account name", "borrower name", "name of the applicant"],
    "father": ["father name", "father's name", "fathers name", "s/o", "son of", "father / husband name"],
    "dob": ["date of birth", "dob", "birth date", "d.o.b"],
    "pan": ["pan", "pan no", "pan number", "permanent account number"],
    "aadhaar": ["aadhaar", "aadhar", "aadhaar no", "aadhaar number", "uid"],
    "mobile": ["mobile", "mobile no", "mobile number", "phone", "phone no", "contact no", "contact number", "tel"],
    "email": ["email", "e-mail", "email id", "mail id", "email address"],
    "account": ["account no", "account number", "a/c no", "a/c number", "acct no", "bank account number", "ac no"],
    "ifsc": ["ifsc", "ifsc code", "ifs code"],
    "bank": ["bank name", "name of bank", "bank", "branch"],
    "address": ["address", "residential address", "permanent address", "correspondence address", "office address"],
    "pin": ["pin", "pin code", "pincode", "postal code", "zip"],
    "gstin": ["gstin", "gst no", "gst number", "gst"],
    "amount": ["loan amount", "amount", "amount required", "income", "monthly income", "annual income", "salary"],
    "date": ["date", "dated"],
}

_KNOWN_LABEL = re.compile(
    r"(?i)(?<![\w/])(" + "|".join(sorted({re.escape(n) for ns in SYNONYMS.values() for n in ns if len(n) > 2},
                                         key=len, reverse=True)) + r")\s*(?:no\.?|number)?\s*[:：]\s*")

PATTERNS = {
    "pan": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    "ifsc": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    "gstin": r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b",
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "mobile": r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",
    "aadhaar": r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)",
    "pin": r"(?<!\d)[1-9]\d{5}(?!\d)",
    "dob": r"\b\d{1,2}[-/.](?:\d{1,2}|[A-Za-z]{3})[-/.]\d{2,4}\b",
    "date": r"\b\d{1,2}[-/.](?:\d{1,2}|[A-Za-z]{3})[-/.]\d{2,4}\b",
    "account": r"(?<![\d-])\d{9,18}(?![\d-])",
}


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9/'ऀ-෿ ]+", " ", s)
    return " ".join(s.split())


GENERIC = {"no", "number", "of", "the", "full", "applicant", "applicant's", "applicants", "customer", "customer's",
            "borrower", "borrower's", "your", "my", "in", "words", "figures", "dd", "mm", "yyyy", "id", "code",
            "details", "current", "present", "registered", "s", "rs", "inr", "for", "correspondence", "residential",
            "permanent", "communication", "with", "date", "self", "personal"}


def concept(label: str) -> str | None:
    """Which kind of information a label asks for ('Applicant's Name' -> 'name').

    Labels about SOMEONE ELSE ('Nominee Name', 'Guarantor PAN', 'Father's Mobile') get no concept,
    so the applicant's own details are never copied into them."""
    n = _norm(label)
    best, best_len, best_name = None, 0, ""
    for key, names in SYNONYMS.items():
        for name in names:
            nn = _norm(name)
            if (n == nn or re.search(rf"(^| ){re.escape(nn)}($| )", n)) and len(nn) > best_len:
                best, best_len, best_name = key, len(nn), nn
    if best is None:
        return None
    rest = re.sub(rf"(^| ){re.escape(best_name)}($| )", " ", n, count=1).split()
    if any(w not in GENERIC and w not in T.STOP and not w.isdigit() for w in rest):
        return None
    return best


def _label_matches(field_label: str, text_label: str) -> float:
    a, b = _norm(field_label), _norm(text_label)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ca, cb = concept(field_label), concept(text_label)
    if ca and ca == cb:
        return 0.9
    wa, wb = set(a.split()) - T.STOP, set(b.split()) - T.STOP
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _pairs(passages: list[T.Passage]) -> list[tuple[str, str, int]]:
    """'Label: value' pairs and two-column table rows of the source document."""
    out = []
    for p in passages:
        for line in p.text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # several pairs on one line: "Name: A B   PAN: ABCDE1234F"
            for m in re.finditer(r"([A-Za-z][A-Za-z0-9 /'.()&-]{1,45}?)\s*[:：]\s*(.+?)(?=\s{2,}[A-Za-z][\w /'.()-]{1,40}[:：]|$)",
                                 line):
                lab, val = m.group(1).strip(), m.group(2)
                # a known label hidden inside the value: "ABCDE1234F Mobile: 98..." -> two pairs
                while True:
                    k = _KNOWN_LABEL.search(val)
                    if not k or k.start() == 0:
                        break
                    out.append((lab, val[:k.start()].strip(" .,;"), p.page))
                    lab, val = k.group(1), val[k.end():]
                out.append((lab, val.strip(" .,;"), p.page))
            cells = re.split(r"\s{3,}|\t", line)
            if len(cells) == 2 and ":" not in line:
                out.append((cells[0].strip(), cells[1].strip(" .,;"), p.page))
    return out


def find_values(fields: list[FormField], passages: list[T.Passage], model: LocalModel | None = None,
                job=None) -> list[FormField]:
    """Fill FormField.value / source / source_page from the source document (the user reviews them)."""
    pairs = _pairs(passages)
    alltext = [(p.page, p.text) for p in passages]
    for f in fields:
        if f.found and f.kind == "widget":
            f.source = "already filled"
            continue
        # 1. a matching "Label: value" in the document
        best = None
        for lab, val, page in pairs:
            s = _label_matches(f.label, lab)
            if s >= 0.6 and val and (best is None or s > best[0]):
                best = (s, val, page)
        if best is not None:
            val = best[1]
            c = concept(f.label)
            if c in PATTERNS:                          # keep only the part that looks right
                m = re.search(PATTERNS[c], val, re.I if c == "email" else 0)
                if m:
                    val = m.group(0)
                elif c in ("pan", "ifsc", "gstin", "email", "mobile", "pin", "aadhaar"):
                    val = ""
            if val:
                f.value, f.source, f.source_page = val[:200], "label", best[2]
                continue
        # 2. a well-known pattern anywhere in the document (only when it is unique)
        c = concept(f.label)
        if c in ("pan", "ifsc", "gstin", "email", "aadhaar") and c in PATTERNS:
            found = {}
            for page, t in alltext:
                for m in re.finditer(PATTERNS[c], t, re.I if c == "email" else 0):
                    found.setdefault(m.group(0), page)
            if len(found) == 1:
                (val, page), = found.items()
                f.value, f.source, f.source_page = val, "pattern", page
    # 3. the local AI model for the rest
    missing = [f for f in fields if not f.found]
    if model is not None and missing:
        _ask_model(missing, passages, model, job)
    return fields


def _ask_model(fields: list[FormField], passages: list[T.Passage], model: LocalModel, job) -> None:
    index = T.Bm25(passages)
    for k in range(0, len(fields), 10):
        batch = fields[k:k + 10]
        if job is not None:
            job.check()
            job.progress(f"Looking for {', '.join(f.label for f in batch[:3])}{'...' if len(batch) > 3 else ''}")
        ctx, used = [], set()
        for f in batch:
            for _, p in index.search(f.label + " " + (concept(f.label) or ""), top=3):
                key = (p.page, p.text[:50])
                if key not in used:
                    used.add(key)
                    ctx.append(p)
        ctx.sort(key=lambda p: p.page)
        context = "\n\n".join(f"[Page {p.page + 1}]\n{p.text}" for p in ctx)
        while T.approx_tokens(context) > 5000 and ctx:
            ctx.pop()
            context = "\n\n".join(f"[Page {p.page + 1}]\n{p.text}" for p in ctx)
        if not context:
            continue
        labels = [f.label for f in batch]
        msgs = [{"role": "system", "content": "You extract information for a form from a document. Copy each value "
                                              "exactly as it is written in the document. If a value is not in the "
                                              "document, use an empty string. Never guess. Reply with JSON only."},
                {"role": "user", "content": f"Document text:\n\n{context}\n\nForm fields: {json.dumps(labels)}\n\n"
                                            "Reply with one JSON object whose keys are exactly these field names "
                                            "and whose values are the values from the document (or \"\")."}]
        reply = model.chat(msgs, max_tokens=500, temperature=0.0, cancel=job.cancel if job else None, json_mode=True)
        data = _parse_json(reply)
        for f in batch:
            val = str(data.get(f.label, "") or "").strip()
            if not val or val.lower() in ("n/a", "na", "none", "not found", "not mentioned", "unknown", "-"):
                continue
            page = _where(val, passages)
            if page is None:                           # the model must copy from the document
                continue
            f.value, f.source, f.source_page = val[:200], "AI", page


def _parse_json(reply: str) -> dict:
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _where(value: str, passages: list[T.Passage]) -> int | None:
    """Page where a value appears (spaces ignored), or None if it is not in the document."""
    v = re.sub(r"\s+", "", value).lower()
    if len(v) < 2:
        return None
    for p in passages:
        if v in re.sub(r"\s+", "", p.text).lower():
            return p.page
    # long free text (addresses): accept when most words are there
    ws = T.words(value)
    if len(ws) >= 3:
        for p in passages:
            pw = set(T.words(p.text))
            if sum(1 for w in ws if w in pw) / len(ws) >= 0.8:
                return p.page
    return None


# ==================================================================== fill
def fill(doc: fitz.Document, fields: list[FormField], out_path: str) -> int:
    """Write the values into the form and save it as a NEW file. Returns the number of fields written."""
    from app.pdf_editor import content

    n = 0
    for f in fields:
        value = f.value.strip()
        if not value:
            continue
        page = doc[f.page]
        if f.kind == "widget":
            for w in page.widgets():
                if w.xref == f.widget_xref:
                    w.field_value = value
                    w.update()
                    n += 1
                    break
        else:
            r = fitz.Rect(f.rect)
            size = max(7.0, min(11.0, r.height * 0.75))
            # room above a printed line for the letters
            box = fitz.Rect(r.x0, r.y1 - size * 1.6, max(r.x1, r.x0 + 40), r.y1 + size * 0.6)
            content.add_text(page, box, value, content.TextStyle("sans", size, (0.05, 0.1, 0.45)), single_line=True)
            n += 1
    doc.save(out_path, garbage=3, deflate=True)
    return n
