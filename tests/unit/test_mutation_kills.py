"""F1.2 mutation-kill tests (ONE owned file; never weaken existing tests).

Covers survivors in money-critical functions across six mutmut runs:
  sizing.plan_size | margin.* | rounding.* | fill_realism.* |
  policy.evaluate/_check_liquidation/_check_filters/note_fill_delta/release/
    note_flat/monitor_tick/_check_stops (+adjacent gate/validation/sink code) |
  order_manager submit_entry/submit_with_retry/_submit/attach/sibling-settle/
    recover/_book_fills/_propagate_delta (+adjacent manager code).

Naming: test_kills_<file>_<mutants>_<behavior>. Mutant numbers cited are the
survivor ids from f1.2-*.txt; for ordermanager (cache live) numbers were
verified via `mutmut show`, for the other five files (cache gone) tests are
written from first principles per the function contract so each behavioral
mutant fails at least one assert. Journal-shape asserts (exact event names +
detail key sets) kill whole string-mutant families at once.

Self-contained: only cryptobot + stdlib + pytest imports, so the file runs
under mutant-shadowing (PYTHONPATH=<mut>/mutants/src) for kill verification.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from cryptobot.accounting.ledger import Ledger
from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side
from cryptobot.execution import FakeVenue, OrderManager, OrderState
from cryptobot.execution.fake_venue import VenueOrderView
from cryptobot.execution.fill_realism import (
    PaperFillParams,
    maker_fill,
    pessimistic_fill_price,
    stressed_pnl,
)
from cryptobot.risk import SizeRejected, plan_size
from cryptobot.risk.margin import (
    liquidation_ok,
    liquidation_price_isolated,
    maintenance_margin,
    minimum_viable_equity,
)
from cryptobot.risk.policy import RiskPolicy
from cryptobot.risk.rounding import _step_eps as step_eps
from cryptobot.risk.rounding import ceil_to_tick, floor_to_step, floor_to_tick, round_to_tick
from cryptobot.risk.types import AccountSnapshot, Approved, InstrumentFilter, Rejected, RiskConfig

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)

BRACKETS = [
    {"bracket": 1, "notionalCap": 50000.0, "maintMarginRatio": 0.004,
     "cum": 0.0},
    {"bracket": 2, "notionalCap": 250000.0, "maintMarginRatio": 0.005,
     "cum": 50.0},
]

COMPLETE = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                            max_notional_usdt=1e9, min_qty=0.01,
                            max_qty=1000.0, tick_size=0.1)


# -- shared builders -------------------------------------------------------

def _intent(side=Side.LONG, **kw):
    base = dict(strategy="F1.2", version="1", instrument="BTCUSDT",
                side=side, evidence_ts_utc=NOW,
                entry_low=100.0, entry_high=101.0,
                entry_expiry_utc=NOW + timedelta(seconds=60),
                invalidation_price=99.0 if side == Side.LONG else 102.0,
                exit_rule="inv", holding_limit_s=60,
                forecast_cost=ForecastCost(5, 5, 5, 0),
                evidence_ref="r", data_quality=DataQuality.CLEAN)
    base.update(kw)
    return Intent(**base)


def _account(equity=10000.0, **kw):
    base = dict(reconciled_equity=equity, marked_equity=equity,
                net_liquidation=equity, net_realised_global=0.0,
                open_position=False)
    base.update(kw)
    return AccountSnapshot(**base)


def _policy(tmp_path, now=NOW, reconcile=10000.0, filename="risk.json", **cfg):
    pol = RiskPolicy(RiskConfig(**cfg), state_path=tmp_path / filename,
                     now_utc=lambda: now)
    if reconcile is not None:
        pol.reconcile_day(reconcile)
    return pol


def _manager(venue, tmp_path, now=NOW, filename="orders.jsonl", **kw):
    return OrderManager(venue, log_path=tmp_path / filename,
                        now_utc=lambda: now, **kw)


def _journal(tmp_path, filename="orders.jsonl"):
    path = tmp_path / filename
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class _Sink:
    """Recording RiskOutcomeSink (full v0.2.0 surface)."""

    def __init__(self):
        self.deltas = []
        self.fills = []
        self.releases = []
        self.flats = 0

    def note_fill_delta(self, reservation_id, exec_id, symbol, venue_side,
                        qty, price, fee, ts_utc):
        self.deltas.append((reservation_id, exec_id, symbol, venue_side,
                            qty, price, fee, ts_utc))

    def note_fill(self, reservation_id):
        self.fills.append(reservation_id)

    def release(self, reservation_id):
        self.releases.append(reservation_id)
        return True

    def note_flat(self):
        self.flats += 1


class _LegacySink:
    """Pre-v0.2.0 sink: no note_fill_delta attr (delta-not-propagated path)."""

    def __init__(self):
        self.fills = []
        self.releases = []
        self.flats = 0

    def note_fill(self, reservation_id):
        self.fills.append(reservation_id)

    def release(self, reservation_id):
        self.releases.append(reservation_id)
        return True

    def note_flat(self):
        self.flats += 1


# =========================================================================
# rounding (f1.2-rounding: 30 survived)
# =========================================================================

class TestRoundingKills:
    def test_kills_rounding_stepeps_1_4_5_6_nonfinite_neg_zero(self):
        # _step_eps guards: nonfinite -> 0.0, negative -> 0.0, -0.0 is NOT < 0.
        for bad in (math.nan, math.inf, -math.inf):
            assert step_eps(bad) == 0.0
        assert step_eps(-1.0) == 0.0
        assert step_eps(-1e300) == 0.0
        assert step_eps(-0.0) == 1e-323  # 2*ulp(0); kills `<` -> `<=`

    def test_kills_rounding_stepeps_11_12_14_scale_and_cap(self):
        # Exact scale (2.0 * ulp) plus the 1e-6 cap; kills multiplier,
        # min->max and cap-value mutants.
        assert step_eps(1.0) == 4.440892098500626e-16
        assert step_eps(0.5) == 2.220446049250313e-16
        assert step_eps(100.0) == 2.842170943040401e-14
        assert step_eps(1e9) == 2.384185791015625e-07
        assert step_eps(1e10) == 1e-6
        assert step_eps(1e300) == 1e-6

    def test_kills_rounding_floortostep_9_15_16_exact_and_floor(self):
        # Exact multiples survive (kills floor->ceil, +eps->-eps/no-eps);
        # genuine non-multiples stay down; non-positive -> 0.0.
        assert floor_to_step(0.1, 0.1) == 0.1
        assert floor_to_step(1.0, 1.0) == 1.0
        assert floor_to_step(0.3, 0.1) == 0.3
        assert floor_to_step(2.35, 0.01) == 2.35
        assert floor_to_step(0.15, 0.1) == 0.1
        assert floor_to_step(1.0000009, 1.0) == 1.0
        assert floor_to_step(0.0, 0.1) == 0.0
        assert floor_to_step(-5.0, 0.1) == 0.0
        assert floor_to_step(10.0, 1e-8) == 10.0
        assert floor_to_step(1e8, 1) == 1e8
        for qty in (0.0009, 0.001, 0.0019, 0.01, 0.1, 0.3, 1.0, 2.359,
                    100.0, 1234.5678):
            for step in (0.001, 0.01, 0.1):
                once = floor_to_step(qty, step)
                assert floor_to_step(once, step) == once

    def test_kills_rounding_floortostep_29_round12_dust(self):
        # Representation dust pinned at 12 digits: kills round-12 digit
        # mutants (11/13 digit variants give different floats here).
        assert floor_to_step(7979.373966547071, 0.0001) == 7979.373900000001
        assert floor_to_step(7979.373966547071, 0.0001) != 7979.3739000000005
        assert floor_to_step(7979.373966547071, 0.0001) != 7979.3739

    def test_kills_rounding_roundtotick_3_9_12_half_even_nearest(self):
        # Banker's rounding + nearest-tick; kills round->floor/ceil/trunc
        # and *tick->/tick mutants.
        assert round_to_tick(2.5, 1.0) == 2.0
        assert round_to_tick(3.5, 1.0) == 4.0
        assert round_to_tick(0.15, 0.1) == 0.1
        assert round_to_tick(100.05, 0.1) == 100.0
        assert round_to_tick(100.15, 0.1) == 100.2
        assert round_to_tick(59990.03, 0.1) == 59990.0
        assert round_to_tick(100.0, 0.1) == 100.0

    def test_kills_rounding_roundtotick_17_18_26_validation(self):
        # Boundary 0.0 must raise (kills `<= 0` -> `< 0`); bool/str/nonfinite.
        for bad_tick in (0.0, -0.1, math.nan, math.inf, True, False,
                         "0.1", None):
            with pytest.raises(ValueError):
                round_to_tick(100.0, bad_tick)
        for bad_px in (0.0, -1.0, math.nan, math.inf, True, "100.0", None):
            with pytest.raises(ValueError):
                round_to_tick(bad_px, 0.1)

    def test_kills_rounding_tick_15_floor_ceil_direction(self):
        # floor/ceil direction + eps-sign on exact multiples.
        assert floor_to_tick(100.55, 0.1) == 100.5
        assert ceil_to_tick(100.55, 0.1) == 100.6
        assert floor_to_tick(0.3, 0.1) == 0.3
        assert ceil_to_tick(0.3, 0.1) == 0.3
        assert floor_to_tick(100.5, 0.1) == 100.5
        assert ceil_to_tick(100.5, 0.1) == 100.5
        assert floor_to_tick(60000.0, 0.10) == 60000.0
        assert ceil_to_tick(60000.0, 0.10) == 60000.0

    def test_kills_rounding_checktick_1_2_3_7_9_10_11_12_16_17_18_args(self):
        for bad in (True, False, "0.1", None, math.nan, math.inf,
                    -math.inf, 0.0, -1.0):
            with pytest.raises(ValueError):
                floor_to_tick(1.0, bad)
            with pytest.raises(ValueError):
                ceil_to_tick(1.0, bad)
            with pytest.raises(ValueError):
                floor_to_tick(bad, 0.1)
            with pytest.raises(ValueError):
                ceil_to_tick(bad, 0.1)
        assert floor_to_tick(1.0, 0.1) == 1.0
        assert ceil_to_tick(1.0, 0.1) == 1.0


# =========================================================================
# margin (f1.2-margin: 105 survived)
# =========================================================================

class TestMarginKills:
    def test_kills_margin_finite_1_5_validation(self):
        from cryptobot.risk.margin import _finite
        for bad in ("x", None, math.nan, math.inf, -math.inf, [1.0]):
            with pytest.raises(ValueError):
                _finite(bad, "v")
        assert _finite(5, "v") == 5.0
        assert _finite(5.5, "v") == 5.5
        assert _finite(True, "v") == 1.0  # bool passes isinstance(int)
        assert isinstance(_finite(5, "v"), float)  # always float, never int

    def test_kills_margin_mm_3_6_7_8_zero_neg_empty(self):
        # 0.0 notional is legal (kills `< 0` -> `<= 0`); negatives, empty
        # and None brackets raise.
        assert maintenance_margin(0.0, BRACKETS) == 0.0
        with pytest.raises(ValueError):
            maintenance_margin(-1.0, BRACKETS)
        with pytest.raises(ValueError):
            maintenance_margin(1.0, [])
        with pytest.raises(ValueError):
            maintenance_margin(1.0, None)
        with pytest.raises(ValueError):
            maintenance_margin(math.nan, BRACKETS)

    def test_kills_margin_mm_10_11_12_boundary_tier(self):
        # Discontinuous tiers: exact cap stays in tier 1 (kills `<=` -> `<`).
        jump = [
            {"notionalCap": 100.0, "maintMarginRatio": 0.01, "cum": 0.0},
            {"notionalCap": 200.0, "maintMarginRatio": 0.05, "cum": 0.0},
        ]
        assert maintenance_margin(100.0, jump) == 1.0
        assert maintenance_margin(100.01, jump) == pytest.approx(5.0005)
        assert maintenance_margin(99.99, jump) == pytest.approx(0.9999)

    def test_kills_margin_mm_14_15_16_44_68_arith_cum(self):
        # Tier arithmetic incl. missing-cum default 0.0 (kills *->/+/-, -->+,
        # default-value mutants) on both the in-tier and top-tier paths.
        assert maintenance_margin(100000.0, BRACKETS) == pytest.approx(450.0)
        assert maintenance_margin(40000.0, BRACKETS) == pytest.approx(160.0)
        no_cum = [{"notionalCap": 50000.0, "maintMarginRatio": 0.004}]
        assert maintenance_margin(40000.0, no_cum) == pytest.approx(160.0)
        top_no_cum = [{"notionalCap": 100.0, "maintMarginRatio": 0.01}]
        assert maintenance_margin(300000.0, top_no_cum) == pytest.approx(3000.0)
        assert maintenance_margin(300000.0, BRACKETS) == pytest.approx(1450.0)

    def test_kills_margin_mm_26_39_41_sort_and_top(self):
        # Unsorted input sorts by cap (kills sorted-removal); above-cap
        # notionals price the TOP tier (kills max->min).
        rev = list(reversed(BRACKETS))
        assert maintenance_margin(40000.0, rev) == pytest.approx(160.0)
        assert maintenance_margin(100000.0, rev) == pytest.approx(450.0)
        assert maintenance_margin(300000.0, rev) == pytest.approx(1450.0)
        three = [
            {"notionalCap": 10.0, "maintMarginRatio": 0.10, "cum": 0.0},
            {"notionalCap": 20.0, "maintMarginRatio": 0.20, "cum": 1.0},
            {"notionalCap": 30.0, "maintMarginRatio": 0.30, "cum": 2.0},
        ]
        assert maintenance_margin(25.0, three) == pytest.approx(25.0 * 0.30 - 2.0)
        assert maintenance_margin(30.0, three) == pytest.approx(30.0 * 0.30 - 2.0)
        assert maintenance_margin(31.0, three) == pytest.approx(31.0 * 0.30 - 2.0)

    def test_kills_margin_mm_keys_sort_by_cap(self):
        # Misaligned tiers (ratio order != cap order): sorting AND the top
        # fallback key on notionalCap, never on the ratio. Kills key mutants.
        crossed = [
            {"notionalCap": 100.0, "maintMarginRatio": 0.05, "cum": 0.0},
            {"notionalCap": 200.0, "maintMarginRatio": 0.01, "cum": 0.0},
        ]
        assert maintenance_margin(50.0, crossed) == pytest.approx(2.5)
        assert maintenance_margin(50.0, list(reversed(crossed))) == \
            pytest.approx(2.5)
        assert maintenance_margin(150.0, crossed) == pytest.approx(1.5)
        assert maintenance_margin(500.0, crossed) == pytest.approx(5.0)

    def test_kills_margin_liqprice_3_6_7_10_32_33_long_short_math(self):
        # entry - buffer/qty with signed qty; qty==0 raises; nonfinite raises.
        assert liquidation_price_isolated(
            entry=100.0, qty=2.0, isolated_margin=30.0,
            maint_margin=6.0) == 88.0
        assert liquidation_price_isolated(
            entry=100.0, qty=-2.0, isolated_margin=30.0,
            maint_margin=6.0) == 112.0
        # Negative buffer (mm > margin): long liq sits above entry.
        assert liquidation_price_isolated(
            entry=100.0, qty=2.0, isolated_margin=5.0,
            maint_margin=9.0) == 102.0
        with pytest.raises(ValueError):
            liquidation_price_isolated(entry=100.0, qty=0.0,
                                       isolated_margin=30.0, maint_margin=6.0)
        with pytest.raises(ValueError):
            liquidation_price_isolated(entry=math.nan, qty=2.0,
                                       isolated_margin=30.0, maint_margin=6.0)
        with pytest.raises(ValueError):
            liquidation_price_isolated(entry=100.0, qty=2.0,
                                       isolated_margin=math.inf,
                                       maint_margin=6.0)

    def test_kills_margin_liqok_3_6_7_10_zero_stop(self):
        # Zero stop distance never admits (kills `<= 0` -> `< 0`); nonfinite
        # inputs raise rather than admit.
        assert not liquidation_ok(entry=100.0, stop=100.0, liq=90.0,
                                  stressed_slippage_bps=50.0, side="LONG")
        assert not liquidation_ok(entry=100.0, stop=100.0, liq=110.0,
                                  stressed_slippage_bps=50.0, side="SHORT")
        with pytest.raises(ValueError):
            liquidation_ok(entry=math.nan, stop=99.0, liq=96.0,
                           stressed_slippage_bps=50.0, side="LONG")
        with pytest.raises(ValueError):
            liquidation_ok(entry=100.0, stop=99.0, liq=96.0,
                           stressed_slippage_bps=math.inf, side="LONG")

    def test_kills_margin_liqok_13_14_17_20_21_3x_boundary(self):
        # Exactly 3x stop distance passes (kills `<` -> `<=`, 3.0 -> 2.0/4.0).
        assert liquidation_ok(entry=100.0, stop=99.0, liq=97.0,
                              stressed_slippage_bps=0.0, side="LONG")
        assert liquidation_ok(entry=100.0, stop=101.0, liq=103.0,
                              stressed_slippage_bps=0.0, side="SHORT")
        assert not liquidation_ok(entry=100.0, stop=99.0, liq=97.001,
                                  stressed_slippage_bps=0.0, side="LONG")
        assert not liquidation_ok(entry=100.0, stop=101.0, liq=102.999,
                                  stressed_slippage_bps=0.0, side="SHORT")
        # Right side but inside 3x still fails.
        assert not liquidation_ok(entry=100.0, stop=99.0, liq=98.5,
                                  stressed_slippage_bps=0.0, side="LONG")

    def test_kills_margin_liqok_24_27_28_slip_strict_boundary(self):
        # Slip line binds (2*stop_dist < slip_abs): exact boundary fails
        # (strict </>), one tick beyond passes. Kills comparison flips and
        # entry*slip/10000 arithmetic mutants.
        assert not liquidation_ok(entry=100.0, stop=99.9, liq=99.4,
                                  stressed_slippage_bps=50.0, side="LONG")
        assert liquidation_ok(entry=100.0, stop=99.9, liq=99.3999,
                              stressed_slippage_bps=50.0, side="LONG")
        assert not liquidation_ok(entry=100.0, stop=100.1, liq=100.6,
                                  stressed_slippage_bps=50.0, side="SHORT")
        assert liquidation_ok(entry=100.0, stop=100.1, liq=100.6001,
                              stressed_slippage_bps=50.0, side="SHORT")
        # Slip math scales with entry: 200 * 200bps / 10000 = 4.0.
        assert not liquidation_ok(entry=200.0, stop=199.9, liq=195.9,
                                  stressed_slippage_bps=200.0, side="LONG")
        assert liquidation_ok(entry=200.0, stop=199.9, liq=195.8999,
                              stressed_slippage_bps=200.0, side="LONG")

    def test_kills_margin_liqok_32_34_38_39_40_side_gates(self):
        # Wrong-side liquidation never admits; side enum is strict.
        assert not liquidation_ok(entry=100.0, stop=99.0, liq=103.0,
                                  stressed_slippage_bps=0.0, side="LONG")
        assert not liquidation_ok(entry=100.0, stop=101.0, liq=97.0,
                                  stressed_slippage_bps=0.0, side="SHORT")
        for bad_side in ("long", "short", "", "BOTH", "Long", None):
            with pytest.raises(ValueError):
                liquidation_ok(entry=100.0, stop=99.0, liq=96.0,
                               stressed_slippage_bps=0.0, side=bad_side)

    def test_kills_margin_mve_1_5_defaults_formula(self):
        # Defaults (0.125% budget, zero costs) + exact formula; kills default
        # mutants, +->-, *->/, /->*.
        assert minimum_viable_equity(min_notional_usdt=100.0,
                                     stop_dist_frac=0.01) == 800.0
        assert minimum_viable_equity(
            min_notional_usdt=100.0, stop_dist_frac=0.01,
            loss_budget_pct=0.00125, stressed_cost_frac=0.005) == 1200.0
        assert minimum_viable_equity(
            min_notional_usdt=200.0, stop_dist_frac=0.02,
            loss_budget_pct=0.002) == 2000.0

    def test_kills_margin_mve_8_31_49_validation(self):
        # Zero min/dist/budget raise (kills `<= 0` -> `< 0`); zero costs pass
        # (kills `< 0` -> `<= 0`); negative costs and nonfinite raise.
        assert minimum_viable_equity(
            min_notional_usdt=100.0, stop_dist_frac=0.01,
            stressed_cost_frac=0.0) == 800.0
        for kw in (dict(min_notional_usdt=0.0),
                   dict(min_notional_usdt=-5.0),
                   dict(stop_dist_frac=0.0),
                   dict(stop_dist_frac=-0.01),
                   dict(loss_budget_pct=0.0),
                   dict(loss_budget_pct=-0.5),
                   dict(stressed_cost_frac=-0.1),
                   dict(min_notional_usdt=math.nan),
                   dict(stop_dist_frac=math.inf)):
            args = dict(min_notional_usdt=100.0, stop_dist_frac=0.01)
            args.update(kw)
            with pytest.raises(ValueError):
                minimum_viable_equity(**args)


# =========================================================================
# sizing (f1.2-sizing: 144 survived, all plan_size)
# =========================================================================

class TestSizingKills:
    def _cfg(self, filt=None):
        return RiskConfig(
            instrument_filters={"BTCUSDT": filt if filt is not None else COMPLETE})

    def test_kills_sizing_m1_m2_adverse_side_selection(self):
        # LONG adverses at entry_high, SHORT at entry_low; invalid enums
        # reject (duck-typed intent: real Intent enforces the enum).
        cfg = self._cfg()
        long = plan_size(_intent(Side.LONG), 10000.0, cfg)
        assert long.adverse_price == 101.0
        assert long.qty == 5.61
        short = plan_size(_intent(Side.SHORT), 10000.0, cfg)
        assert short.adverse_price == 100.0
        assert short.qty == 5.61
        assert short.notional_usdt == pytest.approx(561.0)
        bad = SimpleNamespace(
            side="DIAGONAL", entry_low=100.0, entry_high=101.0,
            invalidation_price=99.0, forecast_cost=ForecastCost(5, 5, 5, 0),
            instrument="BTCUSDT")
        with pytest.raises(SizeRejected) as exc:
            plan_size(bad, 10000.0, cfg)
        assert exc.value.reason == "health:invalid-enum"

    def test_kills_sizing_m7_m9_health_gates(self):
        cfg = self._cfg()

        def _ns(**kw):
            base = dict(side=Side.LONG, entry_low=100.0, entry_high=101.0,
                        invalidation_price=99.0,
                        forecast_cost=ForecastCost(5, 5, 5, 0),
                        instrument="BTCUSDT")
            base.update(kw)
            return SimpleNamespace(**base)

        # Namespace intents bypass Intent's own validation to reach the
        # sizing health gates (LONG/SHORT invalidation rules would fire first).
        for kw in (dict(entry_low=math.nan), dict(entry_high=math.inf),
                   dict(invalidation_price=math.nan)):
            with pytest.raises(SizeRejected) as exc:
                plan_size(_ns(**kw), 10000.0, cfg)
            assert exc.value.reason == "health:nonfinite-price"
        for kw in (dict(entry_low=0.0), dict(entry_high=-1.0),
                   dict(invalidation_price=0.0)):
            with pytest.raises(SizeRejected) as exc:
                plan_size(_ns(**kw), 10000.0, cfg)
            assert exc.value.reason == "health:nonpositive-price"
        with pytest.raises(SizeRejected) as exc:
            plan_size(_intent(forecast_cost=ForecastCost(5, 5, math.nan, 0)),
                      10000.0, cfg)
        assert exc.value.reason == "health:nonfinite-cost"
        for bad_equity in (0.0, -1.0, math.nan, math.inf):
            with pytest.raises(SizeRejected) as exc:
                plan_size(_intent(), bad_equity, cfg)
            assert exc.value.reason == "health:nonfinite-account"
        for kw in (dict(available_margin_usdt=-1.0),
                   dict(available_margin_usdt=math.nan),
                   dict(fee_buffer_usdt=-0.5),
                   dict(fee_buffer_usdt=math.inf),
                   dict(inflight_exposure_usdt=-2.0),
                   dict(inflight_exposure_usdt=math.nan)):
            with pytest.raises(SizeRejected) as exc:
                plan_size(_intent(), 10000.0, cfg, **kw)
            assert exc.value.reason == "health:nonfinite-account"
        # Zero stop distance is undefined risk (namespace bypasses Intent's
        # own LONG/SHORT invalidation validation to reach the sizing gate).
        zero_stop = SimpleNamespace(
            side=Side.LONG, entry_low=101.0, entry_high=101.0,
            invalidation_price=101.0, forecast_cost=ForecastCost(5, 5, 5, 0),
            instrument="BTCUSDT")
        with pytest.raises(SizeRejected) as exc:
            plan_size(zero_stop, 10000.0, cfg)
        assert exc.value.reason == "sizing:undefined-risk"

    def test_kills_sizing_m22_40_stressed_funding_credit_clamped(self):
        # Negative funding (a credit) never enlarges size: bps sum clamps at
        # zero. Exact stressed value kills /10000 and *multiplier mutants.
        cfg = self._cfg()
        credit = plan_size(_intent(forecast_cost=ForecastCost(0, 0, 0, -100)),
                           10000.0, cfg)
        assert credit.stressed_cost_pct == 0.0
        assert credit.qty == 6.25
        assert credit.notional_usdt == pytest.approx(631.25)
        part = plan_size(_intent(forecast_cost=ForecastCost(5, 5, 5, -20)),
                         10000.0, cfg)
        assert part.stressed_cost_pct == 0.0  # net -5bps -> clamped
        exact = plan_size(_intent(), 10000.0, cfg)
        assert exact.stressed_cost_pct == 0.0022500000000000003
        cfg2 = RiskConfig(stress_multiplier=2.0,
                          instrument_filters={"BTCUSDT": COMPLETE})
        stressed2 = plan_size(_intent(), 10000.0, cfg2)
        assert stressed2.stressed_cost_pct == pytest.approx(0.003)
        assert stressed2.qty < exact.qty

    def test_kills_sizing_m46_67_budget_cap_min(self):
        # risk_budget_cap takes the MINIMUM (kills min->max); exhausted or
        # nonfinite caps reject; None keeps the per-position budget.
        cfg = self._cfg()
        capped = plan_size(_intent(), 10000.0, cfg, risk_budget_cap_usdt=1.0)
        assert capped.reserved_risk == 1.0
        assert capped.qty == 0.44
        assert capped.notional_usdt == pytest.approx(44.44)
        loose = plan_size(_intent(), 10000.0, cfg,
                          risk_budget_cap_usdt=10_000.0)
        assert loose.reserved_risk == 12.5
        assert loose.qty == 5.61
        plain = plan_size(_intent(), 10000.0, cfg)
        assert plain.reserved_risk == 12.5
        for bad_cap in (0.0, -1.0):
            with pytest.raises(SizeRejected) as exc:
                plan_size(_intent(), 10000.0, cfg,
                          risk_budget_cap_usdt=bad_cap)
            assert exc.value.reason == "skip:remaining-budget"
        with pytest.raises(SizeRejected) as exc:
            plan_size(_intent(), 10000.0, cfg,
                      risk_budget_cap_usdt=math.nan)
        assert exc.value.reason == "health:nonfinite-account"

    def test_kills_sizing_m72_90_qty_formula_floored(self):
        # Hand-computed LONG plan: qty_raw = 12.5/2.22725 floored to 0.01.
        # Kills qty-formula (+->-, *->/), step and floor-direction mutants.
        cfg = self._cfg()
        plan = plan_size(_intent(), 10000.0, cfg)
        assert plan.qty == 5.61
        assert plan.notional_usdt == pytest.approx(566.61)
        assert plan.reserved_risk == 12.5
        assert plan.stop_pct == 0.019801980198019802
        assert plan.adverse_price == 101.0
        # No instrument filter: 1e-8 step keeps full precision.
        cfg_nofilt = RiskConfig()
        raw = plan_size(_intent(), 10000.0, cfg_nofilt)
        assert raw.qty == floor_to_step(12.5 / 2.22725, 1e-8)
        assert raw.qty == pytest.approx(5.61230217)

    def test_kills_sizing_m106_160_qty_notional_gates(self):
        # max_qty caps down; min_qty gates (never rounds up).
        small_max = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                                     min_qty=0.01, max_qty=1.0, tick_size=0.1)
        capped = plan_size(_intent(), 10000.0,
                           RiskConfig(instrument_filters={"BTCUSDT": small_max}))
        assert capped.qty == 1.0
        assert capped.notional_usdt == pytest.approx(101.0)
        big_min = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                                   min_qty=100.0, max_qty=1000.0, tick_size=0.1)
        with pytest.raises(SizeRejected) as exc:
            plan_size(_intent(), 10000.0,
                      RiskConfig(instrument_filters={"BTCUSDT": big_min}))
        assert exc.value.reason == "skip:min-notional"
        # MARKET_LOT_SIZE intersection: tighter bound governs each side.
        mkt = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                               min_qty=0.01, max_qty=1000.0, tick_size=0.1,
                               market_min_qty=10.0, market_max_qty=1000.0)
        with pytest.raises(SizeRejected) as exc:
            plan_size(_intent(), 10000.0,
                      RiskConfig(instrument_filters={"BTCUSDT": mkt}))
        assert exc.value.reason == "skip:min-notional"
        mkt2 = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                                min_qty=0.01, max_qty=1000.0, tick_size=0.1,
                                market_max_qty=2.0)
        capped2 = plan_size(_intent(), 10000.0,
                            RiskConfig(instrument_filters={"BTCUSDT": mkt2}))
        assert capped2.qty == 2.0
        # max_notional caps down with re-floor; min_notional gates.
        maxn = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                                min_qty=0.01, max_qty=1000.0, tick_size=0.1,
                                max_notional_usdt=100.0)
        capped3 = plan_size(_intent(), 10000.0,
                            RiskConfig(instrument_filters={"BTCUSDT": maxn}))
        assert capped3.qty == 0.99
        assert capped3.notional_usdt == pytest.approx(99.99)
        minn = InstrumentFilter(min_notional_usdt=10_000.0, qty_step=0.01,
                                min_qty=0.01, max_qty=1000.0, tick_size=0.1)
        with pytest.raises(SizeRejected) as exc:
            plan_size(_intent(), 10000.0,
                      RiskConfig(instrument_filters={"BTCUSDT": minn}))
        assert exc.value.reason == "skip:min-notional"
        # max_notional below the minimum floor reports the cap: qty passes
        # min_qty (5.61 >= 2.0) but the capped 0.99 does not.
        cap_floor = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                                     min_qty=2.0, max_qty=1000.0,
                                     tick_size=0.1, max_notional_usdt=100.0)
        with pytest.raises(SizeRejected) as exc:
            plan_size(_intent(), 10000.0,
                      RiskConfig(instrument_filters={"BTCUSDT": cap_floor}))
        assert exc.value.reason == "filters:notional-cap"

    def test_kills_sizing_m167_196_leverage_cap_boundary(self):
        # Exact boundary (notional == cap*equity) passes: kills `>` -> `>=`.
        cfg = RiskConfig(leverage_cap=2.0,
                         instrument_filters={"BTCUSDT": COMPLETE})
        edge = plan_size(_intent(entry_low=99.95, entry_high=100.0,
                                 invalidation_price=99.9375,
                                 forecast_cost=ForecastCost(0, 0, 0, 0)),
                         1000.0, cfg)
        assert edge.qty == 20.0
        assert edge.notional_usdt == 2000.0
        over = _intent(entry_low=99.97, entry_high=100.0,
                       invalidation_price=99.96875,
                       forecast_cost=ForecastCost(0, 0, 0, 0))
        with pytest.raises(SizeRejected) as exc:
            plan_size(over, 1000.0, cfg)
        assert exc.value.reason == "leverage:cap-exceeded"

    def test_kills_sizing_m200_225_margin_gate(self):
        # affordable = (avail - fee) * cap - inflight; re-floors qty; gates.
        cfg = self._cfg()
        plan = plan_size(_intent(), 10000.0, cfg,
                         available_margin_usdt=100.0, fee_buffer_usdt=10.0,
                         inflight_exposure_usdt=20.0)
        assert plan.qty == 2.47  # floor(250/101, 0.01)
        assert plan.notional_usdt == pytest.approx(249.47)
        skipped = plan_size(_intent(), 10000.0, cfg,
                            available_margin_usdt=None)
        assert skipped.qty == 5.61  # gate skipped without margin input
        with pytest.raises(SizeRejected) as exc:
            plan_size(_intent(), 10000.0, cfg, available_margin_usdt=1.0)
        assert exc.value.reason == "margin:insufficient"
        # Affordable above the sized notional leaves qty untouched.
        rich = plan_size(_intent(), 10000.0, cfg,
                         available_margin_usdt=10_000.0)
        assert rich.qty == 5.61
        # Re-floor below min_qty after the margin cap reports insufficient.
        tight = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                                 min_qty=2.5, max_qty=1000.0, tick_size=0.1)
        with pytest.raises(SizeRejected) as exc:
            plan_size(_intent(), 10000.0,
                      RiskConfig(instrument_filters={"BTCUSDT": tight}),
                      available_margin_usdt=100.0, fee_buffer_usdt=10.0,
                      inflight_exposure_usdt=20.0)
        assert exc.value.reason == "margin:insufficient"

    def test_kills_sizing_m232_264_exact_multiple_within_tolerance(self):
        # qty_raw an exact step multiple spends exactly the budget: must
        # approve (kills tolerance-removal and always-raise mutants).
        cfg = self._cfg()
        plan = plan_size(_intent(entry_low=100.0, entry_high=100.0,
                                 invalidation_price=87.5,
                                 forecast_cost=ForecastCost(0, 0, 0, 0)),
                         10000.0, cfg)
        assert plan.qty == 1.0
        assert plan.notional_usdt == 100.0
        assert plan.reserved_risk == 12.5
        assert plan.stop_pct == 0.125


# =========================================================================
# fill_realism (f1.2-fillrealism: 53 survived + maker_fill 51 no-tests)
# =========================================================================

class TestFillRealismKills:
    def test_kills_fill_fromdict_2_4_version_shape(self):
        with pytest.raises(ValueError):
            PaperFillParams.from_dict(["not-a-dict"])
        for bad_version in (0, 2, "1", None):
            with pytest.raises(ValueError):
                PaperFillParams.from_dict({"version": bad_version})
        with pytest.raises(ValueError):
            PaperFillParams.from_dict({})
        with pytest.raises(ValueError):
            PaperFillParams.from_dict({"version": 1, "nope": 1.0})
        assert PaperFillParams.from_dict({"version": 1}) == \
            PaperFillParams.default_pessimistic()

    def test_kills_fill_fromdict_11_21_cost_validation(self):
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            for bad in (-1.0, math.nan, math.inf, "2.0", None):
                with pytest.raises(ValueError):
                    PaperFillParams.from_dict({"version": 1, name: bad})
        zeros = PaperFillParams.from_dict(
            {"version": 1, "spread_bps": 0.0, "slippage_bps": 0.0,
             "latency_bps": 0.0, "empty_book_bps": 0.0})
        assert zeros.spread_bps == 0.0

    def test_kills_fill_fromdict_35_49_latency_int(self):
        for bad in (0, -5, 1.5, "50", None, math.nan):
            with pytest.raises(ValueError):
                PaperFillParams.from_dict({"version": 1,
                                           "latency_ms_p95": bad})
        assert PaperFillParams.from_dict(
            {"version": 1, "latency_ms_p95": 50}).latency_ms_p95 == 50

    def test_kills_fill_fromdict_40_58_provenance_roundtrip(self):
        for bad in ("measured", "", None, 0, "CALIBRATED"):
            with pytest.raises(ValueError):
                PaperFillParams.from_dict({"version": 1, "provenance": bad})
        assert PaperFillParams.from_dict(
            {"version": 1, "provenance": "MEASURED",
             "source": "live", "asof_utc": "2026-01-01T00:00:00+00:00"}
        ).provenance == "MEASURED"
        params = PaperFillParams.default_pessimistic()
        assert PaperFillParams.from_dict(params.to_dict()) == params

    def test_kills_fill_pess_1_2_validation(self):
        for bad_side in ("buy", "", None, "LONG"):
            with pytest.raises(ValueError):
                pessimistic_fill_price(bad_side, qty=1.0,
                                       levels=[(100.0, 1.0)])
        for bad_qty in (0.0, -1.0, math.nan, math.inf):
            with pytest.raises(ValueError):
                pessimistic_fill_price("BUY", qty=bad_qty,
                                       levels=[(100.0, 1.0)])
        with pytest.raises(ValueError):
            pessimistic_fill_price("BUY", qty=1.0, levels=[])

    def test_kills_fill_pess_8_10_exact_depth_no_penalty(self):
        # Fully covered fills pay pure VWAP (kills always-penalize); omitted
        # latency/empty args default to no drift (kills default mutants).
        assert pessimistic_fill_price(
            "BUY", qty=1.0, levels=[(100.0, 0.5), (101.0, 0.5)],
            latency_bps=0.0) == 100.5
        assert pessimistic_fill_price(
            "SELL", qty=1.0, levels=[(100.0, 0.5), (99.0, 0.5)],
            latency_bps=0.0) == 99.5
        assert pessimistic_fill_price(
            "BUY", qty=1.0,
            levels=[(100.0, 0.5), (101.0, 0.5)]) == 100.5
        assert pessimistic_fill_price(
            "BUY", qty=0.5, levels=[(100.0, 1.0)]) == 100.0

    def test_kills_fill_pess_14_20_walk_skip(self):
        # Zero-availability levels never move `worst`: an uncovered tail
        # prices off the last FILLED level (kills take<=0/continue mutants).
        assert pessimistic_fill_price(
            "BUY", qty=2.0, levels=[(100.0, 1.0), (101.0, 0.0)],
            latency_bps=0.0) == 100.125
        assert pessimistic_fill_price(
            "BUY", qty=1.0, levels=[(100.0, 0.0), (101.0, 1.0)],
            latency_bps=0.0) == 101.0
        assert pessimistic_fill_price(
            "BUY", qty=1.0, levels=[(100.0, 0.5), (101.0, 1.0)],
            latency_bps=0.0) == 100.5

    def test_kills_fill_pess_25_29_penalty_direction(self):
        # Uncovered remainder: BUY pays worst*(1+bps), SELL gets worst*(1-bps).
        assert pessimistic_fill_price(
            "BUY", qty=2.0, levels=[(100.0, 0.5)],
            latency_bps=0.0, empty_book_bps=25.0) == pytest.approx(100.1875)
        assert pessimistic_fill_price(
            "SELL", qty=2.0, levels=[(100.0, 0.5)],
            latency_bps=0.0, empty_book_bps=25.0) == pytest.approx(99.8125)
        assert pessimistic_fill_price(
            "BUY", qty=2.0, levels=[(100.0, 0.5)],
            latency_bps=0.0, empty_book_bps=0.0) == 100.0

    def test_kills_fill_pess_38_57_vwap_latency(self):
        # VWAP over walked levels; latency drifts adverse per side; int qty ok.
        assert pessimistic_fill_price(
            "BUY", qty=1.0, levels=[(100.0, 0.5), (101.0, 1.0)],
            latency_bps=10.0) == pytest.approx(100.5 * 1.001)
        assert pessimistic_fill_price(
            "SELL", qty=1.0, levels=[(100.0, 0.5), (99.0, 1.0)],
            latency_bps=10.0) == pytest.approx(99.5 * 0.999)
        assert pessimistic_fill_price(
            "BUY", qty=1, levels=[(100, 1)],
            latency_bps=100.0) == pytest.approx(101.0)
        assert pessimistic_fill_price(
            "SELL", qty=1, levels=[(100, 1)],
            latency_bps=100.0) == pytest.approx(99.0)

    def test_kills_fill_maker_1_11_side_empty(self):
        for bad_side in ("buy", "", None, "LONG"):
            with pytest.raises(ValueError):
                maker_fill(side=bad_side, limit_price=100.0, qty=10.0,
                           queue_ahead_qty=5.0, trades=[(99.0, 1.0)])
        assert maker_fill(side="BUY", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=5.0, trades=[]) == 0.0

    def test_kills_fill_maker_11_20_buy_through(self):
        # BUY fills only on prints THROUGH (below) the limit; prints above
        # are ignored; fills cap at qty.
        assert maker_fill(side="BUY", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=5.0,
                          trades=[(101.0, 100.0)]) == 0.0
        assert maker_fill(side="BUY", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=5.0,
                          trades=[(99.0, 3.0), (98.0, 4.0)]) == 7.0
        assert maker_fill(side="BUY", limit_price=100.0, qty=5.0,
                          queue_ahead_qty=0.0,
                          trades=[(99.0, 3.0), (98.0, 4.0)]) == 5.0

    def test_kills_fill_maker_21_30_sell_through_mirror(self):
        assert maker_fill(side="SELL", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=5.0,
                          trades=[(99.0, 100.0)]) == 0.0
        assert maker_fill(side="SELL", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=5.0,
                          trades=[(101.0, 3.0), (102.0, 4.0)]) == 7.0
        assert maker_fill(side="SELL", limit_price=100.0, qty=2.0,
                          queue_ahead_qty=0.0,
                          trades=[(101.0, 5.0)]) == 2.0

    def test_kills_fill_maker_31_40_at_limit_queue(self):
        # At-limit prints consume queue ahead first; only excess fills.
        # Exact queue consumption earns NOTHING (kills `>` -> `>=`).
        assert maker_fill(side="BUY", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=5.0,
                          trades=[(100.0, 5.0)]) == 0.0
        assert maker_fill(side="BUY", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=5.0,
                          trades=[(100.0, 3.0), (100.0, 4.0)]) == 2.0
        assert maker_fill(side="BUY", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=0.0,
                          trades=[(100.0, 3.0)]) == 3.0
        assert maker_fill(side="SELL", limit_price=100.0, qty=10.0,
                          queue_ahead_qty=2.0,
                          trades=[(100.0, 5.0)]) == 3.0

    def test_kills_fill_maker_41_51_cap_and_break(self):
        # Filling stops exactly at qty; through-prints overshoot capped.
        assert maker_fill(side="BUY", limit_price=100.0, qty=5.0,
                          queue_ahead_qty=10.0,
                          trades=[(99.0, 100.0), (98.0, 100.0)]) == 5.0
        assert maker_fill(side="BUY", limit_price=100.0, qty=5.0,
                          queue_ahead_qty=1.0,
                          trades=[(100.0, 3.0), (99.0, 100.0)]) == 5.0
        assert maker_fill(side="BUY", limit_price=100.0, qty=5.0,
                          queue_ahead_qty=0.0,
                          trades=[(100.0, 2.0), (100.0, 2.0),
                                  (100.0, 2.0)]) == 5.0

    def test_kills_fill_stressed_1_2_4_5(self):
        out = stressed_pnl(gross_pnl=100.0, costs_1x=30.0)
        assert out == {"gross": 100.0, "costs_1x": 30.0,
                       "pnl_1x": 70.0, "pnl_2x": 40.0}
        ints = stressed_pnl(gross_pnl=100, costs_1x=30)
        assert ints == {"gross": 100.0, "costs_1x": 30.0,
                        "pnl_1x": 70.0, "pnl_2x": 40.0}
        assert all(isinstance(v, float) for v in ints.values())
        zero = stressed_pnl(gross_pnl=-10.0, costs_1x=0.0)
        assert (zero["pnl_1x"], zero["pnl_2x"]) == (-10.0, -10.0)


# =========================================================================
# policy (f1.2-policy: 301 survived + 74 no-tests)
# =========================================================================

class _Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def _live_policy(tmp_path, clock=None, reconcile=10000.0, **cfg):
    clock = clock or _Clock(NOW)
    pol = RiskPolicy(RiskConfig(**cfg), state_path=tmp_path / "risk.json",
                     now_utc=clock)
    if reconcile is not None:
        pol.reconcile_day(reconcile)
    return pol


class TestPolicyEvaluateKills:
    def test_kills_policy_eval_25_26_data_quality_halts(self, tmp_path):
        pol = _live_policy(tmp_path)
        out = pol.evaluate(_intent(data_quality=DataQuality.HALT), _account())
        assert isinstance(out, Rejected) and out.reason == "health:data-quality-halt"
        out = pol.evaluate(_intent(data_quality=DataQuality.DEGRADED),
                           _account())
        assert isinstance(out, Rejected) and out.reason == "health:data-quality-degraded"

    def test_kills_policy_eval_41_day_open(self, tmp_path):
        pol = _live_policy(tmp_path, reconcile=None)
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Rejected)
        assert out.reason == "health:day-open-needs-reconciliation"
        pol.reconcile_day(10000.0)
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Approved)

    def test_kills_policy_eval_50_53_stops_first(self, tmp_path):
        pol = _live_policy(tmp_path)
        em_line = 10000.0 * (1 - 0.01)
        out = pol.evaluate(_intent(), _account(net_liquidation=em_line - 1.0))
        assert isinstance(out, Rejected) and out.reason == "halt:emergency"

    def test_kills_policy_eval_stop_reasons(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "a.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        op_line = 10000.0 * (1 - 0.005)
        out = pol.evaluate(_intent(), _account(net_liquidation=op_line))
        assert isinstance(out, Rejected) and out.reason == "halt:operating-stop"
        pol_b = RiskPolicy(RiskConfig(), state_path=tmp_path / "b.json",
                           now_utc=clock)
        pol_b.reconcile_day(10000.0)
        em_line = 10000.0 * (1 - 0.01)
        out = pol_b.evaluate(_intent(), _account(net_liquidation=em_line))
        assert isinstance(out, Rejected) and out.reason == "halt:emergency"

    def test_kills_policy_eval_56_70_pause_latch(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        target = 10000.0 * (1 + 0.02)
        out = pol.evaluate(_intent(), _account(net_liquidation=target))
        assert isinstance(out, Rejected) and out.reason == "pause:daily-target"
        # Latched: persists across reload and blocks a neutral print.
        pol2 = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                          now_utc=clock)
        out = pol2.evaluate(_intent(), _account(net_liquidation=10000.0))
        assert isinstance(out, Rejected) and out.reason == "pause:daily-target"
        # One tick below the target does not pause.
        pol3 = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk3.json",
                          now_utc=clock)
        pol3.reconcile_day(10000.0)
        out = pol3.evaluate(_intent(), _account(net_liquidation=target - 0.01))
        assert isinstance(out, Approved), out

    def test_kills_policy_eval_68_69_profit_protection(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        # Arm the floor first with a high marked print.
        out = pol.evaluate(_intent(),
                           _account(net_realised_global=1000.0,
                                    marked_equity=12000.0))
        assert isinstance(out, Approved), out
        floor = pol._state.profit_floor
        assert floor == pytest.approx(10700.0)
        # Exact floor breach halts (kills `<=` -> `<`).
        out = pol.evaluate(_intent(),
                           _account(net_realised_global=1000.0,
                                    marked_equity=floor))
        assert isinstance(out, Rejected)
        assert out.reason == "halt:profit-protection"
        # One tick above the floor passes the HALT (the F-W5R1 cushion then
        # squeezes the budget to ~0.01, which cannot fund a legal order).
        assert pol.release("r-000001") is True
        out = pol.evaluate(_intent(),
                           _account(net_realised_global=1000.0,
                                    marked_equity=floor + 0.01))
        assert isinstance(out, Rejected)
        assert out.reason == "skip:min-notional", out.reason
        # Well clear of the floor approves with the full budget.
        out = pol.evaluate(_intent(),
                           _account(net_realised_global=1000.0,
                                    marked_equity=floor + 600.0))
        assert isinstance(out, Approved), out
        assert out.reserved_risk == 12.5

    def test_kills_policy_eval_94_expired_settle_save(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Approved)
        rid = out.reservation_id
        clock.now = NOW + timedelta(seconds=61)  # past entry_expiry
        out = pol.evaluate(_intent(evidence_ts_utc=clock.now,
                                   entry_expiry_utc=clock.now + timedelta(seconds=60)),
                           _account())
        assert isinstance(out, Rejected)
        assert out.reason == "exposure:unresolved"
        assert rid in pol.unresolved_ids()
        # Persisted: reload still shows unresolved.
        pol2 = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                          now_utc=clock)
        assert rid in pol2.unresolved_ids()

    def test_kills_policy_eval_106_110_exposure_blocks(self, tmp_path):
        pol = _live_policy(tmp_path)
        out = pol.evaluate(_intent(), _account(open_position=True))
        assert isinstance(out, Rejected) and out.reason == "exposure:one-position"
        pol.note_fill("ghost")
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Rejected) and out.reason == "exposure:one-position"
        pol._state.open_position = False
        from cryptobot.risk import save_state as _save
        _save(pol.state_path, pol._state)
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Approved)
        out2 = pol.evaluate(_intent(), _account())
        assert isinstance(out2, Rejected)
        assert out2.reason == "exposure:one-position"

    def test_kills_policy_eval_110_booked_blocks(self, tmp_path):
        pol = _live_policy(tmp_path)
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            NOW.isoformat())
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Rejected) and out.reason == "exposure:booked"

    def test_kills_policy_eval_122_filters_passthrough(self, tmp_path):
        pol = _live_policy(tmp_path, run_mode=True,
                           instrument_filters={"BTCUSDT": COMPLETE},
                           filters_asof_utc=NOW)
        out = pol.evaluate(_intent(instrument="ETHUSDT"), _account())
        assert isinstance(out, Rejected)
        assert out.reason == "filters:unknown-instrument"

    def test_kills_policy_eval_129_131_cap_math(self, tmp_path):
        # Remaining-daily cap binds: netliq 9960 -> cap ~= 10 -> reserved 10.
        pol = _live_policy(tmp_path)
        out = pol.evaluate(_intent(), _account(net_liquidation=9960.0))
        assert isinstance(out, Approved), out
        assert out.reserved_risk == pytest.approx(10.0, abs=1e-6)
        # Full budget when the cap is loose.
        pol2 = RiskPolicy(RiskConfig(), state_path=tmp_path / "b.json",
                          now_utc=_Clock(NOW))
        pol2.reconcile_day(10000.0)
        out2 = pol2.evaluate(_intent(), _account(net_liquidation=10000.0))
        assert isinstance(out2, Approved)
        assert out2.reserved_risk == 12.5

    def test_kills_policy_eval_131_floor_cushion_min(self, tmp_path):
        # Cushion = marked - floor - fee_buffer; min(cap, cushion) governs.
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        pol.evaluate(_intent(), _account(net_realised_global=1000.0,
                                         marked_equity=12000.0))
        floor = pol._state.profit_floor
        pol.release("r-000001")
        out = pol.evaluate(
            _intent(),
            _account(net_realised_global=1000.0, marked_equity=floor + 5.0,
                     fee_buffer_usdt=1.0))
        assert isinstance(out, Approved), out
        assert out.reserved_risk == pytest.approx(4.0, abs=1e-6)

    def test_kills_policy_eval_139_147_reject_passthrough(self, tmp_path):
        pol = _live_policy(tmp_path, min_notional_usdt=10_000.0)
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Rejected)
        assert out.reason == "skip:min-notional"
        pol2 = _live_policy(tmp_path, run_mode=True,
                            instrument_filters={"BTCUSDT": COMPLETE},
                            filters_asof_utc=NOW)
        out = pol2.evaluate(_intent(), _account())
        assert isinstance(out, Rejected)
        assert out.reason == "brackets:required-in-run-mode"

    def test_kills_policy_eval_149_150_approve_shape(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Approved)
        assert out.reservation_id == "r-000001"
        assert out.reserved_risk == 12.5
        assert out.qty == out.required_stop_qty
        assert out.qty > 0 and out.notional_usdt > 0
        assert pol.live_reservations() == ("r-000001",)
        assert pol.release("r-000001") is True
        out2 = pol.evaluate(_intent(), _account())
        assert isinstance(out2, Approved)
        assert out2.reservation_id == "r-000002"


class TestPolicyMonitorKills:
    def _pol(self, tmp_path, filename="risk.json", **cfg):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(**cfg),
                         state_path=tmp_path / filename, now_utc=clock)
        pol.reconcile_day(10000.0)
        return pol, clock

    def test_kills_policy_checkhealth_1_delegates(self, tmp_path):
        pol, _ = self._pol(tmp_path)
        assert pol.check_health(_account()) == pol.monitor_tick(NOW, _account())

    def test_kills_policy_mon_8_day_roll(self, tmp_path):
        pol, clock = self._pol(tmp_path)
        clock.now = NOW + timedelta(days=2)
        status = pol.monitor_tick(clock.now, None)
        assert status.ok is False
        assert "day-rolled" in status.latched
        assert status.reasons == ("health:day-open-needs-reconciliation",)
        assert pol._state.needs_reconciliation is True
        # Same-day tick does not roll.
        pol2, _clock2 = self._pol(tmp_path, filename="risk2.json")
        status = pol2.monitor_tick(NOW + timedelta(hours=1), _account())
        assert "day-rolled" not in status.latched

    def test_kills_policy_mon_21_invalid_account(self, tmp_path):
        pol, _ = self._pol(tmp_path)
        status = pol.monitor_tick(NOW, _account(reconciled_equity=math.nan))
        assert status.ok is False
        assert status.reasons == ("health:nonfinite-account",)
        assert status.latched == ()

    def test_kills_policy_mon_24_35_needs_recon(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        status = pol.monitor_tick(NOW, _account())
        assert status.ok is False
        assert status.reasons == ("health:day-open-needs-reconciliation",)
        assert pol._state.last_tick_utc == NOW.isoformat()

    def test_kills_policy_mon_31_34_none_blocks(self, tmp_path):
        pol, _ = self._pol(tmp_path)
        status = pol.monitor_tick(NOW, None)
        assert status.ok is True
        assert status.reasons == ()
        # Latched blocks surface without any account snapshot.
        pol._state.emergency_latched = True
        status = pol.monitor_tick(NOW, None)
        assert status.ok is False
        assert status.reasons == ("halt:emergency",)
        pol._state.emergency_latched = False
        from cryptobot.accounting.day import accounting_date
        today = accounting_date(NOW).isoformat()
        pol._state.operating_stop_days[today] = "operating-stop"
        pol._state.pause_days[today] = "daily-target"
        status = pol.monitor_tick(NOW, None)
        assert status.reasons == ("halt:operating-stop", "pause:daily-target")

    def test_kills_policy_mon_33_none_settles_expiry(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Approved)
        clock.now = NOW + timedelta(seconds=61)
        status = pol.monitor_tick(clock.now, None)
        assert "expiry-settled" in status.latched
        assert out.reservation_id in pol.unresolved_ids()

    def test_kills_policy_mon_47_49_mark_age(self, tmp_path):
        pol, _ = self._pol(tmp_path, max_mark_age_ms=1000.0)
        status = pol.monitor_tick(NOW, _account(mark_age_ms=None))
        assert status.ok is False
        assert status.reasons == ("health:mark-age-unknown",)
        status = pol.monitor_tick(NOW, _account(mark_age_ms=1000.0))
        assert status.ok is True  # boundary: == limit passes
        status = pol.monitor_tick(NOW, _account(mark_age_ms=1000.01))
        assert status.reasons == ("health:stale-mark",)
        # Disabled when unconfigured.
        pol2, _ = self._pol(tmp_path, filename="riskB.json")
        status = pol2.monitor_tick(NOW, _account(mark_age_ms=None))
        assert status.ok is True

    def test_kills_policy_mon_51_57_stop_latches(self, tmp_path):
        pol, _ = self._pol(tmp_path)
        op_line = 10000.0 * (1 - 0.005)
        status = pol.monitor_tick(NOW, _account(net_liquidation=op_line))
        assert status.ok is False
        assert status.reasons == ("halt:operating-stop",)
        assert status.latched == ("operating-stop",)
        status = pol.monitor_tick(NOW, _account(net_liquidation=op_line))
        assert status.reasons == ("halt:operating-stop",)
        assert "operating-stop" not in status.latched  # already latched
        pol2, _ = self._pol(tmp_path, filename="riskB.json")
        em_line = 10000.0 * (1 - 0.01)
        status = pol2.monitor_tick(NOW, _account(net_liquidation=em_line),
                                   )
        assert status.reasons == ("halt:emergency",)
        assert status.latched == ("emergency",)

    def test_kills_policy_mon_63_67_pause(self, tmp_path):
        pol, _ = self._pol(tmp_path)
        target = 10000.0 * (1 + 0.02)
        status = pol.monitor_tick(NOW, _account(net_liquidation=target))
        assert status.ok is False
        assert "pause" in status.latched
        assert "pause:daily-target" in status.reasons
        status = pol.monitor_tick(NOW, _account(net_liquidation=target))
        assert "pause:daily-target" in status.reasons
        assert "pause" not in status.latched

    def test_kills_policy_mon_77_93_floor(self, tmp_path):
        pol, _ = self._pol(tmp_path)
        status = pol.monitor_tick(NOW, _account(net_realised_global=1000.0,
                                               marked_equity=12000.0))
        assert "floor" in status.latched
        assert status.ok is True
        floor = pol._state.profit_floor
        status = pol.monitor_tick(NOW, _account(net_realised_global=1000.0,
                                               marked_equity=floor))
        assert "halt:profit-protection" in status.reasons
        # No original equity (fresh day pre-reconcile tested elsewhere);
        # peak ratchet only moves up.
        before = pol._state.peak_realised
        pol.monitor_tick(NOW, _account(net_realised_global=500.0,
                                      marked_equity=12000.0))
        assert pol._state.peak_realised == before

    def test_kills_policy_mon_103_155_tick_persist(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        pol.monitor_tick(NOW, _account())
        first = (tmp_path / "risk.json").read_bytes()
        # Same-event-time tick: debounced (no write, dirty flag set).
        pol.monitor_tick(NOW, _account())
        assert (tmp_path / "risk.json").read_bytes() == first
        assert pol._tick_dirty is True
        # Past the 1s event-time window: writes through.
        clock.now = NOW + timedelta(seconds=1.1)
        pol.monitor_tick(clock.now, _account())
        assert (tmp_path / "risk.json").read_bytes() != first
        assert pol._tick_dirty is False
        assert pol._state.last_tick_utc == clock.now.isoformat()

    def test_kills_policy_persist_exact_1s_saves(self, tmp_path):
        # Elapsed exactly 1.0s saves (kills `>=` -> `>`).
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        pol.monitor_tick(NOW, _account())
        pol.monitor_tick(NOW, _account())
        assert pol._tick_dirty is True
        clock.now = NOW + timedelta(seconds=1)
        pol.monitor_tick(clock.now, _account())
        assert pol._tick_dirty is False

    def test_kills_policy_persist_1_25_force_and_broken_stamp(self, tmp_path):
        pol, _ = self._pol(tmp_path)
        pol._tick_dirty = True
        pol._persist_tick(force=True, now=NOW)
        assert pol._tick_dirty is False
        # Broken monotonic stamp (overflow) fails open into a save, not a raise.
        pol._last_tick_save_mono = float("inf")
        pol._persist_tick(force=False, now=NOW)  # must not raise
        assert pol._tick_dirty is False

    def test_kills_policy_flush_1_7_state(self, tmp_path):
        pol, _ = self._pol(tmp_path)
        pol.monitor_tick(NOW, _account())
        pol.monitor_tick(NOW, _account())  # debounced -> dirty
        assert pol._tick_dirty is True
        # Dirty flush writes (prove it by deleting the file first).
        (tmp_path / "risk.json").unlink()
        pol.flush_state()
        assert pol._tick_dirty is False
        assert (tmp_path / "risk.json").exists()
        # Clean flush is a no-op write.
        (tmp_path / "risk.json").unlink()
        pol.flush_state()
        assert not (tmp_path / "risk.json").exists()


class TestPolicySinkKills:
    def test_kills_policy_nfd_1_6_id_validation(self, tmp_path):
        pol = _live_policy(tmp_path)
        ts = NOW.isoformat()
        for bad_rid in ("", None, 123):
            with pytest.raises(ValueError):
                pol.note_fill_delta(bad_rid, "e1", "BTCUSDT", "BUY", 1.0,
                                    100.0, 0.1, ts)
        for bad_exec in ("", None, 7):
            with pytest.raises(ValueError):
                pol.note_fill_delta("r-1", bad_exec, "BTCUSDT", "BUY", 1.0,
                                    100.0, 0.1, ts)
        for bad_sym in ("", None):
            with pytest.raises(ValueError):
                pol.note_fill_delta("r-1", "e1", bad_sym, "BUY", 1.0,
                                    100.0, 0.1, ts)
        for bad_side in ("buy", "", None, "LONG"):
            with pytest.raises(ValueError):
                pol.note_fill_delta("r-1", "e1", "BTCUSDT", bad_side, 1.0,
                                    100.0, 0.1, ts)

    def test_kills_policy_nfd_10_13_qty_price_fee(self, tmp_path):
        pol = _live_policy(tmp_path)
        ts = NOW.isoformat()
        for bad_qty in (0.0, -1.0, math.nan, math.inf, "1.0"):
            with pytest.raises(ValueError):
                pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", bad_qty,
                                    100.0, 0.1, ts)
        for bad_px in (0.0, -100.0, math.nan):
            with pytest.raises(ValueError):
                pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0,
                                    bad_px, 0.1, ts)
        with pytest.raises(ValueError):
            pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0,
                                -0.1, ts)
        # Non-run ledgers accept fee 0.0.
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.0,
                            ts)
        assert pol.booked_net("r-1") == 1.0

    def test_kills_policy_nfd_13_run_fee_strict(self, tmp_path):
        pol = _live_policy(tmp_path, run_mode=True)
        ts = NOW.isoformat()
        with pytest.raises(ValueError):
            pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0,
                                0.0, ts)
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            ts)
        assert pol.booked_net("r-1") == 1.0

    def test_kills_policy_nfd_16_18_ts(self, tmp_path):
        pol = _live_policy(tmp_path)
        for bad_ts in ("2026-10-17T12:00:00",  # naive
                       "not-a-time",
                       "2026-10-17T12:00:00+05:30",  # non-UTC offset
                       None, ""):
            with pytest.raises(ValueError):
                pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0,
                                    100.0, 0.1, bad_ts)
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            "2026-10-17T12:00:00+00:00")
        assert pol.booked_net("r-1") == 1.0

    def test_kills_policy_nfd_24_36_booking_sign(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        ts = NOW.isoformat()
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.5, 100.0, 0.1,
                            ts)
        assert pol.booked_net("r-1") == 1.5
        pol.note_fill_delta("r-1", "e2", "BTCUSDT", "SELL", 0.5, 101.0,
                            0.1, ts)
        assert pol.booked_net("r-1") == pytest.approx(1.0)
        assert pol._state.booked["r-1"]["symbol"] == "BTCUSDT"
        assert pol._state.booked["r-1"]["exec_ids"] == ["e1", "e2"]
        # Persisted across reload.
        pol2 = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                          now_utc=clock)
        assert pol2.booked_net("r-1") == pytest.approx(1.0)
        assert pol.booked_net("unknown") == 0.0

    def test_kills_policy_nfd_42_58_idempotent_ledger(self, tmp_path):
        pol = _live_policy(tmp_path)
        ledger = Ledger(10000.0)
        pol.bind_ledger(ledger)
        ts = NOW.isoformat()
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            ts)
        assert ledger.position_qty() == 1.0
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            ts)  # redelivery: no double-book
        assert pol.booked_net("r-1") == 1.0
        assert pol._state.booked["r-1"]["exec_ids"] == ["e1"]
        assert ledger.position_qty() == 1.0
        # Rebinding replaces the binding.
        ledger2 = Ledger(10000.0)
        pol.bind_ledger(ledger2)
        pol.note_fill_delta("r-1", "e2", "BTCUSDT", "BUY", 2.0, 100.0, 0.1,
                            ts)
        assert ledger2.position_qty() == 2.0
        assert ledger.position_qty() == 1.0

    def test_kills_policy_release_14_27_branches(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        out = pol.evaluate(_intent(), _account())
        rid = out.reservation_id
        pol._executable[rid] = 5.0
        assert pol.release(rid) is True
        assert rid not in pol.live_reservations()
        assert rid not in pol._executable
        assert pol.release("never-issued") is False
        # Live + nonzero booked -> unresolved, kept, False.
        out = pol.evaluate(_intent(), _account())
        rid2 = out.reservation_id
        pol.note_fill_delta(rid2, "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            NOW.isoformat())
        assert pol.release(rid2) is False
        assert rid2 in pol.unresolved_ids()
        assert pol.release(rid2) is False  # unresolved + nonzero: retained
        # Unresolved + zero booked -> lifted, reports False.
        pol._state.booked[rid2]["net_qty"] = 0.0
        pol._executable[rid2] = 1.0
        assert pol.release(rid2) is False
        assert rid2 not in pol.unresolved_ids()
        assert rid2 not in pol._executable

    def test_kills_policy_noteflat_1_gated(self, tmp_path):
        pol = _live_policy(tmp_path)
        pol._state.open_position = True
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            NOW.isoformat())
        pol.note_flat()
        assert pol._state.open_position is True  # blocked: booked nonzero
        pol._state.booked["r-1"]["net_qty"] = 0.0
        pol.note_flat()
        assert pol._state.open_position is False
        # Dust at exactly BOOKED_ZERO_EPS reads as flat (kills `>` -> `>=`).
        from cryptobot.risk.policy import BOOKED_ZERO_EPS
        assert BOOKED_ZERO_EPS == 1e-9
        pol._state.open_position = True
        pol._state.booked["r-1"]["net_qty"] = 1e-9
        pol.note_flat()
        assert pol._state.open_position is False
        assert pol._booked_net("r-1") == 0.0
        pol._state.open_position = True
        pol._state.booked["r-1"]["net_qty"] = 1.1e-9
        pol.note_flat()
        assert pol._state.open_position is True
        assert pol._booked_nonzero_global() is True

    def test_kills_policy_notefill_3_converts(self, tmp_path):
        pol = _live_policy(tmp_path)
        out = pol.evaluate(_intent(), _account())
        pol.note_fill(out.reservation_id)
        assert pol._state.open_position is True
        assert pol.live_reservations() == ()
        pol.note_fill(out.reservation_id)  # idempotent
        assert pol._state.open_position is True

    def test_kills_policy_bookedtotal_4_8_sum_eps(self, tmp_path):
        pol = _live_policy(tmp_path)
        assert pol.booked_total_qty() == 0.0
        ts = NOW.isoformat()
        pol.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.5, 100.0, 0.1,
                            ts)
        pol.note_fill_delta("r-2", "e2", "BTCUSDT", "SELL", 0.5, 100.0, 0.1,
                            ts)
        assert pol.booked_total_qty() == pytest.approx(1.0)
        pol._state.booked["r-1"]["net_qty"] = 5e-10
        pol._state.booked["r-2"]["net_qty"] = -4e-10
        assert pol.booked_total_qty() == 0.0  # |sum| <= eps reads flat


class TestPolicyValidateKills:
    def _ns_intent(self, **kw):
        base = dict(side=Side.LONG, data_quality=DataQuality.CLEAN,
                    entry_low=100.0, entry_high=101.0,
                    invalidation_price=99.0,
                    forecast_cost=ForecastCost(5, 5, 5, 0),
                    holding_limit_s=60, evidence_ts_utc=NOW,
                    entry_expiry_utc=NOW + timedelta(seconds=60))
        base.update(kw)
        return SimpleNamespace(**base)

    def test_kills_policy_validate_6_39_inputs(self, tmp_path):
        pol = _live_policy(tmp_path)
        acct = _account()
        assert pol._validate_inputs(_intent(), acct, NOW) is None
        assert pol._validate_inputs(self._ns_intent(), acct, NOW) is None
        cases = [
            (dict(side="LONG"), "health:invalid-enum"),
            (dict(data_quality="clean"), "health:invalid-enum"),
            (dict(entry_low=math.nan), "health:nonfinite-price"),
            (dict(entry_high=math.inf), "health:nonfinite-price"),
            (dict(invalidation_price=math.nan), "health:nonfinite-price"),
            (dict(entry_low=0.0), "health:nonpositive-price"),
            (dict(entry_high=-1.0), "health:nonpositive-price"),
            (dict(invalidation_price=0.0), "health:nonpositive-price"),
            (dict(holding_limit_s=0), "health:invalid-holding"),
            (dict(holding_limit_s=-5), "health:invalid-holding"),
            (dict(holding_limit_s=60.0), "health:invalid-holding"),
        ]
        for kw, reason in cases:
            got = pol._validate_inputs(self._ns_intent(**kw), acct, NOW)
            assert isinstance(got, Rejected) and got.reason == reason, kw
        bad_cost = self._ns_intent(
            forecast_cost=ForecastCost(5, 5, math.nan, 0))
        assert pol._validate_inputs(bad_cost, acct, NOW).reason == \
            "health:nonfinite-cost"
        # Timestamps: naive, expired, aged, future.
        naive = self._ns_intent(evidence_ts_utc=datetime(2026, 10, 17, 12, 0, 0))
        assert pol._validate_inputs(naive, acct, NOW).reason == \
            "stale:naive-timestamp"
        expired = self._ns_intent(
            evidence_ts_utc=NOW - timedelta(seconds=120),
            entry_expiry_utc=NOW - timedelta(seconds=1))
        assert pol._validate_inputs(expired, acct, NOW).reason == \
            "stale:expired"
        aged = self._ns_intent(
            evidence_ts_utc=NOW - timedelta(seconds=120.001),
            entry_expiry_utc=NOW + timedelta(seconds=60))
        assert pol._validate_inputs(aged, acct, NOW).reason == \
            "stale:evidence-age"
        edge = self._ns_intent(
            evidence_ts_utc=NOW - timedelta(seconds=120),
            entry_expiry_utc=NOW + timedelta(seconds=60))
        assert pol._validate_inputs(edge, acct, NOW) is None  # == max passes
        future = self._ns_intent(
            evidence_ts_utc=NOW + timedelta(seconds=5.001),
            entry_expiry_utc=NOW + timedelta(seconds=60))
        assert pol._validate_inputs(future, acct, NOW).reason == \
            "stale:future-evidence"
        future_edge = self._ns_intent(
            evidence_ts_utc=NOW + timedelta(seconds=5),
            entry_expiry_utc=NOW + timedelta(seconds=60))
        assert pol._validate_inputs(future_edge, acct, NOW) is None
        # Bad account and stale mark surface through validation.
        assert pol._validate_inputs(
            self._ns_intent(), _account(fee_buffer_usdt=-1.0),
            NOW).reason == "health:nonfinite-account"
        pol3 = _live_policy(tmp_path, max_mark_age_ms=100.0)
        assert pol3._validate_inputs(
            self._ns_intent(), _account(mark_age_ms=101.0),
            NOW).reason == "health:stale-mark"

    def test_kills_policy_validateacct_2_28_matrix(self, tmp_path):
        pol = _live_policy(tmp_path)
        assert pol._validate_account(_account()) is True
        assert pol._validate_account(_account(open_position=True)) is True
        assert pol._validate_account(
            _account(open_position="yes")) is False
        for kw in (dict(reconciled_equity=math.nan),
                   dict(marked_equity=math.inf),
                   dict(net_liquidation=math.nan),
                   dict(net_realised_global=math.nan),
                   dict(flows_cumulative=math.inf),
                   dict(fee_buffer_usdt=-0.01),
                   dict(inflight_exposure_usdt=-1.0),
                   dict(available_margin_usdt=-1.0),
                   dict(available_margin_usdt=math.nan),
                   dict(mark_age_ms=-1.0),
                   dict(mark_age_ms=math.nan)):
            assert pol._validate_account(_account(**kw)) is False, kw
        assert pol._validate_account(
            _account(available_margin_usdt=0.0)) is True
        assert pol._validate_account(
            _account(available_margin_usdt=None)) is True
        assert pol._validate_account(_account(mark_age_ms=0.0)) is True
        assert pol._validate_account(_account(mark_age_ms=None)) is True

    def test_kills_policy_markage_1_8_limits(self, tmp_path):
        pol = _live_policy(tmp_path)
        assert pol._check_mark_age(_account()) is None  # unconfigured
        pol2 = _live_policy(tmp_path, max_mark_age_ms=100.0)
        assert pol2._check_mark_age(_account(mark_age_ms=None)) == \
            "health:mark-age-unknown"
        assert pol2._check_mark_age(_account(mark_age_ms=100.0)) is None
        assert pol2._check_mark_age(_account(mark_age_ms=99.9)) is None
        assert pol2._check_mark_age(_account(mark_age_ms=100.01)) == \
            "health:stale-mark"

    def test_kills_policy_stops_4_36_thresholds(self, tmp_path):
        from cryptobot.accounting.day import accounting_date
        today = accounting_date(NOW).isoformat()
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        # Exact emergency line latches (kills `<=` -> `<`).
        em_line = 10000.0 * (1 - 0.01)
        reason, latched = pol._check_stops(em_line, 10000.0, today, NOW)
        assert (reason, latched) == ("halt:emergency", True)
        assert pol._state.emergency_since_utc == NOW.isoformat()
        reason, latched = pol._check_stops(12000.0, 10000.0, today, NOW)
        assert (reason, latched) == ("halt:emergency", False)
        # Latch persists across reload (structural persist requirement).
        pol2 = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                          now_utc=clock)
        assert pol2._state.emergency_latched is True
        # Operating stop: exact line latches per-day.
        pol3 = RiskPolicy(RiskConfig(), state_path=tmp_path / "b.json",
                          now_utc=clock)
        pol3.reconcile_day(10000.0)
        op_line = 10000.0 * (1 - 0.005)
        reason, latched = pol3._check_stops(op_line, 10000.0, today, NOW)
        assert (reason, latched) == ("halt:operating-stop", True)
        reason, latched = pol3._check_stops(12000.0, 10000.0, today, NOW)
        assert (reason, latched) == ("halt:operating-stop", False)
        # Yesterday's operating stop does not block today; clean passes.
        reason, _ = pol3._check_stops(12000.0, 10000.0, "2000-01-01", NOW)
        assert reason is None
        reason, latched = pol3._check_stops(9999.0, 10000.0, "2000-01-01",
                                            NOW)
        assert (reason, latched) == (None, False)
        # Emergency dominates a simultaneous operating breach.
        pol4 = RiskPolicy(RiskConfig(), state_path=tmp_path / "c.json",
                          now_utc=clock)
        pol4.reconcile_day(10000.0)
        reason, _ = pol4._check_stops(em_line - 100.0, 10000.0, today, NOW)
        assert reason == "halt:emergency"

    def test_kills_policy_filters_9_25_branches(self, tmp_path):
        run = _live_policy(tmp_path, run_mode=True,
                           instrument_filters={"BTCUSDT": COMPLETE},
                           filters_asof_utc=NOW)
        assert run._check_filters(_intent(), NOW) is None
        bare = _live_policy(tmp_path, run_mode=True)
        assert bare._check_filters(_intent(), NOW).reason == \
            "filters:required-in-run-mode"
        assert run._check_filters(_intent(instrument="ETHUSDT"),
                                 NOW).reason == "filters:unknown-instrument"
        incomplete = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                                      min_qty=0.0, max_qty=1000.0,
                                      tick_size=0.1)
        run_inc = _live_policy(tmp_path, run_mode=True,
                               instrument_filters={"BTCUSDT": incomplete},
                               filters_asof_utc=NOW)
        assert run_inc._check_filters(_intent(), NOW).reason == \
            "filters:incomplete"
        # Non-run: no filters -> skip; unknown instrument still rejects.
        plain = _live_policy(tmp_path)
        assert plain._check_filters(_intent(), NOW) is None
        with_filt = _live_policy(tmp_path,
                                 instrument_filters={"BTCUSDT": COMPLETE},
                                 filters_asof_utc=NOW)
        assert with_filt._check_filters(_intent(), NOW) is None
        assert with_filt._check_filters(_intent(instrument="ETHUSDT"),
                                        NOW).reason == \
            "filters:unknown-instrument"
        # Stale metadata (None asof or aged); exact max-age passes.
        stale = _live_policy(tmp_path,
                             instrument_filters={"BTCUSDT": COMPLETE},
                             filters_asof_utc=None)
        assert stale._check_filters(_intent(), NOW).reason == \
            "filters:stale-metadata"
        aged = _live_policy(tmp_path,
                            instrument_filters={"BTCUSDT": COMPLETE},
                            filters_asof_utc=NOW - timedelta(seconds=3600.001))
        assert aged._check_filters(_intent(), NOW).reason == \
            "filters:stale-metadata"
        edge = _live_policy(tmp_path,
                            instrument_filters={"BTCUSDT": COMPLETE},
                            filters_asof_utc=NOW - timedelta(seconds=3600))
        assert edge._check_filters(_intent(), NOW) is None


class TestPolicyLiquidationKills:
    def _plan(self):
        cfg = RiskConfig(instrument_filters={"BTCUSDT": COMPLETE})
        return plan_size(_intent(), 10000.0, cfg)

    def _run_pol(self, tmp_path, **cfg):
        base = dict(run_mode=True,
                    instrument_filters={"BTCUSDT": COMPLETE},
                    filters_asof_utc=NOW)
        base.update(cfg)
        return _live_policy(tmp_path, **base)

    def test_kills_policy_liq_5_12_bracket_presence(self, tmp_path):
        missing = self._run_pol(tmp_path)
        assert missing._check_liquidation(_intent(), self._plan(),
                                          NOW).reason == \
            "brackets:required-in-run-mode"
        other = self._run_pol(tmp_path,
                              leverage_brackets={"ETHUSDT": BRACKETS},
                              brackets_asof_utc=NOW)
        assert other._check_liquidation(_intent(), self._plan(),
                                        NOW).reason == \
            "brackets:unknown-instrument"
        # B#14 paper path: brackets optional -> skip.
        paper = self._run_pol(tmp_path, brackets_required_in_run_mode=False)
        assert paper._check_liquidation(_intent(), self._plan(), NOW) is None
        # Non-run without brackets skips.
        plain = _live_policy(tmp_path)
        assert plain._check_liquidation(_intent(), self._plan(), NOW) is None

    def test_kills_policy_liq_14_20_stale(self, tmp_path):
        no_asof = self._run_pol(tmp_path,
                                leverage_brackets={"BTCUSDT": BRACKETS},
                                brackets_asof_utc=None)
        assert no_asof._check_liquidation(_intent(), self._plan(),
                                          NOW).reason == \
            "brackets:stale-metadata"
        aged = self._run_pol(tmp_path,
                             leverage_brackets={"BTCUSDT": BRACKETS},
                             brackets_asof_utc=NOW - timedelta(seconds=3600.001))
        assert aged._check_liquidation(_intent(), self._plan(),
                                       NOW).reason == \
            "brackets:stale-metadata"
        edge = self._run_pol(tmp_path,
                             leverage_brackets={"BTCUSDT": BRACKETS},
                             brackets_asof_utc=NOW - timedelta(seconds=3600))
        assert edge._check_liquidation(_intent(), self._plan(), NOW) is None

    def test_kills_policy_liq_26_49_tier_and_distance(self, tmp_path):
        ok = self._run_pol(tmp_path, leverage_cap=3.0,
                           leverage_brackets={"BTCUSDT": BRACKETS},
                           brackets_asof_utc=NOW,
                           brackets_max_age_s=3600.0)
        assert ok._check_liquidation(_intent(), self._plan(), NOW) is None
        # SHORT mirrors with signed qty.
        cfg = RiskConfig(instrument_filters={"BTCUSDT": COMPLETE})
        short_plan = plan_size(_intent(Side.SHORT), 10000.0, cfg)
        assert ok._check_liquidation(_intent(Side.SHORT), short_plan,
                                     NOW) is None
        # 20x leverage: liquidation inside 3x -> reject.
        tight = self._run_pol(tmp_path, leverage_cap=20.0,
                              leverage_brackets={"BTCUSDT": BRACKETS},
                              brackets_asof_utc=NOW,
                              brackets_max_age_s=3600.0)
        assert tight._check_liquidation(_intent(), self._plan(),
                                        NOW).reason == \
            "brackets:liquidation-distance"
        # Garbage cum fails the tier pricing closed (config allows any cum).
        junk = self._run_pol(tmp_path,
                             leverage_brackets={"BTCUSDT": [
                                 {"notionalCap": 50000.0,
                                  "maintMarginRatio": 0.004,
                                  "cum": "junk"}]},
                             brackets_asof_utc=NOW)
        assert junk._check_liquidation(_intent(), self._plan(),
                                       NOW).reason == \
            "brackets:invalid-tier"

    def test_kills_policy_liq_61_67_defensive_tier_math(self, tmp_path):
        # Out-of-contract plans fail closed (never raise through the gate).
        ok = self._run_pol(tmp_path,
                           leverage_brackets={"BTCUSDT": BRACKETS},
                           brackets_asof_utc=NOW)
        zero_qty = SimpleNamespace(notional_usdt=100.0, qty=0.0,
                                   adverse_price=101.0)
        assert ok._check_liquidation(_intent(), zero_qty,
                                     NOW).reason == "brackets:invalid-tier"
        bad_side = SimpleNamespace(
            side=SimpleNamespace(value="DIAGONAL"), instrument="BTCUSDT",
            invalidation_price=99.0,
            forecast_cost=ForecastCost(5, 5, 5, 0))
        assert ok._check_liquidation(bad_side, self._plan(),
                                     NOW).reason == "brackets:invalid-tier"

    def test_kills_policy_liq_wiring_stressed_and_margin(self, tmp_path,
                                                         monkeypatch):
        # Gate wiring: stressed slip = slippage_bps * stress_multiplier;
        # isolated margin = notional / leverage_cap; signed qty by side.
        # Kills wiring/operator mutants the approve/reject cases miss.
        import cryptobot.risk.policy as polmod
        seen = {}
        real_ok = polmod.liquidation_ok
        real_liq = polmod.liquidation_price_isolated

        def spy_ok(**kw):
            seen["ok"] = kw
            return real_ok(**kw)

        def spy_liq(**kw):
            seen["liq"] = kw
            return real_liq(**kw)

        monkeypatch.setattr(polmod, "liquidation_ok", spy_ok)
        monkeypatch.setattr(polmod, "liquidation_price_isolated", spy_liq)
        ok = self._run_pol(tmp_path, leverage_cap=3.0,
                           leverage_brackets={"BTCUSDT": BRACKETS},
                           brackets_asof_utc=NOW)
        plan = self._plan()
        assert ok._check_liquidation(_intent(), plan, NOW) is None
        assert seen["ok"]["stressed_slippage_bps"] == 5.0 * 1.5
        assert seen["ok"]["side"] == "LONG"
        assert seen["ok"]["stop"] == 99.0
        assert seen["liq"]["qty"] == plan.qty
        assert seen["liq"]["isolated_margin"] == plan.notional_usdt / 3.0
        cfg = RiskConfig(instrument_filters={"BTCUSDT": COMPLETE})
        short_plan = plan_size(_intent(Side.SHORT), 10000.0, cfg)
        assert ok._check_liquidation(_intent(Side.SHORT), short_plan,
                                     NOW) is None
        assert seen["liq"]["qty"] == -short_plan.qty
        assert seen["ok"]["side"] == "SHORT"


class TestPolicyDayProfitKills:
    def test_kills_policy_reconcile_1_7_fields(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        from cryptobot.accounting.day import accounting_date
        today = accounting_date(NOW).isoformat()
        assert pol.reconcile_day(10000.0, 250.0) == today
        assert pol._state.day_start_equity == 10000.0
        assert pol._state.flow_baseline_day == 250.0
        assert pol._state.needs_reconciliation is False
        assert pol._state.original_equity == 10000.0
        assert pol._state.flow_baseline_inception == 250.0
        # Originals absorb once: later reconciles keep inception values.
        pol.reconcile_day(11000.0, 300.0)
        assert pol._state.original_equity == 10000.0
        assert pol._state.flow_baseline_inception == 250.0
        assert pol._state.day_start_equity == 11000.0
        for bad in (math.nan, math.inf):
            with pytest.raises(ValueError):
                pol.reconcile_day(bad)
            with pytest.raises(ValueError):
                pol.reconcile_day(10000.0, bad)

    def test_kills_policy_roll_3_day(self, tmp_path):
        pol = _live_policy(tmp_path)
        assert pol._roll_day_if_needed(NOW, pol._state.current_day) is False
        assert pol._roll_day_if_needed(NOW + timedelta(days=2),
                                       "2099-01-01") is True
        assert pol._state.current_day == "2099-01-01"
        assert pol._state.needs_reconciliation is True

    def test_kills_policy_adjust_1_6_baselines(self, tmp_path):
        pol = _live_policy(tmp_path)
        pol._state.flow_baseline_day = 20.0
        pol._state.flow_baseline_inception = 100.0
        assert pol._adjust_day(100.0, 50.0) == 70.0
        assert pol._adjust_inception(1000.0, 150.0) == 950.0
        pol._state.flow_baseline_day = None
        pol._state.flow_baseline_inception = None
        assert pol._adjust_day(100.0, 50.0) == 50.0
        assert pol._adjust_inception(1000.0, 150.0) == 850.0

    def test_kills_policy_profit_3_32_ratchet(self, tmp_path):
        pol = _live_policy(tmp_path)
        # No original equity: never armed, never halts.
        pol._state.original_equity = None
        assert pol._update_profit_protection(_account()) is False
        assert pol._state.profit_floor is None
        pol._state.original_equity = 10000.0
        # Below the arm line: no floor even at peak.
        assert pol._update_profit_protection(
            _account(net_realised_global=50.0,
                     marked_equity=10000.0)) is False
        assert pol._state.peak_realised == 50.0
        assert pol._state.profit_floor is None
        # Arm at 1%: floor = original + 70% of peak.
        assert pol._update_profit_protection(
            _account(net_realised_global=1000.0,
                     marked_equity=12000.0)) is False
        assert pol._state.profit_floor == pytest.approx(10700.0)
        # Floor only ratchets up, never down.
        assert pol._update_profit_protection(
            _account(net_realised_global=500.0,
                     marked_equity=12000.0)) is False
        assert pol._state.profit_floor == pytest.approx(10700.0)
        assert pol._state.peak_realised == 1000.0
        # Breach at the floor halts.
        assert pol._update_profit_protection(
            _account(net_realised_global=1000.0,
                     marked_equity=pol._state.profit_floor)) is True
        # Inception flows back out before the comparison.
        pol._state.flow_baseline_inception = 0.0
        assert pol._update_profit_protection(
            _account(net_realised_global=1000.0, marked_equity=10800.0,
                     flows_cumulative=200.0)) is True  # 10600 <= floor

    def test_kills_policy_profit_save_only_on_change(self, tmp_path,
                                                     monkeypatch):
        # Equal peak / equal floor persist nothing (kills `>` -> `>=`).
        import cryptobot.risk.policy as polmod
        calls = []
        real_save = polmod.save_state

        def counting_save(path, state):
            calls.append(path)
            return real_save(path, state)

        monkeypatch.setattr(polmod, "save_state", counting_save)
        pol = _live_policy(tmp_path)
        calls.clear()  # drop the reconcile_day save
        pol._update_profit_protection(_account(net_realised_global=1000.0,
                                              marked_equity=12000.0))
        assert len(calls) == 1  # peak + floor set
        pol._update_profit_protection(_account(net_realised_global=1000.0,
                                              marked_equity=12000.0))
        assert len(calls) == 1  # equal values: no write
        pol._update_profit_protection(_account(net_realised_global=500.0,
                                              marked_equity=12000.0))
        assert len(calls) == 1  # lower peak: no write

    def test_kills_policy_move_4_10_unresolved(self, tmp_path):
        pol = _live_policy(tmp_path)
        out = pol.evaluate(_intent(), _account())
        rid = out.reservation_id
        pol._move_to_unresolved(rid, NOW)
        assert rid not in pol.live_reservations()
        entry = pol._state.unresolved[rid]
        assert entry["reservation"]["instrument"] == "BTCUSDT"
        assert entry["reservation"]["qty"] == out.qty
        assert entry["unresolved_since_utc"] == NOW.isoformat()
        pol._move_to_unresolved("ghost", NOW)  # unknown: no-op
        assert "ghost" not in pol._state.unresolved

    def test_kills_policy_init_7_16_defaults(self, tmp_path):
        pol = RiskPolicy(state_path=tmp_path / "risk.json",
                         now_utc=_Clock(NOW))
        assert pol.config == RiskConfig()
        assert pol._executable == {}
        assert pol._last_tick_save_mono == 0.0
        assert pol._tick_dirty is False
        assert pol._ledger is None
        from pathlib import Path as _Path
        assert pol.state_path == _Path(tmp_path / "risk.json")

    def test_kills_policy_executable_1_17_narrow(self, tmp_path):
        pol = _live_policy(tmp_path)
        out = pol.evaluate(_intent(), _account())
        rid = out.reservation_id
        assert pol.required_stop_qty(rid) == out.qty
        for bad_qty in (0.0, -1.0, math.nan, math.inf, "5.0"):
            assert pol.note_executable_qty(rid, bad_qty) is False
        assert pol.note_executable_qty("unknown", 5.0) is False
        assert pol.note_executable_qty(rid, 5.0) is True
        assert pol.required_stop_qty(rid) == 5.0
        assert pol.note_executable_qty(rid, 4.5) is True  # last wins
        assert pol.required_stop_qty(rid) == 4.5
        assert pol.required_stop_qty("unknown") is None
        # Unresolved ids stay narrowable; release pops the narrowing.
        pol.note_fill(rid)
        pol.note_fill_delta(rid, "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            NOW.isoformat())
        assert pol.booked_reservations() == (rid,)
        assert pol.live_reservations() == ()  # converted by note_fill

    def test_kills_policy_live_1_6_settles(self, tmp_path):
        clock = _Clock(NOW)
        pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                         now_utc=clock)
        pol.reconcile_day(10000.0)
        out = pol.evaluate(_intent(), _account())
        assert pol.live_reservations() == (out.reservation_id,)
        clock.now = NOW + timedelta(seconds=61)
        assert pol.live_reservations() == ()  # settled + saved
        assert out.reservation_id in pol.unresolved_ids()
        pol2 = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                          now_utc=clock)
        assert out.reservation_id in pol2.unresolved_ids()

    def test_kills_policy_stopactions_1_24_derived(self, tmp_path):
        from cryptobot.accounting.day import accounting_date
        today = accounting_date(NOW).isoformat()
        pol = _live_policy(tmp_path)
        assert pol.operating_stopped() is False
        assert pol.operating_stopped("2000-01-01") is False
        assert pol.pending_stop_actions() == ()
        assert pol.pending_stop_actions(_account()) == ()
        # Operating stop + exposure -> cancel + reduce.
        pol._state.operating_stop_days[today] = "operating-stop"
        assert pol.operating_stopped() is True
        assert pol.operating_stopped(today) is True
        assert pol.pending_stop_actions(_account(open_position=True)) == (
            "cancel_pending_orders", "reduce_exposure")
        # No exposure anywhere -> no action demands.
        assert pol.pending_stop_actions() == ()
        assert pol.pending_stop_actions(_account()) == ()
        # Emergency adds the operator alert, keeps exposure actions.
        pol._state.emergency_latched = True
        assert pol.pending_stop_actions() == ("alert_operator",)
        assert pol.pending_stop_actions(_account(open_position=True)) == (
            "alert_operator", "cancel_pending_orders", "reduce_exposure")
        # Reservations/unresolved/booked/state exposure all count.
        pol._state.emergency_latched = False
        pol2 = _live_policy(tmp_path)
        pol2._state.operating_stop_days[today] = "operating-stop"
        pol2.note_fill("ghost")  # state exposure, no reservation
        assert pol2.pending_stop_actions() == (
            "cancel_pending_orders", "reduce_exposure")

    def test_kills_policy_recover_1_15_emergency(self, tmp_path):
        pol = _live_policy(tmp_path)
        assert pol.recover_from_emergency(_account()) is True  # no latch
        out = pol.evaluate(_intent(), _account())
        assert isinstance(out, Approved)
        pol._state.emergency_latched = True
        pol._state.emergency_since_utc = NOW.isoformat()
        # Each exposure kind refuses recovery.
        assert pol.recover_from_emergency(_account()) is False
        pol.release(out.reservation_id)
        pol.note_fill("ghost")
        assert pol.recover_from_emergency(_account()) is False
        pol._state.open_position = False
        pol.note_fill_delta("r-x", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.1,
                            NOW.isoformat())
        assert pol.recover_from_emergency(_account()) is False
        pol._state.booked["r-x"]["net_qty"] = 0.0
        assert pol.recover_from_emergency(
            _account(open_position=True)) is False
        # Reconciled flat recovers and persists the clear.
        assert pol.recover_from_emergency(_account()) is True
        assert pol._state.emergency_latched is False
        assert pol._state.emergency_since_utc is None
        pol2 = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json",
                          now_utc=_Clock(NOW))
        assert pol2._state.emergency_latched is False

    def test_kills_policy_funding_1_38_sink(self, tmp_path):
        pol = _live_policy(tmp_path)
        ts = NOW.isoformat()
        with pytest.raises(ValueError):
            pol.note_funding("f1", -5.0, ts)  # unbound: fail closed
        ledger = Ledger(10000.0)
        pol.bind_ledger(ledger)
        for bad_id in ("", None, 9):
            with pytest.raises(ValueError):
                pol.note_funding(bad_id, -5.0, ts)
        with pytest.raises(ValueError):
            pol.note_funding("f1", math.nan, ts)
        for bad_ts in ("2026-10-17T12:00:00", "junk",
                       "2026-10-17T12:00:00+05:30", None):
            with pytest.raises(ValueError):
                pol.note_funding("f1", -5.0, bad_ts)
        assert pol.note_funding("f1", -5.0, ts, symbol="BTCUSDT") is None
        assert ledger.funding_net() == -5.0
        assert ledger._funding[0].symbol == "BTCUSDT"
        assert ledger._funding[0].event_id == "f1"
        assert pol.note_funding("f1", -5.0, ts) is None  # idempotent
        assert ledger.funding_net() == -5.0
        run = _live_policy(tmp_path, run_mode=True)
        run.bind_ledger(Ledger(10000.0))
        with pytest.raises(ValueError):
            run.note_funding("f0", 0.0, ts)
        assert run.note_funding("f2", 2.5, ts) is None


# =========================================================================
# order_manager (f1.2-ordermanager: 760 survived)
# =========================================================================

class TestOrderManagerSubmitKills:
    def test_kills_ordmgr_venue_7_8_mapping(self):
        from cryptobot.execution.order_manager import _venue_state_to_local
        assert _venue_state_to_local("NEW") == OrderState.OPEN
        assert _venue_state_to_local("PARTIALLY_FILLED") == OrderState.PARTIAL
        assert _venue_state_to_local("FILLED") == OrderState.FILLED
        assert _venue_state_to_local("REJECTED") == OrderState.REJECTED
        assert _venue_state_to_local("CANCELLED") == OrderState.CANCELLED
        with pytest.raises(KeyError):
            _venue_state_to_local("BOGUS")

    def test_kills_ordmgr_init_6_27_defaults(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        assert mgr.exit_only is False
        assert mgr.outcome_sink is None
        assert mgr.expiry_settle_polls == 2
        assert mgr.orders == {}
        assert mgr._seq == 0
        nested = tmp_path / "a" / "b" / "orders.jsonl"
        mgr2 = OrderManager(FakeVenue(), log_path=nested,
                            now_utc=lambda: NOW, exit_only=True,
                            outcome_sink=_Sink(), expiry_settle_polls=5)
        assert nested.parent.is_dir()
        assert mgr2.exit_only is True
        assert isinstance(mgr2.outcome_sink, _Sink)
        assert mgr2.expiry_settle_polls == 5

    def test_kills_ordmgr_cid_4_14_format_unique(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        first = mgr.new_client_id()
        assert re.fullmatch(r"w2-000001-[0-9a-f]{8}", first), first
        assert mgr.new_client_id("zz").startswith("zz-000002-")
        ids = {mgr.new_client_id() for _ in range(500)}
        assert len(ids) == 500

    def test_kills_ordmgr_cid_5_13_collision_bound(self, tmp_path, monkeypatch):
        monkeypatch.setattr(uuid, "uuid4",
                            lambda: SimpleNamespace(hex="ab" * 32))
        mgr = _manager(FakeVenue(), tmp_path)
        # 99 consecutive collisions then success on the 100th draw.
        for i in range(1, 100):
            mgr._minted_ids.add(f"w2-{i:06d}-abababab")
        assert mgr.new_client_id() == "w2-000100-abababab"
        # 100 consecutive collisions raise (kills range/condition mutants).
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        for i in range(1, 101):
            mgr2._minted_ids.add(f"w2-{i:06d}-abababab")
        with pytest.raises(RuntimeError,
                           match=r"^new_client_id: 100 consecutive collisions$"):
            mgr2.new_client_id()

    def test_kills_ordmgr_entry_4_14_side_threading(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        long = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                expire_at_utc=NOW + timedelta(seconds=60),
                                kind="STOP_MARKET", reservation_id="r-1")
        assert long.venue_side == "BUY"
        assert long.reservation_id == "r-1"
        short = mgr.submit_entry("BTCUSDT", "SHORT", 0.01, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET", reservation_id="r-2")
        assert short.venue_side == "SELL"
        assert short.reservation_id == "r-2"
        with pytest.raises(KeyError):
            mgr.submit_entry("BTCUSDT", "DIAGONAL", 0.01, 1.0,
                             expire_at_utc=NOW + timedelta(seconds=60))

    def test_kills_ordmgr_entry_4_exit_only_msg(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path, exit_only=True)
        with pytest.raises(PermissionError,
                           match=r"^exit-only mode refuses new entries$"):
            mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                             expire_at_utc=NOW + timedelta(seconds=60))

    def test_kills_ordmgr_entry_12_30_wiring(self, tmp_path):
        sink = _Sink()
        mgr = _manager(FakeVenue(), tmp_path, outcome_sink=sink)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.5, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 reservation_id="r-7")
        assert order.symbol == "BTCUSDT"
        assert order.qty == 0.5
        assert order.price == 67005.0
        assert order.kind == "LIMIT"
        assert order.role == "entry"
        assert order.retry_of is None
        assert order.expire_at_utc == NOW + timedelta(seconds=60)
        assert order.state == OrderState.FILLED  # immediate LIMIT fill
        assert sink.fills == ["r-7"]  # callbacks evaluated on submit

    def test_kills_ordmgr_retry_3_bound(self, tmp_path):
        venue = FakeVenue()
        for _ in range(3):
            venue.fail_next_submit("timeout", received=False)
        mgr = _manager(venue, tmp_path)
        order = mgr.submit_with_retry(
            "BTCUSDT", "LONG", 0.01, 1.0,
            expire_at_utc=NOW + timedelta(seconds=60))
        intents = [r for r in _journal(tmp_path)
                   if r["event"] == "submit-intent"]
        assert len(intents) == 3  # initial + max_retries(2); kills 2->3
        assert order.state == OrderState.AMBIGUOUS
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        mgr2.venue.fail_next_submit("timeout", received=False)
        order2 = mgr2.submit_with_retry(
            "BTCUSDT", "LONG", 0.01, 1.0,
            expire_at_utc=NOW + timedelta(seconds=60), max_retries=0)
        assert order2.state == OrderState.AMBIGUOUS
        assert len([r for r in _journal(tmp_path, "b.jsonl")
                    if r["event"] == "submit-intent"]) == 1

    def test_kills_ordmgr_retry_8_26_same_reservation(self, tmp_path):
        venue = FakeVenue()
        venue.set_last_price("BTCUSDT", 67000.0)
        venue.fail_next_submit("timeout", received=False)
        mgr = _manager(venue, tmp_path)
        order = mgr.submit_with_retry(
            "BTCUSDT", "LONG", 0.01, 67005.0,
            expire_at_utc=NOW + timedelta(seconds=60), reservation_id="r-9")
        assert order.state == OrderState.FILLED
        assert order.retry_of is not None
        assert order.retry_of != order.client_id
        assert order.reservation_id == "r-9"  # same reservation, new ID
        assert order.venue_side == "BUY"  # retried side preserved
        assert order.role == "entry"
        assert order.kind == "LIMIT"
        assert order.expire_at_utc == NOW + timedelta(seconds=60)
        assert venue.query(order.retry_of) is None
        # Adopted path keeps the original ID and reservation.
        venue2 = FakeVenue()
        venue2.set_last_price("BTCUSDT", 67000.0)
        venue2.fail_next_submit("timeout", received=True)
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl")
        adopted = mgr2.submit_with_retry(
            "BTCUSDT", "LONG", 0.01, 67005.0,
            expire_at_utc=NOW + timedelta(seconds=60), reservation_id="r-3")
        assert adopted.retry_of is None
        assert adopted.reconciled is True
        assert adopted.reservation_id == "r-3"
        assert adopted.expire_at_utc == NOW + timedelta(seconds=60)
        assert len([r for r in _journal(tmp_path, "b.jsonl")
                    if r["event"] == "submit-intent"]) == 1
        # Non-default kind threads through the retry submit.
        venue4 = FakeVenue()
        venue4.fail_next_submit("timeout", received=False)
        mgr4 = _manager(venue4, tmp_path, filename="d.jsonl")
        stop_retry = mgr4.submit_with_retry(
            "BTCUSDT", "LONG", 0.01, 67005.0,
            expire_at_utc=NOW + timedelta(seconds=60), kind="STOP_MARKET")
        assert stop_retry.retry_of is not None
        assert stop_retry.kind == "STOP_MARKET"
        assert stop_retry.expire_at_utc == NOW + timedelta(seconds=60)
        # The FIRST attempt keeps the requested kind too (kills the
        # dropped-kind mutant on the initial submit_entry call).
        first = mgr4.orders[stop_retry.retry_of]
        assert first.kind == "STOP_MARKET"
        # Immediate fill: no reconcile loop at all.
        mgr3 = _manager(venue2, tmp_path, filename="c.jsonl")
        direct = mgr3.submit_with_retry(
            "BTCUSDT", "LONG", 0.01, 67005.0,
            expire_at_utc=NOW + timedelta(seconds=60))
        assert direct.reconciled is False

    def test_kills_ordmgr_submit_1_role_default(self, tmp_path):
        # _submit's role default is "entry" (pins the signature default).
        mgr = _manager(FakeVenue(), tmp_path)
        order = mgr._submit("BTCUSDT", "BUY", 0.5, "LIMIT", price=10.0)
        assert order.role == "entry"

    def test_kills_ordmgr_submit_5_minted(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        assert order.client_id in mgr._minted_ids  # kills add(None)
        assert None not in mgr._minted_ids

    def test_kills_ordmgr_submit_6_33_intent_shape(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.5, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET", reservation_id="r-1")
        rec = _journal(tmp_path)[0]
        assert rec["client_id"] == order.client_id
        assert rec["event"] == "submit-intent"
        assert rec["detail"] == {
            "symbol": "BTCUSDT", "venue_side": "BUY", "kind": "STOP_MARKET",
            "qty": 0.5, "price": 67005.0, "stop_price": None,
            "role": "entry", "group_id": "", "retry_of": None,
            "reservation_id": "r-1"}
        assert rec["order"] == {}  # intent precedes registration

    def test_kills_ordmgr_submit_38_57_order_fields(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        entry = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60))
        assert entry.kind == "LIMIT"
        assert entry.price == 10.0
        assert entry.stop_price is None
        assert entry.role == "entry"
        stop, target = mgr.attach_siblings(entry, stop_price=9.0,
                                           target_price=11.0)
        assert (stop.kind, stop.price, stop.stop_price, stop.role) == \
            ("STOP_MARKET", None, 9.0, "stop")
        assert (target.kind, target.price, target.stop_price,
                target.role) == ("TAKE_PROFIT_MARKET", None, 11.0, "target")

    def test_kills_ordmgr_submit_79_100_timeout_reject_shape(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("timeout", received=False,
                               reason="boom-timeout")
        mgr = _manager(venue, tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60))
        assert order.state == OrderState.AMBIGUOUS
        rec = _journal(tmp_path)[1]
        assert rec["client_id"] == order.client_id
        assert rec["event"] == "submit-timeout-ambiguous"
        assert rec["detail"] == {"reason": "boom-timeout"}
        venue2 = FakeVenue()
        venue2.fail_next_submit("reject", reason="no-margin")
        sink = _Sink()
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl",
                        outcome_sink=sink)
        rej = mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                expire_at_utc=NOW + timedelta(seconds=60),
                                reservation_id="r-1")
        assert rej.state == OrderState.REJECTED
        recs = _journal(tmp_path, "b.jsonl")
        assert recs[1]["client_id"] == rej.client_id
        assert recs[1]["event"] == "rejected"
        assert recs[1]["detail"] == {"reason": "no-margin"}
        assert sink.releases == ["r-1"]  # callbacks evaluated on reject

    def test_kills_ordmgr_submit_102_113_submitted_shape(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        rec = _journal(tmp_path)[1]
        assert rec["client_id"] == order.client_id
        assert rec["event"] == "submitted"
        assert rec["detail"] == {"reason": "accepted", "state": "open"}


class TestOrderManagerAttachReconcileKills:
    def test_kills_ordmgr_attach_1_4_requires_fills(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        entry = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        with pytest.raises(ValueError,
                           match=r"^siblings attach only to an entry with fills$"):
            mgr.attach_siblings(entry, stop_price=9.0, target_price=11.0)

    def test_kills_ordmgr_attach_7_9_frozen(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path, outcome_sink=_Sink())
        entry = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 reservation_id="r-1")
        stop, target = mgr.attach_siblings(entry, stop_price=9.0,
                                           target_price=11.0)
        venue.inject_fill(stop.client_id, 1.0, 9.0)
        venue.inject_fill(target.client_id, 1.0, 11.0)
        mgr.poll()  # exit race -> overfill freeze
        assert "r-1" in mgr._exit_frozen
        rec = [r for r in _journal(tmp_path)
               if r["event"] == "exit-overfill"][0]
        assert rec["client_id"] == "*"
        assert rec["detail"] == {
            "reservation_id": "r-1", "net": -1.0,
            "reason": "venue-side exit race; exits frozen, "
                      "no compounding orders"}
        with pytest.raises(ValueError,
                           match=r"^exits frozen after overfill; no new legs$"):
            mgr.attach_siblings(entry, stop_price=9.0, target_price=11.0)

    def test_kills_ordmgr_attach_8_19_sizing(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("partial", fractions=(0.4, 0.6))
        mgr = _manager(venue, tmp_path)
        part = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                expire_at_utc=NOW + timedelta(seconds=60),
                                reservation_id="r-1")
        assert part.filled_qty == pytest.approx(0.4)
        stop, target = mgr.attach_siblings(part, stop_price=9.0,
                                           target_price=11.0)
        assert stop.qty == pytest.approx(0.4)  # sized to FILLED qty
        assert target.qty == pytest.approx(0.4)
        assert stop.venue_side == "SELL"  # exit side flips
        # Net cap: partial exit filled -> second attach sizes to |net|.
        venue2 = FakeVenue()
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl")
        entry = mgr2.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                  expire_at_utc=NOW + timedelta(seconds=60),
                                  reservation_id="r-2")
        mgr2.attach_siblings(entry, stop_price=9.0, target_price=11.0)
        legs = [o for o in mgr2.orders.values() if o.role == "stop"]
        venue2.inject_fill(legs[0].client_id, 0.5, 9.0)
        mgr2.poll()
        stop2, _ = mgr2.attach_siblings(entry, stop_price=9.0,
                                        target_price=11.0)
        assert stop2.qty == pytest.approx(0.5)
        # SHORT entry -> BUY legs.
        mgr3 = _manager(FakeVenue(), tmp_path, filename="c.jsonl")
        short = mgr3.submit_entry("BTCUSDT", "SHORT", 1.0, 10.0,
                                  expire_at_utc=NOW + timedelta(seconds=60))
        stop3, _ = mgr3.attach_siblings(short, stop_price=11.0,
                                        target_price=9.0)
        assert stop3.venue_side == "BUY"

    def test_kills_ordmgr_attach_25_83_group_verify(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        entry = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 reservation_id="r-1")
        stop, target = mgr.attach_siblings(entry, stop_price=9.0,
                                           target_price=11.0)
        assert stop.group_id == f"grp-{entry.client_id}"
        assert target.group_id == f"grp-{entry.client_id}"
        assert stop.reservation_id == "r-1"
        assert target.reservation_id == "r-1"
        assert stop.reconciled is True  # independently verified
        assert target.reconciled is True
        # Filled but net-zero -> nothing left to protect.
        venue = mgr.venue
        venue.inject_fill(stop.client_id, 1.0, 9.0)
        mgr.poll()
        with pytest.raises(
                ValueError,
                match=r"^nothing to protect: no unprotected filled quantity$"):
            mgr.attach_siblings(entry, stop_price=9.0, target_price=11.0)

    def test_kills_ordmgr_reconcile_7_28_unknown_void(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("timeout", received=False)
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 reservation_id="r-1")
        assert mgr.reconcile(order.client_id) is None
        assert order.state == OrderState.CANCELLED
        assert order.reconciled is True
        assert order.venue_known is False
        rec = [r for r in _journal(tmp_path)
               if r["event"] == "reconciled-unknown-void"]
        assert len(rec) == 1 and rec[0]["client_id"] == order.client_id
        assert rec[0]["detail"] == {}
        assert sink.releases == ["r-1"]  # callbacks evaluated
        # Terminal + unknown: state kept, distinct record.
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        filled = mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                   expire_at_utc=NOW + timedelta(seconds=60))
        mgr2.venue._orders.pop(filled.client_id)
        assert mgr2.reconcile(filled.client_id) is None
        assert filled.state == OrderState.FILLED
        rec = [r for r in _journal(tmp_path, "b.jsonl")
               if r["event"] == "reconciled-unknown"][0]
        assert rec["client_id"] == filled.client_id
        assert rec["detail"] == {"state": "filled"}

    def test_kills_ordmgr_reconcile_35_44_known_adopt(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("partial", fractions=(0.4, 0.6))
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        order = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 reservation_id="r-1")
        venue.settle()
        view = mgr.reconcile(order.client_id)
        assert view is not None and view.status == "FILLED"
        assert order.state == OrderState.FILLED
        assert order.venue_known is True
        rec = [r for r in _journal(tmp_path) if r["event"] == "reconciled"]
        assert len(rec) == 1
        assert rec[0]["client_id"] == order.client_id
        assert rec[0]["detail"] == {"state": "filled"}
        assert [d[4] for d in sink.deltas] == pytest.approx([0.4, 0.6])
        assert sink.fills == ["r-1"]

    def test_kills_ordmgr_fire_2_36_dispatch(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)  # no sink
        assert mgr._fire("fill", "r-1", "x") is False
        with pytest.raises(ValueError, match=r"^unknown callback kind"):
            _manager(FakeVenue(), tmp_path, filename="b.jsonl",
                     outcome_sink=_Sink())._fire("bogus", "r-1", "x")
        venue = FakeVenue()
        venue.fail_next_submit("reject", reason="nope")
        sink = _Sink()
        mgr2 = _manager(venue, tmp_path, filename="c.jsonl",
                        outcome_sink=sink)
        mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                          expire_at_utc=NOW + timedelta(seconds=60),
                          reservation_id="r-1")
        assert sink.releases == ["r-1"]
        rec = [r for r in _journal(tmp_path, "c.jsonl")
               if r["event"] == "callback-fired"][0]
        assert rec["client_id"] == "*"
        assert rec["detail"]["kind"] == "release"
        assert rec["detail"]["reservation_id"] == "r-1"
        assert "(sink freed: True)" in rec["detail"]["reason"]
        # Exactly once: second evaluation fires nothing new.
        assert mgr2._evaluate_callbacks() == []
        assert sink.releases == ["r-1"]


class TestOrderManagerPositionCallbacksKills:
    def _long_position(self, tmp_path, filename="orders.jsonl"):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path, filename=filename)
        entry = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 reservation_id="r-1")
        stop, target = mgr.attach_siblings(entry, stop_price=9.0,
                                           target_price=11.0)
        return venue, mgr, entry, stop, target

    def test_kills_ordmgr_position_4_38_signs(self, tmp_path):
        venue, mgr, entry, stop, target = self._long_position(tmp_path)
        assert mgr._position_state("r-1") == (1.0, 0.0, 1.0, False)
        assert mgr.position_net("r-1") == 1.0
        venue.inject_fill(stop.client_id, 0.4, 9.0)
        mgr.poll()
        entry_net, exit_net, net, overfilled = mgr._position_state("r-1")
        assert (entry_net, exit_net, net) == pytest.approx((1.0, -0.4, 0.6))
        assert overfilled is False
        # SHORT mirror: entry SELL subtracts, BUY legs add.
        venue2 = FakeVenue()
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl")
        short = mgr2.submit_entry("BTCUSDT", "SHORT", 1.0, 10.0,
                                  expire_at_utc=NOW + timedelta(seconds=60),
                                  reservation_id="r-s")
        stop2, _ = mgr2.attach_siblings(short, stop_price=11.0,
                                        target_price=9.0)
        venue2.inject_fill(stop2.client_id, 0.3, 11.0)
        mgr2.poll()
        got = mgr2._position_state("r-s")
        assert got[:3] == pytest.approx((-1.0, 0.3, -0.7))
        assert got[3] is False
        assert mgr2.position_net("ghost") == 0.0

    def test_kills_ordmgr_position_38_overfill(self, tmp_path):
        venue, mgr, entry, stop, target = self._long_position(tmp_path)
        venue.inject_fill(stop.client_id, 1.0, 9.0)
        venue.inject_fill(target.client_id, 1.0, 11.0)
        mgr.poll()
        _, _, net, overfilled = mgr._position_state("r-1")
        assert net == pytest.approx(-1.0)
        assert overfilled is True
        # Zero entry or zero net never counts as overfilled.
        assert mgr._position_state("nobody") == (0.0, 0.0, 0.0, False)

    def test_kills_ordmgr_resolved_1_6_either(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path, outcome_sink=_Sink())
        assert mgr._reservation_resolved("r-1") is False
        mgr._callbacks_fired.add(("release", "r-1"))
        assert mgr._reservation_resolved("r-1") is True  # kills or->and
        mgr._callbacks_fired.discard(("release", "r-1"))
        mgr._callbacks_fired.add(("flat", "r-1"))
        assert mgr._reservation_resolved("r-1") is True
        mgr._callbacks_fired.add(("fill", "r-2"))
        assert mgr._reservation_resolved("r-2") is False

    def test_kills_ordmgr_evalcb_24_70_release_fill_flat(self, tmp_path):
        # Zero-fill terminal -> release.
        venue = FakeVenue()
        venue.fail_next_submit("reject", reason="nope")
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         reservation_id="r-1")
        assert sink.releases == ["r-1"]
        # First nonzero fill converts (fill-first); flat on reconciled zero.
        venue2 = FakeVenue()
        sink2 = _Sink()
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl",
                        outcome_sink=sink2)
        entry = mgr2.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                  expire_at_utc=NOW + timedelta(seconds=60),
                                  reservation_id="r-2")
        assert sink2.fills == ["r-2"]
        stop, _ = mgr2.attach_siblings(entry, stop_price=9.0,
                                       target_price=11.0)
        venue2.inject_fill(stop.client_id, 1.0, 9.0)
        mgr2.poll()
        assert sink2.flats == 1
        # The flat callback is journaled exactly once (the settle-time
        # reconcile fires it; poll's returned list carries only the
        # sibling event -- the sink call is the money-critical effect).
        flats = [r for r in _journal(tmp_path, "b.jsonl")
                 if r["event"] == "callback-fired"
                 and r["detail"]["kind"] == "flat"]
        assert len(flats) == 1
        assert flats[0]["detail"]["reservation_id"] == "r-2"
        assert flats[0]["detail"]["reason"] == "reconciled-net-zero"
        assert sink2.fills == ["r-2"]  # fill fired exactly once
        # No sink -> no events, no crash.
        mgr3 = _manager(FakeVenue(), tmp_path, filename="c.jsonl")
        assert mgr3._evaluate_callbacks() == []

    def test_kills_ordmgr_evalcb_70_unsettled_blocks(self, tmp_path):
        venue = FakeVenue()
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         kind="STOP_MARKET", reservation_id="r-1")
        mgr.poll(NOW + timedelta(seconds=61))  # expires, settle 0
        assert sink.releases == []
        mgr.poll(NOW + timedelta(seconds=62))  # settle 1
        assert sink.releases == []
        mgr.poll(NOW + timedelta(seconds=63))  # settle 2 -> released
        assert sink.releases == ["r-1"]
        # expiry_settle_polls=0 releases on the first post-expiry poll.
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl",
                        outcome_sink=_Sink(), expiry_settle_polls=0)
        mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                          expire_at_utc=NOW + timedelta(seconds=60),
                          kind="STOP_MARKET", reservation_id="r-9")
        mgr2.poll(NOW + timedelta(seconds=61))
        assert mgr2.outcome_sink.releases == ["r-9"]

    def test_kills_ordmgr_evalcb_74_117_sorted_once(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("reject", reason="a")
        venue.fail_next_submit("reject", reason="b")
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         reservation_id="b")
        mgr._evaluate_callbacks()
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         reservation_id="a")
        # Both fired exactly once across the two submits.
        assert sorted(sink.releases) == ["a", "b"]
        assert len(sink.releases) == 2
        assert mgr._evaluate_callbacks() == []

    def test_kills_ordmgr_halt_1_18_level(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        mgr.set_halted(True, "risk-stop")
        assert mgr.exit_only is True
        recs = _journal(tmp_path)
        assert recs[-1]["client_id"] == "*"
        assert recs[-1]["event"] == "halt-engaged"
        assert recs[-1]["detail"] == {"reason": "risk-stop"}
        # Default reason is "" (kills the default-value mutant).
        mgr.set_halted(False)
        assert _journal(tmp_path)[-1]["detail"] == {"reason": ""}
        mgr.set_halted(True)
        n_before = len(_journal(tmp_path))
        mgr.set_halted(True, "again")  # steady state: no record
        assert len(_journal(tmp_path)) == n_before
        mgr.set_halted(False, "lift")
        assert mgr.exit_only is False
        assert _journal(tmp_path)[-1]["client_id"] == "*"
        assert _journal(tmp_path)[-1]["event"] == "halt-cleared"
        mgr.set_halted(True)
        mgr.clear_halt_via_reconciliation()
        assert mgr.exit_only is False
        assert _journal(tmp_path)[-1]["client_id"] == "*"
        assert _journal(tmp_path)[-1]["detail"] == \
            {"reason": "cleared-via-reconciliation"}


class TestOrderManagerPollSettleKills:
    def test_kills_ordmgr_poll_6_24_skip_rejected_only(self, tmp_path):
        # REJECTED orders are never re-read (rejected can never fill).
        # NOTE: resolved reservations ARE still read (late fills adopted);
        # only expiry actions are skipped post-resolution (F1.2 poll fix).
        venue = FakeVenue()
        venue.fail_next_submit("reject", reason="nope")
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         reservation_id="r-1")
        assert sink.releases == ["r-1"]  # resolved
        calls = []
        orig = venue.query
        venue.query = lambda cid: (calls.append(cid), orig(cid))[1]
        try:
            mgr.poll()
        finally:
            venue.query = orig
        assert calls == []  # resolved reservation: no venue reads
        # Bare REJECTED (no reservation) is likewise never re-read.
        venue2 = FakeVenue()
        venue2.fail_next_submit("reject", reason="nope")
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl")
        mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                          expire_at_utc=NOW + timedelta(seconds=60))
        calls2 = []
        orig2 = venue2.query
        venue2.query = lambda cid: (calls2.append(cid), orig2(cid))[1]
        try:
            mgr2.poll()
        finally:
            venue2.query = orig2
        assert calls2 == []

    def test_kills_ordmgr_poll_30_54_late_fill(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)  # no sink: never resolved
        order = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=600),
                                 kind="STOP_MARKET", reservation_id="r-1")
        venue.cancel(order.client_id)
        first = mgr.poll()  # adopts CANCELLED
        assert order.state == OrderState.CANCELLED
        assert order.venue_known is True  # known-adopt flags (poll_21_24)
        assert order.reconciled is True
        assert {"client_id": order.client_id,
                "event": "state:open->cancelled"} in first
        venue.inject_fill(order.client_id, 1.0, 10.0)  # cancel race: full
        events = mgr.poll()
        assert {"client_id": order.client_id,
                "event": "late-fill-booked"} in events
        deltas = [r for r in _journal(tmp_path)
                  if r["event"] == "fill-delta"]
        assert len(deltas) == 1
        assert deltas[0]["detail"]["qty_delta"] == pytest.approx(1.0)

    def test_kills_ordmgr_poll_6_cancelled_late_fill_released(self, tmp_path):
        # F1.2 REAL-BUG, FIXED in poll(): venue-cancelled entry releases
        # at zero fills; a raced fill landing after the release still
        # books + propagates + converts (resolved reservations keep
        # their venue reads; only expiry actions are skipped).
        venue = FakeVenue()
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        order = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=600),
                                 kind="STOP_MARKET", reservation_id="r-1")
        venue.cancel(order.client_id)
        mgr.poll()
        assert sink.releases == ["r-1"]
        venue.inject_fill(order.client_id, 1.0, 10.0)
        events = mgr.poll()
        assert [d[4] for d in sink.deltas] == pytest.approx([1.0])
        assert sink.fills == ["r-1"]
        assert {"client_id": order.client_id,
                "event": "late-fill-booked"} in events

    def test_kills_ordmgr_poll_6_resolved_reads_no_expiry(self, tmp_path):
        # Resolved reservations are READ (fills adopted) but take no expiry
        # actions. White-box: release pre-fired, entry OPEN and past expiry.
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path, outcome_sink=_Sink())
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW - timedelta(seconds=1),
                                 kind="STOP_MARKET", reservation_id="r-1")
        assert order.state == OrderState.OPEN
        mgr._callbacks_fired.add(("release", "r-1"))
        events = mgr.poll(NOW + timedelta(seconds=5))
        assert order.state == OrderState.OPEN  # no expiry post-release
        assert order.reconciled is True  # ...but the read happened
        assert events == []
        # Control: unresolved twin expires normally.
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        order2 = mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                   expire_at_utc=NOW - timedelta(seconds=1),
                                   kind="STOP_MARKET")
        mgr2.poll(NOW + timedelta(seconds=5))
        assert order2.state == OrderState.EXPIRED

    def test_kills_ordmgr_poll_40_54_settle_records(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET", reservation_id="r-1")
        mgr.poll(NOW + timedelta(seconds=61))
        mgr.poll(NOW + timedelta(seconds=62))
        settles = [r for r in _journal(tmp_path)
                   if r["event"] == "settle-poll"]
        assert [r["detail"] for r in settles] == [{"settle_polls": 1}]
        assert [r["client_id"] for r in settles] == [order.client_id]
        mgr.poll(NOW + timedelta(seconds=63))
        settles = [r for r in _journal(tmp_path)
                   if r["event"] == "settle-poll"]
        assert [r["detail"] for r in settles] == [{"settle_polls": 1},
                                                 {"settle_polls": 2}]

    def test_kills_ordmgr_poll_56_71_expiry(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        events = mgr.poll(NOW + timedelta(seconds=30))
        assert order.state == OrderState.OPEN  # unexpired
        assert events == []
        # Expiry at exactly the deadline (kills `>=` -> `>`).
        mgr2edge = _manager(FakeVenue(), tmp_path, filename="edge.jsonl")
        edge = mgr2edge.submit_entry(
            "BTCUSDT", "LONG", 0.01, 1.0,
            expire_at_utc=NOW + timedelta(seconds=60), kind="STOP_MARKET")
        mgr2edge.poll(NOW + timedelta(seconds=60))
        assert edge.state == OrderState.EXPIRED
        events = mgr.poll(NOW + timedelta(seconds=61))
        assert order.state == OrderState.EXPIRED
        assert venue.query(order.client_id).status == "CANCELLED"
        assert {"client_id": order.client_id, "event": "expired"} in events
        intents = [r for r in _journal(tmp_path)
                   if r["event"] == "cancel-intent"]
        assert intents[-1]["detail"] == {"reason": "entry-expired"}
        expired = [r for r in _journal(tmp_path)
                   if r["event"] == "expired"][0]
        assert expired["client_id"] == order.client_id
        assert expired["detail"] == {}
        # PARTIAL entries expire too.
        venue2 = FakeVenue()
        venue2.fail_next_submit("partial", fractions=(0.4, 0.6))
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl")
        part = mgr2.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60))
        assert part.state == OrderState.PARTIAL
        mgr2.poll(NOW + timedelta(seconds=61))
        assert part.state == OrderState.EXPIRED
        # Legs never expire, even with an expiry stamp set.
        mgr3 = _manager(FakeVenue(), tmp_path, filename="c.jsonl")
        entry = mgr3.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                  expire_at_utc=NOW + timedelta(seconds=600))
        stop, _ = mgr3.attach_siblings(entry, stop_price=9.0,
                                       target_price=11.0)
        stop.expire_at_utc = NOW - timedelta(seconds=1)
        mgr3.poll(NOW + timedelta(seconds=61))
        assert stop.state == OrderState.OPEN

    def test_kills_ordmgr_poll_75_106_unknown_paths(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("timeout", received=False)
        mgr = _manager(venue, tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60))
        events = mgr.poll()
        assert order.state == OrderState.CANCELLED
        assert order.venue_known is False
        assert {"client_id": order.client_id,
                "event": "void-unknown"} in events
        rec = [r for r in _journal(tmp_path)
               if r["event"] == "reconciled-unknown-void"][0]
        assert rec["client_id"] == order.client_id
        assert rec["detail"] == {}
        # Terminal + unknown venue: no event, state kept.
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        filled = mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                   expire_at_utc=NOW + timedelta(seconds=60))
        mgr2.venue._orders.pop(filled.client_id)
        assert mgr2.poll() == []
        assert filled.state == OrderState.FILLED

    def test_kills_ordmgr_cancelintent_1_10_logged(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        view = mgr._cancel_with_intent(order.client_id, "test-cancel")
        assert view is not None and view.status == "CANCELLED"
        rec = [r for r in _journal(tmp_path)
               if r["event"] == "cancel-intent"][0]
        assert rec["client_id"] == order.client_id
        assert rec["detail"] == {"reason": "test-cancel"}
        assert mgr._cancel_with_intent("no-such-id", "x") is None

    def test_kills_ordmgr_settle_5_29_sibling_cancel(self, tmp_path):
        venue, mgr, entry, stop, target = (
            TestOrderManagerPositionCallbacksKills()._long_position(tmp_path))
        venue.inject_fill(stop.client_id, 1.0, 9.0)
        events = mgr.poll()
        assert stop.state == OrderState.FILLED
        assert target.state == OrderState.CANCELLED  # verified cancel
        assert venue.query(target.client_id).status == "CANCELLED"
        assert {"client_id": target.client_id,
                "event": f"sibling-cancelled-after:{stop.client_id}"} \
            in events
        intents = [r for r in _journal(tmp_path)
                   if r["event"] == "cancel-intent"]
        assert intents[-1]["client_id"] == target.client_id
        assert intents[-1]["detail"] == {
            "reason": f"sibling-cancelled-after:{stop.client_id}"}

    def test_kills_ordmgr_settle_scope_reservation_wide(self, tmp_path):
        # Same reservation across two groups: one fill cancels every other
        # live leg reservation-wide (top-up groups included).
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        entry = mgr.submit_entry("BTCUSDT", "LONG", 2.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 reservation_id="r-1")
        stop1, target1 = mgr.attach_siblings(entry, stop_price=9.0,
                                             target_price=11.0)
        extra_stop = mgr._submit("BTCUSDT", "SELL", 2.0, "STOP_MARKET",
                                 price=None, stop_price=9.0, role="stop",
                                 group_id="grp-other", reservation_id="r-1")
        venue.inject_fill(stop1.client_id, 2.0, 9.0)
        mgr.poll()
        assert target1.state == OrderState.CANCELLED
        assert extra_stop.state == OrderState.CANCELLED
        # Legs without a reservation fall back to per-group settling.
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        a_stop = mgr2._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET",
                              price=None, stop_price=9.0, role="stop",
                              group_id="g1")
        a_tgt = mgr2._submit("BTCUSDT", "SELL", 1.0, "TAKE_PROFIT_MARKET",
                             price=None, stop_price=11.0, role="target",
                             group_id="g1")
        b_stop = mgr2._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET",
                              price=None, stop_price=9.0, role="stop",
                              group_id="g2")
        mgr2.venue.inject_fill(a_stop.client_id, 1.0, 9.0)
        mgr2.poll()
        assert a_tgt.state == OrderState.CANCELLED
        assert b_stop.state == OrderState.OPEN  # other group untouched
        # No filled legs -> no-op.
        mgr3 = _manager(FakeVenue(), tmp_path, filename="c.jsonl")
        assert mgr3._settle_sibling_groups() == []

    def test_kills_ordmgr_exitcover_2_23_sums(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         reservation_id="r-1")
        stop = mgr._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET",
                           price=None, stop_price=9.0, role="stop",
                           group_id="g", reservation_id="r-1")
        target = mgr._submit("BTCUSDT", "SELL", 2.0, "TAKE_PROFIT_MARKET",
                             price=None, stop_price=11.0, role="target",
                             group_id="g", reservation_id="r-1")
        assert mgr._exit_cover("r-1") == (1.0, 2.0)
        venue.inject_fill(target.client_id, 0.5, 11.0)
        mgr.poll()  # target PARTIAL still covers full qty
        assert mgr._exit_cover("r-1") == (1.0, 2.0)
        venue.inject_fill(stop.client_id, 1.0, 9.0)
        mgr.poll()  # stop FILLED covers filled_qty; target cancelled
        assert mgr._exit_cover("r-1") == (1.0, 0.0)
        venue.fail_next_submit("timeout", received=True)
        amb = mgr._submit("BTCUSDT", "SELL", 0.5, "STOP_MARKET",
                          price=None, stop_price=9.0, role="stop",
                          group_id="g2", reservation_id="r-1")
        assert amb.state == OrderState.AMBIGUOUS
        stop_cover, _ = mgr._exit_cover("r-1")
        assert stop_cover == pytest.approx(1.5)  # ambiguous counts qty


class TestOrderManagerTopupSweepKills:
    def _gap_position(self, tmp_path, filename="orders.jsonl", sink=None):
        # Entries filled 2.0, one stop/target pair covering 1.0, partial
        # exit fills 0.9+0.9 -> net 0.2 -> top-up gap min(1.0, 0.2) = 0.2.
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path, filename=filename,
                       outcome_sink=sink)
        e1 = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                              expire_at_utc=NOW + timedelta(seconds=600),
                              reservation_id="r-1")
        mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="r-1")
        stop, target = mgr.attach_siblings(e1, stop_price=9.0,
                                           target_price=11.0)
        venue.inject_fill(stop.client_id, 0.9, 9.0)
        venue.inject_fill(target.client_id, 0.9, 11.0)
        return venue, mgr, e1, stop, target

    def test_kills_ordmgr_topup_3_28_gap_pair(self, tmp_path):
        venue, mgr, e1, stop, target = self._gap_position(tmp_path)
        events = mgr.poll()
        topups = [e for e in events if str(e["event"]).startswith(
            "protection-topup:")]
        assert len(topups) == 1
        gap = float(topups[0]["event"].split(":")[1])
        assert gap == pytest.approx(0.2)
        legs = [o for o in mgr.orders.values()
                if o.group_id == f"grp-{e1.client_id}-x1"]
        assert sorted(o.role for o in legs) == ["stop", "target"]
        assert sorted(o.kind for o in legs) == ["STOP_MARKET",
                                                "TAKE_PROFIT_MARKET"]
        assert all(o.venue_side == "SELL" for o in legs)
        assert all(o.qty == pytest.approx(0.2) for o in legs)
        assert all(o.reservation_id == "r-1" for o in legs)
        assert all(o.reconciled for o in legs)
        assert {"reservation_id": "r-1",
                "event": topups[0]["event"]} == topups[0]
        new_stop = next(o for o in legs if o.role == "stop")
        new_target = next(o for o in legs if o.role == "target")
        assert (new_stop.stop_price, new_target.stop_price) == (9.0, 11.0)
        assert mgr._topup_attempts["r-1"] == 1
        rec = [r for r in _journal(tmp_path)
               if r["event"] == "topup-attempt"][0]
        assert rec["client_id"] == "*"
        assert rec["detail"]["reservation_id"] == "r-1"
        assert rec["detail"]["gap"] == pytest.approx(0.2)
        assert rec["detail"]["attempt"] == 1

    def test_kills_ordmgr_topup_28_skips(self, tmp_path):
        # No legs -> nothing to extend.
        mgr = _manager(FakeVenue(), tmp_path)
        mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="r-1")
        assert mgr._top_up_protection() == []
        # A filled leg means closing/closed -> skip.
        venue2 = FakeVenue()
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl")
        entry = mgr2.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                  expire_at_utc=NOW + timedelta(seconds=600),
                                  reservation_id="r-2")
        stop, _ = mgr2.attach_siblings(entry, stop_price=9.0,
                                       target_price=11.0)
        venue2.inject_fill(stop.client_id, 1.0, 9.0)
        mgr2.poll()
        assert [e for e in mgr2.poll()
                if "topup" in str(e.get("event", ""))] == []
        # Frozen reservations skip.
        venue3, mgr3, _, _, _ = self._gap_position(tmp_path, "c.jsonl")
        mgr3._exit_frozen.add("r-1")
        assert mgr3._top_up_protection() == []
        # Resolved reservations skip.
        mgr3._exit_frozen.discard("r-1")
        mgr3._callbacks_fired.add(("release", "r-1"))
        assert mgr3._top_up_protection() == []
        # Legs without levels skip.
        mgr4 = _manager(FakeVenue(), tmp_path, filename="d.jsonl")
        mgr4.submit_entry("BTCUSDT", "LONG", 2.0, 10.0,
                          expire_at_utc=NOW + timedelta(seconds=600),
                          reservation_id="r-4")
        mgr4._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET", price=None,
                     stop_price=None, role="stop", group_id="g",
                     reservation_id="r-4")
        mgr4._submit("BTCUSDT", "SELL", 1.0, "TAKE_PROFIT_MARKET",
                     price=None, stop_price=None, role="target",
                     group_id="g", reservation_id="r-4")
        assert mgr4._top_up_protection() == []

    def test_kills_ordmgr_topup_30_191_bound_terminal(self, tmp_path):
        venue, mgr, e1, stop, target = self._gap_position(tmp_path)
        mgr._topup_attempts["r-1"] = 5
        events = mgr.poll()
        assert {"reservation_id": "r-1",
                "event": "protection-gap-unresolved"} in events
        rec = [r for r in _journal(tmp_path)
               if r["event"] == "protection-gap-unresolved"]
        assert len(rec) == 1
        assert rec[0]["client_id"] == "*"
        assert rec[0]["detail"]["reservation_id"] == "r-1"
        assert rec[0]["detail"]["gap"] == pytest.approx(0.2)
        assert rec[0]["detail"]["reason"] == \
            "attempt bound reached; manual intervention required"
        # Terminal: no duplicate record, no legs, on later polls.
        assert mgr.poll() == [] or all(
            e["event"] != "protection-gap-unresolved" for e in mgr.poll())
        assert [r for r in _journal(tmp_path)
                if r["event"] == "protection-gap-unresolved"] == rec
        assert "r-1" in mgr._gap_terminal

    def test_kills_ordmgr_sweep_5_59_scopes(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        known = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        # Foreign live order: never touched, logged and left alone.
        venue.submit("ext-1", "BTCUSDT", "BUY", "STOP_MARKET", 1.0, None,
                     9.0)
        # Foreign terminal order: observed only.
        venue.submit("ext-2", "BTCUSDT", "BUY", "STOP_MARKET", 1.0, None,
                     9.0)
        venue.cancel("ext-2")
        # Bot-owned but locally unknown: drop the local record.
        orphan = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                  expire_at_utc=NOW + timedelta(seconds=60),
                                  kind="STOP_MARKET")
        del mgr.orders[orphan.client_id]
        term = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                expire_at_utc=NOW + timedelta(seconds=60),
                                kind="STOP_MARKET")
        venue.cancel(term.client_id)
        del mgr.orders[term.client_id]
        # Minted-unknown PARTIALLY_FILLED orphans sweep too (kills the
        # NEW/PARTIALLY_FILLED status-tuple mutants).
        part = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                expire_at_utc=NOW + timedelta(seconds=60),
                                kind="STOP_MARKET")
        venue.inject_fill(part.client_id, 0.005, 1.0)
        assert venue.query(part.client_id).status == "PARTIALLY_FILLED"
        del mgr.orders[part.client_id]
        swept = mgr.sweep_venue_orphans()
        assert swept == [orphan.client_id, part.client_id]
        assert venue.query(orphan.client_id).status == "CANCELLED"
        assert venue.query("ext-1").status == "NEW"  # untouched
        assert venue.query(known.client_id).status == "NEW"
        journal = _journal(tmp_path)
        foreign = [r for r in journal
                   if r["event"] == "orphan-foreign-ignored"]
        assert len(foreign) == 2
        assert {r["client_id"] for r in foreign} == {"ext-1", "ext-2"}
        assert foreign[0]["detail"] == {
            "venue_status": "NEW",
            "reason": "not-in-minted-id-set; foreign activity never touched"}
        assert foreign[1]["detail"] == {
            "venue_status": "CANCELLED",
            "reason": "not-in-minted-id-set; foreign activity never touched"}
        swept_rec = [r for r in journal if r["event"] == "orphan-swept"][0]
        assert swept_rec["client_id"] == orphan.client_id
        assert swept_rec["detail"] == {
            "venue_status": "NEW", "reason": "bot-owned-no-local-record"}
        intent = [r for r in journal if r["event"] == "cancel-intent"]
        assert intent[-1]["detail"] == {
            "reason": "no-local-record-after-recovery"}
        observed = [r for r in journal
                    if r["event"] == "orphan-observed-terminal"][0]
        assert observed["client_id"] == term.client_id
        assert observed["detail"] == {
            "venue_status": "CANCELLED",
            "reason": "bot-owned-no-local-record"}


class TestOrderManagerRecoverKills:
    def test_kills_ordmgr_recover_1_6_no_log(self, tmp_path):
        venue = FakeVenue()
        mgr = OrderManager.recover(venue, tmp_path / "missing.jsonl",
                                   now_utc=lambda: NOW)
        assert mgr.exit_only is False
        assert mgr.orders == {}
        mgr2 = OrderManager.recover(venue, tmp_path / "missing.jsonl",
                                    now_utc=lambda: NOW, exit_only=True)
        assert mgr2.exit_only is True  # constructor kept without a log

    def test_kills_ordmgr_recover_10_24_halt_level(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        mgr.set_halted(True, "stop")
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert back.exit_only is True  # persisted level wins
        back.set_halted(False, "lift")
        back2 = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                     now_utc=lambda: NOW)
        assert back2.exit_only is False
        # No halt records: constructor edge kept either way.
        mgr3 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        mgr3.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                          expire_at_utc=NOW + timedelta(seconds=60),
                          kind="STOP_MARKET")
        kept = OrderManager.recover(mgr3.venue, tmp_path / "b.jsonl",
                                    now_utc=lambda: NOW, exit_only=True)
        assert kept.exit_only is True

    def test_kills_ordmgr_recover_35_47_fired_restore(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("reject", reason="nope")
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         reservation_id="r-1")
        assert sink.releases == ["r-1"]
        fresh = _Sink()
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW, outcome_sink=fresh)
        assert ("release", "r-1") in back._callbacks_fired
        back.poll()
        assert fresh.releases == []  # never re-fired after recovery
        assert fresh.fills == [] and fresh.flats == 0

    def test_kills_ordmgr_recover_64_80_minted_seq(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        cids = [mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET").client_id
                for _ in range(3)]
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert back._minted_ids >= set(cids)  # intents + snapshots
        nxt = back.new_client_id()
        assert nxt.startswith("w2-000004-")  # sequence continues
        assert nxt not in cids
        # A#10: journaled seq numbers are never reused.
        assert back._seq == 4

    def test_kills_ordmgr_recover_90_118_snapshot_fields(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("partial", fractions=(0.4, 0.6))
        clock = _Clock(NOW)
        mgr = OrderManager(venue, log_path=tmp_path / "orders.jsonl",
                           now_utc=clock)
        part = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                expire_at_utc=NOW + timedelta(seconds=60),
                                reservation_id="r-1")
        stop, _ = mgr.attach_siblings(part, stop_price=9.0,
                                      target_price=11.0)
        # Terminal FILLED entry: reconcile never heals it, so the recovered
        # avg_price must round-trip exactly (kills avg mutants).
        filled = mgr.submit_entry("BTCUSDT", "LONG", 2.0, 12.0,
                                  expire_at_utc=NOW + timedelta(seconds=60),
                                  reservation_id="r-2")
        assert filled.state == OrderState.FILLED
        assert filled.avg_price == 12.0
        # Reconcile non-terminal originals so flags match the recovered
        # ones (recover skips terminal orders).
        from cryptobot.execution.order_manager import TERMINAL_STATES
        for cid in list(mgr.orders):
            if mgr.orders[cid].state not in TERMINAL_STATES:
                mgr.reconcile(cid)
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=clock)
        assert set(back.orders) == set(mgr.orders)
        for cid, order in mgr.orders.items():
            assert back.orders[cid] == order
        assert back.orders[part.client_id].expire_at_utc == \
            NOW + timedelta(seconds=60)
        assert back.orders[stop.client_id].expire_at_utc is None
        assert back.orders[stop.client_id].avg_price is None
        # Blank lines in the journal are skipped.
        with (tmp_path / "orders.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("\n\n")
        back2 = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                     now_utc=clock)
        assert set(back2.orders) == set(mgr.orders)

    def test_kills_ordmgr_recover_127_156_reconcile_sweep(self, tmp_path):
        venue = FakeVenue()
        venue.fail_next_submit("timeout", received=True)
        mgr = _manager(venue, tmp_path)
        amb = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                               expire_at_utc=NOW + timedelta(seconds=600),
                               kind="STOP_MARKET")
        assert amb.state == OrderState.AMBIGUOUS
        filled = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                  expire_at_utc=NOW + timedelta(seconds=600))
        assert filled.state == OrderState.FILLED
        # Bot-owned venue orphan with no local record: intent-only journal
        # entry (crash after intent, before submit) + live venue order.
        ghost_id = "w2-999999-abcdef12"
        venue.submit(ghost_id, "BTCUSDT", "BUY", "STOP_MARKET", 1.0, None,
                     9.0)
        mgr._log(ghost_id, "submit-intent", {
            "symbol": "BTCUSDT", "venue_side": "BUY", "kind": "STOP_MARKET",
            "qty": 1.0, "price": None, "stop_price": 9.0, "role": "entry",
            "group_id": "", "retry_of": None, "reservation_id": None})
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert back.orders[amb.client_id].state == OrderState.OPEN
        assert back.orders[amb.client_id].reconciled is True
        assert back.orders[filled.client_id].reconciled is False  # terminal
        assert ghost_id not in back.orders
        assert venue.query(ghost_id).status == "CANCELLED"
        rec = _journal(tmp_path)[-1]
        assert rec["client_id"] == "*"
        assert rec["event"] == "recovered"
        assert rec["detail"] == {"orders": 2,
                                 "orphans_swept": [ghost_id]}

    def test_kills_ordmgr_recover_149_156_delta_replay(self, tmp_path):
        # Unpropagated delta replays exactly once to the new sink.
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)  # no sink: logged, not propagated
        mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="r-1")
        assert [r for r in _journal(tmp_path)
                if r["event"] == "delta-propagated"] == []
        sink = _Sink()
        OrderManager.recover(venue, tmp_path / "orders.jsonl",
                             now_utc=lambda: NOW, outcome_sink=sink)
        assert len(sink.deltas) == 1
        assert sink.deltas[0][1].endswith(":fill:0001")
        # Propagated deltas never duplicate on recovery.
        venue2 = FakeVenue()
        sink2 = _Sink()
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl",
                        outcome_sink=sink2)
        mgr2.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                          expire_at_utc=NOW + timedelta(seconds=600),
                          reservation_id="r-2")
        assert len(sink2.deltas) == 1
        fresh = _Sink()
        OrderManager.recover(venue2, tmp_path / "b.jsonl",
                             now_utc=lambda: NOW, outcome_sink=fresh)
        assert fresh.deltas == []

    def test_kills_ordmgr_recover_167_266_event_replay(self, tmp_path):
        # topup attempts, gap-terminal and exit-frozen restore from the log.
        venue = FakeVenue()
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        e1 = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                              expire_at_utc=NOW + timedelta(seconds=600),
                              reservation_id="r-1")
        mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="r-1")
        stop, target = mgr.attach_siblings(e1, stop_price=9.0,
                                           target_price=11.0)
        venue.inject_fill(stop.client_id, 0.9, 9.0)
        venue.inject_fill(target.client_id, 0.9, 11.0)
        mgr.poll()  # topup attempt 1
        assert mgr._topup_attempts["r-1"] == 1
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW, outcome_sink=_Sink())
        assert back._topup_attempts["r-1"] == 1  # max() replays
        # Exit freeze restores: no new legs after recovery.
        venue2 = FakeVenue()
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl",
                        outcome_sink=_Sink())
        e2 = mgr2.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                               expire_at_utc=NOW + timedelta(seconds=600),
                               reservation_id="r-9")
        s2, t2 = mgr2.attach_siblings(e2, stop_price=9.0, target_price=11.0)
        venue2.inject_fill(s2.client_id, 1.0, 9.0)
        venue2.inject_fill(t2.client_id, 1.0, 11.0)
        mgr2.poll()
        assert "r-9" in mgr2._exit_frozen
        back2 = OrderManager.recover(venue2, tmp_path / "b.jsonl",
                                     now_utc=lambda: NOW)
        assert "r-9" in back2._exit_frozen
        with pytest.raises(ValueError,
                           match=r"^exits frozen after overfill; no new legs$"):
            back2.attach_siblings(back2.orders[e2.client_id], stop_price=9.0,
                                  target_price=11.0)
        # Gap-terminal restores: bounded attempts stay bounded. Entries
        # filled 1.9, cover 1.0, exit partials 1.8 -> net 0.1 holds the gap
        # open past 5 journaled attempts (cover 1.0->1.5 < 1.9).
        venue3 = FakeVenue()
        mgr3 = _manager(venue3, tmp_path, filename="c.jsonl")
        e3 = mgr3.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                               expire_at_utc=NOW + timedelta(seconds=600),
                               reservation_id="r-3")
        venue3.fail_next_submit("partial", fractions=(0.9, 0.1))
        mgr3.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                          expire_at_utc=NOW + timedelta(seconds=600),
                          reservation_id="r-3")
        s3, t3 = mgr3.attach_siblings(e3, stop_price=9.0, target_price=11.0)
        venue3.inject_fill(s3.client_id, 0.9, 9.0)
        venue3.inject_fill(t3.client_id, 0.9, 11.0)
        for _ in range(5):
            mgr3.poll()  # journaled attempts 1..5 (net clamp holds gap)
        assert mgr3._topup_attempts["r-3"] == 5
        mgr3.poll()  # attempt bound -> terminal gap record
        assert "r-3" in mgr3._gap_terminal
        back3 = OrderManager.recover(venue3, tmp_path / "c.jsonl",
                                     now_utc=lambda: NOW)
        assert "r-3" in back3._gap_terminal
        back3.poll()
        gaps = [r for r in _journal(tmp_path, "c.jsonl")
                if r["event"] == "protection-gap-unresolved"]
        assert len(gaps) == 1  # no duplicate terminal record
        assert back3._topup_attempts["r-3"] == 5


class TestOrderManagerFillsLogKills:
    def test_kills_ordmgr_bookfills_1_boundary(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 100.0,
                                 expire_at_utc=NOW + timedelta(seconds=600))
        assert order.filled_qty == 1.0
        base = dict(client_id=order.client_id, symbol="BTCUSDT", side="BUY",
                    kind="LIMIT", qty=1.0, price=100.0, stop_price=None,
                    status="FILLED")
        # Exactly filled+1e-12 -> no delta (kills `<=` -> `<`); avg updates.
        edge = VenueOrderView(**base, filled_qty=1.0 + 1e-12, avg_price=105.0)
        assert mgr._book_fills(order, edge) is None
        assert order.filled_qty == 1.0
        assert order.avg_price == 105.0
        # One ulp above the boundary books.
        over = VenueOrderView(**base, filled_qty=1.0 + 2e-12,
                              avg_price=100.0)
        rec = mgr._book_fills(order, over)
        assert rec is not None
        assert rec["qty_delta"] == pytest.approx(2e-12)

    def test_kills_ordmgr_bookfills_4_14_math_shape(self, tmp_path):
        venue = FakeVenue()
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        order = mgr.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                                 expire_at_utc=NOW + timedelta(seconds=600),
                                 kind="STOP_MARKET", reservation_id="r-1")
        venue.inject_fill(order.client_id, 1.0, 100.0)
        mgr.poll()
        venue.inject_fill(order.client_id, 0.5, 102.0)
        mgr.poll()
        assert [d[5] for d in sink.deltas] == pytest.approx([100.0, 102.0])
        assert [d[4] for d in sink.deltas] == pytest.approx([1.0, 0.5])
        assert [d[1] for d in sink.deltas] == [
            f"{order.client_id}:fill:0001", f"{order.client_id}:fill:0002"]
        assert order.fill_notional == pytest.approx(151.0)
        assert order.fill_seq == 2
        rec = [r for r in _journal(tmp_path)
               if r["event"] == "fill-delta"][0]
        assert set(rec["detail"]) == {
            "exec_id", "client_id", "reservation_id", "symbol",
            "venue_side", "qty_delta", "price", "fee", "fee_label",
            "ts_utc"}
        assert rec["detail"]["fee"] == 0.0
        assert rec["detail"]["fee_label"] == "venue-models-no-fee"
        assert rec["detail"]["ts_utc"] == NOW.isoformat()
        assert rec["client_id"] == order.client_id
        # Steady poll books nothing further.
        assert mgr.poll() == []
        assert len(sink.deltas) == 2

    def test_kills_ordmgr_bookfills_22_55_defensive_logged(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 100.0,
                                 expire_at_utc=NOW + timedelta(seconds=600))
        exec_id = f"{order.client_id}:fill:0001"
        assert exec_id in mgr._deltas_logged
        order.fill_seq = 0  # simulate a seq/log skew: same exec replays
        order.filled_qty = 0.5
        view = VenueOrderView(order.client_id, "BTCUSDT", "BUY", "LIMIT",
                              1.0, 100.0, None, "FILLED", 1.0, 100.0)
        assert mgr._book_fills(order, view) is None  # never double-logs
        assert order.filled_qty == 0.5
        assert order.fill_seq == 1  # seq advanced, state untouched

    def test_kills_ordmgr_propagate_2_75_wiring(self, tmp_path):
        record = {"exec_id": "c:fill:0001", "client_id": "c",
                  "reservation_id": "r-1", "symbol": "BTCUSDT",
                  "venue_side": "BUY", "qty_delta": 1.0, "price": 100.0,
                  "fee": 0.0, "ts_utc": NOW.isoformat()}
        mgr = _manager(FakeVenue(), tmp_path)  # no sink
        mgr._propagate_delta(record)
        assert _journal(tmp_path) == []
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl",
                        outcome_sink=_Sink())
        mgr2._propagate_delta({**record, "reservation_id": None})
        assert _journal(tmp_path, "b.jsonl") == []
        legacy = _manager(FakeVenue(), tmp_path, filename="c.jsonl",
                          outcome_sink=_LegacySink())
        legacy._propagate_delta(record)
        rec = _journal(tmp_path, "c.jsonl")[0]
        assert rec["client_id"] == "*"
        assert rec["event"] == "delta-not-propagated"
        assert rec["detail"] == {"exec_id": "c:fill:0001",
                                 "reason": "sink-lacks-v0.2.0-note_fill_delta"}
        sink = _Sink()
        full = _manager(FakeVenue(), tmp_path, filename="d.jsonl",
                        outcome_sink=sink)
        full._propagate_delta(record)
        assert sink.deltas == [("r-1", "c:fill:0001", "BTCUSDT", "BUY", 1.0,
                                100.0, 0.0, NOW.isoformat())]
        rec = _journal(tmp_path, "d.jsonl")[0]
        assert rec["event"] == "delta-propagated"
        assert rec["detail"] == {"exec_id": "c:fill:0001"}
        assert rec["client_id"] == "c"

    def test_kills_ordmgr_log_14_55_snapshot_shape(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        mgr.submit_entry("BTCUSDT", "LONG", 0.5, 67005.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         kind="STOP_MARKET", reservation_id="r-1")
        recs = _journal(tmp_path)
        assert len(recs) == 2
        for rec in recs:
            assert set(rec) == {"ts_utc", "client_id", "event", "detail",
                                "order"}
            assert rec["ts_utc"] == NOW.isoformat()
        assert recs[1]["order"] == {
            "symbol": "BTCUSDT", "venue_side": "BUY", "kind": "STOP_MARKET",
            "qty": 0.5, "price": 67005.0, "stop_price": None,
            "state": "open", "filled_qty": 0.0, "avg_price": None,
            "expire_at_utc": (NOW + timedelta(seconds=60)).isoformat(),
            "role": "entry", "group_id": "", "retry_of": None,
            "reservation_id": "r-1", "fill_notional": 0.0, "fill_seq": 0,
            "settle_polls": 0}
        # "*" client records carry no order snapshot.
        mgr.set_halted(True, "x")
        assert _journal(tmp_path)[-1]["order"] == {}
        # LIMIT fill snapshot carries priced fills.
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                          expire_at_utc=NOW + timedelta(seconds=60))
        submitted = [r for r in _journal(tmp_path, "b.jsonl")
                     if r["event"] == "submitted"][0]
        assert submitted["order"]["state"] == "filled"
        assert submitted["order"]["filled_qty"] == pytest.approx(0.01)
        assert submitted["order"]["avg_price"] == pytest.approx(67005.0)
        assert submitted["order"]["fill_notional"] == pytest.approx(670.05)
        assert submitted["order"]["fill_seq"] == 1


# =========================================================================
# order_manager patch round (resweep-2 survivors)
# =========================================================================

class TestOrderManagerPatchKills:
    def test_kills_ordmgr_init_14_15_default_clock(self, tmp_path):
        mgr = OrderManager(FakeVenue(), log_path=tmp_path / "o.jsonl")
        tick = mgr._now_utc()
        assert isinstance(tick, datetime)
        assert tick.tzinfo is not None  # aware UTC, never None/naive

    def test_kills_ordmgr_fire_36_return_and_fill_reason(self, tmp_path):
        sink = _Sink()
        mgr = _manager(FakeVenue(), tmp_path, outcome_sink=sink)
        assert mgr._fire("fill", "r-x", "t") is True  # newly fired
        assert mgr._fire("fill", "r-x", "t") is False  # duplicate
        assert mgr._fire("release", "r-x", "t") is True
        # Fill reason journaled verbatim.
        venue = FakeVenue()
        sink2 = _Sink()
        mgr2 = _manager(venue, tmp_path, filename="b.jsonl",
                        outcome_sink=sink2)
        mgr2._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                     role="entry", reservation_id="r-1")
        events = mgr2._evaluate_callbacks()
        assert events == [{"reservation_id": "r-1",
                           "event": "callback:fill"}]
        rec = [r for r in _journal(tmp_path, "b.jsonl")
               if r["event"] == "callback-fired"][0]
        assert rec["detail"] == {"kind": "fill",
                                 "reservation_id": "r-1",
                                 "reason": "first-nonzero-fill"}

    def test_kills_ordmgr_evalcb_111_117_release_events(self, tmp_path):
        sink = _Sink()
        mgr = _manager(FakeVenue(), tmp_path, outcome_sink=sink)
        o1 = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                         role="entry", reservation_id="r-1")
        o2 = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                         role="entry", reservation_id="r-1")
        o1.state = OrderState.CANCELLED  # zero-fill terminal pair
        o1.filled_qty = 0.0
        o2.state = OrderState.REJECTED
        o2.filled_qty = 0.0
        events = mgr._evaluate_callbacks()
        assert events == [{"reservation_id": "r-1",
                           "event": "callback:release"}]
        rec = [r for r in _journal(tmp_path)
               if r["event"] == "callback-fired"][0]
        assert rec["detail"]["reason"].startswith(
            "no-live-order(states=cancelled,rejected)")

    def test_kills_ordmgr_evalcb_64_94_freeze_flat_events(self, tmp_path):
        sink = _Sink()
        mgr = _manager(FakeVenue(), tmp_path, outcome_sink=sink)
        entry = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                            role="entry", reservation_id="r-1")
        entry.filled_qty = 1.0
        entry.state = OrderState.FILLED
        stop = mgr._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET",
                           price=None, stop_price=9.0, role="stop",
                           group_id="g", reservation_id="r-1")
        target = mgr._submit("BTCUSDT", "SELL", 1.0, "TAKE_PROFIT_MARKET",
                             price=None, stop_price=11.0, role="target",
                             group_id="g", reservation_id="r-1")
        stop.filled_qty = 1.0
        stop.state = OrderState.FILLED
        target.filled_qty = 1.0
        target.state = OrderState.FILLED
        events = mgr._evaluate_callbacks()
        assert events == [
            {"reservation_id": "r-1", "event": "callback:fill"},
            {"reservation_id": "r-1", "event": "exit-overfill-freeze"}]
        # Flat pair: net-zero, nothing live.
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl",
                        outcome_sink=_Sink())
        e2 = mgr2._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                          role="entry", reservation_id="r-2")
        e2.filled_qty = 1.0
        e2.state = OrderState.FILLED
        s2 = mgr2._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET",
                          price=None, stop_price=9.0, role="stop",
                          group_id="g", reservation_id="r-2")
        s2.filled_qty = 1.0
        s2.state = OrderState.FILLED
        events = mgr2._evaluate_callbacks()
        assert events == [
            {"reservation_id": "r-2", "event": "callback:fill"},
            {"reservation_id": "r-2", "event": "callback:flat"}]

    def test_kills_ordmgr_evalcb_24_exact_eps_no_fire(self, tmp_path):
        # Filled exactly 1e-12 is NOT nonzero (kills `>` -> `>=`).
        sink = _Sink()
        mgr = _manager(FakeVenue(), tmp_path, outcome_sink=sink)
        order = mgr._submit("BTCUSDT", "BUY", 1.0, "STOP_MARKET",
                            price=None, role="entry",
                            reservation_id="r-1")
        order.filled_qty = 1e-12
        assert mgr._evaluate_callbacks() == []
        assert sink.fills == [] and sink.releases == []

    def test_kills_ordmgr_evalcb_74_net_exact_eps_flat(self, tmp_path):
        # Net exactly +1e-12 flats when settled (kills `<=` -> `<`).
        sink = _Sink()
        mgr = _manager(FakeVenue(), tmp_path, outcome_sink=sink)
        entry = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                            role="entry", reservation_id="r-1")
        leg = mgr._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET",
                          price=None, stop_price=9.0, role="stop",
                          group_id="g", reservation_id="r-1")
        entry.filled_qty = 2e-12
        entry.state = OrderState.FILLED
        leg.filled_qty = 1e-12
        leg.state = OrderState.FILLED
        assert 2e-12 - 1e-12 == 1e-12
        events = mgr._evaluate_callbacks()
        assert {"reservation_id": "r-1",
                "event": "callback:flat"} in events
        assert sink.flats == 1

    def test_kills_ordmgr_position_4_multires(self, tmp_path):
        # Non-matching orders are SKIPPED, not loop-ending (kills
        # continue->break): other-reservation order sorts first.
        mgr = _manager(FakeVenue(), tmp_path)
        other = mgr._submit("BTCUSDT", "BUY", 5.0, "LIMIT", price=10.0,
                            role="entry", reservation_id="zzz-other")
        other.filled_qty = 5.0
        mine = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                           role="entry", reservation_id="aaa-mine")
        mine.filled_qty = 1.0
        assert mgr.position_net("aaa-mine") == 1.0
        assert mgr.position_net("zzz-other") == 5.0

    def test_kills_ordmgr_position_30_entry_exact_eps(self, tmp_path):
        # |entry_net| == 1e-12 is NOT overfilled (kills `>` -> `>=`).
        mgr = _manager(FakeVenue(), tmp_path)
        entry = mgr._submit("BTCUSDT", "BUY", 2.0, "LIMIT", price=10.0,
                            role="entry", reservation_id="r-1")
        leg = mgr._submit("BTCUSDT", "SELL", 2.0, "STOP_MARKET",
                          price=None, stop_price=9.0, role="stop",
                          group_id="g", reservation_id="r-1")
        entry.filled_qty = 1e-12
        leg.filled_qty = 1.0 + 1e-12
        _, _, net, overfilled = mgr._position_state("r-1")
        assert abs(net) > 1e-12 and net < 0  # flip present...
        assert overfilled is False  # ...but entry dust is not a position

    def test_kills_ordmgr_attach_1_34_exact_eps(self, tmp_path,
                                                monkeypatch):
        mgr = _manager(FakeVenue(), tmp_path)
        entry = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                            role="entry", reservation_id="r-1")
        entry.filled_qty = 1e-12
        with pytest.raises(ValueError, match="with fills"):
            mgr.attach_siblings(entry, stop_price=9.0, target_price=11.0)
        # Protect qty exactly 1e-12 refuses (net patched exact).
        entry.filled_qty = 1.0
        monkeypatch.setattr(mgr, "position_net", lambda rid: 1e-12)
        with pytest.raises(ValueError, match="nothing to protect"):
            mgr.attach_siblings(entry, stop_price=9.0, target_price=11.0)

    def test_kills_ordmgr_poll_8_10_first_skipped(self, tmp_path):
        # Resolved/REJECTED orders `continue`, never `break` the poll loop.
        venue = FakeVenue()
        venue.fail_next_submit("reject", reason="nope")
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         kind="STOP_MARKET", reservation_id="r-1")
        assert sink.releases == ["r-1"]  # first order resolved
        second = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                  expire_at_utc=NOW + timedelta(seconds=60),
                                  kind="STOP_MARKET")
        mgr.poll(NOW + timedelta(seconds=61))
        assert second.state == OrderState.EXPIRED  # still processed
        # Bare REJECTED first.
        venue2 = FakeVenue()
        venue2.fail_next_submit("reject", reason="nope")
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl")
        mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                          expire_at_utc=NOW + timedelta(seconds=600),
                          kind="STOP_MARKET")
        second2 = mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                    expire_at_utc=NOW + timedelta(seconds=60),
                                    kind="STOP_MARKET")
        mgr2.poll(NOW + timedelta(seconds=61))
        assert second2.state == OrderState.EXPIRED

    def test_kills_ordmgr_poll_12_16_settle_guards(self, tmp_path):
        # Only EXPIRED+reserved+under-cap orders count settle polls.
        sink = _Sink()
        mgr = _manager(FakeVenue(), tmp_path, outcome_sink=sink)
        filled = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                  expire_at_utc=NOW + timedelta(seconds=600),
                                  reservation_id="r-1")
        assert filled.state == OrderState.FILLED
        mgr.poll()
        assert filled.settle_polls == 0
        assert [r for r in _journal(tmp_path)
                if r["event"] == "settle-poll"] == []
        # Sinkless: settle counting caps at expiry_settle_polls (kills `<`).
        mgr2 = _manager(FakeVenue(), tmp_path, filename="b.jsonl")
        exp = mgr2.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                expire_at_utc=NOW + timedelta(seconds=60),
                                kind="STOP_MARKET", reservation_id="r-9")
        mgr2.poll(NOW + timedelta(seconds=61))
        mgr2.poll(NOW + timedelta(seconds=62))
        mgr2.poll(NOW + timedelta(seconds=63))
        assert exp.settle_polls == 2
        mgr2.poll(NOW + timedelta(seconds=64))
        assert exp.settle_polls == 2
        assert len([r for r in _journal(tmp_path, "b.jsonl")
                    if r["event"] == "settle-poll"]) == 2

    def test_kills_ordmgr_exitcover_22_two_targets(self, tmp_path):
        mgr = _manager(FakeVenue(), tmp_path)
        mgr._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET", price=None,
                    stop_price=9.0, role="stop", group_id="g",
                    reservation_id="r-1")
        mgr._submit("BTCUSDT", "SELL", 2.0, "TAKE_PROFIT_MARKET",
                    price=None, stop_price=11.0, role="target",
                    group_id="g", reservation_id="r-1")
        mgr._submit("BTCUSDT", "SELL", 1.0, "TAKE_PROFIT_MARKET",
                    price=None, stop_price=11.0, role="target",
                    group_id="g2", reservation_id="r-1")
        assert mgr._exit_cover("r-1") == (1.0, 3.0)  # targets SUMMED

    def test_kills_ordmgr_topup_17_121_multires_skips(self, tmp_path):
        # Skipped reservations `continue`, never `break` the scan: a later
        # reservation with a real gap still tops up.
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        # a-froz: frozen entry (continue #17).
        fz = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                         role="entry", reservation_id="a-froz")
        fz.filled_qty = 1.0
        mgr._exit_frozen.add("a-froz")
        # a-noleg: filled entry, no legs (continue #31).
        nl = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                         role="entry", reservation_id="a-noleg")
        nl.filled_qty = 1.0
        # a-even: cover exactly equals fills (continue #52).
        ev = mgr._submit("BTCUSDT", "BUY", 1.0, "LIMIT", price=10.0,
                         role="entry", reservation_id="a-even")
        ev.filled_qty = 1.0
        mgr._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET", price=None,
                    stop_price=9.0, role="stop", group_id="g",
                    reservation_id="a-even")
        mgr._submit("BTCUSDT", "SELL", 1.0, "TAKE_PROFIT_MARKET",
                    price=None, stop_price=11.0, role="target",
                    group_id="g", reservation_id="a-even")
        # z-gap: real gap -> must still top up.
        e1 = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                              expire_at_utc=NOW + timedelta(seconds=600),
                              reservation_id="z-gap")
        mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="z-gap")
        stop, target = mgr.attach_siblings(e1, stop_price=9.0,
                                           target_price=11.0)
        venue.inject_fill(stop.client_id, 0.9, 9.0)
        venue.inject_fill(target.client_id, 0.9, 11.0)
        events = mgr.poll()
        assert [e for e in events if str(e["event"]).startswith(
            "protection-topup:")]
        # Levels-missing + attempt-bound skips also continue.
        venue2 = FakeVenue()
        mgr2 = _manager(venue2, tmp_path, filename="b.jsonl")
        _e9 = mgr2.submit_entry("BTCUSDT", "LONG", 2.0, 10.0,
                               expire_at_utc=NOW + timedelta(seconds=600),
                               reservation_id="a-nolevel")
        mgr2._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET", price=None,
                     stop_price=None, role="stop", group_id="g",
                     reservation_id="a-nolevel")
        mgr2._submit("BTCUSDT", "SELL", 1.0, "TAKE_PROFIT_MARKET",
                     price=None, stop_price=None, role="target",
                     group_id="g", reservation_id="a-nolevel")
        g1 = mgr2.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                               expire_at_utc=NOW + timedelta(seconds=600),
                               reservation_id="z-gap")
        mgr2.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                          expire_at_utc=NOW + timedelta(seconds=600),
                          reservation_id="z-gap")
        s9, t9 = mgr2.attach_siblings(g1, stop_price=9.0, target_price=11.0)
        venue2.inject_fill(s9.client_id, 0.9, 9.0)
        venue2.inject_fill(t9.client_id, 0.9, 11.0)
        events = mgr2.poll()
        assert [e for e in events if str(e["event"]).startswith(
            "protection-topup:")]
        assert [r for r in _journal(tmp_path, "b.jsonl")
                if r["event"] == "topup-attempt"][0][
            "detail"]["reservation_id"] == "z-gap"
        # Attempt-bound terminal also continues (topup_87): terminal first.
        venue3 = FakeVenue()
        mgr3 = _manager(venue3, tmp_path, filename="c.jsonl")
        t1 = mgr3.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                               expire_at_utc=NOW + timedelta(seconds=600),
                               reservation_id="a-term")
        mgr3.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                          expire_at_utc=NOW + timedelta(seconds=600),
                          reservation_id="a-term")
        st, tt = mgr3.attach_siblings(t1, stop_price=9.0, target_price=11.0)
        venue3.inject_fill(st.client_id, 0.9, 9.0)
        venue3.inject_fill(tt.client_id, 0.9, 11.0)
        mgr3._topup_attempts["a-term"] = 5
        g2 = mgr3.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                               expire_at_utc=NOW + timedelta(seconds=600),
                               reservation_id="z-gap")
        mgr3.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                          expire_at_utc=NOW + timedelta(seconds=600),
                          reservation_id="z-gap")
        s9b, t9b = mgr3.attach_siblings(g2, stop_price=9.0,
                                        target_price=11.0)
        venue3.inject_fill(s9b.client_id, 0.9, 9.0)
        venue3.inject_fill(t9b.client_id, 0.9, 11.0)
        events = mgr3.poll()
        assert [r for r in _journal(tmp_path, "c.jsonl")
                if r["event"] == "protection-gap-unresolved"]
        assert [e for e in events if str(e["event"]).startswith(
            "protection-topup:")]

    def test_kills_ordmgr_topup_50_exact_eps_skips(self, tmp_path):
        # Gap exactly 1e-12 needs no top-up (kills `<=` -> `<`).
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        entry = mgr.submit_entry("BTCUSDT", "LONG", 2e-12, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=600),
                                 reservation_id="r-1")
        assert entry.filled_qty == 2e-12
        mgr._submit("BTCUSDT", "SELL", 1e-12, "STOP_MARKET", price=None,
                    stop_price=9.0, role="stop", group_id="g",
                    reservation_id="r-1")
        mgr._submit("BTCUSDT", "SELL", 1e-12, "TAKE_PROFIT_MARKET",
                    price=None, stop_price=11.0, role="target",
                    group_id="g", reservation_id="r-1")
        assert 2e-12 - 1e-12 == 1e-12
        events = mgr.poll()
        assert [e for e in events if str(e["event"]).startswith(
            "protection-topup:")] == []
        assert [r for r in _journal(tmp_path)
                if r["event"] == "topup-attempt"] == []

    def test_kills_ordmgr_topup_90_99_short_legs(self, tmp_path):
        # SHORT anchor -> BUY top-up legs (kills exit_side mutants).
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        e1 = mgr.submit_entry("BTCUSDT", "SHORT", 1.0, 10.0,
                              expire_at_utc=NOW + timedelta(seconds=600),
                              reservation_id="r-1")
        mgr.submit_entry("BTCUSDT", "SHORT", 1.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="r-1")
        stop, target = mgr.attach_siblings(e1, stop_price=11.0,
                                           target_price=9.0)
        assert stop.venue_side == "BUY"
        venue.inject_fill(stop.client_id, 0.9, 11.0)
        venue.inject_fill(target.client_id, 0.9, 9.0)
        mgr.poll()
        legs = [o for o in mgr.orders.values()
                if o.group_id == f"grp-{e1.client_id}-x1"]
        assert len(legs) == 2
        assert all(o.venue_side == "BUY" for o in legs)
        assert sorted(o.kind for o in legs) == ["STOP_MARKET",
                                                "TAKE_PROFIT_MARKET"]

    def test_kills_ordmgr_topup_106_118_level_guards(self, tmp_path):
        # Target-first legs with a None stop price: no levels to reuse.
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        mgr.submit_entry("BTCUSDT", "LONG", 2.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="r-106")
        mgr._submit("BTCUSDT", "SELL", 1.0, "TAKE_PROFIT_MARKET",
                    price=None, stop_price=11.0, role="target",
                    group_id="g", reservation_id="r-106")
        mgr._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET", price=None,
                    stop_price=None, role="stop", group_id="g",
                    reservation_id="r-106")
        # Mixed: stop set, target None.
        mgr.submit_entry("BTCUSDT", "LONG", 2.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="r-118")
        mgr._submit("BTCUSDT", "SELL", 1.0, "STOP_MARKET", price=None,
                    stop_price=9.0, role="stop", group_id="h",
                    reservation_id="r-118")
        mgr._submit("BTCUSDT", "SELL", 1.0, "TAKE_PROFIT_MARKET",
                    price=None, stop_price=None, role="target",
                    group_id="h", reservation_id="r-118")
        mgr.poll()
        assert [r for r in _journal(tmp_path)
                if r["event"] == "topup-attempt"] == []

    def test_kills_ordmgr_bookfills_11_none_avg(self, tmp_path):
        # Unknown venue avg prices the delta at 0.0 (kills `or 1.0`).
        mgr = _manager(FakeVenue(), tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 1.0, 100.0,
                                 expire_at_utc=NOW + timedelta(seconds=600),
                                 kind="STOP_MARKET")
        view = VenueOrderView(order.client_id, "BTCUSDT", "BUY", "STOP_MARKET",
                              1.0, None, None, "PARTIALLY_FILLED", 0.5,
                              None)
        rec = mgr._book_fills(order, view)
        assert rec is not None
        assert rec["qty_delta"] == pytest.approx(0.5)
        assert rec["price"] == 0.0

    def test_kills_ordmgr_recover_5_10_clock_forwarded(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         kind="STOP_MARKET")
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert back._now_utc() == NOW  # injected clock, never wall
        rec = _journal(tmp_path)[-1]
        assert rec["event"] == "recovered"
        assert rec["ts_utc"] == NOW.isoformat()

    def test_kills_ordmgr_recover_24_midfile_blanks(self, tmp_path):
        # Blank lines ANYWHERE (not just trailing) are skipped.
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        a = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                             expire_at_utc=NOW + timedelta(seconds=60),
                             kind="STOP_MARKET")
        lines = (tmp_path / "orders.jsonl").read_text().splitlines(keepends=True)
        lines.insert(1, "\n")
        (tmp_path / "orders.jsonl").write_text("".join(lines))
        b = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                             expire_at_utc=NOW + timedelta(seconds=60),
                             kind="STOP_MARKET")
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert set(back.orders) == {a.client_id, b.client_id}

    def test_kills_ordmgr_recover_35_45_missing_keys(self, tmp_path):
        # Records without order/detail keys are tolerated (old readers).
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        with (tmp_path / "orders.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts_utc": NOW.isoformat(),
                                 "client_id": "legacy-1",
                                 "event": "custom",
                                 "detail": {}}) + "\n")
            fh.write(json.dumps({"ts_utc": NOW.isoformat(),
                                 "client_id": "legacy-2",
                                 "event": "custom"}) + "\n")
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert order.client_id in back.orders
        assert "legacy-1" not in back.orders
        assert "legacy-2" not in back.orders

    def test_kills_ordmgr_recover_66_cleared_over_true(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        mgr.set_halted(True, "stop")
        mgr.set_halted(False, "lift")
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW, exit_only=True)
        assert back.exit_only is False  # cleared level wins over True

    def test_kills_ordmgr_recover_77_100_logged_replay(self, tmp_path):
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        mgr.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                         expire_at_utc=NOW + timedelta(seconds=600),
                         reservation_id="r-1")
        exec_id = next(iter(mgr._deltas_logged))
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert back._deltas_logged == {exec_id}  # never {None}
        # Out-of-order attempt records keep the MAX (kills .get(None)).
        mgr._log("*", "topup-attempt",
                 {"reservation_id": "r-9", "gap": 0.1, "attempt": 3})
        mgr._log("*", "topup-attempt",
                 {"reservation_id": "r-9", "gap": 0.1, "attempt": 1})
        back2 = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                     now_utc=lambda: NOW)
        assert back2._topup_attempts["r-9"] == 3

    def test_kills_ordmgr_recover_131_bad_cid_order(self, tmp_path):
        # Nonconforming minted ids are SKIPPED (break would stop the scan).
        # NOTE: set-iteration order varies by hash seed; the test passes
        # deterministically on pristine code (continue always scans all)
        # and kills the mutant whenever junk iterates first — verified
        # across PYTHONHASHSEED values, not just one run.
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         kind="STOP_MARKET")
        mgr._log("junknoseq", "submit-intent", {"symbol": "BTCUSDT"})
        for tag in ("A", "B", "C", "D", "E", "F", "G", "H"):
            mgr._log(f"junk{tag}", "submit-intent", {"symbol": "BTCUSDT"})
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert back._seq == 1
        assert back.new_client_id().startswith("w2-000002-")

    def test_kills_ordmgr_recover_133_star_skips_ahead(self, tmp_path):
        # Empty snapshots are SKIPPED: a "*" record must not hide later
        # orders (kills break — the later order would vanish).
        venue = FakeVenue()
        venue.fail_next_submit("reject", reason="nope")
        sink = _Sink()
        mgr = _manager(venue, tmp_path, outcome_sink=sink)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         reservation_id="r-1")
        assert sink.releases == ["r-1"]  # "*" callback-fired journaled
        later = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert later.client_id in back.orders

    def test_kills_ordmgr_recover_134_snapshot_minted(self, tmp_path):
        # Snapshots alone prove bot ownership (no submit-intent needed).
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
        lines = (tmp_path / "orders.jsonl").read_text().splitlines()
        kept = [ln for ln in lines
                if json.loads(ln)["event"] != "submit-intent"]
        assert kept  # submitted snapshot survives
        (tmp_path / "orders.jsonl").write_text("\n".join(kept) + "\n")
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert order.client_id in back._minted_ids  # never None-minted
        assert order.client_id in back.orders

    def test_kills_ordmgr_recover_153_246_retry_settle(self, tmp_path):
        # retry_of + settle_polls survive the round trip (kills dropped/
        # renamed-key mutants on both fields).
        venue = FakeVenue()
        venue.fail_next_submit("timeout", received=False)
        mgr = _manager(venue, tmp_path)
        retried = mgr.submit_with_retry(
            "BTCUSDT", "LONG", 0.01, 1.0,
            expire_at_utc=NOW + timedelta(seconds=60), kind="STOP_MARKET")
        assert retried.retry_of is not None
        exp = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                               expire_at_utc=NOW + timedelta(seconds=30),
                               kind="STOP_MARKET", reservation_id="r-e")
        mgr.poll(NOW + timedelta(seconds=31))  # expired
        mgr.poll(NOW + timedelta(seconds=32))  # settle 1
        assert exp.settle_polls == 1
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        assert back.orders[retried.client_id].retry_of == retried.retry_of
        assert back.orders[exp.client_id].settle_polls == 1

    def test_kills_ordmgr_recover_194_oldformat_defaults(self, tmp_path):
        # Minimal old-format snapshot: every default pinned at once
        # (filled 0.0, avg None, expire None, role entry, group "", retry
        # None, reservation None, notional 0.0, seq 0, settle 0).
        venue = FakeVenue()
        mgr = _manager(venue, tmp_path)
        mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=NOW + timedelta(seconds=60),
                         kind="STOP_MARKET")
        with (tmp_path / "orders.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts_utc": NOW.isoformat(), "client_id": "w2-old-000001",
                "event": "submitted", "detail": {"reason": "accepted"},
                "order": {"symbol": "BTCUSDT", "venue_side": "BUY",
                          "kind": "LIMIT", "qty": 1.0, "price": 10.0,
                          "stop_price": None, "state": "filled"}}) + "\n")
        back = OrderManager.recover(venue, tmp_path / "orders.jsonl",
                                    now_utc=lambda: NOW)
        old = back.orders["w2-old-000001"]
        assert old.filled_qty == 0.0
        assert old.avg_price is None
        assert old.expire_at_utc is None
        assert old.role == "entry"
        assert old.group_id == ""
        assert old.retry_of is None
        assert old.reservation_id is None
        assert old.fill_notional == 0.0
        assert old.fill_seq == 0
        assert old.settle_polls == 0
