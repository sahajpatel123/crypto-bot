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
  and allow retry — nothing executed. See ``caller_action`` (W3-24H
  app/adapter error contract).
- Independent conditional legs only (STOP_MARKET / TAKE_PROFIT_MARKET,
  reduce-only); no OCO/bracket assumption — Futures has no native
  spot-style OCO. Conditionals ride /fapi/v1/algoOrder with
  algoType=CONDITIONAL (2025-12-09 cutover); legacy conditional posts
  get -4120 (never sent). Triggered fills ride the triggered order id.
- Quantities floor and prices tick-round with the ONE shared rule
  (``risk.rounding``), identical to sim submission.
- Fees must settle in USDT; any other commission asset fails loudly.
- Bot-orders-only scope: open_orders/recover see journaled ids only;
  foreign strays are journaled loudly and ignored.
- The user-data-stream SOCKET reader lives in
  ``adapters/user_stream.py`` (injected transport, gap watchdog,
  reconnect+heal); this module owns listenKey lifecycle (API-key
  header) + user-event parsing via ``note_user_event``
  (transport-agnostic) + reconnect healing via
  ``stream_reconnected``.
- Demo mode (demo=True) selects demo-fapi/demo-fstream (both probed
  answering /fapi/v1/time); testnet is the default otherwise. Either
  way live_enable + credentials stay mandatory.
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
    AccountPosition,
    AccountSnapshot,
    EngineCancel,
    EngineEvent,
    EngineExpire,
    EngineFill,
    EngineOrder,
    EngineOrderStatus,
    EngineReject,
)
from cryptobot.risk.rounding import floor_to_step, round_to_tick

TESTNET_BASE_URL = "https://testnet.binancefuture.com"
TESTNET_FSTREAM_URL = "wss://stream.binancefuture.com"  # testnet stream host.
DEMO_FAPI_URL = "https://demo-fapi.binance.com"  # REST (manager-probed).
DEMO_FSTREAM_URL = "wss://demo-fstream.binance.com"  # user-stream socket host.
PROD_FAPI_URL = "https://fapi.binance.com"  # real-money host: explicit only.
PROD_FSTREAM_URL = "wss://fstream.binance.com"  # prod stream host (fstream).
UNKNOWN_HTTP_STATUSES = (0, 502, 503, 504)  # timeout + gateways: outcome unknown.
RATE_LIMIT_HTTP_STATUSES = (429, 418)  # too many requests / IP ban.
RATE_LIMIT_VENUE_CODES = (-1003,)  # TOO_MANY_REQUESTS.
ALGO_ORDER_TYPES = ("STOP_MARKET", "TAKE_PROFIT_MARKET")
# Terminal seam states (contract v1 §2): an order observed here never
# leaves; transitions INTO this set emit exactly one terminal event.
TERMINAL_STATES = frozenset({"filled", "cancelled", "rejected", "expired"})

__all__ = [
    "ALGO_ORDER_TYPES",
    "DEMO_FAPI_URL",
    "DEMO_FSTREAM_URL",
    "PROD_FAPI_URL",
    "PROD_FSTREAM_URL",
    "TESTNET_BASE_URL",
    "TESTNET_FSTREAM_URL",
    "BinanceLiveEngine",
    "UrllibTransport",
    "RateLimitedError",
    "VenueHttpError",
    "VenueRejectedError",
    "UnknownOutcomeError",
    "caller_action",
]


# -- app/adapter error contract (W3-24H) -------------------------------------------
# UnknownOutcomeError  -> lookup_then_retry (an unknown may have executed;
#                         lookup() must resolve it before new exposure).
# VenueRejectedError   -> retry_safe (deterministic: nothing executed).
# VenueHttpError       -> retry_safe (a failed read has no side effects;
#                         submit-unknowns surface as UnknownOutcomeError).
# ValueError/RuntimeError -> abort (caller bug or closed engine; retrying
#                         the identical call fails identically).
def caller_action(exc: BaseException) -> str:
    """Map an adapter exception to the caller's required behavior."""
    if isinstance(exc, UnknownOutcomeError):
        return "lookup_then_retry"
    if isinstance(exc, VenueHttpError):
        return "retry_safe"
    return "abort"


class VenueHttpError(Exception):
    """Transport/HTTP failure. ``status`` 0 = timeout/socket error."""

    def __init__(self, status: int, code: int | None, msg: str) -> None:
        super().__init__(f"venue http {status} code={code}: {msg}")
        self.status = status
        self.code = code
        self.msg = msg


class VenueRejectedError(VenueHttpError):
    """Deterministic rejection: the venue did NOT execute (retry allowed)."""


class RateLimitedError(VenueRejectedError):
    """Rate limit hit (429/418/-1003): nothing executed, back off first.

    The adapter enforces a refuse-fast window (retry_after_s); submits
    and reads raise immediately inside it WITHOUT sending, while
    cancel/reduce calls still attempt (cancel capacity protected).
    caller_action -> retry_safe (retry only after the window).
    """

    def __init__(self, status: int, code: int | None, msg: str,
                 retry_after_s: float) -> None:
        super().__init__(status, code, msg)
        self.retry_after_s = float(retry_after_s)


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

    def _effective_timeout(self) -> float:
        """Configured timeout bounded by the remaining job budget."""
        import os
        import time

        raw = os.environ.get("CRYPTOBOT_DEADLINE_MONO")
        if raw is None:
            return self._timeout
        try:
            remaining = float(raw) - time.monotonic()
        except ValueError:
            return self._timeout
        return max(1.0, min(self._timeout, remaining))

    def request(self, method: str, path: str, params: dict[str, Any],
                headers: dict[str, str]) -> Any:
        timeout = self._effective_timeout()
        body = urllib.parse.urlencode(params or {}).encode("utf-8")
        url = self._base + path
        if method == "GET" and body:
            url += "?" + body.decode("utf-8")
            body = b""
        req = urllib.request.Request(  # noqa: S310 (explicit https venue call)
            url, data=body if method != "GET" else None, headers=headers,
            method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
            # Algo-order statuses (2025-12-09 cutover): WORKING rests,
            # TRIGGERED fired (fills land on the triggered order).
            "WORKING": "open", "TRIGGERED": "triggered",
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
        demo: bool = False,
        base_url: str | None = None,
        recv_window_ms: int = 5000,
        expected_isolated: bool = False,
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
        # W3-24H explicit demo mode: demo hosts unless the owner passes an
        # explicit base_url (testnet default otherwise). Both demo hosts
        # were probed answering /fapi/v1/time (manager); the in-config
        # choice lives here.
        self._demo = bool(demo)
        self._base_url = (base_url or
                          (DEMO_FAPI_URL if self._demo else TESTNET_BASE_URL))
        # Exact host separation: demo traffic can never target the
        # real-money host, and the real-money host is never a default.
        if self._demo and self._base_url.rstrip("/") == PROD_FAPI_URL:
            raise ValueError("demo=True forbids the production host "
                             f"{PROD_FAPI_URL}")
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        # W3-24H restart identity: venue/account/symbol/trade fill keys.
        # The account tag is a key fingerprint (safe to journal, not secret).
        # Contract v1 §3 namespace: binanceusdm/{account}/{SYMBOL}/{trade}.
        self._venue = "binanceusdm"
        self._account_tag = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]
        self._journal_path = Path(journal_path)
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._journal_path, "a", encoding="utf-8"):
            pass  # fail fast when the journal is not writable.
        self._leverage = int(expected_leverage)
        self._isolated = bool(expected_isolated)
        self._run_tag = run_tag
        self._recv_window = int(recv_window_ms)
        self._working_type = stop_working_type
        self._orders_ttl = float(open_orders_ttl_s)
        self._transport = transport or UrllibTransport(self._base_url)
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
        self._algo: set[str] = set()  # client ids on the algoOrder rail.
        self._triggered: dict[str, str] = {}  # algo cid -> triggered order id.
        self._trades_booked: set[str] = set()  # venue trade ids adopted.
        self._pending: list[EngineEvent] = []
        self._marks: dict[str, float] = {}
        self._mark_ts: dict[str, datetime] = {}
        self._orders_cache: tuple[float, list[EngineOrderStatus]] | None = None
        self._listen_key: str | None = None
        # Contract v1 tracked truth: per-order versions, submit-intent
        # qty/symbol cache, adopted fill qty, emitted terminals.
        self._versions: dict[str, int] = {}
        self._submitted_qty: dict[str, float] = {}
        self._symbols: dict[str, str] = {}
        self._adopted_qty: dict[str, float] = {}
        self._terminal_emitted: set[str] = set()
        self._event_handler: Any | None = None  # bind_sink push target.
        # Rate-limit refuse-fast window (epoch ms; 0 = clear). Submits +
        # reads raise inside it; cancels still attempt (capacity kept).
        self._rate_limited_until_ms: int = 0
        self._rate_limit_backoff_s: float = 60.0
        self._rebuild_from_journal()
        self._journal("live-enabled", {"base_url": self._base_url,
                                       "demo": self._demo,
                                       "run_tag": run_tag,
                                       "recv_window_ms": self._recv_window})

    @property
    def stream_host(self) -> str:
        """User-stream socket host for the integration (demo-aware)."""
        if self._demo and self._base_url == DEMO_FAPI_URL:
            return DEMO_FSTREAM_URL
        return self._base_url.replace("https://", "wss://").replace(
            "http://", "ws://") + "/stream"

    def _fill_exec_id(self, symbol: str, trade_id: str) -> str:
        """Cross-symbol fill key: venue/account/symbol/trade (W3-24H)."""
        return f"{self._venue}/{self._account_tag}/{symbol}/{trade_id}"

    # Order-transition journal events: each bumps the order's version
    # (contract v1 §2), so versions rebuild by counting at construction.
    _VERSIONED_EVENTS = frozenset({
        "submit-intent", "submitted", "submit-outcome-unknown",
        "submit-rejected", "lookup", "user-order-state", "fill-adopted",
        "algo-triggered", "cancel-acked", "cancel-unknown", "lookup-void",
        "cancel-void", "recover-unknown", "terminal-emitted",
    })

    def _rebuild_from_journal(self) -> None:
        """Rebuild reservation/role/order IDs + booked fills + UNKNOWNs.

        Runs at construction so a restarted process resumes with the
        same identities, versions, dedup set, and exposure blocks — no
        replayed fill, no lost unknown, no forgotten role.
        """
        for record in self._read_journal():
            if record.get("event") == "submit-intent" and record.get("client_id"):
                cid = str(record["client_id"])
                self._symbols[cid] = str(record.get("symbol", ""))
        for record in self._read_journal():
            event, cid = record.get("event"), record.get("client_id")
            if event == "submit-intent" and cid:
                cid = str(cid)
                self._roles[cid] = str(record.get("role", "entry"))
                res = record.get("reservation_id")
                self._reservations[cid] = str(res) if res else None
                try:
                    self._submitted_qty[cid] = float(record.get("qty", 0.0))
                except (TypeError, ValueError):
                    self._submitted_qty[cid] = 0.0
                if record.get("algo") or record.get("kind") in ALGO_ORDER_TYPES:
                    self._algo.add(cid)
                self._states.setdefault(cid, "open")
            elif event in ("submitted", "lookup", "user-order-state") and cid:
                state = record.get("state")
                if state:
                    self._states[str(cid)] = str(state)
            elif event in ("submit-outcome-unknown", "recover-unknown") and cid:
                self._states[str(cid)] = "UNKNOWN"
            elif event == "submit-rejected" and cid:
                self._states[str(cid)] = "rejected"
            elif event == "cancel-unknown" and cid:
                self._states[str(cid)] = "CANCEL_UNKNOWN"
            elif event == "algo-triggered" and cid:
                trig = record.get("triggered_id")
                if trig:
                    self._triggered[str(cid)] = str(trig)
            elif event == "lookup-void" and cid:
                self._states[str(cid)] = "void"
            elif event in ("cancel-acked",) and cid:
                self._states[str(cid)] = "cancelled"
            elif event == "fill-adopted" and cid:
                tid = str(record.get("trade_id", ""))
                symbol = (str(record.get("symbol", ""))
                          or self._symbols.get(str(cid), ""))
                if tid and symbol:
                    self._trades_booked.add(f"{symbol}/{tid}")
                try:
                    self._adopted_qty[str(cid)] = self._adopted_qty.get(
                        str(cid), 0.0) + float(record.get("qty", 0.0))
                except (TypeError, ValueError):
                    pass
            elif event == "terminal-emitted" and cid:
                self._terminal_emitted.add(str(cid))
            if event in self._VERSIONED_EVENTS and cid:
                cid = str(cid)
                self._versions[cid] = self._versions.get(cid, 0) + 1

    # -- journal (persist-before-side-effect) --------------------------------
    def _journal(self, event: str, payload: dict[str, Any]) -> None:
        record = {"ts_utc": self._now_utc().isoformat(), "event": event,
                  **payload}
        with open(self._journal_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _journal_transition(self, event: str, client_id: str,
                            payload: dict[str, Any]) -> None:
        """Journal one order transition + bump its version (contract v1)."""
        self._journal(event, {"client_id": client_id, **payload})
        self._versions[client_id] = self._versions.get(client_id, 0) + 1

    def _emit(self, event: EngineEvent) -> None:
        """Route one emission: push when bound, else queue for poll()."""
        if self._event_handler is not None:
            self._event_handler(event)
            return
        self._pending.append(event)

    @staticmethod
    def _seam_state(internal: str) -> str:
        """Internal tracked state -> contract seam state."""
        if internal in ("UNKNOWN", "CANCEL_UNKNOWN"):
            return "unknown"
        if internal == "void":
            # Terminal, zero-fill: the venue never saw the order and
            # nothing ever rested — the honest terminal equivalent.
            return "cancelled"
        if internal == "triggered":
            return "open"  # algo fired; fills land on the triggered order.
        if internal.startswith("unknown:"):
            return "unknown"
        return internal

    def _maybe_emit_terminal(self, client_id: str, symbol: str,
                             reason: str) -> None:
        """Emit one terminal event on first terminal observation."""
        if client_id in self._terminal_emitted:
            return
        state = self._seam_state(self._states.get(client_id, "open"))
        if state not in TERMINAL_STATES or state == "filled":
            return
        now = self._now_utc()
        if state == "cancelled":
            payload: Any = EngineCancel(client_order_id=client_id,
                                        instrument=symbol, reason=reason,
                                        ts_utc=now)
            kind = "cancel"
        elif state == "rejected":
            payload = EngineReject(client_order_id=client_id,
                                   instrument=symbol, reason=reason,
                                   ts_utc=now)
            kind = "reject"
        else:
            payload = EngineExpire(client_order_id=client_id,
                                   instrument=symbol, reason=reason,
                                   ts_utc=now)
            kind = "expire"
        self._terminal_emitted.add(client_id)
        self._journal_transition("terminal-emitted", client_id,
                                 {"kind": kind, "reason": reason})
        self._emit(EngineEvent(kind, payload, now))

    # -- rate-limit guard (refuse-fast window; cancels still attempt) ---------
    def _rate_limited(self) -> bool:
        return self._now_ms() < self._rate_limited_until_ms

    def _note_rate_limit(self, exc: VenueHttpError) -> RateLimitedError:
        backoff = self._rate_limit_backoff_s
        self._rate_limited_until_ms = self._now_ms() + int(backoff * 1000)
        self._journal("rate-limited",
                      {"status": exc.status, "code": exc.code,
                       "backoff_s": backoff})
        self._orders_cache = None
        return RateLimitedError(exc.status, exc.code, exc.msg, backoff)

    @staticmethod
    def _is_rate_limit(exc: VenueHttpError) -> bool:
        return exc.status in RATE_LIMIT_HTTP_STATUSES \
            or exc.code in RATE_LIMIT_VENUE_CODES

    def _guarded(self, op: str) -> None:
        """Refuse-fast for submits/reads inside the window (never cancels)."""
        if self._rate_limited():
            remaining = (self._rate_limited_until_ms - self._now_ms()) / 1000.0
            raise RateLimitedError(
                429, -1003,
                f"{op} refused: rate-limit window has "
                f"{remaining:.1f}s left (cancel/reduce still attempt)",
                max(0.0, remaining))

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
        try:
            return self._transport.request(method, path, dict(params or {}),
                                           {})
        except VenueHttpError as exc:
            if self._is_rate_limit(exc):
                raise self._note_rate_limit(exc) from None
            raise

    def _signed(self, method: str, path: str,
                params: dict[str, Any] | None = None) -> Any:
        try:
            return self._transport.request(
                method, path, self._signed_params(dict(params or {})),
                {"X-MBX-APIKEY": self._key})
        except VenueHttpError as exc:
            if self._is_rate_limit(exc):
                raise self._note_rate_limit(exc) from None
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
        # W3-24H: documented position fields only (isolated, positionSide).
        # One-way mode = every position carries positionSide BOTH.
        for pos in account.get("positions", []):
            if str(pos.get("positionSide", "BOTH")) != "BOTH":
                raise VenueRejectedError(0, None, "hedge mode not supported: "
                                         "one-way position mode required")
            if str(pos.get("symbol", "")).upper() != symbol:
                continue
            if bool(pos.get("isolated", False)) != self._isolated:
                raise VenueRejectedError(
                    0, None, f"{symbol} isolated "
                    f"{pos.get('isolated')} != expected {self._isolated}")
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
        # CANCEL_UNKNOWN blocks too: the order may or may not be live —
        # exposure is unknown until a lookup resolves it.
        return [cid for cid, res in self._reservations.items()
                if res == reservation_id
                and self._states.get(cid) in ("UNKNOWN", "CANCEL_UNKNOWN")]

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
        self._guarded("submit")
        # Refuse-before-network: a predetermined refusal never touches
        # the venue (also keeps the unknown block working pre-readiness).
        blocked = self._unknown_for(cmd.reservation_id)
        if blocked:
            raise UnknownOutcomeError(
                blocked[0], "lookup must resolve the unknown outcome "
                            "before new exposure")
        self._ensure_ready(cmd.instrument.upper())
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
        self._guarded("submit_protected")
        blocked = self._unknown_for(cmd.reservation_id)
        if blocked:
            raise UnknownOutcomeError(
                blocked[0], "lookup must resolve the unknown outcome "
                            "before new exposure")
        self._ensure_ready(cmd.instrument.upper())
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
        # W3-24H algoOrder cutover (2025-12-09): conditional types ride
        # /fapi/v1/algoOrder with algoType=CONDITIONAL; legacy posts to
        # /fapi/v1/order get -4120 STOP_ORDER_SWITCH_ALGO (never sent).
        is_algo = kind in ALGO_ORDER_TYPES
        cid = self._new_client_id()
        params: dict[str, Any] = {
            "symbol": symbol, "side": _side_venue(cmd.side), "type": kind,
            "quantity": repr(qty),
        }
        if is_algo:
            params["algoType"] = "CONDITIONAL"
            params["clientAlgoId"] = cid
        else:
            params["newClientOrderId"] = cid
        if kind == "LIMIT":
            assert price is not None
            params["price"] = repr(round_to_tick(price, filt["tick"]))
            params["timeInForce"] = "IOC"
        if is_algo:
            assert cmd.stop_price is not None
            params["stopPrice"] = repr(round_to_tick(cmd.stop_price, filt["tick"]))
            params["workingType"] = self._working_type
        if reduce_only:
            params["reduceOnly"] = "true"
        self._journal_transition("submit-intent", cid,
                                     {"symbol": symbol, "side": cmd.side,
                                      "kind": kind, "qty": qty,
                                      "params": params, "role": cmd.role,
                                      "algo": is_algo,
                                      "reservation_id": cmd.reservation_id})
        self._roles[cid] = cmd.role
        self._reservations[cid] = cmd.reservation_id
        self._symbols[cid] = symbol
        self._submitted_qty[cid] = qty
        if is_algo:
            self._algo.add(cid)
        path = "/fapi/v1/algoOrder" if is_algo else "/fapi/v1/order"
        try:
            view = self._signed("POST", path, params)
        except VenueHttpError as exc:
            if exc.status in UNKNOWN_HTTP_STATUSES:
                self._states[cid] = "UNKNOWN"
                self._journal_transition(
                    "submit-outcome-unknown", cid, {"reason": str(exc)})
                raise UnknownOutcomeError(cid, str(exc)) from None
            if isinstance(exc, VenueRejectedError):
                # Deterministic: nothing executed. Journal the terminal
                # truth and emit it; retry is allowed.
                self._states[cid] = "rejected"
                self._journal_transition(
                    "submit-rejected", cid,
                    {"status": exc.status, "code": exc.code,
                     "reason": exc.msg})
                self._maybe_emit_terminal(cid, symbol, exc.msg)
            raise
        if is_algo:
            self._states[cid] = _local_state(str(view.get("algoStatus", "WORKING")))
            self._journal_transition("submitted", cid,
                                     {"algo_id": view.get("algoId"),
                                      "state": self._states[cid]})
        else:
            self._states[cid] = _local_state(str(view.get("status", "NEW")))
            self._journal_transition("submitted", cid,
                                     {"order_id": view.get("orderId"),
                                      "state": self._states[cid]})
        self._orders_cache = None
        self._maybe_emit_terminal(cid, symbol, "submitted-terminal")
        return cid

    # -- lookup / reconcile -------------------------------------------------------
    def lookup(self, client_id: str) -> EngineOrderStatus | None:
        """Resolve one order's venue truth (unknown-outcome lookup).

        Algo ids query /fapi/v1/algoOrder (algoStatus + triggered id);
        vanilla ids query /fapi/v1/order. Adopts status + fills (fills
        ride the triggered order once an algo fires); adopted fills and
        first-terminal observations route through _emit(). Returns the
        tracked status, or None only when the venue never saw the id
        (order voided — surfaced as cancelled via order_status()).
        """
        self._guarded("lookup")
        symbol = self._symbol_of(client_id)
        is_algo = client_id in self._algo
        if is_algo:
            view = self._lookup_algo(client_id, symbol)
            if view is None:
                return None
            state = _local_state(str(view.get("algoStatus", "")))
            trig = view.get("triggeredOrderId")
            if trig:
                self._triggered[client_id] = str(trig)
                self._journal_transition("algo-triggered", client_id,
                                         {"triggered_id": str(trig)})
            trades_id = trig if trig else view.get("algoId")
        else:
            try:
                view = self._signed("GET", "/fapi/v1/order",
                                    {"symbol": symbol,
                                     "origClientOrderId": client_id})
            except VenueRejectedError as exc:
                if exc.code == -2013:  # unknown: the venue never saw it.
                    self._states[client_id] = "void"
                    self._journal_transition("lookup-void", client_id, {})
                    self._maybe_emit_terminal(client_id, symbol,
                                              "lookup-void:venue-never-saw")
                    return None
                raise
            state = _local_state(str(view.get("status", "")))
            trades_id = view.get("orderId")
        self._states[client_id] = state
        exec_qty = float(view.get("executedQty", 0.0) or 0.0)
        self._adopt_user_trades(client_id, symbol, trades_id, exec_qty)
        self._journal_transition("lookup", client_id,
                                 {"state": state, "executed_qty": exec_qty})
        self._orders_cache = None
        self._maybe_emit_terminal(client_id, symbol, "lookup-terminal")
        return self.order_status(client_id)

    def order_status(self, client_order_id: str) -> EngineOrderStatus | None:
        """Tracked order truth incl. terminal + unknown (contract v1 §2).

        None ONLY when the id was never journaled. UNKNOWN and
        CANCEL_UNKNOWN surface as "unknown"; void surfaces as
        "cancelled" (terminal, zero-fill); triggered algos surface as
        "open" until their fills land.
        """
        if client_order_id not in self._reservations:
            return None
        return EngineOrderStatus(
            client_order_id=client_order_id,
            instrument=self._symbols.get(client_order_id, "?"),
            state=self._seam_state(
                self._states.get(client_order_id, "open")),
            qty=self._submitted_qty.get(client_order_id, 0.0),
            filled_qty=self._adopted_qty.get(
                client_order_id, self.filled_qty(client_order_id)),
            reservation_id=self._reservations.get(client_order_id),
            role=self._roles.get(client_order_id, "entry"),
            version=self._versions.get(client_order_id, 0))

    def _lookup_algo(self, client_id: str, symbol: str) -> dict | None:
        try:
            return self._signed("GET", "/fapi/v1/algoOrder",
                                {"symbol": symbol,
                                 "origClientAlgoId": client_id})
        except VenueRejectedError as exc:
            if exc.code == -2013:
                self._states[client_id] = "void"
                self._journal_transition("lookup-void", client_id, {})
                self._maybe_emit_terminal(client_id, symbol,
                                          "lookup-void:venue-never-saw")
                return None
            raise

    def unknown_ids(self) -> tuple[str, ...]:
        """Client ids needing lookup/reconciliation (contract v1 §2).

        Both UNKNOWN submits and CANCEL_UNKNOWN cancels: neither may be
        assumed — lookup() resolves each.
        """
        return tuple(sorted(cid for cid, st in self._states.items()
                            if st in ("UNKNOWN", "CANCEL_UNKNOWN")))

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
            key = f"{symbol}/{tid}"
            if tid and key in self._trades_booked:
                continue
            if tid:
                self._trades_booked.add(key)
            asset = str(trade.get("commissionAsset", "USDT"))
            if asset != "USDT":
                raise ValueError(
                    f"non-USDT commission {asset} on trade {tid}: "
                    f"multi-asset fees need explicit support")
            now = self._now_utc()
            exec_id = (self._fill_exec_id(symbol, tid) if tid
                       else f"{self._venue}/{self._account_tag}/{symbol}/"
                            f"notrade:{client_id}:{qty:.12f}")
            self._journal_transition("fill-adopted", client_id,
                                     {"symbol": symbol, "trade_id": tid,
                                      "qty": qty})
            self._adopted_qty[client_id] = self._adopted_qty.get(
                client_id, 0.0) + qty
            self._emit(EngineEvent(
                "fill",
                EngineFill(execution_id=exec_id,
                           client_order_id=client_id, instrument=symbol,
                           side=self._venue_side_of(client_id),
                           qty=qty, price=float(trade.get("price", 0.0)),
                           fee=float(trade.get("commission", 0.0)),
                           ts_utc=now, liquidity="taker"),
                now))
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
        """Cancel one order, preserving unknown exposure (W3-24H).

        Cancelling an UNKNOWN order looks up first (never assume the
        cancel landed). A cancel whose own outcome is unknown journals
        CANCEL_UNKNOWN and keeps blocking new exposure until lookup.
        Not-found (-2013) voids only orders with no adopted fills —
        partial fills plus not-found is contradictory and fails loudly.
        """
        if self._closed:
            raise RuntimeError("engine is closed")
        symbol = self._symbol_of(client_order_id)
        if self._states.get(client_order_id) in ("UNKNOWN", "CANCEL_UNKNOWN"):
            resolved = self.lookup(client_order_id)
            if resolved is None or resolved.state in TERMINAL_STATES:
                return  # lookup settled it: nothing left to cancel.
        self._journal("cancel-request", {"client_id": client_order_id,
                                         "reason": reason})
        is_algo = client_order_id in self._algo
        path = "/fapi/v1/algoOrder" if is_algo else "/fapi/v1/order"
        id_key = "origClientAlgoId" if is_algo else "origClientOrderId"
        try:
            self._signed("DELETE", path,
                         {"symbol": symbol, id_key: client_order_id})
        except VenueRejectedError as exc:
            if exc.code == -2013:
                if self.filled_qty(client_order_id) > 0:
                    raise ValueError(
                        f"venue reports {client_order_id} never existed "
                        f"but fills were adopted: reconcile manually") from None
                self._states[client_order_id] = "void"
                self._journal_transition("cancel-void", client_order_id, {})
                self._maybe_emit_terminal(client_order_id, symbol,
                                          "cancel-void:venue-never-saw")
                return
            raise
        except VenueHttpError as exc:
            if exc.status in UNKNOWN_HTTP_STATUSES:
                self._states[client_order_id] = "CANCEL_UNKNOWN"
                self._journal_transition(
                    "cancel-unknown", client_order_id, {"reason": str(exc)})
                raise UnknownOutcomeError(client_order_id, str(exc)) from None
            raise
        self._states[client_order_id] = "cancelled"
        self._journal_transition("cancel-acked", client_order_id,
                                 {"reason": reason})
        self._maybe_emit_terminal(client_order_id, symbol,
                                  f"cancel-acked:{reason}")
        self._orders_cache = None

    def open_orders(self) -> list[EngineOrderStatus]:
        """Venue open orders (vanilla + algo), TTL-cached, BOT-ORDERS ONLY.

        The hot Session path must not REST-spam, and foreign orders
        (manual/testnet strays) must never enter protection math: only
        journaled client ids are returned; ignored strays are journaled
        loudly by count.
        """
        if self._closed:
            raise RuntimeError("engine is closed")
        self._guarded("open_orders")
        now_s = self._now_utc().timestamp()
        if self._orders_cache is not None:
            cached_at, cached = self._orders_cache
            if now_s - cached_at < self._orders_ttl:
                return list(cached)
        views = self._signed("GET", "/fapi/v1/openOrders")
        algo_views = self._signed("GET", "/fapi/v1/openAlgoOrders")
        journaled = set(self._reservations)
        out: list[EngineOrderStatus] = []
        ignored = 0
        for v in views:
            cid = str(v.get("clientOrderId", ""))
            if cid not in journaled:
                ignored += 1
                continue
            out.append(EngineOrderStatus(
                client_order_id=cid, instrument=str(v.get("symbol", "")),
                state=_local_state(str(v.get("status", "NEW"))),
                qty=float(v.get("origQty", 0.0) or 0.0),
                filled_qty=float(v.get("executedQty", 0.0) or 0.0),
                reservation_id=self._reservations.get(cid),
                role=self._roles.get(cid, "entry"),
                version=self._versions.get(cid, 0)))
        for v in algo_views:
            cid = str(v.get("clientAlgoId", v.get("clientOrderId", "")))
            if cid not in journaled:
                ignored += 1
                continue
            trig = v.get("triggeredOrderId")
            if trig:
                self._triggered[cid] = str(trig)
            out.append(EngineOrderStatus(
                client_order_id=cid, instrument=str(v.get("symbol", "")),
                state=_local_state(str(v.get("algoStatus", "WORKING"))),
                qty=float(v.get("origQty", 0.0) or 0.0),
                filled_qty=float(v.get("executedQty", 0.0) or 0.0),
                reservation_id=self._reservations.get(cid),
                role=self._roles.get(cid, "entry"),
                version=self._versions.get(cid, 0)))
        if ignored:
            self._journal("foreign-orders-ignored", {"count": ignored})
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
        elif kind == "ALGO_UPDATE":
            self._note_algo_update(payload.get("o", {}), payload)
        elif kind == "ACCOUNT_UPDATE":
            self._journal("account-update", {"event_time": payload.get("E")})
        elif kind == "listenKeyExpired":
            self._listen_key = None
            self._journal("listen-key-expired", {})
        else:
            raise ValueError(f"unknown user-stream event: {kind!r}")

    def _note_algo_update(self, order: dict[str, Any], envelope: dict) -> None:
        """ALGO_UPDATE: algo status + triggered-id tracking (W3-24H).

        Shape: {"e": "ALGO_UPDATE", "E": ms, "o": {"s", "c" (client
        algo id), "S", "X" (algoStatus), "x", "i" (algoId),
        "ti" (triggered order id, 0 until fired)}}. Fills ride the
        triggered order (TRADE events / userTrades), never this event.
        """
        for key in ("s", "c", "S", "X", "x"):
            if key not in order:
                raise ValueError(f"ALGO_UPDATE missing {key!r}")
        cid = str(order["c"])
        self._states[cid] = _local_state(str(order["X"]))
        trig = order.get("ti") or order.get("triggeredOrderId")
        if trig:
            self._triggered[cid] = str(trig)
            self._journal_transition("algo-triggered", cid,
                                     {"triggered_id": str(trig)})
        self._journal_transition("user-order-state", cid,
                                 {"state": self._states[cid], "algo": True})
        self._maybe_emit_terminal(cid, str(order["s"]),
                                  f"algo-stream:{order['x']}")

    def _note_order_trade(self, order: dict[str, Any], envelope: dict) -> None:
        for key in ("s", "c", "S", "X", "x"):
            if key not in order:
                raise ValueError(f"ORDER_TRADE_UPDATE missing {key!r}")
        cid = str(order["c"])
        self._states[cid] = _local_state(str(order["X"]))
        self._journal_transition("user-order-state", cid,
                                 {"state": self._states[cid]})
        if str(order["x"]) != "TRADE":
            self._maybe_emit_terminal(cid, str(order["s"]),
                                      f"stream:{order['x']}")
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
        symbol = str(order["s"])
        key = f"{symbol}/{tid}"
        if tid and key in self._trades_booked:
            return  # lookup() already adopted this trade.
        if tid:
            self._trades_booked.add(key)
        ts = envelope.get("E")
        now = (datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
               if isinstance(ts, (int, float)) else self._now_utc())
        exec_id = (self._fill_exec_id(symbol, tid) if tid
                   else f"{self._venue}/{self._account_tag}/{symbol}/"
                        f"notrade:{cid}:{last_qty:.12f}")
        self._journal_transition("fill-adopted", cid,
                                 {"symbol": symbol, "trade_id": tid,
                                  "qty": last_qty, "via": "user-stream"})
        self._adopted_qty[cid] = self._adopted_qty.get(cid, 0.0) + last_qty
        self._emit(EngineEvent(
            "fill",
            EngineFill(execution_id=exec_id,
                       client_order_id=cid, instrument=symbol,
                       side=str(order["S"]), qty=last_qty,
                       price=float(order.get("L", 0.0) or 0.0),
                       fee=float(order.get("n", 0.0) or 0.0),
                       ts_utc=now, liquidity="taker"),
            now))

    # -- listenKey lifecycle ----------------------------------------------------------
    def _keyed(self, method: str, path: str,
               params: dict[str, Any] | None = None) -> Any:
        """API-key-authenticated call (listenKey lifecycle needs the key
        header but no signature)."""
        try:
            return self._transport.request(method, path, dict(params or {}),
                                           {"X-MBX-APIKEY": self._key})
        except VenueHttpError as exc:
            if self._is_rate_limit(exc):
                raise self._note_rate_limit(exc) from None
            if exc.status in UNKNOWN_HTTP_STATUSES:
                raise
            raise VenueRejectedError(exc.status, exc.code, exc.msg) from None

    @property
    def listen_key(self) -> str | None:
        """Current user-stream listenKey (None when never opened/expired)."""
        return self._listen_key

    def open_listen_key(self) -> str:
        """Create a user-stream listenKey (the socket dials it elsewhere)."""
        self._listen_key = str(self._keyed("POST", "/fapi/v1/listenKey")
                               ["listenKey"])
        self._journal("listen-key-open", {})
        return self._listen_key

    def keepalive_listen_key(self) -> None:
        if self._listen_key is None:
            raise ValueError("no listen key open")
        self._keyed("PUT", "/fapi/v1/listenKey")
        self._journal("listen-key-keepalive", {})

    def user_stream_url(self, listen_key: str) -> str:
        """Exact single-stream user-data URL for this engine's host.

        Derived from the effective REST base so the socket always
        matches the REST venue: demo-fapi→demo-fstream,
        fapi→fstream (prod, note: fstream not fapi), testnet→its
        stream host. Unrecognized custom hosts raise (no guessing).
        """
        if not listen_key or not isinstance(listen_key, str):
            raise ValueError("listen_key must be a non-empty string")
        host = self._base_url.rstrip("/")
        if host == DEMO_FAPI_URL:
            ws = DEMO_FSTREAM_URL
        elif host == PROD_FAPI_URL:
            ws = PROD_FSTREAM_URL
        elif host == TESTNET_BASE_URL:
            ws = TESTNET_FSTREAM_URL
        else:
            raise ValueError(
                "no user-stream host mapped for base_url "
                f"{self._base_url!r}")
        return f"{ws}/ws/{listen_key}"

    def stream_reconnected(self) -> None:
        """Heal a user-stream gap: look up every journaled non-terminal
        order (a dropped socket may have lost TRADE events)."""
        self._journal("stream-reconnected", {})
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
            self.lookup(cid)

    def account_snapshot(self) -> AccountSnapshot | None:
        """Authoritative positions/account/margin (contract v1 §2).

        One signed GET /fapi/v2/account per call (no cache: margin
        decisions read fresh truth). None when the venue cannot be
        reached; complete=False when any balance leg is missing (the
        caller must treat that as unknown, never flat). Position
        entry/mark prices are None when the venue omits them.
        """
        self._guarded("account_snapshot")
        try:
            view = self._signed("GET", "/fapi/v2/account")
        except VenueHttpError:
            return None
        now = self._now_utc()
        try:
            wallet = float(view["totalWalletBalance"])
            available = float(view["availableBalance"])
            margin = float(view["totalMarginBalance"])
        except (KeyError, TypeError, ValueError):
            try:
                wallet = float(view.get("totalWalletBalance", 0.0) or 0.0)
                available = float(view.get("availableBalance", 0.0) or 0.0)
                margin_raw = view.get("totalMarginBalance")
            except (TypeError, ValueError):
                return None
            return AccountSnapshot(
                wallet_equity_usdt=wallet,
                available_margin_usdt=available,
                margin_balance_usdt=(
                    float(margin_raw) if margin_raw is not None else None),
                positions=self._snapshot_positions(view.get("positions", [])),
                asof_utc=now, complete=False)
        return AccountSnapshot(
            wallet_equity_usdt=wallet,
            available_margin_usdt=available,
            margin_balance_usdt=margin,
            positions=self._snapshot_positions(view.get("positions", [])),
            asof_utc=now, complete=True)

    @staticmethod
    def _snapshot_positions(views: Any) -> tuple[AccountPosition, ...]:
        out: list[AccountPosition] = []
        if not isinstance(views, list):
            return ()
        for item in views:
            if not isinstance(item, dict):
                continue
            try:
                qty = float(item.get("positionAmt", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if qty == 0.0:
                continue
            entry = item.get("entryPrice")
            mark = item.get("markPrice")
            try:
                entry_f = float(entry) if entry is not None else None
            except (TypeError, ValueError):
                entry_f = None
            try:
                mark_f = float(mark) if mark is not None else None
            except (TypeError, ValueError):
                mark_f = None
            out.append(AccountPosition(
                instrument=str(item.get("symbol", "?")),
                qty=qty, entry_price=entry_f, mark_price=mark_f))
        return tuple(out)

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
        self._guarded("venue_funding_total")
        rows = self._signed("GET", "/fapi/v1/income",
                            {"symbol": symbol.upper(),
                             "incomeType": "FUNDING_FEE", "limit": 1000})
        return sum(float(r.get("income", 0.0) or 0.0) for r in rows)

    def venue_status(self, symbols: list[str]) -> dict[str, Any]:
        """Read-only account/venue snapshot for `cryptobot readiness`.

        Uses GET requests only: server time, account (balances, margin,
        positions), commission rates, position mode, exchange filters,
        and open orders. Never submits, cancels, or sets leverage/margin.
        Raises VenueHttpError/VenueRejectedError on transport failure.
        """
        self._guarded("venue_status")
        server_ms = int(self._public("GET", "/fapi/v1/time")["serverTime"])
        account = self._signed("GET", "/fapi/v2/account")
        dual = self._signed("GET", "/fapi/v1/positionSide/dual")
        info = self._public("GET", "/fapi/v1/exchangeInfo")
        wanted = {s.upper() for s in symbols}
        filters: dict[str, dict[str, Any]] = {}
        for entry in info.get("symbols", []):
            name = str(entry.get("symbol", "")).upper()
            if wanted and name not in wanted:
                continue
            kept = {}
            for filt in entry.get("filters", []):
                ftype = filt.get("filterType")
                if ftype in ("PRICE_FILTER", "LOT_SIZE", "MIN_NOTIONAL",
                             "MARKET_LOT_SIZE", "MAX_NUM_ORDERS"):
                    kept[ftype] = {k: v for k, v in filt.items()
                                   if k != "filterType"}
            filters[name] = {"status": entry.get("status"),
                             "filters": kept}
        fees = {}
        for symbol in sorted(wanted):
            row = self._signed("GET", "/fapi/v1/commissionRate",
                               {"symbol": symbol})
            fees[symbol] = {
                "maker_bps": float(row["makerCommissionRate"]) * 10000.0,
                "taker_bps": float(row["takerCommissionRate"]) * 10000.0,
            }
        open_orders = self._signed("GET", "/fapi/v1/openOrders")
        positions = [p for p in account.get("positions", [])
                     if float(p.get("positionAmt", 0.0) or 0.0) != 0.0]
        assets = [a for a in account.get("assets", [])
                  if float(a.get("walletBalance", 0.0) or 0.0) != 0.0]
        return {
            "base_url": self._base_url,
            "demo": self._demo,
            "account_tag": self._account_tag,
            "server_time_ms": server_ms,
            "clock_skew_ms": server_ms - self._now_ms(),
            "can_trade": bool(account.get("canTrade", False)),
            "can_withdraw": bool(account.get("canWithdraw", False)),
            "can_deposit": bool(account.get("canDeposit", False)),
            "fee_tier": account.get("feeTier", 0),
            "total_wallet_usdt": float(
                account.get("totalWalletBalance", 0.0) or 0.0),
            "available_usdt": float(
                account.get("availableBalance", 0.0) or 0.0),
            "total_margin_usdt": float(
                account.get("totalMarginBalance", 0.0) or 0.0),
            "total_initial_margin_usdt": float(
                account.get("totalInitialMargin", 0.0) or 0.0),
            "assets": assets,
            "positions": positions,
            "position_mode": ("hedge" if dual.get("dualSidePosition")
                              else "one-way"),
            "fees_bps": fees,
            "filters": filters,
            "open_orders": open_orders,
        }

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

    def bind_sink(self, handler: Any) -> None:
        """Bind the Session execution-event handler (contract v1 §2).

        The callable takes one EngineEvent and is invoked on EVERY
        emission (user-stream fills, lookup-adopted fills,
        recovery-adopted fills, terminal events); poll() then drains
        only pre-binding leftovers. Direct note_fill_delta booking is
        removed: Session books through the handler (W1 owns that side).
        """
        if not callable(handler):
            raise TypeError("bind_sink needs an EngineEvent callable; "
                            "direct note_fill_delta booking is removed")
        self._event_handler = handler
        self._journal("sink-bound", {"mode": "event-handler"})

    def recover(self, handler: Any) -> None:
        """Reconcile every journaled non-terminal order via lookup.

        Recovery-adopted fills flow through the bound handler as
        EngineEvents (new-style) or queue for poll(); Session applies
        idempotently by execution_id, so re-adoption is safe.
        """
        self.bind_sink(handler)
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
                    self._journal_transition(
                        "recover-unknown", cid, {"reason": str(exc)})
                else:
                    raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._listen_key is not None:
            try:
                self._keyed("DELETE", "/fapi/v1/listenKey")
            except VenueHttpError as exc:
                self._journal("listen-key-close-failed",
                              {"reason": str(exc)})
            self._listen_key = None
        self._journal("closed", {})
