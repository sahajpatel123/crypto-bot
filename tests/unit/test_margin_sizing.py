"""T1.8: tiered maintenance margin, isolated liquidation, min equity."""
from __future__ import annotations

import pytest

from cryptobot.risk.margin import (
    liquidation_ok, liquidation_price_isolated, maintenance_margin,
    minimum_viable_equity)

BRACKETS = [
    {"bracket": 1, "notionalCap": 50000.0, "maintMarginRatio": 0.004,
     "cum": 0.0},
    {"bracket": 2, "notionalCap": 250000.0, "maintMarginRatio": 0.005,
     "cum": 50.0},
]


def test_maintenance_margin_tiered():
    assert maintenance_margin(40000.0, BRACKETS) == pytest.approx(160.0)
    # Tier 2: 100000*0.005 - 50 = 450
    assert maintenance_margin(100000.0, BRACKETS) == pytest.approx(450.0)


def test_liquidation_price_isolated_long_short():
    # Long 0.1 BTC @60000, isolated margin 2000, mm=24 (400bps of 6000)
    liq_long = liquidation_price_isolated(
        entry=60000.0, qty=0.1, isolated_margin=2000.0,
        maint_margin=24.0)
    assert liq_long == pytest.approx(60000.0 - (2000.0 - 24.0) / 0.1)
    liq_short = liquidation_price_isolated(
        entry=60000.0, qty=-0.1, isolated_margin=2000.0,
        maint_margin=24.0)
    assert liq_short == pytest.approx(60000.0 + (2000.0 - 24.0) / 0.1)


def test_liquidation_gate_requires_3x_and_beyond_stop():
    # entry 100, stop 99 (dist 1), liq 96: distance 4 >= 3 and beyond
    assert liquidation_ok(entry=100.0, stop=99.0, liq=96.0,
                          stressed_slippage_bps=50.0, side="LONG")
    # liq 97.5: distance 2.5 < 3x stop distance
    assert not liquidation_ok(entry=100.0, stop=99.0, liq=97.5,
                              stressed_slippage_bps=50.0, side="LONG")
    # liq 98.8 beyond stop but within stressed slippage of stop
    assert not liquidation_ok(entry=100.0, stop=99.0, liq=98.8,
                              stressed_slippage_bps=50.0, side="LONG")


def test_minimum_viable_equity():
    # min notional 100 USDT, stop 1% away, budget 0.125% of equity:
    # loss at min size = 100*0.01=1 USDT (+ costs ignored) -> equity 800
    eq = minimum_viable_equity(min_notional_usdt=100.0,
                               stop_dist_frac=0.01,
                               loss_budget_pct=0.00125)
    assert eq == pytest.approx(800.0)
    with pytest.raises(ValueError):
        minimum_viable_equity(min_notional_usdt=100.0, stop_dist_frac=0.0)


def test_bracket_admission_tier_boundaries():
    from cryptobot.risk.margin import bracket_admission_check

    now = 1_000_000
    # 1 BTC @ 40,000 => notional 40k (tier 1); tier 2 begins above 50k.
    below = bracket_admission_check(
        entry=40_000.0, stop=39_000.0, qty=1.0, side="LONG",
        leverage=3.0, brackets=BRACKETS, observed_ms=now, now_ms=now)
    assert below["ok"] and below["maintenance_margin_usdt"] == pytest.approx(160.0)
    # 1.25 BTC => 50k exactly: still tier 1 (<= cap).
    at_cap = bracket_admission_check(
        entry=40_000.0, stop=39_000.0, qty=1.25, side="LONG",
        leverage=3.0, brackets=BRACKETS, observed_ms=now, now_ms=now)
    assert at_cap["maintenance_margin_usdt"] == pytest.approx(200.0)
    # 1.3 BTC => 52k: tier 2 arithmetic 52000*0.005 - 50 = 210.
    above = bracket_admission_check(
        entry=40_000.0, stop=39_000.0, qty=1.3, side="LONG",
        leverage=3.0, brackets=BRACKETS, observed_ms=now, now_ms=now)
    assert above["maintenance_margin_usdt"] == pytest.approx(210.0)
    # Same tier data is monotonic in notional (no downward cliff).
    assert below["maintenance_margin_usdt"] <= at_cap["maintenance_margin_usdt"] \
        <= above["maintenance_margin_usdt"]


def test_bracket_admission_stale_or_missing_rejects():
    from cryptobot.risk.margin import bracket_admission_check

    kw = dict(entry=100.0, stop=99.0, qty=1.0, side="LONG",
              leverage=3.0, brackets=BRACKETS)
    stale = bracket_admission_check(observed_ms=1_000, now_ms=1_000_000,
                                    **kw)
    assert stale["ok"] is False
    assert stale["reason"] == "margin:brackets-stale"
    missing = bracket_admission_check(observed_ms=1_000, now_ms=1_000_000,
                                      brackets=None, entry=100.0, stop=99.0,
                                      qty=1.0, side="LONG", leverage=3.0)
    assert missing["reason"] == "margin:brackets-missing"
    unobserved = bracket_admission_check(observed_ms=None, now_ms=1_000_000,
                                         **kw)
    assert unobserved["reason"] == "margin:brackets-unobserved"
    malformed = bracket_admission_check(
        observed_ms=1_000_000, now_ms=1_000_000, entry=100.0, stop=99.0,
        qty=1.0, side="LONG", leverage=3.0,
        brackets=[{"notionalCap": "nope", "maintMarginRatio": 0.004}])
    assert malformed["reason"] == "margin:brackets-malformed"


def test_bracket_admission_liquidation_distance_monotonic_in_leverage():
    from cryptobot.risk.margin import bracket_admission_check

    now = 1_000_000
    results = [bracket_admission_check(
        entry=100.0, stop=99.0, qty=1.0, side="LONG", leverage=lev,
        brackets=BRACKETS, observed_ms=now, now_ms=now)
        for lev in (3.0, 5.0, 10.0, 20.0, 50.0)]
    liqs = [r["liquidation_price"] for r in results]
    assert liqs == sorted(liqs)  # closer to entry (higher) as lev rises
    assert results[0]["ok"] is True
    assert results[-1]["ok"] is False
    assert results[-1]["reason"] == "margin:liquidation-too-close"


def test_session_bracket_admission_uses_live_engine_and_fails_closed():
    from types import SimpleNamespace

    from cryptobot.app.session import Session

    class _Intent:
        instrument = "BTCUSDT"
        side = SimpleNamespace(value="LONG")
        entry_high = 100.0
        entry_low = 100.0

    class _Engine:
        _leverage = 3
        BRACKET_MAX_AGE_MS = 300_000

        def __init__(self, data):
            self.data = data

        def leverage_brackets(self, symbol):
            return self.data

    class _Policy:
        config = SimpleNamespace(leverage_cap=3)

    now = 1_000_000
    good = {"brackets": BRACKETS, "observed_ms": now, "now_ms": now,
            "stale": False}
    stale = {**good, "observed_ms": now - 600_000}
    fake = SimpleNamespace(engine=_Engine(good), policy=_Policy(),
                           _derive_exits=lambda intent: (
                               99.0, 101.0, None, False),
                           now_utc=lambda: __import__("datetime").datetime
                           .fromtimestamp(now / 1000, __import__("datetime")
                                          .timezone.utc))
    assert Session._bracket_admission(fake, _Intent(), 1.0) is None
    fake.engine.data = stale
    assert Session._bracket_admission(fake, _Intent(), 1.0) \
        == "margin:brackets-stale"
    fake.engine.data = None
    assert Session._bracket_admission(fake, _Intent(), 1.0) \
        == "margin:brackets-unavailable"

    class _NoBracketEngine:
        pass

    fake.engine = _NoBracketEngine()
    assert Session._bracket_admission(fake, _Intent(), 1.0) is None
