"""Venue filter sourcing tests (manager-owned, run-mode arming)."""

import pytest

from cryptobot.app.filters import FilterError, build_run_filters


def _payload(symbols=("BTCUSDT",), status="TRADING", drop=None):
    entries = []
    for symbol in symbols:
        filters = [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
            {"filterType": "LOT_SIZE", "minQty": "0.001",
             "maxQty": "1000", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "50"},
        ]
        if drop:
            filters = [f for f in filters if f["filterType"] != drop]
        entries.append({"symbol": symbol, "status": status, "filters": filters})
    return entries


def _http(entries):
    def get(url, timeout):
        assert "exchangeInfo" in url
        return {"symbols": entries}, 1.0
    return get


def test_build_complete_filters():
    filters, asof = build_run_filters(
        ["BTCUSDT"], max_notional_cap_usdt=500.0,
        http_get=_http(_payload()))
    filt = filters["BTCUSDT"]
    assert filt.complete() is True
    assert (filt.tick_size, filt.qty_step, filt.min_qty, filt.max_qty,
            filt.min_notional_usdt, filt.max_notional_usdt) == (
        0.10, 0.001, 0.001, 1000, 50, 500.0)
    assert asof.tzinfo is not None


def test_unknown_symbol_fails_closed():
    with pytest.raises(FilterError, match="not on venue"):
        build_run_filters(["NOPEUSDT"], max_notional_cap_usdt=500.0,
                          http_get=_http(_payload()))


def test_non_trading_status_fails_closed():
    with pytest.raises(FilterError, match="!= TRADING"):
        build_run_filters(["BTCUSDT"], max_notional_cap_usdt=500.0,
                          http_get=_http(_payload(status="HALT")))


def test_missing_filter_fails_closed():
    with pytest.raises(FilterError, match="LOT_SIZE"):
        build_run_filters(["BTCUSDT"], max_notional_cap_usdt=500.0,
                          http_get=_http(_payload(drop="LOT_SIZE")))


def test_bad_cap_fails_closed():
    with pytest.raises(FilterError, match="cap"):
        build_run_filters(["BTCUSDT"], max_notional_cap_usdt=0.0,
                          http_get=_http(_payload()))


def test_arm_run_mode_wires_policy(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore
    text = open("configs/paper.toml").read()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)

    class StubEngine:
        model_label = "stub-test"
        assumptions = ("stub",)
        def submit(self, cmd): raise AssertionError()
        def submit_immediate(self, cmd): raise AssertionError()
        def resolve(self, cid): return None
        def cancel(self, cid, reason): pass
        def poll(self): return []
        def attach_protection(self, e, s, t): return []
        def open_orders(self): return []
        def filled_qty(self, cid): return 0.0
        def set_exit_only(self, h, reason=""): pass
        def note_mark(self, i, p): pass
        def recover(self, sink): pass
        def close(self): pass

    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        session = Session(load_config(cfg_path), store,
                          tmp_path / "runs" / "arm-1", "arm-1",
                          engine=StubEngine())
        store.create_run("arm-1", "paper", "fp", str(session.workdir), None)
        assert session.policy.config.run_mode is False
        session.arm_run_mode(["BTCUSDT"], http_get=_http(_payload()))
        assert session.policy.config.run_mode is True
        assert session.policy.config.instrument_filters["BTCUSDT"].complete()
    finally:
        store.close()
