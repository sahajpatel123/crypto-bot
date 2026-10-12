"""Binance USD-M live execution adapter (V-008 §7). DISABLED BY DEFAULT.

Construction requires explicit ``live_enable=True`` plus API credentials;
without both it raises and no request is ever sent. The paper path never
instantiates this class (R0-style test pins that).

Contract status: request/response shapes follow the field names this repo
already parses from live exchangeInfo (``market_data.discovery``) and the
USD-M futures REST/user-stream surface. Recorded fixtures under
``tests/fixtures/binance_live/`` are hand-built to those shapes (labeled
``recorded-shape``), NOT actual captures — re-record against testnet
before any demo. No production keys in messages/fixtures/commits, ever.

Safety rules (tested, no exceptions):
- Unknown submission outcomes (timeout, 502/503/504 — Binance documents
  503 as UNKNOWN execution status) journal the client id as UNKNOWN and
  raise; any further submit for the same reservation is REFUSED until
  ``lookup()`` resolves the unknown (retry must never add exposure
  blindly). Deterministic rejections (other 4xx/5xx) journal REJECTED
  and allow retry — nothing executed.
- Independent conditional legs only (STOP_MARKET / TAKE_PROFIT_MARKET,
  reduce-only); no OCO/bracket assumption — Futures has no native
  spot-style OCO.
- Quantities floor and prices tick-round with the ONE shared rule
  (``risk.rounding``), identical to sim submission.
- Fees must settle in USDT; any other commission asset fails loudly.
- The user-data-stream SOCKET is integration scope (manager/CLI); this
  module owns listenKey lifecycle + user-event parsing via
  ``note_user_event`` (transport-agnostic).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from cryptobot.app.engine import (
    EngineEvent,
    EngineFill,
    EngineOrder,
    EngineOrderStatus,
)
from cryptobot.risk.rounding import floor_to_step, round_to_tick

TESTNET_BASE_URL = "https://testnet.binancefuture.com"
UNKNOWN_HTTP_STATUSES = (0, 502, 503, 504)  # timeout + gateways: outcome unknown.

__all__ = [
    "BinanceLiveEngine",
    "UrllibTransport",
    "VenueHttpError",
    "VenueRejectedError",
    "UnknownOutcomeError",
]


class VenueHttpError(Exception):
    """Transport/HTTP failure. ``status`` 0 = timeout/socket error."""

    def __init__(self, status: int, code: int | None, msg: str) -> None:
        super().__init__(f"venue http {status} code={code}: {msg}")
        self.status = status
        self.code = code
        self.msg = msg


class VenueRejectedError(VenueHttpError):
    """Deterministic rejection: the venue did NOT execute (retry allowed)."""


class UnknownOutcomeError(Exception):
    """Submission outcome unknown (timeout/502/503/504). Lookup first.

    Carries the journaled ``client_id``; ``lookup(client_id)`` resolves it.
    """

    def __init__(self, client_id: str, reason: str) -> None:
        super().__init__(f"unknown outcome for {client_id}: {reason}")
        self.client_id = client_id
        self.reason = reason


class LiveTransport(Protocol):
    """Synchronous JSON transport (urllib prod / replay test)."""

    def request(self, method: str, path: str, params: dict[str, Any],
                headers: dict[str, str]) -> Any:
        """Send one request; return parsed JSON. Raise VenueHttpError."""
        ...


class UrllibTransport:
    """Stdlib HTTPS transport (no third-party deps)."""

    def __init__(self, base_url: str, timeout_s: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    def request(self, method: str, path: str, params: dict[str, Any],
                headers: dict[str, str]) -> Any:
        body = urllib.parse.urlencode(params or {}).encode("utf-8")
        url = self._base + path
        if method == "GET" and body:
            url += "?" + body.decode("utf-8")
            body = b""
        req = urllib.request.Request(  # noqa: S310 (explicit https venue call)
            url, data=body if method != "GET" else None, headers=headers,
            method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {}
            raise VenueHttpError(
                exc.code, payload.get("code"), str(payload.get("msg", exc))) from None
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise VenueHttpError(0, None, f"transport: {exc}") from None


def _side_venue(side: str) -> str:
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    return side


def _local_state(venue_status: str) -> str:
    return {"NEW": "open", "PARTIALLY_FILLED": "partial", "FILLED": "filled",
            "CANCELED": "cancelled", "CANCELLED": "cancelled",
            "REJECTED": "rejected", "EXPIRED": "expired",
            }.get(venue_status, f"unknown:{venue_status}")


class BinanceLiveEngine:
    """USD-M live execution behind explicit opt-in (see module docstring)."""

    model_label = "binance-usdm-live"
    assumptions = (
        "DISABLED by default: live_enable=True + api credentials required.",
        "testnet base URL by default; production needs an explicit base_url.",
        "independent conditional legs, no OCO; reduce-only exits.",
        "unknown outcomes (timeout/502/503/504) block retry until lookup.",
        "fees must settle in USDT; other commission assets fail loudly.",
        "user-stream socket is integration scope (manager/CLI).",
    )

    def __init__(
        self, *,
        api_key: str,
        api_secret: str,
        journal_path: str | Path,
        expected_leverage: int,
        run_tag: str = "bl",
        live_enable: bool = False,
        base_url: str = TESTNET_BASE_URL,
        recv_window_ms: int = 5000,
        expected_margin_type: str = "CROSS",
        stop_working_type: str = "CONTRACT_PRICE",
        open_orders_ttl_s: float = 1.0,
        transport: LiveTransport | None = None,
        now_utc: Callable[[], datetime] | None = None,
    ) -> None:
        if not live_enable:
            raise ValueError("live trading is disabled: pass live_enable=True "
                             "explicitly (default-off)")
        if not api_key or not api_secret:
            raise ValueError("live trading needs api_key + api_secret")
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self._journal_path = Path(journal_path)
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._journal_path, "a", encoding="utf-8"):
            pass  # fail fast when the journal is not writable.
        self._leverage = int(expected_leverage)
        self._margin_type = expected_margin_type
        self._run_tag = run_tag
        self._recv_window = int(recv_window_ms)
        self._working_type = stop_working_type
        self._orders_ttl = float(open_orders_ttl_s)
        self._transport = transport or UrllibTransport(base_url)
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self._now_ms = lambda: int(self._now_utc().timestamp() * 1000)
        self._offset_ms = 0
        self._ready = False
        self._closed = False
        self._exit_only = False
        self._seq = 0
        self._filters: dict[str, dict[str, float]] = {}
        self._fee_bps: dict[str, float] = {}
        self._roles: dict[str, str] = {}
        self._reservations: dict[str, str | None] = {}
        self._states: dict[str, str] = {}  # client id -> local state/UNKNOWN.
        self._trades_booked: set[str] = set()  # venue trade ids adopted.
        self._pending: list[EngineEvent] = []
        self._marks: dict[str, float] = {}
        self._mark_ts: dict[str, datetime] = {}
        self._orders_cache: tuple[float, list[EngineOrderStatus]] | None = None
        self._listen_key: str | None = None
        self._journal("live-enabled", {"base_url": base_url,
                                       "run_tag": run_tag,
                                       "recv_window_ms": self._recv_window})

    # -- journal (persist-before-side-effect) --------------------------------
    def _journal(self, event: str, payload: dict[str, Any]) -> None:
        record = {"ts_utc": self._now_utc().isoformat(), "event": event,
                  **payload}
        with open(self._journal_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # -- signing --------------------------------------------------------------
    def _signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        body = dict(params)
        body["timestamp"] = self._now_ms() + self._offset_ms
        body["recvWindow"] = self._recv_window
        query = urllib.parse.urlencode(body)
        body["signature"] = hmac.new(
            self._secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        return body

    def _public(self, method: str, path: str,
                params: dict[str, Any] | None = None) -> Any:
        return self._transport.request(method, path, dict(params or {}), {})

    def _signed(self, method: str, path: str,
                params: dict[str, Any] | None = None) -> Any:
        try:
            return self._transport.request(
                method, path, self._signed_params(dict(params or {})),
                {"X-MBX-APIKEY": self._key})
        except VenueHttpError as exc:
            if exc.status in UNKNOWN_HTTP_STATUSES:
                raise
            raise VenueRejectedError(exc.status, exc.code, exc.msg) from None

    # -- readiness (time sync, filters, fees, margin mode, leverage) -----------
    def _ensure_ready(self, symbol: str) -> None:
        if self._ready and symbol in self._filters:
            return
        server_ms = int(self._public("GET", "/fapi/v1/time")["serverTime"])
        self._offset_ms = server_ms - self._now_ms()
        if abs(self._offset_ms) > self._recv_window:
            raise VenueRejectedError(0, None,
                                     f"clock skew {self._offset_ms}ms exceeds "
                                     f"recvWindow {self._recv_window}ms")
        info = self._public("GET", "/fapi/v1/exchangeInfo")
        for entry in info.get("symbols", []):
            if str(entry.get("symbol", "")).upper() != symbol:
                continue
            by_type = {f["filterType"]: f for f in entry.get("filters", [])}
            lot = by_type.get("LOT_SIZE", {})
            mlot = by_type.get("MARKET_LOT_SIZE", {})
            self._filters[symbol] = {
                "tick": float(by_type["PRICE_FILTER"]["tickSize"]),
                "step": float(lot["stepSize"]),
                "min_qty": max(float(lot.get("minQty", 0.0)),
                               float(mlot.get("minQty", 0.0))),
                "min_notional": float(by_type.get(
                    "MIN_NOTIONAL", {}).get("notional", 0.0)),
            }
        if symbol not in self._filters:
            raise VenueRejectedError(0, None,
                                     f"venue publishes no filters for {symbol}")
        fees = self._signed("GET", "/fapi/v1/commissionRate",
                            {"symbol": symbol})
        self._fee_bps[symbol] = float(fees["takerCommissionRate"]) * 10000.0
        account = self._signed("GET", "/fapi/v2/account")
        if account.get("dualSidePosition") is True:
            raise VenueRejectedError(0, None, "hedge mode not supported: "
                                     "one-way position mode required")
        for pos in account.get("positions", []):
            if str(pos.get("symbol", "")).upper() != symbol:
                continue
            if str(pos.get("marginType", "")).upper() != self._margin_type:
                raise VenueRejectedError(
                    0, None, f"{symbol} marginType "
                    f"{pos.get('marginType')} != expected {self._margin_type}")
        actual = int(self._signed("POST", "/fapi/v1/leverage",
                                  {"symbol": symbol,
                                   "leverage": self._leverage})["leverage"])
        if actual != self._leverage:
            raise VenueRejectedError(0, None, f"leverage {actual} != "
                                     f"expected {self._leverage}")
        self._ready = True
        self._journal("ready", {"symbol": symbol, "offset_ms": self._offset_ms,
                                "filters": self._filters[symbol],
                                "taker_bps": self._fee_bps[symbol]})

    # -- submission -------------------------------------------------------------
    def _new_client_id(self) -> str:
        self._seq += 1
        rand = f"{random.getrandbits(16):04x}"
        return f"{self._run_tag}-{self._seq:06d}-{rand}"

    def _unknown_for(self, reservation_id: str | None) -> list[str]:
        if reservation_id is None:
            return []
        return [cid for cid, res in self._reservations.items()
                if res == reservation_id and self._states.get(cid) == "UNKNOWN"]

    def submit(self, cmd: EngineOrder) -> str:
        """Submit one order; returns the journaled client id.

        Raises UnknownOutcomeError (timeout/502/503/504) with the order
        journaled UNKNOWN — lookup() must resolve it before any further
        submit for the same reservation. Raises VenueRejectedError on
        deterministic venue rejection (retry allowed).
        """
        if self._closed:
            raise RuntimeError("engine is closed")
        if self._exit_only and cmd.role == "entry":
            raise ValueError("exit-only: entries refused")
        self._ensure_ready(cmd.instrument.upper())
        blocked = self._unknown_for(cmd.reservation_id)
        if blocked:
            raise UnknownOutcomeError(
                blocked[0], "lookup must resolve the unknown outcome "
                            "before new exposure")
        return self._submit_order(cmd, price_override=None)

    def submit_immediate(self, cmd: EngineOrder) -> str:
        """No delay model on live; exits-only guard still enforced."""
        if cmd.role == "entry":
            raise ValueError("submit_immediate is exits-only; entries use submit()")
        return self.submit(cmd)

    def submit_protected(self, cmd: EngineOrder, limit_price: float) -> str:
        """Price-protected marketable IOC entry (LIMIT IOC at the cap)."""
        if self._exit_only and cmd.role == "entry":
            raise ValueError("exit-only: entries refused")
        self._ensure_ready(cmd.instrument.upper())
        blocked = self._unknown_for(cmd.reservation_id)
        if blocked:
            raise UnknownOutcomeError(
                blocked[0], "lookup must resolve the unknown outcome "
                            "before new exposure")
        return self._submit_order(cmd, price_override=("LIMIT", limit_price))

    def _submit_order(self, cmd: EngineOrder,
                      price_override: tuple[str, float] | None) -> str:
        symbol = cmd.instrument.upper()
        filt = self._filters[symbol]
        qty = floor_to_step(cmd.qty, filt["step"])
        if qty <= 0:
            raise ValueError(f"qty {cmd.qty} below LOT_SIZE step "
                             f"{filt['step']} for {symbol}")
        if qty < filt["min_qty"]:
            raise ValueError(f"qty {qty} below venue minQty for {symbol}")
        kind, price = cmd.kind.upper(), cmd.price
        if price_override is not None:
            kind, price = price_override
        if kind == "LIMIT" and price is None:
            raise ValueError("LIMIT submit needs price")
        if kind in ("STOP_MARKET", "TAKE_PROFIT_MARKET") and cmd.stop_price is None:
            raise ValueError(f"{kind} submit needs stop_price")
        if kind not in ("MARKET", "LIMIT", "STOP_MARKET", "TAKE_PROFIT_MARKET"):
            raise ValueError(f"unsupported order kind {cmd.kind!r}")
        reduce_only = cmd.reduce_only or cmd.role in ("stop", "target")
        if cmd.role in ("stop", "target") and not reduce_only:
            raise AssertionError("unreachable: exits are always reduce-only")
        params: dict[str, Any] = {
            "symbol": symbol, "side": _side_venue(cmd.side), "type": kind,
            "quantity": repr(qty),
            "newClientOrderId": self._new_client_id(),
        }
        if kind == "LIMIT":
            assert price is not None
            params["price"] = repr(round_to_tick(price, filt["tick"]))
            params["timeInForce"] = "IOC"
        if kind in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            assert cmd.stop_price is not None
            params["stopPrice"] = repr(round_to_tick(cmd.stop_price, filt["tick"]))
            params["workingType"] = self._working_type
        if reduce_only:
            params["reduceOnly"] = "true"
        cid = params["newClientOrderId"]
        self._journal("submit-intent", {"client_id": cid, "symbol": symbol,
                                        "side": cmd.side, "kind": kind,
                                        "qty": qty, "params": params,
                                        "role": cmd.role,
                                        "reservation_id": cmd.reservation_id})
        self._roles[cid] = cmd.role
        self._reservations[cid] = cmd.reservation_id
        try:
            view = self._signed("POST", "/fapi/v1/order", params)
        except VenueHttpError as exc:
            if exc.status in UNKNOWN_HTTP_STATUSES:
                self._states[cid] = "UNKNOWN"
                self._journal("submit-outcome-unknown",
                              {"client_id": cid, "reason": str(exc)})
                raise UnknownOutcomeError(cid, str(exc)) from None
            raise
        self._states[cid] = _local_state(str(view.get("status", "NEW")))
        self._journal("submitted", {"client_id": cid,
                                    "order_id": view.get("orderId"),
                                    "state": self._states[cid]})
        self._orders_cache = None
        return cid

    # -- lookup / reconcile -------------------------------------------------------
    def lookup(self, client_id: str) -> EngineOrderStatus | None:
        """Resolve one order's venue truth (unknown-outcome lookup).

        Returns None when the venue never saw the id (order voided);
        otherwise adopts status + cumulative fills and queues delta
        EngineFill events for poll().
        """
        symbol = self._symbol_of(client_id)
        try:
            view = self._signed("GET", "/fapi/v1/order",
                                {"symbol": symbol,
                                 "origClientOrderId": client_id})
        except VenueRejectedError as exc:
            if exc.code == -2013:  # unknown order: the venue never saw it.
                self._states[client_id] = "void"
                self._journal("lookup-void", {"client_id": client_id})
                return None
            raise
        state = _local_state(str(view.get("status", "")))
        self._states[client_id] = state
        exec_qty = float(view.get("executedQty", 0.0) or 0.0)
        self._adopt_user_trades(client_id, symbol, view.get("orderId"),
                                exec_qty)
        self._journal("lookup", {"client_id": client_id, "state": state,
                                 "executed_qty": exec_qty})
        self._orders_cache = None
        return EngineOrderStatus(
            client_order_id=client_id, instrument=symbol, state=state,
            qty=float(view.get("origQty", 0.0) or 0.0), filled_qty=exec_qty,
            reservation_id=self._reservations.get(client_id),
            role=self._roles.get(client_id, "entry"))

    def unknown_ids(self) -> tuple[str, ...]:
        """Journaled UNKNOWN client ids (integration must lookup each)."""
        return tuple(cid for cid, st in self._states.items() if st == "UNKNOWN")

    def _adopt_user_trades(self, client_id: str, symbol: str, order_id: Any,
                           exec_qty: float) -> None:
        """Adopt per-trade fills with exact venue commissions.

        The order query carries no per-fill fees, so fills come from the
        userTrades tape (deduped by venue trade id — the user stream may
        report the same trade first). Any cumulative-vs-tape difference
        is journaled loudly and resolves on a later lookup; fees are
        never estimated.
        """
        if order_id is None or exec_qty <= 0:
            return
        trades = self._signed("GET", "/fapi/v1/userTrades",
                              {"symbol": symbol, "orderId": order_id})
        booked = 0.0
        for trade in trades:
            tid = str(trade.get("id", ""))
            qty = float(trade.get("qty", 0.0) or 0.0)
            booked += qty
            if tid and tid in self._trades_booked:
                continue
            if tid:
                self._trades_booked.add(tid)
            asset = str(trade.get("commissionAsset", "USDT"))
            if asset != "USDT":
                raise ValueError(
                    f"non-USDT commission {asset} on trade {tid}: "
                    f"multi-asset fees need explicit support")
            now = self._now_utc()
            self._pending.append(EngineEvent(
                "fill",
                EngineFill(execution_id=f"live:{tid or client_id}:{qty:.12f}",
                           client_order_id=client_id, instrument=symbol,
                           side=self._venue_side_of(client_id),
                           qty=qty, price=float(trade.get("price", 0.0)),
                           fee=float(trade.get("commission", 0.0)),
                           ts_utc=now, liquidity="taker"),
                now))
            self._journal("fill-adopted", {"client_id": client_id,
                                           "trade_id": tid, "qty": qty})
        if abs(booked - exec_qty) > 1e-9:
            self._journal("fills-unreconciled",
                          {"client_id": client_id, "executed_qty": exec_qty,
                           "tape_qty": booked})

    def _symbol_of(self, client_id: str) -> str:
        for record in self._read_journal():
            if record.get("client_id") == client_id and record.get("symbol"):
                return str(record["symbol"])
        raise KeyError(f"unknown client_id: {client_id!r} (not journaled)")

    def _read_journal(self) -> list[dict[str, Any]]:
        try:
            text = self._journal_path.read_text(encoding="utf-8")
        except OSError:
            return []
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def _venue_side_of(self, client_id: str) -> str:
        for record in reversed(self._read_journal()):
            if record.get("event") == "submit-intent" \
                    and record.get("client_id") == client_id:
                return str(record.get("side", "BUY"))
        return "BUY"

    # -- cancel / orders / poll ---------------------------------------------------
    def cancel(self, client_order_id: str, reason: str) -> None:
        if self._closed:
            raise RuntimeError("engine is closed")
        symbol = self._symbol_of(client_order_id)
        self._journal("cancel-request", {"client_id": client_order_id,
                                         "reason": reason})
        try:
            self._signed("DELETE", "/fapi/v1/order",
                         {"symbol": symbol,
                          "origClientOrderId": client_order_id})
        except VenueRejectedError as exc:
            if exc.code == -2013:  # already gone at the venue: adopt.
                self._states[client_order_id] = "void"
                self._journal("cancel-void", {"client_id": client_order_id})
                return
            raise
        self._states[client_order_id] = "cancelled"
        self._journal("cancel-acked", {"client_id": client_order_id})
        self._orders_cache = None

    def open_orders(self) -> list[EngineOrderStatus]:
        """Venue open orders, TTL-cached (hot Session path must not REST-spam)."""
        if self._closed:
            raise RuntimeError("engine is closed")
        now_s = self._now_utc().timestamp()
        if self._orders_cache is not None:
            cached_at, cached = self._orders_cache
            if now_s - cached_at < self._orders_ttl:
                return list(cached)
        views = self._signed("GET", "/fapi/v1/openOrders")
        out = [EngineOrderStatus(
            client_order_id=str(v.get("clientOrderId", "")),
            instrument=str(v.get("symbol", "")),
            state=_local_state(str(v.get("status", "NEW"))),
            qty=float(v.get("origQty", 0.0) or 0.0),
            filled_qty=float(v.get("executedQty", 0.0) or 0.0),
            reservation_id=self._reservations.get(str(v.get("clientOrderId", ""))),
            role=self._roles.get(str(v.get("clientOrderId", "")), "entry"))
            for v in views]
        self._orders_cache = (now_s, out)
        return list(out)

    def resolve(self, client_id: str) -> str | None:
        """Live ids are durable at submit; None only when never journaled."""
        try:
            self._symbol_of(client_id)
        except KeyError:
            return None
        return client_id

    def poll(self) -> list[EngineEvent]:
        """Drain user-stream-fed + lookup-adopted events (never blocks)."""
        due, self._pending = self._pending, []
        return due

    def filled_qty(self, client_order_id: str) -> float:
        """Tracked cumulative fills (user stream + lookups; 0.0 unknown)."""
        total = 0.0
        for record in self._read_journal():
            if record.get("event") == "fill-adopted" \
                    and record.get("client_id") == client_order_id:
                total += float(record.get("qty", 0.0))
        return total

    # -- user-data-stream events (socket owned by integration) ----------------------
    def note_user_event(self, payload: dict[str, Any]) -> None:
        """Parse one user-stream payload into fills/state (fail loudly)."""
        kind = payload.get("e")
        if kind == "ORDER_TRADE_UPDATE":
            self._note_order_trade(payload.get("o", {}), payload)
        elif kind == "ACCOUNT_UPDATE":
            self._journal("account-update", {"event_time": payload.get("E")})
        elif kind == "listenKeyExpired":
            self._listen_key = None
            self._journal("listen-key-expired", {})
        else:
            raise ValueError(f"unknown user-stream event: {kind!r}")

    def _note_order_trade(self, order: dict[str, Any], envelope: dict) -> None:
        for key in ("s", "c", "S", "X", "x"):
            if key not in order:
                raise ValueError(f"ORDER_TRADE_UPDATE missing {key!r}")
        cid = str(order["c"])
        self._states[cid] = _local_state(str(order["X"]))
        self._journal("user-order-state",
                      {"client_id": cid, "state": self._states[cid]})
        if str(order["x"]) != "TRADE":
            return
        last_qty = float(order.get("l", 0.0) or 0.0)
        if last_qty <= 0:
            return
        asset = str(order.get("N", "USDT"))
        if asset != "USDT":
            raise ValueError(
                f"non-USDT commission {asset} on {cid}: multi-asset fees "
                f"need explicit support")
        tid = str(order.get("t", ""))
        if tid and tid in self._trades_booked:
            return  # lookup() already adopted this trade.
        if tid:
            self._trades_booked.add(tid)
        ts = envelope.get("E")
        now = (datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
               if isinstance(ts, (int, float)) else self._now_utc())
        self._pending.append(EngineEvent(
            "fill",
            EngineFill(execution_id=f"live:{tid or cid}:{last_qty:.12f}",
                       client_order_id=cid, instrument=str(order["s"]),
                       side=str(order["S"]), qty=last_qty,
                       price=float(order.get("L", 0.0) or 0.0),
                       fee=float(order.get("n", 0.0) or 0.0),
                       ts_utc=now, liquidity="taker"),
            now))
        self._journal("fill-adopted", {"client_id": cid, "trade_id": tid,
                                       "qty": last_qty, "via": "user-stream"})

    # -- listenKey lifecycle ----------------------------------------------------------
    def open_listen_key(self) -> str:
        """Create a user-stream listenKey (the socket dials it elsewhere)."""
        self._listen_key = str(self._public("POST", "/fapi/v1/listenKey")
                               ["listenKey"])
        self._journal("listen-key-open", {})
        return self._listen_key

    def keepalive_listen_key(self) -> None:
        if self._listen_key is None:
            raise ValueError("no listen key open")
        self._public("PUT", "/fapi/v1/listenKey")
        self._journal("listen-key-keepalive", {})

    # -- marks / margin / funding (valuation + reconcile inputs) ------------------------
    def note_mark(self, instrument: str, price: float,
                  ts_utc: datetime | None = None) -> None:
        if price > 0:
            self._marks[instrument.upper()] = price
            self._mark_ts[instrument.upper()] = ts_utc or self._now_utc()

    def valuation_mark(self, instrument: str) -> float | None:
        return self._marks.get(instrument.upper())

    def valuation_mark_ts(self, instrument: str) -> datetime | None:
        return self._mark_ts.get(instrument.upper())

    def account_margin(self) -> tuple[float, float]:
        """(availableBalance, marginBalance − initialMargin) from the venue."""
        account = self._signed("GET", "/fapi/v2/account")
        available = float(account.get("availableBalance", 0.0) or 0.0)
        free = float(account.get("totalMarginBalance", 0.0) or 0.0) - float(
            account.get("totalInitialMargin", 0.0) or 0.0)
        return available, free

    def fee_bps(self, symbol: str) -> float:
        """Venue taker rate in bps (cached at readiness)."""
        return self._fee_bps[symbol.upper()]

    def venue_funding_total(self, symbol: str) -> float:
        """Sum of FUNDING_FEE income (live funding-reconcile input)."""
        rows = self._signed("GET", "/fapi/v1/income",
                            {"symbol": symbol.upper(),
                             "incomeType": "FUNDING_FEE", "limit": 1000})
        return sum(float(r.get("income", 0.0) or 0.0) for r in rows)

    # -- protection / lifecycle -----------------------------------------------------------
    def attach_protection(self, entry_client_id: str, stop_price: float,
                          target_price: float | None) -> list[str]:
        """Independent reduce-only legs sized to filled qty (verified individually).

        Returns [stop_id] or [stop_id, target_id] — STOP FIRST, always.
        """
        status = self.lookup(entry_client_id)
        if status is None:
            raise KeyError(f"entry {entry_client_id!r} unknown at venue")
        if status.filled_qty <= 1e-12:
            raise ValueError("protection attaches only to an entry with fills")
        symbol = status.instrument
        filt = self._filters.get(symbol, {})
        step = filt.get("step")
        if step is None:
            self._ensure_ready(symbol)
            step = self._filters[symbol]["step"]
        protect_qty = floor_to_step(min(status.filled_qty, status.qty), step)
        if protect_qty <= 0:
            raise ValueError(f"protect qty below LOT_SIZE step for {symbol}")
        side = "SELL" if self._venue_side_of(entry_client_id) == "BUY" else "BUY"
        legs = [self.submit(EngineOrder(
            instrument=symbol, side=side, qty=protect_qty,
            kind="STOP_MARKET", stop_price=stop_price, reduce_only=True,
            reservation_id=status.reservation_id, role="stop"))]
        if target_price is not None:
            legs.append(self.submit(EngineOrder(
                instrument=symbol, side=side, qty=protect_qty,
                kind="TAKE_PROFIT_MARKET", stop_price=target_price,
                reduce_only=True, reservation_id=status.reservation_id,
                role="target")))
        return legs

    def set_exit_only(self, halted: bool, reason: str = "") -> None:
        self._exit_only = halted
        self._journal("exit-only", {"halted": halted, "reason": reason})

    def bind_sink(self, outcome_sink: Any) -> None:
        self._journal("sink-bound", {})

    def recover(self, outcome_sink: Any) -> None:
        """Reconcile every journaled non-terminal order via lookup.

        Adopted fills queue as EngineEvents for poll() (the session
        drains them into risk/ledger through the normal path).
        """
        self.bind_sink(outcome_sink)
        seen: set[str] = set()
        for record in self._read_journal():
            if record.get("event") != "submit-intent":
                continue
            cid = str(record.get("client_id", ""))
            if not cid or cid in seen:
                continue
            seen.add(cid)
            if self._states.get(cid, "open") in (
                    "filled", "cancelled", "rejected", "expired", "void"):
                continue
            try:
                self.lookup(cid)
            except VenueHttpError as exc:
                if exc.status in UNKNOWN_HTTP_STATUSES:
                    self._states[cid] = "UNKNOWN"
                    self._journal("recover-unknown",
                                  {"client_id": cid, "reason": str(exc)})
                else:
                    raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._listen_key is not None:
            try:
                self._transport.request("DELETE", "/fapi/v1/listenKey", {}, {})
            except VenueHttpError as exc:
                self._journal("listen-key-close-failed",
                              {"reason": str(exc)})
            self._listen_key = None
        self._journal("closed", {})
