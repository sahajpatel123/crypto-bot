"""W3-30MIN §4+§9 runtime controls: tick, gates, budget, prod guards.

Deterministic proofs: stop/entry-block recognition within 1s under a
2s-blocked producer (250ms tick), 1s quote-age gate, budget-bounded
network deadlines, reconcile-before-entries, and prod default-off.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.session import Session, WallClock, _SymbolFeed
from cryptobot.app.store import RunStore
from cryptobot.coordination.exits import ExitPolicy, encode_exit_rule
from cryptobot.coordination.intent import (
    DataQuality, ForecastCost, Intent, Side)
from cryptobot.coordination.selector import Candidate


def _paper_config(tmp_path: Path, **over) -> object:
    text = open("configs/paper.toml").read()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    for key, value in over.items():
        text = text.replace(f"{key} =", f"{key} = {value} #", 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    return load_config(cfg_path)


class _CtlEngine:
    model_label = "ctl-stub"
    assumptions = ("stub: 30min controls",)

    def __init__(self):
        self.advance_calls: list = []
        self.pop_calls = 0
        self.marks: list = []
        self.exit_only: list = []
        self.submits: list = []
        self.cancels: list = []
        self._now = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self._unknown: list = []

    @property
    def now_utc(self):
        return self._now

    def advance_to(self, ts_utc):
        self.advance_calls.append(ts_utc)
        self._now = ts_utc

    def poll(self):
        return []

    def pop_events(self, max_events: int = 1000):
        self.pop_calls += 1
        return []

    def note_mark(self, instrument, price):
        self.marks.append((instrument, price))

    def set_exit_only(self, halted, reason=""):
        self.exit_only.append((halted, reason))

    def recover(self, sink):
        pass

    def close(self):
        pass

    def unknown_ids(self):
        return list(self._unknown)

    def resolve(self, cid):
        return None

    def cancel(self, cid, reason):
        self.cancels.append((cid, reason))

    def submit(self, cmd):
        self.submits.append(cmd)
        return "ctl-1"

    def submit_immediate(self, cmd):
        self.submits.append(cmd)
        return "ctl-1"


def _ctl_session(tmp_path: Path, engine=None, name="ctl-1", **over):
    engine = engine or _CtlEngine()
    cfg = _paper_config(tmp_path, **over)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / name, name,
                      clock=WallClock(), engine=engine)
    session.policy.reconcile_day(120.0, 0.0)
    # No create_run: run_live owns run registration; direct-call tests
    # only need ledger/policy/store handles.
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin="test", asof_utc=datetime.now(timezone.utc))
    session._init_run_files()
    return session, store


def _intent(now: datetime, **over) -> Intent:
    args = dict(
        strategy="S1", version="0.1.0", instrument="BTCUSDT",
        side=Side.LONG, evidence_ts_utc=now,
        entry_low=100.0, entry_high=100.55,
        entry_expiry_utc=now + timedelta(seconds=60),
        invalidation_price=99.0,
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=99.0, target_price=102.0,
            time_exit_utc=now + timedelta(seconds=600),
            policy_id="test")),
        holding_limit_s=600,
        forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
        evidence_ref="test:ctl", data_quality=DataQuality.CLEAN)
    args.update(over)
    return Intent(**args)


def _seed_mark(session, age_s=0.0, symbol="BTCUSDT"):
    feed = _SymbolFeed(symbol, 0)
    feed.mark = 100.0
    feed.mark_ts = session.now_utc() - timedelta(seconds=age_s)
    session._feeds[symbol] = feed


def _risk_reasons(session) -> list:
    path = session.workdir / "risk.jsonl"
    if not path.exists():
        return []
    return [json.loads(line).get("reason", "")
            for line in path.read_text().splitlines() if line.strip()]


# -- (2) 250ms tick + 2s-block proof -------------------------------------------


def test_control_tick_defaults(tmp_path):
    cfg = _paper_config(tmp_path)
    assert cfg.control_tick_s == 0.25
    assert cfg.feed_queue_max == 1000
    assert cfg.quote_max_age_s == 1.0


def test_stop_recognized_during_2s_producer_block(tmp_path):
    engine = _CtlEngine()
    session, store = _ctl_session(tmp_path, engine)
    try:
        session._stop_flag = "stop"  # operator instruction at t=0.

        def gen():
            time.sleep(2.0)  # producer blocked; ticks must not wait.
            yield None

        start = time.monotonic()
        report = session.run_live(gen(), duration_s=30)
        recognized_in = time.monotonic() - start
        assert recognized_in <= 1.0, f"stop took {recognized_in:.2f}s"
        assert "operator-stop:stop" in _risk_reasons(session)
        assert report["latency_ms"]["control_step"]["n"] >= 1
    finally:
        store.close()


def test_ticks_fire_during_feed_block(tmp_path):
    engine = _CtlEngine()
    session, store = _ctl_session(tmp_path, engine)
    try:
        def gen():
            time.sleep(0.6)
            yield None

        session.run_live(gen(), duration_s=30)
        assert len(engine.advance_calls) >= 2  # ticks at .25/.50.
        assert "feed-ended" in _risk_reasons(session)
    finally:
        store.close()


# -- (3) budget deadlines, supervisor, reconcile -------------------------------


def test_deadline_remaining_s(monkeypatch):
    from cryptobot.app.producer import deadline_remaining_s
    monkeypatch.delenv("CRYPTOBOT_DEADLINE_MONO", raising=False)
    assert deadline_remaining_s() is None
    assert deadline_remaining_s(default=5.0) == 5.0
    monkeypatch.setenv("CRYPTOBOT_DEADLINE_MONO",
                       str(time.monotonic() + 10.0))
    left = deadline_remaining_s()
    assert left is not None and 0.0 < left <= 10.0
    monkeypatch.setenv("CRYPTOBOT_DEADLINE_MONO", "not-a-number")
    assert deadline_remaining_s(default=5.0) == 5.0
    monkeypatch.setenv("CRYPTOBOT_DEADLINE_MONO",
                       str(time.monotonic() - 5.0))
    assert deadline_remaining_s() == 0.0  # never negative.


def test_rest_timeout_bounded_by_budget(tmp_path, monkeypatch):
    session, store = _ctl_session(tmp_path)
    try:
        monkeypatch.delenv("CRYPTOBOT_DEADLINE_MONO", raising=False)
        assert session._rest_timeout() == 15.0
        monkeypatch.setenv("CRYPTOBOT_DEADLINE_MONO",
                           str(time.monotonic() + 3.0))
        assert session._rest_timeout() <= 3.05
        monkeypatch.setenv("CRYPTOBOT_DEADLINE_MONO",
                           str(time.monotonic() + 0.05))
        assert session._rest_timeout() == 1.0  # usable floor.
    finally:
        store.close()


def test_urllib_transport_timeout_bounded(monkeypatch):
    from cryptobot.adapters.binance_live import UrllibTransport
    transport = UrllibTransport("https://fapi.binance.com", 10.0)
    monkeypatch.delenv("CRYPTOBOT_DEADLINE_MONO", raising=False)
    assert transport._effective_timeout() == 10.0
    monkeypatch.setenv("CRYPTOBOT_DEADLINE_MONO",
                       str(time.monotonic() + 2.0))
    assert transport._effective_timeout() <= 2.05
    monkeypatch.setenv("CRYPTOBOT_DEADLINE_MONO", "bogus")
    assert transport._effective_timeout() == 10.0


def test_control_tick_recognizes_operator_stop_without_feed(tmp_path):
    session, store = _ctl_session(tmp_path)
    try:
        assert session.control_tick() is None
        session._stop_flag = "stop"
        start = time.monotonic()
        reason = session.control_tick()
        assert reason == "operator-stop:stop"
        assert time.monotonic() - start < 1.0
    finally:
        store.close()


def test_entries_held_until_reconciled(tmp_path):
    engine = _CtlEngine()
    session, store = _ctl_session(tmp_path, engine)
    try:
        session._reconciled = False
        assert session._admission_hold() == "reconcile:restart-pending"
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        assert session._position is None
        assert engine.submits == []
        assert session._reject_counts.get("reconcile:restart-pending") == 1
        session._reconciled = True
        engine._unknown.append("cid-1")
        assert session._admission_hold() == "reconcile:unknown-outcomes"
    finally:
        store.close()


# -- (4) quote-age gate + burst latencies ---------------------------------------


def test_stale_quote_blocks_admit(tmp_path):
    engine = _CtlEngine()
    session, store = _ctl_session(tmp_path, engine)
    try:
        _seed_mark(session, age_s=2.0)
        assert session._quote_age_gate() == "gate:stale-quote"
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        assert session._position is None
        assert engine.submits == []
        assert session._reject_counts.get("gate:stale-quote") == 1
    finally:
        store.close()


def test_future_quote_blocked_as_clock_fault(tmp_path):
    session, store = _ctl_session(tmp_path)
    try:
        _seed_mark(session, age_s=-30.0)  # 30s in the future.
        assert session._quote_age_gate() == "gate:clock-future-quote"
    finally:
        store.close()


def test_unknown_quote_age_blocks_admit(tmp_path):
    session, store = _ctl_session(tmp_path)
    try:
        assert session._quote_age_gate() == "gate:quote-age-unknown"
    finally:
        store.close()


def test_fresh_quote_passes_gate(tmp_path):
    engine = _CtlEngine()
    session, store = _ctl_session(tmp_path, engine)
    try:
        _seed_mark(session)
        assert session._quote_age_gate() is None
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        gates = [r for r in session._reject_counts if r.startswith("gate:")]
        assert gates == []
    finally:
        store.close()


def test_missing_timestamps_fail_closed_loudly(tmp_path):
    session, store = _ctl_session(tmp_path)
    try:
        before = session._admitted
        session._ingest({"channel": "bookTicker", "symbol": "BTCUSDT",
                         "input_class": "observed-public",
                         "payload": {"bid": 99.0, "ask": 101.0}}, {}, {})
        assert session._admitted == before
        assert session._reject_counts.get("event-no-timestamp") == 1
    finally:
        store.close()


def test_burst_records_control_latencies(tmp_path):
    engine = _CtlEngine()
    session, store = _ctl_session(tmp_path, engine)
    try:
        base_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        def gen():
            for i in range(200):
                yield {"channel": "bookTicker", "symbol": "BTCUSDT",
                       "input_class": "observed-public",
                       "exchange_ts_ms": base_ms + i * 5,
                       "local_recv_ms": base_ms + i * 5 + 1,
                       "payload": {"bid": 99.99, "ask": 100.01}}

        report = session.run_live(gen(), duration_s=30)
        step = report["latency_ms"]["control_step"]
        assert step["n"] >= 200
        assert step["max_ms"] < 1000.0
        assert report["dropped_feed_events"] == 0
        assert "p50_ms" in step and "p99_ms" in step
    finally:
        store.close()


# -- (5) prod config, preflight, default-off ------------------------------------


def test_prod_config_guards(tmp_path):
    cfg = load_config("configs/prod.toml")
    assert cfg.mode == "prod"
    assert cfg.engine_kind == "live"
    assert cfg.engine_demo is False
    assert "fapi.binance.com" in (cfg.engine_base_url or "")
    assert cfg.allow_live_submission is False  # §9 default-off.
    assert cfg.api_key_ref is None
    assert cfg.risk.max_mark_age_ms == 1000
    assert cfg.control_tick_s == 0.25
    assert cfg.quote_max_age_s == 1.0


def test_config_rejects_inline_secrets(tmp_path):
    from cryptobot.app.config import ConfigError
    text = open("configs/prod.toml").read()
    text = text.replace("allow_live_submission = false",
                        "allow_live_submission = false\n"
                        'api_secret = "sk-live-abc"', 1)
    path = tmp_path / "bad.toml"
    path.write_text(text)
    try:
        load_config(path)
    except ConfigError as exc:
        assert "api_secret" in str(exc)
    else:
        raise AssertionError("inline api_secret accepted")


def test_config_rejects_prod_demo_and_testnet(tmp_path):
    import pytest
    from cryptobot.app.config import ConfigError
    base = open("configs/prod.toml").read()
    demo = base.replace("demo = false", "demo = true", 1)
    path = tmp_path / "demo.toml"
    path.write_text(demo)
    with pytest.raises(ConfigError, match="demo"):
        load_config(path)
    tn = base.replace("https://fapi.binance.com",
                      "https://testnet.binancefuture.com", 1)
    path = tmp_path / "tn.toml"
    path.write_text(tn)
    with pytest.raises(ConfigError, match="testnet"):
        load_config(path)


def _prod_session(tmp_path, name="prod-1"):
    cfg = load_config("configs/prod.toml")
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / name, name,
                      clock=WallClock(), engine=_CtlEngine())
    session.policy.reconcile_day(120.0, 0.0)
    session._init_run_files()
    return session, store


def test_prod_admission_hold_and_flatten_guard(tmp_path):
    import pytest
    session, store = _prod_session(tmp_path)
    try:
        assert session._admission_hold() == "config:prod-submission-disabled"
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        assert session._position is None
        assert (session._reject_counts.get("config:prod-submission-disabled")
                == 1)
        with pytest.raises(ValueError, match="prod-submission-disabled"):
            session._flatten("test")
    finally:
        store.close()


def _preflight(*args, env=None):
    import subprocess
    full_env = dict(os.environ)
    full_env.pop("CRYPTOBOT_API_KEY", None)
    full_env.pop("CRYPTOBOT_API_SECRET", None)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "tools/preflight.py", *args],
        capture_output=True, text=True, env=full_env, timeout=60)


def test_preflight_prod_observe_only_go():
    proc = _preflight("--config", "configs/prod.toml")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "GO" in proc.stdout


def test_preflight_submission_needs_confirm_and_keys(tmp_path):
    text = open("configs/prod.toml").read()
    text = text.replace("allow_live_submission = false",
                        "allow_live_submission = true", 1)
    path = tmp_path / "live.toml"
    path.write_text(text)
    proc = _preflight("--config", str(path))
    assert proc.returncode == 2  # no confirm, no keys.
    proc = _preflight("--config", str(path), "--confirm-live-submission")
    assert proc.returncode == 2  # confirmed but keys missing.
    proc = _preflight("--config", str(path), "--confirm-live-submission",
                      env={"CRYPTOBOT_API_KEY": "k",
                           "CRYPTOBOT_API_SECRET": "s"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "sk-live" not in proc.stdout  # values never echoed.


def test_preflight_rejects_inline_secret_and_reports_json(tmp_path):
    text = open("configs/prod.toml").read()
    text = text.replace("allow_live_submission = false",
                        "allow_live_submission = false\n"
                        'api_secret = "sk-live-abc"', 1)
    path = tmp_path / "bad.toml"
    path.write_text(text)
    proc = _preflight("--config", str(path), "--json")
    assert proc.returncode == 2
    report = json.loads(proc.stdout)
    assert report["ok"] is False
    assert "sk-live-abc" not in proc.stdout
    proc = _preflight("--config", "configs/prod.toml", "--json")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["submission"] == "disabled"
