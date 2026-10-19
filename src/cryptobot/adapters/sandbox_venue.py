"""Scriptable offline Binance USD-M sandbox venue (DEEP-W2-D3).

Implements the engine's ``LiveTransport`` REST dialogue plus user-stream
sockets against a SEEDED, fully offline simulated venue: book, filters,
fees/funding, IOC/market/algo matching, partials, cancels, lookup,
snapshots, listenKey lifecycle, ORDER_TRADE_UPDATE reorder/dupe,
rate-limit and UNKNOWN injects. Every simulated response is labeled
(``sandboxSimulated: True`` on dict payloads/envelopes; lists are
documented venue-truth shapes — see below).

NOT a market model: prices are a seeded walk (deterministic per
250ms tick index + seed), spreads/sizes are configured constants.
It proves EXECUTION MECHANICS (submit/fill/cancel/lookup/reconcile/
stream-gap/rate-limit/unknown paths) through the REAL
BinanceLiveEngine + Session + user-stream code. Venue fee/funding
numbers are hand-built fixtures until re-recorded on testnet.

Determinism: ``seed`` pins the RNG (fills ids, faults, walk noise).
Venue time is wall-anchored (the engine skew gate needs it); the
price path is a pure function of (seed, tick) so equal wall ticks
reproduce. Fault scripts are explicit and logged.
"""
from __future__ import annotations

import copy
import json
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptobot.adapters.binance_live import VenueHttpError

LABEL_KEY = "sandboxSimulated"

SYMBOLS = {
    "BTCUSDT": {"base": 60000.0, "tick": 0.10, "step": 0.001,
                "min_qty": 0.001, "min_notional": 5.0,
                "taker_bps": 5.0, "funding_8h": 0.0001,
                "spread_bps": 1.0, "size": 10.0},
    "ETHUSDT": {"base": 2500.0, "tick": 0.01, "step": 0.001,
                "min_qty": 0.001, "min_notional": 5.0,
                "taker_bps": 5.0, "funding_8h": 0.0001,
                "spread_bps": 1.0, "size": 100.0},
}

FUNDING_DAY_MS = [0, 8 * 3600_000, 16 * 3600_000]  # UTC boundaries.


@dataclass
class FaultScript:
    """Scripted venue faults, applied in request order (logged).

    Each entry: {"op": <path suffix or "stream" or "submit:<n>">,
    "action": "rate-limit" | "unknown" | "partial-legs" |
    "reorder" | "dupe" | "die" | "expire-key" | "void-lookup",
    "at": <1-based request counter, or "always"/"once">}.
    """
    entries: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SandboxConfig:
    seed: int = 7
    virtual_capital_usdt: float = 10000.0
    leverage: int = 3
    submit_delay_ms: int = 0
    fill_delay_ms: int = 0
    faults: FaultScript = field(default_factory=FaultScript)
    walk_bps_per_tick: float = 2.0  # tick = 250ms.


class SandboxVenue:
    """Stateful offline USD-M venue (single-threaded, deterministic)."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.cfg = config or SandboxConfig()
        self.rng = random.Random(self.cfg.seed)
        self.request_no = 0
        self.log: list[dict[str, Any]] = []  # every request + faults.
        self._order_seq = 100000
        self._trade_seq = 777000
        self._algo_seq = 500000
        self.orders: dict[str, dict[str, Any]] = {}  # venue orderId -> row.
        self.by_client: dict[str, str] = {}  # client id -> venue orderId.
        self.algos: dict[str, dict[str, Any]] = {}  # algoId -> row.
        self.algo_by_client: dict[str, str] = {}
        self.trades: list[dict[str, Any]] = []  # userTrades tape.
        self.positions: dict[str, dict[str, float]] = {}
        self.wallet = float(self.cfg.virtual_capital_usdt)
        self.realized = 0.0
        self.fees_paid = 0.0
        self.funding_rows: list[dict[str, Any]] = []
        self._funding_cursor_ms = 0
        self.listen_key: str | None = None
        self.key_deadline_ms = 0
        self.stream_queue: list[dict[str, Any]] = []
        self._walk_cache: dict[int, float] = {}
        self._fault_hits: list[dict[str, Any]] = []
        self._stream_die_armed = False

    # -- clock / market data ------------------------------------------------
    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def _walk(self, tick: int) -> float:
        if tick not in self._walk_cache:
            prev = self._walk_cache.get(tick - 1, 0.0)
            self._walk_cache[tick] = prev + self.rng.gauss(
                0.0, self.cfg.walk_bps_per_tick / 10000.0)
        return self._walk_cache[tick]

    def mid(self, symbol: str, now_ms: int | None = None) -> float:
        base = SYMBOLS[symbol.upper()]["base"]
        tick = (now_ms if now_ms is not None else self.now_ms()) // 250
        return base * math.exp(self._walk(tick))

    def book(self, symbol: str) -> dict[str, float]:
        spec = SYMBOLS[symbol.upper()]
        now = self.now_ms()
        mid = self.mid(symbol, now)
        half = mid * spec["spread_bps"] / 10000.0 / 2.0
        return {"bid": mid - half, "ask": mid + half,
                "bid_qty": spec["size"], "ask_qty": spec["size"],
                "ts_ms": now}

    def set_size(self, symbol: str, size: float) -> None:
        """Override displayed size (partial-fill legs)."""
        SYMBOLS[symbol.upper()]["size"] = size

    # -- faults ---------------------------------------------------------------
    def _fault_for(self, op: str) -> dict[str, Any] | None:
        for entry in self.cfg.faults.entries:
            at = entry.get("at", "always")
            if at != "always" and at != "once":
                continue
            if entry.get("op") not in (op, "*"):
                continue
            if at == "once" and entry.get("_fired"):
                continue
            entry["_fired"] = True
            self._fault_hits.append({"op": op, "action": entry["action"],
                                     "request_no": self.request_no})
            return entry
        return None

    def _maybe_request_fault(self, op: str) -> None:
        fault = self._fault_for(op)
        if fault is None:
            return
        action = fault["action"]
        if action == "rate-limit":
            raise VenueHttpError(429, -1003,
                                 "sandbox: Way too many requests")
        if action == "unknown":
            raise VenueHttpError(503, None, "sandbox: response dropped")
        if action == "partial-legs":
            for spec in SYMBOLS.values():
                spec["size"] = 0.0001  # below any drill qty.
        if action == "expire-key":
            self.listen_key = None
            self.stream_queue.append(
                {"e": "listenKeyExpired", "E": self.now_ms(),
                 LABEL_KEY: True})
        if action == "die":
            self._stream_die_armed = True

    # -- positions / balances -------------------------------------------------
    def _position(self, symbol: str) -> dict[str, float]:
        return self.positions.setdefault(
            symbol.upper(), {"qty": 0.0, "entry": 0.0})

    def _apply_fill(self, symbol: str, side: str, qty: float,
                    price: float) -> float:
        """Update position + wallet; returns USDT commission."""
        spec = SYMBOLS[symbol.upper()]
        fee = qty * price * spec["taker_bps"] / 10000.0
        self.fees_paid += fee
        self.wallet -= fee
        pos = self._position(symbol)
        signed = qty if side == "BUY" else -qty
        old = pos["qty"]
        new = old + signed
        if old == 0.0:
            pos["entry"] = price
        elif new == 0.0:
            self.realized += (price - pos["entry"]) * old
            self.wallet += (price - pos["entry"]) * old
            pos["entry"] = 0.0
        elif (old > 0) == (new > 0) and abs(new) < abs(old):
            closed = old - new  # same sign as old.
            self.realized += (price - pos["entry"]) * closed
            self.wallet += (price - pos["entry"]) * closed
        elif (old > 0) != (new > 0):
            self.realized += (price - pos["entry"]) * old
            self.wallet += (price - pos["entry"]) * old
            pos["entry"] = price
        else:  # adding.
            pos["entry"] = (pos["entry"] * abs(old) + price * qty) / \
                abs(new)
        pos["qty"] = new
        return fee

    # -- orders -----------------------------------------------------------------
    def _next_ids(self) -> tuple[int, int]:
        self._order_seq += 1
        self._trade_seq += 1
        return self._order_seq, self._trade_seq

    def _stream_envelope(self, order: dict[str, Any], x: str,
                         last_qty: float = 0.0, last_px: float = 0.0,
                         fee: float = 0.0, trade_id: int = 0) -> dict:
        return {
            "e": "ORDER_TRADE_UPDATE", "E": self.now_ms(),
            LABEL_KEY: True,
            "o": {
                "s": order["symbol"], "c": order["client_id"],
                "S": order["side"], "o": order["kind"],
                "X": order["status"], "x": x,
                "i": order["order_id"], "l": f"{last_qty:.8f}",
                "z": f"{order['filled']:.8f}",
                "L": f"{last_px:.2f}", "ap": f"{order['avg']:.2f}",
                "n": f"{fee:.8f}", "N": "USDT",
                "t": trade_id if trade_id else 0,
            },
        }

    def _record_trade(self, order: dict[str, Any], qty: float,
                      price: float, fee: float, trade_id: int) -> None:
        self.trades.append({
            "symbol": order["symbol"], "id": trade_id,
            "orderId": order["order_id"], "side": order["side"],
            "price": f"{price:.2f}", "qty": f"{qty:.8f}",
            "commission": f"{fee:.8f}", "commissionAsset": "USDT",
            "time": self.now_ms(), "buyer": order["side"] == "BUY",
        })

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        """POST /fapi/v1/order — MARKET full, LIMIT IOC (partials ok)."""
        symbol = str(params["symbol"]).upper()
        side = str(params["side"])
        kind = str(params["type"])
        qty = float(params["quantity"])
        cid = str(params.get("newClientOrderId",
                             f"sandbox-{self._order_seq + 1}"))
        if cid in self.by_client:
            raise VenueHttpError(400, -2013, "sandbox: duplicate client id")
        spec = SYMBOLS[symbol]
        # Notional at ORDER price (venue semantics). Relative 1e-3
        # dust tolerance absorbs sim float/walk microstructure at the
        # boundary (documented, labeled); real violations still reject.
        ref_px = float(params["price"]) if kind == "LIMIT" \
            else self.mid(symbol)
        if qty < spec["min_qty"] or qty * ref_px < \
                spec["min_notional"] * (1.0 - 1e-3):
            raise VenueHttpError(400, -2013 - 1,
                                 "sandbox: below venue minimums")
        reduce_only = str(params.get("reduceOnly", "false")) == "true"
        if reduce_only:
            pos_qty = self._position(symbol)["qty"]
            signed = qty if side == "BUY" else -qty
            closing = (pos_qty > 0 > signed) or (pos_qty < 0 < signed)
            if not closing or abs(signed) > abs(pos_qty) + 1e-12:
                raise VenueHttpError(
                    400, -2022, "sandbox: ReduceOnly Order is rejected")
        book = self.book(symbol)
        touch = book["ask"] if side == "BUY" else book["bid"]
        size = book["ask_qty"] if side == "BUY" else book["bid_qty"]
        fill_qty, status = 0.0, "NEW"
        if kind == "MARKET":
            fill_qty, status = qty, "FILLED"
        elif kind == "LIMIT":
            limit = float(params["price"])
            tif = str(params.get("timeInForce", "GTC"))
            marketable = (touch <= limit) if side == "BUY" \
                else (touch >= limit)
            if marketable:
                fill_qty = min(qty, size)
                status = "FILLED" if fill_qty >= qty else \
                    "PARTIALLY_FILLED"
                if tif == "IOC" and fill_qty < qty:
                    status = "CANCELED" if fill_qty <= 0 else \
                        "PARTIALLY_FILLED"
                    # IOC remainder cancels; partial keeps its fills.
                    if fill_qty <= 0:
                        status = "CANCELED"
            else:
                status = "CANCELED" if tif == "IOC" else "NEW"
        else:
            raise VenueHttpError(400, -4120, "sandbox: use algoOrder rail")
        order_id, trade_id = self._next_ids()
        order = {"symbol": symbol, "side": side, "kind": kind,
                 "qty": qty, "client_id": cid, "order_id": order_id,
                 "status": status, "filled": 0.0, "avg": touch,
                 "reduce_only": str(params.get("reduceOnly",
                                               "false")) == "true"}
        fee = 0.0
        if fill_qty > 0:
            fee = self._apply_fill(symbol, side, fill_qty, touch)
            order["filled"] = fill_qty
            order["avg"] = touch
            self._record_trade(order, fill_qty, touch, fee, trade_id)
            self.stream_queue.append(self._stream_envelope(
                order, "TRADE", fill_qty, touch, fee, trade_id))
        else:
            self.stream_queue.append(self._stream_envelope(order, status))
        self.orders[str(order_id)] = order
        self.by_client[cid] = str(order_id)
        return {"symbol": symbol, "orderId": order_id,
                "clientOrderId": cid, "origQty": f"{qty:.8f}",
                "executedQty": f"{order['filled']:.8f}",
                "status": status, LABEL_KEY: True}

    def query_order(self, params: dict[str, Any]) -> dict[str, Any]:
        cid = str(params.get("origClientOrderId", ""))
        oid = self.by_client.get(cid)
        if oid is None or oid not in self.orders:
            raise VenueHttpError(400, -2013, "sandbox: unknown order")
        order = self.orders[oid]
        return {"symbol": order["symbol"], "orderId": order["order_id"],
                "clientOrderId": cid, "origQty": f"{order['qty']:.8f}",
                "executedQty": f"{order['filled']:.8f}",
                "status": order["status"], LABEL_KEY: True}

    def cancel_order(self, params: dict[str, Any]) -> dict[str, Any]:
        cid = str(params.get("origClientOrderId", ""))
        oid = self.by_client.get(cid)
        if oid is None or oid not in self.orders:
            raise VenueHttpError(400, -2013, "sandbox: unknown order")
        order = self.orders[oid]
        if order["status"] in ("FILLED", "CANCELED", "REJECTED",
                               "EXPIRED"):
            raise VenueHttpError(400, -2011, "sandbox: already terminal")
        order["status"] = "CANCELED"
        self.stream_queue.append(self._stream_envelope(order, "CANCELED"))
        return {"symbol": order["symbol"], "orderId": order["order_id"],
                "clientOrderId": cid, "status": "CANCELED",
                LABEL_KEY: True}

    def open_orders(self) -> list[dict[str, Any]]:
        return [{"symbol": o["symbol"], "orderId": o["order_id"],
                 "clientOrderId": o["client_id"],
                 "origQty": f"{o['qty']:.8f}",
                 "executedQty": f"{o['filled']:.8f}",
                 "status": o["status"]}
                for o in self.orders.values()
                if o["status"] in ("NEW", "PARTIALLY_FILLED")]

    def user_trades(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        oid = params.get("orderId")
        out = [t for t in self.trades
               if str(t["orderId"]) == str(oid)]
        return copy.deepcopy(out)

    # -- algo (conditional) orders -------------------------------------------------
    def place_algo(self, params: dict[str, Any]) -> dict[str, Any]:
        """POST /fapi/v1/algoOrder — STOP_MARKET / TAKE_PROFIT_MARKET."""
        symbol = str(params["symbol"]).upper()
        side = str(params["side"])
        kind = str(params["type"])
        if kind not in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            raise VenueHttpError(400, -2013 - 2,
                                 "sandbox: algo rail takes conditionals")
        qty = float(params["quantity"])
        cid = str(params.get("clientAlgoId",
                             f"sandbox-algo-{self._algo_seq + 1}"))
        if cid in self.algo_by_client:
            raise VenueHttpError(400, -2013, "sandbox: duplicate algo id")
        self._algo_seq += 1
        algo_id = str(self._algo_seq)
        row = {"symbol": symbol, "side": side, "kind": kind, "qty": qty,
               "client_id": cid, "algo_id": algo_id,
               "stop": float(params["stopPrice"]),
               "status": "WORKING", "filled": 0.0,
               "triggered_id": None, "reduce_only": True}
        self.algos[algo_id] = row
        self.algo_by_client[cid] = algo_id
        self.stream_queue.append({
            "e": "ALGO_UPDATE", "E": self.now_ms(), LABEL_KEY: True,
            "o": {"s": symbol, "c": cid, "S": side, "X": "WORKING",
                  "x": "NEW", "i": int(algo_id), "ti": 0}})
        return {"symbol": symbol, "algoId": int(algo_id),
                "clientAlgoId": cid, "algoStatus": "WORKING",
                LABEL_KEY: True}

    def query_algo(self, params: dict[str, Any]) -> dict[str, Any]:
        cid = str(params.get("origClientAlgoId", ""))
        aid = self.algo_by_client.get(cid)
        if aid is None or aid not in self.algos:
            raise VenueHttpError(400, -2013, "sandbox: unknown algo")
        row = self.algos[aid]
        return {"symbol": row["symbol"], "algoId": int(aid),
                "clientAlgoId": cid, "algoStatus": row["status"],
                "triggeredOrderId": row["triggered_id"],
                "origQty": f"{row['qty']:.8f}",
                "executedQty": f"{row['filled']:.8f}", LABEL_KEY: True}

    def cancel_algo(self, params: dict[str, Any]) -> dict[str, Any]:
        cid = str(params.get("origClientAlgoId", ""))
        aid = self.algo_by_client.get(cid)
        if aid is None or aid not in self.algos:
            raise VenueHttpError(400, -2013, "sandbox: unknown algo")
        row = self.algos[aid]
        if row["status"] != "WORKING":
            raise VenueHttpError(400, -2011, "sandbox: algo not working")
        row["status"] = "CANCELED"
        self.stream_queue.append({
            "e": "ALGO_UPDATE", "E": self.now_ms(), LABEL_KEY: True,
            "o": {"s": row["symbol"], "c": cid, "S": row["side"],
                  "X": "CANCELED", "x": "CANCELED",
                  "i": int(aid), "ti": 0}})
        return {"symbol": row["symbol"], "algoId": int(aid),
                "clientAlgoId": cid, "algoStatus": "CANCELED",
                LABEL_KEY: True}

    def open_algo_orders(self) -> list[dict[str, Any]]:
        return [{"symbol": r["symbol"], "algoId": int(a),
                 "clientAlgoId": r["client_id"],
                 "algoStatus": r["status"],
                 "origQty": f"{r['qty']:.8f}",
                 "executedQty": f"{r['filled']:.8f}"}
                for a, r in self.algos.items() if r["status"] == "WORKING"]

    def _poll_algos(self) -> None:
        """Trigger working conditionals against the live mark."""
        for aid, row in self.algos.items():
            if row["status"] != "WORKING":
                continue
            mark = self.mid(row["symbol"])
            stop = row["stop"]
            side, kind = row["side"], row["kind"]
            if kind == "STOP_MARKET":
                hit = (mark >= stop) if side == "BUY" else (mark <= stop)
            else:  # TAKE_PROFIT_MARKET
                hit = (mark <= stop) if side == "BUY" else (mark >= stop)
            if not hit:
                continue
            book = self.book(row["symbol"])
            touch = book["ask"] if side == "BUY" else book["bid"]
            order_id, trade_id = self._next_ids()
            fee = self._apply_fill(row["symbol"], side, row["qty"], touch)
            row["status"] = "TRIGGERED"
            row["filled"] = row["qty"]
            row["triggered_id"] = order_id
            trig_order = {"symbol": row["symbol"], "side": side,
                          "kind": "MARKET", "qty": row["qty"],
                          "client_id": row["client_id"],
                          "order_id": order_id, "status": "FILLED",
                          "filled": row["qty"], "avg": touch}
            self._record_trade(trig_order, row["qty"], touch, fee,
                               trade_id)
            self.stream_queue.append({
                "e": "ALGO_UPDATE", "E": self.now_ms(), LABEL_KEY: True,
                "o": {"s": row["symbol"], "c": row["client_id"],
                      "S": side, "X": "TRIGGERED", "x": "TRIGGERED",
                      "i": int(aid), "ti": order_id}})
            self.stream_queue.append(self._stream_envelope(
                trig_order, "TRADE", row["qty"], touch, fee, trade_id))

    # -- account / funding ---------------------------------------------------------
    def account_view(self) -> dict[str, Any]:
        positions = []
        for symbol, pos in self.positions.items():
            if pos["qty"] == 0.0:
                continue
            mark = self.mid(symbol)
            positions.append({
                "symbol": symbol, "positionAmt": f"{pos['qty']:.8f}",
                "entryPrice": f"{pos['entry']:.2f}",
                "markPrice": f"{mark:.2f}", "positionSide": "BOTH",
                "isolated": False, "leverage": str(self.cfg.leverage)})
        margin_used = sum(
            abs(self.positions[s]["qty"]) * self.mid(s) / self.cfg.leverage
            for s in self.positions if self.positions[s]["qty"] != 0.0)
        return {"totalWalletBalance": f"{self.wallet:.8f}",
                "availableBalance": f"{self.wallet - margin_used:.8f}",
                "totalMarginBalance": f"{self.wallet:.8f}",
                "totalInitialMargin": f"{margin_used:.8f}",
                "positions": positions, LABEL_KEY: True}

    def _poll_funding(self) -> None:
        now = self.now_ms()
        day_start = (now // 86_400_000) * 86_400_000
        for boundary in FUNDING_DAY_MS:
            funding_ms = day_start + boundary
            if funding_ms <= self._funding_cursor_ms or funding_ms > now:
                continue
            self._funding_cursor_ms = funding_ms
            for symbol, pos in self.positions.items():
                if pos["qty"] == 0.0:
                    continue
                rate = SYMBOLS[symbol]["funding_8h"]
                amount = -pos["qty"] * pos["entry"] * rate
                self.wallet += amount
                self.funding_rows.append({
                    "symbol": symbol, "incomeType": "FUNDING_FEE",
                    "income": f"{amount:.8f}", "time": funding_ms})

    def income_view(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        symbol = str(params.get("symbol", "")).upper()
        rows = [r for r in self.funding_rows
                if r["symbol"] == symbol
                and r["incomeType"] == params.get("incomeType",
                                                  "FUNDING_FEE")]
        return copy.deepcopy(rows[-int(params.get("limit", 1000)):])

    # -- listenKey -------------------------------------------------------------------
    def open_listen_key(self) -> dict[str, Any]:
        self.listen_key = f"sandbox-{uuid.UUID(int=self.rng.getrandbits(128))}"
        self.key_deadline_ms = self.now_ms() + 3_600_000
        return {"listenKey": self.listen_key, LABEL_KEY: True}

    def keepalive_listen_key(self) -> dict[str, Any]:
        if self.listen_key is None:
            raise VenueHttpError(400, -2013, "sandbox: no listenKey")
        self.key_deadline_ms = self.now_ms() + 3_600_000
        return {LABEL_KEY: True}

    def close_listen_key(self) -> dict[str, Any]:
        self.listen_key = None
        return {LABEL_KEY: True}

    # -- stream ------------------------------------------------------------------------
    def poll_stream(self) -> dict[str, Any] | None:
        """Next user-stream envelope with scripted reorder/dupe applied."""
        if self._stream_die_armed:
            self._stream_die_armed = False
            raise ConnectionError("sandbox: socket died (scripted)")
        if not self.stream_queue:
            return None
        fault = self._fault_for("stream")
        if fault is not None and fault["action"] == "reorder" \
                and len(self.stream_queue) >= 2:
            self.stream_queue[0], self.stream_queue[1] = \
                self.stream_queue[1], self.stream_queue[0]
        env = self.stream_queue.pop(0)
        if fault is not None and fault["action"] == "dupe":
            self.stream_queue.insert(0, copy.deepcopy(env))
        return copy.deepcopy(env)

    # -- snapshots ----------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {"orders": copy.deepcopy(self.orders),
                "by_client": dict(self.by_client),
                "algos": copy.deepcopy(self.algos),
                "algo_by_client": dict(self.algo_by_client),
                "trades": copy.deepcopy(self.trades),
                "positions": copy.deepcopy(self.positions),
                "wallet": self.wallet, "realized": self.realized,
                "fees_paid": self.fees_paid,
                "funding_rows": copy.deepcopy(self.funding_rows),
                "funding_cursor_ms": self._funding_cursor_ms,
                "listen_key": self.listen_key,
                "key_deadline_ms": self.key_deadline_ms,
                "stream_queue": copy.deepcopy(self.stream_queue),
                "order_seq": self._order_seq, "trade_seq": self._trade_seq,
                "algo_seq": self._algo_seq,
                "rng_state": self.rng.getstate(),
                "walk_cache": {str(k): v
                               for k, v in self._walk_cache.items()},
                "request_no": self.request_no,
                LABEL_KEY: True}

    def restore(self, snap: dict[str, Any]) -> None:
        self.orders = copy.deepcopy(snap["orders"])
        self.by_client = dict(snap["by_client"])
        self.algos = copy.deepcopy(snap["algos"])
        self.algo_by_client = dict(snap["algo_by_client"])
        self.trades = copy.deepcopy(snap["trades"])
        self.positions = copy.deepcopy(snap["positions"])
        self.wallet = snap["wallet"]
        self.realized = snap["realized"]
        self.fees_paid = snap["fees_paid"]
        self.funding_rows = copy.deepcopy(snap["funding_rows"])
        self._funding_cursor_ms = snap["funding_cursor_ms"]
        self.listen_key = snap["listen_key"]
        self.key_deadline_ms = snap["key_deadline_ms"]
        self.stream_queue = copy.deepcopy(snap["stream_queue"])
        self._order_seq = snap["order_seq"]
        self._trade_seq = snap["trade_seq"]
        self._algo_seq = snap["algo_seq"]
        _v, _inner, _g = snap["rng_state"]
        self.rng.setstate((_v, tuple(_inner), _g))
        self._walk_cache = {int(k): v
                            for k, v in snap["walk_cache"].items()}
        self.request_no = snap["request_no"]

    def save(self, path: str | Path) -> None:
        # rng state holds tuples; JSON round-trips them as lists.
        Path(path).write_text(json.dumps(self.snapshot(), default=list),
                              encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path,
             config: SandboxConfig | None = None) -> "SandboxVenue":
        venue = cls(config)
        venue.restore(json.loads(Path(path).read_text(encoding="utf-8")))
        return venue


class SandboxTransport:
    """LiveTransport over a SandboxVenue (offline, no network).

    Routes the engine's REST dialogue to venue handlers, polling
    algos/funding on every request (venue time advances with traffic).
    Unknown paths fail loudly (never silently OK).
    """

    def __init__(self, venue: SandboxVenue) -> None:
        self.venue = venue
        self.requests: list[tuple[str, str, dict]] = []

    def request(self, method: str, path: str, params: dict[str, Any],
                headers: dict[str, str]) -> Any:
        venue = self.venue
        venue.request_no += 1
        venue.log.append({"n": venue.request_no, "method": method,
                          "path": path, "params": dict(params)})
        self.requests.append((method, path, dict(params)))
        venue._poll_algos()
        venue._poll_funding()
        op = path.rsplit("/", 1)[-1]
        venue._maybe_request_fault(op)
        venue._maybe_request_fault(f"{method}:{op}")
        handler = (method, path)
        if handler == ("GET", "/fapi/v1/time"):
            return {"serverTime": venue.now_ms(), LABEL_KEY: True}
        if handler == ("GET", "/fapi/v1/exchangeInfo"):
            return {"symbols": [
                {"symbol": sym,
                 "pricePrecision": 2, "quantityPrecision": 3,
                 "filters": [
                     {"filterType": "PRICE_FILTER",
                      "tickSize": str(spec["tick"])},
                     {"filterType": "LOT_SIZE",
                      "stepSize": str(spec["step"]),
                      "minQty": str(spec["min_qty"]),
                      "maxQty": "1000"},
                     {"filterType": "MARKET_LOT_SIZE",
                      "minQty": str(spec["min_qty"]),
                      "maxQty": "500"},
                     {"filterType": "MIN_NOTIONAL",
                      "notional": str(spec["min_notional"])}]}
                for sym, spec in SYMBOLS.items()], LABEL_KEY: True}
        if handler == ("GET", "/fapi/v1/commissionRate"):
            spec = SYMBOLS[str(params["symbol"]).upper()]
            return {"symbol": str(params["symbol"]).upper(),
                    "makerCommissionRate": str(spec["taker_bps"] / 10000.0),
                    "takerCommissionRate": str(spec["taker_bps"] / 10000.0),
                    LABEL_KEY: True}
        if handler == ("GET", "/fapi/v1/leverageBracket"):
            sym = str(params.get("symbol", "")).upper() or "ETHUSDT"
            return [{"symbol": sym, "brackets": [
                {"bracket": 1, "notionalCap": "50000",
                 "maintMarginRatio": "0.004", "cum": "0"},
                {"bracket": 2, "notionalCap": "250000",
                 "maintMarginRatio": "0.005", "cum": "50"}]},
                {LABEL_KEY: True}]
        if handler == ("GET", "/fapi/v2/positionRisk"):
            sym = str(params.get("symbol", "")).upper() or "ETHUSDT"
            return [{"symbol": sym, "leverage": venue.cfg.leverage,
                     LABEL_KEY: True}]
        if handler == ("GET", "/fapi/v2/account"):
            return venue.account_view()
        if handler == ("POST", "/fapi/v1/leverage"):
            return {"symbol": str(params["symbol"]).upper(),
                    "leverage": venue.cfg.leverage, LABEL_KEY: True}
        if handler == ("POST", "/fapi/v1/order"):
            return venue.place_order(params)
        if handler == ("GET", "/fapi/v1/order"):
            return venue.query_order(params)
        if handler == ("DELETE", "/fapi/v1/order"):
            return venue.cancel_order(params)
        if handler == ("POST", "/fapi/v1/algoOrder"):
            return venue.place_algo(params)
        if handler == ("GET", "/fapi/v1/algoOrder"):
            return venue.query_algo(params)
        if handler == ("DELETE", "/fapi/v1/algoOrder"):
            return venue.cancel_algo(params)
        if handler == ("GET", "/fapi/v1/openOrders"):
            return venue.open_orders()
        if handler == ("GET", "/fapi/v1/openAlgoOrders"):
            return venue.open_algo_orders()
        if handler == ("GET", "/fapi/v1/userTrades"):
            return venue.user_trades(params)
        if handler == ("GET", "/fapi/v1/income"):
            return venue.income_view(params)
        if handler == ("POST", "/fapi/v1/listenKey"):
            return venue.open_listen_key()
        if handler == ("PUT", "/fapi/v1/listenKey"):
            return venue.keepalive_listen_key()
        if handler == ("DELETE", "/fapi/v1/listenKey"):
            return venue.close_listen_key()
        if handler == ("GET", "/fapi/v1/ticker/bookTicker"):
            book = venue.book(str(params["symbol"]).upper())
            return {"symbol": str(params["symbol"]).upper(),
                    "bidPrice": f"{book['bid']:.2f}",
                    "askPrice": f"{book['ask']:.2f}",
                    "time": book["ts_ms"], LABEL_KEY: True}
        raise VenueHttpError(404, -2013 - 99,
                             f"sandbox: unhandled {method} {path}")


class SandboxSocket:
    """StreamSocket over the venue queue (offline user stream)."""

    def __init__(self, venue: SandboxVenue) -> None:
        self.venue = venue
        self.closed = False

    def recv(self, timeout_s: float) -> dict[str, Any] | None:
        if self.closed:
            raise ConnectionError("sandbox: socket closed")
        try:
            return self.venue.poll_stream()
        except ConnectionError:
            self.closed = True
            raise

    def close(self) -> None:
        self.closed = True


__all__ = ["LABEL_KEY", "SYMBOLS", "SandboxConfig", "SandboxSocket",
           "SandboxTransport", "SandboxVenue", "FaultScript"]
