"""Live test with the REAL local model (runs only when ai\\llama and ai\\models are installed).

Run:  .venv\\Scripts\\python tests\\test_ai_live.py
Prints what the model answered and how long it took.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def say(msg: str) -> None:
    prefix = "::notice::" if os.environ.get("GITHUB_ACTIONS") else ""
    for line in msg.splitlines() or [""]:
        print(prefix + line, flush=True)


def main() -> int:
    import pymupdf as fitz

    from app.ai import engine as E
    from app.ai import forms as F
    from app.ai import tasks as K
    from app.ai import text as T
    from tests.test_ai import book, flat_form, source_doc

    model = E.get_model()
    if model is None:
        print("No local model installed - live test skipped.")
        return 0
    say(f"Model: {model.name}  ({model.model.name}, threads={model.threads})")
    t0 = time.time()
    model.start()
    say(f"Loaded in {time.time() - t0:.1f}s")
    try:
        ps = T.pages_text(book(), list(range(6)))
        t0 = time.time()
        a = K.answer(model, ps, "What is the interest rate and how many instalments?", K.Job())
        say(f"ANSWER ({time.time() - t0:.1f}s): {a}")
        assert "8.5" in a, a
        t0 = time.time()
        s = K.summarise(model, ps, K.Request("summary", pages=list(range(6)), length="short"), K.Job())
        say(f"SUMMARY ({time.time() - t0:.1f}s): {s}")
        assert len(s) > 40, s
        # long-document path (several parts)
        old = T.chunks
        T.chunks = lambda p, max_tokens=2200: old(p, max_tokens=400)
        try:
            t0 = time.time()
            s2 = K.summarise(model, ps, K.Request("summary", pages=list(range(6)), length="medium"), K.Job())
        finally:
            T.chunks = old
        say(f"SUMMARY in parts ({time.time() - t0:.1f}s): {s2}")
        # form: rules + model
        src = T.pages_text(source_doc(), [0, 1])
        fields = F.detect_fields(flat_form())
        fields.append(F.FormField("x", "Father's name", 0, fitz.Rect(0, 0, 10, 10)))
        fields.append(F.FormField("y", "Business started in year", 0, fitz.Rect(0, 0, 10, 10)))
        t0 = time.time()
        F.find_values(fields, src, model, K.Job())
        say(f"FORM ({time.time() - t0:.1f}s): " + "; ".join(f"{f.label}={f.value!r} [{f.source}]" for f in fields))
        got = {f.label: f.value for f in fields}
        assert got["PAN No"] == "ABCPS1234K" and got["Nominee Name"] == "", got
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            F.fill(flat_form(), fields[:8], str(Path(tmp) / "f.pdf"))
    finally:
        model.stop()
    say("Live AI test: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
