"""Venue/runtime adapters (Worker 2, E-007).

Lazy exports: ``cryptobot.adapters.bridge`` (stdlib-only live iterator) must
import without nautilus; the nautilus-backed engine resolves on first use.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "ENGINE_VERSION",
    "NautilusPaperEngine",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .paper_engine import ENGINE_VERSION, NautilusPaperEngine
        return {"ENGINE_VERSION": ENGINE_VERSION,
                "NautilusPaperEngine": NautilusPaperEngine}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
