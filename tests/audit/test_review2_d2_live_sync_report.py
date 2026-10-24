"""Review-2 defect 2: false live synchronization report (W5-24H).

A buffered diff that cannot bridge snapshot ID 10 returns resync, but
_prime_live_books ignores the result and reports BTCUSDT in synced.
Actual book.state.synced is false.

Required: report actual outcome and current state separately from REST
fetch success. Buffer before snapshot installation, bridge correctly
and resynchronize after breaks or new-symbol discovery.

Fails on base 3cadfca (bug reproduced); passes once fixed.
Strict-xfail marked in tests/audit/conftest.py while open.
"""
import dataclasses
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore


class _CannedResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _session(tmp_path):
    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "test.toml"
    cfg_path.write_text(text)
    cfg = dataclasses.replace(load_config(cfg_path), symbols=("BTCUSDT",))
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / "liveprime", "liveprime")
    return session, store


def test_prime_reports_actual_sync_state_not_fetch_success(tmp_path,
                                                           monkeypatch):
    """Unbridgeable prime must not report the symbol as synced."""
    session, store = _session(tmp_path)
    try:
        # A diff buffered before the snapshot that snapshot ID 10 cannot
        # bridge (first update 50 spans nothing near 10 + 1).
        assert session._depth_store.apply_diff(
            "BTCUSDT",
            {"first_update": 50, "last_update": 55, "prev_last_update": 49,
             "bids": [], "asks": []}, 500) == "buffered"

        def fake_urlopen(req, timeout=15.0):
            return _CannedResponse(
                {"bids": [["100", "1"]], "asks": [["101", "1"]],
                 "lastUpdateId": 10})

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        summary = session._prime_live_books()
        # Setup guard: the actual book really is unsynced (bridge failed).
        book, _, reason = session._depth_store.book_flow_for(
            "BTCUSDT", 60_000)
        assert book is None and reason, (
            f"setup broken: expected unsynced book, got {book!r}")
        assert "BTCUSDT" not in summary.get("synced", []), (
            f"prime claims synced while the book is unsynced: {summary!r}")
        assert "resync" in json.dumps(summary).lower(), (
            f"prime hides the resync outcome: {summary!r}")
    finally:
        store.close()
