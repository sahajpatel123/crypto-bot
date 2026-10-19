"""Study 01/02/03 unit tests (manager-owned, self-contained).

Covers: --rt-cost changes charge only (identical trade list), gz fallback
for study readers, study-02 trend math, study-03 funding sum + provenance
gate. Loads tools by path, no src/. Synthetic captures only.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "tools" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s1 = _load("pivot_study_01_momentum")
s2 = _load("pivot_study_02_swing")
s4 = _load("pivot_study_04_maker")

T0 = 1_760_000_000_000  # 2026-01-01T00:00Z


def _write_trades(cap, secs, px_fn):
    cap.mkdir(parents=True, exist_ok=True)
    with open(cap / "events.jsonl", "w") as fh:
        for i, s in enumerate(secs):
            fh.write(json.dumps(
                {"v": 1, "format": "cryptobot-events/1", "seq": i + 1,
                 "channel": "aggTrade", "symbol": "BTCUSDT",
                 "exchange_ts_ms": T0 + s * 1000,
                 "payload": {"price": px_fn(s), "qty": 1.0, "agg_id": s,
                             "first_id": s, "last_id": s,
                             "is_buyer_maker": False}},
                sort_keys=True) + "\n")
    (cap / "manifest.json").write_text(json.dumps(
        {"run_id": "synth", "symbols": ["BTCUSDT"], "date": "2026-01-01"}))


def test_s1_rt_cost_changes_charge_only(tmp_path):
    cap = tmp_path / "cap"
    # Choppy: alternate +/-20bps each minute -> fires 15bps cells.
    _write_trades(cap, range(0, 3600),
                  lambda s: 100 * (1 + 0.002 * ((s // 60) % 2 * 2 - 1)))
    closes = s1.load_bars(cap, "BTCUSDT")
    ordered = sorted(closes)
    a = s1.score_side(closes, ordered, 15, "LONG", 26.0)
    b = s1.score_side(closes, ordered, 15, "LONG", 52.0)
    assert a["n"] > 0 and b["n"] == a["n"]  # identical trade list
    assert b["net_mean_bps"] == round(a["net_mean_bps"] - 26.0, 2)


def test_s1_reads_gz_when_plain_absent(tmp_path):
    cap = tmp_path / "cap"
    _write_trades(cap, range(0, 600), lambda s: 100.0)
    plain = cap / "events.jsonl"
    blob = plain.read_bytes()
    with gzip.open(cap / "events.jsonl.gz", "wb") as fh:
        fh.write(blob)
    plain.unlink()
    closes = s1.load_bars(cap, "BTCUSDT")
    assert len(closes) == 600


def test_s2_trend_math_and_gz(tmp_path):
    cap = tmp_path / "cap"
    _write_trades(cap, range(0, 86400), lambda s: 100 * (1 + 0.04 * s / 86400))
    bars = s2.hour_bars(s2.load_closes(cap, "BTCUSDT"))
    assert len(bars) == 24
    res = s2.score(bars, 26.0)
    assert res["LONG"]["n"] == 12  # entries h4..h15, 4h exit in-day
    assert res["SHORT"]["n"] == 0
    assert res["LONG"]["gross_mean_bps"] == round(400 / 6, 2) or \
        abs(res["LONG"]["gross_mean_bps"] - 66.7) < 3.0
    # Gz fallback path.
    plain = cap / "events.jsonl"
    with gzip.open(cap / "events.jsonl.gz", "wb") as fh:
        fh.write(plain.read_bytes())
    plain.unlink()
    bars2 = s2.hour_bars(s2.load_closes(cap, "BTCUSDT"))
    assert len(bars2) == 24


def _book(ts, bid, ask, q=0.001):
    return {"channel": "bookTicker", "exchange_ts_ms": ts,
            "payload": {"bid": bid, "ask": ask, "bid_qty": q, "ask_qty": q}}


def _trade(ts, px, qty, sell):
    return {"channel": "aggTrade", "exchange_ts_ms": ts,
            "payload": {"price": px, "qty": qty, "buyer_is_maker": sell}}


def test_s4_fills_both_sides_flat_book():
    evs = []
    for s in range(60):
        ts = T0 + s * 1000
        evs.append(_book(ts, 100.0, 100.02))
        evs.append(_trade(ts + 10, 100.0, 0.01, True))
        evs.append(_trade(ts + 20, 100.02, 0.01, False))
    res = s4._simulate(evs, 2.0)
    assert res["BID"]["n"] == 60 and res["ASK"]["n"] == 60
    assert res["BID"]["net_mean_bps"] == -3.0  # 1bp half-spread - 4bps RT


def test_s4_toxicity_cancels_and_cools_down():
    # Bid joins at 100.0; mid crashes 10bps within 2s -> cancel + 30s cooldown.
    evs = [_book(T0, 100.0, 100.02)]
    evs.append(_book(T0 + 2000, 99.90, 99.92))  # mid -10bps vs join
    # Heavy selling that WOULD fill a resting bid — must not fill.
    for s in range(3, 25):
        evs.append(_trade(T0 + s * 1000, 99.90, 1.0, True))
    res = s4._simulate(evs, 2.0)
    assert res["BID"]["n"] == 0


def test_s4_gap_cancels_and_chase_rejoins():
    evs = [_book(T0, 100.0, 100.02)]
    evs.append(_book(T0 + 10000, 100.01, 100.03))  # 10s gap -> cancel, rejoin new level
    evs.append(_trade(T0 + 10010, 100.01, 0.01, True))  # fills NEW bid level
    res = s4._simulate(evs, 2.0)
    assert res["BID"]["n"] == 1


def test_s3_sums_funding_and_gates_provenance(tmp_path, capsys):
    import sys
    s3 = _load("pivot_study_03_carry")
    cap = tmp_path / "cap"
    cap.mkdir()
    (cap / "manifest.json").write_text(json.dumps({"date": "2026-01-01"}))
    (cap / "funding.jsonl").write_text(
        json.dumps({"funding_rate": 0.0001, "source": "x"}) + "\n" +
        json.dumps({"funding_rate": -0.00005, "source": "y"}) + "\n")
    argv, sys.argv = sys.argv, ["s3", "--capture", str(cap),
                               "--out", str(tmp_path / "o.json")]
    try:
        assert s3.main() == 0
    finally:
        sys.argv = argv
    out = json.loads((tmp_path / "o.json").read_text())
    assert out["funding_bps"] == 0.5 and out["settlements"] == 2
    # Missing provenance -> BLOCKED.
    cap2 = tmp_path / "cap2"
    cap2.mkdir()
    (cap2 / "manifest.json").write_text(json.dumps({"date": "2026-01-01"}))
    (cap2 / "funding.jsonl").write_text(
        json.dumps({"funding_rate": 0.0001}) + "\n")
    sys.argv = ["s3", "--capture", str(cap2), "--out", str(tmp_path / "o2.json")]
    try:
        assert s3.main() == 2
    finally:
        sys.argv = argv
