"""Independent cost-contract probes (Worker 5, 30min §5).

The frozen inputs price a round trip at 26 bps in research and 31 bps
in the selector because one-way vs round-trip spread semantics are
implicit. §5 requires one versioned cost contract (price reference +
leg-specific units) used by research, selector and risk sizing.

These probes assert agreement and explicitness WITHOUT assuming which
side is right (reducing 31 to 26 is not automatically correct). Each
fails before W4's unification and passes after; open items carry
strict-xfail with owner in tests/audit/conftest.py.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import ForecastCost  # noqa: E402
from cryptobot.coordination.intent import DataQuality, Intent  # noqa: E402
from cryptobot.coordination.selector import Selector  # noqa: E402
from cryptobot.research.returns import ROUNDTRIP_COST_BPS  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _intent_with_costs(fee, spread, slippage, funding):
    from cryptobot.coordination import Side
    return Intent(
        strategy="S1", version="w5-cost-1", instrument="BTCUSDT",
        side=Side.LONG, evidence_ts_utc=T0,
        entry_low=100.0, entry_high=100.1,
        entry_expiry_utc=T0, invalidation_price=99.0,
        exit_rule="target:101.0/stop:99.0", holding_limit_s=60,
        forecast_cost=ForecastCost(
            fee_bps=fee, spread_bps=spread, slippage_bps=slippage,
            funding_bps=funding),
        evidence_ref="w5:cost-probe",
        data_quality=DataQuality.CLEAN)


def test_research_selector_agree_on_frozen_inputs():
    """Same 5/5/5/1 inputs must price identically in research and the
    selector (currently 26 vs 31)."""
    intent = _intent_with_costs(5.0, 5.0, 5.0, 1.0)
    selector_cost = Selector()._round_trip_bps(intent)
    assert selector_cost == pytest.approx(ROUNDTRIP_COST_BPS), (
        f"cost contract split: research {ROUNDTRIP_COST_BPS} bps vs "
        f"selector {selector_cost} bps on identical inputs")


def test_funding_sign_is_representable():
    """Funding rebates exist; the schema must carry signed funding
    (currently any negative leg raises)."""
    try:
        costs = ForecastCost(fee_bps=5.0, spread_bps=5.0, slippage_bps=5.0,
                             funding_bps=-1.0)
    except ValueError as exc:
        pytest.fail(f"signed funding rejected: {exc}")
    assert costs.funding_bps == -1.0


def test_spread_semantics_are_explicit():
    """The schema must state one-way vs round-trip spread semantics
    (currently the selector doubles spread while research singles it,
    with nothing marking which is meant)."""
    fields = set(ForecastCost.__dataclass_fields__)
    markers = {f for f in fields
               if any(tag in f for tag in
                      ("half", "one_way", "oneway", "round_trip", "roundtrip",
                       "per_leg", "leg_", "semantics", "version",
                       "price_ref", "reference"))}
    assert markers, (
        f"ForecastCost{sorted(fields)} carries no explicit spread "
        f"semantics/version marker; one-way vs round-trip is implicit")
