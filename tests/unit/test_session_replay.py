"""Session replay + admit/flatten + CLI smoke tests (manager-owned, A-001)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.session import ReplayClock, Session
from cryptobot.app.store import RunStore
from cryptobot.coordination import (DataQuality, ForecastCost, Intent, Side,
                                    encode_exit_rule)
from cryptobot.coordination.exits import ExitPolicy
from cryptobot.coordination.selector import Candidate

CLASS = "synthetic-test"
T0 = 1_700_000_000_000


def _trade(seq, ts, agg_id, price, qty, maker=False):
    return {"v": 1, "format": "cryptobot-events/1", "input_class": CLASS,
            "source": "synthetic", "route": "test", "run_id": "sess",
            "seq": seq, "channel": "aggTrade", "symbol": "BTCUSDT",
            "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
            "local_mono_ns": seq, "gap_kind": None, "venue_seq": agg_id,
            "payload": {"agg_id": agg_id, "price": price, "qty": qty,
                        "first_id": agg_id, "last_id": agg_id,
                        "trade_ts_ms": ts, "buyer_is_maker": maker}}


def _bbo(seq, ts, bid, ask):
    return {"v": 1, "format": "cryptobot-events/1", "input_class": CLASS,
            "source": "synthetic", "route": "test", "run_id": "sess",
            "seq": seq, "channel": "bookTicker", "symbol": "BTCUSDT",
            "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
            "local_mono_ns": seq, "gap_kind": None, "venue_seq": 0,
            "payload": {"bid": bid, "ask": ask}}


def _capture(path: Path, windows: int = 10) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    events = []
    seq = 0
    for w in range(windows):
        base = T0 + w * 1000
        price = 100.0 + w * 0.01
        seq += 1
        events.append(_bbo(seq, base + 100, price - 0.01, price + 0.01))
        seq += 1
        events.append(_trade(seq, base + 200, w + 1, price, 1.0))
        seq += 1
        events.append(_trade(seq, base + 1200, 100 + w, price + 0.01, 0.5))
    (path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _config(tmp_path: Path, **over) -> Path:
    text = open("configs/paper.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    for key, value in over.items():
        text = text.replace(f"{key} =", f"{key} = {value} #", 1)
    path = tmp_path / "test.toml"
    path.write_text(text)
    return path


def _session(tmp_path: Path, **over) -> tuple[Session, RunStore]:
    cfg = load_config(_config(tmp_path, **over))
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    run_id = "sess-test"
    session = Session(cfg, store, tmp_path / "runs" / run_id, run_id)
    return session, store


def test_full_loop_no_trade_reports(tmp_path):
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        cap = _capture(tmp_path / "cap")
        report = session.run_replay(cap, expect_class=CLASS)
        assert report["events_seen"] > 0
        assert report["symbols"] == ["BTCUSDT"]
        assert report["intents_admitted"] == 0
        assert report["reject_counts"], "no-trade must explain why"
        assert report["execution_model"] == "reference-fake-venue"
        assert report["simulator_assumptions"]
        assert report["latency_ms"]["strategy_eval"]["n"] > 0
        assert (session.workdir / "report.json").exists()
        assert store.get_run("sess-test")["state"] == "stopped"
        assert session.ledger.paid_costs() == 0.0
    finally:
        store.close()


def test_crash_resume_continues(tmp_path):
    session, store = _session(tmp_path, warmup_bars=3)
    cap = _capture(tmp_path / "cap")
    try:
        try:
            session.run_replay(cap, expect_class=CLASS, crash_after=5)
        except RuntimeError:
            pass
        else:
            raise AssertionError("crash hook did not fire")
    finally:
        store.close()
    store2 = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        cfg = load_config(tmp_path / "test.toml")
        resumed = Session(cfg, store2, tmp_path / "runs" / "sess-test",
                          "sess-test")
        report = resumed.run_replay(cap, expect_class=CLASS, resume=True)
        assert report["events_seen"] > 0  # only post-cursor events reprocessed
        assert store2.get_run("sess-test")["state"] == "stopped"
    finally:
        store2.close()


def test_admit_protect_flatten_cycle(tmp_path):
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
        session.clock.set_ms(int(now.timestamp() * 1000))
        session.policy.reconcile_day(120.0, 0.0)
        session.store.create_run("sess-test", "replay", "fp",
                                 str(session.workdir), None)
        session.engine.note_mark("BTCUSDT", 100.2)
        intent = Intent(
            strategy="S1", version="0.1.0", instrument="BTCUSDT",
            side=Side.LONG, evidence_ts_utc=now,
            entry_low=100.0, entry_high=100.5,
            entry_expiry_utc=now + timedelta(seconds=60),
            invalidation_price=99.0,
            exit_rule=encode_exit_rule(ExitPolicy(
                stop_price=99.0, target_price=102.0,
                time_exit_utc=now + timedelta(seconds=600),
                policy_id="test")),
            holding_limit_s=600,
            forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
            evidence_ref="test:1", data_quality=DataQuality.CLEAN)
        session._maybe_admit([Candidate("S1", intent)])
        assert session._position is not None
        # Advance past the modeled submit delay, then drain to fills.
        session.clock.set_ms(int(now.timestamp() * 1000) + 5000)
        session._drain_engine()
        assert session.ledger.has_position()
        assert session._position["protected"] is True
        assert len(session._position["legs"]) == 2
        session._flatten("test")
        session._drain_engine()
        # Settle loop: flatten fill + leg cancels propagate through polls.
        for _ in range(5):
            session._drain_engine()
            session._update_position(
                __import__("cryptobot.app.engine",
                           fromlist=["EngineEvent"]).EngineEvent(
                    "mark", None, session.now_utc()))
        assert not session.ledger.has_position()
        assert session._position is None
        assert session.ledger.paid_costs() > 0.0, "modeled fees must book"
        fills = [r for r in store._db.execute(
            "SELECT payload FROM execution_events WHERE run_id='sess-test'"
            " AND kind='fill'").fetchall()]
        assert len(fills) == 2
        assert all(json.loads(r[0])["fee"] > 0 for r in fills)
        assert all(json.loads(r[0])["liquidity"] == "taker" for r in fills)
    finally:
        store.close()


def test_short_uses_venue_sell_side(tmp_path):
    # Regression: session must submit venue SELL (never "SHORT") for shorts.
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
        session.clock.set_ms(int(now.timestamp() * 1000))
        session.policy.reconcile_day(120.0, 0.0)
        session.store.create_run("sess-test", "replay", "fp",
                                 str(session.workdir), None)
        session.engine.note_mark("BTCUSDT", 100.2)
        intent = Intent(
            strategy="S1", version="0.1.0", instrument="BTCUSDT",
            side=Side.SHORT, evidence_ts_utc=now,
            entry_low=99.5, entry_high=100.0,
            entry_expiry_utc=now + timedelta(seconds=60),
            invalidation_price=101.0,
            exit_rule=encode_exit_rule(ExitPolicy(
                stop_price=101.0, target_price=98.0,
                time_exit_utc=now + timedelta(seconds=600),
                policy_id="test")),
            holding_limit_s=600,
            forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
            evidence_ref="test:short", data_quality=DataQuality.CLEAN)
        session._maybe_admit([Candidate("S1", intent)])
        assert session._position is not None
        session.clock.set_ms(int(now.timestamp() * 1000) + 5000)
        session._drain_engine()
        assert session.ledger.position_qty() < 0
        fills = [json.loads(r[0]) for r in store._db.execute(
            "SELECT payload FROM execution_events WHERE run_id='sess-test'"
            " AND kind='fill'").fetchall()]
        assert fills and all(f["side"] in ("BUY", "SELL") for f in fills)
        assert fills[0]["side"] == "SELL"
    finally:
        store.close()


def test_run_live_with_stub_engine(tmp_path):
    from cryptobot.app.session import Session, WallClock
    text = open("configs/paper.toml").read()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    text = text.replace("warmup_bars =", "warmup_bars = 3 #", 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    cfg = load_config(cfg_path)

    class StubEngine:
        model_label = "stub-test"
        assumptions = ("stub: no fills",)

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

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    base = (now_ms // 1000) * 1000 - 9000
    events = []
    for w in range(10):
        ts = base + w * 1000
        events.append({"channel": "bookTicker", "symbol": "BTCUSDT",
                       "input_class": "observed-public",
                       "exchange_ts_ms": ts + 100, "local_recv_ms": ts + 105,
                       "payload": {"bid": 99.99, "ask": 100.01}})
        events.append({"channel": "aggTrade", "symbol": "BTCUSDT",
                       "input_class": "observed-public",
                       "exchange_ts_ms": ts + 200, "local_recv_ms": ts + 205,
                       "payload": {"agg_id": w + 1, "price": 100.0, "qty": 1.0,
                                   "buyer_is_maker": False}})
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        session = Session(cfg, store, tmp_path / "runs" / "live-1", "live-1",
                          clock=WallClock(), engine=StubEngine())
        # Pre-arm filters with a stub transport (no network in tests).
        from dataclasses import replace

        from cryptobot.app.filters import build_run_filters
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
        report = session.run_live(iter(events), duration_s=30)
        assert report["mode"] == "paper"
        assert report["intents_admitted"] == 0
        assert report["events_seen"] == 20
        assert store.get_run("live-1")["state"] == "stopped"
    finally:
        store.close()


def test_paper_session_requires_injected_engine(tmp_path):
    import pytest
    text = open("configs/paper.toml").read()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        with pytest.raises(ValueError, match="injected Nautilus"):
            Session(load_config(cfg_path), store, tmp_path / "runs" / "x",
                    "x")
    finally:
        store.close()


def test_cli_doctor_run_status_stop(tmp_path):
    from cryptobot.cli import main
    cap = _capture(tmp_path / "cap", windows=6)
    cfg_path = _config(tmp_path, warmup_bars=3)
    assert main(["doctor", "--config", str(cfg_path),
                 "--capture", str(cap)]) == 0
    assert main(["run", "--mode", "replay", "--config", str(cfg_path),
                 "--capture", str(cap), "--run-id", "cli-1",
                 "--expect-class", CLASS]) == 0
    storage = str(tmp_path / "runs")
    assert main(["status", "--run-id", "cli-1", "--storage", storage]) == 0
    assert main(["stop", "--run-id", "cli-1", "--storage", storage]) == 0
    assert main(["status", "--run-id", "missing",
                 "--storage", storage]) == 1
