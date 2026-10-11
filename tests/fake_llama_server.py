"""A stand-in for llama-server used by the tests (no real model needed).

It speaks the same HTTP API (/health, streaming /v1/chat/completions) and gives
predictable answers:
  * form requests ("Form fields: [...]")  -> JSON with values copied from "Label: value" lines
  * everything else                         -> "SUMMARY:" / "ANSWER:" + the first words of the text, with a page number
"""
from __future__ import annotations

import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def reply_for(messages: list[dict]) -> str:
    user = messages[-1]["content"]
    m = re.search(r"Form fields: (\[.*?\])\n", user)
    if m:
        labels = json.loads(m.group(1))
        out = {}
        for lab in labels:
            key = lab.split("(")[0].strip().lower()
            mm = re.search(rf"(?im)^.*{re.escape(key.split()[0])}[^:\n]*:\s*(.+?)\s*$", user)
            out[lab] = mm.group(1) if mm else ""
        return json.dumps(out)
    page = re.search(r"\[Page (\d+)\]", user)
    p = f" (p. {page.group(1)})" if page else ""
    if "Question:" in user:
        q = user.split("Question:", 1)[1].split("\n")[0].strip()
        return f"ANSWER to '{q}': found in the document{p}."
    if "List the important facts" in user:
        return f"- fact from this part{p}"
    if "Merge these notes" in user:
        return f"- merged facts{p}"
    return f"SUMMARY: the document is about loans{p}.\n- key point one\n- key point two"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n))
        text = reply_for(req["messages"])
        delay = float(DELAY)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for k in range(0, len(text), 6):
                chunk = {"choices": [{"delta": {"content": text[k:k + 6]}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                if delay:
                    time.sleep(delay)
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass


DELAY = 0.0

if __name__ == "__main__":
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1])
    if "--slow" in args:
        DELAY = 0.05
    time.sleep(0.3)                      # pretend to load a model
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
