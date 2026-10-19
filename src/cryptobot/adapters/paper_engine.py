"""Nautilus-backed paper execution engine (Worker 2, E-008, S3 seam).

Implements the canonical :class:`cryptobot.app.engine.PaperEngine` protocol
(manager-owned; this module imports those types and defines no competing
event/order types) on top of NautilusTrader's own simulated matching core:
the same ``SimulatedExchange`` + ``BacktestExecClient`` pair that
``SandboxExecutionClient`` delegates to internally. This module is NOT a
competing fill engine — every fill, cancel, reject, and expiry is produced by
Nautilus; the engine only translates between durable bot IDs and nautilus
commands/events.

Constructor matches the CLI paper seam exactly::

    NautilusPaperEngine(outcome_sink=None, taker_bps=..., now_utc=...,
                        submit_delay_ms=..., fill_delay_ms=...)

Taker-only by construction: MARKET, STOP_MARKET, TAKE_PROFIT_MARKET
(market-if-touched), and LIMIT orders all take liquidity when they trade.
Canonical LIMIT maps to a nautilus LIMIT IOC (marketable-or-cancel with price
protection); resting GTC limits are unsupported — filling them as maker would
need a queue model that does not exist yet. Any fill the simulator labels
non-taker fails closed (raises) instead of booking mislabeled costs.

Market-data drive has two tiers, both observed-only (nothing fabricated):
1. ``feed`` / ``note_event`` with real quotes/trades/book deltas: the sim
   crosses the observed book — true taker-cross fills (replay bridge path).
2. ``note_mark`` (session live-paper path): the mark feeds the sim as a
   zero-spread quote (the "mark-quote" model, labeled in assumptions). Fill
   basis equals the session mark (reference-equivalent); spread/size realism
   upgrades automatically if the seam ever carries quotes.

Paper mode never instantiates a Binance live execution client (R0): the only
execution client in this module is nautilus' backtest/sandbox simulator.
"""
from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from nautilus_trader.accounting.manager import AccountsManager
from nautilus_trader.backtest.engine import SimulatedExchange
from nautilus_trader.backtest.execution_client import BacktestExecClient
from nautilus_trader.backtest.models import FillModel, LatencyModel, MakerTakerFeeModel
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import Logger, MessageBus, TestClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.data import Data
from nautilus_trader.core.datetime import dt_to_unix_nanos, unix_nanos_to_dt
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import CancelOrder, SubmitOrder
from nautilus_trader.model.currencies import BTC, USDT
from nautilus_trader.model.data import Bar, OrderBookDelta, OrderBookDeltas, QuoteTick, TradeTick
from nautilus_trader.model.enums import (
    AccountType,
    BookType,
    LiquiditySide,
    OmsType,
    OrderSide,
    OrderStatus,
    TimeInForce,
)
from nautilus_trader.model.events import (
    OrderAccepted,
    OrderCanceled,
    OrderCancelRejected,
    OrderEvent,
    OrderExpired,
    OrderFilled,
    OrderRejected,
    OrderUpdated,
)
from nautilus_trader.model.events.position import (
    PositionChanged,
    PositionClosed,
    PositionOpened,
)
from nautilus_trader.model.identifiers import (
    ClientId,
    ClientOrderId,
    InstrumentId,
    PositionId,
    StrategyId,
    TraderId,
    Venue,
)
from nautilus_trader.model.instruments import CryptoPerpetual, Instrument
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.orders.base import Order
from nautilus_trader.model.position import Position
from nautilus_trader.portfolio.portfolio import Portfolio

from cryptobot.app.engine import (
    AccountPosition,
    AccountSnapshot,
    EngineCancel,
    EngineEvent,
    EngineExpire,
    EngineFill,
    EngineFunding,
    EngineOrder,
    EngineOrderStatus,
    EngineReject,
)
from cryptobot.execution.fill_realism import (
    PaperFillParams, pessimistic_fill_price)
from cryptobot.market_data.discovery import FAPI_BASE_URL, urllib_json_get
from cryptobot.risk.rounding import floor_to_step, round_to_tick

__all__ = ["ENGINE_VERSION", "NautilusPaperEngine"]

ENGINE_VERSION = "e008-1"

VENUE = Venue("BINANCE")

# Nautilus applied states -> seam states (open|partial|filled|rejected|cancelled|expired).
# Keyed by OrderStatus value (order.status exposes the raw int from Cython).
# Unknown states map to "open": flat inference treats non-terminal as live, and
# blocking flat on an unknown is the safe direction (a false flat is worse).
_SEAM_STATE = {
    1: "open", 2: "rejected", 3: "open", 4: "open", 5: "open", 6: "open",
    7: "rejected", 8: "cancelled", 9: "expired", 10: "open", 11: "open",
    12: "open", 13: "partial", 14: "filled", 15: "cancelled",
}

# Order events that move account state (mirrors nautilus portfolio's set).
_ACCOUNT_EVENTS = (OrderAccepted, OrderCanceled, OrderExpired, OrderRejected,
                   OrderUpdated, OrderFilled)



def _venue_side(side: str) -> OrderSide:
    text = str(side).upper()
    if text in ("BUY", "LONG"):
        return OrderSide.BUY
    if text in ("SELL", "SHORT"):
        return OrderSide.SELL
    raise ValueError(f"side must be BUY/SELL, got {side!r}")


class NautilusPaperEngine:
    """Canonical S3 paper engine, nautilus-backed (CLI paper seam)."""

    model_label = "nautilus-paper"

    def __init__(
        self,
        outcome_sink: Any | None = None,
        taker_bps: float = 5.0,
        now_utc: Callable[[], datetime] | None = None,
        submit_delay_ms: int = 0,
        fill_delay_ms: int | None = None,
        *,
        journal_path: str | Path | None = None,
        maker_bps: float | None = None,
        starting_balance_usdt: float = 10_000.0,
        trader_id: str = "W2-PAPER-001",
        strategy_id: str = "RUNTIME-001",
        client_id_prefix: str = "pe",
        random_seed: int = 42,
        rest_get: Callable | None = None,
        strict_replay: bool = False,
        default_leverage: int = 1,
        max_queued_submits: int = 1000,
        max_pending_events: int = 10000,
        run_tag: str | None = None,
        fill_params: PaperFillParams | dict | None = None,
    ) -> None:
        if isinstance(fill_params, dict):
            fill_params = PaperFillParams.from_dict(fill_params)
        # F0.4c: explicit parameterized fill economics. Defaults are
        # ASSUMED-pessimistic until F2.2 calibrates MEASURED params.
        self.fill_params: PaperFillParams = (
            fill_params if fill_params is not None
            else PaperFillParams.default_pessimistic())
        # Delay model comes from params unless explicitly overridden.
        if fill_delay_ms is None:
            fill_delay_ms = self.fill_params.latency_ms_p95
        if taker_bps <= 0:
            raise ValueError("taker_bps must be > 0 (run-mode fees are never zero)")
        if fill_delay_ms <= 0:
            raise ValueError("fill_delay_ms must be > 0 (S3 nonzero submission/fill delay)")
        if submit_delay_ms < 0:
            raise ValueError("submit_delay_ms must be >= 0")
        if starting_balance_usdt <= 0:
            raise ValueError("starting_balance_usdt must be > 0")
        if default_leverage <= 0:
            raise ValueError("default_leverage must be > 0 (aligns with risk cap)")
        if max_queued_submits <= 0 or max_pending_events <= 0:
            raise ValueError("queue bounds must be > 0 (B10 bounded ingestion)")
        # Contract v1: the constructor sink is the event handler when
        # callable. A legacy note_fill_delta object is tolerated but
        # NEVER invoked (direct booking removed; W1 renames this param).
        self._event_handler = outcome_sink if callable(outcome_sink) else None
        self._legacy_sink_ignored = (
            outcome_sink is not None and not callable(outcome_sink))
        self.taker_bps = float(taker_bps)
        self.maker_bps = float(taker_bps if maker_bps is None else maker_bps)
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.submit_delay_ms = int(submit_delay_ms)
        self.fill_delay_ms = int(fill_delay_ms)
        self.strict_replay = bool(strict_replay)
        self.default_leverage = int(default_leverage)
        self.max_queued_submits = int(max_queued_submits)
        self.max_pending_events = int(max_pending_events)
        self.journal_path = Path(journal_path) if journal_path else None
        self._rest_get = rest_get or urllib_json_get
        self._rng = random.Random(random_seed)  # deterministic client ids (B1).
        self._clock = TestClock()
        self._trader_id = TraderId(trader_id)
        self._strategy_id = StrategyId(strategy_id)
        self._prefix = client_id_prefix
        self._msgbus = MessageBus(trader_id=self._trader_id, clock=self._clock)
        self._cache = Cache(database=None)
        self._portfolio = Portfolio(msgbus=self._msgbus, clock=self._clock, cache=self._cache)
        self._accounts = AccountsManager(self._cache, Logger("W2-ACCOUNTS"),
                                         self._clock)
        self._exchange = SimulatedExchange(
            venue=VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(starting_balance_usdt, USDT)],
            base_currency=USDT,
            default_leverage=Decimal(self.default_leverage),
            leverages={},
            modules=[],
            portfolio=self._portfolio,
            msgbus=self._msgbus,
            cache=self._cache,
            clock=self._clock,
            # F0.4c: nautilus handles MATCHING TIMING; fill ECONOMICS are
            # set by self.fill_params (PaperFillParams, versioned +
            # provenance-stamped). prob_slippage=1.0 keeps the pessimistic
            # direction (never better than touch); the explicit bps terms
            # (spread/slippage/latency/empty-book) price the fill via
            # slippage_audit, and F2.2 calibrates them from measured
            # fills. The bare "one tick" rule is retired: every basis
            # point is now a named, versioned parameter.
            fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=1.0,
                                 random_seed=random_seed),
            fee_model=MakerTakerFeeModel(),  # reads maker/taker fees off each instrument.
            latency_model=LatencyModel(self.fill_delay_ms * 1_000_000),
            book_type=BookType.L1_MBP,
            support_contingent_orders=False,  # S3: simulator-only contingencies disabled.
            use_reduce_only=True,
            use_message_queue=True,
        )
        self._client = BacktestExecClient(
            exchange=self._exchange, msgbus=self._msgbus,
            cache=self._cache, clock=self._clock,
        )
        self._client._start()
        self._exchange.register_client(self._client)
        self._exchange.initialize_account()
        self._factory = OrderFactory(
            trader_id=self._trader_id, strategy_id=self._strategy_id, clock=self._clock,
        )
        self._orders: dict[str, Order] = {}  # durable client id -> nautilus order.
        self._instruments: dict[str, Instrument] = {}  # symbol -> nautilus instrument.
        self._filters: dict[str, dict[str, float]] = {}  # symbol -> tick/step/minQty/minNotional.
        self._symbols: dict[str, str] = {}  # client id -> symbol.
        self._roles: dict[str, str] = {}  # client id -> role.
        self._reservations: dict[str, str | None] = {}  # client id -> reservation.
        self._marks: dict[str, float] = {}
        # V-008 §7: mark-age semantics — every exchange mark carries its
        # observation time; settled funding totals back ledger/engine
        # reconciliation after funding as well as fills.
        self._mark_ts: dict[str, datetime] = {}
        self._settled_funding: dict[str, float] = {}
        self._funding_terms: dict[str, dict[str, Any]] = {}  # symbol -> rate/next/settled.
        self._pending: list[EngineEvent] = []
        self._submit_queue: list[tuple[int, EngineOrder, str]] = []  # (due_ns, cmd, id).
        self._pre2real: dict[str, str] = {}  # queue id -> durable id (same value here).
        self._lost: dict[str, dict[str, Any]] = {}  # recover(): journaled but not in sim.
        self._recovered_fills: dict[str, float] = {}  # recover(): client id -> filled qty.
        self._seq = 0
        self._run_tag = run_tag or trader_id
        self._fill_seq = 0  # paper/{run}/{sym}/{seq} execution ids.
        self._versions: dict[str, int] = {}  # client id -> transition count.
        # Terminal-without-sim orders (arrival-cancelled IOC, queued-past-
        # window): tracked truth for order_status(), never in _orders.
        self._dead: dict[str, dict[str, Any]] = {}
        self._closed = False
        self._exit_only = False
        self._exit_only_reasons: set[str] = set()
        # IOC no-rest enforcement (30MIN §4): causally-available book per
        # symbol (BBO from quotes, last print fallback for trade-only),
        # data-tick clock, and tracked IOC arrivals for remainder-cancel.
        self._bbo: dict[str, tuple[float, float, float, float]] = {}
        self._last_print: dict[str, tuple[float, float]] = {}
        self._op_seq = 0  # processing opportunities (feeds + advances).
        self._ioc_open: dict[str, int] = {}  # client id -> arrival op.
        self._ioc_accepted: dict[str, int] = {}  # client id -> accept op.
        self._ioc_cancel_sent: set[str] = set()
        self._ioc_done: dict[str, None] = {}  # bounded terminal-IOC memory.
        self.stats: dict[str, int] = {  # engine-owned counters (B1/B10).
            "engine_events_total": 0,
            "pending_events": 0,
            "queued_submits": 0,
            "restamped_ticks": 0,
            "funding_events": 0,
            "ioc_remainder_canceled": 0,
            "ioc_artifact_corrected": 0,
        }
        if self.journal_path is not None:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._msgbus.register(endpoint="ExecEngine.process", handler=self._on_order_event)

    # -- sink ------------------------------------------------------------------
    def bind_sink(self, handler: Any) -> None:
        """Bind the Session execution-event handler (contract v1 §2).

        The callable takes one EngineEvent and is invoked on EVERY
        emission (fills, terminals, funding, recovery-adopted fills);
        poll() then drains only pre-binding leftovers. Direct
        note_fill_delta booking is removed: Session books through the
        handler (W1 owns the handler side).
        """
        if not callable(handler):
            raise TypeError("bind_sink needs an EngineEvent callable; "
                            "direct note_fill_delta booking is removed")
        self._event_handler = handler
        self._journal("sink-bound", {"mode": "event-handler"})

    def _emit(self, event: EngineEvent) -> None:
        """Route one emission: push when bound, else queue for poll()."""
        if self._event_handler is not None:
            self._event_handler(event)
            return
        self._enqueue(event)

    # -- instruments -----------------------------------------------------------
    def add_instrument(
        self,
        symbol: str,
        *,
        price_precision: int,
        size_precision: int,
        tick_size: float,
        step_size: float,
        min_qty: float = 0.0,
        min_notional: float = 0.0,
        ts_utc: datetime | None = None,
    ) -> InstrumentId:
        """Register one USDT-perp instrument (fees come from taker_bps)."""
        moment = ts_utc or self._now_utc()
        ts_ns = dt_to_unix_nanos(moment)
        iid = InstrumentId.from_str(f"{symbol.upper()}.{VENUE.value}")
        instrument = CryptoPerpetual(
            instrument_id=iid,
            raw_symbol=iid.symbol,
            base_currency=BTC if symbol.upper().startswith("BTC") else USDT,
            quote_currency=USDT,
            settlement_currency=USDT,
            is_inverse=False,
            price_precision=price_precision,
            size_precision=size_precision,
            price_increment=Price(tick_size, price_precision),
            size_increment=Quantity(step_size, size_precision),
            ts_event=ts_ns,
            ts_init=ts_ns,
            maker_fee=Decimal(str(self.maker_bps / 10_000)),
            taker_fee=Decimal(str(self.taker_bps / 10_000)),
            # Margin requirements (labeled assumption, linear model): with
            # nautilus' default LeveragedMarginModel, init = notional/L
            # (matches Binance cross initial at leverage L) and maint =
            # notional/(2L) (conservative linear stand-in for the venue's
            # tiered MMR schedule; the venue's real tiers are NOT modeled).
            margin_init=Decimal(1),
            margin_maint=Decimal("0.5"),
        )
        self._exchange.add_instrument(instrument)
        self._cache.add_instrument(instrument)  # portfolio margin/balance path.
        self._instruments[symbol.upper()] = instrument
        self._filters[symbol.upper()] = {
            "tick": float(tick_size), "step": float(step_size),
            "min_qty": float(min_qty), "min_notional": float(min_notional),
        }
        return iid

    def instrument_id(self, symbol: str) -> InstrumentId:
        return InstrumentId.from_str(f"{symbol.upper()}.{VENUE.value}")

    def _ensure_instrument(self, symbol: str) -> Instrument:
        """Return the registered instrument, auto-registering from live venue filters.

        Live paper cannot know precisions upfront: the first sighting of a
        symbol fetches its real PRICE_FILTER/LOT_SIZE/MIN_NOTIONAL from the
        public exchangeInfo endpoint (no creds). REST failure fails closed —
        the engine never invents filters.
        """
        known = self._instruments.get(symbol.upper())
        if known is not None:
            return known
        try:
            payload, _ = self._rest_get(f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo", 15.0)
        except Exception as exc:
            raise RuntimeError(f"cannot register {symbol}: venue filters unreachable") from exc
        entry = next((s for s in payload.get("symbols", [])
                      if str(s.get("symbol", "")).upper() == symbol.upper()), None)
        if entry is None:
            raise KeyError(f"unknown instrument: {symbol!r} (not on venue)")
        filters = {f["filterType"]: f for f in entry.get("filters", [])}
        try:
            tick = float(filters["PRICE_FILTER"]["tickSize"])
            step = float(filters["LOT_SIZE"]["stepSize"])
            min_qty = float(filters["LOT_SIZE"].get("minQty", 0.0))
            min_notional = float(filters.get("MIN_NOTIONAL", {}).get("notional", 0.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"cannot register {symbol}: unparsable venue filters") from exc
        self.add_instrument(symbol, price_precision=int(entry["pricePrecision"]),
                            size_precision=int(entry["quantityPrecision"]),
                            tick_size=tick, step_size=step,
                            min_qty=min_qty, min_notional=min_notional)
        return self._instruments[symbol.upper()]

    def _quantize_qty(self, symbol: str, qty: float) -> float:
        """Floor to the LOT_SIZE step (venue behavior); reject dust below minQty.

        V-008 §7: the one shared venue-rounding rule (submission leg).
        """
        step = self._filters[symbol.upper()]["step"]
        quantized = floor_to_step(qty, step)
        if quantized <= 0:
            raise ValueError(f"qty {qty} below LOT_SIZE step {step} for {symbol}")
        if quantized < self._filters[symbol.upper()]["min_qty"]:
            raise ValueError(f"qty {quantized} below venue minQty for {symbol}")
        return quantized

    def _round_tick(self, symbol: str, price: float) -> float:
        # V-008 §7: the one shared venue-rounding rule (price leg).
        return round_to_tick(price, self._filters[symbol.upper()]["tick"])

    def slippage_audit(self, *, side: str, qty: float,
                       nautilus_price: float,
                       levels: list[tuple[float, float]],
                       symbol: str) -> dict:
        """Audit a nautilus fill against the pessimistic model (F0.4c).

        Prices ``qty`` against ``levels`` (best-first book snapshot at
        fill time; top-of-book suffices — uncovered remainder draws the
        empty-book penalty) plus the params latency term. Returns the
        pessimistic price, the nautilus price, and non-negative drift
        in bps (0 when nautilus is already at/past pessimistic).
        drift_bps > 0 means the simulator was optimistic: F2.2 feeds
        these audits into calibration, and paper P&L must use the
        pessimistic leg (never better). Pure function of its inputs +
        self.fill_params (deterministic).
        """
        pessimistic = pessimistic_fill_price(
            side, qty=qty, levels=levels,
            latency_bps=self.fill_params.latency_bps,
            empty_book_bps=self.fill_params.empty_book_bps)
        if side == "BUY":
            drift = max(0.0, pessimistic - float(nautilus_price))
        elif side == "SELL":
            drift = max(0.0, float(nautilus_price) - pessimistic)
        else:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        base = float(nautilus_price) or 1.0
        return {"symbol": symbol.upper(), "side": side,
                "qty": float(qty), "nautilus_price": float(nautilus_price),
                "pessimistic_price": pessimistic,
                "drift_bps": drift / base * 10000.0,
                "params_version": self.fill_params.version,
                "provenance": self.fill_params.provenance}

    def _fill_drift_bps(self, symbol: str, side: str,
                        qty: float, price: float) -> float:
        """Pessimistic drift for one fill (B#9; never negative).

        BBO single-level book-walk when tracked; last-print level
        when only prints exist; flat params cost (spread + slippage
        + latency) when no book evidence exists at all. Audit
        failures fail CLOSED to the flat params cost (never 0 by
        accident — an unaudited fill must not read as perfect).
        """
        params = self.fill_params
        flat = params.spread_bps + params.slippage_bps + params.latency_bps
        if qty <= 0 or price <= 0:
            return flat
        levels: list[tuple[float, float]] | None = None
        bbo = self._bbo.get(symbol.upper())
        if bbo is not None:
            bid, ask, bid_size, ask_size = bbo
            if side == "BUY" and ask > 0 and ask_size > 0:
                levels = [(ask, ask_size)]
            elif side == "SELL" and bid > 0 and bid_size > 0:
                levels = [(bid, bid_size)]
        if levels is None:
            last = self._last_print.get(symbol.upper())
            if last is not None and last[0] > 0 and last[1] > 0:
                levels = [(last[0], last[1])]
        if levels is None:
            return flat
        try:
            audit = self.slippage_audit(
                side=side, qty=qty, nautilus_price=price,
                levels=levels, symbol=symbol)
        except (ValueError, ArithmeticError):
            return flat
        return max(0.0, float(audit["drift_bps"]))

    # -- S3 seam ----------------------------------------------------------
    def _new_client_id(self) -> str:
        self._seq += 1
        return f"{self._prefix}-{self._seq:06d}-{self._rng.getrandbits(32):08x}"

    def submit(self, cmd: EngineOrder) -> str:
        """Submit (modeled submit-delay may apply); returns id for resolve()."""
        if self._closed:
            raise RuntimeError("engine is closed")
        if self._exit_only and cmd.role == "entry":
            raise PermissionError("exit-only mode refuses new entries")
        self._validate(cmd)
        client_id = self._new_client_id()
        if self.submit_delay_ms > 0:
            if len(self._submit_queue) >= self.max_queued_submits:
                raise OverflowError(
                    f"submit queue full ({self.max_queued_submits}); "
                    "advance the clock (feed/advance_to) to drain it")
            due = self._clock.timestamp_ns() + self.submit_delay_ms * 1_000_000
            self._submit_queue.append((due, cmd, client_id))
            self.stats["queued_submits"] = len(self._submit_queue)
            self._drain_pending()
            self.stats["queued_submits"] = len(self._submit_queue)
            return client_id
        return self._submit_now(cmd, client_id)

    def submit_protected(self, cmd: EngineOrder, limit_price: float) -> str:
        """Price-protected marketable IOC entry: fills at-or-better or not at all.

        The limit bounds the cross (BUY fills at ask <= limit, SELL at bid >=
        limit); when bounds cannot be honored the order cancels on the next
        data tick (opportunity expired — never chased, never faked).
        """
        if limit_price <= 0:
            raise ValueError("limit_price must be > 0")
        protected = EngineOrder(
            instrument=cmd.instrument, side=cmd.side, qty=cmd.qty, kind="LIMIT",
            price=limit_price, reduce_only=cmd.reduce_only,
            reservation_id=cmd.reservation_id, expire_at_utc=cmd.expire_at_utc,
            role=cmd.role)
        return self.submit(protected)

    def submit_immediate(self, cmd: EngineOrder) -> str:
        """Submit bypassing modeled delays. Exits/flatten ONLY, never entries.

        DIAGNOSTIC latency model: zero submit + zero venue latency. Base
        economics must not depend on instant exits — journal tags every
        such submit immediate-exit for sensitivity review (30MIN §4).
        """
        if cmd.role == "entry":
            raise ValueError("submit_immediate is exits-only; entries use submit()")
        if self._closed:
            raise RuntimeError("engine is closed")
        self._validate(cmd)
        client_id = self._new_client_id()
        # Bypass the venue-latency model for this one command (urgent exit);
        # the configured model is restored immediately afterwards.
        prev = self._exchange.latency_model
        self._exchange.set_latency_model(LatencyModel(0))
        try:
            return self._submit_now(cmd, client_id, immediate=True)
        finally:
            self._exchange.set_latency_model(prev)

    def _validate(self, cmd: EngineOrder) -> None:
        if cmd.qty <= 0:
            raise ValueError("qty must be > 0")
        kind = cmd.kind.upper()
        if kind == "LIMIT" and cmd.price is None:
            raise ValueError("LIMIT submit needs price")
        if kind in ("STOP_MARKET", "TAKE_PROFIT_MARKET") and cmd.stop_price is None:
            raise ValueError(f"{kind} submit needs stop_price")
        if kind not in ("MARKET", "LIMIT", "STOP_MARKET", "TAKE_PROFIT_MARKET"):
            raise ValueError(f"unsupported order kind {cmd.kind!r}")

    def _bump(self, client_id: str) -> int:
        """Bump one order's transition version (contract v1 §2)."""
        self._versions[client_id] = self._versions.get(client_id, 0) + 1
        return self._versions[client_id]

    def _submit_now(self, cmd: EngineOrder, client_id: str,
                    immediate: bool = False,
                    arrival_ns: int | None = None,
                    venue_ts_ns: int | None = None) -> str:
        instrument = self._ensure_instrument(cmd.instrument)
        symbol = cmd.instrument.upper()
        qty = self._quantize_qty(symbol, cmd.qty)
        notional_ref = cmd.price or cmd.stop_price or self._marks.get(symbol)
        min_notional = self._filters[symbol]["min_notional"]
        if min_notional and notional_ref and qty * notional_ref < min_notional:
            raise ValueError(f"notional below venue MIN_NOTIONAL for {symbol}")
        iid = self.instrument_id(symbol)
        side = _venue_side(cmd.side)
        coid = ClientOrderId(client_id)
        kind = cmd.kind.upper()
        # MARKET works through arriving liquidity (GTC/GTD), never cancels
        # for thin prints: with a live book it still resolves on the next
        # tick; on trade-only replay it fills across prints at observed
        # prices instead of fake-cancelling the remainder (IOC would cancel
        # anything the next print cannot cover — real markets never do that).
        # Only price-protected LIMIT stays IOC (marketable-or-cancel).
        use_gtd = cmd.expire_at_utc is not None
        tif = TimeInForce.GTD if use_gtd else TimeInForce.GTC
        if kind == "MARKET":
            # GTC so thin prints never fake-cancel the remainder (sweeps
            # complete across ticks; nautilus market() takes no expire_time
            # and in-sim markets resolve on the next tick by construction —
            # entry windows bind pre-submit and in the submit queue below).
            order = self._factory.market(
                instrument_id=iid, order_side=side,
                quantity=Quantity(qty, instrument.size_precision),
                time_in_force=TimeInForce.GTC,
                reduce_only=cmd.reduce_only, client_order_id=coid,
            )
        elif kind == "LIMIT":
            # Taker-only mapping: marketable-or-cancel with price protection.
            # Arrival gate (30MIN §4): a nonmarketable IOC cancels HERE, at
            # command arrival against the causally-available book — it is
            # never submitted, so it can never revive on a later tick.
            assert cmd.price is not None
            cap = self._round_tick(symbol, cmd.price)
            if not self._ioc_marketable(symbol, side, cap):
                arrived = (self._clock.timestamp_ns() if arrival_ns is None
                           else arrival_ns)
                ts_utc = unix_nanos_to_dt(arrived).replace(tzinfo=timezone.utc)
                _prt = self._last_print.get(symbol)
                ref = self._bbo.get(symbol, ((_prt[0] if _prt else None),
                                             (_prt[0] if _prt else None),
                                             0.0, 0.0))
                self._journal("submitted", {
                    "client_id": client_id, "instrument": symbol,
                    "side": cmd.side, "qty": qty, "kind": kind,
                    "role": cmd.role, "reservation_id": cmd.reservation_id,
                    "at_arrival": True})
                self._journal("terminal", {
                    "client_id": client_id, "kind": "cancel",
                    "reason": "nonmarketable-at-arrival", "cap": cap,
                    "ref_touch": ref[1] if side == OrderSide.BUY else ref[0]})
                # Two observable transitions: submitted + terminal.
                self._bump(client_id)
                self._bump(client_id)
                self._dead[client_id] = {
                    "state": "cancelled", "symbol": symbol, "qty": qty,
                    "filled_qty": 0.0, "reservation_id": cmd.reservation_id,
                    "role": cmd.role, "version": self._versions[client_id]}
                self._emit(EngineEvent(
                    "cancel", EngineCancel(client_id, symbol,
                                           "nonmarketable-at-arrival", ts_utc),
                    ts_utc))
                self._ioc_done[client_id] = None
                return client_id
            order = self._factory.limit(
                instrument_id=iid, order_side=side,
                quantity=Quantity(qty, instrument.size_precision),
                price=Price(cap, instrument.price_precision),
                time_in_force=TimeInForce.IOC,
                reduce_only=cmd.reduce_only, client_order_id=coid,
            )
            self._ioc_open[client_id] = self._op_seq
        elif kind == "STOP_MARKET":
            assert cmd.stop_price is not None
            order = self._factory.stop_market(
                instrument_id=iid, order_side=side,
                quantity=Quantity(qty, instrument.size_precision),
                trigger_price=Price(self._round_tick(symbol, cmd.stop_price),
                                    instrument.price_precision),
                time_in_force=tif, expire_time=cmd.expire_at_utc,
                reduce_only=cmd.reduce_only, client_order_id=coid,
            )
        else:  # TAKE_PROFIT_MARKET == market-if-touched: trigger then cross.
            assert cmd.stop_price is not None
            order = self._factory.market_if_touched(
                instrument_id=iid, order_side=side,
                quantity=Quantity(qty, instrument.size_precision),
                trigger_price=Price(self._round_tick(symbol, cmd.stop_price),
                                    instrument.price_precision),
                time_in_force=tif, expire_time=cmd.expire_at_utc,
                reduce_only=cmd.reduce_only, client_order_id=coid,
            )
        self._orders[client_id] = order
        self._cache.add_order(order)  # portfolio balance/margin path.
        self._symbols[client_id] = symbol
        self._roles[client_id] = cmd.role
        self._reservations[client_id] = cmd.reservation_id
        # CORR-EXEC: the command enters the venue at its MODELED due time,
        # not at observation time — a drain at T for a due at T-150ms must
        # not let post-due information determine the execution. Canonical
        # LIMIT (nautilus IOC) ALWAYS resolves at due time against the
        # standing arrival book — immediate-or-cancel by definition, no
        # tick required — so it ignores the advance observation override:
        # drains on bare time advance resolve it in that same advance.
        # Other kinds keep observation-time stamping on advance drains
        # (next-tick resolution, baseline behavior).
        if venue_ts_ns is not None and kind != "LIMIT":
            venue_ts = venue_ts_ns
        else:
            venue_ts = (self._clock.timestamp_ns() if arrival_ns is None
                        else arrival_ns)
        self._client.submit_order(SubmitOrder(
            trader_id=self._trader_id, strategy_id=self._strategy_id, order=order,
            command_id=UUID4(), ts_init=venue_ts,
            client_id=ClientId(VENUE.value),
        ))
        submitted: dict[str, Any] = {
            "client_id": client_id, "instrument": symbol,
            "side": cmd.side, "qty": qty, "kind": kind,
            "role": cmd.role, "reservation_id": cmd.reservation_id}
        if immediate:
            submitted["immediate_exit"] = True  # diagnostic: zero latency.
        self._journal("submitted", submitted)
        self._bump(client_id)
        return client_id

    def _drain_pending(self, venue_now_ns: int | None = None) -> None:
        # venue_now_ns: observation-time stamp for advance-context drains
        # of non-IOC kinds (None = modeled-due-time stamp for feed/poll/
        # submit drains; canonical LIMIT always stamps due time).
        now_ns = self._clock.timestamp_ns()
        due_now = [item for item in self._submit_queue if item[0] <= now_ns]
        self._submit_queue = [item for item in self._submit_queue if item[0] > now_ns]
        # Stable FIFO per due tick: same-tick submits (entry + protection
        # legs) must never compare EngineOrder (integration fix: TypeError
        # crashed R2 on its first live protection attach).
        for due_ns, cmd, client_id in sorted(due_now, key=lambda item: item[0]):
            if (cmd.expire_at_utc is not None
                    and now_ns > dt_to_unix_nanos(cmd.expire_at_utc)):
                # Window passed while queued: expire, never submit late.
                ts_utc = unix_nanos_to_dt(now_ns).replace(tzinfo=timezone.utc)
                self._journal("submitted", {
                    "client_id": client_id,
                    "instrument": cmd.instrument.upper(),
                    "side": cmd.side, "qty": cmd.qty, "kind": cmd.kind.upper(),
                    "role": cmd.role, "reservation_id": cmd.reservation_id,
                    "expired_queued": True})
                self._journal("terminal", {"client_id": client_id, "kind": "expire",
                                          "reason": "queued-past-window"})
                # Two observable transitions: submitted-intent + terminal.
                self._bump(client_id)
                self._bump(client_id)
                self._dead[client_id] = {
                    "state": "expired", "symbol": cmd.instrument.upper(),
                    "qty": cmd.qty, "filled_qty": 0.0,
                    "reservation_id": cmd.reservation_id, "role": cmd.role,
                    "version": self._versions[client_id]}
                self._emit(EngineEvent(
                    "expire", EngineExpire(client_id, cmd.instrument.upper(),
                                           "queued-past-window", ts_utc), ts_utc))
                continue
            self._submit_now(cmd, client_id, arrival_ns=due_ns,
                               venue_ts_ns=venue_now_ns)
            self._pre2real[client_id] = client_id

    def resolve(self, client_id: str) -> str | None:
        """Map a submit-time id to the durable order id (None while queued)."""
        if client_id in self._orders:
            return client_id
        return self._pre2real.get(client_id)

    def attach_protection(self, entry_client_id: str, stop_price: float,
                          target_price: float | None) -> list[str]:
        """Independent reduce-only legs sized to filled qty (verified individually).

        Leg acceptance/rejection arrives via poll(); the caller must confirm
        each leg before treating the position as protected — the engine never
        assumes both legs exist.
        """
        real = self.resolve(entry_client_id) or entry_client_id
        order = self._orders.get(real)
        if order is None:
            if real in self._ioc_done:
                # 30MIN §4: arrival-cancelled IOC is known to the engine
                # with zero resting quantity — refused, not unknown.
                raise ValueError(
                    "protection attaches only to an entry with fills")
            raise KeyError(f"unknown entry_client_id: {entry_client_id!r}")
        filled = float(order.filled_qty)
        if filled <= 1e-12:
            raise ValueError("protection attaches only to an entry with fills")
        symbol = self._symbols[real]
        exit_side = "SELL" if order.side == OrderSide.BUY else "BUY"
        # V-008 §7: protection leg floors with the shared rule BEFORE
        # submit, so the recorded leg quantity is the executed quantity
        # (never silently less after venue-side flooring).
        protect_qty = self._quantize_qty(
            symbol, min(filled, float(order.quantity)))
        reservation = self._reservations.get(real)
        legs = [self.submit(EngineOrder(
            instrument=symbol, side=exit_side, qty=protect_qty,
            kind="STOP_MARKET", stop_price=stop_price, reduce_only=True,
            reservation_id=reservation, role="stop"))]
        if target_price is not None:
            try:
                legs.append(self.submit(EngineOrder(
                    instrument=symbol, side=exit_side, qty=protect_qty,
                    kind="TAKE_PROFIT_MARKET", stop_price=target_price,
                    reduce_only=True, reservation_id=reservation,
                    role="target")))
            except Exception as exc:
                # B#11 (paper mirror): roll the stop back; surface its
                # id when the rollback is ambiguous.
                try:
                    self.cancel(legs[0], "attach-rollback")
                except Exception:
                    try:
                        exc.partial_leg_id = legs[0]  # type: ignore[attr-defined]
                    except (AttributeError, TypeError):
                        pass
                raise
        return legs

    def cancel(self, client_order_id: str, reason: str) -> None:
        """Request cancellation; the verified outcome arrives via poll()."""
        if self._closed:
            raise RuntimeError("engine is closed")
        queued = [item for item in self._submit_queue if item[2] == client_order_id]
        if queued:
            _, cmd, _ = queued[0]
            self._submit_queue = [item for item in self._submit_queue
                                  if item[2] != client_order_id]
            self._journal("cancel-request", {"client_id": client_order_id,
                                            "reason": reason, "dropped": "queued"})
            # Tracked terminal truth (no EngineEvent: the submit never
            # materialized; Session's entry_dropped path covers release).
            self._journal("submitted", {
                "client_id": client_order_id,
                "instrument": cmd.instrument.upper(),
                "side": cmd.side, "qty": cmd.qty, "kind": cmd.kind.upper(),
                "role": cmd.role, "reservation_id": cmd.reservation_id,
                "dropped_queued": True})
            self._journal("terminal", {"client_id": client_order_id,
                                      "kind": "cancel",
                                      "reason": "dropped-queued"})
            self._bump(client_order_id)
            self._bump(client_order_id)
            self._dead[client_order_id] = {
                "state": "cancelled", "symbol": cmd.instrument.upper(),
                "qty": cmd.qty, "filled_qty": 0.0,
                "reservation_id": cmd.reservation_id, "role": cmd.role,
                "version": self._versions[client_order_id]}
            return
        order = self._orders.get(client_order_id)
        if order is None:
            raise KeyError(f"unknown client_order_id: {client_order_id!r}")
        self._journal("cancel-request", {"client_id": client_order_id, "reason": reason})
        self._client.cancel_order(CancelOrder(
            trader_id=self._trader_id, strategy_id=self._strategy_id,
            instrument_id=order.instrument_id, client_order_id=order.client_order_id,
            venue_order_id=order.venue_order_id, command_id=UUID4(),
            ts_init=self._clock.timestamp_ns(), client_id=ClientId(VENUE.value),
        ))

    def poll(self) -> list[EngineEvent]:
        """Non-blocking drain of simulator-produced events (never advances time)."""
        self._drain_pending()
        drained, self._pending = self._pending, []
        self.stats["pending_events"] = 0
        return drained

    def pop_events(self, max_events: int = 1000) -> list[EngineEvent]:
        """Bounded drain for the B1 seam (never advances time).

        The live session calls this per wake; max_events bounds the backlog
        served per wake so a burst cannot starve the strategy loop. ``poll``
        remains the unbounded drain for replay harnesses.
        """
        self._drain_pending()
        drained, self._pending = self._pending[:max_events], self._pending[max_events:]
        self.stats["pending_events"] = len(self._pending)
        return drained

    def open_orders(self) -> list[EngineOrderStatus]:
        """Currently-open/partial bot orders ONLY (contract v1 §2).

        A missing order here proves nothing about cancellation, fills,
        or flatness — use order_status() for tracked truth.
        """
        out = []
        for client_id, order in self._orders.items():
            state = self._status_of(order)
            if state not in ("open", "partial"):
                continue
            out.append(EngineOrderStatus(
                client_order_id=client_id, instrument=self._symbols[client_id],
                state=state, qty=float(order.quantity),
                filled_qty=float(order.filled_qty),
                reservation_id=self._reservations.get(client_id),
                role=self._roles.get(client_id, "entry"),
                version=self._versions.get(client_id, 0)))
        return out

    def order_status(self, client_order_id: str) -> EngineOrderStatus | None:
        """Tracked order truth incl. terminal + unknown (contract v1 §2).

        None ONLY when the id was never seen. Queued (not yet
        submitted) ids report open/version 0; restart-lost ids report
        unknown (see also lost_orders()).
        """
        order = self._orders.get(client_order_id)
        if order is not None:
            return EngineOrderStatus(
                client_order_id=client_order_id,
                instrument=self._symbols[client_order_id],
                state=self._status_of(order), qty=float(order.quantity),
                filled_qty=float(order.filled_qty),
                reservation_id=self._reservations.get(client_order_id),
                role=self._roles.get(client_order_id, "entry"),
                version=self._versions.get(client_order_id, 0))
        for _, cmd, queued_id in self._submit_queue:
            if queued_id == client_order_id:
                return EngineOrderStatus(
                    client_order_id=client_order_id,
                    instrument=cmd.instrument.upper(), state="open",
                    qty=float(cmd.qty), filled_qty=0.0,
                    reservation_id=cmd.reservation_id, role=cmd.role,
                    version=0)
        dead = self._dead.get(client_order_id)
        if dead is not None:
            return EngineOrderStatus(
                client_order_id=client_order_id,
                instrument=dead["symbol"], state=dead["state"],
                qty=float(dead["qty"]),
                filled_qty=float(dead["filled_qty"]),
                reservation_id=dead["reservation_id"], role=dead["role"],
                version=int(dead["version"]))
        if client_order_id in self._lost:
            detail = self._lost[client_order_id]
            return EngineOrderStatus(
                client_order_id=client_order_id,
                instrument=str(detail.get("instrument",
                                          detail.get("symbol", "?"))),
                state="unknown",
                qty=float(detail.get("qty", 0.0) or 0.0),
                filled_qty=self._recovered_fills.get(client_order_id, 0.0),
                reservation_id=detail.get("reservation_id"),
                role=str(detail.get("role", "entry")),
                version=self._versions.get(client_order_id, 0))
        return None

    def unknown_ids(self) -> tuple[str, ...]:
        """No venue lookup exists on paper: always empty (contract v1 §2).

        Restart-lost orders surface as order_status() "unknown" plus
        lost_orders(); there is no lookup that could resolve them.
        """
        return ()

    def filled_qty(self, client_order_id: str) -> float:
        order = self._orders.get(client_order_id)
        if order is not None:
            return float(order.filled_qty)
        dead = self._dead.get(client_order_id)
        if dead is not None:
            return float(dead["filled_qty"])
        return self._recovered_fills.get(client_order_id, 0.0)

    def set_exit_only(self, halted: bool, reason: str = "") -> None:
        """Reason-keyed halt: a recovered feed cannot lift a risk stop."""
        if halted:
            self._exit_only_reasons.add(reason or "unspecified")
        elif reason:
            self._exit_only_reasons.discard(reason)
        else:
            self._exit_only_reasons.clear()
        self._exit_only = bool(self._exit_only_reasons)
        self._journal("exit-only", {
            "halted": self._exit_only, "engaged": halted, "reason": reason,
            "reasons": sorted(self._exit_only_reasons)})

    def exit_only_reasons(self) -> tuple[str, ...]:
        return tuple(sorted(self._exit_only_reasons))

    def note_mark(self, instrument: str, price: float,
                ts_utc: datetime | None = None) -> None:
        """Record a valuation-only mark. NEVER executable (B2).

        Captured fills cross real bid/ask + liquidity from ``note_event``
        quotes/trades/depth only. A mid-mark can never become a fill price:
        with BBO 59999/60001 and mark 60000, a market buy fills at 60001
        (ask cross) and submit_protected(limit 60000) cancels (CEO probe).
        """
        if price > 0:
            self._marks[instrument.upper()] = price
            self._mark_ts[instrument.upper()] = ts_utc or self._now_utc()

    def valuation_mark(self, instrument: str) -> float | None:
        """Latest valuation-only mark (accounting/valuation use, never fills)."""
        return self._marks.get(instrument.upper())

    def valuation_mark_ts(self, instrument: str) -> datetime | None:
        """Observation time of the latest valuation mark (V-008 §7 mark age)."""
        return self._mark_ts.get(instrument.upper())

    def settled_funding_total(self, symbol: str | None = None) -> float:
        """Sum of emitted funding cash flows (V-008 §7 reconcile input).

        Covers exactly the EngineFunding events this engine emitted; the
        session ledger must agree (idempotent event ids, no double count).
        ``symbol=None`` totals across symbols.
        """
        if symbol is None:
            return sum(self._settled_funding.values())
        return self._settled_funding.get(symbol.upper(), 0.0)

    def latest_mark(self, instrument: str) -> float | None:
        return self.valuation_mark(instrument)

    def account_margin(self) -> tuple[float, float]:
        """(available_margin_usdt, free_margin_usdt) from the SIMULATED account.

        Balances move through nautilus' own portfolio/accounting path (fills
        post commissions/realized PnL; open exposure locks maintenance
        margin). available = free balance; free = free balance minus total
        maintenance requirement. Resting-stop order margin is NOT locked in
        the sim — risk-side sizing is the control there.
        """
        account = self._portfolio.account(VENUE)
        if account is None:  # pre-first-fill: nothing filed yet; report starting equity.
            account = self._exchange.get_account()
        free = float(account.balance_free(USDT))
        maint = float(account.total_margin_maint(USDT))
        return free, free - maint

    def account_snapshot(self) -> AccountSnapshot:
        """Authoritative sim positions/account/margin (contract v1 §2).

        Wallet/available come from the simulated margin account; positions
        from the netting cache with entry averages and marks. complete is
        False when an open position has no mark (margin balance unknown);
        consumers must treat incomplete snapshots as unknown, never flat.
        """
        account = self._portfolio.account(VENUE)
        if account is None:
            account = self._exchange.get_account()
        wallet = float(account.balance_total(USDT))
        available = float(account.balance_free(USDT))
        positions: list[AccountPosition] = []
        unrealized = 0.0
        complete = True
        for position in self._cache.positions_open():
            try:
                symbol = position.instrument_id.symbol.value
            except AttributeError:
                symbol = str(position.instrument_id).split(".")[0]
            symbol = symbol.upper()
            qty = float(position.signed_decimal_qty())
            entry = float(position.avg_px_open)
            mark = self._marks.get(symbol)
            if mark is None:
                bbo = self._bbo.get(symbol)
                if bbo is not None:
                    mark = (bbo[0] + bbo[1]) / 2.0
            if mark is None:
                prt = self._last_print.get(symbol)
                if prt is not None:
                    mark = prt[0]
            if mark is None:
                complete = False
            else:
                instrument = self._instruments.get(symbol)
                precision = (instrument.price_precision
                             if instrument is not None else 8)
                try:
                    unrealized += float(position.unrealized_pnl(
                        Price(mark, precision)))
                except Exception:
                    complete = False
                    mark = None
            positions.append(AccountPosition(
                instrument=symbol, qty=qty, entry_price=entry,
                mark_price=mark))
        return AccountSnapshot(
            wallet_equity_usdt=wallet,
            available_margin_usdt=available,
            margin_balance_usdt=(wallet + unrealized) if complete else None,
            positions=tuple(positions),
            asof_utc=self.now_utc,
            complete=complete)

    def note_event(self, event: dict[str, Any]) -> None:
        """Feed one NORMALIZED market-data event to the simulator.

        bookTicker/aggTrade/depth records map to nautilus ticks/deltas for
        true taker-cross fills; markPrice records refresh the valuation mark
        and funding terms (never executable).
        """
        from cryptobot.market_data.bridge import to_nautilus_ticks
        symbol = str(event.get("symbol", "")).upper()
        if not symbol:
            return
        if event.get("channel") == "markPrice":
            payload = event.get("payload", {})
            mark = payload.get("mark")
            if mark:
                self._marks[symbol] = float(mark)
                exch_ms = event.get("exchange_ts_ms")
                self._mark_ts[symbol] = (
                    datetime.fromtimestamp(exch_ms / 1000, tz=timezone.utc)
                    if isinstance(exch_ms, (int, float)) and exch_ms > 0
                    else self._now_utc())
            self._note_funding_terms(symbol, payload)
            self._settle_funding(symbol)
            return
        self._ensure_instrument(symbol)
        inst = self._instruments[symbol]
        for tick in to_nautilus_ticks([event],
                                      {symbol: (inst.price_precision, inst.size_precision)}):
            self.feed(tick)

    def _note_funding_terms(self, symbol: str, payload: dict[str, Any]) -> None:
        state = self._funding_terms.setdefault(symbol, {"rate": 0.0, "next_ms": 0,
                                                        "settled_ms": 0})
        rate = payload.get("funding_rate")
        if payload.get("funding_status") == "absent" or rate is None:
            # Explicitly unknown terms: invalidate so nothing settles on
            # stale rates or projected boundaries (E-009; no silent zero).
            # Live venue records carry no status and always assert a rate.
            state["rate"] = 0.0
            state["next_ms"] = 0
            return
        try:
            state["rate"] = float(rate)
            state["next_ms"] = int(payload.get("next_funding_ms", 0) or 0)
        except (TypeError, ValueError):
            pass  # malformed terms: keep the last known, never invent.

    def _settle_funding(self, symbol: str) -> None:
        """Emit one funding event when engine time crosses a settlement boundary."""
        state = self._funding_terms.get(symbol)
        if not state or not state["next_ms"]:
            return
        now_ms = self._clock.timestamp_ns() // 1_000_000
        if now_ms < state["next_ms"] or state["settled_ms"] >= state["next_ms"]:
            return
        funding_ms = state["next_ms"]
        state["settled_ms"] = funding_ms
        # No self-projection: the next boundary must be asserted by a newer
        # sourced record (per-minute live, per-minute archive). Settlement
        # past the last asserted boundary would invent terms (E-009).
        state["next_ms"] = 0
        position = self._cache.position(
            PositionId(f"{symbol}.{VENUE.value}-{self._strategy_id}"))
        qty = (float(position.signed_decimal_qty())
               if position is not None and position.is_open else 0.0)
        rate, ref = state["rate"], self._marks.get(symbol, 0.0)
        if qty == 0.0 or rate == 0.0 or ref <= 0:
            return  # flat/zero-rate/unpriced: no cash flow, nothing to book.
        amount = -qty * ref * rate  # rate>0: longs pay.
        if amount == 0.0:
            return
        ts_utc = datetime.fromtimestamp(funding_ms / 1000, tz=timezone.utc)
        self._settled_funding[symbol] = \
            self._settled_funding.get(symbol, 0.0) + amount
        # A#5: journal every settlement so recover() restores the
        # cumulative totals (else the first post-restart settlement
        # false-trips funding-mismatch and halts the run).
        self._journal("funding-settled", {"symbol": symbol, "amount": amount,
                                          "funding_ms": funding_ms})
        self._emit(EngineEvent(
            "funding",
            EngineFunding(event_id=f"funding:{symbol}:{funding_ms}",
                          instrument=symbol, amount=amount, ts_utc=ts_utc),
            ts_utc))
        self.stats["funding_events"] += 1
        self.stats["engine_events_total"] += 1

    def recover(self, handler: Any) -> None:
        """Rebuild tracking from the durable journal; adopt fills via _emit.

        Recovery-adopted fills (reservation or not — W1 item 7) flow
        through the bound handler as EngineEvents. Session applies
        idempotently by execution_id, so re-adoption is safe. Versions
        rebuild deterministically from journaled transitions; the fill
        seq resumes past journaled paper ids so post-restart
        execution_ids never collide.
        """
        if self.journal_path is None:
            raise RuntimeError("recover needs journal_path (no durable journal)")
        self.bind_sink(handler)
        path = self.journal_path
        if not path.exists():
            self._journal("recovered", {"fills_replayed": 0, "lost": []})
            return
        submitted: dict[str, dict[str, Any]] = {}
        terminal: dict[str, str] = {}
        fills: list[dict[str, Any]] = []
        halted: bool | None = None
        halt_reasons: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            event, detail = entry.get("event"), entry.get("detail", {})
            if event == "submitted":
                submitted[detail["client_id"]] = detail
                try:
                    self._seq = max(self._seq, int(detail["client_id"].split("-")[1]))
                except (IndexError, ValueError):
                    pass
            elif event == "fill":
                fills.append(detail)
                self._recovered_fills[detail["client_id"]] = (
                    self._recovered_fills.get(detail["client_id"], 0.0) + detail["qty"])
            elif event == "terminal":
                terminal[detail["client_id"]] = str(detail.get("kind", "cancel"))
            elif event == "exit-only":
                halted = bool(detail.get("halted"))
                if "reasons" in detail:
                    halt_reasons = set(detail["reasons"])
                elif halted:
                    # Legacy journals recorded only one aggregate bool.
                    # Preserve that hold with its last known reason.
                    halt_reasons = {detail.get("reason") or
                                    "recovered:exit-only"}
                else:
                    halt_reasons.clear()
            elif event == "funding-settled":
                # A#5: restore cumulative settled totals WITHOUT
                # re-emitting (the ledger already holds these via its
                # own journal/store replay; totals only feed reconcile).
                try:
                    symbol = str(detail["symbol"]).upper()
                    amount = float(detail["amount"])
                except (KeyError, TypeError, ValueError):
                    continue
                self._settled_funding[symbol] = \
                    self._settled_funding.get(symbol, 0.0) + amount
        for client_id, detail in submitted.items():
            if client_id not in terminal:
                self._lost[client_id] = detail  # sim orders never survive restart.
            else:
                # Terminal-without-sim: tracked truth survives the restart.
                kind = terminal[client_id]
                state = {"cancel": "cancelled", "reject": "rejected",
                         "expire": "expired"}.get(kind, "cancelled")
                self._dead[client_id] = {
                    "state": state, "symbol": detail.get("instrument",
                                                         detail.get("symbol", "?")),
                    "qty": detail.get("qty", 0.0), "filled_qty":
                        self._recovered_fills.get(client_id, 0.0),
                    "reservation_id": detail.get("reservation_id"),
                    "role": detail.get("role", "entry"), "version": 0}
        # Deterministic version rebuild: submitted + one per fill + terminal.
        for client_id in submitted:
            version = 1
            version += sum(1 for record in fills
                           if record["client_id"] == client_id)
            if client_id in terminal:
                version += 1
            self._versions[client_id] = version
            if client_id in self._dead:
                self._dead[client_id]["version"] = version
        # Fill-seq resync: never reuse a journaled paper execution id.
        for record in fills:
            exec_id = str(record.get("exec_id", ""))
            parts = exec_id.split("/")
            if len(parts) == 4 and parts[0] == "paper" and parts[1] == self._run_tag:
                try:
                    self._fill_seq = max(self._fill_seq, int(parts[3]))
                except ValueError:
                    pass
        for _ in range(self._seq):  # advance seeded RNG past journaled ids.
            # A#10: generation draws getrandbits(32) per id — recovery
            # must advance the IDENTICAL stream (64-bit draws diverge
            # it and break post-restart determinism).
            self._rng.getrandbits(32)
        if halted is not None:
            self._exit_only_reasons = halt_reasons
            self._exit_only = bool(halt_reasons)
        replayed = 0
        for record in fills:
            # At-least-once: re-push every journaled fill (reservation
            # or not); Session dedups by execution_id (contract v1 §3).
            moment = datetime.fromisoformat(record["ts_utc"])
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            self._emit(EngineEvent(
                "fill",
                EngineFill(
                    execution_id=record["exec_id"],
                    client_order_id=record["client_id"],
                    instrument=record["symbol"], side=record["venue_side"],
                    qty=record["qty"], price=record["price"],
                    fee=record["fee"], ts_utc=moment,
                    liquidity="taker"),
                moment))
            replayed += 1
        self._journal("recovered", {"fills_replayed": replayed,
                                    "lost": sorted(self._lost)})

    def lost_orders(self) -> list[str]:
        """Journaled-but-not-in-sim order ids (recover() findings)."""
        return sorted(self._lost)

    def close(self) -> None:
        self._closed = True

    # -- order visibility --------------------------------------------------
    def _status_of(self, order: Order) -> str:
        return _SEAM_STATE.get(int(order.status), "open")

    # -- market-data drive --------------------------------------------------
    @staticmethod
    def _restamp(data: Data, ts_init: int) -> Data:
        """Rebuild a tick/delta batch with receipt-time ts_init (ts_event kept)."""
        if isinstance(data, QuoteTick):
            return QuoteTick(data.instrument_id, data.bid_price, data.ask_price,
                             data.bid_size, data.ask_size,
                             ts_event=int(data.ts_event), ts_init=ts_init)
        if isinstance(data, TradeTick):
            return TradeTick(data.instrument_id, data.price, data.size,
                             data.aggressor_side, data.trade_id,
                             ts_event=int(data.ts_event), ts_init=ts_init)
        if isinstance(data, OrderBookDelta):
            return OrderBookDelta(data.instrument_id, data.action, data.order,
                                  data.flags, data.sequence,
                                  ts_event=int(data.ts_event), ts_init=ts_init)
        if isinstance(data, OrderBookDeltas):
            return OrderBookDeltas(
                data.instrument_id,
                [OrderBookDelta(d.instrument_id, d.action, d.order, d.flags,
                                d.sequence, ts_event=int(d.ts_event),
                                ts_init=ts_init) for d in data.deltas])
        return data

    def feed(self, data: Data) -> None:
        """Process one market-data object; engine time never moves backward.

        Lenient mode (live default): ticks older than the clock (receipt lag,
        cross-symbol interleave) are re-stamped to engine-now with ts_event
        preserved, so the book still updates and nautilus time stays
        monotonic. Strict mode (``strict_replay=True``): shuffled history
        fails closed with ValueError instead of silently reordering.
        """
        if self._closed:
            raise RuntimeError("engine is closed")
        now_ns = self._clock.timestamp_ns()
        ts_init = int(data.ts_init)
        if ts_init > now_ns:
            self._clock.set_time(ts_init)
        elif ts_init < now_ns:
            if self.strict_replay:
                raise ValueError(
                    f"strict replay: out-of-order ts_init {ts_init} < clock {now_ns}")
            data = self._restamp(data, now_ns)
            self.stats["restamped_ticks"] += 1
            ts_init = now_ns
        self._drain_pending()
        # CORR-EXEC: flush venue messages due STRICTLY before this tick
        # against the pre-tick (due-time-or-older) book, so a later tick
        # cannot price an earlier-due execution; cancels due before the
        # tick win instead of racing it. Same-timestamp ties keep tick
        # semantics (installed book), and with no reference ever seen the
        # first tick installs before anything resolves (wait model).
        if (self._bbo or self._last_print) and ts_init > 0:
            self._exchange.process(ts_init - 1)
        if isinstance(data, QuoteTick):
            self._track_bbo(data)
            self._exchange.process_quote_tick(data)
        elif isinstance(data, TradeTick):
            self._track_print(data)
            self._exchange.process_trade_tick(data)
        elif isinstance(data, OrderBookDelta):
            self._exchange.process_order_book_delta(data)
        elif isinstance(data, OrderBookDeltas):
            self._exchange.process_order_book_deltas(data)
        elif isinstance(data, Bar):
            self._exchange.process_bar(data)
        elif isinstance(data, Instrument):
            self._exchange.add_instrument(data)
        else:
            raise TypeError(f"unsupported feed data: {type(data).__name__}")
        self._exchange.process(ts_init)
        self._op_seq += 1
        self._sweep_ioc_remainders()
        for symbol in list(self._funding_terms):
            self._settle_funding(symbol)

    def _track_bbo(self, tick: QuoteTick) -> None:
        try:
            symbol = tick.instrument_id.symbol.value
        except AttributeError:
            symbol = str(tick.instrument_id).split(".")[0]
        self._bbo[symbol.upper()] = (float(tick.bid_price), float(tick.ask_price),
                                     float(tick.bid_size), float(tick.ask_size))

    def _track_print(self, tick: TradeTick) -> None:
        try:
            symbol = tick.instrument_id.symbol.value
        except AttributeError:
            symbol = str(tick.instrument_id).split(".")[0]
        self._last_print[symbol.upper()] = (float(tick.price),
                                            float(tick.size))

    def _ioc_marketable(self, symbol: str, side: OrderSide, cap: float) -> bool:
        """Whether a cap crosses EXECUTABLE liquidity (touch + size > 0).

        BBO when quoted, else the last print for trade-only flow. A touch
        with zero size (or no reference at all) is not executable: the IOC
        cancels at arrival rather than inventing a fill.
        """
        ref = self._bbo.get(symbol)
        if side == OrderSide.BUY:
            if ref:
                return ref[3] > 0 and cap >= ref[1]
            prt = self._last_print.get(symbol)
            return prt is not None and prt[1] > 0 and cap >= prt[0]
        if ref:
            return ref[2] > 0 and cap <= ref[0]
        prt = self._last_print.get(symbol)
        return prt is not None and prt[1] > 0 and cap <= prt[0]

    def _sweep_ioc_remainders(self) -> None:
        """Cancel live IOC remainders at the end of their accept opportunity.

        Every accept is followed by matching inside the same processing
        opportunity (pre-flush/data/post-flush within one feed, or one
        advance), so an IOC still live at the opportunity's end has had
        its one matching opportunity: the remainder cancels here and the
        cancel is due before the next opportunity's matching (pre-flush
        ordering). A fill executing before a sub-latency cancel lands
        stands as a genuine race. No tick-count bound is asserted: the
        rule is opportunity-counted (CORR-EXEC supersedes accept+1-tick).
        In practice nautilus enforces IOC natively at the matching tick
        (remainder canceled by the venue, tracked here via the terminal),
        so this send is a backstop for a tracked IOC the venue left live;
        the retire path is the live one.
        """
        for client_id in list(self._ioc_open):
            accepted = self._ioc_accepted.get(client_id)
            if accepted is None or accepted > self._op_seq:
                continue  # not yet accepted.
            order = self._orders.get(client_id)
            if order is None or self._status_of(order) not in ("open", "partial"):
                self._ioc_retire(client_id)
                continue
            if client_id in self._ioc_cancel_sent:
                continue  # cancel already in flight; await the terminal.
            self.cancel(client_id, "ioc-remainder")
            self._ioc_cancel_sent.add(client_id)
            self.stats["ioc_remainder_canceled"] += 1

    def _ioc_retire(self, client_id: str) -> None:
        self._ioc_open.pop(client_id, None)
        self._ioc_accepted.pop(client_id, None)
        self._ioc_cancel_sent.discard(client_id)
        self._ioc_done[client_id] = None
        while len(self._ioc_done) > 4096:
            self._ioc_done.pop(next(iter(self._ioc_done)))

    def advance_to(self, ts_utc: datetime) -> None:
        """Advance engine time without market data (drains latency-delayed commands).

        Nautilus evaluates stop/target triggers and GTD expiry on fed data
        ticks, not on bare time advance — expiry/trigger outcomes arrive with
        the next ``feed`` at or after their timestamp. This matches the
        backtest loop, where time always couples to data.
        """
        if self._closed:
            raise RuntimeError("engine is closed")
        ts_ns = dt_to_unix_nanos(ts_utc)
        if ts_ns < self._clock.timestamp_ns():
            raise ValueError("advance_to must be non-decreasing")
        self._clock.set_time(ts_ns)
        # Observation-time stamp for non-IOC drains (baseline behavior);
        # canonical LIMIT ignores it and resolves at due time in this same
        # advance (CORR-EXEC M1: immediate-or-cancel needs no tick).
        self._drain_pending(venue_now_ns=ts_ns)
        self._exchange.process(ts_ns)
        self._op_seq += 1
        self._sweep_ioc_remainders()
        for symbol in list(self._funding_terms):
            self._settle_funding(symbol)

    @property
    def now_utc(self) -> datetime:
        return unix_nanos_to_dt(self._clock.timestamp_ns())

    # -- simulator assumptions (S3: logged at startup, printed by doctor) ---
    @property
    def assumptions(self) -> tuple[str, ...]:
        return tuple([
            f"simulator=nautilus-SimulatedExchange equivalent-of-SandboxExecutionClient core "
            f"(matching/fills/fees all nautilus; no bot fill engine)",
            f"modeled delays: submit_delay_ms={self.submit_delay_ms} (pre-queue; "
            f"submit_immediate bypasses, exits-only) + fill_delay_ms={self.fill_delay_ms} "
            f"(venue latency, >0 enforced); submit_immediate bypasses both for one command",
            f"fees: taker={self.taker_bps:.1f}bps maker={self.maker_bps:.1f}bps off-instrument "
            f"(MakerTakerFeeModel; run-mode fees never zero; maker unused under taker-only)",
            "liquidity=taker-only: MARKET/STOP_MARKET/TAKE_PROFIT_MARKET cross the book; "
            "canonical LIMIT maps to nautilus LIMIT IOC under chronological "
            "execution (CORR-EXEC): feed/poll-drained commands enter the venue "
            "at modeled due time; messages due strictly before a tick flush "
            "against the pre-tick book, so a later tick cannot price an "
            "earlier-due execution and cancels due before a tick win it. "
            "Same-tick ties use the installed book; with no reference ever "
            "seen the first tick installs before anything resolves (wait "
            "model). Canonical LIMIT (nautilus IOC) ALWAYS resolves at "
            "modeled due time against the standing arrival book — "
            "immediate-or-cancel by definition, no tick required; "
            "advance-drained IOCs resolve in that same advance. Other kinds "
            "drained on advance keep observation-time stamping (next-tick "
            "resolution, baseline behavior). Nonmarketable IOCs (cap not "
            "crossing executable touch+size, BBO else last print, none when "
            "unquoted) cancel AT arrival and never submit. A submitted IOC "
            "fills up to executable size at the due-time opportunity and "
            "any remainder cancels there (opportunity-counted — no "
            "tick-count bound; the venue usually enforces natively, the "
            "adapter sweep retires tracking). A same-timestamp submit/cancel "
            "tie breaks at the venue and a fill executing before a "
            "sub-latency cancel lands stands as a genuine race. A maker flag "
            "on a tracked-IOC fill is the sub-tick artifact and books as "
            "taker (journaled ioc-artifact); any other non-taker fill fails "
            "closed. SPARSE-DATA MODEL (declared): gaps never invent ticks; "
            "an IOC with a standing book resolves at due time, without any "
            "reference it cancels at arrival.",
            "markets are GTC (never IOC-cancelled for thin prints): with quotes they "
            "resolve at the next tick against the pre-tick book when already due; "
            "on trade-only replay prints seed L1 size, the "
            "print size fills at-print and swept excess walks one tick adverse "
            "(nautilus empty-book model); queued submits that outlive expire_at_utc "
            "expire unsubmitted (queued-past-window)",
            "valuation-only marks (B2): note_mark records the reference mark for "
            "accounting only — it can NEVER produce a fill; all fills cross real "
            "bid/ask + liquidity from the quote/trade/depth feed (feed/note_event); "
            "submit_protected limit entries cancel when the touch cannot be lifted",
            "time model: engine clock advances on fed data/receipts only; poll/advance "
            "never invent market ticks; strict_replay=True fails closed on out-of-order "
            "replay input instead of restamping (live default stays receipt-lenient)",
            "deterministic ids (B1): client ids derive from random_seed's RNG stream "
            "(stable across same-seed runs); trade ids are venue FNV-1a; restart "
            "replays the RNG stream past journaled ids",
            "funding (B2): markPrice terms feed boundary settlements from open "
            "cache positions as pure rate x notional (no venue settlement tax "
            "exists or is applied); only venue-asserted boundaries settle "
            "(no self-projection past the last record); absent/unknown terms "
            "invalidate (settle nothing, never zero); unpriced/flat/zero-rate "
            "settlements book nothing",
            "margins (B2): account_margin reads the simulated MarginAccount filed "
            "through nautilus' own portfolio path (update_order/update_account on "
            "each fill); leverage is engine-owned (matches the risk cap)",
            "bounds (B10): max_queued_submits/max_pending_events fail closed with "
            "OverflowError so bursts surface instead of growing unbounded",
            "instruments auto-register from live venue filters (PRICE_FILTER/LOT_SIZE/"
            "MIN_NOTIONAL) on first sight; qty floored to step, prices rounded to tick, "
            "REST failure fails closed (filters never invented)",
            "reduce-only honored by the venue (use_reduce_only=True) against ExecutionEngine-"
            "equivalent netting positions filed from simulator fills; stop/target legs are "
            "independent orders (support_contingent_orders=False; no OCO assumption)",
            "stops/targets reject when the trigger is already in the market "
            "(reject_stop_orders=True); attach_protection legs verify via poll, never assumed",
            "fills reach Session exactly-once-accounted (at-least-once "
            "push/replay, Session dedups by namespaced execution_id); "
            "forecast costs and booked fill costs are never double-charged",
            "contract v1: open_orders is open/partial only (tracked truth via "
            "order_status incl. terminal/unknown + monotonic versions); "
            "execution ids are paper/{run}/{sym}/{seq} (venue trade id kept "
            "in the journal); bind_sink(handler) pushes EVERY emission to a "
            "callable Session handler, poll() drains pre-binding leftovers; "
            "account_snapshot() is authoritative positions/margin",
            "restart: sim orders never survive; recover() rebuilds tracking from the "
            "journal, replays unpropagated fills, marks the rest lost-on-restart (never "
            "assumed filled/cancelled/flat)",
            "paper mode instantiates no Binance live execution client (R0, tested)",
            "receipt-time processing: ticks older than the engine clock "
            "(mark-quote skew, cross-symbol interleave) are re-stamped to "
            "engine-now with ts_event preserved; the book updates, time stays "
            "monotonic; ordered replay passes through untouched",
        ])

    def doctor(self) -> str:
        lines = [f"paper-engine {ENGINE_VERSION} assumptions:"] + [
            f"  - {item}" for item in self.assumptions
        ]
        return "\n".join(lines) + "\n"

    # -- internals ------------------------------------------------------------
    def _journal(self, event: str, detail: dict[str, Any]) -> None:
        if self.journal_path is None:
            return
        with self.journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts_utc": self.now_utc.isoformat(),
                "event": event,
                "detail": detail,
            }) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _enqueue(self, event: EngineEvent) -> None:
        self.stats["pending_events"] = len(self._pending)
        if len(self._pending) >= self.max_pending_events:
            raise OverflowError(
                f"pending event queue full ({self.max_pending_events}); "
                "poll() the engine to drain it")
        self._pending.append(event)
        self.stats["pending_events"] = len(self._pending)

    def _on_order_event(self, event: OrderEvent) -> None:
        # Mirror ExecutionEngine's apply/filing role for local state (fills and
        # cancels still originate in the simulator): without this, tracked
        # orders never leave SUBMITTED and cancels/expiry cannot resolve.
        coid = getattr(event, "client_order_id", None)
        order = self._orders.get(coid.value if coid is not None else "")
        if order is not None:
            order.apply(event)
        if isinstance(event, OrderAccepted) and order is not None:
            coid = event.client_order_id.value
            if coid in self._ioc_open and coid not in self._ioc_accepted:
                self._ioc_accepted[coid] = self._op_seq
        if isinstance(event, OrderFilled):
            self._file_fill(event)
        mapped = self._translate(event)
        if mapped is not None:
            kind, payload = mapped.kind, mapped.payload
            if kind == "fill":
                assert isinstance(payload, EngineFill)
                self._journal("fill", {
                    "exec_id": payload.execution_id, "client_id": payload.client_order_id,
                    "reservation_id": self._reservations.get(payload.client_order_id),
                    "symbol": payload.instrument, "venue_side": payload.side,
                    "qty": payload.qty, "price": payload.price, "fee": payload.fee,
                    "ts_utc": payload.ts_utc.isoformat(),
                    "venue_trade_id": event.trade_id.value,
                    # Execution vs report delivery stay separate (30MIN §4):
                    # ts_event is venue execution, ts_utc is report arrival.
                    "exec_ts_utc": unix_nanos_to_dt(
                        event.ts_event).replace(
                            tzinfo=timezone.utc).isoformat()})
                self._bump(payload.client_order_id)
                self._emit(mapped)
            else:
                self._journal("terminal", {"client_id": getattr(payload, "client_order_id", ""),
                                          "kind": kind,
                                          "reason": getattr(payload, "reason", "")})
                self._bump(getattr(payload, "client_order_id", ""))
                self._emit(mapped)
            self.stats["engine_events_total"] += 1

    def _file_fill(self, fill: OrderFilled) -> None:
        # ExecutionEngine-equivalent margin-account filing (netting OMS), same
        # order as nautilus' own _handle_order_fill: balances first (balance
        # PnL needs the pre-fill cached position), then position update with
        # PositionOpened/Changed/Closed events into the portfolio so margins
        # track open exposure. Fills originate in the simulator; this only
        # files them where the venue/portfolio expect. PnL book of record
        # stays our ledger.
        # (position_id is readonly from Python, hence the stamped copy.)
        instrument = self._instruments[fill.instrument_id.symbol.value]
        pid = PositionId(f"{fill.instrument_id}-{fill.strategy_id}")
        stamped = self._stamp_position(fill, pid)
        self._portfolio.update_order(stamped)
        position = self._cache.position(pid)
        if position is None or position.is_closed:
            if position is not None:
                self._cache.snapshot_position(position)  # NETTING reopen cycle.
            position = Position(instrument, stamped)
            self._cache.add_position(position, OmsType.NETTING)
            self._portfolio.update_position(PositionOpened.create(
                position, stamped, UUID4(), self._clock.timestamp_ns()))
        elif (position.is_opposite_side(stamped.order_side)
                and stamped.last_qty > position.quantity):
            self._flip_position(instrument, position, stamped)
        else:
            position.apply(stamped)
            self._cache.update_position(position)
            event_cls = PositionClosed if position.is_closed else PositionChanged
            self._portfolio.update_position(event_cls.create(
                position, stamped, UUID4(), self._clock.timestamp_ns()))

    def _flip_position(self, instrument: Instrument, position: Position,
                       fill: OrderFilled) -> None:
        # Over-close split (nautilus _flip_position, NETTING): close the
        # original position with its share of commission, open the flipped
        # remainder under the same netting ID.
        difference = fill.last_qty - position.quantity
        fill_percent = position.quantity / fill.last_qty
        commission1 = Money(fill.commission * fill_percent, fill.commission.currency)
        commission2 = fill.commission - commission1
        split1 = self._stamp_position(fill, fill.position_id,
                                      last_qty=position.quantity,
                                      commission=commission1, event_id=fill.id)
        position.apply(split1)
        self._cache.update_position(position)
        self._portfolio.update_position(PositionClosed.create(
            position, split1, UUID4(), self._clock.timestamp_ns()))
        self._cache.snapshot_position(position)
        if float(difference) == 0.0:
            return
        split2 = self._stamp_position(fill, fill.position_id, last_qty=difference,
                                      commission=commission2, event_id=UUID4())
        flipped = Position(instrument, split2)
        self._cache.add_position(flipped, OmsType.NETTING)
        self._portfolio.update_position(PositionOpened.create(
            flipped, split2, UUID4(), self._clock.timestamp_ns()))

    @staticmethod
    def _stamp_position(fill: OrderFilled, position_id: PositionId,
                        last_qty: Quantity | None = None,
                        commission: Money | None = None,
                        event_id: UUID4 | None = None) -> OrderFilled:
        return OrderFilled(
            trader_id=fill.trader_id, strategy_id=fill.strategy_id,
            instrument_id=fill.instrument_id, client_order_id=fill.client_order_id,
            venue_order_id=fill.venue_order_id, account_id=fill.account_id,
            trade_id=fill.trade_id, position_id=position_id, order_side=fill.order_side,
            order_type=fill.order_type, last_qty=last_qty or fill.last_qty,
            last_px=fill.last_px, currency=fill.currency,
            commission=commission or fill.commission,
            liquidity_side=fill.liquidity_side, event_id=event_id or UUID4(),
            ts_event=fill.ts_event, ts_init=fill.ts_init, info=dict(fill.info or {}),
        )

    def _translate(self, event: OrderEvent) -> EngineEvent | None:
        ts_utc = unix_nanos_to_dt(int(event.ts_event)).replace(tzinfo=timezone.utc)
        coid = event.client_order_id.value
        symbol = self._symbols.get(coid, event.instrument_id.symbol.value)
        if isinstance(event, OrderFilled):
            if event.liquidity_side != LiquiditySide.TAKER:
                order = self._orders.get(coid)
                tif = getattr(order, "time_in_force", None)
                tracked = (coid in self._ioc_open or coid in self._ioc_done)
                if tif == TimeInForce.IOC and tracked:
                    # No-rest enforcement (30MIN §4, SUPERSEDES the F-W1B1
                    # blanket relabel): tracked IOCs are canceled past
                    # their accept tick, so a live one never rests; a maker
                    # flag on such a fill is definitionally the simulator
                    # artifact (sub-tick cross), booked as a take with
                    # taker costs. Anything else fails closed as before.
                    self.stats["ioc_artifact_corrected"] += 1
                    self._journal("ioc-artifact", {
                        "client_id": coid, "from": "maker", "to": "taker",
                        "reason": "no-rest-ioc-subtick-artifact"})
                else:
                    raise RuntimeError(
                        f"non-taker fill for {coid}: {event.liquidity_side} "
                        f"(taker-only model; refusing to book mislabeled costs)")
            self._fill_seq += 1
            # B#9: price the pessimistic drift NOW (book evidence is
            # freshest at fill time): BBO single-level walk, last-print
            # fallback, else flat params cost (no book evidence).
            drift_bps = self._fill_drift_bps(
                symbol,
                "BUY" if event.order_side == OrderSide.BUY else "SELL",
                float(event.last_qty), float(event.last_px))
            return EngineEvent("fill", EngineFill(
                execution_id=f"paper/{self._run_tag}/{symbol}/{self._fill_seq:06d}",
                client_order_id=coid,
                instrument=symbol,
                side="BUY" if event.order_side == OrderSide.BUY else "SELL",
                qty=float(event.last_qty),
                price=float(event.last_px),
                fee=float(event.commission),
                ts_utc=ts_utc,
                liquidity="taker",
                slippage_drift_bps=drift_bps,
            ), ts_utc)
        if isinstance(event, OrderCanceled):
            return EngineEvent("cancel", EngineCancel(
                coid, symbol, "venue-canceled", ts_utc), ts_utc)
        if isinstance(event, OrderCancelRejected):
            return EngineEvent("reject", EngineReject(
                coid, symbol, f"cancel-rejected:{event.reason}", ts_utc), ts_utc)
        if isinstance(event, OrderRejected):
            return EngineEvent("reject", EngineReject(
                coid, symbol, event.reason, ts_utc), ts_utc)
        if isinstance(event, OrderExpired):
            return EngineEvent("expire", EngineExpire(
                coid, symbol, "gtd-expired", ts_utc), ts_utc)
        return None  # submitted/accepted/triggered/pending-update: internal state only.
