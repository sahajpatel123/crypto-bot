"""Observed return evaluation tests (Worker 1, Q-006)."""
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import DataQuality, Side
from cryptobot.research.returns import (
    HOLDOUT_SEEDS_S3,
    HOLDOUT_SEEDS_S4,
    MAX_HORIZON,
    N_BARS,
    ROUNDTRIP_COST_BPS,
    evaluate_signal,
    exits_for_signal,
    run_returns,
    split_ranges,
)
from cryptobot.research.synthetic import (
    SCENARIO_S3_LONG,
    generate_fixture,
)
from cryptobot.strategies.contract import (
    S3_BASE,
    S3_FORECAST_COST,
    S4_BASE,
    S4_FORECAST_COST,
    build_intent,
)
from cryptobot.strategies.s1 import Bar
from cryptobot.strategies.s3 import evaluate_bar as evaluate_s3

T0 = datetime(2026, 1, 2, tzinfo=UTC)


def _bar(i, close=100.0, high=None, low=None):
    return Bar(ts_utc=T0 + timedelta(seconds=i), open=close,
               high=close if high is None else high,
               low=close if low is None else low, close=close, volume=10.0,
               trades=5, buy_frac=0.5, spread_bps=1.0)


def _intent(side=Side.LONG, t=200, entry_lo=99.99, entry_hi=100.01,
            inval=99.5, cost=S4_FORECAST_COST, arm=S4_BASE):
    ev = T0 + timedelta(seconds=t)
    return build_intent(
        strategy=arm, instrument="BTCUSDT", side=side, evidence_ts_utc=ev,
        entry_low=entry_lo, entry_high=entry_hi,
        entry_expiry_utc=ev + timedelta(seconds=15),
        invalidation_price=inval, exit_rule="wire", holding_limit_s=120,
        evidence_ref="r", data_quality=DataQuality.CLEAN,
        data_quality_reason="test", forecast_cost=cost,
    )


def test_geometry_covers_max_horizon():
    r = split_ranges()
    assert r["purge"] == (240, 375)
    assert r["purge"][1] - r["purge"][0] == MAX_HORIZON == 135
    assert r["validation"][1] + MAX_HORIZON <= N_BARS
    assert r["holdout"][1] + MAX_HORIZON <= N_BARS
    assert r["train"][1] + MAX_HORIZON <= r["validation"][0]
    try:
        split_ranges(n_bars=500)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for short fixture")


def test_holdout_seeds_disjoint_from_train_val():
    from cryptobot.research.experiments import (
        TRAIN_SEEDS_S3,
        TRAIN_SEEDS_S4,
        VALIDATION_SEEDS_S3,
        VALIDATION_SEEDS_S4,
    )
    assert not (set(HOLDOUT_SEEDS_S3) & set(TRAIN_SEEDS_S3 + VALIDATION_SEEDS_S3))
    assert not (set(HOLDOUT_SEEDS_S4) & set(TRAIN_SEEDS_S4 + VALIDATION_SEEDS_S4))


def test_cost_haircut_is_net_s1_v1():
    assert ROUNDTRIP_COST_BPS == 26.0


def test_s4_target_is_1_5r():
    bars = [_bar(i) for i in range(400)]
    intent = _intent()
    stop, target, time_t = exits_for_signal(S4_BASE, intent, bars, 200)
    assert stop == 99.5
    assert target == 100.0 + 1.5 * 0.5
    assert time_t == 320


def test_s3_target_is_range_mid():
    bars = [_bar(i, close=100.0 + (i % 5) * 0.1,
                 high=100.5, low=99.5) for i in range(400)]
    intent = _intent(arm=S3_BASE, cost=S3_FORECAST_COST)
    stop, target, _ = exits_for_signal(S3_BASE, intent, bars, 200)
    assert stop == 99.5
    assert target == (100.5 + 99.5) / 2


def test_entry_fills_first_touch_after_signal():
    bars = [_bar(i) for i in range(400)]
    bars[201] = _bar(201, close=100.0, high=100.0, low=100.0)  # touches
    trade = evaluate_signal(S4_BASE, _intent(), bars, 200)
    assert trade.status == "closed"
    assert trade.entry_t == 201
    assert trade.entry_px == 100.0


def test_signal_bar_touch_alone_does_not_enter():
    bars = [_bar(i, close=110.0, high=110.0, low=110.0) for i in range(400)]
    bars[200] = _bar(200, close=100.0)  # only bar t touches the box
    trade = evaluate_signal(S4_BASE, _intent(), bars, 200)
    assert trade.status == "expired"
    assert trade.exit_kind == "expired"


def test_no_touch_within_expiry_expires():
    bars = [_bar(i, close=110.0, high=110.0, low=110.0) for i in range(400)]
    trade = evaluate_signal(S4_BASE, _intent(), bars, 200)
    assert trade.status == "expired"
    assert trade.entry_t is None and trade.gross_bps == 0.0


def test_stop_hit_before_target():
    bars = [_bar(i) for i in range(400)]
    bars[205] = _bar(205, close=99.6, high=99.7, low=99.4)  # pierces stop
    trade = evaluate_signal(S4_BASE, _intent(), bars, 200)
    assert trade.exit_kind == "stop"
    assert trade.exit_px == 99.5
    assert trade.exit_t == 205


def test_target_hit_pays_target():
    bars = [_bar(i) for i in range(400)]
    bars[205] = _bar(205, close=100.7, high=100.8, low=100.6)
    trade = evaluate_signal(S4_BASE, _intent(), bars, 200)
    assert trade.exit_kind == "target"
    assert trade.exit_px == 100.75
    assert trade.gross_bps == (100.75 - 100.0) / 100.0 * 1e4
    assert trade.net_bps == trade.gross_bps - 26.0


def test_same_bar_stop_and_target_conservative_stop_wins():
    bars = [_bar(i) for i in range(400)]
    bars[205] = _bar(205, close=100.0, high=101.0, low=99.0)  # hits both
    trade = evaluate_signal(S4_BASE, _intent(), bars, 200)
    assert trade.exit_kind == "stop"
    assert trade.exit_px == 99.5


def test_quiet_path_exits_on_time_at_close():
    bars = [_bar(i) for i in range(400)]
    trade = evaluate_signal(S4_BASE, _intent(), bars, 200)
    assert trade.exit_kind == "time"
    assert trade.exit_t == 320
    assert trade.exit_px == 100.0
    assert trade.gross_bps == 0.0
    assert trade.net_bps == -26.0


def test_none_bars_skipped_in_scans():
    bars = [_bar(i) for i in range(400)]
    bars[201] = None
    bars[202] = _bar(202)
    trade = evaluate_signal(S4_BASE, _intent(), bars, 200)
    assert trade.entry_t == 202


def test_short_side_mirror():
    bars = [_bar(i) for i in range(400)]
    bars[205] = _bar(205, close=99.3, high=99.4, low=99.2)
    intent = _intent(side=Side.SHORT, inval=100.5)
    trade = evaluate_signal(S4_BASE, intent, bars, 200)
    # risk=0.5 target=100-0.75=99.25; bar touches 99.2 -> target
    assert trade.exit_kind == "target"
    assert trade.gross_bps > 0


def test_real_s3_signal_scores_end_to_end():
    fixture = generate_fixture(seed=51, scenario=SCENARIO_S3_LONG, n_bars=600)
    bars = list(fixture.bars)
    found = None
    for t in range(120, 240):
        long_d, _ = evaluate_s3(bars, t, S3_BASE, fixture.instrument)
        if long_d.intent is not None:
            found = (t, long_d.intent)
            break
    assert found is not None
    t, intent = found
    trade = evaluate_signal(S3_BASE, intent, bars, t)
    assert trade.status in ("closed", "expired")
    if trade.status == "closed":
        assert trade.exit_t <= t + 135
        assert trade.net_bps == trade.gross_bps - 26.0


def test_run_returns_smoke_reconciles(tmp_path):
    doc = run_returns("EXP-004", tmp_path, splits=("train",))
    assert doc["exp_id"] == "EXP-004"
    assert doc["promotion_rule"] == "NONE"
    lines = (tmp_path / "EXP-004" / "trades.jsonl").read_text().splitlines()
    assert len(lines) == doc["n_trades_scored"] > 0
    for line in lines:
        rec = json.loads(line)
        assert rec["exit_t"] is None or rec["exit_t"] <= rec["signal_t"] + 135
        assert "fixture_hash" in rec and rec["split"] == "train"
    for _key, cell in doc["cells"].items():
        assert cell["n_signals"] == cell["n_entered"] + cell["n_expired"]
        assert cell["n_entered"] == cell["n_stop"] + cell["n_target"] + cell["n_time"]
