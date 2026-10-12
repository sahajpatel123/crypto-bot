"""Deterministic reference paper engine over OrderManager+FakeVenue (manager-owned).

REPLAY/TESTS ONLY. Paper mode refuses this engine (see config validation).
It exercises the real lifecycle/protection/recovery mechanics with modeled,
labeled taker fees — it does NOT model depth-crossing, queue position, or
venue matching. E-007's Nautilus adapter is the economic paper path.

Simulator assumptions (logged at startup AND in every session report):
- entries are MARKET (taker) filled immediately at the latest noted mark;
- submissions are delayed by submit_delay_ms (pending queue, real);
- fills are immediate at mark (no fill-delay simulation);
- fees are modeled: qty*price*taker_bps/1e4, labeled by config fee_label;
- stop/target legs are independent reduce-only STOP_MARKET/TAKE_PROFIT_MARKET
  orders verified individually (no native OCO assumption).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cryptobot.execution import FakeVenue, OrderManager

from .engine import (EngineCancel, EngineEvent, EngineExpire, EngineFill,
                     EngineOrder, EngineReject)

__all__ = ["ReferenceEngine", "SIMULATOR_ASSUMPTIONS"]

SIMULATOR_ASSUMPTIONS = (
    "reference-engine: MARKET entries fill immediately at latest mark; "
    "submit delayed by submit_delay_ms; fills immediate (no fill-delay sim); "
    "modeled taker fee qty*price*taker_bps/1e4; independent reduce-only "
    "stop/target legs, no native OCO.",
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class _FeeShim:
    """RiskOutcomeSink that substitutes the modeled fee before forwarding.

    OrderManager books venue deltas with fee 0.0; the shim forwards each
    delta to the real policy sink with the modeled taker fee so the bound
    ledger books the fill exactly once WITH the labeled cost. No double
    booking: the shim is the manager's only sink.
    """

    def __init__(self, sink: Any, taker_bps: float, on_fill: Callable[[dict], None]) -> None:
        self._sink = sink
        self._taker_bps = taker_bps
        self._on_fill = on_fill

    def note_fill_delta(self, reservation_id: str, exec_id: str, symbol: str,
                        venue_side: str, qty: float, price: float,
                        fee: float, ts_utc: str) -> None:
        del fee  # venue models no fee; substitute the labeled modeled fee.
        modeled = abs(qty) * price * self._taker_bps / 10_000.0
        self._sink.note_fill_delta(reservation_id, exec_id, symbol, venue_side,
                                   qty, price, modeled, ts_utc)
        self._on_fill({"exec_id": exec_id, "symbol": symbol, "side": venue_side,
                       "qty": qty, "price": price, "fee": modeled, "ts_utc": ts_utc})

    def note_fill(self, reservation_id: str) -> None:
        self._sink.note_fill(reservation_id)

    def release(self, reservation_id: str) -> bool:
        return self._sink.release(reservation_id)

    def note_flat(self) -> None:
        self._sink.note_flat()


class ReferenceEngine:
    """PaperEngine over the shared OrderManager + FakeVenue."""

    model_label = "reference-fake-venue"

    def __init__(self, *, log_path: str | Path, outcome_sink: Any,
                 taker_bps: float,
                 now_utc: Callable[[], datetime] | None = None,
                 submit_delay_ms: int = 0) -> None:
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.venue = FakeVenue(now_ms=lambda: int(
            self._now_utc().timestamp() * 1000))
        self._fills: deque[dict] = deque()
        shim = _FeeShim(outcome_sink, taker_bps, self._fills.append)
        self.manager = OrderManager(self.venue, log_path=log_path,
                                    now_utc=self._now_utc, outcome_sink=shim)
        self._pending: deque[tuple[float, EngineOrder, str]] = deque()
        self._submit_delay_s = max(0, submit_delay_ms) / 1000.0
        self._client_role: dict[str, str] = {}
        self._marks: dict[str, float] = {}
        self._pre2real: dict[str, str] = {}

    @property
    def assumptions(self) -> tuple[str, ...]:
        return SIMULATOR_ASSUMPTIONS

    # -- PaperEngine ------------------------------------------------------
    def submit(self, cmd: EngineOrder) -> str:
        if cmd.qty <= 0:
            raise ValueError("qty must be > 0")
        pre_id = self.manager.new_client_id("ref")
        due = self._now_utc().timestamp() + self._submit_delay_s
        self._pending.append((due, cmd, pre_id))
        self._drain_pending()
        return pre_id

    def resolve(self, client_id: str) -> str | None:
        """Map a submit-time pre-id to the durable manager id (None if queued)."""
        if client_id in self.manager.orders:
            return client_id
        return self._pre2real.get(client_id)

    def _drain_pending(self) -> None:
        now_ts = self._now_utc().timestamp()
        while self._pending and self._pending[0][0] <= now_ts:
            _, cmd, pre_id = self._pending.popleft()
            self._pre2real[pre_id] = self._submit_now(cmd)

    def _submit_now(self, cmd: EngineOrder) -> str:
        if cmd.kind == "MARKET":
            if cmd.instrument not in self._marks:
                raise ValueError(f"no mark for MARKET submit on {cmd.instrument}")
            self.venue.set_last_price(cmd.instrument, self._marks[cmd.instrument])
            order = self.manager._submit(
                cmd.instrument, cmd.side, cmd.qty, "MARKET",
                price=self._marks.get(cmd.instrument),
                role=cmd.role, reservation_id=cmd.reservation_id)
        elif cmd.kind == "LIMIT":
            if cmd.price is None:
                raise ValueError("LIMIT submit needs price")
            order = self.manager.submit_entry(
                cmd.instrument, "LONG" if cmd.side == "BUY" else "SHORT",
                cmd.qty, cmd.price,
                expire_at_utc=cmd.expire_at_utc or self._now_utc(),
                kind="LIMIT", reservation_id=cmd.reservation_id)
        elif cmd.kind in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            if cmd.stop_price is None:
                raise ValueError(f"{cmd.kind} submit needs stop_price")
            order = self.manager._submit(
                cmd.instrument, cmd.side, cmd.qty, cmd.kind,
                price=None, stop_price=cmd.stop_price,
                role="stop" if cmd.kind == "STOP_MARKET" else "target",
                reservation_id=cmd.reservation_id)
        else:
            raise ValueError(f"unsupported order kind {cmd.kind!r}")
        self._client_role[order.client_id] = cmd.role
        self.manager._evaluate_callbacks()
        return order.client_id

    def submit_sync(self, cmd: EngineOrder) -> str:
        """Submit bypassing the delay queue (time-exits, flatten)."""
        return self._submit_now(cmd)

    def attach_protection(self, entry_client_id: str, stop_price: float,
                          target_price: float | None) -> list[str]:
        """Independent reduce-only legs sized to filled qty (verified individually)."""
        entry = self.manager.orders[entry_client_id]
        legs: list[str] = []
        if target_price is None:
            stop = self.manager._submit(
                entry.symbol, "SELL" if entry.venue_side == "BUY" else "BUY",
                min(entry.filled_qty, entry.qty), "STOP_MARKET",
                price=None, stop_price=stop_price, role="stop",
                group_id=f"grp-{entry.client_id}",
                reservation_id=entry.reservation_id)
            self.manager.reconcile(stop.client_id)
            return [stop.client_id]
        stop, target = self.manager.attach_siblings(
            entry, stop_price=stop_price, target_price=target_price)
        return [stop.client_id, target.client_id]

    def cancel(self, client_order_id: str, reason: str) -> None:
        real = self.resolve(client_order_id)
        if real is None:
            self._pending = deque(
                (due, cmd, pre) for due, cmd, pre in self._pending
                if pre != client_order_id)
            return
        self.venue.cancel(real)
        self.manager._log(real, "cancel-request", {"reason": reason})

    def poll(self) -> list[EngineEvent]:
        self._drain_pending()
        out: list[EngineEvent] = []
        for record in self.manager.poll():
            event = record.get("event", "")
            cid = record.get("client_id", "")
            order = self.manager.orders.get(cid)
            ts = self._now_utc()
            if event == "expired" and order is not None:
                out.append(EngineEvent("expire", EngineExpire(
                    cid, order.symbol, "entry-expired", ts), ts))
            elif event.startswith("state:") and event.endswith("->cancelled") and order is not None:
                out.append(EngineEvent("cancel", EngineCancel(
                    cid, order.symbol, "cancelled", ts), ts))
            elif event.startswith("state:") and event.endswith("->rejected") and order is not None:
                out.append(EngineEvent("reject", EngineReject(
                    cid, order.symbol, "venue-rejected", ts), ts))
        while self._fills:
            f = self._fills.popleft()
            cid = f["exec_id"].split(":fill:")[0]
            order = self.manager.orders.get(cid)
            ts = datetime.fromisoformat(f["ts_utc"])
            out.append(EngineEvent("fill", EngineFill(
                execution_id=f["exec_id"], client_order_id=cid,
                instrument=f["symbol"], side=f["side"], qty=f["qty"],
                price=f["price"], fee=f["fee"], ts_utc=ts,
                liquidity="taker"), ts))
            del order
        return out

    def note_mark(self, instrument: str, price: float) -> None:
        if price > 0:
            self._marks[instrument] = price
            self.venue.set_last_price(instrument, price)

    def set_exit_only(self, halted: bool, reason: str = "") -> None:
        self.manager.set_halted(halted, reason)

    def close(self) -> None:
        self._pending.clear()
