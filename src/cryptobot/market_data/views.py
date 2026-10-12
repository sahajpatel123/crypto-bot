"""Synchronized book/flow views for strategies (W2, E-008; B4).

:class:`DepthStore` maintains per-symbol synchronized depth books (Binance
snapshot/diff protocol via :class:`DepthBook`) plus causal 1 s signed-trade
windows. :func:`book_flow_for` answers as-of queries: a :class:`BookView`
(synchronized top-N levels + sync age + quality), a :class:`FlowView2`
(signed aggregates + window + completeness), and a precise ineligibility
reason when a view is absent (``""`` when both are present).

Honesty rules: bookTicker top-of-book is NEVER fed into the synchronized
book (unsynced quotes must not masquerade as observed depth); gapped
trade-ID windows are missing, never interpolated; archive data without
quotes/depth yields ``book:never-synced`` / ``flow:no-trades-yet``
(S5-ineligible with reasons, never estimated BBO presented as observed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cryptobot.market_data.bridge import flow_window
from cryptobot.market_data.depth import DepthBook

__all__ = ["BookView", "FlowView2", "DepthStore", "book_flow_for"]

_DEFAULT_LEVELS = 10
_DEFAULT_STALE_AFTER_MS = 5_000


@dataclass(frozen=True)
class BookView:
    """Synchronized top-N book as of ``ts_ms`` (observed levels only)."""

    symbol: str
    ts_ms: int
    bids: tuple[tuple[float, float], ...]  # (price, qty), best first.
    asks: tuple[tuple[float, float], ...]  # (price, qty), best first.
    levels: int                            # requested N (fewer when thin).
    sync_age_ms: int                       # ts_ms - last applied update.
    last_update_id: int
    quality: str                           # "clean" | "stale".
    spread_bps: float | None
    imbalance_top1: float | None           # (bid1-sask1)/(bid1+ask1) size.


@dataclass(frozen=True)
class FlowView2:
    """Signed trade aggregates for one closed 1 s window."""

    symbol: str
    window_start_ms: int
    window_end_ms: int
    buy_notional: float
    sell_notional: float
    buy_count: int
    sell_count: int
    total_qty: float
    vwap: float | None
    last_id: int
    completeness: str  # "complete" | "chain-resync" (re-anchored after a gap).


class DepthStore:
    """Per-symbol synchronized books + causal trade windows (bounded).

    Memory is bounded: one book per seen symbol (the traded universe), one
    open 1 s trade window per symbol, and one closed aggregate per symbol.
    """

    def __init__(self, *, levels: int = _DEFAULT_LEVELS,
                 stale_after_ms: int = _DEFAULT_STALE_AFTER_MS) -> None:
        if levels <= 0:
            raise ValueError("levels must be > 0")
        if stale_after_ms <= 0:
            raise ValueError("stale_after_ms must be > 0")
        self.levels = levels
        self.stale_after_ms = stale_after_ms
        self._books: dict[str, DepthBook] = {}
        self._applied_ms: dict[str, int] = {}
        self._ever_synced: set[str] = set()
        self._flow: dict[str, dict[str, Any]] = {}

    # -- ingestion ------------------------------------------------------
    def apply_snapshot_record(self, snap: dict[str, Any]) -> str:
        """Install a persisted snapshot record (symbol/bids/asks/ids/recv ms)."""
        symbol = str(snap["symbol"])
        book = self._books.setdefault(symbol, DepthBook(symbol))
        outcome = book.on_snapshot(snap["bids"], snap["asks"],
                                   int(snap["last_update_id"]))
        if outcome == "synced":
            self._ever_synced.add(symbol)
            self._applied_ms[symbol] = int(snap["rest_recv_ms"])
        return outcome

    def apply_diff(self, symbol: str, payload: dict[str, Any],
                   exchange_ms: int) -> str:
        """Apply one normalized depth payload; returns buffered|applied|resync."""
        book = self._books.setdefault(symbol, DepthBook(symbol))
        outcome = book.on_diff({
            "first_update": payload["first_update"],
            "last_update": payload["last_update"],
            "prev_last_update": payload["prev_last_update"],
            "bids": payload["bids"],
            "asks": payload["asks"],
        })
        if outcome == "applied":
            self._applied_ms[symbol] = int(exchange_ms)
        elif outcome == "resync":
            book.request_resync("chain-break")
        return outcome

    def apply_trade(self, symbol: str, payload: dict[str, Any]) -> None:
        """Accumulate one normalized aggTrade payload into its 1 s window."""
        trade_ms = int(payload.get("trade_ts_ms", 0) or 0)
        window = trade_ms // 1000 * 1000
        state = self._flow.setdefault(symbol, {"window": window, "trades": [],
                                               "prev_last_id": None,
                                               "closed": None,
                                               "resync_pending": False})
        if window == state["window"]:
            state["trades"].append(payload)
            return
        self._close_window(symbol, state)
        state["window"], state["trades"] = window, [payload]

    def apply_record(self, record: dict[str, Any]) -> None:
        """Dispatch one normalized record (depth/aggTrade; bookTicker ignored).

        bookTicker is deliberately NOT fed into the synchronized book: it is
        unsynced top-of-book and must never masquerade as observed depth.
        markPrice carries no book/flow information and is skipped.
        """
        channel = record.get("channel")
        symbol = str(record.get("symbol", ""))
        if channel == "depth":
            self.apply_diff(symbol, record["payload"],
                            int(record.get("exchange_ts_ms", 0) or 0))
        elif channel == "aggTrade":
            self.apply_trade(symbol, record["payload"])

    def _close_window(self, symbol: str, state: dict[str, Any]) -> None:
        closed = state["trades"]
        if not closed:
            return  # empty intermediate windows carry no information.
        agg, reason = flow_window(closed, state["window"],
                                  prev_last_id=state["prev_last_id"])
        if agg is not None:
            state["prev_last_id"] = agg["last_id"]
            completeness = ("chain-resync" if state["resync_pending"]
                            else "complete")
        elif closed:
            state["prev_last_id"] = int(closed[-1]["last_id"])  # gap: re-anchor.
            completeness = "gap"
        state["resync_pending"] = reason == "flow:trade-id-gap"
        state["closed"] = (agg, reason, completeness)

    # -- as-of query ----------------------------------------------------
    def book_flow_for(
        self, symbol: str, ts_ms: int
    ) -> tuple[BookView | None, FlowView2 | None, str]:
        """As-of (book, flow, reason): ``reason == ""`` iff both present."""
        book, book_reason = self._book_view(symbol, ts_ms)
        flow, flow_reason = self._flow_view(symbol)
        if book is not None and flow is not None:
            return book, flow, ""
        reasons = [r for r in (book_reason, flow_reason) if r]
        return book, flow, "; ".join(reasons)

    def _book_view(self, symbol: str, ts_ms: int) -> tuple[BookView | None, str]:
        book = self._books.get(symbol)
        if book is None or not book.state.synced:
            if book is not None and symbol in self._ever_synced:
                return None, "book:resync-in-flight"
            return None, "book:never-synced"
        state = book.state
        bid, ask = book.top()
        if bid is None or ask is None:
            return None, "book:empty-book"
        top_bids = tuple((p, book.bids[p]) for p in sorted(book.bids, reverse=True)[:self.levels])
        top_asks = tuple((p, book.asks[p]) for p in sorted(book.asks)[:self.levels])
        age = ts_ms - self._applied_ms.get(symbol, ts_ms)
        bid_qty = book.bids.get(bid, 0.0)
        ask_qty = book.asks.get(ask, 0.0)
        denom = bid_qty + ask_qty
        return BookView(
            symbol=symbol, ts_ms=ts_ms, bids=top_bids, asks=top_asks,
            levels=self.levels, sync_age_ms=age,
            last_update_id=state.last_update_id,
            quality="clean" if age <= self.stale_after_ms else "stale",
            spread_bps=book.spread_bps(),
            imbalance_top1=(bid_qty - ask_qty) / denom if denom > 0 else None,
        ), ""

    def _flow_view(self, symbol: str) -> tuple[FlowView2 | None, str]:
        state = self._flow.get(symbol)
        if state is None or (not state["trades"] and state["closed"] is None):
            return None, "flow:no-trades-yet"
        closed = state["closed"]
        if closed is None:
            return None, "flow:window-incomplete"
        agg, reason, completeness = closed
        if agg is None:
            return None, reason
        return FlowView2(
            symbol=symbol, window_start_ms=agg["window_start_ms"],
            window_end_ms=agg["window_start_ms"] + 1000,
            buy_notional=agg["buy_notional"], sell_notional=agg["sell_notional"],
            buy_count=agg["buy_count"], sell_count=agg["sell_count"],
            total_qty=agg["total_qty"], vwap=agg["vwap"], last_id=agg["last_id"],
            completeness=completeness,
        ), ""


def book_flow_for(
    symbol: str, ts_ms: int, depth_store: DepthStore
) -> tuple[BookView | None, FlowView2 | None, str]:
    """B4 seam: as-of book/flow views from a :class:`DepthStore`."""
    return depth_store.book_flow_for(symbol, ts_ms)
