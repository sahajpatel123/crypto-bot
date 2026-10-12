"""Diff-depth book synchronization (Worker 2, E-006).

Implements the standard Binance snapshot/diff sequence protocol:
buffer diff events, fetch a REST snapshot, discard buffered events at or
before the snapshot ID, require the first applied event to span
``lastUpdateId + 1``, then apply strictly chained events (``pu`` must equal
the previous ``u``). Any chain break forces a resync; the book is unusable
until synchronization completes, and affected intervals stay labelled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["DepthBook", "DepthState"]


@dataclass(frozen=True)
class DepthState:
    synced: bool
    last_update_id: int
    buffered: int
    resyncs: int
    applied: int
    dropped_stale: int
    last_reason: str = ""  # why the book is currently unsynced ("" if synced).


class DepthBook:
    """Per-symbol diff-depth book with explicit sync lifecycle."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self._synced = False
        self._last_update_id = 0
        self._buffer: list[dict[str, Any]] = []
        self.resyncs = 0
        self.applied = 0
        self.dropped_stale = 0
        self._resync_reason = ""

    @property
    def state(self) -> DepthState:
        return DepthState(self._synced, self._last_update_id, len(self._buffer),
                          self.resyncs, self.applied, self.dropped_stale,
                          self._resync_reason)

    def on_diff(self, payload: dict[str, Any]) -> str:
        """Handle one NORMALIZED depth payload (first/last/prev_last_update keys).

        Returns buffered|applied|resync. Normalized input means numerics were
        already validated by the event parser; the snapshot path keeps raw
        REST strings and validates on install.
        """
        if not self._synced:
            self._buffer.append(payload)
            return "buffered"
        if int(payload["prev_last_update"]) != self._last_update_id:
            return "resync"
        self._apply(payload)
        return "applied"

    def on_snapshot(self, bids: list[list[str]], asks: list[list[str]], last_update_id: int) -> str:
        """Install a REST snapshot, then drain the buffer. Returns synced|resync."""
        self.bids = {float(p): float(q) for p, q in bids if float(q) != 0.0}
        self.asks = {float(p): float(q) for p, q in asks if float(q) != 0.0}
        self._last_update_id = int(last_update_id)
        buffered, self._buffer = self._buffer, []
        first = True
        for payload in buffered:
            u, upu = int(payload["last_update"]), int(payload["first_update"])
            if u <= self._last_update_id:
                self.dropped_stale += 1
                continue
            if first:
                if not (upu <= self._last_update_id + 1 <= u):
                    return self._request_resync("snapshot-span")
                first = False
            elif int(payload["prev_last_update"]) != self._last_update_id:
                return self._request_resync("buffer-chain")
            self._apply(payload)
        self._synced = True
        self._resync_reason = ""
        return "synced"

    def _request_resync(self, reason: str) -> str:
        self._synced = False
        self._buffer = []
        self.resyncs += 1
        self._resync_reason = reason
        return "resync"

    def request_resync(self, reason: str = "chain-break") -> None:
        self._request_resync(reason)

    def _apply(self, payload: dict[str, Any]) -> None:
        for price, qty in payload["bids"]:
            if qty == 0.0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = qty
        for price, qty in payload["asks"]:
            if qty == 0.0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = qty
        self._last_update_id = int(payload["last_update"])
        self.applied += 1

    def top(self) -> tuple[float | None, float | None]:
        """Best (bid, ask); None side when the book has no levels (or is unsynced)."""
        if not self._synced:
            return None, None
        bid = max(self.bids) if self.bids else None
        ask = min(self.asks) if self.asks else None
        return bid, ask

    def spread_bps(self) -> float | None:
        bid, ask = self.top()
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None
        return (ask - bid) / ((ask + bid) / 2) * 10_000

    def depth_totals(self, levels: int = 10) -> tuple[float, float]:
        """Notional within the top N levels per side (0.0 when unsynced/empty)."""
        if not self._synced:
            return 0.0, 0.0
        top_bids = sorted(self.bids, reverse=True)[:levels]
        top_asks = sorted(self.asks)[:levels]
        return (sum(p * self.bids[p] for p in top_bids),
                sum(p * self.asks[p] for p in top_asks))
