"""F1.1 property tests: risk sizing/rounding/liquidation/client-IDs (Hypothesis).

Money invariants that must hold for ALL inputs, not just examples:
sizing within budget under stressed costs (incl. negative funding),
rounding never grows quantity, liquidation distance monotonic in
leverage, client IDs unique across restarts, protection covering
fills. Failing seeds are printed by Hypothesis for reproduction.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from itertools import count

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side
from cryptobot.risk.margin import liquidation_price_isolated, maintenance_margin
from cryptobot.risk.rounding import floor_to_step
from cryptobot.risk.sizing import SizeRejected, plan_size
from cryptobot.risk.types import RiskConfig

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)

# Unique subdir per Hypothesis example (function-scoped tmp_path is
# shared across examples; state files must not collide). Suppression
# is safe BECAUSE every example uses its own fresh subdir.
_case = count()
_FIXTURE_OK = [HealthCheck.function_scoped_fixture]

_side = st.sampled_from([Side.LONG, Side.SHORT])
_price = st.floats(min_value=1.0, max_value=100000.0,
                   allow_nan=False, allow_infinity=False)
_funding_bps = st.floats(min_value=-500.0, max_value=500.0,
                         allow_nan=False, allow_infinity=False)
_pos_bps = st.floats(min_value=0.0, max_value=500.0,
                     allow_nan=False, allow_infinity=False)


def _intent(side, entry_low, entry_high, stop, fc):
    return Intent(
        strategy="prop", version="1", instrument="BTCUSDT", side=side,
        evidence_ts_utc=NOW, entry_low=entry_low, entry_high=entry_high,
        entry_expiry_utc=NOW + timedelta(seconds=60),
        invalidation_price=stop, exit_rule="inv", holding_limit_s=60,
        forecast_cost=fc, evidence_ref="r",
        data_quality=DataQuality.CLEAN)


@given(side=_side, base=_price,
       width_frac=st.floats(0.0001, 0.05),
       stop_frac=st.floats(0.001, 0.2),
       fee=_pos_bps, spread=_pos_bps, slip=_pos_bps, funding=_funding_bps,
       equity=st.floats(100.0, 1000000.0),
       lev=st.floats(1.0, 20.0))
@settings(max_examples=150, deadline=2000)
def test_sizing_never_exceeds_budget(side, base, width_frac, stop_frac,
                                     fee, spread, slip, funding,
                                     equity, lev):
    entry_low = base
    entry_high = base * (1.0 + width_frac)
    adverse = entry_high if side == Side.LONG else entry_low
    stop = (adverse * (1.0 - stop_frac) if side == Side.LONG
            else adverse * (1.0 + stop_frac))
    fc = ForecastCost(fee_bps=fee, spread_bps=spread,
                      slippage_bps=slip, funding_bps=funding)
    try:
        intent = _intent(side, entry_low, entry_high, stop, fc)
    except ValueError:
        return  # invalid geometry for this side; skip
    cfg = RiskConfig(leverage_cap=lev)
    budget = cfg.max_loss_budget_pct * equity
    try:
        plan = plan_size(intent, equity, cfg)
    except SizeRejected:
        return  # skipping is safe; only sized plans must fit
    stressed = max(fee + spread + slip + funding, 0.0) / 10000 \
        * cfg.stress_multiplier
    worst_loss = plan.qty * abs(adverse - stop) + plan.qty * adverse * stressed
    assert worst_loss <= budget * (1 + 1e-6) + 1e-9, (
        worst_loss, budget, plan.qty)
    # Negative funding must never buy extra size vs zero funding.
    fc0 = ForecastCost(fee_bps=fee, spread_bps=spread,
                       slippage_bps=slip, funding_bps=min(funding, 0.0))
    if funding < 0:
        plan0 = plan_size(_intent(side, entry_low, entry_high, stop, fc0),
                          equity, cfg)
        assert plan.qty <= plan0.qty * (1 + 1e-9) + 1e-12


@given(qty=st.floats(0.0, 1e6),
       step=st.sampled_from(
           [1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 0.001, 0.01, 0.1, 0.25,
            0.5, 1.0, 5.0, 100.0]))
@settings(max_examples=200, deadline=1000)
def test_rounding_never_increases_risk(qty, step):
    # Venue LOT_SIZE steps are short decimals; 16-digit random steps
    # are outside the venue contract (round-12 truncation can slip a
    # re-floor there — safe direction, dust value, untestable either
    # way since no venue publishes such steps).
    if not (math.isfinite(qty) and math.isfinite(step)):
        return
    floored = floor_to_step(qty, step)
    # Safety: never up by more than float noise (~1e-12 relative; the
    # old bug added a FULL step at 5e-10 relative and fails this).
    assert floored <= qty * (1 + 1e-12) + 1e-12
    if qty > 0:
        assert floored >= 0.0
    if qty / step < 1e9:
        # Exact idempotency inside float-noise reach (all venue ratios).
        assert floor_to_step(floored, step) == floored
    else:
        # Beyond 1e9 the quotient ulp exceeds any safe epsilon: the
        # re-floor may slip one step DOWN (safe direction, dust value)
        # but never up.
        again = floor_to_step(floored, step)
        assert again <= floored
        assert floored - again <= step * 1.01


@given(qty=st.floats(0.0, 1e6), step=st.floats(1e-8, 1.0))
@settings(max_examples=100, deadline=1000)
def test_rounding_safe_direction_universal(qty, step):
    # For EVERY finite step (even pathological): never up by more than
    # float noise, non-negative.
    if not (math.isfinite(qty) and math.isfinite(step)):
        return
    floored = floor_to_step(qty, step)
    assert floored <= qty * (1 + 1e-12) + 1e-12
    assert floored >= 0.0


@given(base=_price, qty_mag=st.floats(0.001, 100.0),
       lev_lo=st.floats(1.0, 10.0), lev_hi=st.floats(1.0, 20.0))
@settings(max_examples=150, deadline=1000)
def test_liquidation_distance_monotonic_in_leverage(base, qty_mag,
                                                    lev_lo, lev_hi):
    if lev_hi <= lev_lo:
        return
    brackets = [{"notionalCap": 1e9, "maintMarginRatio": 0.004, "cum": 0.0}]
    notional = base * qty_mag
    mm = maintenance_margin(notional, brackets)
    liq_lo = liquidation_price_isolated(
        entry=base, qty=qty_mag, isolated_margin=notional / lev_lo,
        maint_margin=mm)
    liq_hi = liquidation_price_isolated(
        entry=base, qty=qty_mag, isolated_margin=notional / lev_hi,
        maint_margin=mm)
    # Higher leverage -> liquidation CLOSER to entry (smaller distance).
    assert abs(base - liq_hi) <= abs(base - liq_lo) + 1e-9


LEGAL_ID = re.compile(r"^[A-Za-z0-9._\-]{1,36}$")


@given(tag=st.text(min_size=1, max_size=40))
@settings(max_examples=100, deadline=2000,
          suppress_health_check=_FIXTURE_OK)
def test_client_ids_legal_for_any_tag(tmp_path, tag):
    """Any run_tag (unicode, symbols, long) yields legal <=36 ids."""
    import venue_fixtures as venues
    from cryptobot.adapters.binance_live import BinanceLiveEngine

    case_dir = tmp_path / f"case{next(_case)}"
    case_dir.mkdir(parents=True, exist_ok=True)
    # Real constructor (venue_fixtures hardcodes run_tag="bl", so build
    # directly with the same offline ReplayTransport wiring).
    transport = venues.ReplayTransport([])
    engine = BinanceLiveEngine(
        api_key="TESTKEY", api_secret="TESTSECRET",
        journal_path=case_dir / "live.jsonl", expected_leverage=3,
        run_tag=tag, live_enable=True, transport=transport,
        now_utc=lambda: venues.NOW)
    cids = [engine._new_client_id() for _ in range(5)]  # noqa: SLF001
    assert len(set(cids)) == 5
    for cid in cids:
        assert LEGAL_ID.match(cid), (tag, cid)


def test_client_ids_unique_across_restarts(tmp_path):
    """Real-engine restart uniqueness (extends T1.6 fixed-tag cover)."""
    import venue_fixtures as venues

    seen: set[str] = set()
    for run in range(5):
        engine, _ = venues.make_engine(tmp_path / f"r{run}", [])
        for _ in range(200):
            cid = engine._new_client_id()  # noqa: SLF001
            assert cid not in seen, cid
            seen.add(cid)
    assert len(seen) == 1000


@given(fill_fracs=st.lists(st.floats(0.05, 1.0), min_size=1, max_size=5))
@settings(max_examples=100, deadline=2000,
          suppress_health_check=_FIXTURE_OK)
def test_protection_covers_filled_quantity(tmp_path, fill_fracs):
    from cryptobot.risk import Approved
    from cryptobot.risk.policy import RiskPolicy

    case_dir = tmp_path / f"case{next(_case)}"
    case_dir.mkdir(parents=True, exist_ok=True)
    cfg = RiskConfig()
    policy = RiskPolicy(config=cfg, state_path=case_dir / "risk.json",
                        now_utc=lambda: NOW)
    policy.reconcile_day(10000.0)
    fc = ForecastCost(fee_bps=5, spread_bps=2, slippage_bps=5,
                      funding_bps=0)
    intent = _intent(Side.LONG, 100.0, 101.0, 99.0, fc)
    from cryptobot.risk.types import AccountSnapshot

    acct = AccountSnapshot(reconciled_equity=10000.0,
                           marked_equity=10000.0,
                           net_liquidation=10000.0,
                           net_realised_global=0.0, open_position=False)
    out = policy.evaluate(intent, acct)
    assert isinstance(out, Approved)
    assert policy.note_executable_qty(out.reservation_id, out.qty)
    filled = 0.0
    for i, frac in enumerate(fill_fracs):
        remaining = out.qty - filled
        if remaining <= 1e-12:
            break
        dq = min(remaining, out.qty * frac)
        if dq <= 0:
            continue
        policy.note_fill_delta(out.reservation_id, f"e{i}", "BTCUSDT",
                               "BUY", dq, 100.5, 0.01,
                               NOW.isoformat())
        filled += dq
        need = policy.required_stop_qty(out.reservation_id)
        assert need is not None
        assert need + 1e-9 >= abs(policy.booked_net(out.reservation_id)), (
            need, policy.booked_net(out.reservation_id))
