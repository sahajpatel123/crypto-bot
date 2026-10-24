"""V-008 §7: identical venue rounding across risk/submission/fills/protection.

Economic path (nautilus engine) + fault path (FakeVenue) both floor with
the one shared rule; a risk-sized quantity submits, fills and protects
at the identical value.
"""
from datetime import UTC, datetime

import pytest

from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side
from cryptobot.execution.fake_venue import FakeVenue
from cryptobot.risk import InstrumentFilter, RiskConfig, plan_size
from cryptobot.risk.rounding import floor_to_step

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _intent():
    return Intent(
        strategy="S1", version="v1", instrument="BTCUSDT", side=Side.LONG,
        evidence_ts_utc=T0, entry_low=59990.0, entry_high=60010.0,
        entry_expiry_utc=datetime(2026, 10, 2, tzinfo=UTC),
        invalidation_price=59800.0, exit_rule="tbd", holding_limit_s=3600,
        forecast_cost=ForecastCost(fee_bps=5.0, spread_bps=5.0,
                                   slippage_bps=5.0, funding_bps=1.0),
        evidence_ref="r1", data_quality=DataQuality.CLEAN)


def _config():
    return RiskConfig(instrument_filters={
        "BTCUSDT": InstrumentFilter(min_notional_usdt=5.0, qty_step=0.001,
                                    min_qty=0.001, max_qty=1000.0,
                                    tick_size=0.01)})


# -- fault path: FakeVenue -------------------------------------------------
def test_fake_venue_floors_submit_when_step_configured():
    venue = FakeVenue(lot_steps={"BTCUSDT": 0.001})
    venue.set_last_price("BTCUSDT", 60000.0)
    result = venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 0.0019, 60000.0)
    assert result.accepted
    assert venue.query("c1").qty == 0.001
    assert venue.fills[0].qty == 0.001


def test_fake_venue_dust_below_step_raises():
    venue = FakeVenue(lot_steps={"BTCUSDT": 0.001})
    venue.set_last_price("BTCUSDT", 60000.0)
    with pytest.raises(ValueError, match="below LOT_SIZE step"):
        venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 0.0009, 60000.0)


def test_fake_venue_unconfigured_symbol_keeps_raw():
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 60000.0)
    result = venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 0.0019, 60000.0)
    assert result.accepted
    assert venue.query("c1").qty == 0.0019


# -- economic path: nautilus engine ----------------------------------------
nautilus = pytest.importorskip("nautilus_trader")


def _engine():
    from cryptobot.adapters import NautilusPaperEngine
    engine = NautilusPaperEngine(taker_bps=5.0, now_utc=lambda: T0,
                                 submit_delay_ms=0, fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    return engine


def _quote(engine, i, bid, ask):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    engine.feed(QuoteTick(
        instrument_id=engine.instrument_id("BTCUSDT"),
        bid_price=Price(bid, 2), ask_price=Price(ask, 2),
        bid_size=Quantity(1.0, 3), ask_size=Quantity(1.0, 3),
        ts_event=int(T0.timestamp() * 1e9) + i * 1_000_000_000,
        ts_init=int(T0.timestamp() * 1e9) + i * 1_000_000_000))


def test_engine_submit_fills_at_floored_qty():
    from cryptobot.app.engine import EngineOrder
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.0019, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert len(fills) == 1
    assert fills[0].payload.qty == 0.001
    assert fills[0].payload.qty == floor_to_step(0.0019, 0.001)


def test_engine_protection_legs_carry_floored_qty():
    from cryptobot.app.engine import EngineOrder
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.0029, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    legs = engine.attach_protection(entry, 59990.00, 60010.00)
    statuses = {s.client_order_id: s for s in engine.open_orders()}
    assert statuses[legs[0]].qty == 0.002
    assert statuses[legs[1]].qty == 0.002


def test_risk_sized_qty_submits_fills_protects_identical():
    from cryptobot.app.engine import EngineOrder
    plan = plan_size(_intent(), 10000.0, _config())
    assert plan.qty == floor_to_step(plan.qty, 0.001)
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", plan.qty, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert len(fills) == 1
    assert fills[0].payload.qty == plan.qty
    legs = engine.attach_protection(entry, 59990.00, 60010.00)
    statuses = {s.client_order_id: s for s in engine.open_orders()}
    assert statuses[legs[0]].qty == plan.qty
    assert statuses[legs[1]].qty == plan.qty
