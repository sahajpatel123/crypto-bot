"""SC scalp: real adapter, real session, and the daily-band verdict.

The synthetic tape is built from the frozen SC constants so the
micro-breakout rule can fire. It is not a measurement of the dev
window. The dev window is scored only by ``sc_measure``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.research.sc_measure import (
    BAND_HI,
    BAND_LO,
    annotate,
    average_daily_net_pct,
)
from cryptobot.strategies.contract import SC_BASE
from cryptobot.strategies.runtime import get_adapter
from cryptobot.strategies.s1 import Bar
from cryptobot.strategies.sc import (
    HOLDING_LIMIT_S,
    ROUND_TRIP_BPS,
    TARGET_BPS,
    WARMUP_N,
    evaluate_bar,
)

CLASS = "synthetic-test"
T0 = datetime(2026, 9, 11, 18, 30, tzinfo=timezone.utc)
T0_MS = int(T0.timestamp() * 1000)


def _bar(i: int, price: float) -> Bar:
    return Bar(
        ts_utc=T0 + timedelta(seconds=i),
        open=price, high=price, low=price, close=price,
        volume=1.0, trades=1, buy_frac=0.5, spread_bps=1.0,
        source="synthetic",
    )


def _scalp_bars() -> list[Bar]:
    """60 flat-alternating seconds, then one extension that clears SC."""
    bars: list[Bar] = []
    for i in range(WARMUP_N):
        bars.append(_bar(i, 100.00 if i % 2 == 0 else 100.05))
    bars.append(_bar(WARMUP_N, 100.20))
    return bars


def test_frozen_rule_fires_a_long_scalp_and_clears_cost():
    bars = _scalp_bars()
    long_d, short_d = evaluate_bar(bars, WARMUP_N, SC_BASE, "BTCUSDT")
    assert short_d.intent is None
    assert long_d.intent is not None
    assert long_d.intent.holding_limit_s == HOLDING_LIMIT_S
    assert long_d.intent.holding_limit_s <= 180
    assert "stop" in long_d.intent.exit_rule
    reward = next(part for part in long_d.record.rejects_evaluated
                  if part.startswith("reward="))
    assert float(reward.split("=", 1)[1]) >= ROUND_TRIP_BPS
    assert TARGET_BPS > ROUND_TRIP_BPS


def test_adapter_is_registered():
    adapter = get_adapter("SC")
    assert adapter.strategy_id == "SC"


def _config(tmp_path: Path) -> Path:
    text = Path("configs/sc-dev.toml").read_text(encoding="utf-8")
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    path = tmp_path / "sc.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _event(seq: int, trade_id: int, second: int, kind: str,
           price: float) -> dict:
    ts = T0_MS + second * 1000 + (100 if kind == "bookTicker" else 400)
    base = {
        "v": 1, "format": "cryptobot-events/1", "input_class": CLASS,
        "source": "synthetic", "route": "test", "run_id": "sc",
        "seq": seq, "channel": kind, "symbol": "BTCUSDT",
        "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
        "local_mono_ns": seq, "gap_kind": None, "venue_seq": seq,
    }
    if kind == "bookTicker":
        half = price * 0.5 / 1e4  # about 1 bp full spread
        base["payload"] = {"bid": price - half, "ask": price + half}
    else:
        # Trade ids are consecutive. A gap makes the bar fail-safe None.
        base["payload"] = {
            "agg_id": trade_id, "price": price, "qty": 0.2,
            "first_id": trade_id, "last_id": trade_id, "trade_ts_ms": ts,
            "buyer_is_maker": False,
        }
    return base


def _capture(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    events = []
    seq = 1
    trade_id = 1
    # Dense 1-second tape: range, the extension, then a hold past 90s.
    for second in range(220):
        if second < WARMUP_N:
            price = 100.00 if second % 2 == 0 else 100.05
        elif second == WARMUP_N:
            price = 100.20
        else:
            price = 100.70
        events.append(_event(seq, trade_id, second, "bookTicker", price))
        seq += 1
        events.append(_event(seq, trade_id, second, "aggTrade", price))
        seq += 1
        trade_id += 1
    (path / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8")
    return path


def test_session_books_a_fee_bearing_round_trip_or_names_the_rejection(tmp_path):
    prod = Path("configs/prod.toml").read_text(encoding="utf-8")
    assert "allow_live_submission = false" in prod
    print("PROD_CONFIG configs/prod.toml allow_live_submission=false")
    cfg = load_config(_config(tmp_path))
    assert cfg.strategies_enabled == ("SC",)
    assert cfg.mode == "replay"
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / "sc-unit", "sc-unit")
    try:
        report = session.run_replay(_capture(tmp_path / "cap"),
                                    expect_class=CLASS)
    finally:
        store.close()
    flat_round_trip = (
        report["paid_costs"] > 0.0
        and report["open_position"] is False
        and report["position_qty"] == 0.0
    )
    assert flat_round_trip or report["reject_counts"], report
    if flat_round_trip:
        assert report["paid_costs"] == pytest.approx(session.ledger.paid_costs())
    print("SC_SESSION", json.dumps({
        "paid_costs": report["paid_costs"],
        "net_return_pct": report["net_return_pct"],
        "open_position": report["open_position"],
        "intents_admitted": report["intents_admitted"],
        "reject_counts": report["reject_counts"],
    }))


def test_band_uses_the_ledger_and_does_not_add_zero_funding():
    report = {
        "booked": {
            "equity_open": 120.0,
            "equity_close": 120.0,
            "realised": 0.0,
            "commissions": 0.0,
            "funding": 0.0,
        }
    }
    annotated = annotate(report, validation_net_pct=None)
    assert annotated["sc"]["inside_band"] is False
    assert annotated["sc"]["qualified_for_real_capital"] is False
    assert "outside 1.5-2%" in annotated["sc"]["reason"]
    assert annotated["net_return_pct"] == 0.0
    # A 1.4% ledger day stays outside even if someone treats funding 0
    # as an extra 0.2%. The annotator does not add funding.
    near = {
        "booked": {
            "equity_open": 100.0,
            "equity_close": 101.4,
            "realised": 1.4,
            "commissions": 0.2,
            "funding": 0.0,
        }
    }
    missed = annotate(near, validation_net_pct=5.0)
    assert missed["sc"]["avg_daily_net_pct"] == pytest.approx(1.4)
    assert missed["sc"]["inside_band"] is False
    assert missed["sc"]["qualified_for_real_capital"] is False
    inside = {
        "booked": {
            "equity_open": 100.0,
            "equity_close": 101.7,
            "realised": 1.7,
            "commissions": 0.1,
            "funding": 0.0,
        }
    }
    hit = annotate(inside, validation_net_pct=0.4)
    assert BAND_LO <= hit["sc"]["avg_daily_net_pct"] <= BAND_HI
    assert hit["sc"]["qualified_for_real_capital"] is True
    assert average_daily_net_pct(1.7, 1) == pytest.approx(1.7)
    # Two dates halve the average. A one-day 1.7% is not 3.4%.
    assert average_daily_net_pct(1.7, 2) == pytest.approx(0.85)
