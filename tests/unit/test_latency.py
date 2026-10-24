"""REL-W3-DATA (3): latency ledger honesty + queue-delay wiring."""
from __future__ import annotations

import pytest

from cryptobot.market_data.ingest import BoundedIngest
from cryptobot.market_data.latency import (
    EVENT_AGE,
    FEATURE_CALC,
    FILL_NOTIFY,
    QUEUE_DELAY,
    RISK_TO_COMMAND,
    STOP_CONFIRM,
    TRANSPORT_ACK,
    LatencyLedger,
)


def test_unmeasured_spans_stay_unmeasured():
    ledger = LatencyLedger()
    summary = ledger.summarize()
    assert set(summary) == {EVENT_AGE, QUEUE_DELAY, FEATURE_CALC,
                            RISK_TO_COMMAND, TRANSPORT_ACK, FILL_NOTIFY,
                            STOP_CONFIRM}
    for span, stats in summary.items():
        assert stats["n"] == 0
        assert stats["measured"] is False
        assert stats["max_ms"] == 0.0
    assert summary[EVENT_AGE]["clock_start"] == "venue-exchange"
    assert summary[QUEUE_DELAY]["clock_start"] == "local-mono"


def test_observe_and_quantiles():
    ledger = LatencyLedger()
    for value in (10.0, 20.0, 30.0, 40.0):
        ledger.observe(FEATURE_CALC, value)
    stats = ledger.summarize(FEATURE_CALC)[FEATURE_CALC]
    assert stats["n"] == 4 and stats["measured"] is True
    assert stats["p50_ms"] == pytest.approx(25.0)
    assert stats["p95_ms"] == pytest.approx(38.5)
    assert stats["max_ms"] == 40.0
    # Other spans unaffected: no cross-span masquerading.
    assert ledger.summarize(TRANSPORT_ACK)[TRANSPORT_ACK]["measured"] is False


def test_timer_is_local_mono_only():
    ledger = LatencyLedger()
    with ledger.timer(FEATURE_CALC):
        pass
    assert ledger.summarize(FEATURE_CALC)[FEATURE_CALC]["n"] == 1
    with pytest.raises(ValueError), ledger.timer(TRANSPORT_ACK):
        pass
    with pytest.raises(ValueError), ledger.timer(FILL_NOTIFY):
        pass
    with pytest.raises(ValueError), ledger.timer(STOP_CONFIRM):
        pass


def test_observe_rejects_unknown_and_nonfinite():
    ledger = LatencyLedger()
    with pytest.raises(ValueError):
        ledger.observe("strategy-timer-total", 1.0)
    with pytest.raises(ValueError):
        ledger.observe(QUEUE_DELAY, float("nan"))


def test_ingest_records_queue_delay():
    mono = {"t": 100.0}
    ledger = LatencyLedger(mono_s=lambda: mono["t"])
    ingest = BoundedIngest(["BTCUSDT"], mono_s=lambda: mono["t"],
                           ledger=ledger)
    ingest.publish_market("BTCUSDT", "aggTrade", {"a": 1})
    mono["t"] += 0.025  # 25ms queue delay.
    assert ingest.poll_market("BTCUSDT") == ("aggTrade", {"a": 1})
    stats = ledger.summarize(QUEUE_DELAY)[QUEUE_DELAY]
    assert stats["n"] == 1
    assert stats["p50_ms"] == pytest.approx(25.0)


def test_ingest_without_ledger_unaffected():
    ingest = BoundedIngest(["BTCUSDT"])
    ingest.publish_market("BTCUSDT", "aggTrade", {"a": 1})
    assert ingest.poll_market("BTCUSDT") == ("aggTrade", {"a": 1})
