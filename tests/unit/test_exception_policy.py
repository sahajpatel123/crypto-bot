"""T1.3: table-driven exception policy + safe mode.

Pins: classification table (rate-limit / 5xx-read / unknown / rejected /
fatal), bounded retry for idempotent reads, and Session safe mode:
halt entries, attempt flatten with retries, record alert, never raise
out of the live loop while exposure exists.
"""
from __future__ import annotations

from pathlib import Path

import venue_fixtures as venues
from cryptobot.adapters.binance_live import (
    RateLimitedError,
    UnknownOutcomeError,
    VenueHttpError,
    VenueRejectedError,
    classify_exception,
)
from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore


def test_classification_table():
    rl = RateLimitedError(429, -1003, "limit", retry_after_s=2.0)
    assert classify_exception(rl).action == "retry_backoff"
    assert classify_exception(rl).retry_after_s == 2.0
    assert classify_exception(
        VenueHttpError(503, None, "x"), idempotent_read=True
    ).action == "retry_backoff"
    assert classify_exception(
        VenueHttpError(503, None, "x")).action == "safe_mode"
    assert classify_exception(
        UnknownOutcomeError("cid", "timeout")).action == "lookup_first"
    assert classify_exception(
        VenueRejectedError(400, -1013, "bad")).action == "reject_intent"
    assert classify_exception(RuntimeError("boom")).action == "safe_mode"


def test_idempotent_read_retries_then_succeeds(tmp_path):
    script = [
        ("GET", "/fapi/v2/account", None, ("err", 503, None, "down")),
        ("GET", "/fapi/v2/account", None, ("ok", {
            "totalWalletBalance": "100.0", "availableBalance": "90.0",
            "totalMarginBalance": "100.0", "totalInitialMargin": "0",
            "positions": []})),
    ]
    engine, transport = venues.make_engine(tmp_path, script)
    snap = engine.account_snapshot()
    assert snap is not None and snap.wallet_equity_usdt == 100.0
    transport.assert_empty()


class _StubEngine:
    model_label = "t13-stub"
    assumptions = ("stub: t13",)

    def poll(self):
        return []

    def open_orders(self):
        return []


def _session(tmp_path: Path) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    return Session(load_config(cfg_path), store, tmp_path / "run",
                   "t13-run", engine=_StubEngine())


def test_safe_mode_halts_flattens_alerts(tmp_path):
    session = _session(tmp_path)
    calls = []
    session._flatten = lambda reason: calls.append(reason)  # noqa: SLF001
    out = session.enter_safe_mode("venue-down")
    assert out["flatten_attempted"] is True
    assert len(calls) == 1
    assert session.safe_mode_reason == "venue-down"
    assert any("safe-mode" in r for r in session._exit_only_reasons)
    assert session.alerts and session.alerts[-1]["kind"] == "safe-mode"


def test_safe_mode_flatten_failure_still_alerts(tmp_path):
    session = _session(tmp_path)

    def _boom(reason):
        raise RuntimeError("venue unreachable")

    session._flatten = _boom  # noqa: SLF001
    out = session.enter_safe_mode("fatal", attempts=2)
    assert out["flatten_attempted"] is True
    assert out["flatten_ok"] is False
    assert session.alerts[-1]["kind"] == "safe-mode"
