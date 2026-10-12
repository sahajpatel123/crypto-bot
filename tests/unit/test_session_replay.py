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


def test_run_files_match_b9_schemas(tmp_path):
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        cap = _capture(tmp_path / "cap")
        session.run_replay(cap, expect_class=CLASS)
        fills = [json.loads(line) for line in
                 (session.workdir / "fills.jsonl").open()
                 if line.strip()] if (session.workdir / "fills.jsonl").exists() else []
        assert fills == []  # no-trade loop books nothing
        rej = [json.loads(line) for line in
               (session.workdir / "rejections.jsonl").read_text().splitlines()]
        assert rej, "no-trade must persist rejection rows"
        assert set(rej[0]) == {"ts_utc", "stage", "reason", "strategy",
                               "instrument", "side"}
        eq = [json.loads(line) for line in
              (session.workdir / "equity.jsonl").read_text().splitlines()]
        assert eq and set(eq[0]) == {"ts_utc", "marked_equity", "cash",
                                     "position_qty", "position_symbol",
                                     "open_pnl", "source",
                                     "mark_source", "mark_age_ms"}
        risk = [json.loads(line) for line in
                (session.workdir / "risk.jsonl").read_text().splitlines()]
        assert risk and set(risk[0]) == {"ts_utc", "wall_ts_utc", "kind",
                                         "from_state", "to_state", "reason"}
    finally:
        store.close()


def test_fill_rows_match_b9_schema(tmp_path):
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
        session.clock.set_ms(int(now.timestamp() * 1000) + 5000)
        session._drain_engine()
        fills = [json.loads(line) for line in
                 (session.workdir / "fills.jsonl").read_text().splitlines()]
        assert len(fills) == 1
        assert set(fills[0]) == {"execution_id", "client_order_id",
                                  "instrument", "side", "qty", "price", "fee",
                                  "liquidity", "ts_utc"}
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


class _ScriptedEngine:
    """Fault-injecting PaperEngine stub for protection tests."""

    model_label = "script-stub"
    assumptions = ("stub",)

    def __init__(self):
        self.attach_script: list = []
        self.leg_states: dict = {}
        self.leg_qty: dict = {}
        self.leg_filled: dict = {}
        self.submitted_immediate: list = []
        self.cancelled: list = []
        self.attaches = 0

    def submit(self, cmd):
        raise AssertionError("not used")
    def submit_immediate(self, cmd):
        self.submitted_immediate.append(cmd)
        return "imm-1"
    def submit_protected(self, cmd, limit):
        raise AssertionError("not used")
    def resolve(self, cid):
        return cid
    def cancel(self, cid, reason):
        self.cancelled.append(cid)
    def poll(self):
        return []
    def attach_protection(self, entry_id, stop, target):
        self.attaches += 1
        action = self.attach_script.pop(0) if self.attach_script else ["s1"]
        if action == "raise":
            raise ValueError("venue refused legs")
        return action
    def open_orders(self):
        from cryptobot.app.engine import EngineOrderStatus
        return [EngineOrderStatus(cid, "BTCUSDT", st,
                                  self.leg_qty.get(cid, 1.0),
                                  self.leg_filled.get(cid, 0.0))
                for cid, st in self.leg_states.items()]
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


def _protection_session(tmp_path):
    cfg = load_config(_config(tmp_path, warmup_bars=3))
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    engine = _ScriptedEngine()
    session = Session(cfg, store, tmp_path / "runs" / "prot", "prot",
                      engine=engine)
    store.create_run("prot", "replay", "fp", str(session.workdir), None)
    session.ledger.record_fill(
        "BUY", 1.0, 100.0, 0.05,
        datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc), "e1")
    session._position = {"reservation_id": "r-1", "instrument": "BTCUSDT",
                         "side": "LONG", "entry_pre_id": "p", "entry_id": "e",
                         "legs": [], "stop": 99.0, "target": 102.0,
                         "time_exit": datetime(2026, 10, 12, 7, 0,
                                               tzinfo=timezone.utc),
                         "legacy_exit": False, "protected": False,
                         "protect_attempts": 0}
    return session, store, engine


def _checkpoints(store, run_id="prot"):
    return [r[0] for r in store._db.execute(
        "SELECT kind FROM checkpoints WHERE run_id=? ORDER BY id", (run_id,))]


def test_protection_verified_only_on_live_covering_stop(tmp_path):
    session, store, engine = _protection_session(tmp_path)
    try:
        engine.attach_script = [["stop-1", "tgt-1"]]
        engine.leg_states = {"stop-1": "open", "tgt-1": "open"}
        session._ensure_protection(session._position)
        assert session._position["protected"] is True
        assert "protection-verified" in _checkpoints(store)
    finally:
        store.close()


def test_protection_failure_never_marks_protected(tmp_path):
    session, store, engine = _protection_session(tmp_path)
    try:
        engine.attach_script = ["raise", "raise", "raise"]
        for _ in range(3):
            session._ensure_protection(session._position)
            assert session._position["protected"] is False
        assert session._position["legs"] == []
        # Fourth call crosses the bound -> emergency close attempted.
        session._ensure_protection(session._position)
        assert session._position["protected"] is False
        assert len(engine.submitted_immediate) == 1
        assert engine.submitted_immediate[0].reduce_only is True
        kinds = _checkpoints(store)
        assert "protection-emergency" in kinds
        # Exposure retained: entries stay blocked via _position being set.
        assert session._position is not None
    finally:
        store.close()


def test_protection_dead_leg_retries(tmp_path):
    session, store, engine = _protection_session(tmp_path)
    try:
        engine.attach_script = [["stop-1"], ["stop-2"]]
        engine.leg_states = {"stop-1": "rejected"}
        session._ensure_protection(session._position)
        assert session._position["protected"] is False
        assert session._position["legs"] == []  # cleared for retry
        assert "protection-unverified" in _checkpoints(store)
        engine.leg_states = {"stop-2": "open"}
        session._ensure_protection(session._position)
        assert session._position["protected"] is True
    finally:
        store.close()


def _paper_cfg(tmp_path, name="paper"):
    text = open("configs/paper.toml").read()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    text = text.replace("warmup_bars =", "warmup_bars = 3 #", 1)
    cfg_path = tmp_path / f"{name}.toml"
    cfg_path.write_text(text)
    return load_config(cfg_path)


def _stopping_reason(store, run_id):
    row = store._db.execute(
        "SELECT reason FROM risk_transitions WHERE run_id=? AND"
        " to_state='stopping' ORDER BY id DESC LIMIT 1",
        (run_id,)).fetchone()
    return row[0] if row else None


def test_live_deadline_fires_on_silent_heartbeats(tmp_path):
    """B3: duration deadline ends the run during pure silence (no arrivals)."""
    import time
    from cryptobot.app.session import Session, WallClock
    cfg = _paper_cfg(tmp_path, "paper-b3a")
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        session = Session(cfg, store, tmp_path / "runs" / "silent",
                          "silent", clock=WallClock(),
                          engine=_ScriptedEngine())
        def beats():
            while True:
                time.sleep(0.01)
                yield None
        t0 = time.monotonic()
        report = session.run_live(beats(), duration_s=1)
        elapsed = time.monotonic() - t0
        assert report["events_seen"] == 0
        assert store.get_run("silent")["state"] == "stopped"
        assert _stopping_reason(store, "silent") == "duration-elapsed"
        assert 0.9 <= elapsed < 5.0  # waited for deadline, not first None
    finally:
        store.close()


def test_live_stop_flag_breaks_silence(tmp_path):
    """B3: an operator stop ends the run promptly with no market traffic."""
    from cryptobot.app.session import Session, WallClock
    cfg = _paper_cfg(tmp_path, "paper-b3b")
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        session = Session(cfg, store, tmp_path / "runs" / "stopq",
                          "stopq", clock=WallClock(),
                          engine=_ScriptedEngine())
        session._stop_flag = "now"
        report = session.run_live(iter([None, None, None]), duration_s=30)
        assert report["events_seen"] == 0
        assert store.get_run("stopq")["state"] == "stopped"
        assert _stopping_reason(store, "stopq") == "operator-stop:now"
    finally:
        store.close()


def test_live_time_exit_fires_on_silent_heartbeat(tmp_path):
    """B3: an expiring holding deadline flattens with zero arrivals."""
    from cryptobot.app.session import Session, WallClock
    cfg = _paper_cfg(tmp_path, "paper-b3c")
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        engine = _ScriptedEngine()
        session = Session(cfg, store, tmp_path / "runs" / "t3", "t3",
                          clock=WallClock(), engine=engine)
        session.ledger.record_fill(
            "BUY", 1.0, 100.0, 0.05,
            datetime.now(timezone.utc), "e1")
        session._position = {
            "reservation_id": "r-1", "instrument": "BTCUSDT",
            "side": "LONG", "entry_pre_id": "p", "entry_id": "e",
            "legs": [], "stop": 99.0, "target": 102.0,
            "time_exit": datetime.now(timezone.utc) - timedelta(seconds=1),
            "legacy_exit": False, "protected": False,
            "protect_attempts": 0}
        report = session.run_live(iter([None, None, None]), duration_s=30)
        assert report["events_seen"] == 0
        assert engine.submitted_immediate, \
            "time exit must fire without arrivals"
        assert engine.submitted_immediate[0].reduce_only is True
        assert "flatten" in _checkpoints(store, "t3")
        assert store.get_run("t3")["state"] == "stopped"
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


def test_protection_stop_must_cover_risk_approved_qty(tmp_path):
    """B8 ack loop: a stop covering the net but not the approved qty fails."""
    from cryptobot.risk.state import Reservation
    session, store, engine = _protection_session(tmp_path)
    try:
        session.policy._state.reservations["r-1"] = Reservation(
            reservation_id="r-1", intent_ref="i", instrument="BTCUSDT",
            side="LONG", notional=200.0, reserved_risk=1.0,
            created_utc="2026-10-12T06:00:00+00:00",
            expires_utc="2026-10-12T07:00:00+00:00", qty=2.0)
        engine.attach_script = [["stop-1"], ["stop-2"]]
        engine.leg_states = {"stop-1": "open"}
        engine.leg_qty = {"stop-1": 1.0}  # covers net 1.0, not approved 2.0
        session._ensure_protection(session._position)
        assert session._position["protected"] is False
        assert session._position["legs"] == []
        assert "protection-unverified" in _checkpoints(store)
        engine.leg_states = {"stop-2": "open"}
        engine.leg_qty = {"stop-2": 2.0}
        session._ensure_protection(session._position)
        assert session._position["protected"] is True
    finally:
        store.close()


def test_replay_run_feeds_reporting_package(tmp_path):
    """B6: a replay workdir loads strictly and reconciles via reporting/."""
    import json as _json
    from cryptobot.cli import main
    from cryptobot.reporting import build_report
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        cap = _capture(tmp_path / "cap")
        session.run_replay(cap, expect_class=CLASS)
        assert (session.workdir / "config.toml").exists()
        assert (session.workdir / "dataset_manifest.json").exists()
        out = tmp_path / "analysis"
        artifacts = build_report(session.workdir, out)
        assert sorted(artifacts) == [
            "daily_returns.csv", "equity.csv", "rejections.csv",
            "report.html", "summary.json", "trades.csv"]
        summary = _json.loads((out / "summary.json").read_text())
        assert summary["reconciliation"]["status"] == "agree"
        cli_out = tmp_path / "cli-analysis"
        assert main(["report", "--run-dir", str(session.workdir),
                     "--out", str(cli_out)]) == 0
        assert (cli_out / "report.html").exists()
    finally:
        store.close()


def _intent(now, ref="test:1"):
    return Intent(
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
        evidence_ref=ref, data_quality=DataQuality.CLEAN)


def _gate_at(now, offset_s=0):
    """EventGate with one release `offset_s` from now; no coverage needed."""
    from cryptobot.events.gate import EventGate, GateConfig
    from cryptobot.events.store import EventStore
    from cryptobot.events.timezones import et_tz
    from cryptobot.events.types import Event
    sched = now + timedelta(seconds=offset_s)
    wall = sched.astimezone(et_tz()).replace(tzinfo=None).isoformat()
    store = EventStore()
    store.upsert(Event(
        event_id="T-1", source="cpi", title="t", kind="release",
        source_url="https://example.invalid/", scheduled_local_iso=wall,
        tz_name="America/New_York", scheduled_utc=sched,
        first_seen_utc=now - timedelta(days=1), fetch_utc=now,
        revision=0, horizon_end_utc=None,
        expires_utc=sched + timedelta(days=7)))
    return EventGate(store, GateConfig(required_sources=()))


def _reservation(rid="r-1", qty=1.0):
    from cryptobot.risk.state import Reservation
    return Reservation(
        reservation_id=rid, intent_ref="i", instrument="BTCUSDT",
        side="LONG", notional=100.0, reserved_risk=1.0,
        created_utc="2026-10-12T06:00:00+00:00",
        expires_utc="2026-10-12T07:00:00+00:00", qty=qty)


def test_flat_inference_releases_risk_hold(tmp_path):
    """Q-007: flat inference frees the reservation for the next approval."""
    from cryptobot.app.engine import EngineEvent
    session, store, engine = _protection_session(tmp_path)
    try:
        session.ledger.record_fill(
            "SELL", 1.0, 101.0, 0.05,
            datetime.now(timezone.utc), "e2")
        assert not session.ledger.has_position()
        session.policy._state.reservations["r-1"] = _reservation()
        session.policy._state.open_position = True
        engine.leg_states = {"e": "filled"}
        engine.leg_filled = {"e": 1.0}
        session._update_position(
            EngineEvent("tick", None, datetime.now(timezone.utc)))
        assert session._position is None
        assert store.get_run("prot")["state"] == "ready"
        assert session.policy._state.reservations == {}
        assert session.policy._state.open_position is False
        assert session.policy._state.unresolved == {}
    finally:
        store.close()


def test_flat_inference_lifts_zero_net_unresolved(tmp_path):
    """Q-007 trap: expired-then-flat reservation must not block forever."""
    from cryptobot.app.engine import EngineEvent
    session, store, engine = _protection_session(tmp_path)
    try:
        session.ledger.record_fill(
            "SELL", 1.0, 101.0, 0.05,
            datetime.now(timezone.utc), "e2")
        session.policy._state.reservations["r-1"] = _reservation()
        session.policy._move_to_unresolved(
            "r-1", datetime.now(timezone.utc))
        assert session.policy.unresolved_ids() == ("r-1",)
        engine.leg_states = {"e": "filled"}
        engine.leg_filled = {"e": 1.0}
        session._update_position(
            EngineEvent("tick", None, datetime.now(timezone.utc)))
        assert session._position is None
        assert session.policy.unresolved_ids() == ()
    finally:
        store.close()


def test_entry_dead_releases_reservation(tmp_path):
    """Q-007: a dead entry frees its reservation (zero booked)."""
    from cryptobot.app.engine import EngineEvent
    session, store, engine = _protection_session(tmp_path)
    try:
        session.policy._state.reservations["r-1"] = _reservation()
        engine.leg_states = {"e": "rejected"}
        session._update_position(
            EngineEvent("tick", None, datetime.now(timezone.utc)))
        assert session._position is None
        assert session.policy._state.reservations == {}
    finally:
        store.close()


def test_event_gate_blocks_admit(tmp_path):
    """EV-001 seam: a blocked gate rejects before risk evaluation."""
    session, store = _session(tmp_path, warmup_bars=3)
    from cryptobot.app.session import Session
    store.close()
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(session.config, store, tmp_path / "runs" / "ev",
                      "ev", engine=_ScriptedEngine())
    try:
        now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
        session.clock.set_ms(int(now.timestamp() * 1000))
        session.policy.reconcile_day(120.0, 0.0)
        session.event_gate = _gate_at(session.now_utc(), offset_s=0)
        session._maybe_admit([Candidate("S1", _intent(now))])
        assert session._position is None
        assert session.policy._state.reservations == {}
        assert any(r.startswith("event:") for r in session._reject_counts), \
            dict(session._reject_counts)
    finally:
        store.close()


def test_event_gate_clear_passes_through(tmp_path):
    """EV-001 seam: a clear gate lets admission reach risk/submit."""
    session, store = _session(tmp_path, warmup_bars=3)
    from cryptobot.app.session import Session
    store.close()
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(session.config, store, tmp_path / "runs" / "ev2",
                      "ev2", engine=_RejectingEngine())
    try:
        now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
        session.clock.set_ms(int(now.timestamp() * 1000))
        session.policy.reconcile_day(120.0, 0.0)
        session.event_gate = _gate_at(
            session.now_utc(), offset_s=10_000)
        session._maybe_admit([Candidate("S1", _intent(now))])
        # Reached risk + submit (rejected there, proving gate passed).
        assert ("execution:submit-rejected:ValueError"
                in session._reject_counts)
    finally:
        store.close()


def test_event_prepare_flat_cancels_unfilled(tmp_path):
    """EV-001 sweep: unfilled entries cancel ahead of the window."""
    session, store, engine = _protection_session(tmp_path)
    try:
        session.event_gate = _gate_at(session.now_utc(), offset_s=960)
        session.policy._state.reservations["r-1"] = _reservation()
        engine.leg_states = {"e": "open"}
        session._event_prepare_flat()
        assert session._position is None
        assert "e" in engine.cancelled
        assert session.policy._state.reservations == {}
        assert "event-prepare-flat" in _checkpoints(store)
    finally:
        store.close()


def test_event_prepare_flat_keeps_filled(tmp_path):
    """EV-001 sweep: filled positions keep protection, no cancel."""
    session, store, engine = _protection_session(tmp_path)
    try:
        session.event_gate = _gate_at(session.now_utc(), offset_s=960)
        engine.leg_states = {"e": "filled"}
        engine.leg_filled = {"e": 1.0}
        session._event_prepare_flat()
        assert session._position is not None
        assert engine.cancelled == []
    finally:
        store.close()


def test_events_enabled_builds_gate(tmp_path):
    """run.events_enabled=True builds a gate from required fixtures."""
    import dataclasses
    from cryptobot.app.session import Session
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        cfg = dataclasses.replace(session.config, events_enabled=True)
        gated = Session(cfg, store, tmp_path / "runs" / "ev3",
                        "ev3", engine=_ScriptedEngine())
        assert gated.event_gate is not None
        assert session.event_gate is None
    finally:
        store.close()


def _margin_session(tmp_path, run_id="marg"):
    from cryptobot.app.session import Session
    cfg = load_config(_config(tmp_path))
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    engine = _MarginEngine()
    session = Session(cfg, store, tmp_path / "runs" / run_id, run_id,
                      engine=engine)
    return session, store, engine


def test_snapshot_carries_margin_inputs(tmp_path):
    """V-008 NEEDS: available/fee-buffer/inflight reach the snapshot."""
    session, store, engine = _margin_session(tmp_path)
    try:
        engine.margin = (8000.0, 8000.0)
        snap = session._snapshot_account()
        assert snap.available_margin_usdt == 8000.0
        assert snap.fee_buffer_usdt == 2 * 8000.0 * 5.0 / 1e4
        assert snap.inflight_exposure_usdt == 0.0
        engine.margin = None
        assert session._snapshot_account().available_margin_usdt is None
    finally:
        store.close()


def test_one_budget_pending_ledger_booked(tmp_path):
    """V-008 NEEDS: one budget = pending + |ledger| + booked excess."""
    session, store, engine = _margin_session(tmp_path)
    try:
        now = datetime.now(timezone.utc)
        session.ledger.record_fill(
            "BUY", 1.0, 100.0, 0.05, now, "e1")
        class _Ord:
            role = "entry"
            state = "open"
            qty = 2.0
            filled_qty = 0.0
        engine.open_orders = lambda: [_Ord()]
        session.policy.note_fill_delta(
            "r-x", "x1", "BTCUSDT", "BUY", 1.5, 100.0, 0.05,
            now.isoformat())
        # pending 2.0 + ledger 1.0 + booked-excess (1.5 + 1.0 - 1.0)
        assert session._inflight_exposure_usdt(100.0) == (
            200.0 + 100.0 + 150.0)
        assert session._inflight_exposure_usdt(0.0) == 0.0
    finally:
        store.close()


def test_mark_preference_exchange_feed_none(tmp_path):
    """V-008 NEEDS: exchange > feed > 0.0 with provenance."""
    session, store, engine = _margin_session(tmp_path)
    try:
        session.policy.reconcile_day(120.0, 0.0)
        session.store.create_run("marg", "replay", "fp",
                                 str(session.workdir), None)
        assert session._reference_mark_full() == (0.0, "none", None)
        base = T0 + 120_000
        session._ingest(_trade(1, base, 1, 100.0, 0.5), {}, {})
        mark, source, ts = session._reference_mark_full()
        assert (mark, source) == (100.0, "feed") and ts is not None
        now = session.now_utc()
        engine.marks["BTCUSDT"] = 101.5
        engine.mark_ts["BTCUSDT"] = now
        session._ingest(
            {"channel": "markPrice", "symbol": "BTCUSDT",
             "exchange_ts_ms": base + 500,
             "payload": {"mark": 101.5}}, {}, {})
        mark, source, ts = session._reference_mark_full()
        assert (mark, source, ts) == (101.5, "exchange", now)
    finally:
        store.close()


def test_equity_row_carries_mark_provenance(tmp_path):
    """V-008 NEEDS: equity rows record mark_source + mark_age_ms."""
    session, store, engine = _margin_session(tmp_path, "marg2")
    try:
        session.policy.reconcile_day(120.0, 0.0)
        session.store.create_run("marg2", "replay", "fp",
                                 str(session.workdir), None)
        base = T0 + 180_000
        session._ingest(_trade(1, base, 1, 100.0, 0.5), {}, {})
        session._sample_equity("test", force=True)
        line = (session.workdir / "equity.jsonl").read_text().strip()
        row = json.loads(line)
        assert row["mark_source"] == "feed"
        assert row["mark_age_ms"] >= 0.0
    finally:
        store.close()


def test_funding_reconcile_agree_and_mismatch(tmp_path):
    """V-008 NEEDS: agree checkpoints; mismatch halts exit-only loudly."""
    session, store, engine = _margin_session(tmp_path, "marg3")
    try:
        session.store.create_run("marg3", "replay", "fp",
                                 str(session.workdir), None)
        session._reconcile_funding()
        assert "funding-reconciled" in _checkpoints(store, "marg3")
        engine.settled = 999.0
        session._reconcile_funding()
        assert "funding-mismatch" in _checkpoints(store, "marg3")
        assert store.get_run("marg3")["state"] == "halted"
    finally:
        store.close()


class _RejectingEngine(_ScriptedEngine):
    """Submit raises like the venue would on dust (F3)."""

    def submit(self, cmd):
        raise ValueError("qty 0.00099865 below LOT_SIZE step 0.001")


class _MarginEngine(_ScriptedEngine):
    """V-008 surface: margin account, exchange marks, settled totals."""

    def __init__(self):
        super().__init__()
        self.margin = None
        self.marks = {}
        self.mark_ts = {}
        self.settled = 0.0
        self.noted_events = []

    def account_margin(self):
        return self.margin

    def valuation_mark(self, instrument):
        return self.marks.get(instrument)

    def valuation_mark_ts(self, instrument):
        return self.mark_ts.get(instrument)

    def settled_funding_total(self, symbol=None):
        return self.settled

    def note_event(self, event):
        self.noted_events.append(event)


def test_submit_rejection_releases_and_continues(tmp_path):
    """F3: an unsubmittable opportunity rejects + frees the hold, no crash."""
    session, store = _session(tmp_path, warmup_bars=3)
    from cryptobot.app.session import Session
    store.close()
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(session.config, store, tmp_path / "runs" / "rej",
                      "rej", engine=_RejectingEngine())
    try:
        now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
        session.clock.set_ms(int(now.timestamp() * 1000))
        session.policy.reconcile_day(120.0, 0.0)
        session._maybe_admit([Candidate("S1", _intent(now))])
        assert session._position is None
        assert session.policy._state.reservations == {}
        assert ("execution:submit-rejected:ValueError"
                in session._reject_counts)
    finally:
        store.close()


def test_replay_filters_arm_step_sizing(tmp_path):
    """F3: armed replay filters size on the venue step, never dust."""
    from cryptobot.risk.types import Approved
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
        session.clock.set_ms(int(now.timestamp() * 1000))
        session.policy.reconcile_day(120.0, 0.0)
        session.store.create_run("sess-test", "replay", "fp",
                                 str(session.workdir), None)
        session.arm_replay_filters(
            {"BTCUSDT": {"tick_size": 0.01, "step_size": 0.001,
                         "min_qty": 0.001, "min_notional": 5.0}},
            "manifest-frozen", asof_utc=now)
        verdict = session.policy.evaluate(
            _intent(now), session._snapshot_account())
        assert isinstance(verdict, Approved)
        assert verdict.qty >= 0.001
        assert abs(verdict.qty / 0.001 - round(verdict.qty / 0.001)) < 1e-9
        rows = store._db.execute(
            "SELECT payload FROM checkpoints WHERE run_id='sess-test'"
            " AND kind='filters-armed'").fetchall()
        assert rows and "manifest-frozen" in rows[0][0]
    finally:
        store.close()


def test_funding_event_routes_to_ledger(tmp_path):
    """Funding EngineEvents book to the ledger (idempotent redelivery)."""
    from cryptobot.app.engine import EngineEvent, EngineFunding
    session, store, engine = _protection_session(tmp_path)
    try:
        session._position["time_exit"] = (
            datetime.now(timezone.utc) + timedelta(hours=1))
        now = datetime.now(timezone.utc)
        evt = EngineEvent(
            "funding", EngineFunding(
                event_id="funding:BTCUSDT:123", instrument="BTCUSDT",
                amount=-1.5, ts_utc=now), now)
        session._on_engine_event(evt)
        assert session.ledger.funding_net() == -1.5
        session._on_engine_event(evt)
        assert session.ledger.funding_net() == -1.5
    finally:
        store.close()


def test_map_b4_views_contract(tmp_path):
    """S5 card B4: stale/absent map to None + verbatim reasons."""
    from cryptobot.app.session import _map_b4_views
    from cryptobot.market_data.views import BookView, FlowView2
    book = BookView(
        symbol="BTCUSDT", ts_ms=1000, bids=((100.0, 1.0),),
        asks=((100.1, 1.0),), levels=10, sync_age_ms=99999,
        last_update_id=5, quality="stale", spread_bps=10.0,
        imbalance_top1=0.1)
    depth, flow_v, reasons = _map_b4_views(book, None, "flow:no-trades-yet")
    assert depth is None and flow_v is None
    assert reasons == ["book:stale-book", "flow:no-trades-yet"]
    clean = BookView(
        symbol="BTCUSDT", ts_ms=2000, bids=((100.0, 2.0),),
        asks=((100.1, 1.0),), levels=10, sync_age_ms=100,
        last_update_id=6, quality="clean", spread_bps=10.0,
        imbalance_top1=1 / 3)
    flow = FlowView2(
        symbol="BTCUSDT", window_start_ms=1000, window_end_ms=2000,
        buy_notional=60.0, sell_notional=40.0, buy_count=6, sell_count=4,
        total_qty=1.0, vwap=100.0, last_id=9, completeness="complete")
    depth, flow_v, reasons = _map_b4_views(clean, flow, "")
    assert depth is not None and depth.imbalance == 1 / 3
    assert flow_v is not None and flow_v.trade_count == 10
    assert reasons == []


def test_b4_wiring_flow_present_depth_precise(tmp_path):
    """Session ingests trades into views: flow present, depth precise."""
    from cryptobot.strategies.runtime import get_adapter
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
        session.policy.reconcile_day(120.0, 0.0)
        session.store.create_run("sess-test", "replay", "fp",
                                 str(session.workdir), None)
        adapters = {"S5": get_adapter("S5")}
        base = T0 + 60_000  # own windows, clear of other tests' data
        seq = 0
        tid = 0
        for w in range(6):
            ts = base + w * 1000
            for k in range(4):
                tid += 1
                seq += 1
                session._ingest(_trade(seq, ts + 100 + k * 100, tid,
                                       100.0, 0.5),
                                adapters, {})
            seq += 1
            session._ingest(_bbo(seq, ts + 500, 99.99, 100.01),
                            adapters, {})
        assert any(r.startswith("strategy:book:never-synced")
                   for r in session._reject_counts), \
            dict(session._reject_counts)
        assert not [r for r in session._reject_counts
                    if ":flow:" in r or r.endswith(":flow")], \
            "flow views present: no flow:* rejects expected"
        from cryptobot.market_data.views import book_flow_for
        book, flow, _reason = book_flow_for(
            "BTCUSDT", base + 6000, session._depth_store)
        assert book is None and flow is not None
    finally:
        store.close()


def _snap(symbol="BTCUSDT", last_id=100):
    return {"symbol": symbol, "bids": [["99.5", "1.0"]],
            "asks": [["100.5", "1.0"]], "last_update_id": last_id,
            "rest_recv_ms": T0, "rest_mono_ns": 1, "limit": 1000,
            "outcome": "synced"}


def test_replay_primes_depth_books(tmp_path):
    """Manager: replay installs depth_snapshots.jsonl before events."""
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        cap = _capture(tmp_path / "cap")
        (cap / "depth_snapshots.jsonl").write_text(
            json.dumps(_snap()) + "\n")
        report = session.run_replay(cap, expect_class=CLASS)
        assert report["events_seen"] > 0
        from cryptobot.market_data.views import book_flow_for
        book, _, _ = book_flow_for(
            "BTCUSDT", T0 + 60_000, session._depth_store)
        assert book is not None, "primed book must sync"
        start = json.loads(store._db.execute(
            "SELECT payload FROM checkpoints WHERE run_id=? AND kind=?",
            ("sess-test", "depth-prime")).fetchone()[0])
        assert start["present"] is True and start["total"] == 1
        assert start["applied"] == 0  # nothing installed upfront (P1).
        final = json.loads(store._db.execute(
            "SELECT payload FROM checkpoints WHERE run_id=? AND kind=?",
            ("sess-test", "depth-prime-final")).fetchone()[0])
        assert final["applied"] == 1 and final["unreached"] == 0
        assert final["synced"] == ["BTCUSDT"]
    finally:
        store.close()


def test_replay_missing_snapshots_recorded_absent(tmp_path):
    """Manager: pre-E-007 captures record the book gap explicitly."""
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        cap = _capture(tmp_path / "cap")
        session.run_replay(cap, expect_class=CLASS)
        ckpt = json.loads(store._db.execute(
            "SELECT payload FROM checkpoints WHERE run_id=? AND kind=?",
            ("sess-test", "depth-prime")).fetchone()[0])
        assert ckpt["present"] is False and ckpt["total"] == 0
        final = json.loads(store._db.execute(
            "SELECT payload FROM checkpoints WHERE run_id=? AND kind=?",
            ("sess-test", "depth-prime-final")).fetchone()[0])
        assert final["applied"] == 0 and final["unreached"] == 0
    finally:
        store.close()


def test_stop_actions_cancel_reduce_and_alert_once(tmp_path):
    """Manager P1: latched stop cancels entries, reduces, alerts once."""
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        session._init_run_files()
        # Latch an emergency stop with exposure present.
        session.policy._state.emergency_latched = True

        class _Ord:
            client_order_id = "e-1"
            role = "entry"
            state = "open"

        cancelled: list[str] = []
        session.engine.open_orders = lambda: [_Ord()]
        session.engine.cancel = lambda cid, why: cancelled.append(cid)
        flattened: list[str] = []
        session._flatten = lambda why: flattened.append(why)
        session.ledger.record_fill(
            "BUY", 1.0, 100.0, 0.01, session.now_utc(), "t1", "BTCUSDT")
        session._run_stop_actions()
        session._run_stop_actions()  # alert must not duplicate.
        assert cancelled == ["e-1", "e-1"]
        assert flattened == ["stop-action", "stop-action"]
        alerts = [json.loads(line) for line in
                  (session.workdir / "risk.jsonl").read_text().splitlines()
                  if '"operator-alert"' in line]
        assert len(alerts) == 1
    finally:
        store.close()


def test_live_prime_skipped_for_dynamic_symbols(tmp_path):
    """Manager: live priming with undiscovered symbols records skip."""
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        assert session.config.symbols == ()
        summary = session._prime_live_books()
        assert summary["skipped"] == "dynamic-symbols"
    finally:
        store.close()


def test_live_prime_reports_install_outcome(tmp_path, monkeypatch):
    """Manager P2: a fetched-but-uninstalled snapshot is NOT synced."""
    import dataclasses
    import urllib.request
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        session.config = dataclasses.replace(
            session.config, symbols=("BTCUSDT",))

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({
                    "bids": [["99.5", "1.0"]], "asks": [["100.5", "1.0"]],
                    "lastUpdateId": 7, "T": T0}).encode()

        monkeypatch.setattr(urllib.request, "urlopen",
                            lambda req, timeout=15.0: _Resp())
        monkeypatch.setattr(
            session._depth_store, "apply_snapshot_record",
            lambda snap: "resync")
        summary = session._prime_live_books()
        assert summary["synced"] == []
        assert summary["failed"]["BTCUSDT"]["outcome"] == "resync"
        assert "sync" in summary["failed"]["BTCUSDT"]
    finally:
        store.close()


def test_replay_future_snapshot_never_installs(tmp_path):
    """Manager P1: a snapshot newer than every event is never installed."""
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        cap = _capture(tmp_path / "cap")
        early = _snap()
        late = _snap(last_id=999)
        late["rest_recv_ms"] = T0 + 10_000_000
        late["bids"] = [["200.0", "1.0"]]
        late["asks"] = [["201.0", "1.0"]]
        (cap / "depth_snapshots.jsonl").write_text(
            "\n".join(json.dumps(s) for s in (early, late)) + "\n")
        session.run_replay(cap, expect_class=CLASS)
        final = json.loads(store._db.execute(
            "SELECT payload FROM checkpoints WHERE run_id=? AND kind=?",
            ("sess-test", "depth-prime-final")).fetchone()[0])
        assert (final["applied"], final["unreached"]) == (1, 1)
        from cryptobot.market_data.views import book_flow_for
        book, _, _ = book_flow_for(
            "BTCUSDT", T0 + 60_000, session._depth_store)
        assert book is not None and book.bids[0][0] < 150.0
    finally:
        store.close()


def test_ingest_resync_marks_book_unsynced(tmp_path):
    """Manager P3: a chain break stops the sync claim + is counted."""
    session, store = _session(tmp_path, warmup_bars=3)
    try:
        session._depth_store.apply_snapshot_record(_snap())
        assert not session._depth_store.needs_snapshot("BTCUSDT")
        session._ingest({
            "channel": "depth", "symbol": "BTCUSDT",
            "exchange_ts_ms": T0 + 500, "local_recv_ms": T0 + 505,
            "payload": {"first_update": 50, "last_update": 55,
                        "prev_last_update": 49,
                        "bids": [], "asks": []}}, {}, {})
        assert session._depth_store.needs_snapshot("BTCUSDT")
        assert session._resyncs_seen == {"BTCUSDT": 1}
        rep = session._depth_store.sync_report("BTCUSDT")
        assert rep["synced"] is False and rep["needs_snapshot"] is True
    finally:
        store.close()
