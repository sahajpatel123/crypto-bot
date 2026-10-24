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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptobot.execution import FakeVenue, OrderManager

from .engine import (
    EngineCancel,
    EngineEvent,
    EngineExpire,
    EngineFill,
    EngineOrder,
    EngineOrderStatus,
    EngineReject,
)

__all__ = ["ReferenceEngine", "SIMULATOR_ASSUMPTIONS"]

SIMULATOR_ASSUMPTIONS = (
    "reference-engine: MARKET entries fill immediately at latest mark; "
    "submit delayed by submit_delay_ms; fills immediate (no fill-delay sim); "
    "modeled taker fee qty*price*taker_bps/1e4; independent reduce-only "
    "stop/target legs, no native OCO.",
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class _FeeShim:
    """RiskOutcomeSink that substitutes the modeled fee before forwarding.

    OrderManager books venue deltas with fee 0.0; the shim forwards each
    delta to the real policy sink with the modeled taker fee so the bound
    ledger books the fill exactly once WITH the labeled cost. No double
    booking: the shim is the manager's only sink.

    Contract v1 (W1): a None sink makes the shim record-only — fills
    queue as EngineEvents for the bound Session handler, and the
    adapter never mutates application state directly.
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
        if self._sink is not None:
            self._sink.note_fill_delta(reservation_id, exec_id, symbol, venue_side,
                                       qty, price, modeled, ts_utc)
        self._on_fill({"exec_id": exec_id, "symbol": symbol, "side": venue_side,
                       "qty": qty, "price": price, "fee": modeled, "ts_utc": ts_utc})

    def note_fill(self, reservation_id: str) -> None:
        if self._sink is not None:
            self._sink.note_fill(reservation_id)

    def release(self, reservation_id: str) -> bool:
        if self._sink is None:
            return False
        return self._sink.release(reservation_id)

    def note_flat(self) -> None:
        if self._sink is not None:
            self._sink.note_flat()


class ReferenceEngine:
    """PaperEngine over the shared OrderManager + FakeVenue."""

    model_label = "reference-fake-venue"

    def __init__(self, *, log_path: str | Path, outcome_sink: Any,
                 taker_bps: float,
                 now_utc: Callable[[], datetime] | None = None,
                 submit_delay_ms: int = 0) -> None:
        self._now_utc = now_utc or (lambda: datetime.now(UTC))
        self._log_path = Path(log_path)
        self._taker_bps = taker_bps
        self.venue = FakeVenue(now_ms=lambda: int(
            self._now_utc().timestamp() * 1000))
        self._fills: deque[dict] = deque()
        shim = _FeeShim(outcome_sink, taker_bps, self._record_fill)
        self.manager = OrderManager(self.venue, log_path=log_path,
                                    now_utc=self._now_utc, outcome_sink=shim)
        self._pending: deque[tuple[float, EngineOrder, str]] = deque()
        self._submit_delay_s = max(0, submit_delay_ms) / 1000.0
        self._client_role: dict[str, str] = {}
        self._marks: dict[str, float] = {}
        self._pre2real: dict[str, str] = {}
        self._fills_queued: set[str] = set()
        self._exit_only_reasons: set[str] = set()
        # Contract v1 (W1): bound Session handler (push delivery),
        # per-order observed versions, and last observed (state, filled)
        # for version bumps.
        self._bound: Any | None = None
        self._versions: dict[str, int] = {}
        self._last_obs: dict[str, tuple[str, float]] = {}

    @property
    def assumptions(self) -> tuple[str, ...]:
        return SIMULATOR_ASSUMPTIONS

    def _record_fill(self, record: dict) -> None:
        """Queue one fill record for poll/push (exec-deduped)."""
        exec_id = record.get("exec_id", "")
        if exec_id in self._fills_queued:
            return
        self._fills_queued.add(exec_id)
        self._fills.append(record)

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
            real = self._submit_now(cmd)
            self._pre2real[pre_id] = real
            # Durable alias: submit-time ids resolve after restart.
            self.manager._log(real, "pre-mapped", {"pre_id": pre_id})

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

    def submit_immediate(self, cmd: EngineOrder) -> str:
        """Submit bypassing the delay queue. Exits/flatten ONLY, never entries."""
        if cmd.role == "entry":
            raise ValueError("submit_immediate is exits-only; entries use submit()")
        return self._submit_now(cmd)

    def submit_protected(self, cmd: EngineOrder, limit_price: float) -> str:
        """Not supported: the reference engine is a fault-test tool, and
        price-protected IOC entries exist only on the economic path."""
        raise NotImplementedError(
            "reference engine has no protected IOC (non-economic tool)")

    def bind_sink(self, handler: Any) -> None:
        """Register the Session execution-event handler (contract v1 §2).

        While bound, poll() pushes every emission to the handler and
        returns [] (steady-state push); unbound, poll() returns events
        (pre-binding drain). Rebinding replaces the previous handler.
        """
        self._bound = handler

    def open_orders(self) -> list[EngineOrderStatus]:
        """Currently-open/partial bot orders ONLY (contract v1 §2).

        Terminal orders are tracked truth via order_status(), never
        inferred from absence here.
        """
        return [self._status_of(o.client_id)
                for o in self.manager.orders.values()
                if o.state.value in ("open", "partial")]

    def order_status(self, client_order_id: str) -> EngineOrderStatus | None:
        """Tracked order truth incl. terminal states (contract v1 §2).

        None ONLY when the id was never seen. Versions rise
        monotonically per order on every observed transition.
        """
        real = self.resolve(client_order_id)
        if real is None or real not in self.manager.orders:
            return None
        return self._status_of(real)

    def _status_of(self, client_id: str) -> EngineOrderStatus:
        order = self.manager.orders[client_id]
        obs = (order.state.value, float(order.filled_qty or 0.0))
        if self._last_obs.get(client_id) != obs:
            self._last_obs[client_id] = obs
            self._versions[client_id] = self._versions.get(client_id, 0) + 1
        return EngineOrderStatus(
            client_order_id=order.client_id, instrument=order.symbol,
            state=order.state.value, qty=order.qty,
            filled_qty=order.filled_qty,
            reservation_id=order.reservation_id, role=order.role,
            version=self._versions.get(client_id, 0))

    def unknown_ids(self) -> tuple[str, ...]:
        """Tracked ids needing lookup. Reference never has unknowns."""
        return ()

    def account_snapshot(self) -> None:
        """Venue account truth. Reference models no margin account.

        None = unknown (never flat by itself): the Session falls back
        to ledger-derived equity and order truth for the venue leg.
        """
        return None

    def filled_qty(self, client_order_id: str) -> float:
        real = self.resolve(client_order_id)
        order = self.manager.orders.get(real or "")
        return order.filled_qty if order is not None else 0.0

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
        return self._drain_events()

    def _drain_events(self) -> list[EngineEvent]:
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
            self._fills_queued.discard(f.get("exec_id", ""))
            cid = f["exec_id"].split(":fill:")[0]
            order = self.manager.orders.get(cid)
            ts = datetime.fromisoformat(f["ts_utc"])
            out.append(EngineEvent("fill", EngineFill(
                execution_id=f["exec_id"], client_order_id=cid,
                instrument=f["symbol"], side=f["side"], qty=f["qty"],
                price=f["price"], fee=f["fee"], ts_utc=ts,
                liquidity="taker"), ts))
            del order
        if self._bound is not None:
            # Steady-state push (contract v1 §2/§3): every emission
            # goes to the bound Session handler; nothing left to drain.
            for event in out:
                self._bound(event)
            return []
        return out

    def note_mark(self, instrument: str, price: float) -> None:
        if price > 0:
            self._marks[instrument] = price
            self.venue.set_last_price(instrument, price)

    def account_margin(self) -> tuple[float, float] | None:
        # Fault-test engine: no margin account modelled; the sizing
        # margin gate skips (leverage cap still applies).
        return None

    def valuation_mark_ts(self, instrument: str) -> datetime | None:
        # Fault-test engine: marks are simulation inputs without
        # observation times; Session falls back to feed marks.
        return None

    def recover(self, outcome_sink: Any) -> None:
        """Rebuild the OrderManager from its journal (durable source).

        Contract v1 (W1): recovery-adopted fills queue as EngineEvents
        for the bound Session handler (or poll); the adapter never
        books into application state directly. outcome_sink is kept
        for protocol compatibility and ignored.

        Durability: the in-memory fill queue does not survive a crash,
        so every journaled fill-delta re-queues here (exec-deduped;
        the Session's exec gate makes redelivery a safe no-op). The
        OrderManager "delta-propagated" mark means "handed to the
        sink interface", not "applied" — never a replay filter here.
        """
        del outcome_sink
        self.manager = OrderManager.recover(
            self.venue, self._log_path, now_utc=self._now_utc,
            outcome_sink=_FeeShim(None, self._taker_bps,
                                  self._record_fill))
        self._requeue_journaled_fills()

    def _read_journal(self) -> list[dict]:
        """Parse durable journal entries (best-effort, skips corrupt)."""
        if not self._log_path.exists():
            return []
        import json as _json
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries = []
        for line in lines:
            if not line.strip():
                continue
            try:
                entries.append(_json.loads(line))
            except ValueError:
                continue
        return entries

    def _requeue_journaled_fills(self) -> None:
        """Re-queue every journaled fill-delta after recover (v1 §4)."""
        for entry in self._read_journal():
            if entry.get("event") == "pre-mapped":
                pre = entry.get("detail", {}).get("pre_id", "")
                real = entry.get("client_id", "")
                if pre and real:
                    self._pre2real[pre] = real
                continue
            if entry.get("event") != "fill-delta":
                continue
            detail = entry.get("detail", {})
            exec_id = detail.get("exec_id", "")
            if not exec_id:
                continue
            qty = detail.get("qty_delta", 0.0) or 0.0
            price = detail.get("price", 0.0) or 0.0
            self._record_fill({
                "exec_id": exec_id, "symbol": detail.get("symbol", ""),
                "side": detail.get("venue_side", ""),
                "qty": qty, "price": price,
                "fee": abs(qty) * price * self._taker_bps / 10_000.0,
                "ts_utc": detail.get("ts_utc", "")})

    def exit_only_reasons(self) -> tuple[str, ...]:
        """Held halt reasons, sorted (R3 halt independence)."""
        return tuple(sorted(self._exit_only_reasons))

    def set_exit_only(self, halted: bool, reason: str = "") -> None:
        """Reason-keyed halt (R3): lifting clears ONLY that reason.

        The OrderManager keeps its persisted bool semantics; this
        layer owns the reason set and mirrors the level down.
        """
        if halted:
            self._exit_only_reasons.add(reason or "unspecified")
        elif reason:
            self._exit_only_reasons.discard(reason)
        else:
            self._exit_only_reasons.clear()
        self.manager.set_halted(bool(self._exit_only_reasons),
                                reason or ",".join(
                                    sorted(self._exit_only_reasons)))

    def close(self) -> None:
        self._pending.clear()
