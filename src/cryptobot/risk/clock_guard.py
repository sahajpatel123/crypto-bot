"""F2.6: continuous clock-skew guard for entries.

The venue's signed requests carry ``recvWindow``; if local clock drift
approaches that window, signatures can fail or, worse, an order can be
accepted with stale intent timestamps. This guard trips entries well
before the recvWindow safety margin and never resets itself silently.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ClockGuard:
    max_skew_ms: float
    hard_margin_ms: float = 1000.0
    _tripped: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_skew_ms) or self.max_skew_ms <= 0:
            raise ValueError("max_skew_ms must be positive finite")
        if not math.isfinite(self.hard_margin_ms) \
                or self.hard_margin_ms <= 0:
            raise ValueError("hard_margin_ms must be positive finite")

    def observe(self, offset_ms: float) -> str:
        """Record a measured (server-local) offset; return a halt reason."""
        if not isinstance(offset_ms, (int, float)) \
                or not math.isfinite(offset_ms):
            self._tripped = "clock:offset-unmeasured"
            return self._tripped
        if abs(offset_ms) > self.max_skew_ms:
            self._tripped = (
                f"clock:skew-{abs(offset_ms):.0f}ms"
                f">max-{self.max_skew_ms:.0f}ms")
        return self._tripped

    def allows_entries(self, offset_ms: float | None = None) -> bool:
        if offset_ms is not None:
            self.observe(offset_ms)
        return not self._tripped

    def require(self, offset_ms: float) -> None:
        reason = self.observe(offset_ms)
        if reason:
            raise ValueError(reason)

    def recv_window_safe_ms(self, recv_window_ms: int) -> bool:
        """Reserve the hard margin inside the venue recvWindow."""
        return float(recv_window_ms) - float(self.max_skew_ms) \
            >= float(self.hard_margin_ms)


__all__ = ["ClockGuard"]
