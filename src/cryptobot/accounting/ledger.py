"""Minimal deterministic ledger, USDT primary (Worker 3 ledger review).

Tracks cash, one signed position, realised P&L, paid costs, and external
flows. Flows (deposits/transfers) move equity but never touch realised P&L.
Marked equity (incl. open P&L and paid costs) and the net-liquidation estimate
(projected close costs) are kept distinct per CONTRACTS v0.1.0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class _Flow:
    ts_utc: datetime
    amount: float
    kind: str


class Ledger:
    def __init__(self, pilot_equity: float) -> None:
        self._cash = float(pilot_equity)
        self._qty = 0.0
        self._avg_entry = 0.0
        self._realised = 0.0
        self._paid_costs = 0.0
        self._flows: list[_Flow] = []

    def record_flow(self, amount: float, kind: str, ts: datetime) -> None:
        self._cash += amount
        self._flows.append(_Flow(ts, float(amount), kind))

    def record_fill(self, side: str, qty: float, price: float, fee: float, ts: datetime) -> None:
        del ts
        if qty <= 0:
            raise ValueError("qty must be > 0")
        if side == "BUY":
            signed = qty
        elif side == "SELL":
            signed = -qty
        else:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        self._cash -= fee
        self._paid_costs += fee
        self._realised -= fee
        if self._qty == 0.0:
            self._qty = signed
            self._avg_entry = price
            self._cash -= signed * price
            return
        if (self._qty > 0) == (signed > 0):
            total = abs(self._qty) + abs(signed)
            self._avg_entry = (abs(self._qty) * self._avg_entry + abs(signed) * price) / total
            self._qty += signed
            self._cash -= signed * price
            return
        direction = 1.0 if self._qty > 0 else -1.0
        close_mag = min(abs(self._qty), abs(signed))
        self._realised += close_mag * (price - self._avg_entry) * direction
        self._cash += close_mag * price * direction
        self._qty -= direction * close_mag
        remainder = signed + direction * close_mag
        if remainder != 0.0:
            self._qty = remainder
            self._avg_entry = price
            self._cash -= remainder * price
        else:
            self._avg_entry = 0.0

    def marked_equity(self, ref_price: float) -> float:
        return self._cash + self._qty * ref_price

    def net_liquidation(self, ref_price: float, close_cost_bps: float) -> float:
        return self.marked_equity(ref_price) - abs(self._qty * ref_price) * close_cost_bps / 10000

    def net_realised(self) -> float:
        return self._realised

    def paid_costs(self) -> float:
        return self._paid_costs

    def flows_since(self, since_utc: datetime) -> float:
        return sum(f.amount for f in self._flows if f.ts_utc >= since_utc)

    def flow_adjusted(self, marked: float, since_utc: datetime) -> float:
        """Marked equity with post-reference flows backed out (halt reference)."""
        return marked - self.flows_since(since_utc)
