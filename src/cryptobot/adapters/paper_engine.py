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
    EngineCancel,
    EngineEvent,
    EngineExpire,
    EngineFill,
    EngineFunding,
    EngineOrder,
    EngineOrderStatus,
    EngineReject,
)
from cryptobot.market_data.discovery import FAPI_BASE_URL, urllib_json_get

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

_FUNDING_INTERVAL_MS = 8 * 3600 * 1000


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
        fill_delay_ms: int = 50,
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
    ) -> None:
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
        self._sink = outcome_sink
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
            fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0,
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
        self._funding_terms: dict[str, dict[str, Any]] = {}  # symbol -> rate/next/settled.
        self._pending: list[EngineEvent] = []
        self._submit_queue: list[tuple[int, EngineOrder, str]] = []  # (due_ns, cmd, id).
        self._pre2real: dict[str, str] = {}  # queue id -> durable id (same value here).
        self._lost: dict[str, dict[str, Any]] = {}  # recover(): journaled but not in sim.
        self._recovered_fills: dict[str, float] = {}  # recover(): client id -> filled qty.
        self._seq = 0
        self._closed = False
        self._exit_only = False
        self.stats: dict[str, int] = {  # engine-owned counters (B1/B10).
            "engine_events_total": 0,
            "pending_events": 0,
            "queued_submits": 0,
            "restamped_ticks": 0,
            "funding_events": 0,
        }
        if self.journal_path is not None:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._msgbus.register(endpoint="ExecEngine.process", handler=self._on_order_event)

    # -- sink ------------------------------------------------------------------
    def bind_sink(self, outcome_sink: Any) -> None:
        """Bind the risk outcome sink; replays any unpropagated journaled fills."""
        self._sink = outcome_sink
        self._replay_unpropagated(outcome_sink)

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
        """Floor to the LOT_SIZE step (venue behavior); reject dust below minQty."""
        step = self._filters[symbol.upper()]["step"]
        quantized = math.floor(qty / step * (1 + 1e-9)) * step
        quantized = round(quantized, 12)
        if quantized <= 0:
            raise ValueError(f"qty {qty} below LOT_SIZE step {step} for {symbol}")
        if quantized < self._filters[symbol.upper()]["min_qty"]:
            raise ValueError(f"qty {quantized} below venue minQty for {symbol}")
        return quantized

    def _round_tick(self, symbol: str, price: float) -> float:
        tick = self._filters[symbol.upper()]["tick"]
        return round(round(price / tick) * tick, 12)

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
        """Submit bypassing modeled delays. Exits/flatten ONLY, never entries."""
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
            return self._submit_now(cmd, client_id)
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

    def _submit_now(self, cmd: EngineOrder, client_id: str) -> str:
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
            assert cmd.price is not None
            order = self._factory.limit(
                instrument_id=iid, order_side=side,
                quantity=Quantity(qty, instrument.size_precision),
                price=Price(self._round_tick(symbol, cmd.price),
                            instrument.price_precision),
                time_in_force=TimeInForce.IOC,
                reduce_only=cmd.reduce_only, client_order_id=coid,
            )
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
        self._client.submit_order(SubmitOrder(
            trader_id=self._trader_id, strategy_id=self._strategy_id, order=order,
            command_id=UUID4(), ts_init=self._clock.timestamp_ns(),
            client_id=ClientId(VENUE.value),
        ))
        self._journal("submitted", {"client_id": client_id, "instrument": symbol,
                                   "side": cmd.side, "qty": qty, "kind": kind,
                                   "role": cmd.role,
                                   "reservation_id": cmd.reservation_id})
        return client_id

    def _drain_pending(self) -> None:
        now_ns = self._clock.timestamp_ns()
        due_now = [item for item in self._submit_queue if item[0] <= now_ns]
        self._submit_queue = [item for item in self._submit_queue if item[0] > now_ns]
        # Stable FIFO per due tick: same-tick submits (entry + protection
        # legs) must never compare EngineOrder (integration fix: TypeError
        # crashed R2 on its first live protection attach).
        for _, cmd, client_id in sorted(due_now, key=lambda item: item[0]):
            if (cmd.expire_at_utc is not None
                    and now_ns > dt_to_unix_nanos(cmd.expire_at_utc)):
                # Window passed while queued: expire, never submit late.
                ts_utc = unix_nanos_to_dt(now_ns).replace(tzinfo=timezone.utc)
                self._journal("terminal", {"client_id": client_id, "kind": "expire",
                                          "reason": "queued-past-window"})
                self._enqueue(EngineEvent(
                    "expire", EngineExpire(client_id, cmd.instrument.upper(),
                                           "queued-past-window", ts_utc), ts_utc))
                continue
            self._submit_now(cmd, client_id)
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
            raise KeyError(f"unknown entry_client_id: {entry_client_id!r}")
        filled = float(order.filled_qty)
        if filled <= 1e-12:
            raise ValueError("protection attaches only to an entry with fills")
        symbol = self._symbols[real]
        exit_side = "SELL" if order.side == OrderSide.BUY else "BUY"
        protect_qty = min(filled, float(order.quantity))
        reservation = self._reservations.get(real)
        legs = [self.submit(EngineOrder(
            instrument=symbol, side=exit_side, qty=protect_qty,
            kind="STOP_MARKET", stop_price=stop_price, reduce_only=True,
            reservation_id=reservation, role="stop"))]
        if target_price is not None:
            legs.append(self.submit(EngineOrder(
                instrument=symbol, side=exit_side, qty=protect_qty,
                kind="TAKE_PROFIT_MARKET", stop_price=target_price,
                reduce_only=True, reservation_id=reservation, role="target")))
        return legs

    def cancel(self, client_order_id: str, reason: str) -> None:
        """Request cancellation; the verified outcome arrives via poll()."""
        if self._closed:
            raise RuntimeError("engine is closed")
        queued = [item for item in self._submit_queue if item[2] == client_order_id]
        if queued:
            self._submit_queue = [item for item in self._submit_queue
                                  if item[2] != client_order_id]
            self._journal("cancel-request", {"client_id": client_order_id,
                                            "reason": reason, "dropped": "queued"})
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
        """Point-in-time order snapshot for flat inference (no venue reads)."""
        out = []
        for client_id, order in self._orders.items():
            state = self._status_of(order)
            out.append(EngineOrderStatus(
                client_order_id=client_id, instrument=self._symbols[client_id],
                state=state, qty=float(order.quantity),
                filled_qty=float(order.filled_qty),
                reservation_id=self._reservations.get(client_id),
                role=self._roles.get(client_id, "entry")))
        return out

    def filled_qty(self, client_order_id: str) -> float:
        order = self._orders.get(client_order_id)
        if order is not None:
            return float(order.filled_qty)
        return self._recovered_fills.get(client_order_id, 0.0)

    def set_exit_only(self, halted: bool, reason: str = "") -> None:
        """Level-triggered halt: entries refuse while set; exits still submit."""
        self._exit_only = halted
        self._journal("exit-only", {"halted": halted, "reason": reason})

    def note_mark(self, instrument: str, price: float) -> None:
        """Record a valuation-only mark. NEVER executable (B2).

        Captured fills cross real bid/ask + liquidity from ``note_event``
        quotes/trades/depth only. A mid-mark can never become a fill price:
        with BBO 59999/60001 and mark 60000, a market buy fills at 60001
        (ask cross) and submit_protected(limit 60000) cancels (CEO probe).
        """
        if price > 0:
            self._marks[instrument.upper()] = price

    def valuation_mark(self, instrument: str) -> float | None:
        """Latest valuation-only mark (accounting/valuation use, never fills)."""
        return self._marks.get(instrument.upper())

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
        try:
            state["rate"] = float(payload.get("funding_rate", 0.0) or 0.0)
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
        state["next_ms"] = funding_ms + _FUNDING_INTERVAL_MS
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
        self._enqueue(EngineEvent(
            "funding",
            EngineFunding(event_id=f"funding:{symbol}:{funding_ms}",
                          instrument=symbol, amount=amount, ts_utc=ts_utc),
            ts_utc))
        self.stats["funding_events"] += 1
        self.stats["engine_events_total"] += 1

    def recover(self, outcome_sink: Any) -> None:
        """Rebuild tracking from the durable journal; replay fills to the sink."""
        if self.journal_path is None:
            raise RuntimeError("recover needs journal_path (no durable journal)")
        self._sink = outcome_sink
        path = self.journal_path
        if not path.exists():
            self._journal("recovered", {"fills_replayed": 0, "lost": []})
            return
        submitted: dict[str, dict[str, Any]] = {}
        terminal: set[str] = set()
        fills: list[dict[str, Any]] = []
        propagated: set[str] = set()
        halted: bool | None = None
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
                terminal.add(detail["client_id"])
            elif event == "delta-propagated":
                propagated.add(detail["exec_id"])
            elif event == "exit-only":
                halted = bool(detail.get("halted"))
        for client_id, detail in submitted.items():
            if client_id not in terminal:
                self._lost[client_id] = detail  # sim orders never survive restart.
        for _ in range(self._seq):  # advance seeded RNG past journaled ids.
            self._rng.getrandbits(64)
        if halted is not None:
            self._exit_only = halted
        replayed = 0
        if hasattr(outcome_sink, "note_fill_delta"):
            for record in fills:
                if record["exec_id"] in propagated or not record["reservation_id"]:
                    continue
                outcome_sink.note_fill_delta(
                    record["reservation_id"], record["exec_id"], record["symbol"],
                    record["venue_side"], record["qty"], record["price"],
                    record["fee"], record["ts_utc"])
                propagated.add(record["exec_id"])
                self._journal("delta-propagated", {"exec_id": record["exec_id"]})
                replayed += 1
        self._journal("recovered", {"fills_replayed": replayed,
                                    "lost": sorted(self._lost)})

    def lost_orders(self) -> list[str]:
        """Journaled-but-not-in-sim order ids (recover() findings)."""
        return sorted(self._lost)

    def close(self) -> None:
        self._closed = True

    # -- order visibility --------------------------------------------------
    def order_status(self, client_order_id: str) -> str:
        """Local applied nautilus state name of a tracked order (runtime use)."""
        order = self._orders.get(client_order_id)
        if order is None:
            raise KeyError(f"unknown client_order_id: {client_order_id!r}")
        return OrderStatus(int(order.status)).name

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
        if isinstance(data, QuoteTick):
            self._exchange.process_quote_tick(data)
        elif isinstance(data, TradeTick):
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
        for symbol in list(self._funding_terms):
            self._settle_funding(symbol)

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
        self._drain_pending()
        self._exchange.process(ts_ns)
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
            "canonical LIMIT maps to nautilus LIMIT IOC (marketable-or-cancel, keeps price "
            "protection); resting GTC limits unsupported (no queue model); non-taker fills "
            "fail closed",
            "markets are GTC (never IOC-cancelled for thin prints): with quotes they "
            "resolve on the next tick; on trade-only replay prints seed L1 size, the "
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
            "funding (B2): markPrice terms feed 8h-boundary settlements from open "
            "cache positions as pure rate x notional (no venue settlement tax "
            "exists or is applied); unpriced/flat/zero-rate settlements book "
            "nothing",
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
            "fills propagate to the bound outcome sink exactly-once-accounted "
            "(journaled delta-propagated; at-least-once replay on bind/recover, sink dedups); "
            "forecast costs and booked fill costs are never double-charged",
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
                    "ts_utc": payload.ts_utc.isoformat()})
                self._enqueue(mapped)
                self._propagate_live(payload)
            else:
                self._journal("terminal", {"client_id": getattr(payload, "client_order_id", ""),
                                          "kind": kind,
                                          "reason": getattr(payload, "reason", "")})
                self._enqueue(mapped)
            self.stats["engine_events_total"] += 1

    def _propagate_live(self, fill: EngineFill) -> None:
        """Propagate a live fill to the bound sink (exactly-once-accounted)."""
        sink, reservation = self._sink, self._reservations.get(fill.client_order_id)
        if sink is None or not hasattr(sink, "note_fill_delta") or not reservation:
            return  # unbound or reservation-less: recover()/bind_sink() replays later.
        sink.note_fill_delta(reservation, fill.execution_id, fill.instrument,
                             fill.side, fill.qty, fill.price, fill.fee,
                             fill.ts_utc.isoformat())
        self._journal("delta-propagated", {"exec_id": fill.execution_id})

    def _replay_unpropagated(self, sink: Any) -> None:
        """Replay journaled fills the sink never acknowledged (bind-time catch-up)."""
        if (sink is None or not hasattr(sink, "note_fill_delta")
                or self.journal_path is None or not self.journal_path.exists()):
            return
        fills: list[dict[str, Any]] = []
        propagated: set[str] = set()
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("event") == "fill":
                fills.append(entry["detail"])
            elif entry.get("event") == "delta-propagated":
                propagated.add(entry["detail"]["exec_id"])
        for record in fills:
            if record["exec_id"] in propagated or not record["reservation_id"]:
                continue
            sink.note_fill_delta(record["reservation_id"], record["exec_id"],
                                 record["symbol"], record["venue_side"], record["qty"],
                                 record["price"], record["fee"], record["ts_utc"])
            self._journal("delta-propagated", {"exec_id": record["exec_id"]})

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
                raise RuntimeError(
                    f"non-taker fill for {coid}: {event.liquidity_side} "
                    f"(taker-only model; refusing to book mislabeled costs)")
            return EngineEvent("fill", EngineFill(
                execution_id=event.trade_id.value,
                client_order_id=coid,
                instrument=symbol,
                side="BUY" if event.order_side == OrderSide.BUY else "SELL",
                qty=float(event.last_qty),
                price=float(event.last_px),
                fee=float(event.commission),
                ts_utc=ts_utc,
                liquidity="taker",
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
