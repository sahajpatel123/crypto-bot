"""T1.1: venue-seeded accounting (fail closed).

Defect: Session built Ledger(paper_capital_usdt=120) even live; venue
equity/positions were never seeded. These tests pin: fresh ledger can be
reseeded from venue wallet; non-fresh cannot; Session.seed_from_venue
refuses incomplete snapshots, unknown positions and unknown orders; a
flat/clean venue seeds day-start + profit basis from VENUE equity.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryptobot.accounting.ledger import Ledger
from cryptobot.app.config import load_config
from cryptobot.app.engine import AccountPosition, AccountSnapshot
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def _snap(wallet=5000.0, positions=(), complete=True):
    return AccountSnapshot(wallet_equity_usdt=wallet,
                           available_margin_usdt=wallet,
                           margin_balance_usdt=wallet,
                           positions=tuple(positions),
                           asof_utc=NOW, complete=complete)


class _StubEngine:
    model_label = "t11-stub"
    assumptions = ("stub: t11",)

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
    config = load_config(cfg_path)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    return Session(config, store, tmp_path / "run", "t11-run",
                   engine=_StubEngine())


def test_ledger_reseed_opening_fresh_only():
    ledger = Ledger(120.0)
    ledger.reseed_opening(5000.0)
    assert ledger.marked_equity(100.0) == 5000.0
    ledger.record_fill("BUY", 0.1, 100.0, 0.01, NOW, "e1")
    with pytest.raises(ValueError, match="reseed"):
        ledger.reseed_opening(6000.0)


def test_seed_from_venue_flat_seeds_equity(tmp_path):
    session = _session(tmp_path)
    equity = session.seed_from_venue(_snap(5000.0))
    assert equity == 5000.0
    assert session.ledger.marked_equity(100.0) == 5000.0
    assert session.venue_seed_equity == 5000.0


def test_seed_from_venue_refuses_incomplete(tmp_path):
    session = _session(tmp_path)
    with pytest.raises(ValueError, match="incomplete|unknown"):
        session.seed_from_venue(_snap(complete=False))
    with pytest.raises(ValueError, match="incomplete|unknown"):
        session.seed_from_venue(None)


def test_seed_from_venue_refuses_unknown_position(tmp_path):
    session = _session(tmp_path)
    pos = AccountPosition("BTCUSDT", 0.01, 60000.0, 60000.0)
    with pytest.raises(ValueError, match="position"):
        session.seed_from_venue(_snap(positions=[pos]))


def test_verify_account_modes_sets_and_fails_closed(tmp_path):
    import venue_fixtures as venues
    from cryptobot.adapters.binance_live import VenueRejectedError

    script = [
        ("GET", "/fapi/v1/positionSide/dual", None,
         ("ok", {"dualSidePosition": True})),
        ("POST", "/fapi/v1/positionSide/dual", None, ("ok", {})),
        ("GET", "/fapi/v1/positionSide/dual", None,
         ("ok", {"dualSidePosition": False})),
        ("GET", "/fapi/v1/multiAssetsMargin", None,
         ("ok", {"multiAssetsMargin": False})),
        ("POST", "/fapi/v1/marginType", {"symbol": "BTCUSDT"},
         ("ok", {"code": 200})),
        ("POST", "/fapi/v1/leverage", {"symbol": "BTCUSDT"},
         ("ok", {"leverage": 3})),
    ]
    engine, transport = venues.make_engine(tmp_path, script)
    out = engine.verify_account_modes(["BTCUSDT"], leverage_cap=3.0)
    assert out["position_mode"] == "one-way"
    transport.assert_empty()
    # Leverage above cap fails before any venue call.
    engine2, transport2 = venues.make_engine(tmp_path / "b", [])
    with pytest.raises(VenueRejectedError, match="cap"):
        engine2.verify_account_modes(["BTCUSDT"], leverage_cap=2.0)
    transport2.assert_empty()


def test_seed_from_venue_refuses_unknown_order(tmp_path):
    session = _session(tmp_path)
    with pytest.raises(ValueError, match="order"):
        session.seed_from_venue(_snap(), open_client_ids=["foreign-1"],
                                journal_client_ids=["mine-1"])
    # Journal-owned orders are fine.
    assert session.seed_from_venue(
        _snap(), open_client_ids=["mine-1"],
        journal_client_ids=["mine-1"]) == 5000.0
