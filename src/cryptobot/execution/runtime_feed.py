"""Market-data stream pump: file/live events -> engine + views + funding (W2, E-007).

The pump is the runtime half of the data bridge: every normalized record is
fed to the paper engine (quotes/trades/book deltas for true taker-cross
fills), depth/flow views are computed under sync/quality gating (never
fabricated), and funding cash flows settle when stream time crosses the
venue's funding time while a position is open.

File mode consumes :func:`cryptobot.market_data.bridge.iter_market_stream`
items (persisted snapshots + sync boundaries); live mode maintains its own
books with REST snapshots on the collector's re-buffer-then-install protocol.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

from cryptobot.app.engine import EngineEvent, EngineFunding
from cryptobot.market_data.bridge import StreamBook, StreamItem, book_features, flow_window
from cryptobot.market_data.depth import DepthBook
from cryptobot.market_data.discovery import FAPI_BASE_URL, urllib_json_get

__all__ = ["PumpTick", "StreamPump"]

_FUNDING_INTERVAL_MS = 8 * 3600 * 1000


@dataclass
class PumpTick:
    record: dict[str, Any]
    engine_events: list[EngineEvent] = field(default_factory=list)
    funding: list[EngineFunding] = field(default_factory=list)
    depth: dict[str, Any] | None = None
    depth_reason: str = ""
    flow: dict[str, Any] | None = None
    flow_reason: str = ""


class StreamPump:
    def __init__(
        self,
        engine: Any,
        *,
        position_of: Callable[[str], tuple[float, float]] | None = None,
        rest_get: Callable | None = None,
        snapshot_limit: int = 1000,
    ) -> None:
        """Engine: S3 paper engine (note_event/poll/latest_mark). position_of:
        symbol -> (open qty, ref price) for funding settlement (None = flat)."""
        self.engine = engine
        self._position_of = position_of
        self._rest_get = rest_get or urllib_json_get
        self._snapshot_limit = snapshot_limit
        self._books: dict[str, StreamBook] = {}  # live mode only.
        self._snap_due: dict[str, float] = {}  # live mode: symbol -> wall deadline.
        self._funding: dict[str, dict[str, Any]] = {}  # symbol -> rate/next/last_settled.
        self._flow: dict[str, dict[str, Any]] = {}  # symbol -> window/trades/prev_last_id.

    # -- file mode (persisted snapshots + boundaries) ---------------------------
    def pump_stream(self, items: Iterable[StreamItem]) -> Iterator[PumpTick]:
        for item in items:
            yield self._handle(item.record, item.books.get(str(item.record.get("symbol", ""))))

    # -- live mode (own books, REST snapshots) -----------------------------------
    def pump_live(self, records: Iterable[dict[str, Any]]) -> Iterator[PumpTick]:
        for record in records:
            symbol = str(record.get("symbol", ""))
            entry = self._books.get(symbol)
            if entry is None:
                entry = self._books[symbol] = StreamBook(DepthBook(symbol))
                self._snap_due[symbol] = time.monotonic()  # sync ASAP.
            if record.get("channel") == "depth":
                payload = record["payload"]
                outcome = entry.book.on_diff({
                    "first_update": payload["first_update"],
                    "last_update": payload["last_update"],
                    "prev_last_update": payload["prev_last_update"],
                    "bids": payload["bids"],
                    "asks": payload["asks"],
                })
                if outcome == "applied":
                    entry.last_applied_ms = int(record["exchange_ts_ms"])
                elif outcome == "resync":
                    entry.book.request_resync("chain-break")
                    # Re-buffer before reinstalling (collector protocol): diffs
                    # arriving during the window queue in the unsynced book, so
                    # the snapshot install can drop stale ones and span cleanly.
                    self._snap_due[symbol] = time.monotonic() + 2.5
            self._snapshot_due_check()
            yield self._handle(record, entry)

    def _snapshot_due_check(self) -> None:
        now = time.monotonic()
        for symbol in list(self._snap_due):
            if now < self._snap_due[symbol]:
                continue
            del self._snap_due[symbol]
            entry = self._books[symbol]
            try:
                payload, _ = self._rest_get(
                    f"{FAPI_BASE_URL}/fapi/v1/depth?symbol={symbol}"
                    f"&limit={self._snapshot_limit}", 15.0)
            except Exception:
                self._snap_due[symbol] = now + 5.0  # retry shortly, never die.
                continue
            try:
                outcome = entry.book.on_snapshot(payload["bids"], payload["asks"],
                                                 payload["lastUpdateId"])
            except (KeyError, TypeError, ValueError):
                self._snap_due[symbol] = now + 5.0  # garbage: re-buffer, retry.
                continue
            if outcome == "synced":
                entry.ever_synced = True
                entry.last_applied_ms = int(time.time() * 1000)
            else:
                self._snap_due[symbol] = now + 2.5  # genuine gap; re-buffer, retry.

    # -- shared per-record handling -------------------------------------------------
    def _handle(self, record: dict[str, Any], entry: StreamBook | None) -> PumpTick:
        symbol = str(record.get("symbol", ""))
        channel = record.get("channel")
        if channel == "markPrice":
            self._note_funding_terms(symbol, record["payload"])
        # Engine feed first (matching advances on this record's data)...
        if hasattr(self.engine, "note_event"):
            self.engine.note_event(record)
        engine_events = list(self.engine.poll())
        # ...then views and funding settle against post-record state.
        depth, depth_reason = book_features(entry) if entry is not None else (None, "depth:symbol-not-captured")
        flow, flow_reason = self._flow_for(symbol, record)
        funding = self._settle_funding(symbol, int(record.get("exchange_ts_ms", 0) or 0))
        return PumpTick(record, engine_events, funding, depth, depth_reason, flow, flow_reason)

    def _note_funding_terms(self, symbol: str, payload: dict[str, Any]) -> None:
        state = self._funding.setdefault(symbol, {"rate": 0.0, "next_ms": 0,
                                                  "settled_ms": 0})
        try:
            state["rate"] = float(payload.get("funding_rate", 0.0) or 0.0)
            state["next_ms"] = int(payload.get("next_funding_ms", 0) or 0)
        except (TypeError, ValueError):
            pass  # malformed terms: keep the last known, never invent.

    def _settle_funding(self, symbol: str, now_ms: int) -> list[EngineFunding]:
        state = self._funding.get(symbol)
        if not state or not state["next_ms"] or now_ms < state["next_ms"]:
            return []
        if state["settled_ms"] >= state["next_ms"]:
            return []  # already settled this funding time.
        state["settled_ms"] = state["next_ms"]
        if self._position_of is None:
            return []
        qty, ref = self._position_of(symbol)
        rate = state["rate"]
        if qty == 0.0 or rate == 0.0 or ref <= 0:
            return []  # flat/zero-rate: no cash flow, nothing to book.
        amount = -qty * ref * rate  # rate>0: longs pay.
        if amount == 0.0:
            return []
        funding_ms = state["next_ms"]
        # Project the next funding time; the venue's next markPrice confirms it.
        state["next_ms"] = funding_ms + _FUNDING_INTERVAL_MS
        from datetime import datetime, timezone
        ts_utc = datetime.fromtimestamp(funding_ms / 1000, tz=timezone.utc)
        return [EngineFunding(event_id=f"funding:{symbol}:{funding_ms}",
                              instrument=symbol, amount=amount, ts_utc=ts_utc)]

    def _flow_for(self, symbol: str, record: dict[str, Any]) -> tuple[dict | None, str]:
        """Flow view: the just-closed 1 s window when a trade rolls it, else missing."""
        if record.get("channel") != "aggTrade":
            return None, "flow:window-incomplete"
        payload = record["payload"]
        trade_ms = int(payload.get("trade_ts_ms", record.get("exchange_ts_ms", 0)) or 0)
        window = trade_ms // 1000 * 1000
        state = self._flow.setdefault(symbol, {"window": window, "trades": [],
                                               "prev_last_id": None})
        if window == state["window"]:
            state["trades"].append(payload)
            return None, "flow:window-incomplete"
        closed, reason_holder = state["trades"], state["prev_last_id"]
        agg, reason = flow_window(closed, state["window"], prev_last_id=reason_holder)
        if agg is not None:
            state["prev_last_id"] = agg["last_id"]
        elif closed:
            state["prev_last_id"] = int(closed[-1]["last_id"])  # gap: resync chain.
        state["window"], state["trades"] = window, [payload]
        return agg, reason
