"""Cost-contract tests (W2, 30MIN §5). Golden + asymmetric + funding-sign."""
import pytest

from cryptobot.coordination.intent import ForecastCost
from cryptobot.costs import (
    CONTRACT_VERSION,
    COST_S1,
    CostLeg,
    CostSpec,
    estimate_for_notional,
    from_forecast_cost,
    one_way_bps,
    roundtrip_bps,
)


def test_golden_example_yields_26bps():
    # 5 fee/leg + 5 full spread via 2.5 halves + 5 adverse/leg + 1 funding.
    assert one_way_bps(COST_S1, "entry") == 12.5
    assert one_way_bps(COST_S1, "exit") == 12.5
    assert roundtrip_bps(COST_S1) == 26.0
    assert CONTRACT_VERSION == "cost-contract-v1"


def test_asymmetric_legs():
    spec = CostSpec(entry=CostLeg(5.0, 5.0), exit=CostLeg(7.0, 3.0),
                    spread_full_bps=5.0, funding_bps=1.0)
    assert one_way_bps(spec, "entry") == 12.5
    assert one_way_bps(spec, "exit") == 12.5  # 7 + 2.5 + 3.
    assert roundtrip_bps(spec) == 26.0
    spec2 = CostSpec(entry=CostLeg(5.0, 5.0), exit=CostLeg(2.0, 1.0),
                     spread_full_bps=4.0, funding_bps=0.0)
    assert roundtrip_bps(spec2) == (5 + 2 + 5) + (2 + 2 + 1) + 0.0
    with pytest.raises(ValueError, match="entry\\|exit"):
        one_way_bps(spec, "middle")


def test_funding_sign():
    paid = CostSpec(entry=CostLeg(5.0, 5.0), exit=CostLeg(5.0, 5.0),
                    spread_full_bps=5.0, funding_bps=1.0)
    assert roundtrip_bps(paid) == 26.0
    received = CostSpec(entry=CostLeg(5.0, 5.0), exit=CostLeg(5.0, 5.0),
                        spread_full_bps=5.0, funding_bps=-1.0)
    assert roundtrip_bps(received) == 24.0  # received funding reduces cost.
    zero = CostSpec(entry=CostLeg(5.0, 5.0), exit=CostLeg(5.0, 5.0),
                    spread_full_bps=5.0, funding_bps=0.0)
    assert roundtrip_bps(zero) == 25.0


def test_estimate_attribution_matches_formula():
    est = estimate_for_notional(COST_S1, 10_000.0)
    assert (est.fee_bps, est.spread_bps, est.adverse_bps,
            est.funding_bps) == (10.0, 5.0, 10.0, 1.0)
    assert est.total_bps == 26.0
    assert est.total_usdt == pytest.approx(26.0)
    assert est.price_ref == "entry_notional"
    doc = est.to_dict()
    assert doc["contract_version"] == CONTRACT_VERSION
    with pytest.raises(ValueError, match="notional"):
        estimate_for_notional(COST_S1, 0.0)


def test_validation_rejects_bad_specs():
    with pytest.raises(ValueError, match=">= 0"):
        CostLeg(-1.0, 5.0)
    with pytest.raises(ValueError, match=">= 0"):
        CostSpec(CostLeg(5.0, 5.0), CostLeg(5.0, 5.0),
                 spread_full_bps=-5.0, funding_bps=1.0)
    with pytest.raises(ValueError, match="price_ref"):
        CostSpec(CostLeg(5.0, 5.0), CostLeg(5.0, 5.0),
                 spread_full_bps=5.0, funding_bps=1.0, price_ref="mid")
    with pytest.raises(ValueError, match="finite"):
        CostSpec(CostLeg(5.0, float("nan")), CostLeg(5.0, 5.0),
                 spread_full_bps=5.0, funding_bps=1.0)


def test_from_forecast_cost_maps_symmetric_preset():
    fc = ForecastCost(fee_bps=5.0, spread_bps=5.0, slippage_bps=5.0,
                      funding_bps=1.0)
    assert roundtrip_bps(from_forecast_cost(fc)) == 26.0  # not 31: half-spread.
