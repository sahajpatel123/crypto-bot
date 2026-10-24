"""W5 review finding F-W5R1: sizing ignores remaining daily/floor budgets.

Directive section 4 requires each entry to reserve loss-to-invalidation
plus stressed costs against the SMALLEST of: (1) per-position limit,
(2) remaining daily operating-loss budget, (3) cushion above the global
earned-profit floor, (4) available margin + minimums — skipping when
minimum venue size cannot fit. sizing.py plans against (1) only
(budget = max_loss_budget_pct * equity); no remaining-budget or
floor-cushion reduction or gate exists anywhere in src or tests.

Failed on af91e34 (missing behavior); fixed by the manager
four-budget cap (directive section 4); now passing unmarked.
"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side
from cryptobot.risk import AccountSnapshot, Approved, Rejected, RiskConfig, RiskPolicy

FIX = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
INTENTS = json.loads((FIX / "risk_intents.json").read_text())
ACCOUNTS = json.loads((FIX / "risk_accounts.json").read_text())


def _intent():
    spec = INTENTS["canonical_long"]
    fc = spec["forecast_cost"]
    return Intent(
        strategy=spec["strategy"], version=spec["version"],
        instrument=spec["instrument"], side=Side(spec["side"]),
        evidence_ts_utc=datetime.fromisoformat(spec["evidence_ts_utc"]),
        entry_low=spec["entry_low"], entry_high=spec["entry_high"],
        entry_expiry_utc=datetime.fromisoformat(spec["entry_expiry_utc"]),
        invalidation_price=spec["invalidation_price"],
        exit_rule=spec["exit_rule"],
        holding_limit_s=spec["holding_limit_s"],
        forecast_cost=ForecastCost(
            fee_bps=fc["fee_bps"], spread_bps=fc["spread_bps"],
            slippage_bps=fc["slippage_bps"], funding_bps=fc["funding_bps"]),
        evidence_ref=spec["evidence_ref"],
        data_quality=DataQuality(spec["data_quality"]))


def _account(marked):
    return AccountSnapshot(
        reconciled_equity=marked, marked_equity=marked,
        net_liquidation=marked, net_realised_global=marked - 10000.0,
        open_position=False)


def _policy(tmp_path):
    policy = RiskPolicy(config=RiskConfig(),
                        state_path=tmp_path / "risk_state.json",
                        now_utc=lambda: NOW)
    policy.reconcile_day(10000.0)
    return policy


def test_entry_capped_by_remaining_daily_budget(tmp_path):
    """Down 0.49%, a 0.125% intent must shrink to ~0.01% or be refused."""
    policy = _policy(tmp_path)
    out = policy.evaluate(_intent(), _account(9951.0))
    remaining = 9951.0 - 10000.0 * (1 - 0.005)  # 1.0 USDT to the stop.
    assert remaining == 1.0
    if isinstance(out, Approved):
        assert out.reserved_risk <= remaining * (1 + 1e-9), (
            f"reserved {out.reserved_risk} exceeds remaining daily budget "
            f"{remaining}: sizing ignores the burnt budget")
    else:
        assert isinstance(out, Rejected)


def test_entry_capped_by_floor_cushion(tmp_path):
    """Marked 1 USDT above an armed floor: reserve <= cushion or refuse."""
    policy = _policy(tmp_path)
    assert policy.check_health(_account(10150.0)).ok  # arms the floor.
    floor = policy._state.profit_floor
    assert floor is not None and floor == 10000.0 + 0.7 * 150.0
    out = policy.evaluate(_intent(), _account(floor + 1.0))
    if isinstance(out, Approved):
        assert out.reserved_risk <= 1.0 * (1 + 1e-9), (
            f"reserved {out.reserved_risk} exceeds the 1.0 USDT floor "
            f"cushion: sizing ignores the earned-profit floor")
    else:
        assert isinstance(out, Rejected)
