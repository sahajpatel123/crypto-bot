"""Venue/runtime adapters (Worker 2, E-007).

Lazy exports: ``cryptobot.adapters.bridge`` (stdlib-only live iterator) must
import without nautilus; the nautilus-backed engine resolves on first use.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "ENGINE_VERSION",
    "NautilusPaperEngine",
    "BinanceLiveEngine",
    "RateLimitedError",
    "UnknownOutcomeError",
    "VenueHttpError",
    "VenueRejectedError",
    "caller_action",
    "UserStreamReader",
    "UserStreamAttachment",
    "attach_user_stream",
]


def __getattr__(name: str) -> Any:
    if name in ("ENGINE_VERSION", "NautilusPaperEngine"):
        from .paper_engine import ENGINE_VERSION, NautilusPaperEngine
        return {"ENGINE_VERSION": ENGINE_VERSION,
                "NautilusPaperEngine": NautilusPaperEngine}[name]
    if name in ("BinanceLiveEngine", "UnknownOutcomeError", "VenueHttpError",
                "VenueRejectedError", "RateLimitedError", "caller_action"):
        from . import binance_live
        return getattr(binance_live, name)
    if name in ("UserStreamReader", "UserStreamAttachment",
                "attach_user_stream"):
        from . import user_stream
        return getattr(user_stream, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
