"""Causal closed 1-second bars from trade events (Worker 2, E-006).

Consumes normalized ``aggTrade`` events (plus ``bookTicker`` BBO for spread)
and emits dense per-second series for the S1/S2 bar interface
(``list[Bar | None]`` with 1-second ``ts_utc`` spacing, ``None`` = missing).

Causality contract:
- A window closes only when the watermark passes its end. Watermark = max
  exchange trade time seen minus the lateness allowance. Nothing after the
  watermark can revise a closed bar.
- Trades older than the watermark are counted as late and dropped, never
  backfilled into closed bars.
- Windows with no trades are ``BarMissing`` (empty); windows skipped by a
  trade-ID discontinuity are ``BarMissing`` with ``gap_before`` set. Both
  convert to ``None`` for the S1/S2 consumer; the missing marker keeps the
  window identity so dense series rebuild from disk. No OHLC is carried backward.
- ``buy_frac`` comes only from real trade side flags; ``spread_bps`` only
  from in-window BBO samples. Bars lacking spread convert to ``None`` —
  spread is never carried forward or invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = ["Bar1s", "BarAggregator", "BarMissing", "to_s1_bar",
         "bar_from_dict", "bar_to_dict"]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Bar1s:
    symbol: str
    window_start_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int
    buy_volume: float
    first_id: int
    last_id: int
    spread_bps: float | None  # last in-window BBO spread; None when unobserved.
    gap_before: bool  # a trade-ID discontinuity precedes this bar.

    @property
    def buy_frac(self) -> float:
        return self.buy_volume / self.volume if self.volume > 0 else 0.0


@dataclass(frozen=True)
class BarMissing:
    """Closed window with no usable bar: empty, or skipped by a trade-ID jump.

    Carries its window identity so file records stay attributable — a dense
    per-symbol series can only be rebuilt from disk when missing windows know
    their own (symbol, window_start_ms). Converts to ``None`` for S1/S2.
    """

    symbol: str
    window_start_ms: int
    gap_before: bool  # True when a trade-ID discontinuity may hide trades here.


def bar_to_dict(bar: Bar1s | BarMissing) -> dict[str, Any]:
    """JSON-safe dict for a closed bar/missing marker (checkpointing)."""
    if isinstance(bar, BarMissing):
        return {"kind": "missing", "symbol": bar.symbol,
                "window_start_ms": bar.window_start_ms,
                "gap_before": bar.gap_before}
    return {"kind": "bar", "symbol": bar.symbol,
            "window_start_ms": bar.window_start_ms, "open": bar.open,
            "high": bar.high, "low": bar.low, "close": bar.close,
            "volume": bar.volume, "trades": bar.trades,
            "buy_volume": bar.buy_volume, "first_id": bar.first_id,
            "last_id": bar.last_id, "spread_bps": bar.spread_bps,
            "gap_before": bar.gap_before}


def bar_from_dict(raw: dict[str, Any]) -> Bar1s | BarMissing:
    """Inverse of :func:`bar_to_dict` (checkpoint restore)."""
    if raw["kind"] == "missing":
        return BarMissing(symbol=raw["symbol"],
                          window_start_ms=int(raw["window_start_ms"]),
                          gap_before=bool(raw["gap_before"]))
    if raw["kind"] != "bar":
        raise ValueError(f"unknown bar kind {raw.get('kind')!r}")
    spread = raw["spread_bps"]
    return Bar1s(symbol=raw["symbol"],
                 window_start_ms=int(raw["window_start_ms"]),
                 open=float(raw["open"]), high=float(raw["high"]),
                 low=float(raw["low"]), close=float(raw["close"]),
                 volume=float(raw["volume"]), trades=int(raw["trades"]),
                 buy_volume=float(raw["buy_volume"]),
                 first_id=int(raw["first_id"]), last_id=int(raw["last_id"]),
                 spread_bps=None if spread is None else float(spread),
                 gap_before=bool(raw["gap_before"]))


def to_s1_bar(bar: Bar1s | BarMissing | None):
    """Convert to the strategies-side Bar, or None when unbuildable (missing window/spread).

    A set ``gap_before`` also yields None: a trade-ID discontinuity may hide
    trades inside the window, so the bar must fail safe (E-009 finding 4).
    """
    if bar is None or isinstance(bar, BarMissing) or bar.spread_bps is None:
        return None
    if bar.gap_before:
        return None
    from cryptobot.strategies.s1 import Bar  # lazy: strategies stay an integration edge, not a dep.

    return Bar(
        ts_utc=_EPOCH + timedelta(milliseconds=bar.window_start_ms),
        open=bar.open, high=bar.high, low=bar.low, close=bar.close,
        volume=bar.volume, trades=bar.trades, buy_frac=bar.buy_frac,
        spread_bps=bar.spread_bps, source="observed-public",
    )


@dataclass
class _Window:
    start_ms: int
    o: float = 0.0
    h: float = float("-inf")
    low: float = float("inf")
    c: float = 0.0
    volume: float = 0.0
    trades: int = 0
    buy_volume: float = 0.0
    first_id: int = 0
    last_id: int = 0
    spread_bps: float | None = None
    has_trades: bool = False

    def add_trade(self, price: float, qty: float, buy_taker: bool, trade_id: int) -> None:
        if not self.has_trades:
            self.o = self.c = price
            self.first_id = trade_id
            self.has_trades = True
        self.c = price
        self.h = max(self.h, price)
        self.low = min(self.low, price)
        self.volume += qty
        self.trades += 1
        if buy_taker:
            self.buy_volume += qty
        self.last_id = trade_id


class BarAggregator:
    """Per-symbol causal 1s bar builder over normalized trade events."""

    def __init__(self, symbol: str, *, lateness_ms: int = 500) -> None:
        self.symbol = symbol
        self.lateness_ms = lateness_ms
        self._windows: dict[int, _Window] = {}
        self._max_ts_ms = 0
        self._last_id = 0
        self._last_ts_ms = 0
        self._gap_flag_windows: set[int] = set()  # windows possibly missing jumped-over trades.
        self._closed_through_ms = 0  # watermark frontier, exclusive window-end bound.
        self.late_dropped = 0
        self.empty_windows = 0
        self.gap_jumps = 0  # trade-ID discontinuities observed (events, not windows).
        self.spreads_seen = 0

    @property
    def watermark_ms(self) -> int:
        return max(0, self._max_ts_ms - self.lateness_ms)

    def on_bbo(self, bid: float, ask: float, exchange_ts_ms: int) -> None:
        if bid <= 0 or ask <= 0 or ask < bid:
            return
        window = (exchange_ts_ms // 1000) * 1000
        w = self._windows.setdefault(window, _Window(window))
        w.spread_bps = (ask - bid) / ((ask + bid) / 2) * 10_000
        self.spreads_seen += 1

    def on_trade(self, event: dict[str, Any]) -> list[Bar1s | BarMissing]:
        """Feed one normalized aggTrade event; returns newly closed windows (bar or missing)."""
        payload = event["payload"]
        ts_ms = int(event["exchange_ts_ms"])
        trade_id = int(payload["agg_id"])
        if ts_ms < self.watermark_ms:
            self.late_dropped += 1
            return []
        window = (ts_ms // 1000) * 1000
        if self._last_id and trade_id > self._last_id + 1:
            # Jumped-over IDs have timestamps inside (prev_ts, ts]: flag every
            # not-yet-closed window in that span; missing trades may hide there.
            self.gap_jumps += 1
            floor = max((self._last_ts_ms // 1000) * 1000, self._closed_through_ms)
            span = window
            while floor <= span:
                self._gap_flag_windows.add(floor)
                floor += 1000
        elif trade_id <= self._last_id:
            self.late_dropped += 1  # duplicate/out-of-order trade ID.
            return []
        self._last_id = max(self._last_id, trade_id)
        self._last_ts_ms = ts_ms
        self._max_ts_ms = max(self._max_ts_ms, ts_ms)
        w = self._windows.setdefault(window, _Window(window))
        w.add_trade(float(payload["price"]), float(payload["qty"]),
                    not bool(payload["buyer_is_maker"]), trade_id)
        return self._close_ready()

    def _close_ready(self) -> list[Bar1s | BarMissing]:
        out: list[Bar1s | BarMissing] = []
        frontier = self.watermark_ms
        if not self._windows and self._closed_through_ms == 0:
            return out
        # Dense series: every whole second through the frontier, missing where empty.
        start = self._closed_through_ms or min(self._windows)
        while start + 1000 <= frontier:
            w = self._windows.pop(start, None)
            flagged = start in self._gap_flag_windows
            self._gap_flag_windows.discard(start)
            if w is None or not w.has_trades:
                self.empty_windows += 1
                out.append(BarMissing(self.symbol, start, flagged))
            else:
                out.append(Bar1s(self.symbol, start, w.o, w.h, w.low, w.c, w.volume,
                                 w.trades, w.buy_volume, w.first_id, w.last_id,
                                 w.spread_bps, flagged))
            start += 1000
            self._closed_through_ms = start
        return out

    def flush(self) -> list[Bar1s | BarMissing]:
        """Close every complete window (drains through max observed time)."""
        if not self._windows:
            return []
        saved, self._max_ts_ms = self._max_ts_ms, self._max_ts_ms + self.lateness_ms
        try:
            return self._close_ready()
        finally:
            self._max_ts_ms = saved

    def stats(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "lateness_ms": self.lateness_ms,
            "watermark_ms": self.watermark_ms,
            "max_ts_ms": self._max_ts_ms,
            "late_dropped": self.late_dropped,
            "empty_windows": self.empty_windows,
            "gap_jumps": self.gap_jumps,
            "spreads_seen": self.spreads_seen,
            "open_windows": len(self._windows),
        }

    def to_dict(self) -> dict[str, Any]:
        """Full aggregator state: open windows, watermark, seq, counters."""
        windows = {}
        for start, w in self._windows.items():
            # h/low are +/-inf until the first trade: persist null then
            # (from_dict restores defaults), keeping the dict strict-JSON.
            windows[str(start)] = {
                "o": w.o, "h": w.h if w.has_trades else None,
                "low": w.low if w.has_trades else None, "c": w.c,
                "volume": w.volume, "trades": w.trades,
                "buy_volume": w.buy_volume, "first_id": w.first_id,
                "last_id": w.last_id, "spread_bps": w.spread_bps,
                "has_trades": w.has_trades}
        return {"symbol": self.symbol, "lateness_ms": self.lateness_ms,
                "windows": windows, "max_ts_ms": self._max_ts_ms,
                "last_id": self._last_id, "last_ts_ms": self._last_ts_ms,
                "gap_flag_windows": sorted(self._gap_flag_windows),
                "closed_through_ms": self._closed_through_ms,
                "late_dropped": self.late_dropped,
                "empty_windows": self.empty_windows,
                "gap_jumps": self.gap_jumps,
                "spreads_seen": self.spreads_seen}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BarAggregator":
        """Rebuild aggregator state exactly (checkpoint restore)."""
        agg = cls(str(raw["symbol"]), lateness_ms=int(raw["lateness_ms"]))
        for key, wd in raw["windows"].items():
            w = _Window(int(key))
            if wd["has_trades"]:
                w.o = float(wd["o"])
                w.h = float(wd["h"])
                w.low = float(wd["low"])
                w.c = float(wd["c"])
                w.volume = float(wd["volume"])
                w.trades = int(wd["trades"])
                w.buy_volume = float(wd["buy_volume"])
                w.first_id = int(wd["first_id"])
                w.last_id = int(wd["last_id"])
                w.has_trades = True
            spread = wd["spread_bps"]
            w.spread_bps = None if spread is None else float(spread)
            agg._windows[int(key)] = w
        agg._max_ts_ms = int(raw["max_ts_ms"])
        agg._last_id = int(raw["last_id"])
        agg._last_ts_ms = int(raw["last_ts_ms"])
        agg._gap_flag_windows = {int(v) for v in raw["gap_flag_windows"]}
        agg._closed_through_ms = int(raw["closed_through_ms"])
        agg.late_dropped = int(raw["late_dropped"])
        agg.empty_windows = int(raw["empty_windows"])
        agg.gap_jumps = int(raw["gap_jumps"])
        agg.spreads_seen = int(raw["spreads_seen"])
        return agg
