"""Bounded async ingest with loud overload semantics (REL-W3-DATA 2).

One bounded queue per (symbol, channel-family); producers (socket
readers) never block the consumer and memory never grows without limit:

- Market data (trades, BBO, marks): drop-oldest past capacity, every
  drop counted with the last-drop reason and timestamp. Dropped data is
  never silently treated as fresh: drops flip the symbol into SHEDDING.
- Depth diffs: NEVER dropped (a dropped diff breaks the sequence
  chain). Backpressure on the depth queue marks the book unsynced and
  raises a resync request instead; the queued diffs are preserved for
  the post-snapshot drain.
- Overload state per symbol (OK / SHEDDING / OVERLOADED) plus a global
  rollup. ``entries_hold_reason()`` returns None when entries may flow
  or a reason when overload (or an unsynced required book) must stop
  new entries. Exposure management is unaffected by construction: book
  state readers and the drain path stay available in every state.

Session/bridge adoption (W1/W2 own those files) is proposed via the
manager: Session consults ``entries_hold_reason()`` in its admission
hold, and the live pump feeds this primitive instead of unbounded
growth. This module is the market-data side of that contract.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from .depth import DepthBook
from .latency import QUEUE_DELAY, LatencyLedger

OK = "ok"
SHEDDING = "shedding"
OVERLOADED = "overloaded"

_MARKET_CHANNELS = ("aggTrade", "bookTicker", "markPrice")


@dataclass
class ChannelStats:
    received: int = 0
    dropped: int = 0
    last_drop_reason: str = ""
    last_drop_ts_ms: int = 0


@dataclass
class SymbolIngest:
    symbol: str
    market: queue.Queue  # trades/BBO/marks; drop-oldest when full.
    depth: queue.Queue  # diffs; NEVER dropped (resync on pressure).
    book: DepthBook
    stats: dict[str, ChannelStats] = field(default_factory=dict)
    resyncs_requested: int = 0
    resync_pending: bool = False
    state: str = OK
    degraded_since_ms: int = 0


class BoundedIngest:
    """Thread-safe bounded ingest for the live pump (see module docstring)."""

    def __init__(self, symbols: list[str], *,
                 market_max: int = 1000,
                 depth_max: int = 5000,
                 overload_after_drops: int = 100,
                 clock_ms: Callable[[], int] | None = None,
                 mono_s: Callable[[], float] | None = None,
                 ledger: LatencyLedger | None = None) -> None:
        if market_max < 1 or depth_max < 1:
            raise ValueError("queue bounds must be >= 1")
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._mono_s = mono_s or time.monotonic
        self._ledger = ledger
        self._market_max = market_max
        self._depth_max = depth_max
        self._overload_after = overload_after_drops
        self._lock = threading.Lock()
        self._market_ts: dict[str, deque[float]] = {
            s: deque() for s in symbols}
        self._symbols: dict[str, SymbolIngest] = {}
        for symbol in symbols:
            self._symbols[symbol] = SymbolIngest(
                symbol=symbol,
                market=queue.Queue(maxsize=market_max),
                depth=queue.Queue(maxsize=depth_max),
                book=DepthBook(symbol),
                stats={c: ChannelStats() for c in
                       (*_MARKET_CHANNELS, "depth")})

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self._symbols)

    def _note_drop(self, ingest: SymbolIngest, channel: str,
                   reason: str) -> None:
        stats = ingest.stats[channel]
        stats.dropped += 1
        stats.last_drop_reason = reason
        stats.last_drop_ts_ms = self._clock_ms()
        if ingest.state == OK:
            ingest.state = SHEDDING
            ingest.degraded_since_ms = stats.last_drop_ts_ms
        elif (ingest.state == SHEDDING
              and stats.dropped >= self._overload_after):
            ingest.state = OVERLOADED

    def publish_market(self, symbol: str, channel: str, event: Any) -> bool:
        """Publish a trade/BBO/mark; drop-oldest when full. Returns kept."""
        ingest = self._symbols[symbol]
        ingest.stats[channel].received += 1
        with self._lock:
            try:
                ingest.market.put_nowait((channel, event))
                self._market_ts[symbol].append(self._mono_s())
                return True
            except queue.Full:
                pass
            try:
                ingest.market.get_nowait()
                if self._market_ts[symbol]:
                    self._market_ts[symbol].popleft()
            except queue.Empty:
                pass
            self._note_drop(ingest, channel, "market-queue-full")
            try:
                ingest.market.put_nowait((channel, event))
                self._market_ts[symbol].append(self._mono_s())
            except queue.Full:
                self._note_drop(ingest, channel, "market-queue-full-retry")
                return False
            return True

    def publish_diff(self, symbol: str, payload: dict[str, Any]) -> str:
        """Publish one depth diff. Never dropped; backpressure resyncs.

        Returns queued|resync-requested. When the depth queue is full the
        book is marked unsynced and a resync is requested (loudly
        counted); queued diffs are preserved for the snapshot drain.
        """
        ingest = self._symbols[symbol]
        ingest.stats["depth"].received += 1
        try:
            ingest.depth.put_nowait(payload)
            return "queued"
        except queue.Full:
            ingest.book.request_resync("depth-queue-full")
            ingest.resyncs_requested += 1
            ingest.resync_pending = True
            if ingest.state == OK:
                ingest.state = SHEDDING
                ingest.degraded_since_ms = self._clock_ms()
            return "resync-requested"

    def poll_market(self, symbol: str) -> Any | None:
        """Next (channel, event) or None. Consumer-paced; never blocks."""
        try:
            item = self._symbols[symbol].market.get_nowait()
        except queue.Empty:
            return None
        if self._ledger is not None:
            with self._lock:
                put_at = (self._market_ts[symbol].popleft()
                          if self._market_ts[symbol] else None)
            if put_at is not None:
                self._ledger.observe(
                    QUEUE_DELAY, (self._mono_s() - put_at) * 1000.0)
        return item

    def drain_depth(self, symbol: str, max_items: int = 1000) -> list[str]:
        """Apply up to max_items queued diffs; returns per-diff outcomes.

        Chain breaks request resync (loud) and stop the drain at the
        break; nothing is applied out of order and nothing is skipped
        silently. Returns outcomes so the caller can snapshot on resync.
        """
        ingest = self._symbols[symbol]
        outcomes: list[str] = []
        for _ in range(max_items):
            try:
                payload = ingest.depth.get_nowait()
            except queue.Empty:
                break
            outcome = ingest.book.on_diff(payload)
            outcomes.append(outcome)
            if outcome == "resync":
                ingest.book.request_resync("chain-break")
                ingest.resyncs_requested += 1
                ingest.resync_pending = True
                break
        if ingest.resync_pending and ingest.book.state.synced:
            ingest.resync_pending = False
        self._maybe_recover(ingest)
        return outcomes

    def install_snapshot(self, symbol: str, bids: list, asks: list,
                         last_update_id: int) -> str:
        """Install a REST snapshot; clears the resync flag on success."""
        ingest = self._symbols[symbol]
        outcome = ingest.book.on_snapshot(bids, asks, last_update_id)
        if outcome == "synced":
            ingest.resync_pending = False
            self._maybe_recover(ingest)
        return outcome

    def _maybe_recover(self, ingest: SymbolIngest) -> None:
        if (ingest.state != OK and not ingest.resync_pending
                and ingest.market.empty() and ingest.depth.empty()):
            ingest.state = OK
            ingest.degraded_since_ms = 0

    def entries_hold_reason(self, symbol: str | None = None) -> str | None:
        """None when entries may flow; a hold reason under overload.

        With a symbol, reports that symbol; without, rolls up all symbols
        (any SHEDDING/OVERLOADED symbol or pending depth resync holds).
        Exposure management never consults this gate.
        """
        names = [symbol] if symbol else list(self._symbols)
        for name in names:
            ingest = self._symbols[name]
            if ingest.resync_pending:
                return f"ingest:depth-resync-pending:{name}"
            if ingest.state == OVERLOADED:
                return f"ingest:overloaded:{name}"
            if ingest.state == SHEDDING:
                return f"ingest:shedding:{name}"
        return None

    def book_state(self, symbol: str):
        """Lock-free book state read (available in every overload state)."""
        return self._symbols[symbol].book.state

    def report(self) -> dict[str, Any]:
        """Full counters snapshot for status/report paths."""
        with self._lock:
            out: dict[str, Any] = {"symbols": {}}
            for name, ingest in self._symbols.items():
                out["symbols"][name] = {
                    "state": ingest.state,
                    "degraded_since_ms": ingest.degraded_since_ms,
                    "resyncs_requested": ingest.resyncs_requested,
                    "resync_pending": ingest.resync_pending,
                    "market_qsize": ingest.market.qsize(),
                    "depth_qsize": ingest.depth.qsize(),
                    "book": {"synced": ingest.book.state.synced,
                             "last_update_id":
                                 ingest.book.state.last_update_id,
                             "applied": ingest.book.state.applied,
                             "chain_breaks": ingest.book.state.chain_breaks,
                             "buffer_overflows":
                                 ingest.book.state.buffer_overflows,
                             "last_reason": ingest.book.state.last_reason},
                    "channels": {c: {"received": s.received,
                                     "dropped": s.dropped,
                                     "last_drop_reason": s.last_drop_reason,
                                     "last_drop_ts_ms": s.last_drop_ts_ms}
                                 for c, s in ingest.stats.items()},
                }
            return out
