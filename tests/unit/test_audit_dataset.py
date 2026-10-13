"""CORR-DATA step 4: dataset audit verdict tests (synthetic captures)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BASE_MS = 1791755039610


def _row(seq, channel, symbol, ts, payload):
    event = {"v": 1, "format": "cryptobot-events/1",
             "input_class": "observed-public", "source": "t", "route": "m",
             "run_id": "fx", "seq": seq, "channel": channel, "symbol": symbol,
             "local_recv_ms": (ts or BASE_MS) + 5,
             "gap_kind": None, "payload": payload}
    if ts is not None:
        event["exchange_ts_ms"] = ts
    return event


def _capture(tmp_path: Path, name: str, rows, symbols):
    capture = tmp_path / name
    capture.mkdir()
    (capture / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n")
    (capture / "manifest.json").write_text(json.dumps(
        {"run_id": name, "input_class": "observed-public",
         "symbols": symbols}))
    return capture


def _audit(capture: Path, *extra):
    proc = subprocess.run(
        [sys.executable, "tools/audit_dataset.py", "--capture", str(capture),
         "--json", *extra],
        capture_output=True, text=True, timeout=120)
    return proc.returncode, json.loads(proc.stdout)


def _span_rows(symbol: str, seconds: int, channel="aggTrade"):
    payload = {"price": 100.0, "qty": 0.1} if channel == "aggTrade" else {
        "bid": 99.0, "ask": 101.0}
    return [_row(i + 1, channel, symbol, BASE_MS + i * 1000, payload)
            for i in range(seconds)]


def test_scorable_capture(tmp_path):
    rows = _span_rows("BTCUSDT", 200) + [
        _row(1000 + i, "bookTicker", "ETHUSDT", BASE_MS + i * 1000,
             {"bid": 99.0, "ask": 101.0}) for i in range(200)]
    rows.append(_row(2000, "markPrice", "BTCUSDT", BASE_MS + 199000,
                     {"mark": 100.0, "funding_rate": 1e-05}))
    capture = _capture(tmp_path, "ok", rows, ["BTCUSDT", "ETHUSDT"])
    rc, report = _audit(capture)
    assert rc == 0
    assert report["verdict"] == "SCORABLE"
    assert report["reasons"] == []
    assert report["symbols"]["BTCUSDT"]["executable_rows_usable"] == 200
    assert report["symbols"]["BTCUSDT"]["warmup_coverable"] is True
    assert report["marks"]["BTCUSDT"]["valuation_path"] == "exchange-mark"
    assert report["funding"]["BTCUSDT"]["rows_with_rate"] == 1
    assert report["profile"]["quote_max_age_s"] == 1.0
    assert report["profile"]["diagnostic_only"] is False
    assert report["coverage"]["span_s"] == 199.0


def test_unscorable_no_executable_evidence(tmp_path):
    rows = [_row(1, "markPrice", "BTCUSDT", BASE_MS, {"mark": 100.0})]
    capture = _capture(tmp_path, "marks-only", rows, ["BTCUSDT"])
    rc, report = _audit(capture)
    assert rc == 3
    assert report["verdict"] == "UNSCORABLE"
    assert any("BTCUSDT" in r and "executable" in r
               for r in report["reasons"])


def test_unscorable_unusable_timestamps(tmp_path):
    rows = [_row(i + 1, "aggTrade", "BTCUSDT", None, {"price": 1.0})
            for i in range(3)]
    capture = _capture(tmp_path, "no-ts", rows, ["BTCUSDT"])
    rc, report = _audit(capture)
    assert rc == 3
    assert report["verdict"] == "UNSCORABLE"
    key = "aggTrade/BTCUSDT"
    assert report["streams"][key]["missing_exchange_ts"] == 3


def test_unscorable_missing_filters(tmp_path):
    capture = _capture(tmp_path, "no-filt",
                       _span_rows("ZZZUSDT", 200), ["ZZZUSDT"])
    rc, report = _audit(capture)
    assert rc == 3
    assert any("filters" in r and "ZZZUSDT" in r
               for r in report["reasons"])


def test_diag_profile_labels_verdict(tmp_path):
    capture = _capture(tmp_path, "diag", _span_rows("BTCUSDT", 200),
                       ["BTCUSDT"])
    rc, report = _audit(capture, "--profile", "configs/research_coarse.toml")
    assert rc == 0
    assert report["verdict"] == "SCORABLE"
    assert report["profile"]["diagnostic_only"] is True
    assert report["profile"]["profile_version"] == "diag-coarse-1"
    assert any("DIAGNOSTIC" in w for w in report["warnings"])


def test_gap_warning_names_starvation(tmp_path):
    rows = ([_row(1, "bookTicker", "BTCUSDT", BASE_MS,
                  {"bid": 99.0, "ask": 101.0})]
            + [_row(2, "bookTicker", "BTCUSDT", BASE_MS + 5000,
                    {"bid": 99.0, "ask": 101.0})])
    capture = _capture(tmp_path, "gap", rows, ["BTCUSDT"])
    rc, report = _audit(capture)
    assert rc == 0  # warning, not fatal.
    assert any("starves" in w for w in report["warnings"])
