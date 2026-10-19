"""F1.4: replay determinism — same capture twice, byte-identical logs.

Decision logs (fills.jsonl, risk.jsonl bytes; intents/commands dumps)
must match exactly across two runs with fixed event + wall clocks.
Report timing fields (perf noise) are stripped before comparison and
asserted present-but-ignored explicitly.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

CLASS = "synthetic-test"
T0 = 1_700_000_000_000
WALL = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)


def _trade(seq, ts, agg_id, price, qty):
    return {"v": 1, "format": "cryptobot-events/1", "input_class": CLASS,
            "source": "synthetic", "route": "test", "run_id": "sess",
            "seq": seq, "channel": "aggTrade", "symbol": "BTCUSDT",
            "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
            "local_mono_ns": seq, "gap_kind": None, "venue_seq": agg_id,
            "payload": {"agg_id": agg_id, "price": price, "qty": qty,
                        "first_id": agg_id, "last_id": agg_id,
                        "trade_ts_ms": ts, "buyer_is_maker": False}}


def _bbo(seq, ts, bid, ask):
    return {"v": 1, "format": "cryptobot-events/1", "input_class": CLASS,
            "source": "synthetic", "route": "test", "run_id": "sess",
            "seq": seq, "channel": "bookTicker", "symbol": "BTCUSDT",
            "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
            "local_mono_ns": seq, "gap_kind": None, "venue_seq": 0,
            "payload": {"bid": bid, "ask": ask}}


def _capture(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    events = []
    seq = 0
    for w in range(10):
        base = T0 + w * 1000
        price = 100.0 + w * 0.01
        seq += 1
        events.append(_bbo(seq, base + 100, price - 0.01, price + 0.01))
        seq += 1
        events.append(_trade(seq, base + 200, w + 1, price, 1.0))
    (path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _run_once(root: Path, cap: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{root / "runs"}"', 1)
    cfg_path = root / "test.toml"
    cfg_path.write_text(text)
    store = RunStore(root / "runs" / "cryptobot.db")
    workdir = root / "runs" / "det"
    session = Session(load_config(cfg_path), store, workdir, "det",
                      wall_utc=lambda: WALL)
    try:
        session.run_replay(cap, expect_class=CLASS)
    finally:
        store.close()
    return workdir


def _dump_db(root: Path, table: str, cols: str) -> list:
    conn = sqlite3.connect(root / "runs" / "cryptobot.db")
    try:
        return conn.execute(
            f"SELECT {cols} FROM {table} ORDER BY id").fetchall()
    finally:
        conn.close()


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def test_replay_twice_byte_identical(tmp_path):
    cap = _capture(tmp_path / "cap")
    first = _run_once(tmp_path / "a", cap)
    second = _run_once(tmp_path / "b", cap)
    assert _read_bytes(first / "fills.jsonl") == \
        _read_bytes(second / "fills.jsonl")
    assert _read_bytes(first / "risk.jsonl") == \
        _read_bytes(second / "risk.jsonl")
    assert _read_bytes(first / "fills_drift.jsonl") == \
        _read_bytes(second / "fills_drift.jsonl")
    for table, cols in (("intents", "intent_id, decision, reason"),
                        ("execution_events", "execution_id, kind")):
        assert _dump_db(tmp_path / "a", table, cols) == \
            _dump_db(tmp_path / "b", table, cols)


def test_report_identical_modulo_perf_noise(tmp_path):
    cap = _capture(tmp_path / "cap")
    first = _run_once(tmp_path / "a", cap)
    second = _run_once(tmp_path / "b", cap)

    def _scrub(report: dict) -> dict:
        report = json.loads(json.dumps(report))
        report.pop("latency_ms", None)
        report.pop("tick_latency_ms", None)
        report.pop("duration_s", None)
        report.pop("workdir", None)  # run dirs differ by construction
        for key in ("capture_end", "capture_start"):
            report.get("milestones", {}).pop(key, None)
        return report

    rep_a = json.loads((first / "report.json").read_text())
    rep_b = json.loads((second / "report.json").read_text())
    assert "latency_ms" in rep_a  # perf noise exists (stripped, not absent)
    assert _scrub(rep_a) == _scrub(rep_b)
