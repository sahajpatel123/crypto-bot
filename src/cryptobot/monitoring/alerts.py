"""Pluggable alert sinks with rate limiting (T3.3).

Sinks: memory (tests), log (stderr JSON) and webhook (env URL, stdlib).
Telegram/email are reached through the same webhook shape (owner points
it at a relay) — credentials live in env only, never in code/config.
Rate limiting is per kind: a flapping protection gap cannot spam.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

ALERT_KINDS = ("emergency-stop", "unknown-outcome", "protection-gap",
               "drop-breaker", "daily-stop", "watchdog", "crash-restart",
               "safe-mode", "operator-kill", "stream-outage",
               "order-rejected", "dust-position")


class AlertSink(Protocol):
    def send(self, kind: str, payload: dict[str, Any]) -> bool: ...


class MemorySink:
    """Fake sink for tests/dry runs."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send(self, kind: str, payload: dict[str, Any]) -> bool:
        self.sent.append((kind, dict(payload)))
        return True


class LogSink:
    def send(self, kind: str, payload: dict[str, Any]) -> bool:
        print(json.dumps({"alert": kind, **payload}, sort_keys=True),
              file=sys.stderr)
        return True


class WebhookSink:
    def __init__(self, url: str, *, timeout_s: float = 5.0) -> None:
        self._url = url
        self._timeout = timeout_s

    def send(self, kind: str, payload: dict[str, Any]) -> bool:
        try:
            body = json.dumps({"kind": kind, **payload}).encode()
            req = urllib.request.Request(  # noqa: S310 (owner-configured)
                self._url, data=body, method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self._timeout):
                return True
        except Exception:  # noqa: BLE001 — alerting must not kill the bot
            return False


def sink_from_env() -> AlertSink:
    url = os.environ.get("CRYPTOBOT_ALERT_WEBHOOK", "")
    return WebhookSink(url) if url else LogSink()


class RateLimitedSink:
    """Per-kind minimum interval wrapper (default 60s)."""

    def __init__(self, inner: AlertSink, *, min_interval_s: float = 60.0,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._inner = inner
        self._min = float(min_interval_s)
        self._now = now
        self._last: dict[str, float] = {}
        self.suppressed = 0

    def send(self, kind: str, payload: dict[str, Any]) -> bool:
        now = self._now()
        if now - self._last.get(kind, -1e18) < self._min:
            self.suppressed += 1
            return False
        self._last[kind] = now
        return self._inner.send(kind, payload)
