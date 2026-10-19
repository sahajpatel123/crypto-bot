"""Fault-injectable fake venue for order-manager verification (Worker 2, E-001/E-005).

FAULT SIMULATOR ONLY — never a profitability fill model. It models failure
modes a real venue exhibits: ambiguous timeouts (request outcome unknown),
rejections, partial fills, late fills and exit races. Faults are programmed
explicitly per test via ``fail_next_submit``/``inject_fill``; there is no
randomness. Instant LIMIT fills at the submitted price exercise the state
machine; economic evaluation must use the research simulator instead.

Timeout ambiguity is the critical case: ``received=True`` means the order
reached the matching engine even though the client saw a timeout (retrying
blindly would double exposure), while ``received=False`` means it never
arrived (retry with a new client ID is safe). Only reconciliation — querying
the venue — distinguishes the two.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from cryptobot.risk.rounding import floor_to_step


class VenueTimeoutError(Exception):
    """Submit timed out; order state on the venue is UNKNOWN (ambiguous)."""


@dataclass(frozen=True)
class Fill:
    client_id: str
    symbol: str
    price: float
    qty: float


@dataclass(frozen=True)
class SubmitResult:
    client_id: str
    accepted: bool
    reason: str


@dataclass(frozen=True)
class VenueOrderView:
    client_id: str
    symbol: str
    side: str  # "BUY" | "SELL"
    kind: str  # "MARKET" | "LIMIT" | "STOP_MARKET" | "TAKE_PROFIT_MARKET"
    qty: float
    price: float | None
    stop_price: float | None
    status: str  # NEW | PARTIALLY_FILLED | FILLED | REJECTED | CANCELLED
    filled_qty: float
    avg_price: float | None


@dataclass
class _Order:
    client_id: str
    symbol: str
    side: str
    kind: str
    qty: float
    price: float | None
    stop_price: float | None
    status: str = "NEW"
    filled_qty: float = 0.0
    fill_notional: float = 0.0
    pending_fractions: list[float] = field(default_factory=list)

    def view(self) -> VenueOrderView:
        avg = self.fill_notional / self.filled_qty if self.filled_qty > 0 else None
        return VenueOrderView(
            client_id=self.client_id, symbol=self.symbol, side=self.side,
            kind=self.kind, qty=self.qty, price=self.price,
            stop_price=self.stop_price, status=self.status,
            filled_qty=self.filled_qty, avg_price=avg,
        )


@dataclass(frozen=True)
class _Fault:
    mode: str  # "timeout" | "reject" | "partial"
    received: bool = False  # for timeout: did the order reach the engine?
    reason: str = "injected-fault"
    fractions: tuple[float, ...] = (0.5, 0.5)  # for partial: first fills now, rest on settle()


class FakeVenue:
    def __init__(self, now_ms: Callable[[], int] | None = None, *,
                 lot_steps: dict[str, float] | None = None) -> None:
        self._now_ms = now_ms or (lambda: 0)
        self._orders: dict[str, _Order] = {}
        self._faults: deque[_Fault] = deque()
        self._last_price: dict[str, float] = {}
        self.fills: list[Fill] = []
        # V-008 §7: optional per-symbol LOT_SIZE steps. Absent = legacy
        # raw behavior (fault tests); present = venue floors with the one
        # shared rule, exactly like the economic path.
        self._lot_steps = {str(k).upper(): float(v)
                           for k, v in (lot_steps or {}).items()}

    def lot_step(self, symbol: str) -> float | None:
        """Configured LOT_SIZE step for ``symbol`` (None = raw legacy)."""
        return self._lot_steps.get(symbol.upper())

    # -- fault programming -------------------------------------------------
    def fail_next_submit(
        self,
        mode: str,
        *,
        received: bool = False,
        reason: str = "injected-fault",
        fractions: tuple[float, ...] = (0.5, 0.5),
    ) -> None:
        if mode not in ("timeout", "reject", "partial"):
            raise ValueError(f"unknown fault mode: {mode!r}")
        self._faults.append(_Fault(mode, received, reason, fractions))

    # -- venue API ---------------------------------------------------------
    def submit(
        self,
        client_id: str,
        symbol: str,
        side: str,
        kind: str,
        qty: float,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> SubmitResult:
        if qty <= 0:
            raise ValueError("qty must be > 0")
        step = self.lot_step(symbol)
        if step is not None:
            qty = floor_to_step(qty, step)
            if qty <= 0:
                raise ValueError(f"qty below LOT_SIZE step {step} for {symbol}")
        existing = self._orders.get(client_id)
        if existing is not None:
            # Idempotent client ID: no duplicate order, report current state.
            return SubmitResult(client_id, existing.status != "REJECTED", f"duplicate-client-id:{existing.status}")
        if kind in ("MARKET", "LIMIT") and price is None and symbol not in self._last_price:
            # F-E001-04: reject before storing, so a caller bug leaves no venue-side residue.
            raise ValueError(f"no price reference for {kind} submit of {client_id}")
        fault = self._faults.popleft() if self._faults else None
        if fault is not None and fault.mode == "reject":
            self._orders[client_id] = _Order(client_id, symbol, side, kind, qty, price, stop_price, status="REJECTED")
            return SubmitResult(client_id, False, fault.reason)
        order = _Order(client_id, symbol, side, kind, qty, price, stop_price)
        if fault is not None and fault.mode == "timeout":
            if fault.received:
                self._orders[client_id] = order
                self._try_immediate_fill(order)
            raise VenueTimeoutError(fault.reason)
        self._orders[client_id] = order
        if fault is not None and fault.mode == "partial":
            order.pending_fractions = list(fault.fractions[1:])
            self._apply_fill(order, order.qty * fault.fractions[0], self._ref_price(order))
            if order.filled_qty < order.qty:
                order.status = "PARTIALLY_FILLED"
            return SubmitResult(client_id, True, "accepted-partial")
        self._try_immediate_fill(order)
        return SubmitResult(client_id, True, "accepted")

    def query(self, client_id: str) -> VenueOrderView | None:
        """Reconciliation read. Returns None when the venue never saw the ID."""
        order = self._orders.get(client_id)
        return order.view() if order is not None else None

    def list_orders(self) -> list[VenueOrderView]:
        """List every order the venue holds, in submission order (for orphan sweeps)."""
        return [order.view() for order in self._orders.values()]

    def cancel(self, client_id: str) -> VenueOrderView | None:
        order = self._orders.get(client_id)
        if order is None or order.status in ("FILLED", "REJECTED", "CANCELLED"):
            return order.view() if order is not None else None
        order.status = "CANCELLED"
        order.pending_fractions.clear()
        return order.view()

    def set_last_price(self, symbol: str, price: float) -> list[Fill]:
        """Advance the market; trigger resting stop/target orders."""
        self._last_price[symbol] = price
        triggered: list[Fill] = []
        for order in self._orders.values():
            if order.symbol != symbol or order.status not in ("NEW", "PARTIALLY_FILLED"):
                continue
            if order.kind in ("STOP_MARKET", "TAKE_PROFIT_MARKET") and order.stop_price is not None:
                if self._stop_triggered(order, price):
                    triggered.extend(self._fill_rest(order, price))
        return triggered

    def settle(self) -> list[Fill]:
        """Advance pending partial fills by one fraction per order."""
        settled: list[Fill] = []
        for order in self._orders.values():
            if order.pending_fractions and order.status == "PARTIALLY_FILLED":
                fraction = order.pending_fractions.pop(0)
                settled.extend(self._apply_fill(order, order.qty * fraction, self._ref_price(order)))
        return settled

    def inject_fill(self, client_id: str, qty: float, price: float) -> list[Fill]:
        """FAULT SIMULATOR: force a fill onto an order (late-fill / exit-race cases).

        Works even on CANCELLED orders to model the cancel race (fill landed
        before the cancel processed, report arrived after). Rejected orders
        can never fill.
        """
        order = self._orders.get(client_id)
        if order is None:
            raise KeyError(f"unknown order: {client_id}")
        if order.status == "REJECTED":
            raise ValueError("cannot fill a rejected order")
        if qty <= 0:
            raise ValueError("qty must be > 0")
        return self._apply_fill(order, qty, price)

    # -- internals ---------------------------------------------------------
    def _ref_price(self, order: _Order) -> float:
        # F-E001-04: never fill at an invented 0.0; a market order with no
        # price reference is a caller bug and must raise loudly.
        if order.price is not None:
            return order.price
        if order.symbol in self._last_price:
            return self._last_price[order.symbol]
        raise ValueError(f"no price reference for MARKET fill of {order.client_id}")

    def _try_immediate_fill(self, order: _Order) -> None:
        if order.kind in ("MARKET", "LIMIT"):
            self._fill_rest(order, self._ref_price(order))

    def _stop_triggered(self, order: _Order, price: float) -> bool:
        assert order.stop_price is not None
        # Exit semantics: SELL stop triggers at/below stop, SELL target at/above stop.
        if order.kind == "STOP_MARKET":
            return price <= order.stop_price if order.side == "SELL" else price >= order.stop_price
        return price >= order.stop_price if order.side == "SELL" else price <= order.stop_price

    def _fill_rest(self, order: _Order, price: float) -> list[Fill]:
        remaining = order.qty - order.filled_qty
        if remaining <= 0:
            return []
        return self._apply_fill(order, remaining, price)

    def _apply_fill(self, order: _Order, qty: float, price: float) -> list[Fill]:
        order.filled_qty += qty
        order.fill_notional += qty * price
        if order.filled_qty >= order.qty - 1e-12:
            order.filled_qty = order.qty
            order.status = "FILLED"
            order.pending_fractions.clear()
        else:
            order.status = "PARTIALLY_FILLED"
        fill = Fill(order.client_id, order.symbol, price, qty)
        self.fills.append(fill)
        return [fill]
