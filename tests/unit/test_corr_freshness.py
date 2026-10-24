"""CORR-DATA step 3: symbol-scoped freshness gates.

Each admission candidate is gated on its OWN symbol's executable
observation (last BBO/trade exchange time) and, when exchange
valuation marks source valuation, its own mark observation. No
cross-symbol substitution, no receipt-time refresh of old stamps.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.session import Session, WallClock, _SymbolFeed
from cryptobot.app.store import RunStore
from cryptobot.coordination.exits import ExitPolicy, encode_exit_rule
from cryptobot.coordination.intent import DataQuality, ForecastCost, Intent, Side
from cryptobot.coordination.selector import Candidate


def _paper_config(tmp_path: Path, **over):
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    for key, value in over.items():
        text = text.replace(f"{key} =", f"{key} = {value} #", 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    return load_config(cfg_path)


class _MarkEngine:
    model_label = "corr-stub"
    assumptions = ("stub: corr-data",)

    def __init__(self):
        self.advance_calls: list = []
        self.marks: dict = {}
        self.mark_ts: dict = {}
        self.submits: list = []
        self._now = datetime(2020, 1, 1, tzinfo=UTC)

    @property
    def now_utc(self):
        return self._now

    def advance_to(self, ts_utc):
        self.advance_calls.append(ts_utc)
        self._now = ts_utc

    def poll(self):
        return []

    def pop_events(self, max_events: int = 1000):
        return []

    def note_mark(self, instrument, price, ts_utc=None):
        pass

    def note_event(self, event):
        pass

    def valuation_mark(self, instrument):
        return self.marks.get(instrument)

    def valuation_mark_ts(self, instrument):
        return self.mark_ts.get(instrument)

    def set_exit_only(self, halted, reason=""):
        pass

    def recover(self, sink):
        pass

    def close(self):
        pass

    def unknown_ids(self):
        return []

    def resolve(self, cid):
        return None

    def cancel(self, cid, reason):
        pass

    def submit(self, cmd):
        self.submits.append(cmd)
        return "corr-1"

    def submit_immediate(self, cmd):
        self.submits.append(cmd)
        return "corr-1"


def _corr_session(tmp_path: Path, engine=None, name="corr-1"):
    engine = engine or _MarkEngine()
    cfg = _paper_config(tmp_path)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / name, name,
                      clock=WallClock(), engine=engine)
    session.policy.reconcile_day(120.0, 0.0)
    now = datetime.now(UTC)
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0},
         "ETHUSDT": {"tick_size": 0.01, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin="test", asof_utc=now)
    session._init_run_files()
    return session, store


def _intent(symbol: str, now: datetime, **over) -> Intent:
    args = dict(
        strategy="S1", version="0.1.0", instrument=symbol,
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
        evidence_ref=f"test:{symbol}", data_quality=DataQuality.CLEAN)
    args.update(over)
    return Intent(**args)


def _seed(session, symbol: str, age_s: float):
    feed = _SymbolFeed(symbol, 0)
    feed.mark = 100.0
    feed.mark_ts = session.now_utc() - timedelta(seconds=age_s)
    session._feeds[symbol] = feed


def _rejections(session):
    path = session.workdir / "rejections.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def _saw_marks(session):
    session._ingest({"channel": "markPrice", "symbol": "BTCUSDT",
                     "exchange_ts_ms": int(time.time() * 1000),
                     "payload": {"mark": 100.0}}, {}, {})


# -- cross-symbol isolation ----------------------------------------------------


def test_fresh_first_does_not_admit_stale_symbol(tmp_path):
    engine = _MarkEngine()
    session, store = _corr_session(tmp_path, engine)
    try:
        _seed(session, "BTCUSDT", 0.0)   # fresh, inserted first.
        _seed(session, "ETHUSDT", 30.0)  # stale candidate symbol.
        assert session._quote_age_gate("ETHUSDT") == "gate:stale-quote"
        session._maybe_admit(
            [Candidate("S1", _intent("ETHUSDT", session.now_utc()))])
        assert session._position is None
        assert engine.submits == []
        rows = _rejections(session)
        assert len(rows) == 1
        assert (rows[0]["instrument"], rows[0]["reason"]) == (
            "ETHUSDT", "gate:stale-quote")
    finally:
        store.close()


def test_stale_first_does_not_block_fresh_symbol(tmp_path):
    engine = _MarkEngine()
    session, store = _corr_session(tmp_path, engine)
    try:
        _seed(session, "BTCUSDT", 30.0)  # stale, inserted first.
        _seed(session, "ETHUSDT", 0.0)   # fresh candidate symbol.
        assert session._quote_age_gate("ETHUSDT") is None
        session._maybe_admit(
            [Candidate("S1", _intent("ETHUSDT", session.now_utc()))])
        gates = [r for r in session._reject_counts if r.startswith("gate:")]
        assert gates == []
        assert session._position is not None  # admitted on own merit.
    finally:
        store.close()


def test_mixed_batch_gates_each_candidate_on_own_symbol(tmp_path):
    session, store = _corr_session(tmp_path)
    try:
        _seed(session, "BTCUSDT", 30.0)
        _seed(session, "ETHUSDT", 0.0)
        now = session.now_utc()
        session._maybe_admit(
            [Candidate("S1", _intent("BTCUSDT", now)),
             Candidate("S1", _intent("ETHUSDT", now))])
        rows = {(r["instrument"], r["reason"]) for r in _rejections(session)}
        assert ("BTCUSDT", "gate:stale-quote") in rows
        assert not any(inst == "ETHUSDT" and reason.startswith("gate:")
                       for inst, reason in rows)
    finally:
        store.close()


def test_missing_symbol_observation_fails_closed(tmp_path):
    session, store = _corr_session(tmp_path)
    try:
        _seed(session, "BTCUSDT", 0.0)
        assert (session._quote_age_gate("ETHUSDT")
                == "gate:quote-age-unknown")
        session._maybe_admit(
            [Candidate("S1", _intent("ETHUSDT", session.now_utc()))])
        assert session._position is None
    finally:
        store.close()


# -- executable vs valuation-mark ages -----------------------------------------


def test_fresh_mark_with_stale_quote_rejects(tmp_path):
    engine = _MarkEngine()
    session, store = _corr_session(tmp_path, engine)
    try:
        _saw_marks(session)
        now = session.now_utc()
        engine.marks["BTCUSDT"] = 100.0
        engine.mark_ts["BTCUSDT"] = now  # fresh exchange mark.
        _seed(session, "BTCUSDT", 30.0)  # stale executable quote.
        assert session._quote_age_gate("BTCUSDT") == "gate:stale-quote"
    finally:
        store.close()


def test_fresh_quote_with_stale_mark_rejects(tmp_path):
    engine = _MarkEngine()
    session, store = _corr_session(tmp_path, engine)
    try:
        _saw_marks(session)
        now = session.now_utc()
        engine.marks["BTCUSDT"] = 100.0
        engine.mark_ts["BTCUSDT"] = now - timedelta(seconds=30)
        _seed(session, "BTCUSDT", 0.0)  # fresh executable quote.
        assert session._quote_age_gate("BTCUSDT") == "gate:stale-mark"
        session._maybe_admit(
            [Candidate("S1", _intent("BTCUSDT", now))])
        assert session._position is None
        assert session._reject_counts.get("gate:stale-mark") == 1
    finally:
        store.close()


def test_mark_present_without_timestamp_fails_closed(tmp_path):
    engine = _MarkEngine()
    session, store = _corr_session(tmp_path, engine)
    try:
        _saw_marks(session)
        engine.marks["BTCUSDT"] = 100.0
        engine.mark_ts["BTCUSDT"] = None
        _seed(session, "BTCUSDT", 0.0)
        assert (session._quote_age_gate("BTCUSDT")
                == "gate:mark-age-unknown")
    finally:
        store.close()


def test_mark_not_required_without_exchange_flow(tmp_path):
    engine = _MarkEngine()
    session, store = _corr_session(tmp_path, engine)
    try:
        # No markPrice ever flowed: valuation falls back to the feed,
        # so no mark observation is required (even with echo marks set).
        engine.marks["BTCUSDT"] = 100.0
        engine.mark_ts["BTCUSDT"] = (session.now_utc()
                                     - timedelta(seconds=300))
        _seed(session, "BTCUSDT", 0.0)
        assert session._quote_age_gate("BTCUSDT") is None
    finally:
        store.close()


def test_mark_age_unenforced_when_profile_bound_unset(tmp_path):
    import dataclasses
    engine = _MarkEngine()
    session, store = _corr_session(tmp_path, engine)
    try:
        session.config = dataclasses.replace(
            session.config, max_mark_age_ms=None)
        _saw_marks(session)
        engine.marks["BTCUSDT"] = 100.0
        engine.mark_ts["BTCUSDT"] = (session.now_utc()
                                     - timedelta(seconds=30))
        _seed(session, "BTCUSDT", 0.0)
        assert session._quote_age_gate("BTCUSDT") is None
    finally:
        store.close()


# -- malformed timestamps: reject, never crash ---------------------------------


def test_malformed_quote_timestamps_reject(tmp_path):
    session, store = _corr_session(tmp_path)
    try:
        feed = _SymbolFeed("BTCUSDT", 0)
        feed.mark = 100.0
        feed.mark_ts = "not-a-time"
        session._feeds["BTCUSDT"] = feed
        assert (session._quote_age_gate("BTCUSDT")
                == "gate:quote-age-unknown")
        feed.mark_ts = datetime(2026, 1, 1)  # naive.
        assert (session._quote_age_gate("BTCUSDT")
                == "gate:quote-age-unknown")
    finally:
        store.close()


def test_malformed_mark_timestamp_rejects(tmp_path):
    engine = _MarkEngine()
    session, store = _corr_session(tmp_path, engine)
    try:
        _saw_marks(session)
        engine.marks["BTCUSDT"] = 100.0
        engine.mark_ts["BTCUSDT"] = "not-a-time"
        _seed(session, "BTCUSDT", 0.0)
        assert (session._quote_age_gate("BTCUSDT")
                == "gate:mark-age-unknown")
    finally:
        store.close()


# -- event-time stamping: no receipt-time refresh -------------------------------


def test_late_stale_event_keeps_exchange_age(tmp_path):
    session, store = _corr_session(tmp_path)
    try:
        old_ms = int(time.time() * 1000) - 30_000
        session._ingest({"channel": "bookTicker", "symbol": "BTCUSDT",
                         "input_class": "observed-public",
                         "exchange_ts_ms": old_ms,
                         "local_recv_ms": old_ms + 5,
                         "payload": {"bid": 99.99, "ask": 100.01}}, {}, {})
        feed = session._feeds["BTCUSDT"]
        assert feed.mark == 100.0
        # Stamped with exchange time, not receipt: still stale.
        assert session._quote_age_gate("BTCUSDT") == "gate:stale-quote"
    finally:
        store.close()


def test_fresh_event_stamps_fresh(tmp_path):
    session, store = _corr_session(tmp_path)
    try:
        now_ms = int(time.time() * 1000)
        session._ingest({"channel": "bookTicker", "symbol": "BTCUSDT",
                         "input_class": "observed-public",
                         "exchange_ts_ms": now_ms,
                         "local_recv_ms": now_ms + 1,
                         "payload": {"bid": 99.99, "ask": 100.01}}, {}, {})
        assert session._quote_age_gate("BTCUSDT") is None
    finally:
        store.close()


# -- risk snapshot follows the candidate symbol ---------------------------------


def test_risk_snapshot_age_follows_candidate_symbol(tmp_path):
    session, store = _corr_session(tmp_path)
    try:
        _seed(session, "BTCUSDT", 30.0)
        _seed(session, "ETHUSDT", 0.0)
        eth = session._snapshot_account(symbol="ETHUSDT")
        btc = session._snapshot_account(symbol="BTCUSDT")
        assert eth.mark_age_ms is not None and eth.mark_age_ms < 1000.0
        assert btc.mark_age_ms is not None and btc.mark_age_ms > 5000.0
        assert (session._snapshot_account(symbol="NOPEUSDT").mark_age_ms
                is None)
    finally:
        store.close()
