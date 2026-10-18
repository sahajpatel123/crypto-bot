"""Order-manager skeleton (Worker 2, CONTRACTS v0.1.0 + v0.1.1 execution side).

Owns client order IDs (unique across restarts), entry expiry, partial-fill
tracking, stop/target sibling handling, reconciliation before retry of
ambiguous orders, and restart recovery from an append-only order log.

v0.1.1 handoff (E-003): ``reservation_id`` threads from ``submit_entry``
onto the entry and its protective siblings; outcome callbacks
(``note_fill``/``release``/``note_flat``) fire exactly-once per reservation
against a ``RiskOutcomeSink``; the halt → exit-only signal is level-triggered
and persisted; recovery reconciles reservations and sweeps venue orphans.

v0.2.0 deltas (E-005): every fill increment mints a durable exec-id delta
record (fsync before the sink call) and propagates via
``note_fill_delta`` when the sink provides it; fill-first semantics (first
nonzero fill converts the reservation); release only on zero lifetime fills
with nothing live/ambiguous/settling; flat on reconciled net-zero. Expired
entries re-reconcile through a settle window so late fills book and extend
protection; exit overfills freeze further exits for the reservation.

Exactly-once scope: the fired-callback set persists in the log (fsync on
append), so reservation callbacks fire once per process lifetime and are
never repeated across clean restarts. Deltas are at-least-once on exec_id
(recovery replays unpropagated ones) with risk-side dedup. A crash strictly
between a reservation-callback sink call and its log record could re-fire
after recovery; ``release`` is bool-idempotent by interface design, and
``note_fill``/``note_flat`` duplicates in that micro window are risk's to
tolerate (residual, documented).

Siblings are deliberately NOT an atomic bracket: each conditional leg is
submitted and verified independently, and completing one leg cancels the
other on a best-effort basis with verification. Any venue that cannot prove
both legs exists in this unverified state — the manager never assumes it.

Time is injectable (``now_utc``) so every behaviour is deterministic in tests.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from cryptobot.coordination import RiskOutcomeSink

from .fake_venue import FakeVenue, VenueOrderView, VenueTimeoutError

CONTRACT_VERSION = "v0.1.0"  # baseline; v0.1.1 handoff addendum implemented on the execution side.


class OrderState(str, Enum):
    OPEN = "open"
    PARTIAL = "partial"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    AMBIGUOUS = "ambiguous"  # submit timed out; venue state unknown until reconciled.


TERMINAL_STATES = frozenset(
    {OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELLED, OrderState.EXPIRED}
)


@dataclass
class ManagedOrder:
    client_id: str
    symbol: str
    venue_side: str  # "BUY" | "SELL"
    kind: str
    qty: float
    price: float | None
    stop_price: float | None
    state: OrderState
    filled_qty: float = 0.0
    avg_price: float | None = None
    expire_at_utc: datetime | None = None
    role: str = "entry"  # "entry" | "stop" | "target"
    group_id: str = ""
    retry_of: str | None = None
    reconciled: bool = False  # venue queried at least once for this ID.
    venue_known: bool = True  # False once the venue confirms it never saw the ID.
    reservation_id: str | None = None  # v0.1.1 risk reservation key; shared by entry + siblings + retries.
    fill_notional: float = 0.0  # Σ fill qty*price; lets recovery price each delta incrementally.
    fill_seq: int = 0  # fill-delta records logged for this order; exec-ID counter.
    settle_polls: int = 0  # clean polls since EXPIRED; gates release past the cancel race.


def _venue_state_to_local(status: str) -> OrderState:
    return {
        "NEW": OrderState.OPEN,
        "PARTIALLY_FILLED": OrderState.PARTIAL,
        "FILLED": OrderState.FILLED,
        "REJECTED": OrderState.REJECTED,
        "CANCELLED": OrderState.CANCELLED,
    }[status]


class OrderManager:
    def __init__(
        self,
        venue: FakeVenue,
        *,
        log_path: str | Path,
        now_utc: Callable[[], datetime] | None = None,
        exit_only: bool = False,
        outcome_sink: RiskOutcomeSink | None = None,
        expiry_settle_polls: int = 2,
    ) -> None:
        self.venue = venue
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.exit_only = exit_only
        self.outcome_sink = outcome_sink
        self.expiry_settle_polls = expiry_settle_polls
        self._seq = 0
        self.orders: dict[str, ManagedOrder] = {}
        self._callbacks_fired: set[tuple[str, str]] = set()  # (kind, reservation_id); persisted via log.
        self._deltas_logged: set[str] = set()  # exec_ids; persisted via fill-delta records.
        self._minted_ids: set[str] = set()  # client IDs this manager minted; rebuilt from intent records.
        self._exit_frozen: set[str] = set()  # reservation_ids with exit overfill; no further exits.
        self._topup_attempts: dict[str, int] = {}  # reservation_id -> top-up pairs attempted; rebuilt from log.
        self._gap_terminal: set[str] = set()  # reservation_ids with terminal protection-gap record.

    # -- identity --------------------------------------------------------
    def new_client_id(self, prefix: str = "w2") -> str:
        # A#10: never re-mint a journaled id (post-recover _seq could
        # otherwise re-collide on the random leg): bounded redraw.
        for _ in range(100):
            self._seq += 1
            rand = uuid.uuid4().hex[:8]  # cross-restart uniqueness; seq is per-process.
            cid = f"{prefix}-{self._seq:06d}-{rand}"
            if cid not in self._minted_ids:
                return cid
        raise RuntimeError("new_client_id: 100 consecutive collisions")

    # -- submission ------------------------------------------------------
    def submit_entry(
        self,
        symbol: str,
        strategy_side: str,
        qty: float,
        price: float,
        *,
        expire_at_utc: datetime,
        kind: str = "LIMIT",
        reservation_id: str | None = None,
    ) -> ManagedOrder:
        if self.exit_only:
            raise PermissionError("exit-only mode refuses new entries")
        venue_side = {"LONG": "BUY", "SHORT": "SELL"}[strategy_side]
        order = self._submit(
            symbol, venue_side, qty, kind, price=price,
            expire_at_utc=expire_at_utc, role="entry", reservation_id=reservation_id,
        )
        self._evaluate_callbacks()
        return order

    def submit_with_retry(
        self,
        symbol: str,
        strategy_side: str,
        qty: float,
        price: float,
        *,
        expire_at_utc: datetime,
        kind: str = "LIMIT",
        max_retries: int = 2,
        reservation_id: str | None = None,
    ) -> ManagedOrder:
        """Submit, reconciling before every retry. Retries always use a NEW ID."""
        order = self.submit_entry(symbol, strategy_side, qty, price,
                                  expire_at_utc=expire_at_utc, kind=kind,
                                  reservation_id=reservation_id)
        attempts = 0
        while order.state == OrderState.AMBIGUOUS and attempts < max_retries:
            attempts += 1
            view = self.reconcile(order.client_id)
            if view is None:
                # Venue never saw it: safe to retry as a brand-new order under the SAME reservation.
                order = self._submit(
                    symbol, order.venue_side, qty, kind, price=price,
                    expire_at_utc=expire_at_utc, role="entry", retry_of=order.client_id,
                    reservation_id=reservation_id,
                )
            else:
                break  # Venue owns it; adopted state stands, no duplicate.
        self._evaluate_callbacks()
        return order

    def _submit(
        self,
        symbol: str,
        venue_side: str,
        qty: float,
        kind: str,
        *,
        price: float | None,
        stop_price: float | None = None,
        expire_at_utc: datetime | None = None,
        role: str = "entry",
        group_id: str = "",
        retry_of: str | None = None,
        reservation_id: str | None = None,
    ) -> ManagedOrder:
        client_id = self.new_client_id()
        self._minted_ids.add(client_id)
        # Persist-before-side-effect: the intent record names this client ID
        # durably before venue.submit runs, so recovery can prove bot
        # ownership of anything the venue holds under it.
        self._log(client_id, "submit-intent", {
            "symbol": symbol, "venue_side": venue_side, "kind": kind, "qty": qty,
            "price": price, "stop_price": stop_price, "role": role,
            "group_id": group_id, "retry_of": retry_of, "reservation_id": reservation_id,
        })
        order = ManagedOrder(
            client_id=client_id, symbol=symbol, venue_side=venue_side,
            kind=kind, qty=qty, price=price, stop_price=stop_price,
            state=OrderState.OPEN, expire_at_utc=expire_at_utc,
            role=role, group_id=group_id, retry_of=retry_of,
            reservation_id=reservation_id,
        )
        self.orders[client_id] = order
        try:
            result = self.venue.submit(client_id, symbol, venue_side, kind, qty, price, stop_price)
        except VenueTimeoutError as exc:
            order.state = OrderState.AMBIGUOUS
            self._log(client_id, "submit-timeout-ambiguous", {"reason": str(exc)})
            return order
        if not result.accepted:
            order.state = OrderState.REJECTED
            self._log(client_id, "rejected", {"reason": result.reason})
            self._evaluate_callbacks()
            return order
        self._adopt_venue_state(order)
        self._log(client_id, "submitted", {"reason": result.reason, "state": order.state.value})
        return order

    # -- siblings (no atomic bracket assumption) ---------------------------
    def attach_siblings(
        self, entry: ManagedOrder, *, stop_price: float, target_price: float
    ) -> tuple[ManagedOrder, ManagedOrder]:
        """Attach independently-verified stop + target legs sized to FILLED qty (partial OK)."""
        if entry.filled_qty <= 1e-12:
            raise ValueError("siblings attach only to an entry with fills")
        if entry.reservation_id in self._exit_frozen:
            raise ValueError("exits frozen after overfill; no new legs")
        exit_side = "SELL" if entry.venue_side == "BUY" else "BUY"
        protect_qty = min(entry.filled_qty, entry.qty)
        if entry.reservation_id is not None:
            net = self.position_net(entry.reservation_id)
            protect_qty = min(protect_qty, abs(net))  # never instruct more exit than exposure.
        if protect_qty <= 1e-12:
            raise ValueError("nothing to protect: no unprotected filled quantity")
        group_id = f"grp-{entry.client_id}"
        stop = self._submit(
            entry.symbol, exit_side, protect_qty, "STOP_MARKET",
            price=None, stop_price=stop_price, role="stop", group_id=group_id,
            reservation_id=entry.reservation_id,
        )
        target = self._submit(
            entry.symbol, exit_side, protect_qty, "TAKE_PROFIT_MARKET",
            price=None, stop_price=target_price, role="target", group_id=group_id,
            reservation_id=entry.reservation_id,
        )
        # Verify each conditional leg independently; no atomic-bracket assumption.
        for leg in (stop, target):
            self.reconcile(leg.client_id)
        return stop, target

    # -- reconciliation ----------------------------------------------------
    def reconcile(self, client_id: str) -> VenueOrderView | None:
        """Query the venue and adopt its truth. Returns None when unknown.

        A definitive unknown voids a live order: the venue never saw it, so
        nothing can ever fill. (Live adapters must raise on transport failure
        and return None only on definitive unknown — otherwise voiding is unsafe.)
        """
        order = self.orders[client_id]
        view = self.venue.query(client_id)
        order.reconciled = True
        if view is None:
            order.venue_known = False
            if order.state not in TERMINAL_STATES:
                order.state = OrderState.CANCELLED  # void: nothing exists to fill or cancel.
                self._log(client_id, "reconciled-unknown-void", {})
            else:
                self._log(client_id, "reconciled-unknown", {"state": order.state.value})
            self._evaluate_callbacks()
            return None
        order.venue_known = True
        self._adopt_view(order, view)
        self._log(client_id, "reconciled", {"state": order.state.value})
        self._evaluate_callbacks()
        return view

    # -- v0.1.1 outcome callbacks (exactly-once per reservation) -------------
    def _fire(self, kind: str, reservation_id: str, reason: str) -> bool:
        """Fire one outcome callback unless already fired. Returns True if newly fired."""
        if self.outcome_sink is None:
            return False
        key = (kind, reservation_id)
        if key in self._callbacks_fired:
            return False
        if kind == "fill":
            self.outcome_sink.note_fill(reservation_id)
        elif kind == "release":
            freed = self.outcome_sink.release(reservation_id)
            reason = f"{reason} (sink freed: {freed})"
        elif kind == "flat":
            self.outcome_sink.note_flat()  # single-position pilot: no reservation key.
        else:
            raise ValueError(f"unknown callback kind: {kind!r}")
        self._callbacks_fired.add(key)
        self._log("*", "callback-fired", {"kind": kind, "reservation_id": reservation_id, "reason": reason})
        return True

    def position_net(self, reservation_id: str) -> float:
        """Signed open exposure for a reservation: entry fills minus exit-leg fills."""
        return self._position_state(reservation_id)[2]

    def _position_state(self, reservation_id: str) -> tuple[float, float, float, bool]:
        """Return (entry_net, exit_net, net, overfilled) for a reservation.

        Signs follow economics: a LONG entry BUY adds, its SELL legs subtract;
        a SHORT entry SELL subtracts, its BUY legs add. ``overfilled`` means
        exits overshot entries (a venue-side race); the book stays truthful
        and further exits freeze — see _evaluate_callbacks.
        """
        entry_net = exit_net = 0.0
        for o in self.orders.values():
            if o.reservation_id != reservation_id:
                continue
            signed = o.filled_qty if o.venue_side == "BUY" else -o.filled_qty
            if o.role == "entry":
                entry_net += signed
            elif o.role in ("stop", "target"):
                exit_net += signed
        net = entry_net + exit_net
        overfilled = (
            abs(entry_net) > 1e-12
            and abs(net) > 1e-12
            and (net > 0) != (entry_net > 0)
        )
        return entry_net, exit_net, net, overfilled

    def _reservation_resolved(self, reservation_id: str) -> bool:
        return (("release", reservation_id) in self._callbacks_fired
                or ("flat", reservation_id) in self._callbacks_fired)

    def _evaluate_callbacks(self) -> list[dict[str, Any]]:
        """Fire due outcome callbacks. Idempotent; safe to call after any state change."""
        events: list[dict[str, Any]] = []
        if self.outcome_sink is None:
            return events
        by_reservation: dict[str, list[ManagedOrder]] = {}
        for order in self.orders.values():
            if order.reservation_id is not None:
                by_reservation.setdefault(order.reservation_id, []).append(order)
        for reservation_id in sorted(by_reservation):
            orders = by_reservation[reservation_id]
            entries = [o for o in orders if o.role == "entry"]
            live = [o for o in orders if o.state not in TERMINAL_STATES]
            unsettled = [o for o in entries
                         if o.state == OrderState.EXPIRED and o.settle_polls < self.expiry_settle_polls]
            entry_filled = sum(o.filled_qty for o in entries)
            if entry_filled > 1e-12:
                # v0.2.0 fill-first: the FIRST nonzero fill converts the reservation.
                if self._fire("fill", reservation_id, "first-nonzero-fill"):
                    events.append({"reservation_id": reservation_id, "event": "callback:fill"})
                _, _, net, overfilled = self._position_state(reservation_id)
                if overfilled:
                    if reservation_id not in self._exit_frozen:
                        self._exit_frozen.add(reservation_id)
                        self._log("*", "exit-overfill",
                                  {"reservation_id": reservation_id, "net": net,
                                   "reason": "venue-side exit race; exits frozen, no compounding orders"})
                        events.append({"reservation_id": reservation_id, "event": "exit-overfill-freeze"})
                elif abs(net) <= 1e-12 and not live and not unsettled:
                    if self._fire("flat", reservation_id, "reconciled-net-zero"):
                        events.append({"reservation_id": reservation_id, "event": "callback:flat"})
            elif entries and not live and not unsettled:
                # Zero lifetime fills and nothing left to resolve: free the reservation.
                states = ",".join(sorted({o.state.value for o in orders}))
                if self._fire("release", reservation_id, f"no-live-order(states={states})"):
                    events.append({"reservation_id": reservation_id, "event": "callback:release"})
        return events

    # -- halt → exit-only (level-triggered, persisted) -----------------------
    def set_halted(self, halted: bool, reason: str = "") -> None:
        """Engage or lift the risk halt signal. Persisted; survives restart until cleared."""
        if halted == self.exit_only:
            return  # level-triggered: steady state, nothing to record.
        self.exit_only = halted
        self._log("*", "halt-engaged" if halted else "halt-cleared", {"reason": reason})

    def clear_halt_via_reconciliation(self, reason: str = "cleared-via-reconciliation") -> None:
        """Risk clears the halt through reconciliation (the only clearing path besides direct lift)."""
        self.set_halted(False, reason)

    # -- polling: expiry, fills, sibling completion ------------------------
    def poll(self, now_utc: datetime | None = None) -> list[dict[str, Any]]:
        now = now_utc or self._now_utc()
        events: list[dict[str, Any]] = []
        for order in list(self.orders.values()):
            # F1.2 REAL-BUG (mutation triage): resolved reservations still
            # need venue READS (a fill racing a venue-side cancel lands
            # after the zero-fill release; skipping the read drops it
            # and risk undercounts exposure fail-open). Only expiry
            # ACTIONS are skipped below for resolved reservations.
            resolved = (order.reservation_id is not None
                        and self._reservation_resolved(order.reservation_id))
            if order.state == OrderState.REJECTED:
                continue  # rejected can never fill.
            settling = (
                order.state == OrderState.EXPIRED
                and order.reservation_id is not None
                and order.settle_polls < self.expiry_settle_polls
            )
            before_filled = order.filled_qty
            view = self.venue.query(order.client_id)
            if view is not None:
                order.venue_known = True
                order.reconciled = True  # poll queries are reconciliation reads too.
                before = order.state
                self._adopt_view(order, view)
                if before != order.state:
                    events.append({"client_id": order.client_id, "event": f"state:{before.value}->{order.state.value}"})
            elif order.state not in TERMINAL_STATES:
                order.venue_known = False
                order.state = OrderState.CANCELLED  # void, as in reconcile().
                self._log(order.client_id, "reconciled-unknown-void", {})
                events.append({"client_id": order.client_id, "event": "void-unknown"})
            if order.state in TERMINAL_STATES:
                # Terminal orders are re-read for late fills (cancel/fill races,
                # report lag); only EXPIRED entries count settle polls.
                if order.filled_qty > before_filled + 1e-12:
                    events.append({"client_id": order.client_id, "event": "late-fill-booked"})
                elif settling:
                    order.settle_polls += 1
                    self._log(order.client_id, "settle-poll", {"settle_polls": order.settle_polls})
                continue
            if resolved:
                continue  # fills adopted above; no expiry actions post-release.
            # F-E001-05 (live note): expiry covers entries only. Stop/target legs
            # never expire here — accepted for M1 (legs die only by fill or by
            # the sibling winner's verified cancel). A live venue needs leg
            # expiry/GTC policy plus end-of-day cancel hygiene on top.
            if (
                order.role == "entry"
                and order.expire_at_utc is not None
                and now >= order.expire_at_utc
                and order.state in (OrderState.OPEN, OrderState.PARTIAL, OrderState.AMBIGUOUS)
            ):
                # Reconciled at the top of this same poll before expiring (F-CEO-03).
                self._cancel_with_intent(order.client_id, "entry-expired")
                order.state = OrderState.EXPIRED
                self._log(order.client_id, "expired", {})
                events.append({"client_id": order.client_id, "event": "expired"})
        events.extend(self._settle_sibling_groups())
        events.extend(self._evaluate_callbacks())
        events.extend(self._top_up_protection())
        return events

    def _cancel_with_intent(self, client_id: str, reason: str) -> VenueOrderView | None:
        """Cancel with a persisted intent first; recovery re-verifies via query."""
        self._log(client_id, "cancel-intent", {"reason": reason})
        return self.venue.cancel(client_id)

    def _settle_sibling_groups(self) -> list[dict[str, Any]]:
        # Reservation-wide: a fill in ANY group cancels every other live leg of
        # the same reservation (top-up groups included), so delayed cancels and
        # multi-group races cannot stack exits into a reversal. Legs without a
        # reservation fall back to per-group settling (pre-handoff behavior).
        events: list[dict[str, Any]] = []
        by_scope: dict[str, list[ManagedOrder]] = {}
        for order in self.orders.values():
            if not order.group_id:
                continue
            scope = f"res:{order.reservation_id}" if order.reservation_id is not None else f"grp:{order.group_id}"
            by_scope.setdefault(scope, []).append(order)
        for legs in by_scope.values():
            filled = [o for o in legs if o.state == OrderState.FILLED]
            open_legs = [o for o in legs if o.state in (OrderState.OPEN, OrderState.PARTIAL, OrderState.AMBIGUOUS)]
            if filled and open_legs:
                for leg in open_legs:
                    self._cancel_with_intent(leg.client_id, f"sibling-cancelled-after:{filled[0].client_id}")
                    self.reconcile(leg.client_id)  # verify the cancel landed.
                    events.append({"client_id": leg.client_id,
                                   "event": f"sibling-cancelled-after:{filled[0].client_id}"})
        return events

    def _exit_cover(self, reservation_id: str) -> tuple[float, float]:
        """Live (+conservatively ambiguous) stop/target cover for a reservation."""
        stop_cover = target_cover = 0.0
        for o in self.orders.values():
            if o.reservation_id != reservation_id or o.role not in ("stop", "target"):
                continue
            if o.state in (OrderState.OPEN, OrderState.PARTIAL, OrderState.AMBIGUOUS):
                covered = o.qty
            elif o.state == OrderState.FILLED:
                covered = o.filled_qty
            else:
                covered = 0.0
            if o.role == "stop":
                stop_cover += covered
            else:
                target_cover += covered
        return stop_cover, target_cover

    def _top_up_protection(self) -> list[dict[str, Any]]:
        """Submit top-up leg pairs where filled entries outgrew their cover.

        Bounded response: at most 5 attempts per reservation per log lifetime;
        afterwards a terminal protection-gap record stands and no further legs
        are submitted. Never tops up frozen, resolved, or leg-filled reservations.
        """
        events: list[dict[str, Any]] = []
        by_reservation: dict[str, list[ManagedOrder]] = {}
        for order in self.orders.values():
            if order.reservation_id is not None and order.role == "entry":
                by_reservation.setdefault(order.reservation_id, []).append(order)
        for reservation_id in sorted(by_reservation):
            if reservation_id in self._exit_frozen or self._reservation_resolved(reservation_id):
                continue
            entries = by_reservation[reservation_id]
            legs = [o for o in self.orders.values()
                    if o.reservation_id == reservation_id and o.role in ("stop", "target")]
            if not legs or any(o.state == OrderState.FILLED for o in legs):
                continue  # nothing to extend, or position already closing/closed.
            entry_filled = sum(o.filled_qty for o in entries)
            stop_cover, target_cover = self._exit_cover(reservation_id)
            gap = entry_filled - min(stop_cover, target_cover)
            net = self.position_net(reservation_id)
            gap = min(gap, abs(net))  # clamp: never instruct more exit than exposure.
            if gap <= 1e-12:
                continue
            attempts = self._topup_attempts.get(reservation_id, 0)
            if attempts >= 5:
                if reservation_id not in self._gap_terminal:
                    self._gap_terminal.add(reservation_id)
                    self._log("*", "protection-gap-unresolved",
                              {"reservation_id": reservation_id, "gap": gap,
                               "reason": "attempt bound reached; manual intervention required"})
                    events.append({"reservation_id": reservation_id, "event": "protection-gap-unresolved"})
                continue
            anchor = entries[0]
            exit_side = "SELL" if anchor.venue_side == "BUY" else "BUY"
            groups = {o.group_id for o in legs if o.group_id}
            group_id = f"grp-{anchor.client_id}-x{len(groups)}"
            # Reuse the anchor levels for the incremental pair (levels are entry-owned).
            stop_px = next((o.stop_price for o in legs if o.role == "stop" and o.stop_price), None)
            tgt_px = next((o.stop_price for o in legs if o.role == "target" and o.stop_price), None)
            if stop_px is None or tgt_px is None:
                continue
            self._topup_attempts[reservation_id] = attempts + 1
            self._log("*", "topup-attempt",
                      {"reservation_id": reservation_id, "gap": gap, "attempt": attempts + 1})
            stop = self._submit(anchor.symbol, exit_side, gap, "STOP_MARKET",
                                price=None, stop_price=stop_px, role="stop",
                                group_id=group_id, reservation_id=reservation_id)
            target = self._submit(anchor.symbol, exit_side, gap, "TAKE_PROFIT_MARKET",
                                  price=None, stop_price=tgt_px, role="target",
                                  group_id=group_id, reservation_id=reservation_id)
            for leg in (stop, target):
                self.reconcile(leg.client_id)
            events.append({"reservation_id": reservation_id, "event": f"protection-topup:{gap}"})
        return events

    # -- restart recovery ---------------------------------------------------
    # -- startup orphan sweep (F-E001-02) --------------------------------------
    def sweep_venue_orphans(self) -> list[str]:
        """Cancel live venue orders that are verifiably bot-owned but locally unknown.

        Scope is the minted-ID set (submit-intent records + order snapshots):
        an order we never minted is foreign account activity and is NEVER
        touched — logged and left alone. Terminal strangers are logged, not
        cancelled. (Live residual: the fake venue has no position endpoint;
        a live venue needs position-to-exec-ID matching before touching
        anything position-shaped.)
        """
        swept: list[str] = []
        for view in self.venue.list_orders():
            if view.client_id in self.orders:
                continue
            if view.client_id not in self._minted_ids:
                self._log(view.client_id, "orphan-foreign-ignored",
                          {"venue_status": view.status,
                           "reason": "not-in-minted-id-set; foreign activity never touched"})
                continue
            if view.status in ("NEW", "PARTIALLY_FILLED"):
                self._cancel_with_intent(view.client_id, "no-local-record-after-recovery")
                self._log(view.client_id, "orphan-swept",
                          {"venue_status": view.status, "reason": "bot-owned-no-local-record"})
                swept.append(view.client_id)
            else:
                self._log(view.client_id, "orphan-observed-terminal",
                          {"venue_status": view.status, "reason": "bot-owned-no-local-record"})
        return swept

    # -- restart recovery ---------------------------------------------------
    @classmethod
    def recover(
        cls,
        venue: FakeVenue,
        log_path: str | Path,
        *,
        now_utc: Callable[[], datetime] | None = None,
        exit_only: bool = False,
        outcome_sink: RiskOutcomeSink | None = None,
    ) -> "OrderManager":
        """Rebuild from the log: orders, fired callbacks, halt state; then reconcile, sweep, evaluate."""
        manager = cls(venue, log_path=log_path, now_utc=now_utc, exit_only=exit_only,
                      outcome_sink=outcome_sink)
        path = Path(log_path)
        if not path.exists():
            return manager
        snapshots: dict[str, dict[str, Any]] = {}
        halted: bool | None = None
        logged_deltas: dict[str, dict[str, Any]] = {}
        propagated: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            snapshots.setdefault(entry["client_id"], {}).update(entry.get("order", {}))
            event, detail = entry.get("event"), entry.get("detail", {})
            if event == "callback-fired":
                manager._callbacks_fired.add((detail["kind"], detail["reservation_id"]))
            elif event == "halt-engaged":
                halted = True
            elif event == "halt-cleared":
                halted = False
            elif event == "submit-intent":
                manager._minted_ids.add(entry["client_id"])
            elif event == "fill-delta":
                manager._deltas_logged.add(detail["exec_id"])
                logged_deltas[detail["exec_id"]] = detail
            elif event == "delta-propagated":
                propagated.add(detail["exec_id"])
            elif event == "topup-attempt":
                res = detail["reservation_id"]
                manager._topup_attempts[res] = max(manager._topup_attempts.get(res, 0), detail["attempt"])
            elif event == "protection-gap-unresolved":
                manager._gap_terminal.add(detail["reservation_id"])
            elif event == "exit-overfill":
                manager._exit_frozen.add(detail["reservation_id"])
        if halted is not None:
            manager.exit_only = halted  # persisted halt level wins over the constructor edge.
        # A#10: restore the monotonic seq past journaled ids so the
        # post-restart sequence continues (never reuses seq numbers).
        for cid in manager._minted_ids:
            try:
                manager._seq = max(manager._seq, int(str(cid).split("-")[1]))
            except (IndexError, ValueError):
                continue
        for client_id, snap in snapshots.items():
            if not snap:
                continue
            manager._minted_ids.add(client_id)  # snapshots also prove bot ownership.
            expire = snap.get("expire_at_utc")
            manager.orders[client_id] = ManagedOrder(
                client_id=client_id, symbol=snap["symbol"], venue_side=snap["venue_side"],
                kind=snap["kind"], qty=snap["qty"], price=snap.get("price"),
                stop_price=snap.get("stop_price"), state=OrderState(snap["state"]),
                filled_qty=snap.get("filled_qty", 0.0), avg_price=snap.get("avg_price"),
                expire_at_utc=datetime.fromisoformat(expire) if expire else None,
                role=snap.get("role", "entry"), group_id=snap.get("group_id", ""),
                retry_of=snap.get("retry_of"), reservation_id=snap.get("reservation_id"),
                fill_notional=snap.get("fill_notional", 0.0), fill_seq=snap.get("fill_seq", 0),
                settle_polls=snap.get("settle_polls", 0),
            )
        for order in manager.orders.values():
            if order.state not in TERMINAL_STATES:
                manager.reconcile(order.client_id)
        swept = manager.sweep_venue_orphans()
        for exec_id in sorted(logged_deltas):
            if exec_id not in propagated:
                manager._propagate_delta(logged_deltas[exec_id])  # at-least-once replay.
        manager._evaluate_callbacks()  # covers reservation releases incl. no-live-order.
        manager._log("*", "recovered", {"orders": len(manager.orders), "orphans_swept": swept})
        return manager

    # -- internals ---------------------------------------------------------
    def _adopt_venue_state(self, order: ManagedOrder) -> None:
        view = self.venue.query(order.client_id)
        if view is not None:
            self._adopt_view(order, view)

    def _adopt_view(self, order: ManagedOrder, view: VenueOrderView) -> None:
        self._book_fills(order, view)  # late fills book even past local expiry.
        if order.state == OrderState.EXPIRED:
            return  # local expiry wins on STATE; fills above still booked.
        order.state = _venue_state_to_local(view.status)

    def _book_fills(self, order: ManagedOrder, view: VenueOrderView) -> dict[str, Any] | None:
        """Book any new fill increment as a durable exec-id delta record. Returns it, else None."""
        if view.filled_qty <= order.filled_qty + 1e-12:
            order.avg_price = view.avg_price or order.avg_price
            return None
        delta = view.filled_qty - order.filled_qty
        view_notional = (view.avg_price or 0.0) * view.filled_qty
        price = (view_notional - order.fill_notional) / delta
        order.fill_seq += 1
        exec_id = f"{order.client_id}:fill:{order.fill_seq:04d}"
        if exec_id in self._deltas_logged:
            return None  # defensive: never log the same increment twice.
        order.filled_qty = view.filled_qty
        order.fill_notional = view_notional
        order.avg_price = view.avg_price
        record = {
            "exec_id": exec_id, "client_id": order.client_id,
            "reservation_id": order.reservation_id, "symbol": order.symbol,
            "venue_side": order.venue_side, "qty_delta": delta, "price": price,
            "fee": 0.0, "fee_label": "venue-models-no-fee",
            "ts_utc": self._now_utc().isoformat(),
        }
        self._deltas_logged.add(exec_id)
        self._log(order.client_id, "fill-delta", record)  # fsync BEFORE the sink call (v0.2.0).
        self._propagate_delta(record)
        return record

    def _propagate_delta(self, record: dict[str, Any]) -> None:
        """At-least-once delta wire; risk dedups on exec_id. Marks propagation for recovery replay."""
        sink = self.outcome_sink
        if sink is None or record["reservation_id"] is None:
            return
        if hasattr(sink, "note_fill_delta"):
            sink.note_fill_delta(record["reservation_id"], record["exec_id"], record["symbol"],
                                 record["venue_side"], record["qty_delta"], record["price"],
                                 record["fee"], record["ts_utc"])
            self._log(record["client_id"], "delta-propagated", {"exec_id": record["exec_id"]})
        else:
            self._log("*", "delta-not-propagated",
                      {"exec_id": record["exec_id"], "reason": "sink-lacks-v0.2.0-note_fill_delta"})

    def _log(self, client_id: str, event: str, detail: dict[str, Any]) -> None:
        order = self.orders.get(client_id)
        snapshot = (
            {
                "symbol": order.symbol, "venue_side": order.venue_side,
                "kind": order.kind, "qty": order.qty, "price": order.price,
                "stop_price": order.stop_price, "state": order.state.value,
                "filled_qty": order.filled_qty, "avg_price": order.avg_price,
                "expire_at_utc": order.expire_at_utc.isoformat() if order.expire_at_utc else None,
                "role": order.role, "group_id": order.group_id, "retry_of": order.retry_of,
                "reservation_id": order.reservation_id, "fill_notional": order.fill_notional,
                "fill_seq": order.fill_seq, "settle_polls": order.settle_polls,
            }
            if order is not None
            else {}
        )
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts_utc": self._now_utc().isoformat(),
                "client_id": client_id,
                "event": event,
                "detail": detail,
                "order": snapshot,
            }) + "\n")
            fh.flush()
            os.fsync(fh.fileno())  # F-E001-02: every record durable before the call returns.
