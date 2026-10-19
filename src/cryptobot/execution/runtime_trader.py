"""Runtime trader: reservations, protection, and recovery over the S3 engine (W2, E-007).

Ports the OrderManager lifecycle semantics (fill-first conversion, independent
stop/target legs, sibling settle, top-up bounds, overfill freeze, expiry
settle windows, level-triggered halt, exactly-once callbacks, restart
recovery) from the query-shaped FakeVenue to the event-driven canonical
:class:`cryptobot.app.engine.PaperEngine` seam. Fills book to risk/ledger
with the simulator's real fee exactly once per execution_id.

Restart honesty: simulator orders are in-memory — a fresh engine holds none.
Recovery therefore never invents fills or flats: logged fills stand, live
orders unknown to the new engine are marked lost-on-restart, and reservations
with logged-but-unflattened exposure are flagged for an explicit re-decision
instead of auto-closing against a phantom position.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cryptobot.app.engine import EngineEvent, EngineFill, EngineOrder
from cryptobot.coordination import RiskOutcomeSink

__all__ = ["RuntimeTrader"]

# Contract-v1 seam states that can still fill or change (filled /
# rejected / cancelled / expired are terminal; unknown is conservatively
# live: an unresolved order may still fill).
LIVE_STATUSES = frozenset({"open", "partial", "unknown"})

_EPS = 1e-12
_TOPUP_BOUND = 5
_ENGINE_HALT_REASON = "runtime-trader"


class RuntimeTrader:
    def __init__(
        self,
        engine: Any,
        *,
        log_path: str | Path,
        ledger: Any | None = None,
        outcome_sink: RiskOutcomeSink | None = None,
        now_utc: Callable[[], datetime] | None = None,
        exit_only: bool = False,
        expiry_settle_polls: int = 2,
    ) -> None:
        self.engine = engine
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger
        self.outcome_sink = outcome_sink
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.exit_only = exit_only
        self.expiry_settle_polls = expiry_settle_polls
        self._client_reservation: dict[str, str] = {}  # client id -> reservation.
        self._client_role: dict[str, str] = {}  # client id -> entry|stop|target|exit.
        self._entries: dict[str, list[str]] = {}  # reservation -> entry ids.
        self._legs: dict[str, dict[str, str]] = {}  # reservation -> {client id: role}.
        self._fills: dict[str, dict[str, Any]] = {}  # exec_id -> fill record.
        self._client_fills: dict[str, float] = {}  # client id -> filled qty (event-observed).
        self._terminal: dict[str, str] = {}  # client id -> cancel|reject|expire reason.
        self._settle_polls: dict[str, int] = {}  # expired entry id -> clean polls.
        self._levels: dict[str, dict[str, float | None]] = {}  # reservation -> stop/target.
        self._time_exits: dict[str, datetime] = {}  # reservation -> time_exit_utc.
        self._symbols: dict[str, str] = {}  # reservation -> symbol.
        self._sides: dict[str, str] = {}  # reservation -> entry venue side.
        self._fired: set[tuple[str, str]] = set()  # (kind, reservation); persisted.
        self._propagated: set[str] = set()  # exec_ids; persisted.
        self._frozen: set[str] = set()  # overfilled reservations; persisted.
        self._topup_attempts: dict[str, int] = {}
        self._gap_terminal: set[str] = set()
        if exit_only:
            engine.set_exit_only(True, _ENGINE_HALT_REASON)

    # -- submission ------------------------------------------------------
    def submit_entry(
        self,
        symbol: str,
        strategy_side: str,
        qty: float,
        *,
        kind: str = "MARKET",
        price: float | None = None,
        expire_at_utc: datetime | None = None,
        reservation_id: str | None = None,
    ) -> str:
        """Submit a taker entry; returns the durable client id.

        Intent-level expiry is enforced pre-submit: an entry whose window has
        passed is refused, never sent. Queued submits that outlive their
        window expire in the engine queue (never submitted late); in-sim
        MARKET/LIMIT-IOC resolve on the next data tick after submit.
        """
        if self.exit_only:
            raise PermissionError("exit-only mode refuses new entries")
        now = self._now_utc()
        if expire_at_utc is not None and now >= expire_at_utc:
            raise ValueError("entry window has passed (entry-expired pre-submit)")
        venue_side = {"LONG": "BUY", "SHORT": "SELL"}[strategy_side]
        self._log("*", "submit-intent", {"role": "entry", "symbol": symbol,
                                        "venue_side": venue_side, "kind": kind,
                                        "qty": qty, "reservation_id": reservation_id})
        client_id = self.engine.submit(EngineOrder(
            instrument=symbol, side=venue_side, qty=qty, kind=kind, price=price,
            reservation_id=reservation_id, expire_at_utc=expire_at_utc, role="entry"))
        if reservation_id is not None:
            self._client_reservation[client_id] = reservation_id
            self._entries.setdefault(reservation_id, []).append(client_id)
            self._symbols[reservation_id] = symbol
            self._sides[reservation_id] = venue_side
        self._client_role[client_id] = "entry"
        self._log(client_id, "submitted", {"role": "entry", "kind": kind,
                                          "reservation_id": reservation_id})
        self._evaluate_callbacks()
        return client_id

    def protect(self, reservation_id: str, stop_price: float,
                target_price: float | None) -> list[str]:
        """Attach independent reduce-only legs to each filled entry lacking them."""
        entries = [c for c in self._entries.get(reservation_id, [])
                   if self._client_fills.get(c, 0.0) > _EPS
                   and not any(self._client_reservation.get(leg) == reservation_id
                               for leg in self._legs.get(reservation_id, {}))]
        if not entries:
            if not any(self._client_fills.get(c, 0.0) > _EPS
                       for c in self._entries.get(reservation_id, [])):
                raise ValueError("protection attaches only to an entry with fills")
            return []  # legs already exist; never double-protect.
        if reservation_id in self._frozen:
            raise ValueError("exits frozen after overfill; no new legs")
        legs: list[str] = []
        for entry_id in entries:
            leg_ids = self.engine.attach_protection(entry_id, stop_price, target_price)
            for i, leg_id in enumerate(leg_ids):
                role = "stop" if i == 0 else "target"
                self._client_reservation[leg_id] = reservation_id
                self._client_role[leg_id] = role
                self._legs.setdefault(reservation_id, {})[leg_id] = role
                self._log(leg_id, "leg-submitted", {"role": role, "entry": entry_id,
                                                   "reservation_id": reservation_id})
            legs.extend(leg_ids)
        self._levels[reservation_id] = {"stop": stop_price, "target": target_price}
        return legs

    # -- polling -----------------------------------------------------------
    def ingest(self, events_in: list[EngineEvent]) -> list[dict[str, Any]]:
        """Process engine events drained elsewhere (pump-driven sessions)."""
        events: list[dict[str, Any]] = []
        for event in events_in:
            handled = self._handle_event(event)
            if handled is not None:
                events.append(handled)
        return events

    def poll(self) -> list[dict[str, Any]]:
        """Drain engine events, book fills, settle siblings, fire callbacks."""
        events = self.ingest(self.engine.poll())
        for client_id in list(self._terminal):
            # Late-fill watch on expired entries (cancel/fill races, report lag).
            if (self._client_role.get(client_id) == "entry"
                    and self._terminal[client_id] == "expired"):
                before = self._client_fills.get(client_id, 0.0)
                try:
                    observed = float(self.engine.filled_qty(client_id))
                except KeyError:
                    observed = before  # unknown to this engine; logged fills stand.
                if observed > before + _EPS:
                    self._log(client_id, "late-fill-observed", {"observed": observed})
                else:
                    self._settle_polls[client_id] = self._settle_polls.get(client_id, 0) + 1
        events.extend(self._settle_sibling_groups())
        events.extend(self._evaluate_callbacks())
        events.extend(self._top_up_protection())
        return events

    def _handle_event(self, event: EngineEvent) -> dict[str, Any] | None:
        payload = event.payload
        if event.kind == "fill":
            assert isinstance(payload, EngineFill)
            return self._book_fill(payload)
        client_id = getattr(payload, "client_order_id", "")
        reason = getattr(payload, "reason", event.kind)
        self._terminal[client_id] = event.kind if event.kind != "cancel" else "cancelled"
        self._log(client_id, f"terminal:{event.kind}", {"reason": reason})
        reservation = self._client_reservation.get(client_id)
        if reservation is not None and self._client_role.get(client_id) in ("stop", "target"):
            self._maybe_fallback(reservation, client_id, event.kind)
        return {"client_id": client_id, "event": f"terminal:{event.kind}"}

    def _book_fill(self, fill: EngineFill) -> dict[str, Any] | None:
        if fill.fee < 0:
            raise ValueError(f"negative fee refused: {fill.fee!r}")
        if fill.execution_id in self._fills:
            return None  # redelivered event; ledger + sink both dedup anyway.
        reservation = self._client_reservation.get(fill.client_order_id, "")
        record = {
            "exec_id": fill.execution_id, "client_id": fill.client_order_id,
            "reservation_id": reservation, "symbol": fill.instrument,
            "venue_side": fill.side, "qty": fill.qty, "price": fill.price,
            "fee": fill.fee, "ts_utc": fill.ts_utc.isoformat(),
        }
        self._fills[fill.execution_id] = record
        self._client_fills[fill.client_order_id] = (
            self._client_fills.get(fill.client_order_id, 0.0) + fill.qty)
        self._log(fill.client_order_id, "fill", record)  # fsync BEFORE the sink call.
        self._propagate_delta(record)
        return {"client_id": fill.client_order_id, "event": "fill",
                "exec_id": fill.execution_id}

    def _propagate_delta(self, record: dict[str, Any]) -> None:
        sink = self.outcome_sink
        if sink is not None and record["reservation_id"]:
            sink.note_fill_delta(record["reservation_id"], record["exec_id"],
                                 record["symbol"], record["venue_side"], record["qty"],
                                 record["price"], record["fee"], record["ts_utc"])
            self._propagated.add(record["exec_id"])
            self._log(record["client_id"], "delta-propagated",
                      {"exec_id": record["exec_id"]})
        elif self.ledger is not None and record["reservation_id"]:
            # No v0.2.0 sink: book the increment directly (same exec_id key).
            self._ledger_fill(record)
            self._propagated.add(record["exec_id"])
            self._log(record["client_id"], "delta-propagated-direct",
                      {"exec_id": record["exec_id"]})

    def _ledger_fill(self, record: dict[str, Any]) -> None:
        from datetime import datetime as _dt
        ts = _dt.fromisoformat(record["ts_utc"])
        note = getattr(self.ledger, "note_fill", None)
        if callable(note):
            # V-006 seam takes ISO-8601 str (integration fix: was datetime).
            note(record["exec_id"], record["symbol"], record["venue_side"],
                 record["qty"], record["price"], record["fee"],
                 record["ts_utc"])
        else:  # pre-V-006 ledger: identical idempotent contract via record_fill.
            self.ledger.record_fill(record["venue_side"], record["qty"], record["price"],
                                    record["fee"], ts, record["exec_id"])

    def ingest_funding(self, instrument: str, amount: float, event_id: str,
                       ts_utc: datetime) -> bool:
        """Book a funding cash flow; False when skipped (flat/zero/duplicate)."""
        if amount == 0.0:
            return False  # run-mode ledgers refuse zero funding; never propagate it.
        if self.ledger is None:
            return False
        note = getattr(self.ledger, "note_funding", None)
        if callable(note):
            # V-006 seam takes ISO-8601 str (integration fix: was datetime).
            return bool(note(event_id, amount, ts_utc.isoformat()))
        return bool(self.ledger.record_funding(amount, ts_utc, event_id))

    # -- protection lifecycle --------------------------------------------------
    def _settle_sibling_groups(self) -> list[dict[str, Any]]:
        # Reservation-wide: a fill in ANY leg cancels every other live leg of
        # the same reservation, so delayed cancels and multi-group races
        # cannot stack exits into a reversal.
        events: list[dict[str, Any]] = []
        for reservation_id, legs in self._legs.items():
            filled = [c for c in legs if self._leg_filled_qty(c) > _EPS]
            if not filled:
                continue
            for leg_id in legs:
                if leg_id in filled or leg_id in self._terminal:
                    continue
                if not self._is_live(leg_id):
                    continue
                self._log(leg_id, "cancel-intent",
                          {"reason": f"sibling-cancelled-after:{filled[0]}"})
                try:
                    self.engine.cancel(leg_id, f"sibling-cancelled-after:{filled[0]}")
                except KeyError:
                    self._terminal[leg_id] = "cancelled"  # unknown = nothing to fill.
                    self._log(leg_id, "terminal:cancel", {"reason": "unknown-to-engine"})
                    continue
                events.append({"client_id": leg_id,
                               "event": f"sibling-cancelled-after:{filled[0]}"})
        return events

    def _maybe_fallback(self, reservation_id: str, leg_id: str, kind: str) -> None:
        """A failed stop leg with live exposure falls back to a market exit.

        A failed target leg with a live stop keeps the stop (logged gap). No
        fallback fires while any exit for the reservation is still live, or
        once the reservation is flat — terminal state never implies flat, and
        a market exit is only ever submitted against measured exposure.
        """
        role = self._client_role.get(leg_id)
        _, _, net, _ = self._position_state(reservation_id)
        if abs(net) <= _EPS:
            return
        live = [c for c, r in self._legs.get(reservation_id, {}).items()
                if self._is_live(c) and c != leg_id]
        live_exits = [c for c, r in self._client_role.items()
                      if r == "exit"
                      and self._client_reservation.get(c) == reservation_id
                      and self._is_live(c)]
        if live_exits:
            return  # flatten already in flight; never stack exits.
        if role == "target" and any(self._legs[reservation_id][c] == "stop" for c in live):
            self._log("*", "target-leg-failed-keeping-stop",
                      {"reservation_id": reservation_id, "leg": leg_id, "kind": kind})
            return
        if role == "stop" or not live:
            self._flatten(reservation_id, f"protection-fallback-market:{leg_id}:{kind}")

    def _flatten(self, reservation_id: str, reason: str) -> str | None:
        _, _, net, _ = self._position_state(reservation_id)
        if abs(net) <= _EPS:
            return None
        if reservation_id in self._frozen:
            self._log("*", "flatten-refused-frozen",
                      {"reservation_id": reservation_id, "reason": reason})
            return None
        side = "SELL" if net > 0 else "BUY"
        symbol = self._symbols[reservation_id]
        self._log("*", "flatten-intent", {"reservation_id": reservation_id,
                                         "net": net, "reason": reason})
        # Flatten/exits bypass modeled delays (urgent by definition); entries never do.
        client_id = self.engine.submit_immediate(EngineOrder(
            instrument=symbol, side=side, qty=abs(net), kind="MARKET",
            reduce_only=True, reservation_id=reservation_id, role="exit"))
        self._client_reservation[client_id] = reservation_id
        self._client_role[client_id] = "exit"
        self._log(client_id, "submitted", {"role": "exit", "reason": reason,
                                          "reservation_id": reservation_id})
        return client_id

    def flatten(self, reservation_id: str, reason: str = "manual-flatten") -> str | None:
        """Cancel live legs, then market-close measured exposure (halt/time-exit path)."""
        for leg_id in self._legs.get(reservation_id, {}):
            if leg_id not in self._terminal and self._is_live(leg_id):
                self._log(leg_id, "cancel-intent", {"reason": reason})
                try:
                    self.engine.cancel(leg_id, reason)
                except KeyError:
                    self._terminal[leg_id] = "cancelled"
        return self._flatten(reservation_id, reason)

    def check_time_exits(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Flatten reservations past their time exit (caller drives with causal now)."""
        now = now or self._now_utc()
        events: list[dict[str, Any]] = []
        for reservation_id, deadline in sorted(self._time_exits.items()):
            if now < deadline:
                continue
            _, _, net, _ = self._position_state(reservation_id)
            if abs(net) <= _EPS:
                continue
            if self._reservation_resolved(reservation_id):
                continue
            client_id = self.flatten(reservation_id, "time-exit")
            del self._time_exits[reservation_id]
            events.append({"reservation_id": reservation_id, "event": "time-exit",
                           "exit_id": client_id})
        return events

    def set_time_exit(self, reservation_id: str, time_exit_utc: datetime) -> None:
        self._time_exits[reservation_id] = time_exit_utc
        self._log("*", "time-exit-armed", {"reservation_id": reservation_id,
                                          "time_exit_utc": time_exit_utc.isoformat()})

    def _top_up_protection(self) -> list[dict[str, Any]]:
        """Submit top-up leg pairs where filled entries outgrew their cover.

        Bounded: at most 5 attempts per reservation per log lifetime; then a
        terminal protection-gap record stands. Never tops up frozen, resolved,
        or leg-filled reservations.
        """
        events: list[dict[str, Any]] = []
        for reservation_id in sorted(self._entries):
            if reservation_id in self._frozen or self._reservation_resolved(reservation_id):
                continue
            legs = self._legs.get(reservation_id, {})
            if not legs or any(self._leg_filled_qty(c) > _EPS for c in legs):
                continue
            entry_filled = sum(self._client_fills.get(c, 0.0)
                               for c in self._entries[reservation_id])
            stop_cover = sum(self._leg_cover(c) for c, r in legs.items() if r == "stop")
            target_cover = sum(self._leg_cover(c) for c, r in legs.items() if r == "target")
            gap = entry_filled - min(stop_cover, target_cover)
            gap = min(gap, abs(self._position_state(reservation_id)[2]))
            if gap <= _EPS:
                continue
            attempts = self._topup_attempts.get(reservation_id, 0)
            if attempts >= _TOPUP_BOUND:
                if reservation_id not in self._gap_terminal:
                    self._gap_terminal.add(reservation_id)
                    self._log("*", "protection-gap-unresolved",
                              {"reservation_id": reservation_id, "gap": gap})
                    events.append({"reservation_id": reservation_id,
                                   "event": "protection-gap-unresolved"})
                continue
            levels = self._levels.get(reservation_id, {})
            if levels.get("stop") is None:
                continue
            self._topup_attempts[reservation_id] = attempts + 1
            self._log("*", "topup-attempt",
                      {"reservation_id": reservation_id, "gap": gap,
                       "attempt": attempts + 1})
            symbol = self._symbols[reservation_id]
            exit_side = "SELL" if self._sides[reservation_id] == "BUY" else "BUY"
            pair = [("stop", "STOP_MARKET", levels["stop"])]
            if levels.get("target") is not None:
                pair.append(("target", "TAKE_PROFIT_MARKET", levels["target"]))
            for role, kind, trigger in pair:
                leg_id = self.engine.submit(EngineOrder(
                    instrument=symbol, side=exit_side, qty=gap, kind=kind,
                    stop_price=trigger, reduce_only=True,
                    reservation_id=reservation_id, role=role))
                self._client_reservation[leg_id] = reservation_id
                self._client_role[leg_id] = role
                self._legs.setdefault(reservation_id, {})[leg_id] = role
            events.append({"reservation_id": reservation_id,
                           "event": f"protection-topup:{gap}"})
        return events

    def _leg_cover(self, leg_id: str) -> float:
        if leg_id in self._terminal:
            return self._client_fills.get(leg_id, 0.0)
        if self._is_live(leg_id):
            # Live legs cover their full order qty (measured at the engine);
            # filled legs cover what they filled.
            for status in self.engine.open_orders():
                if status.client_order_id == leg_id:
                    return status.qty
            return self._client_fills.get(leg_id, 0.0)
        return self._client_fills.get(leg_id, 0.0)

    def _leg_filled_qty(self, leg_id: str) -> float:
        return self._client_fills.get(leg_id, 0.0)

    # -- exposure and callbacks (OrderManager port) ------------------------------
    def position_net(self, reservation_id: str) -> float:
        """Signed open exposure: entry fills minus exit-leg fills."""
        return self._position_state(reservation_id)[2]

    def _position_state(self, reservation_id: str) -> tuple[float, float, float, bool]:
        entry_net = exit_net = 0.0
        for record in self._fills.values():
            if record["reservation_id"] != reservation_id:
                continue
            signed = record["qty"] if record["venue_side"] == "BUY" else -record["qty"]
            if self._client_role.get(record["client_id"]) == "entry":
                entry_net += signed
            else:
                exit_net += signed
        net = entry_net + exit_net
        overfilled = (abs(entry_net) > _EPS and abs(net) > _EPS
                      and (net > 0) != (entry_net > 0))
        return entry_net, exit_net, net, overfilled

    def _is_live(self, client_id: str) -> bool:
        if client_id in self._terminal:
            return False
        try:
            status = self.engine.order_status(client_id)
        except (KeyError, AttributeError):
            return False  # unknown to this engine: nothing left to resolve here.
        if status is None:
            return False
        # Contract shape is EngineOrderStatus; tolerate a bare state
        # string from pre-contract engines/doubles (same live set).
        state = status if isinstance(status, str) else status.state
        return str(state).lower() in LIVE_STATUSES

    def _reservation_resolved(self, reservation_id: str) -> bool:
        return (("release", reservation_id) in self._fired
                or ("flat", reservation_id) in self._fired)

    def _fire(self, kind: str, reservation_id: str, reason: str) -> bool:
        if self.outcome_sink is None:
            return False
        key = (kind, reservation_id)
        if key in self._fired:
            return False
        if kind == "fill":
            self.outcome_sink.note_fill(reservation_id)
        elif kind == "release":
            freed = self.outcome_sink.release(reservation_id)
            reason = f"{reason} (sink freed: {freed})"
        elif kind == "flat":
            self.outcome_sink.note_flat()
        else:
            raise ValueError(f"unknown callback kind: {kind!r}")
        self._fired.add(key)
        self._log("*", "callback-fired", {"kind": kind, "reservation_id": reservation_id,
                                         "reason": reason})
        return True

    def _evaluate_callbacks(self) -> list[dict[str, Any]]:
        """Fire due outcome callbacks. Idempotent; safe after any state change."""
        events: list[dict[str, Any]] = []
        if self.outcome_sink is None:
            return events
        reservations = set(self._entries) | set(self._legs)
        for reservation_id in sorted(reservations):
            ids = [c for c in list(self._client_reservation)
                   if self._client_reservation[c] == reservation_id]
            live = [c for c in ids if self._is_live(c)]
            unsettled = [c for c in self._entries.get(reservation_id, [])
                         if self._terminal.get(c) == "expired"
                         and self._settle_polls.get(c, 0) < self.expiry_settle_polls]
            entry_filled = sum(self._client_fills.get(c, 0.0)
                               for c in self._entries.get(reservation_id, []))
            if entry_filled > _EPS:
                if self._fire("fill", reservation_id, "first-nonzero-fill"):
                    events.append({"reservation_id": reservation_id, "event": "callback:fill"})
                _, _, net, overfilled = self._position_state(reservation_id)
                if overfilled:
                    if reservation_id not in self._frozen:
                        self._frozen.add(reservation_id)
                        self._log("*", "exit-overfill",
                                  {"reservation_id": reservation_id, "net": net})
                        events.append({"reservation_id": reservation_id,
                                       "event": "exit-overfill-freeze"})
                elif abs(net) <= _EPS and not live and not unsettled:
                    if self._fire("flat", reservation_id, "reconciled-net-zero"):
                        events.append({"reservation_id": reservation_id,
                                       "event": "callback:flat"})
            elif self._entries.get(reservation_id) and not live and not unsettled:
                states = ",".join(sorted({self._terminal.get(c, "open") for c in ids}))
                if self._fire("release", reservation_id, f"no-live-order(states={states})"):
                    events.append({"reservation_id": reservation_id,
                                   "event": "callback:release"})
        return events

    # -- halt ------------------------------------------------------------------
    def set_halted(self, halted: bool, reason: str = "") -> None:
        """Engage or lift the risk halt signal. Persisted; survives restart until cleared."""
        if halted == self.exit_only:
            return  # level-triggered: steady state, nothing to record.
        self.exit_only = halted
        # The engine key denotes ownership; caller-specific engage and
        # recovery descriptions need not be the same string. Preserve
        # unrelated Session/stream/risk reasons in reason-keyed adapters.
        self.engine.set_exit_only(halted, _ENGINE_HALT_REASON)
        self._log("*", "halt-engaged" if halted else "halt-cleared", {"reason": reason})

    # -- restart recovery ---------------------------------------------------------
    @classmethod
    def recover(
        cls,
        engine: Any,
        log_path: str | Path,
        *,
        ledger: Any | None = None,
        outcome_sink: RiskOutcomeSink | None = None,
        now_utc: Callable[[], datetime] | None = None,
    ) -> "RuntimeTrader":
        """Rebuild from the log, reconcile against the engine, replay deltas.

        Simulator orders do not survive restarts: submitted-but-unresolved ids
        unknown to the new engine are marked lost-on-restart (never assumed
        filled, cancelled, or flat). Reservations with logged-but-unflattened
        exposure are flagged restart-exposure-open for an explicit re-decision.
        """
        trader = cls(engine, log_path=log_path, ledger=ledger,
                     outcome_sink=outcome_sink, now_utc=now_utc)
        path = Path(log_path)
        if not path.exists():
            return trader
        halted: bool | None = None
        fills: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            event, detail = entry.get("event"), entry.get("detail", {})
            client_id = entry.get("client_id", "")
            if event == "submitted":
                role = detail.get("role", "entry")
                reservation = detail.get("reservation_id")
                trader._client_role[client_id] = role
                if reservation:
                    trader._client_reservation[client_id] = reservation
                    if role == "entry":
                        trader._entries.setdefault(reservation, []).append(client_id)
                    else:
                        trader._legs.setdefault(reservation, {})[client_id] = role
            elif event == "leg-submitted":
                reservation = detail.get("reservation_id")
                role = detail.get("role", "stop")
                trader._client_role[client_id] = role
                if reservation:
                    trader._client_reservation[client_id] = reservation
                    trader._legs.setdefault(reservation, {})[client_id] = role
            elif event == "fill":
                fills[detail["exec_id"]] = detail
                trader._fills[detail["exec_id"]] = detail
                trader._client_fills[client_id] = (
                    trader._client_fills.get(client_id, 0.0) + detail["qty"])
            elif event == "delta-propagated" or event == "delta-propagated-direct":
                trader._propagated.add(detail["exec_id"])
            elif event == "callback-fired":
                trader._fired.add((detail["kind"], detail["reservation_id"]))
            elif event == "halt-engaged":
                halted = True
            elif event == "halt-cleared":
                halted = False
            elif event == "exit-overfill":
                trader._frozen.add(detail["reservation_id"])
            elif event == "topup-attempt":
                res = detail["reservation_id"]
                trader._topup_attempts[res] = max(
                    trader._topup_attempts.get(res, 0), detail["attempt"])
            elif event == "protection-gap-unresolved":
                trader._gap_terminal.add(detail["reservation_id"])
            elif event and event.startswith("terminal:"):
                trader._terminal[client_id] = event.split(":", 1)[1]
            elif event == "time-exit-armed":
                trader._time_exits[detail["reservation_id"]] = datetime.fromisoformat(
                    detail["time_exit_utc"])
        if halted is not None:
            trader.exit_only = halted
            engine.set_exit_only(halted, _ENGINE_HALT_REASON)
        # Reconcile: ids the engine never saw are lost-on-restart, not assumed.
        lost: list[str] = []
        for client_id in list(trader._client_role):
            if client_id in trader._terminal:
                continue
            try:
                seen = engine.order_status(client_id)
            except KeyError:
                seen = None
            if seen is None:
                trader._terminal[client_id] = "lost-on-restart"
                lost.append(client_id)
        if lost:
            trader._log("*", "lost-on-restart", {"client_ids": sorted(lost)})
        for exec_id in sorted(fills):
            if exec_id not in trader._propagated:
                trader._propagate_delta(fills[exec_id])  # at-least-once replay.
        for reservation_id in sorted(set(trader._entries) | set(trader._legs)):
            _, _, net, _ = trader._position_state(reservation_id)
            if abs(net) > _EPS and not trader._reservation_resolved(reservation_id):
                trader._log("*", "restart-exposure-open",
                            {"reservation_id": reservation_id, "net": net,
                             "reason": "logged fills stand; flatten needs an explicit decision"})
        trader._evaluate_callbacks()
        trader._log("*", "recovered", {"lost": sorted(lost)})
        return trader

    # -- internals ---------------------------------------------------------------
    def _log(self, client_id: str, event: str, detail: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts_utc": self._now_utc().isoformat(),
                "client_id": client_id,
                "event": event,
                "detail": detail,
            }) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
