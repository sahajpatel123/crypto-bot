"""F-SIZING-01 — funding credit must never enlarge stop-loss exposure.

Deep-research audit finding W1: sizing summed SIGNED forecast costs
(funding_bps may be negative = forecast credit). A negative funding
forecast shrank the sizing denominator, so the stop-loss component alone
could exceed the per-trade loss budget severalfold while passing the
leverage cap. If funding flips before the stop fires, realized loss
blows through the budget. Fix: clamp the bps sum at zero for SIZING
(mirror clamp in the Session post-rounding recheck). The clamp can only
shrink or preserve size — strictly risk-reducing.
"""
from __future__ import annotations

import pytest

from conftest import build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")


def _spec(funding_bps: float) -> dict:
    spec = dict(INTENTS["canonical_long"])
    spec["forecast_cost"] = {"fee_bps": 5, "spread_bps": 5,
                             "slippage_bps": 5, "funding_bps": funding_bps}
    return spec


def _unclamped_qty(spec: dict, budget: float = 12.5,
                   stress: float = 1.5) -> float:
    """What the OLD arithmetic would have sized (for the regression assert)."""
    adverse = spec["entry_high"]
    stop_dist = abs(adverse - spec["invalidation_price"])
    fc = spec["forecast_cost"]
    stressed = (fc["fee_bps"] + fc["spread_bps"] + fc["slippage_bps"]
                + fc["funding_bps"]) / 10000 * stress
    return budget / (stop_dist + adverse * stressed)


def test_negative_funding_credit_cannot_inflate_size(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    spec = _spec(-25.0)  # 15-25 = -10bps sum: credit larger than all fees
    out = policy.evaluate(build_intent(spec),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    adverse = spec["entry_high"]
    stop_dist = abs(adverse - spec["invalidation_price"])
    # clamped: stressed == 0 -> the stop alone consumes exactly the budget
    assert out.qty * stop_dist <= 12.5 * (1 + 1e-9)
    assert out.qty == pytest.approx(12.5 / stop_dist, abs=1e-9)
    # and the clamp strictly shrank the position vs the unclamped path
    assert out.qty < _unclamped_qty(spec)


def test_unclamped_path_would_have_breached_budget(tmp_path):
    """Documents WHY the clamp exists: the old arithmetic approved a
    position whose stop-loss component alone was ~2.7x the budget while
    passing the 3x leverage cap."""
    spec = _spec(-25.0)
    adverse = spec["entry_high"]
    stop_dist = abs(adverse - spec["invalidation_price"])
    bad_qty = _unclamped_qty(spec)
    stop_component = bad_qty * stop_dist
    assert stop_component > 12.5  # budget breach on the stop alone
    notional = bad_qty * adverse
    assert notional / 10000.0 < 3.0  # ...while passing the leverage cap


def test_mild_credit_keeps_stop_within_budget(tmp_path):
    """Universal invariant post-fix: the stop-loss component alone never
    exceeds the budget for ANY funding forecast. With a positive cost sum
    the denominator includes those costs (stop < budget naturally); with a
    credit-dominated sum the clamp makes stop == budget exactly."""
    for funding in (0.0, -10.0, -25.0, -100.0):
        pol = make_policy(tmp_path / f"f{funding}")
        pol.reconcile_day(10000.0)
        out = pol.evaluate(build_intent(_spec(funding)),
                           build_account(ACCOUNTS["healthy_10k"]))
        assert isinstance(out, Approved), funding
        stop_dist = abs(_spec(funding)["entry_high"]
                        - _spec(funding)["invalidation_price"])
        assert out.qty * stop_dist <= 12.5 * (1 + 1e-9), funding
    # credit-dominated case pins the exact clamped size (stressed == 0)
    pol = make_policy(tmp_path / "exact")
    pol.reconcile_day(10000.0)
    out = pol.evaluate(build_intent(_spec(-25.0)),
                       build_account(ACCOUNTS["healthy_10k"]))
    assert out.qty == pytest.approx(12.5 / 160.0, abs=1e-9)


def test_positive_funding_unchanged(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    spec = _spec(3.0)
    out = policy.evaluate(build_intent(spec),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    adverse = spec["entry_high"]
    stop_dist = abs(adverse - spec["invalidation_price"])
    stressed = 18.0 / 10000 * 1.5  # 15 + 3, unclamped (positive sum)
    assert out.qty == pytest.approx(12.5 / (stop_dist + adverse * stressed),
                                    rel=1e-6)

