"""Watchdog review: engine-clock advance, stream-stall resync, bounded drain."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.store import RunStore


def _paper_config(tmp_path: Path):
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    text = text.replace("warmup_bars =", "warmup_bars = 3 #", 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    return load_config(cfg_path)


class _WatchdogStubEngine:
    model_label = "watchdog-stub"
    assumptions = ("stub: watchdog",)
    advance_calls: list
    pop_calls: int

    def __init__(self):
        self.advance_calls = []
        self.pop_calls = 0
        self._engine_now = datetime(2020, 1, 1, tzinfo=UTC)

    @property
    def now_utc(self):
        return self._engine_now

    def advance_to(self, ts_utc):
        self.advance_calls.append(ts_utc)
        self._engine_now = ts_utc

    def submit(self, cmd):
        raise AssertionError("no-trade expected")

    def submit_immediate(self, cmd):
        raise AssertionError("no-trade expected")

    def resolve(self, cid):
        return None

    def cancel(self, cid, reason):
        pass

    def poll(self):
        return []

    def pop_events(self, max_events: int = 1000):
        self.pop_calls += 1
        return []

    def attach_protection(self, e, s, t):
        return []

    def open_orders(self):
        return []

    def filled_qty(self, cid):
        return 0.0

    def set_exit_only(self, h, reason=""):
        pass

    def note_mark(self, i, p):
        pass

    def recover(self, sink):
        pass

    def close(self):
        pass


def _armed_session(tmp_path: Path, engine, monkeypatch):
    from dataclasses import replace

    from cryptobot.app.filters import build_run_filters
    from cryptobot.app.session import Session, WallClock

    cfg = _paper_config(tmp_path)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / "wd-1", "wd-1",
                      clock=WallClock(), engine=engine)
    entries = [{"symbol": "BTCUSDT", "status": "TRADING", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
        {"filterType": "LOT_SIZE", "minQty": "0.001",
         "maxQty": "1000", "stepSize": "0.001"},
        {"filterType": "MIN_NOTIONAL", "notional": "50"}]}]
    filters, asof = build_run_filters(
        ["BTCUSDT"], max_notional_cap_usdt=cfg.max_notional_cap_usdt,
        http_get=lambda url, timeout: ({"symbols": entries}, 1.0))
    session.policy.config = replace(
        session.policy.config, instrument_filters=filters,
        filters_asof_utc=asof, run_mode=True)
    primes = []
    monkeypatch.setattr(
        session, "_fetch_depth_snapshots",
        lambda: primes.append(1) or {})
    return session, store, primes


def _bbo(ts: int):
    return {"channel": "bookTicker", "symbol": "BTCUSDT",
            "input_class": "observed-public",
            "exchange_ts_ms": ts + 100, "local_recv_ms": ts + 105,
            "payload": {"bid": 99.99, "ask": 100.01}}


def test_engine_clock_advances_on_idle_heartbeats(tmp_path, monkeypatch):

    engine = _WatchdogStubEngine()
    session, store, _ = _armed_session(tmp_path, engine, monkeypatch)
    try:
        report = session.run_live(iter([None, None, None]), duration_s=30)
        assert report["mode"] == "paper"
        # Every wake (even idle) pushes the native clock to wall time.
        assert len(engine.advance_calls) == 3
        assert engine.advance_calls[-1].tzinfo is not None
        # Live wakes use the bounded drain, never the unbounded poll.
        assert engine.pop_calls >= 3
    finally:
        store.close()


def test_stream_stall_triggers_book_resync(tmp_path, monkeypatch):
    import time
    from dataclasses import replace

    from cryptobot.app import session as session_mod

    engine = _WatchdogStubEngine()
    session, store, primes = _armed_session(tmp_path, engine, monkeypatch)
    # Explicit symbols so the startup prime really fetches (dynamic
    # discovery skips the upfront prime).
    session.config = replace(session.config, symbols=["BTCUSDT"])
    real_mono = time.monotonic()
    fake = {"now": real_mono}
    monkeypatch.setattr(time, "monotonic", lambda: fake["now"])
    # Also patch the session module reference if it bound time directly.
    monkeypatch.setattr(session_mod.time, "monotonic", lambda: fake["now"])
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    base = (now_ms // 1000) * 1000 - 9000
    # The pump thread drains gen() ahead of the control thread, so the
    # 61s silence jump is driven from the control thread after wake 1.
    calls = {"n": 0}
    real_step = session._control_step

    def stepping(event, producer, adapters, modules, ctx, deadline, expect):
        calls["n"] += 1
        if calls["n"] == 2:
            fake["now"] = real_mono + 61.0  # 61s of market silence.
        return real_step(event, producer, adapters, modules, ctx,
                         deadline, expect)

    monkeypatch.setattr(session, "_control_step", stepping)

    def gen():
        yield _bbo(base)
        yield None
        yield None

    try:
        report = session.run_live(gen(), duration_s=30)
        assert report["mode"] == "paper"
        assert len(primes) == 2  # startup prime + stall resync.
        risk_path = session.workdir / "risk.jsonl"
        kinds = [json.loads(line).get("kind")
                 for line in risk_path.read_text().splitlines()
                 if line.strip()]
        assert "stream-stall" in kinds
    finally:
        store.close()
