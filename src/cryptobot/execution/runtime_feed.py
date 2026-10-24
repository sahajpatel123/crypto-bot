"""Market-data stream pump: file/live events -> engine + views + funding (W2, E-008).

The pump is the runtime half of the data bridge: every normalized record is
fed to the paper engine (quotes/trades/book deltas for true taker-cross
fills), depth/flow views are computed under sync/quality gating (never
fabricated), and engine-owned funding events are split out for the ledger.
Heartbeats advance engine time so stops/GTD expire in quiet markets.

File mode consumes :func:`cryptobot.market_data.bridge.iter_market_stream`
items (persisted snapshots + sync boundaries); live mode maintains its own
books with REST snapshots on the collector's re-buffer-then-install protocol.

Economic-path guard: the pump only drives ``nautilus-paper`` engines — the
reference/fake venue is replay-harness-only and must never price fills.
"""
from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptobot.app.engine import EngineEvent, EngineFunding
from cryptobot.market_data.bridge import StreamBook, StreamItem, book_features, flow_window
from cryptobot.market_data.depth import DepthBook
from cryptobot.market_data.discovery import FAPI_BASE_URL, urllib_json_get

__all__ = ["PumpTick", "StreamPump"]


@dataclass
class PumpTick:
    record: dict[str, Any] | None  # None on idle-heartbeat ticks.
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
        rest_get: Callable | None = None,
        snapshot_limit: int = 1000,
    ) -> None:
        """Engine: nautilus-paper engine (note_event/poll/advance_to).

        Funding settles inside the engine from markPrice terms against its
        own cache positions; the pump only splits funding events out for the
        ledger. Reference/fake engines are refused (economic-path guard).
        """
        label = getattr(engine, "model_label", None)
        if label != "nautilus-paper":
            raise ValueError(
                f"StreamPump refuses engine {label!r}: live and replay economic "
                "paths run nautilus-paper only (reference/fake venues are "
                "replay-harness-only and must never price fills)")
        self.engine = engine
        self._rest_get = rest_get or urllib_json_get
        self._snapshot_limit = snapshot_limit
        self._books: dict[str, StreamBook] = {}  # live mode only.
        self._snap_due: dict[str, float] = {}  # live mode: symbol -> wall deadline.
        self._flow: dict[str, dict[str, Any]] = {}  # symbol -> window/trades/prev_last_id.
        self.stats: dict[str, int] = {
            "records": 0, "heartbeats": 0, "engine_events": 0, "funding": 0,
            "depth_ok": 0, "depth_missing": 0, "flow_ok": 0, "flow_missing": 0,
        }

    # -- file mode (persisted snapshots + boundaries) ---------------------------
    def pump_stream(self, items: Iterable[StreamItem]) -> Iterator[PumpTick]:
        for item in items:
            yield self._handle(item.record, item.books.get(str(item.record.get("symbol", ""))))

    # -- live mode (own books, REST snapshots) -----------------------------------
    def pump_live(self, records: Iterable[dict[str, Any] | None],
                  *, replay: bool = False) -> Iterator[PumpTick]:
        """Live records with B3 idle heartbeats (``None``): time advances, no views.

        ``replay=True`` replays dataset streams on the virtual clock: each
        ``None`` advances exactly one virtual second from the engine clock
        (dataset contract). Live default advances to wall-now. Replaying
        with the live default would jump the clock to wall time.

        Replay is strictly offline: REST book snapshots are skipped, so
        books stay unsynced (honest ``depth:unsynced-no-snapshot``) and no
        live state can contaminate the replay (manager integration fix).
        """
        for record in records:
            if record is None:
                if not replay:
                    self._snapshot_due_check()
                yield self._handle_heartbeat(replay=replay)
                continue
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
            if not replay:
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
        self.stats["records"] += 1
        # Engine feed first (matching advances on this record's data)...
        self.engine.note_event(record)
        engine_events = list(self.engine.poll())
        # ...then views against post-record state; funding splits out for the ledger.
        funding = [e.payload for e in engine_events if e.kind == "funding"]
        engine_events = [e for e in engine_events if e.kind != "funding"]
        self.stats["engine_events"] += len(engine_events)
        self.stats["funding"] += len(funding)
        depth, depth_reason = book_features(entry) if entry is not None else (None, "depth:symbol-not-captured")
        flow, flow_reason = self._flow_for(symbol, record)
        self.stats["depth_ok" if depth is not None else "depth_missing"] += 1
        self.stats["flow_ok" if flow is not None else "flow_missing"] += 1
        return PumpTick(record, engine_events, funding, depth, depth_reason, flow, flow_reason)

    def _handle_heartbeat(self, record: None = None, *,
                          replay: bool = False) -> PumpTick:
        """Heartbeat (B3 ``None``): advance engine time, drain, no views."""
        self.stats["records"] += 1
        self.stats["heartbeats"] += 1
        target = (self.engine.now_utc + timedelta(seconds=1) if replay
                  else datetime.now(UTC))
        with contextlib.suppress(ValueError):  # heartbeat behind the engine clock: nothing to advance.
            self.engine.advance_to(target)
        engine_events = list(self.engine.poll())
        funding = [e.payload for e in engine_events if e.kind == "funding"]
        engine_events = [e for e in engine_events if e.kind != "funding"]
        self.stats["engine_events"] += len(engine_events)
        self.stats["funding"] += len(funding)
        self.stats["depth_missing"] += 1
        self.stats["flow_missing"] += 1
        return PumpTick(None, engine_events, funding, None, "depth:heartbeat",
                        None, "flow:heartbeat")

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
