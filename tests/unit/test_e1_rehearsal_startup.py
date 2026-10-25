"""E1 startup contract between account-mode verification and the drill."""
from __future__ import annotations

import pytest

import e1_harness as h
from cryptobot.adapters.binance_live import VenueRejectedError


@pytest.fixture()
def emu(tmp_path):
    emulator = h.Emu(tmp_path)
    try:
        yield emulator
    finally:
        emulator.close()


def test_account_mode_verification_primes_exchange_filters(emu):
    """The drill reads filters after mode verification and before submit."""
    engine = emu.engine("drill-startup")
    engine.verify_account_modes([h.BTC], leverage_cap=3)
    assert h.BTC in engine._filters
    assert engine._filters[h.BTC]["step"] > 0
    assert engine.valuation_mark(h.BTC) > 0


@pytest.mark.parametrize("mark", ["NaN", "Infinity", "0", "-1"])
def test_invalid_mark_is_operator_readable_and_rejected(emu, monkeypatch, mark):
    engine = emu.engine("invalid-mark")
    original = engine._public

    def bad_mark(method, path, params=None):
        if method == "GET" and path == "/fapi/v1/premiumIndex":
            return {"markPrice": mark}
        return original(method, path, params)

    monkeypatch.setattr(engine, "_public", bad_mark)
    with pytest.raises(VenueRejectedError,
                       match="venue returned no valid mark price for BTCUSDT"):
        engine.verify_account_modes([h.BTC], leverage_cap=3)


def test_missing_exchange_filters_are_operator_readable(emu, monkeypatch):
    """An unsupported symbol must fail clearly, never as a later KeyError."""
    engine = emu.engine("missing-filter")
    original = engine._public

    def no_symbol(method, path, params=None):
        if method == "GET" and path == "/fapi/v1/exchangeInfo":
            return {"symbols": []}
        return original(method, path, params)

    monkeypatch.setattr(engine, "_public", no_symbol)
    with pytest.raises(VenueRejectedError,
                       match="venue publishes no filters for BTCUSDT"):
        engine.verify_account_modes([h.BTC], leverage_cap=3)
