"""Optional local AI integration point (not active in Phase 1).

The application must work fully without any AI model. Future features
("summarise this PDF", "find loan terms") will call `get_provider()` and
receive a provider object. The default is NullProvider, which reports that
no model is installed. A later phase can add an OllamaProvider or
LlamaCppProvider that talks ONLY to a model running on this computer
(for example http://127.0.0.1:11434). No online AI API will ever be used.
"""
from __future__ import annotations

from typing import Protocol


class AIProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete(self, prompt: str, context: str = "") -> str: ...


class NullProvider:
    name = "None (no local model installed)"

    def available(self) -> bool:
        return False

    def complete(self, prompt: str, context: str = "") -> str:
        raise RuntimeError("No local AI model is configured. All other features work without one.")


_provider: AIProvider = NullProvider()


def get_provider() -> AIProvider:
    return _provider


def set_provider(provider: AIProvider) -> None:
    global _provider
    _provider = provider
