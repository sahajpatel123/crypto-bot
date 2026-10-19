"""Task B quick wins: list stamping, 5xx cell, 24h soak."""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
import urllib.request
from pathlib import Path

from cryptobot.adapters.mockex_server import DEFAULT_SECRET, MockEx
from cryptobot.emulator.drill import run_drill, run_soak


def _signed(path: str, params: dict) -> str:
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(DEFAULT_SECRET.encode(), qs.encode(),
                   hashlib.sha256).hexdigest()
    return f"{path}?{qs}&signature={sig}"


def test_mockex_list_bodies_are_stamped():
    mock = MockEx()
    port = mock.serve()
    try:
        url = _signed(f"http://127.0.0.1:{port}/fapi/v1/openOrders",
                      {"timestamp": mock.venue.now_ms(), "recvWindow": 60000})
        with urllib.request.urlopen(url) as resp:
            body = json.loads(resp.read().decode())
            assert resp.headers["X-Cryptobot-Provenance"] == "EMULATED"
        assert isinstance(body, list)
        # Place one resting order so the list is non-empty, then re-read.
        from cryptobot.adapters.mockex_server import DEFAULT_KEY  # noqa
        mock.venue.place_order({"symbol": "BTCUSDT", "side": "BUY",
                                "type": "LIMIT", "quantity": 10.0,
                                "price": 1.0, "timeInForce": "GTC"})
        with urllib.request.urlopen(url) as resp:
            body = json.loads(resp.read().decode())
        assert len(body) >= 1
        for row in body:
            assert row.get("emulated") is True
            assert row.get("provenance") == "EMULATED"
    finally:
        mock.close()


def test_drill_has_5xx_cell_and_stays_flat(tmp_path: Path):
    doc = run_drill(tmp_path)
    assert doc["verdict"] == "PASS", doc["cells"]
    names = [c["cell"] for c in doc["cells"]]
    assert "http-503" in names, names
    assert all(c.get("flat") for c in doc["cells"])


def test_soak_defaults_to_24_hours():
    doc = run_soak(24)
    assert doc["hours"] == 24
    assert doc["verdict"] == "PASS"
    assert doc["provenance"] == "EMULATED"
