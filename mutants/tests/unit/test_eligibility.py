"""READY-DATA Track A: gap classes + eligible intervals (synthetic)."""
from __future__ import annotations

import json
from pathlib import Path

from cryptobot.market_data.eligibility import (
    MISSING_TRADE_IDS, QUIET_NO_TRADE, STALE_EXECUTABLE, STALE_MARK,
    TRANSPORT_GAP, UNKNOWN_PROVENANCE, classify_capture)

BASE = 1_791_755_039_000


def _row(seq, channel, symbol, ts, payload, gap=None):
    event = {"v": 1, "format": "cryptobot-events/1",
             "input_class": "observed-public", "source": "t", "route": "m",
             "run_id": "fx", "seq": seq, "channel": channel, "symbol": symbol,
             "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
             "gap_kind": gap, "payload": payload}
    return event


def _trade(seq, symbol, ts, first_id, last_id, agg_id=None):
    return _row(seq, "aggTrade", symbol, ts,
                {"price": 100.0, "qty": 0.1, "first_id": first_id,
                 "last_id": last_id,
                 "agg_id": first_id if agg_id is None else agg_id})


def _bbo(seq, symbol, ts):
    return _row(seq, "bookTicker", symbol, ts, {"bid": 99.0, "ask": 101.0})


def _mark(seq, symbol, ts):
    return _row(seq, "markPrice", symbol, ts, {"mark": 100.0})


def _capture(tmp_path: Path, rows):
    capture = tmp_path / "cap"
    capture.mkdir(exist_ok=True)
    (capture / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n")
    return capture


def _dense(symbol, start_s, n_s, id0=1, bbos=True, marks=True):
    rows, seq, ids = [], [0], [id0]

    def nxt():
        seq[0] += 1
        return seq[0]

    for i in range(n_s):
        ts = BASE + (start_s + i) * 1000
        rows.append(_trade(nxt(), symbol, ts, ids[0], ids[0]))
        ids[0] += 1
        if bbos:
            rows.append(_bbo(nxt(), symbol, ts + 10))
        if marks:
            rows.append(_mark(nxt(), symbol, ts + 20))
    return rows


def _ledger_classes(report, symbol):
    return {(e.get("second", e.get("start_ms")), e["class"])
            for e in report["gap_ledger"] if e["symbol"] == symbol}


def _dense_agg(symbol, start_s, n_s, agg0=1, raw0=1, **kw):
    rows, seq = [], [0]

    def nxt():
        seq[0] += 1
        return seq[0]

    for i in range(n_s):
        ts = BASE + (start_s + i) * 1000
        rows.append(_trade(nxt(), symbol, ts, raw0 + i, raw0 + i,
                           agg_id=agg0 + i))
    return rows


def test_quiet_second_vs_id_jump(tmp_path):
    # Second 5 empty with continuous agg sequence (quiet); seconds 10-11
    # empty across an aggregate break (missing); BBO+marks flow throughout.
    rows = _dense_agg("BTCUSDT", 0, 5)
    rows += [_bbo(1000 + i, "BTCUSDT", BASE + 5000 + i * 100)
             for i in range(5)]
    rows += [_mark(1100, "BTCUSDT", BASE + 5000)]
    rows += _dense_agg("BTCUSDT", 6, 4, agg0=6, raw0=6)
    rows += [_bbo(1200 + i, "BTCUSDT", BASE + 10000 + i * 100)
             for i in range(10)]
    rows += [_mark(1300 + i, "BTCUSDT", BASE + (10 + i) * 1000)
             for i in range(2)]
    rows += _dense_agg("BTCUSDT", 12, 3, agg0=100, raw0=100)
    report = classify_capture(_capture(tmp_path, rows), ["BTCUSDT"],
                              warmup_bars=3)
    classes = dict(_ledger_classes(report, "BTCUSDT"))
    base_s = BASE // 1000
    assert classes[base_s + 5] == QUIET_NO_TRADE
    jumps = [e for e in report["gap_ledger"]
             if e["class"] == MISSING_TRADE_IDS]
    assert len(jumps) == 1
    assert jumps[0]["detail"] == "agg 10..99 absent"
    # Eligible runs skip the empty seconds (no forward-fill).
    runs = report["symbols"]["BTCUSDT"]["market_intervals"]
    covered = [i for i in runs
               if i["start_ms"] <= BASE + 5000 < i["end_ms"]]
    assert covered == []


def test_raw_id_skip_with_continuous_agg_excludes_nothing(tmp_path):
    # Raw IDs skip (venue-side consumption) while aggregate messages are
    # continuous: counted as a volume caveat, excludes no time.
    rows = _dense_agg("BTCUSDT", 0, 10, agg0=1, raw0=1)
    rows += _dense_agg("BTCUSDT", 10, 10, agg0=11, raw0=50)
    report = classify_capture(_capture(tmp_path, rows), ["BTCUSDT"],
                              warmup_bars=3)
    assert [e for e in report["gap_ledger"]
            if e["class"] == MISSING_TRADE_IDS] == []
    sym = report["symbols"]["BTCUSDT"]
    assert sym["venue_raw_id_skips"] == 1
    assert sym["venue_raw_ids_skipped"] == 39
    assert sym["market_eligible_s"] == 20.0


def test_transport_gap_and_marker(tmp_path):
    rows = _dense("BTCUSDT", 0, 4)
    rows.append(_row(9999, "bookTicker", "BTCUSDT", BASE + 4000,
                     {"bid": 1.0, "ask": 2.0}, gap="injected"))
    rows += _dense("BTCUSDT", 6, 4, id0=5)
    report = classify_capture(_capture(tmp_path, rows), ["BTCUSDT"],
                              warmup_bars=3)
    assert len(report["gap_markers"]) == 1
    assert report["gap_markers"][0]["gap_kind"] == "injected"
    classes = dict(_ledger_classes(report, "BTCUSDT"))
    base_s = BASE // 1000
    # Second 5: symbol-silent (marker second has rows; second 5 none).
    assert classes[base_s + 5] == TRANSPORT_GAP


def test_stale_executable_splits_intervals(tmp_path):
    rows = _dense("BTCUSDT", 0, 4, bbos=True, marks=False)
    # 3 silent executable seconds (marks only): stale span.
    rows += [_mark(2000 + i, "BTCUSDT", BASE + (4 + i) * 1000)
             for i in range(3)]
    rows += _dense("BTCUSDT", 7, 4, id0=5, bbos=True, marks=False)
    report = classify_capture(_capture(tmp_path, rows), ["BTCUSDT"],
                              mark_bound_ms=None, warmup_bars=3)
    stale = [e for e in report["gap_ledger"]
             if e["class"] == STALE_EXECUTABLE]
    assert len(stale) == 1
    runs = report["symbols"]["BTCUSDT"]["market_intervals"]
    assert len(runs) == 2


def test_stale_mark_required_only_when_bound_set(tmp_path):
    rows = _dense("BTCUSDT", 0, 10)
    report = classify_capture(_capture(tmp_path, rows), ["BTCUSDT"],
                              mark_bound_ms=1000, warmup_bars=3)
    assert [e for e in report["gap_ledger"]
            if e["class"] == STALE_MARK] == []
    rows2 = _dense("BTCUSDT", 0, 4)
    rows2 += _dense("BTCUSDT", 4, 4, id0=5, bbos=True, marks=False)
    rows2 += _dense("BTCUSDT", 8, 2, id0=9)
    report2 = classify_capture(_capture(tmp_path, rows2), ["BTCUSDT"],
                               mark_bound_ms=1000, warmup_bars=3)
    assert len([e for e in report2["gap_ledger"]
                if e["class"] == STALE_MARK]) == 1
    report3 = classify_capture(_capture(tmp_path, rows2), ["BTCUSDT"],
                               mark_bound_ms=None, warmup_bars=3)
    assert [e for e in report3["gap_ledger"]
            if e["class"] == STALE_MARK] == []


def test_unknown_provenance_edges_and_clocks(tmp_path):
    rows = _dense("BTCUSDT", 10, 140)
    report = classify_capture(_capture(tmp_path, rows), ["BTCUSDT"],
                              warmup_bars=130)
    edges = [e for e in report["gap_ledger"]
             if e["class"] == UNKNOWN_PROVENANCE]
    assert edges == []  # obs start at capture start; 10ms tail is fresh.
    mech = report["mechanical"]["BTCUSDT"]
    assert mech["ready_ms"] == BASE + 10_000 + 130_000
    sym = report["symbols"]["BTCUSDT"]
    assert sym["market_eligible_s"] == 140.0
    assert sym["research_eligible_s"] == 10.0  # post-ready only.
    assert len(sym["research_intervals"]) == 1


def test_depth_flag_without_snapshots(tmp_path):
    capture = _capture(tmp_path, _dense("BTCUSDT", 0, 5))
    report = classify_capture(capture, ["BTCUSDT"], warmup_bars=3)
    assert report["depth"]["present"] is False
    (capture / "depth_snapshots.jsonl").write_text(
        json.dumps({"symbol": "BTCUSDT", "exchange_ts_ms": BASE}) + "\n")
    report2 = classify_capture(capture, ["BTCUSDT"], warmup_bars=3)
    assert report2["depth"]["present"] is True
    assert report2["depth"]["count"] == 1
