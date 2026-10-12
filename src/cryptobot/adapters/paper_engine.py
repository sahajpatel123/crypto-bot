"""Nautilus-backed paper execution engine (Worker 2, E-007, S3 seam).

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
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from nautilus_trader.backtest.engine import SimulatedExchange
from nautilus_trader.backtest.execution_client import BacktestExecClient
from nautilus_trader.backtest.models import FillModel, LatencyModel, MakerTakerFeeModel
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import MessageBus, TestClock
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
    OrderCanceled,
    OrderCancelRejected,
    OrderEvent,
    OrderExpired,
    OrderFilled,
    OrderRejected,
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
    EngineOrder,
    EngineOrderStatus,
    EngineReject,
)
from cryptobot.market_data.discovery import FAPI_BASE_URL, urllib_json_get

__all__ = ["ENGINE_VERSION", "NautilusPaperEngine"]

ENGINE_VERSION = "e007-4"

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

# Nominal quote size (base units) for mark-quote ticks. The mark carries no
# size; this labeled nominal lets modeled fills resolve while the quote feed
# (with real sizes) stays the size-realistic path.
_MARK_QUOTE_SIZE = 1.0


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
    ) -> None:
        if taker_bps <= 0:
            raise ValueError("taker_bps must be > 0 (run-mode fees are never zero)")
        if fill_delay_ms <= 0:
            raise ValueError("fill_delay_ms must be > 0 (S3 nonzero submission/fill delay)")
        if submit_delay_ms < 0:
            raise ValueError("submit_delay_ms must be >= 0")
        if starting_balance_usdt <= 0:
            raise ValueError("starting_balance_usdt must be > 0")
        self._sink = outcome_sink
        self.taker_bps = float(taker_bps)
        self.maker_bps = float(taker_bps if maker_bps is None else maker_bps)
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.submit_delay_ms = int(submit_delay_ms)
        self.fill_delay_ms = int(fill_delay_ms)
        self.journal_path = Path(journal_path) if journal_path else None
        self._rest_get = rest_get or urllib_json_get
        self._clock = TestClock()
        self._trader_id = TraderId(trader_id)
        self._strategy_id = StrategyId(strategy_id)
        self._prefix = client_id_prefix
        self._msgbus = MessageBus(trader_id=self._trader_id, clock=self._clock)
        self._cache = Cache(database=None)
        self._portfolio = Portfolio(msgbus=self._msgbus, clock=self._clock, cache=self._cache)
        self._exchange = SimulatedExchange(
            venue=VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(starting_balance_usdt, USDT)],
            base_currency=USDT,
            default_leverage=Decimal(1),
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
        self._pending: list[EngineEvent] = []
        self._submit_queue: list[tuple[int, EngineOrder, str]] = []  # (due_ns, cmd, id).
        self._pre2real: dict[str, str] = {}  # queue id -> durable id (same value here).
        self._lost: dict[str, dict[str, Any]] = {}  # recover(): journaled but not in sim.
        self._recovered_fills: dict[str, float] = {}  # recover(): client id -> filled qty.
        self._seq = 0
        self._closed = False
        self._exit_only = False
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
        )
        self._exchange.add_instrument(instrument)
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
    def submit(self, cmd: EngineOrder) -> str:
        """Submit (modeled submit-delay may apply); returns id for resolve()."""
        if self._closed:
            raise RuntimeError("engine is closed")
        if self._exit_only and cmd.role == "entry":
            raise PermissionError("exit-only mode refuses new entries")
        self._validate(cmd)
        self._seq += 1
        client_id = f"{self._prefix}-{self._seq:06d}-{uuid.uuid4().hex[:8]}"
        if self.submit_delay_ms > 0:
            due = self._clock.timestamp_ns() + self.submit_delay_ms * 1_000_000
            self._submit_queue.append((due, cmd, client_id))
            self._drain_pending()
            return client_id
        return self._submit_now(cmd, client_id)

    def submit_immediate(self, cmd: EngineOrder) -> str:
        """Submit bypassing modeled delays. Exits/flatten ONLY, never entries."""
        if cmd.role == "entry":
            raise ValueError("submit_immediate is exits-only; entries use submit()")
        if self._closed:
            raise RuntimeError("engine is closed")
        self._validate(cmd)
        self._seq += 1
        client_id = f"{self._prefix}-{self._seq:06d}-{uuid.uuid4().hex[:8]}"
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
        use_gtd = cmd.expire_at_utc is not None and kind != "MARKET"
        tif = TimeInForce.GTD if use_gtd else TimeInForce.GTC
        if kind == "MARKET":
            order = self._factory.market(
                instrument_id=iid, order_side=side,
                quantity=Quantity(qty, instrument.size_precision),
                time_in_force=TimeInForce.IOC,
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
        """Record the session mark AND drive the sim (mark-quote model).

        The mark feeds the simulator as a zero-spread quote at engine-now, so
        live-paper orders resolve against the same fill basis the session
        prices (reference-equivalent basis; labeled assumption). Real
        spread/size realism comes from the quote feed (``feed``/``note_event``).
        """
        if price <= 0:
            return
        symbol = instrument.upper()
        self._marks[symbol] = price
        inst = self._ensure_instrument(symbol)
        px = self._round_tick(symbol, price)
        ts_ns = self._live_now_ns()
        self._clock.set_time(ts_ns)
        tick = QuoteTick(
            instrument_id=self.instrument_id(symbol),
            bid_price=Price(px, inst.price_precision),
            ask_price=Price(px, inst.price_precision),
            bid_size=Quantity(_MARK_QUOTE_SIZE, inst.size_precision),
            ask_size=Quantity(_MARK_QUOTE_SIZE, inst.size_precision),
            ts_event=ts_ns, ts_init=ts_ns,
        )
        self._drain_pending()
        self._exchange.process_quote_tick(tick)
        self._exchange.process(ts_ns)

    def note_event(self, event: dict[str, Any]) -> None:
        """Feed one NORMALIZED market-data event to the simulator (additive).

        Not in the canonical protocol (yet): maps bookTicker/aggTrade/depth
        records to nautilus ticks/deltas for true taker-cross fills. markPrice
        records only refresh the reference mark. Proposed session adoption:
        ``if hasattr(engine, "note_event"): engine.note_event(event)``.
        """
        from cryptobot.market_data.bridge import to_nautilus_ticks
        symbol = str(event.get("symbol", "")).upper()
        if not symbol:
            return
        if event.get("channel") == "markPrice":
            mark = event.get("payload", {}).get("mark")
            if mark:
                self._marks[symbol] = float(mark)
            return
        self._ensure_instrument(symbol)
        inst = self._instruments[symbol]
        for tick in to_nautilus_ticks([event],
                                      {symbol: (inst.price_precision, inst.size_precision)}):
            self.feed(tick)

    def latest_mark(self, instrument: str) -> float | None:
        return self._marks.get(instrument.upper())

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
                    seq = int(detail["client_id"].split("-")[1])
                    self._seq = max(self._seq, seq)
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

        Live ticks carry receipt-time ts_init, which lags the mark-quote
        clock by sub-ms and interleaves across symbols — normal live data,
        not an error. Stale ticks are re-stamped to engine-now (exchange
        ts_event preserved) so the book still updates and nautilus time
        stays monotonic. Ordered replay streams pass through untouched.
        (Integration fix: a hard raise here crashed R2 on 2 symbols.)
        """
        if self._closed:
            raise RuntimeError("engine is closed")
        now_ns = self._clock.timestamp_ns()
        ts_init = int(data.ts_init)
        if ts_init > now_ns:
            self._clock.set_time(ts_init)
        elif ts_init < now_ns:
            data = self._restamp(data, now_ns)
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

    @property
    def now_utc(self) -> datetime:
        return unix_nanos_to_dt(self._clock.timestamp_ns())

    def _live_now_ns(self) -> int:
        """Wall-now floored at the engine clock (live-paper mark timestamps)."""
        wall_ns = dt_to_unix_nanos(self._now_utc())
        return max(wall_ns, self._clock.timestamp_ns())

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
            "mark-quote model (session live-paper path): note_mark feeds the sim as a "
            "zero-spread quote at the session mark with nominal 1.0 size — fill basis "
            "equals the mark (reference-equivalent); true spread/size crossing needs the "
            "quote feed (feed/note_event)",
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
                "ts_utc": self._now_utc().isoformat(),
                "event": event,
                "detail": detail,
            }) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _on_order_event(self, event: OrderEvent) -> None:
        # Mirror ExecutionEngine's apply-role for local state (fills/cancels still
        # originate in the simulator): without this, tracked orders never leave
        # SUBMITTED and cancels/expiry cannot resolve.
        coid = getattr(event, "client_order_id", None)
        order = self._orders.get(coid.value if coid is not None else "")
        if order is not None:
            order.apply(event)
        if isinstance(event, OrderFilled):
            self._track_position(event)
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
                self._pending.append(mapped)
                self._propagate_live(payload)
            else:
                self._journal("terminal", {"client_id": getattr(payload, "client_order_id", ""),
                                          "kind": kind,
                                          "reason": getattr(payload, "reason", "")})
                self._pending.append(mapped)

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

    def _track_position(self, fill: OrderFilled) -> None:
        # ExecutionEngine-equivalent netting bookkeeping: stamp the netting
        # position ID on a copy of the fill and index/extend the position in
        # the shared cache, so the venue's own reduce-only checks
        # (process_order reads cache positions) see real exposure. Fills
        # originate in the simulator; this only files them where the venue
        # expects. PnL book of record stays our ledger.
        # (position_id is readonly from Python, hence the stamped copy.)
        pid = PositionId(f"{fill.instrument_id}-{fill.strategy_id}")
        stamped = OrderFilled(
            trader_id=fill.trader_id, strategy_id=fill.strategy_id,
            instrument_id=fill.instrument_id, client_order_id=fill.client_order_id,
            venue_order_id=fill.venue_order_id, account_id=fill.account_id,
            trade_id=fill.trade_id, position_id=pid, order_side=fill.order_side,
            order_type=fill.order_type, last_qty=fill.last_qty, last_px=fill.last_px,
            currency=fill.currency, commission=fill.commission,
            liquidity_side=fill.liquidity_side, event_id=UUID4(),
            ts_event=fill.ts_event, ts_init=fill.ts_init, info=dict(fill.info or {}),
        )
        position = self._cache.position(pid)
        if position is None or position.is_closed:
            instrument = self._instruments[fill.instrument_id.symbol.value]
            position = Position(instrument, stamped)
            self._cache.add_position(position, OmsType.NETTING)
        else:
            position.apply(stamped)

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
