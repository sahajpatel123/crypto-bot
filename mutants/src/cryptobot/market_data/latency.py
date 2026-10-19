"""Honest multi-span latency ledger (REL-W3-DATA 3).

Seven named spans with counts + p50/p95/p99/max + clock domains:

- event_age: venue exchange timestamp -> local receipt (venue->local wall).
- queue_delay: ingest publish -> consumer poll (local mono -> local mono).
- feature_calc: feature/strategy computation wall time (local mono).
- risk_to_command: risk decision -> order command built (local mono).
- transport_ack: command sent -> venue acknowledgement (local mono).
- fill_notify: venue fill -> local booking (venue -> local).
- stop_confirm: protection request -> verified state (venue -> local).

Honesty rules: spans with no samples report ``measured: False`` and are
never zero-filled or inferred from other spans. In particular no
strategy-function timer may be presented as order latency: the
venue-observed spans (transport_ack, fill_notify, stop_confirm) stay
unmeasured until the adapter path records real venue timestamps.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Callable, Iterator

EVENT_AGE = "event_age"
QUEUE_DELAY = "queue_delay"
FEATURE_CALC = "feature_calc"
RISK_TO_COMMAND = "risk_to_command"
TRANSPORT_ACK = "transport_ack"
FILL_NOTIFY = "fill_notify"
STOP_CONFIRM = "stop_confirm"

SPANS = (EVENT_AGE, QUEUE_DELAY, FEATURE_CALC, RISK_TO_COMMAND,
         TRANSPORT_ACK, FILL_NOTIFY, STOP_CONFIRM)

CLOCK_DOMAINS = {
    EVENT_AGE: ("venue-exchange", "local-wall"),
    QUEUE_DELAY: ("local-mono", "local-mono"),
    FEATURE_CALC: ("local-mono", "local-mono"),
    RISK_TO_COMMAND: ("local-mono", "local-mono"),
    TRANSPORT_ACK: ("local-mono", "venue-ack"),
    FILL_NOTIFY: ("venue", "local"),
    STOP_CONFIRM: ("venue", "local"),
}

_MAX_SAMPLES = 10_000


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


class LatencyLedger:
    """Thread-safe per-span latency recorder with honest summaries."""

    def __init__(self, max_samples: int = _MAX_SAMPLES,
                 mono_s: Callable[[], float] | None = None) -> None:
        self._samples: dict[str, deque[float]] = {
            span: deque(maxlen=max_samples) for span in SPANS}
        self._lock = threading.Lock()
        self._mono_s = mono_s or time.monotonic

    def observe(self, span: str, value_ms: float) -> None:
        """Record one sample. Unknown spans and NaN fail loudly."""
        if span not in self._samples:
            raise ValueError(f"unknown latency span: {span!r}")
        if value_ms != value_ms or value_ms == float("inf"):
            raise ValueError(f"non-finite latency sample for {span}")
        with self._lock:
            self._samples[span].append(float(value_ms))

    @contextmanager
    def timer(self, span: str) -> Iterator[None]:
        """Time a local-mono block into a span (never for venue spans)."""
        if span not in (QUEUE_DELAY, FEATURE_CALC, RISK_TO_COMMAND):
            raise ValueError(
                f"timer() is local-mono only; {span} needs venue timestamps")
        start = self._mono_s()
        try:
            yield
        finally:
            self.observe(span, (self._mono_s() - start) * 1000.0)

    def summarize(self, span: str | None = None) -> dict[str, Any]:
        """Per-span {n, measured, p50/p95/p99/max, clock domains}."""
        names = [span] if span else list(SPANS)
        out: dict[str, Any] = {}
        with self._lock:
            for name in names:
                if name not in self._samples:
                    raise ValueError(f"unknown latency span: {name!r}")
                ordered = sorted(self._samples[name])
                start_domain, end_domain = CLOCK_DOMAINS[name]
                out[name] = {
                    "n": len(ordered),
                    "measured": bool(ordered),
                    "p50_ms": _quantile(ordered, 0.50),
                    "p95_ms": _quantile(ordered, 0.95),
                    "p99_ms": _quantile(ordered, 0.99),
                    "max_ms": max(ordered) if ordered else 0.0,
                    "clock_start": start_domain,
                    "clock_end": end_domain,
                }
        return out
