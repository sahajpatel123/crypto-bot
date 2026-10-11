"""Order-manager skeleton (Worker 2, CONTRACTS v0.1.0 execution interface).

Owns client order IDs (unique across restarts), entry expiry, partial-fill
tracking, stop/target sibling handling, reconciliation before retry of
ambiguous orders, and restart recovery from an append-only order log.

Siblings are deliberately NOT an atomic bracket: each conditional leg is
submitted and verified independently, and completing one leg cancels the
other on a best-effort basis with verification. Any venue that cannot prove
both legs exists in this unverified state — the manager never assumes it.

Time is injectable (``now_utc``) so every behaviour is deterministic in tests.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .fake_venue import FakeVenue, VenueOrderView, VenueTimeoutError

CONTRACT_VERSION = "v0.1.0"


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
    ) -> None:
        self.venue = venue
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.exit_only = exit_only
        self._seq = 0
        self.orders: dict[str, ManagedOrder] = {}

    # -- identity --------------------------------------------------------
    def new_client_id(self, prefix: str = "w2") -> str:
        self._seq += 1
        rand = uuid.uuid4().hex[:8]  # cross-restart uniqueness; seq is per-process.
        return f"{prefix}-{self._seq:06d}-{rand}"

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
    ) -> ManagedOrder:
        if self.exit_only:
            raise PermissionError("exit-only mode refuses new entries")
        venue_side = {"LONG": "BUY", "SHORT": "SELL"}[strategy_side]
        return self._submit(
            symbol, venue_side, qty, kind, price=price,
            expire_at_utc=expire_at_utc, role="entry",
        )

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
    ) -> ManagedOrder:
        """Submit, reconciling before every retry. Retries always use a NEW ID."""
        order = self.submit_entry(symbol, strategy_side, qty, price,
                                  expire_at_utc=expire_at_utc, kind=kind)
        attempts = 0
        while order.state == OrderState.AMBIGUOUS and attempts < max_retries:
            attempts += 1
            view = self.reconcile(order.client_id)
            if view is None:
                # Venue never saw it: safe to retry as a brand-new order.
                order = self._submit(
                    symbol, order.venue_side, qty, kind, price=price,
                    expire_at_utc=expire_at_utc, role="entry", retry_of=order.client_id,
                )
            else:
                break  # Venue owns it; adopted state stands, no duplicate.
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
    ) -> ManagedOrder:
        client_id = self.new_client_id()
        order = ManagedOrder(
            client_id=client_id, symbol=symbol, venue_side=venue_side,
            kind=kind, qty=qty, price=price, stop_price=stop_price,
            state=OrderState.OPEN, expire_at_utc=expire_at_utc,
            role=role, group_id=group_id, retry_of=retry_of,
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
            return order
        self._adopt_venue_state(order)
        self._log(client_id, "submitted", {"reason": result.reason, "state": order.state.value})
        return order

    # -- siblings (no atomic bracket assumption) ---------------------------
    def attach_siblings(
        self, entry: ManagedOrder, *, stop_price: float, target_price: float
    ) -> tuple[ManagedOrder, ManagedOrder]:
        """Attach independently-verified stop + target legs to a filled entry."""
        if entry.state != OrderState.FILLED:
            raise ValueError("siblings attach only to a FILLED entry")
        exit_side = "SELL" if entry.venue_side == "BUY" else "BUY"
        group_id = f"grp-{entry.client_id}"
        stop = self._submit(
            entry.symbol, exit_side, entry.qty, "STOP_MARKET",
            price=None, stop_price=stop_price, role="stop", group_id=group_id,
        )
        target = self._submit(
            entry.symbol, exit_side, entry.qty, "TAKE_PROFIT_MARKET",
            price=None, stop_price=target_price, role="target", group_id=group_id,
        )
        # Verify each conditional leg independently; no atomic-bracket assumption.
        for leg in (stop, target):
            self.reconcile(leg.client_id)
        return stop, target

    # -- reconciliation ----------------------------------------------------
    def reconcile(self, client_id: str) -> VenueOrderView | None:
        """Query the venue and adopt its truth. Returns None when unknown."""
        order = self.orders[client_id]
        view = self.venue.query(client_id)
        order.reconciled = True
        if view is None:
            order.venue_known = False
            self._log(client_id, "reconciled-unknown", {"state": order.state.value})
            return None
        order.venue_known = True
        self._adopt_view(order, view)
        self._log(client_id, "reconciled", {"state": order.state.value})
        return view

    # -- polling: expiry, fills, sibling completion ------------------------
    def poll(self, now_utc: datetime | None = None) -> list[dict[str, Any]]:
        now = now_utc or self._now_utc()
        events: list[dict[str, Any]] = []
        for order in list(self.orders.values()):
            if order.state in TERMINAL_STATES:
                continue
            view = self.venue.query(order.client_id)
            if view is not None:
                order.venue_known = True
                before = order.state
                self._adopt_view(order, view)
                if before != order.state:
                    events.append({"client_id": order.client_id, "event": f"state:{before.value}->{order.state.value}"})
            if (
                order.role == "entry"
                and order.expire_at_utc is not None
                and now >= order.expire_at_utc
                and order.state in (OrderState.OPEN, OrderState.PARTIAL, OrderState.AMBIGUOUS)
            ):
                self.venue.cancel(order.client_id)
                order.state = OrderState.EXPIRED
                self._log(order.client_id, "expired", {})
                events.append({"client_id": order.client_id, "event": "expired"})
        events.extend(self._settle_sibling_groups())
        return events

    def _settle_sibling_groups(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        groups: dict[str, list[ManagedOrder]] = {}
        for order in self.orders.values():
            if order.group_id:
                groups.setdefault(order.group_id, []).append(order)
        for group_id, legs in groups.items():
            filled = [o for o in legs if o.state == OrderState.FILLED]
            open_legs = [o for o in legs if o.state in (OrderState.OPEN, OrderState.PARTIAL)]
            if filled and open_legs:
                for leg in open_legs:
                    self.venue.cancel(leg.client_id)
                    self.reconcile(leg.client_id)  # verify the cancel landed.
                    events.append({"client_id": leg.client_id,
                                   "event": f"sibling-cancelled-after:{filled[0].client_id}"})
        return events

    # -- restart recovery ---------------------------------------------------
    @classmethod
    def recover(
        cls,
        venue: FakeVenue,
        log_path: str | Path,
        *,
        now_utc: Callable[[], datetime] | None = None,
        exit_only: bool = False,
    ) -> "OrderManager":
        """Rebuild open orders from the log, then reconcile each with the venue."""
        manager = cls(venue, log_path=log_path, now_utc=now_utc, exit_only=exit_only)
        path = Path(log_path)
        if not path.exists():
            return manager
        snapshots: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            snapshots.setdefault(entry["client_id"], {}).update(entry.get("order", {}))
        for client_id, snap in snapshots.items():
            if not snap:
                continue
            expire = snap.get("expire_at_utc")
            manager.orders[client_id] = ManagedOrder(
                client_id=client_id, symbol=snap["symbol"], venue_side=snap["venue_side"],
                kind=snap["kind"], qty=snap["qty"], price=snap.get("price"),
                stop_price=snap.get("stop_price"), state=OrderState(snap["state"]),
                filled_qty=snap.get("filled_qty", 0.0), avg_price=snap.get("avg_price"),
                expire_at_utc=datetime.fromisoformat(expire) if expire else None,
                role=snap.get("role", "entry"), group_id=snap.get("group_id", ""),
                retry_of=snap.get("retry_of"),
            )
            manager._seq = max(manager._seq, 0)
        for order in manager.orders.values():
            if order.state not in TERMINAL_STATES:
                manager.reconcile(order.client_id)
        manager._log("*", "recovered", {"orders": len(manager.orders)})
        return manager

    # -- internals ---------------------------------------------------------
    def _adopt_venue_state(self, order: ManagedOrder) -> None:
        view = self.venue.query(order.client_id)
        if view is not None:
            self._adopt_view(order, view)

    def _adopt_view(self, order: ManagedOrder, view: VenueOrderView) -> None:
        if order.state == OrderState.EXPIRED:
            return  # local expiry wins; venue cancel already issued.
        order.state = _venue_state_to_local(view.status)
        order.filled_qty = view.filled_qty
        order.avg_price = view.avg_price

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
