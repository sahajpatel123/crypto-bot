"""pivot_funding_capture unit tests (manager-owned, self-contained).

No real sockets: the suite collection imports a probe module that
permanently replaces socket.connect process-wide, so HTTP is stubbed
at the fetch/urlopen boundary (loopback servers cannot work in-suite).
Live HTTP is proven separately by running the tool for real.
Loads tool by path, no src/.
"""
from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "pivot_funding_capture", REPO / "tools" / "pivot_funding_capture.py")
assert SPEC and SPEC.loader
pfc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pfc)

ROWS = [
    {"symbol": "BTCUSDT", "fundingTime": 1000,
     "fundingRate": "0.0001", "markPrice": "1.0"},
    {"symbol": "BTCUSDT", "fundingTime": 2000,
     "fundingRate": "0.0002", "markPrice": "1.0"},
]


def _records(symbol="BTCUSDT"):
    return [{"symbol": symbol, "funding_ts_ms": r["fundingTime"],
             "funding_rate": float(r["fundingRate"]),
             "mark_price": float(r["markPrice"]),
             "source": pfc.SOURCE} for r in ROWS]


def test_once_writes_settlements_with_source(tmp_path, monkeypatch):
    monkeypatch.setattr(pfc, "_fetch",
                        lambda *a, **k: _records())
    out = tmp_path / "funding.jsonl"
    summary = pfc.record_once(["BTCUSDT"], out)
    assert summary["written"] == 2
    recs = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["funding_ts_ms"] for r in recs] == [1000, 2000]
    assert all(r["source"].startswith("GET /fapi/v1/fundingRate")
               for r in recs)
    # Idempotent rerun: nothing new.
    summary2 = pfc.record_once(["BTCUSDT"], out)
    assert summary2["written"] == 0
    assert len(out.read_text().splitlines()) == 2


def test_per_symbol_floor_keeps_all_symbols(tmp_path, monkeypatch):
    out = tmp_path / "funding.jsonl"
    out.write_text(json.dumps({"symbol": "BTCUSDT", "funding_ts_ms": 2000,
                               "funding_rate": 0.1,
                               "source": "GET /fapi/v1/fundingRate"})
                   + "\n", encoding="utf-8")
    monkeypatch.setattr(pfc, "_fetch",
                        lambda symbol, *a, **k: _records(symbol))
    summary = pfc.record_once(["BTCUSDT", "ETHUSDT"], out)
    # BTC has nothing new; ETH (no floor) gets both rows — a global
    # floor would drop ETH.
    assert summary["written"] == 2
    recs = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["symbol"] for r in recs[1:]] == ["ETHUSDT", "ETHUSDT"]


def test_all_fail_raises(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(pfc, "_fetch", _boom)
    with pytest.raises(ValueError, match="all symbols failed"):
        pfc.record_once(["BTCUSDT"], tmp_path / "f.json")


def test_fetch_builds_url_and_parses(monkeypatch):
    seen = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.get_full_url()
        seen["timeout"] = timeout
        return _Resp(json.dumps(ROWS).encode())
    monkeypatch.setattr(pfc.urllib.request, "urlopen", _fake_urlopen)
    rows = pfc._fetch("BTCUSDT", 10, 30.0, base_url="https://x.test")
    assert "symbol=BTCUSDT" in seen["url"] and "limit=10" in seen["url"]
    assert [r["funding_ts_ms"] for r in rows] == [1000, 2000]
    assert all(r["source"] == pfc.SOURCE for r in rows)


def test_no_symbols_rejected(tmp_path):
    with pytest.raises(ValueError, match="no symbols"):
        pfc.record_once([], tmp_path / "f.json")
