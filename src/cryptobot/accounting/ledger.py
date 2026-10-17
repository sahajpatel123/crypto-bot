"""Deterministic ledger, USDT primary (Worker 3, v0.1.1 + V-004 corrections).

Tracks cash, one signed position, realised P&L, paid costs, signed funding
cash flows, and external flows. Flows (deposits/transfers) move equity but
never touch realised P&L; funding is a signed trading cash flow (it does
affect realised P&L). Marked equity (incl. open P&L and paid costs) and the
net-liquidation estimate (projected close costs) stay distinct.

F-CEO-01 correction: a partial reduction preserves the entry basis of the
remaining quantity; the basis resets only when flat. Every fill, funding
event, and flow carries a durable unique identity in an ordered journal, so
save/load replay is exact and re-submission is idempotent (no double fees,
no lost basis).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

LEDGER_VERSION = 1


@dataclass
class _Flow:
    ts_utc: datetime
    amount: float
    kind: str
    event_id: str


@dataclass
class _Funding:
    ts_utc: datetime
    amount: float
    event_id: str


@dataclass
class _Fill:
    side: str
    qty: float
    price: float
    fee: float
    ts_utc: datetime
    exec_id: str


def _require_finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


class Ledger:
    def __init__(self, pilot_equity: float) -> None:
        self._pilot_equity = _require_finite(pilot_equity, "pilot_equity")
        self._cash = float(pilot_equity)
        self._qty = 0.0
        self._avg_entry = 0.0
        self._realised = 0.0
        self._paid_costs = 0.0
        self._funding_net = 0.0
        self._fills: list[_Fill] = []
        self._flows: list[_Flow] = []
        self._funding: list[_Funding] = []
        self._journal: list[dict] = []
        self._seen_ids: set[str] = set()
        self._seq = 0

    def reseed_opening(self, equity: float) -> None:
        """Replace the opening equity with venue truth (T1.1).

        Only valid on a fresh ledger (no fills/funding/flows booked and
        flat): live startup seeds from the venue wallet instead of the
        paper config number. Refuses otherwise — reseeding over booked
        history would silently rewrite realised P&L.
        """
        equity = _require_finite(equity, "venue equity")
        if equity < 0:
            raise ValueError(f"venue equity must be >= 0, got {equity!r}")
        if self._journal or self._qty != 0.0:
            raise ValueError("reseed refused: ledger already has booked "
                             "history or an open position")
        self._pilot_equity = float(equity)
        self._cash = float(equity)

    # -- recording (idempotent by event identity) --------------------------
    def note_fill(
        self, exec_id: str, symbol: str, side: str,
        qty: float, price: float, fee: float, ts_utc: str,
    ) -> bool:
        """Engine-facing fill ingestion (V-006 S4 seam for E-007).

        Validates the v0.2.0 delta contract (non-empty ids/symbol, BUY/SELL,
        positive finite qty/price, non-negative finite fee, ISO-8601 UTC
        timestamp) and books idempotently. False when exec_id was already
        booked. Run-mode zero-fee policy is enforced by the policy sink,
        not here.
        """
        if not exec_id or not isinstance(exec_id, str):
            raise ValueError("exec_id must be a non-empty string")
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string")
        try:
            ts = datetime.fromisoformat(ts_utc)
        except (TypeError, ValueError):
            raise ValueError(f"ts_utc must be ISO-8601, got {ts_utc!r}") from None
        if ts.tzinfo is None or ts.utcoffset() is None or ts.utcoffset().total_seconds() != 0:
            raise ValueError(f"ts_utc must carry a UTC offset, got {ts_utc!r}")
        return self.record_fill(side, qty, price, fee, ts, exec_id, symbol=symbol)

    def note_funding(self, event_id: str, amount: float, ts_utc: str) -> bool:
        """Engine-facing funding ingestion (V-006 S4 seam for E-007)."""
        if not event_id or not isinstance(event_id, str):
            raise ValueError("event_id must be a non-empty string")
        try:
            ts = datetime.fromisoformat(ts_utc)
        except (TypeError, ValueError):
            raise ValueError(f"ts_utc must be ISO-8601, got {ts_utc!r}") from None
        if ts.tzinfo is None or ts.utcoffset() is None or ts.utcoffset().total_seconds() != 0:
            raise ValueError(f"ts_utc must carry a UTC offset, got {ts_utc!r}")
        return self.record_funding(amount, ts, event_id)

    def record_fill(
        self, side: str, qty: float, price: float, fee: float, ts: datetime,
        exec_id: str | None = None, symbol: str = "",
    ) -> bool:
        """Book one fill increment. False when exec_id was already booked."""
        qty = _require_finite(qty, "qty")
        price = _require_finite(price, "price")
        fee = _require_finite(fee, "fee")
        if qty <= 0:
            raise ValueError("qty must be > 0")
        if price <= 0:
            raise ValueError("price must be > 0")
        if fee < 0:
            raise ValueError("fee must be >= 0")
        if side == "BUY":
            signed = qty
        elif side == "SELL":
            signed = -qty
        else:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        exec_id = self._claim_id(exec_id, "fill")
        if exec_id is None:
            return False
        self._fills.append(_Fill(side, qty, price, fee, ts, exec_id))
        self._journal.append({"kind": "fill", "side": side, "qty": qty,
                              "price": price, "fee": fee,
                              "ts_utc": ts.isoformat(), "exec_id": exec_id,
                              "symbol": symbol})
        self._cash -= fee
        self._paid_costs += fee
        self._realised -= fee
        if self._qty == 0.0:
            self._qty = signed
            self._avg_entry = price
            self._cash -= signed * price
            return True
        if (self._qty > 0) == (signed > 0):
            total = abs(self._qty) + abs(signed)
            self._avg_entry = (abs(self._qty) * self._avg_entry + abs(signed) * price) / total
            self._qty += signed
            self._cash -= signed * price
            return True
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
        elif self._qty == 0.0:
            self._avg_entry = 0.0
        # else: partial reduction — entry basis of the remainder is preserved.
        return True

    def record_funding(self, amount: float, ts: datetime, event_id: str | None = None) -> bool:
        """Book a signed funding cash flow (affects cash and realised P&L)."""
        amount = _require_finite(amount, "funding amount")
        event_id = self._claim_id(event_id, "funding")
        if event_id is None:
            return False
        self._funding.append(_Funding(ts, amount, event_id))
        self._journal.append({"kind": "funding", "amount": amount,
                              "ts_utc": ts.isoformat(), "event_id": event_id})
        self._cash += amount
        self._realised += amount
        self._funding_net += amount
        return True

    def record_flow(
        self, amount: float, kind: str, ts: datetime, event_id: str | None = None
    ) -> bool:
        """Book an external flow (moves equity, never realised P&L)."""
        amount = _require_finite(amount, "flow amount")
        event_id = self._claim_id(event_id, "flow")
        if event_id is None:
            return False
        self._cash += amount
        self._flows.append(_Flow(ts, amount, kind, event_id))
        self._journal.append({"kind": "flow", "amount": amount, "flow_kind": kind,
                              "ts_utc": ts.isoformat(), "event_id": event_id})
        return True

    # -- positions and equity ----------------------------------------------
    def marked_equity(self, ref_price: float) -> float:
        return self._cash + self._qty * _require_finite(ref_price, "ref_price")

    def net_liquidation(self, ref_price: float, close_cost_bps: float) -> float:
        ref_price = _require_finite(ref_price, "ref_price")
        close_cost_bps = _require_finite(close_cost_bps, "close_cost_bps")
        return self.marked_equity(ref_price) - abs(self._qty * ref_price) * close_cost_bps / 10000

    def position_qty(self) -> float:
        return self._qty

    def has_position(self) -> bool:
        return self._qty != 0.0

    def entry_basis(self) -> float | None:
        return self._avg_entry if self._qty != 0.0 else None

    def net_realised(self) -> float:
        return self._realised

    def paid_costs(self) -> float:
        return self._paid_costs

    def funding_net(self) -> float:
        return self._funding_net

    def total_flows(self) -> float:
        """Lifetime net external flows (cumulative, for flow baselines)."""
        return sum(f.amount for f in self._flows)

    def flows_since(self, since_utc: datetime) -> float:
        return sum(f.amount for f in self._flows if f.ts_utc >= since_utc)

    def flow_adjusted(self, marked: float, since_utc: datetime) -> float:
        """Marked equity with post-reference flows backed out (halt reference)."""
        return marked - self.flows_since(since_utc)

    # -- durability: ordered journal replay ----------------------------------
    def _snapshot(self) -> dict:
        return {
            "cash": self._cash, "qty": self._qty, "avg_entry": self._avg_entry,
            "realised": self._realised, "paid_costs": self._paid_costs,
            "funding_net": self._funding_net, "seq": self._seq,
        }

    def to_dict(self) -> dict:
        return {
            "version": LEDGER_VERSION,
            "pilot_equity": self._pilot_equity,
            "seq": self._seq,
            "journal": [dict(entry) for entry in self._journal],
            "snapshot": self._snapshot(),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Ledger":
        if raw.get("version") != LEDGER_VERSION:
            raise ValueError(f"unsupported ledger version: {raw.get('version')!r}")
        ledger = cls(raw["pilot_equity"])
        for entry in raw.get("journal", []):
            ts = datetime.fromisoformat(entry["ts_utc"])
            kind = entry["kind"]
            if kind == "fill":
                ok = ledger.record_fill(entry["side"], entry["qty"], entry["price"],
                                        entry["fee"], ts, entry["exec_id"],
                                        symbol=entry.get("symbol", ""))
            elif kind == "funding":
                ok = ledger.record_funding(entry["amount"], ts, entry["event_id"])
            elif kind == "flow":
                ok = ledger.record_flow(entry["amount"], entry["flow_kind"], ts,
                                        entry["event_id"])
            else:
                raise ValueError(f"unknown journal kind: {kind!r}")
            if not ok:
                raise ValueError("ledger journal replays a duplicate event id")
        ledger._seq = max(int(raw.get("seq", 0)), ledger._seq)
        if ledger._snapshot() != raw.get("snapshot"):
            raise ValueError("ledger journal does not reconcile with its snapshot")
        return ledger

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"
        with NamedTemporaryFile("w", dir=str(path.parent), delete=False, encoding="utf-8") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_name = tmp.name
        os.replace(tmp_name, path)

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- internals -------------------------------------------------------------
    def _claim_id(self, event_id: str | None, prefix: str) -> str | None:
        if event_id is None:
            self._seq += 1
            event_id = f"auto-{prefix}-{self._seq:06d}"
        elif not event_id:
            raise ValueError("event_id must be non-empty")
        if event_id in self._seen_ids:
            return None
        self._seen_ids.add(event_id)
        return event_id
