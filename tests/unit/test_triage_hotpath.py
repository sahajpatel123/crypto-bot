"""F0.5 triage batch 7: hot path + cache truth + cancel window.

A#9/B#16 (MEDIUM): while holding, flat agreement must not REST per
event on live runs (hot_cache): cached snapshots bound reads.
B#15 (MEDIUM): ACCOUNT_UPDATE must not re-mark partially-stale
snapshots fresh (age stays REST-bound).
B#20 (LOW): cancel on UNKNOWN orders attempts the DELETE inside the
refuse-fast window (lookup refused != cancel refused).
"""
from __future__ import annotations

from datetime import datetime, timezone


def _account_view(wallet="5000.0", avail="4900.0"):
    return {"totalWalletBalance": wallet, "availableBalance": avail,
            "totalMarginBalance": wallet, "totalInitialMargin": "0",
            "positions": []}


def test_agree_uses_cached_snapshot_on_hot_cache(tmp_path):
    import venue_fixtures as venues
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore
    from pathlib import Path

    script = [("GET", "/fapi/v2/account", None, ("ok", _account_view()))]
    engine, transport = venues.make_engine(tmp_path, script)
    engine.hot_cache_enabled = True
    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    session = Session(load_config(cfg_path),
                      RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "run", "b7-run", engine=engine)
    pos = {"instrument": "BTCUSDT"}
    for _ in range(10):
        assert session._venue_positions_agree(pos) is True  # noqa: SLF001
    transport.assert_empty()  # exactly 1 REST for 10 agrees


def test_account_update_does_not_refresh_rest_age(tmp_path):
    import time

    import venue_fixtures as venues

    script = [("GET", "/fapi/v2/account", None, ("ok", _account_view()))]
    engine, _ = venues.make_engine(tmp_path, script)
    assert engine.account_margin_cached() == (4900.0, 5000.0)
    at_rest = engine._account_cached_at  # noqa: SLF001
    time.sleep(0.02)
    engine.note_user_event({
        "e": "ACCOUNT_UPDATE", "E": 1,
        "a": {"B": [{"a": "USDT", "wb": "6000.0", "cw": "6000.0"}]}})
    # Wallet value updates, but the snapshot age stays REST-bound:
    # positions/available are still as old as the last REST read.
    assert engine._account_cache.wallet_equity_usdt == 6000.0  # noqa: SLF001
    assert engine._account_cached_at == at_rest  # noqa: SLF001


def test_cancel_attempts_delete_inside_window_for_unknown(tmp_path):
    import venue_fixtures as venues

    engine, transport = venues.make_engine(tmp_path, [])
    engine._journal_transition("submit-intent", "cid-u",  # noqa: SLF001
                               {"symbol": "BTCUSDT", "side": "SELL",
                                "reservation_id": "r-1"})
    engine._states["cid-u"] = "UNKNOWN"  # noqa: SLF001
    engine._symbols["cid-u"] = "BTCUSDT"  # noqa: SLF001
    engine._reservations["cid-u"] = "r-1"  # noqa: SLF001
    # Enter the refuse-fast window (as a 429 would leave it).
    engine._rate_limited_until_ms = engine._now_ms() + 60_000  # noqa: SLF001
    transport.append(
        ("DELETE", "/fapi/v1/order", {"origClientOrderId": "cid-u"},
         ("ok", {"status": "CANCELED"})))
    engine.cancel("cid-u", "triage")  # must NOT raise RateLimitedError
    assert any(r[0] == "DELETE" for r in transport.requests), (
        "cancel never attempted the DELETE inside the window")
    transport.assert_empty()
