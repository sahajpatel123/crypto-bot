"""Integrity-report tests over canned chunk files (gz + jsonl).

One fixture carries an aggTrade id gap, a timestamp regression, and a depth
chain break; the report must count each exactly once. A clean fixture must
report zero violations. Offline only. No network.
"""
import gzip
import json
from pathlib import Path

from cryptobot.recorder.integrity import build_report, render_markdown


def _trade(agg_id, ts, symbol="BTCUSDT"):
    return {"channel": "aggTrade", "symbol": symbol, "exchange_ts_ms": ts,
            "local_recv_ms": ts, "venue_seq": agg_id,
            "payload": {"agg_id": agg_id}}


def _depth(first, last, prev, ts, symbol="BTCUSDT"):
    return {"channel": "depth", "symbol": symbol, "exchange_ts_ms": ts,
            "local_recv_ms": ts, "venue_seq": last,
            "payload": {"first_update": first, "last_update": last,
                        "prev_last_update": prev}}


def _write(path, records, gz=False):
    text = "".join(json.dumps(r) + "\n" for r in records)
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(text)
    else:
        Path(path).write_text(text)


def test_report_counts_each_violation_exactly_once(tmp_path):
    run = tmp_path / "run"
    (run / "chunks").mkdir(parents=True)
    # aggTrade ids 1,2,5 -> exactly one gap (3-4 missing); exchange ts
    # regresses on the third line (2000 -> 1500); local ts stays monotonic.
    trades = [_trade(1, 1000), _trade(2, 2000), _trade(5, 3000)]
    trades[2]["exchange_ts_ms"] = 1500
    _write(run / "chunks" / "BTCUSDT.aggTrade.20260101T00.jsonl.gz", trades, gz=True)
    # Depth chain 51-55 -> 56-60 -> break (prev 69, expected 60).
    depths = [_depth(51, 55, 50, 1100), _depth(56, 60, 55, 1200),
              _depth(70, 75, 69, 1300)]
    _write(run / "chunks" / "BTCUSDT.depth.20260101T00.jsonl", depths)
    (run / "manifest.jsonl").write_text(
        "".join(json.dumps({"chunk": f"c{i}", "gapped": i == 0}) + "\n" for i in range(4)))

    report = build_report(run)
    assert report["files"] == 2
    assert report["events"] == 6

    gaps = report["trade_gaps"]["BTCUSDT"]["gaps"]
    assert len(gaps) == 1
    assert gaps[0] == {"prev": 2, "next": 5, "missing": 2}

    mono = report["monotonicity"]
    assert mono["exchange_violations"] == 1
    assert mono["local_violations"] == 0

    assert report["depth_breaks"]["total"] == 1
    breaks = report["depth_breaks"]["breaks"]["BTCUSDT"]
    assert len(breaks) == 1
    assert breaks[0]["expected_prev"] == 60 and breaks[0]["got_prev"] == 69

    assert report["manifest"]["gap_rate"] == 0.25

    text = render_markdown(report)
    assert "gap_rate=0.2500" in text and "Depth-chain breaks: 1" in text


def test_clean_chunks_report_zero_violations(tmp_path):
    run = tmp_path / "run"
    (run / "chunks").mkdir(parents=True)
    trades = [_trade(i, 1000 + i * 10, symbol="ETHUSDT") for i in (10, 11, 12)]
    depths = [_depth(51, 55, 50, 1000, symbol="ETHUSDT"),
              _depth(56, 60, 55, 1010, symbol="ETHUSDT"),
              _depth(61, 70, 60, 1020, symbol="ETHUSDT")]
    _write(run / "chunks" / "ETHUSDT.aggTrade.20260101T00.jsonl", trades)
    _write(run / "chunks" / "ETHUSDT.depth.20260101T00.jsonl.gz", depths, gz=True)

    report = build_report(run)
    assert report["trade_gaps"]["ETHUSDT"]["gaps"] == []
    assert report["trade_gaps"]["ETHUSDT"]["missing_total"] == 0
    assert report["monotonicity"]["exchange_violations"] == 0
    assert report["monotonicity"]["local_violations"] == 0
    assert report["depth_breaks"]["total"] == 0
    assert report["manifest"]["present"] is False
    assert report["malformed_lines"] == 0
