"""T1.2: hot path must not do signed REST per event.

Pins: account_margin/account_snapshot serve a <=5s cache updated by
ACCOUNT_UPDATE; stale cache forces REST; request-weight governor reads
transport headers; risk monitor_tick debounces fsync (transitions force).
"""
from __future__ import annotations

import venue_fixtures as venues
from cryptobot.risk.policy import RiskPolicy
from cryptobot.risk.types import RiskConfig


def _account(wallet="5000.0", avail="4900.0"):
    return {"totalWalletBalance": wallet, "availableBalance": avail,
            "totalMarginBalance": wallet, "totalInitialMargin": "0",
            "positions": []}


def test_account_margin_cached_and_stream_updated(tmp_path):
    script = [("GET", "/fapi/v2/account", None, ("ok", _account()))]
    engine, transport = venues.make_engine(tmp_path, script)
    assert engine.account_margin() == (4900.0, 5000.0)
    # Second CACHED call within TTL: no REST (script exhausted).
    assert engine.account_margin_cached() == (4900.0, 5000.0)
    engine.note_user_event({
        "e": "ACCOUNT_UPDATE", "E": 1,
        "a": {"B": [{"a": "USDT", "wb": "6000.0", "cw": "6000.0"}]}})
    assert engine.account_margin_cached()[0] == 4900.0  # avail unchanged
    snap = engine.account_snapshot_cached()
    assert snap is not None and snap.wallet_equity_usdt == 6000.0
    transport.assert_empty()


def test_account_cache_stale_forces_rest(tmp_path):
    script = [("GET", "/fapi/v2/account", None, ("ok", _account())),
              ("GET", "/fapi/v2/account", None,
               ("ok", _account("7000.0", "6900.0")))]
    engine, transport = venues.make_engine(tmp_path, script)
    assert engine.account_margin_cached() == (4900.0, 5000.0)
    engine._account_cached_at -= 10.0  # age beyond TTL
    assert engine.account_margin_cached() == (6900.0, 7000.0)
    transport.assert_empty()


def test_weight_governor_from_headers(tmp_path):
    engine, transport = venues.make_engine(tmp_path, [])
    transport.last_used_weight_1m = 100
    assert engine.weight_used_1m() == 100
    assert engine.weight_budget_ok(limit=2400, reserve_frac=0.1)
    transport.last_used_weight_1m = 2300
    assert not engine.weight_budget_ok(limit=2400, reserve_frac=0.1)


def test_monitor_tick_debounces_fsync(tmp_path, monkeypatch):
    import cryptobot.risk.policy as policy_mod

    saves = []
    monkeypatch.setattr(policy_mod, "save_state",
                        lambda p, s: saves.append(1))
    pol = RiskPolicy(RiskConfig(), state_path=tmp_path / "risk.json")
    pol.reconcile_day(10000.0)
    saves.clear()
    from cryptobot.risk.types import AccountSnapshot
    acct = AccountSnapshot(reconciled_equity=10000.0, marked_equity=10000.0,
                           net_liquidation=10000.0, net_realised_global=0.0,
                           open_position=False)
    for _ in range(5):
        pol.monitor_tick(account=acct)
    assert len(saves) <= 2  # debounced: not one fsync per tick
    pol.flush_state()
    assert len(saves) >= 1
