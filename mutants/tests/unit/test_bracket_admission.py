"""F0.4a: leverage-bracket / liquidation gate wired into LIVE admission.

The T1.8 margin helpers (maintenance_margin, liquidation_price_isolated,
liquidation_ok) had zero production callers — sizing helpers only. This
pins the LIVE path: RiskPolicy.evaluate must enforce the bracket gate in
run_mode (fresh venue brackets required), reject on stale brackets, and
enforce the 3x liquidation-distance rule at the sized notional.

Failing-first: RiskConfig has no leverage_brackets on HEAD, so the
run_mode tests below error until the gate is wired.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side
from cryptobot.risk import Approved, Rejected
from cryptobot.risk.margin import maintenance_margin
from cryptobot.risk.policy import RiskPolicy
from cryptobot.risk.types import AccountSnapshot, InstrumentFilter, RiskConfig

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)

BRACKETS = [
    {"bracket": 1, "notionalCap": 50000.0, "maintMarginRatio": 0.004,
     "cum": 0.0},
    {"bracket": 2, "notionalCap": 250000.0, "maintMarginRatio": 0.005,
     "cum": 50.0},
]

COMPLETE = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                            max_notional_usdt=1e9, min_qty=0.01,
                            max_qty=1000.0, tick_size=0.1)


def _intent(side=Side.LONG, **kw):
    base = dict(strategy="F0.4a", version="1", instrument="BTCUSDT",
                side=side, evidence_ts_utc=NOW,
                entry_low=100.0, entry_high=101.0,
                entry_expiry_utc=NOW + timedelta(seconds=60),
                invalidation_price=99.0 if side == Side.LONG else 102.0,
                exit_rule="inv", holding_limit_s=60,
                forecast_cost=ForecastCost(5, 5, 5, 0),
                evidence_ref="r", data_quality=DataQuality.CLEAN)
    base.update(kw)
    return Intent(**base)


def _account(equity=10000.0):
    return AccountSnapshot(reconciled_equity=equity, marked_equity=equity,
                           net_liquidation=equity, net_realised_global=0.0,
                           open_position=False)


def _policy(tmp_path, **cfg):
    defaults = dict(run_mode=True,
                    instrument_filters={"BTCUSDT": COMPLETE},
                    filters_asof_utc=NOW)
    defaults.update(cfg)
    pol = RiskPolicy(RiskConfig(**defaults),
                     state_path=tmp_path / "risk.json",
                     now_utc=lambda: NOW)
    pol.reconcile_day(10000.0)
    return pol


def test_run_mode_missing_brackets_rejects(tmp_path):
    pol = _policy(tmp_path)  # no leverage_brackets
    out = pol.evaluate(_intent(), _account())
    assert isinstance(out, Rejected)
    assert out.reason.startswith("brackets:"), out.reason


def test_stale_brackets_reject(tmp_path):
    pol = _policy(tmp_path, leverage_brackets={"BTCUSDT": BRACKETS},
                  brackets_asof_utc=NOW - timedelta(seconds=7200),
                  brackets_max_age_s=3600.0)
    out = pol.evaluate(_intent(), _account())
    assert isinstance(out, Rejected)
    assert out.reason == "brackets:stale-metadata", out.reason


def test_fresh_brackets_safe_distance_approves(tmp_path):
    pol = _policy(tmp_path, leverage_cap=3.0,
                  leverage_brackets={"BTCUSDT": BRACKETS},
                  brackets_asof_utc=NOW, brackets_max_age_s=3600.0)
    out = pol.evaluate(_intent(), _account())
    assert isinstance(out, Approved), out


def test_tight_liquidation_rejects_high_leverage(tmp_path):
    # Same brackets, leverage 20x: isolated buffer shrinks, liq lands
    # inside 3x stop distance -> must reject.
    pol = _policy(tmp_path, leverage_cap=20.0,
                  leverage_brackets={"BTCUSDT": BRACKETS},
                  brackets_asof_utc=NOW, brackets_max_age_s=3600.0)
    out = pol.evaluate(_intent(), _account())
    assert isinstance(out, Rejected)
    assert out.reason == "brackets:liquidation-distance", out.reason


def test_maintenance_margin_bracket_boundaries():
    # Exact cap stays in tier 1; one wei above moves to tier 2.
    # Tier1: 50000*0.004 = 200. Tier2 continuous: 50000*0.005-50 = 200.
    assert maintenance_margin(50000.0, BRACKETS) == 200.0
    assert maintenance_margin(50000.01, BRACKETS) > 200.0
    assert maintenance_margin(49999.99, BRACKETS) < 200.0
    # Top-tier overflow uses the top ratio (no silent cap).
    assert maintenance_margin(300000.0, BRACKETS) == 300000.0 * 0.005 - 50.0


def test_tier_switch_flips_admission(tmp_path):
    # Same intent/equity/lev3: wide tier-1 cap -> tier1 MM -> approve;
    # tiny tier-1 cap pushes the ~567 notional into an extreme tier-2
    # ratio -> liq inside 3x -> reject. Proves evaluate prices the
    # ACTIVE tier, not a fixed ratio. (Tier-2 ratio synthetic-extreme
    # for sensitivity; venue values come from leverageBracket.)
    wide = [{"bracket": 1, "notionalCap": 1e9, "maintMarginRatio": 0.004,
             "cum": 0.0}]
    narrow = [{"bracket": 1, "notionalCap": 100.0, "maintMarginRatio": 0.004,
               "cum": 0.0},
              {"bracket": 2, "notionalCap": 1e9, "maintMarginRatio": 0.32,
               "cum": 0.0}]
    (tmp_path / "w").mkdir(parents=True, exist_ok=True)
    (tmp_path / "n").mkdir(parents=True, exist_ok=True)
    pol_wide = _policy(tmp_path / "w", leverage_cap=3.0,
                       leverage_brackets={"BTCUSDT": wide},
                       brackets_asof_utc=NOW, brackets_max_age_s=3600.0)
    # _policy writes tmp/risk.json; isolate the second policy dir.
    pol_narrow = _policy(tmp_path / "n", leverage_cap=3.0,
                         leverage_brackets={"BTCUSDT": narrow},
                         brackets_asof_utc=NOW, brackets_max_age_s=3600.0)
    assert isinstance(pol_wide.evaluate(_intent(), _account()), Approved)
    out = pol_narrow.evaluate(_intent(), _account())
    assert isinstance(out, Rejected)
    assert out.reason == "brackets:liquidation-distance", out.reason


def test_parse_brackets_payload_shapes():
    from cryptobot.app.filters import FilterError, parse_brackets_payload

    import pytest

    payload = [{"symbol": "BTCUSDT", "brackets": [
        {"bracket": 2, "notionalCap": "250000", "notionalFloor": "50000",
         "maintMarginRatio": "0.005", "cum": "50.0"},
        {"bracket": 1, "notionalCap": 50000, "notionalFloor": 0,
         "maintMarginRatio": 0.004},  # cum absent -> 0.0
    ]}]
    out = parse_brackets_payload(payload, ["BTCUSDT"])
    assert [t["notionalCap"] for t in out["BTCUSDT"]] == [50000.0, 250000.0]
    assert out["BTCUSDT"][0]["cum"] == 0.0
    assert out["BTCUSDT"][1]["cum"] == 50.0
    with pytest.raises(FilterError):
        parse_brackets_payload(payload, ["ETHUSDT"])  # missing symbol
    with pytest.raises(FilterError):
        parse_brackets_payload([], ["BTCUSDT"])
    with pytest.raises(FilterError):
        parse_brackets_payload([{"symbol": "BTCUSDT", "brackets": []}],
                               ["BTCUSDT"])


def test_session_arm_brackets_injection(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    from pathlib import Path as _Path

    cfg_text = _Path("configs/paper.toml").read_text()
    cfg_text = cfg_text.replace('dir = "runs"',
                                f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(cfg_text)
    session = Session(load_config(cfg_path),
                      RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "run", "bracket-arm")
    session.arm_brackets({"BTCUSDT": BRACKETS}, origin="fixture-test",
                         asof_utc=NOW)
    assert session.policy.config.leverage_brackets["BTCUSDT"] == BRACKETS
    assert session.policy.config.brackets_asof_utc == NOW
    import pytest

    with pytest.raises(ValueError):
        session.arm_brackets({}, origin="empty")
