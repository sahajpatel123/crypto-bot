"""Operator commands. Prod refuses unless a human arm record exists.

Emulator and sandbox actions go through RiskPolicy, then the sandbox
venue. Nothing here places a real or demo order.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptobot.adapters.sandbox_venue import SYMBOLS, SandboxVenue
from cryptobot.coordination.intent import DataQuality, ForecastCost, Intent, Side
from cryptobot.risk.policy import RiskPolicy
from cryptobot.risk.rounding import floor_to_step, round_to_tick
from cryptobot.risk.types import AccountSnapshot, Approved, RiskConfig


def prod_arm_refusal(mode: str, armed_path: Path, gate_path: Path) -> str | None:
    if mode != "prod":
        return None
    try:
        armed = json.loads(armed_path.read_text(encoding="utf-8"))
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "ops: REFUSED prod without a valid human arm"
    if not armed.get("armed") or gate.get("gate") != "GO":
        return "ops: REFUSED prod without a valid human arm"
    try:
        expiry = datetime.fromisoformat(str(gate.get("expires_utc", "")))
    except ValueError:
        return "ops: REFUSED prod gate expiry unreadable"
    if expiry < datetime.now(UTC):
        return "ops: REFUSED prod gate expired"
    return None


def _intent(symbol: str, side: str, price: float, now: datetime) -> Intent:
    venue_side = Side.LONG if side == "BUY" else Side.SHORT
    if venue_side == Side.LONG:
        low, high, invalid = price * 0.999, price * 1.001, price * 0.99
    else:
        low, high, invalid = price * 0.999, price * 1.001, price * 1.01
    return Intent(
        strategy="ops", version="1", instrument=symbol, side=venue_side,
        evidence_ts_utc=now,
        entry_low=low, entry_high=high,
        entry_expiry_utc=now + timedelta(minutes=5),
        invalidation_price=invalid, exit_rule="ops-manual",
        holding_limit_s=300,
        forecast_cost=ForecastCost(5.0, 1.0, 1.0, 0.0, label="ops"),
        evidence_ref="ops", data_quality=DataQuality.CLEAN)


def admit(symbol: str, side: str, qty: float, price: float,
          state_path: Path) -> Approved | str:
    now = datetime.now(UTC)
    policy = RiskPolicy(RiskConfig(), state_path=state_path, now_utc=lambda: now)
    policy.reconcile_day(10_000.0, 0.0)
    account = AccountSnapshot(
        reconciled_equity=10_000.0, marked_equity=10_000.0,
        net_liquidation=10_000.0, net_realised_global=0.0,
        open_position=False, available_margin_usdt=10_000.0,
        mark_age_ms=0.0)
    decision = policy.evaluate(_intent(symbol, side, price, now), account)
    if isinstance(decision, Approved):
        return decision
    return f"ops: REFUSED risk {decision.reason}"


def journal(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(record)
    row["provenance"] = "EMULATED" if row.get("mode") != "prod" else "OBSERVED"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


class Book:
    """In-process sandbox book for ops. Not a live venue."""

    def __init__(self) -> None:
        self.venue = SandboxVenue()
        self.paused = False

    def snapshot(self) -> dict:
        account = self.venue.account_view()
        return {"paused": self.paused,
                "positions": account.get("positions", []),
                "orders": self.venue.open_orders(),
                "algo_orders": self.venue.open_algo_orders(),
                "provenance": "EMULATED"}


def apply_order(book: Book, *, symbol: str, side: str, qty: float,
                kind: str, price: float | None, reduce_only: bool,
                state_path: Path, stop_price: float | None = None,
                post_only: bool = False,
                client_id: str | None = None) -> dict:
    if book.paused and not reduce_only:
        return {"ok": False, "message": "ops: REFUSED entries paused"}
    px = round_to_tick(price or book.venue.mid(symbol),
                       float(SYMBOLS.get(symbol.upper(), {"tick": 0.01})["tick"]))
    qty_out = qty
    notional = qty * px
    if not reduce_only:
        decision = admit(symbol, side, qty, px, state_path)
        if isinstance(decision, str):
            return {"ok": False, "message": decision}
        qty_out = decision.qty or qty
        notional = decision.notional_usdt
    spec = SYMBOLS.get(symbol.upper())
    if spec is None:
        return {"ok": False,
                "message": f"ops: REFUSED unknown symbol {symbol}"}
    qty_out = floor_to_step(qty_out, float(spec["step"]))
    if qty_out < float(spec["min_qty"]):
        return {"ok": False,
                "message": "ops: REFUSED qty below venue minimum"}
    px = round_to_tick(px, float(spec["tick"]))
    if stop_price is not None:
        stop_price = round_to_tick(stop_price, float(spec["tick"]))
    if kind in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
        if stop_price is None:
            return {"ok": False,
                    "message": "ops: REFUSED conditional needs --stop-price"}
        params = {"symbol": symbol, "side": side, "type": kind,
                  "quantity": qty_out,
                  "stopPrice": stop_price}
        if client_id:
            params["clientAlgoId"] = client_id
        try:
            placed = book.venue.place_algo(params)
        except Exception as exc:
            return {"ok": False, "message": f"ops: REFUSED venue {exc}"}
        return {"ok": True, "order": placed,
                "notional": notional}
    params = {"symbol": symbol, "side": side, "type": kind,
              "quantity": qty_out}
    if client_id:
        params["newClientOrderId"] = client_id
    if kind == "LIMIT":
        params["price"] = px
        if post_only:
            touch = book.venue.mid(symbol)
            marketable = (touch <= px) if side == "BUY" else (touch >= px)
            if marketable:
                return {"ok": False,
                        "message": "ops: REFUSED post-only would take"}
            params["timeInForce"] = "GTX"
        else:
            params["timeInForce"] = "GTC"
    if reduce_only:
        params["reduceOnly"] = "true"
    try:
        placed = book.venue.place_order(params)
    except Exception as exc:
        return {"ok": False, "message": f"ops: REFUSED venue {exc}"}
    return {"ok": True, "order": placed, "notional": notional}


def flatten(book: Book, symbol: str | None) -> dict:
    account = book.venue.account_view()
    done = []
    for pos in account.get("positions", []):
        if symbol and pos["symbol"] != symbol:
            continue
        qty = float(pos["positionAmt"])
        if abs(qty) < 1e-12:
            continue
        side = "SELL" if qty > 0 else "BUY"
        book.venue.place_order({
            "symbol": pos["symbol"], "side": side, "type": "MARKET",
            "quantity": abs(qty), "reduceOnly": "true"})
        done.append(pos["symbol"])
    return {"ok": True, "flattened": done, "provenance": "EMULATED"}


def cancel_one(book: Book, client_id: str) -> dict:
    try:
        row = book.venue.cancel_order({"origClientOrderId": client_id})
        return {"ok": True, "canceled": row, "provenance": "EMULATED"}
    except Exception:
        pass
    try:
        row = book.venue.cancel_algo({"origClientAlgoId": client_id})
        return {"ok": True, "canceled": row, "provenance": "EMULATED"}
    except Exception as exc:
        return {"ok": False, "message": f"ops: REFUSED unknown order {exc}"}


def cancel_all(book: Book) -> dict:
    canceled = 0
    for row in list(book.venue.open_orders()):
        try:
            book.venue.cancel_order(
                {"origClientOrderId": row["clientOrderId"]})
            canceled += 1
        except Exception:
            continue
    for row in list(book.venue.open_algo_orders()):
        try:
            book.venue.cancel_algo(
                {"origClientAlgoId": row["clientAlgoId"]})
            canceled += 1
        except Exception:
            continue
    return {"ok": True, "canceled": canceled, "provenance": "EMULATED"}
