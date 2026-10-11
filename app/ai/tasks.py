"""What the AI Assistant does: summaries and answers about the open PDF.

Every function takes a `Job` (progress messages, streamed text, Stop button).
With a local model the text is written by the model; without one ("quick
mode") the app picks the most relevant sentences from the document itself.
Nothing leaves the computer either way.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from app.ai import text as T
from app.ai.engine import Cancelled, LocalModel

SYSTEM = ("You are the assistant inside BRB PDF, an offline PDF program. You only know the document text "
          "you are given. Never invent facts, names, numbers or dates that are not in the text. Keep numbers, "
          "amounts, dates and names exactly as written. When you use a fact, mention its page like (p. 4). "
          "If the text does not contain the answer, say so plainly.")

LENGTHS = {
    "short": ("a short summary: 2 sentences of overview, then at most 5 bullet points", 350),
    "medium": ("a summary: a short overview paragraph, then 6 to 10 bullet points with the key facts", 700),
    "detailed": ("a detailed summary: an overview paragraph, then the main sections with their key facts "
                 "as bullet points under short headings", 1200),
}


@dataclass
class Job:
    """Progress / streaming / cancel link between the worker thread and the window."""
    progress: callable = lambda msg: None          # status line text
    token: callable = lambda piece: None           # streamed answer text
    cancel: threading.Event = field(default_factory=threading.Event)

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


# ------------------------------------------------------------------ routing
@dataclass
class Request:
    kind: str                     # "summary" | "ask"
    scope: str = "document"       # "document" | "chapter" | "pages" | "page"
    pages: list[int] | None = None
    chapter: str = ""
    length: str = "medium"
    question: str = ""
    instruction: str = ""         # extra wish, e.g. "in Hindi", "as a table"


def route(prompt: str, page_count: int, current_page: int, chapter_list: list[T.Chapter]) -> Request:
    """Understand a typed request like 'summarise chapter 3 in short' or 'what is the interest rate?'."""
    p = prompt.strip()
    low = p.lower()
    if not re.search(r"\b(summar|summer|overview|gist|key points|main points|tl;?dr|brief)", low):
        return Request("ask", question=p)
    req = Request("summary", instruction=p)
    if re.search(r"\b(short|brief|quick|few lines|one paragraph)\b", low):
        req.length = "short"
    elif re.search(r"\b(detail|detailed|long|full|complete)\b", low):
        req.length = "detailed"
    m = re.search(r"\bpages?\s*(\d+)\s*(?:-|to|–|until|through)\s*(\d+)", low)
    m1 = re.search(r"\bpage\s*(\d+)\b", low)
    mc = re.search(r"\b(?:chapter|section|part|ch\.?)\s*([\w ]{1,40}?)(?=$|[,.;]| in | as | with )", low)
    if re.search(r"\b(this|current) page\b", low):
        req.scope, req.pages = "page", [current_page]
    elif m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        req.scope, req.pages = "pages", [i for i in range(a - 1, b) if 0 <= i < page_count]
    elif m1:
        n = int(m1.group(1)) - 1
        req.scope, req.pages = "page", [n] if 0 <= n < page_count else []
    elif mc:
        ch = T.find_chapter(chapter_list, mc.group(0)) or T.find_chapter(chapter_list, mc.group(1))
        if ch is not None:
            req.scope, req.chapter = "chapter", ch.title
            req.pages = list(range(ch.first, ch.last + 1))
    if req.pages is None:
        req.scope, req.pages = "document", list(range(page_count))
    return req


def scope_words(req: Request) -> str:
    if req.scope == "chapter":
        return f"the chapter \"{req.chapter}\""
    if req.scope == "page" and req.pages:
        return f"page {req.pages[0] + 1}"
    if req.scope == "pages" and req.pages:
        return f"pages {req.pages[0] + 1} to {req.pages[-1] + 1}"
    return "the whole document"


def _extra(instruction: str) -> str:
    """Pass on wishes such as 'in Hindi' or 'as a table' from the user's own words."""
    wish = []
    lang = re.search(r"\bin (hindi|bengali|bangla|english)\b", instruction, re.I)
    if lang:
        wish.append(f"Write the answer in {lang.group(1).capitalize()}.")
    if re.search(r"\btable\b", instruction, re.I):
        wish.append("Present the key facts as a simple table.")
    return " ".join(wish)


# ---------------------------------------------------------------- summaries
def summarise(model: LocalModel | None, passages: list[T.Passage], req: Request, job: Job) -> str:
    if not passages:
        return ("There is no text to summarise in " + scope_words(req) + ". If the pages are scanned, run "
                "OCR > Make Searchable PDF first.")
    if model is None:
        return _quick_summary(passages, req)
    how, budget = LENGTHS.get(req.length, LENGTHS["medium"])
    extra = _extra(req.instruction)
    groups = T.chunks(passages, max_tokens=2200)
    if len(groups) == 1:
        job.progress("Writing the summary...")
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Document text ({scope_words(req)}):\n\n{T.with_pages(groups[0])}\n\n"
                                            f"Write {how} of {scope_words(req)}. {extra}"}]
        return model.chat(msgs, max_tokens=budget, on_token=job.token, cancel=job.cancel).strip()

    # long text: summarise each part, then combine the part summaries
    notes: list[str] = []
    for k, g in enumerate(groups, 1):
        job.check()
        job.progress(f"Reading part {k} of {len(groups)} (pages {g[0].page + 1}-{g[-1].page + 1})...")
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Part {k} of {len(groups)} of a document:\n\n{T.with_pages(g)}\n\n"
                                            "List the important facts of this part as 3 to 8 short bullet points. "
                                            "Keep names, dates, amounts and page numbers."}]
        notes.append(f"Part {k} (pages {g[0].page + 1}-{g[-1].page + 1}):\n" +
                     model.chat(msgs, max_tokens=320, cancel=job.cancel).strip())
    # combine (in rounds if the notes are themselves long)
    while T.approx_tokens("\n\n".join(notes)) > 5200 and len(notes) > 1:
        job.check()
        job.progress("Combining the notes...")
        merged = []
        for k in range(0, len(notes), 4):
            part = "\n\n".join(notes[k:k + 4])
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Notes from consecutive parts of a document:\n\n{part}\n\n"
                                                "Merge these notes into at most 10 bullet points. Keep the page "
                                                "numbers."}]
            merged.append(model.chat(msgs, max_tokens=420, cancel=job.cancel).strip())
        notes = merged
    job.check()
    job.progress("Writing the summary...")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Notes taken while reading " + scope_words(req) + ":\n\n" + "\n\n".join(notes) +
                                        f"\n\nFrom these notes, write {how} of {scope_words(req)}. {extra}"}]
    return model.chat(msgs, max_tokens=budget, on_token=job.token, cancel=job.cancel).strip()


def _quick_summary(passages: list[T.Passage], req: Request) -> str:
    n = {"short": 5, "medium": 9, "detailed": 16}.get(req.length, 9)
    picked = T.extractive_summary(passages, n)
    if not picked:
        return "The text could not be summarised (no full sentences were found)."
    lines = [f"Key sentences from {scope_words(req)} (quick mode - no AI model installed):", ""]
    lines += [f"- {s} (p. {p + 1})" for p, s in picked]
    return "\n".join(lines)


# ------------------------------------------------------------------ answers
def answer(model: LocalModel | None, passages: list[T.Passage], question: str, job: Job) -> str:
    if not passages:
        return "This document has no text to search. If it is scanned, run OCR > Make Searchable PDF first."
    total = sum(T.approx_tokens(p.text) for p in passages)
    if model is not None and total <= 4500:
        context = T.with_pages(passages)                     # small document: give it all
    else:
        job.progress("Searching the document...")
        hits = T.Bm25(passages).search(question, top=7 if model is not None else 5)
        if not hits:
            return ("I could not find anything about that in this document. Try other words, or check that the "
                    "pages contain text (scanned pages need OCR first).")
        if model is None:
            lines = ["Most relevant passages (quick mode - no AI model installed):", ""]
            for _, p in hits:
                lines.append(f"p. {p.page + 1}: " + " ".join(p.text.split())[:400])
                lines.append("")
            return "\n".join(lines).strip()
        hits.sort(key=lambda h: (h[1].page, h[1].text))
        context = "\n\n".join(f"[Page {p.page + 1}]\n{p.text}" for _, p in hits)
    job.check()
    job.progress("Thinking...")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Document text:\n\n{context}\n\nQuestion: {question}\n\n"
                                        "Answer from the document text only, briefly, with page numbers. "
                                        "Answer in the language of the question."}]
    return model.chat(msgs, max_tokens=600, on_token=job.token, cancel=job.cancel).strip()
