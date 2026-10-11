"""Recorder/replayer unit tests (Worker 2, E-001). All rows SYNTHETIC."""
import json

import pytest

from cryptobot.market_data import (
    KlineRecorder,
    analyze_klines,
    load_recording,
    replay,
    replay_hash,
)
from cryptobot.market_data.recorder import INPUT_SYNTHETIC, stats_to_dict
from cryptobot.market_data.replayer import assert_input_class

MIN = 60_000
BASE = 1_700_000_000_000


def _row(open_ms, close_price="100"):
    # SYNTHETIC Binance-shaped REST kline row.
    return [open_ms, "99", "101", "98", close_price, "12.5", open_ms + MIN - 1,
            "1250", 42, "6.0", "600", "0"]


def _write_recording(path, opens, *, recv_lag_ms=1_000, input_class=INPUT_SYNTHETIC):
    rec = KlineRecorder(path, symbol="SYNUSDT", channel="klines/1m",
                        interval_ms=MIN, input_class=input_class,
                        source="unit-test", capture_cmd="pytest synthetic")
    for i, open_ms in enumerate(opens):
        rec.record_rest_kline(_row(open_ms), open_ms + MIN - 1 + recv_lag_ms)
    return rec.finish()


def test_contiguous_recording_has_no_gaps(tmp_path):
    path = tmp_path / "rec.jsonl"
    stats = _write_recording(path, [BASE + i * MIN for i in range(5)])
    assert (stats.count, stats.closed_count) == (5, 5)
    assert stats.gaps == () and stats.stale_count == 0
    assert stats.max_lag_ms == 1_000


def test_missing_interval_is_a_gap(tmp_path):
    path = tmp_path / "gap.jsonl"
    stats = _write_recording(path, [BASE, BASE + MIN, BASE + 3 * MIN])
    assert len(stats.gaps) == 1
    gap = stats.gaps[0]
    assert (gap.first_missing_open_ms, gap.last_missing_open_ms, gap.missing_count) == (
        BASE + 2 * MIN, BASE + 2 * MIN, 1)


def test_late_observation_is_stale(tmp_path):
    path = tmp_path / "stale.jsonl"
    stats = _write_recording(path, [BASE, BASE + MIN], recv_lag_ms=120_000)
    assert stats.stale_count == 2
    assert stats.max_lag_ms == 120_000


def test_forming_kline_excluded_from_closed_and_stale(tmp_path):
    path = tmp_path / "forming.jsonl"
    rec = KlineRecorder(path, symbol="SYNUSDT", channel="klines/1m",
                        interval_ms=MIN, input_class=INPUT_SYNTHETIC,
                        source="unit-test", capture_cmd="pytest synthetic")
    rec.record_rest_kline(_row(BASE), BASE + MIN)
    rec.record_event_kline({"t": BASE + MIN, "T": BASE + 2 * MIN - 1, "o": "1",
                            "h": "1", "l": "1", "c": "1", "v": "1", "x": False},
                           BASE + 10 * MIN)
    stats = rec.finish()
    assert (stats.count, stats.closed_count, stats.stale_count) == (2, 1, 0)


def test_header_footer_and_input_class_label(tmp_path):
    path = tmp_path / "label.jsonl"
    _write_recording(path, [BASE])
    lines = path.read_text().splitlines()
    assert json.loads(lines[0])["input_class"] == "synthetic"
    assert json.loads(lines[-1])["type"] == "footer"
    header, records = load_recording(path)
    assert header["input_class"] == "synthetic" and len(records) == 1


def test_replay_is_deterministic_and_ordered(tmp_path):
    path = tmp_path / "det.jsonl"
    _write_recording(path, [BASE + 2 * MIN, BASE, BASE + MIN])
    _, records = load_recording(path)
    first = [e.exchange_open_ms for e in replay(records)]
    assert first == [BASE, BASE + MIN, BASE + 2 * MIN]
    assert replay_hash(records) == replay_hash(list(reversed(records)))


def test_input_class_mismatch_raises(tmp_path):
    path = tmp_path / "mix.jsonl"
    _write_recording(path, [BASE])
    header, _ = load_recording(path)
    with pytest.raises(ValueError, match="input_class mismatch"):
        assert_input_class(header, "observed-public")


def test_recorder_rejects_unknown_input_class(tmp_path):
    with pytest.raises(ValueError, match="input_class"):
        KlineRecorder(tmp_path / "x.jsonl", symbol="S", channel="c",
                      interval_ms=MIN, input_class="paper",
                      source="t", capture_cmd="t")


def test_stats_serialize(tmp_path):
    path = tmp_path / "s.jsonl"
    stats = _write_recording(path, [BASE])
    assert stats_to_dict(stats)["closed_count"] == 1
