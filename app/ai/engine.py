"""The local AI model.

BRB PDF runs a small language model ON THIS COMPUTER with llama.cpp's
`llama-server` program. It listens only on 127.0.0.1 (this computer), so no
document text ever leaves the PC and no internet connection is needed.

Files (installed by the full installer, or copied by hand):
    <program folder>\\ai\\llama\\llama-server.exe   (+ its .dll files)
    <program folder>\\ai\\models\\*.gguf            (the model, e.g. Qwen2.5 1.5B Instruct)

Any other GGUF chat model can be dropped into ai\\models (a bigger model gives
better answers but is slower); the largest file is used unless one is chosen
in the settings.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from app import config

log = logging.getLogger("pdfworkbench.ai")

# Never use a proxy: the model is on this computer.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Cancelled(Exception):
    """The user pressed Stop."""


class ModelError(Exception):
    """The local model could not start or answer (message is meant for the user)."""


def ai_dir() -> Path:
    return config.app_dir() / "ai"


def find_server() -> Path | None:
    exe = "llama-server.exe" if sys.platform.startswith("win") else "llama-server"
    for p in (ai_dir() / "llama" / exe, ai_dir() / exe):
        if p.is_file():
            return p
    return None


def find_models() -> list[Path]:
    d = ai_dir() / "models"
    if not d.is_dir():
        return []
    return sorted((p for p in d.glob("*.gguf") if p.stat().st_size > 50_000_000),
                  key=lambda p: -p.stat().st_size)


def friendly_name(model: Path) -> str:
    n = model.stem.replace("-", " ").replace("_", " ")
    for junk in ("q4 k m", "q5 k m", "q8 0", "q4 0", "instruct", "gguf"):
        n = n.replace(junk, "").replace(junk.upper(), "")
    return " ".join(w.capitalize() if w.islower() else w for w in n.split()) or model.stem


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LocalModel:
    """One llama-server process for the whole app (started on first use, stopped on exit)."""

    def __init__(self, server: Path, model: Path, context: int = 8192, threads: int | None = None,
                 launcher: list[str] | None = None):
        self.server = server
        self.launcher = launcher          # tests: run a stand-in server script instead of the .exe
        self.model = model
        self.context = context
        cores = os.cpu_count() or 4
        self.threads = threads or max(2, min(8, cores // 2 if cores > 4 else cores))
        self.port = 0
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return friendly_name(self.model)

    # ------------------------------------------------------------- process
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, timeout: float = 180.0, cancel: threading.Event | None = None) -> None:
        with self._lock:
            if self.running():
                return
            self.port = _free_port()
            config.ensure_dirs()
            logf = open(config.LOG_DIR / "local-ai.log", "ab")
            args = (self.launcher or [str(self.server)]) + ["-m", str(self.model), "--host", "127.0.0.1", "--port", str(self.port),
                    "-c", str(self.context), "-t", str(self.threads), "-np", "1"]
            flags = 0x08000000 if sys.platform.startswith("win") else 0          # CREATE_NO_WINDOW
            log.info("Starting local AI: %s", " ".join(args))
            try:
                self.proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                             cwd=str(self.server.parent), creationflags=flags)
            except OSError as exc:
                raise ModelError(f"The local AI program could not be started: {exc}") from exc
            finally:
                logf.close()
        end = time.time() + timeout
        while time.time() < end:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if self.proc.poll() is not None:
                raise ModelError("The local AI program stopped while loading the model. The model file may be "
                                 "damaged, or the computer may not have enough free memory (about 2 GB is needed). "
                                 "Details: Help > Open Log Folder > local-ai.log")
            try:
                with _OPENER.open(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if r.status == 200 and json.loads(r.read() or b"{}").get("status", "ok") == "ok":
                        log.info("Local AI ready on port %s", self.port)
                        return
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.4)
        self.stop()
        raise ModelError("The local AI model took too long to load.")

    def stop(self) -> None:
        p = self.proc
        self.proc = None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()

    # ---------------------------------------------------------------- chat
    def chat(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.2,
             on_token=None, cancel: threading.Event | None = None, json_mode: bool = False) -> str:
        """Send a conversation, stream the reply (on_token gets each piece), return the full text."""
        self.start(cancel=cancel)
        body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                "top_p": 0.9, "repeat_penalty": 1.1, "stream": True, "cache_prompt": True}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        out: list[str] = []
        try:
            with _OPENER.open(req, timeout=600) as resp:
                for raw in resp:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        piece = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
                    except (ValueError, KeyError, IndexError):
                        continue
                    if piece:
                        out.append(piece)
                        if on_token is not None:
                            on_token(piece)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ModelError(f"The local AI model refused the request ({exc.code}). {detail}") from exc
        except (urllib.error.URLError, ConnectionError) as exc:
            if not self.running():
                raise ModelError("The local AI program stopped unexpectedly. Try again; see local-ai.log "
                                 "in the log folder for details.") from exc
            raise ModelError(f"Could not talk to the local AI model: {exc}") from exc
        return "".join(out)


_model: LocalModel | None = None
_checked = False


def get_model() -> LocalModel | None:
    """The installed local model, or None (then the app uses quick mode)."""
    global _model, _checked
    if not _checked:
        _checked = True
        server, models = find_server(), find_models()
        if server is not None and models:
            _model = LocalModel(server, models[0])
            log.info("Local AI available: %s (%s)", _model.name, models[0])
        else:
            log.info("No local AI model installed (server=%s, models=%d)", server, len(models))
    return _model


def set_model(model: LocalModel | None) -> None:
    """For tests and settings."""
    global _model, _checked
    if _model is not None and _model is not model:
        _model.stop()
    _model, _checked = model, True


def shutdown() -> None:
    if _model is not None:
        _model.stop()
