"""Adversarial-review regressions (B1/B2/B7/B9, A6)."""
from __future__ import annotations

import types

import pytest

from cryptobot.app.session import Session


class _Ledger:
    def __init__(self, qty=0.0):
        self.qty = qty

    def has_position(self):
        return abs(self.qty) > 0

    def position_qty(self):
        return self.qty


class _Store:
    def __init__(self):
        self.checkpoints = []

    def checkpoint(self, run_id, kind, detail):
        self.checkpoints.append((kind, detail))


def _fake_session(*, ledger=None, engine=None):
    self = Session.__new__(Session)
    self.ledger = ledger or _Ledger()
    self.engine = engine or types.SimpleNamespace()
    self.store = _Store()
    self.run_id = "r"
    self._position = None
    self._exit_only_reasons = set()
    self._health_halt_reasons = set()
    return self


def test_unreachable_venue_is_not_flat():
    engine = types.SimpleNamespace(
        model_label="binance-usdm-live", account_snapshot=lambda: None)
    self = _fake_session(engine=engine)
    assert self._is_flat_confirmed() is False
    assert self._venue_positions_agree({}) is False
    assert self.store.checkpoints[-1][0] == "flat-blocked"


def test_reference_engine_none_snapshot_keeps_ledger_fallback():
    engine = types.SimpleNamespace(
        model_label="reference-fake-venue", account_snapshot=lambda: None)
    self = _fake_session(engine=engine)
    assert self._is_flat_confirmed() is True


def test_hard_halts_survive_day_roll_release():
    self = _fake_session()
    self._exit_only_reasons = {"safe-mode:flatten-failed",
                               "funding-mismatch", "health:stale-mark",
                               "feed-drop-breaker"}
    self._release_all_exit_only("day-reconciled")
    assert "safe-mode:flatten-failed" in self._exit_only_reasons
    assert "funding-mismatch" in self._exit_only_reasons
    assert "health:stale-mark" not in self._exit_only_reasons
    assert "feed-drop-breaker" not in self._exit_only_reasons


def test_malformed_venue_position_is_incomplete_not_flat():
    from cryptobot.adapters.binance_live import BinanceLiveEngine

    with pytest.raises(ValueError, match="malformed positionAmt"):
        BinanceLiveEngine._snapshot_positions(
            [{"symbol": "BTCUSDT", "positionAmt": "N/A"}])
    with pytest.raises(ValueError, match="not a list"):
        BinanceLiveEngine._snapshot_positions({"BTCUSDT": 1})


def test_maintenance_margin_never_negative():
    from cryptobot.risk.margin import maintenance_margin

    assert maintenance_margin(100.0, [{
        "notionalCap": 1e9, "maintMarginRatio": 0.004,
        "cum": 1e5}]) == 0.0


def test_leave_protected_requires_live_venue_stop():
    self = _fake_session(ledger=_Ledger(1.0))
    self.leave_protected = True
    self._position = {"legs": ["stop-1"]}

    class Engine:
        def order_status(self, cid):
            return types.SimpleNamespace(state="cancelled", qty=1.0,
                                         filled_qty=0.0)

    self.engine = Engine()
    with pytest.raises(ValueError, match="venue stop is cancelled"):
        self.shutdown_flatten()
