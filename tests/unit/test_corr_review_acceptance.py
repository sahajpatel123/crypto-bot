"""CORR acceptance: reviewer probes converted to regression assertions.

Manager-owned. Each test encodes the CORRECT behavior from
Crypto_Bot_cdcd10c_Review_Probes.py observations; on the base tag they
fail (defect present), and they must pass on the integrated fix revision.
Freshness symbol-scoping assertions land after W3 files its API.

No network, no keys, synthetic data only. Seconds-scale.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

nautilus = pytest.importorskip("nautilus_trader")

from cryptobot.adapters import NautilusPaperEngine  # noqa: E402
from cryptobot.app.engine import EngineOrder  # noqa: E402
from cryptobot.bench_run import BenchRunner  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SYM = "BTCUSDT"


def _engine(**kw):
    kw.setdefault("taker_bps", 5.0)
    kw.setdefault("now_utc", lambda: T0)
    kw.setdefault("submit_delay_ms", 0)
    kw.setdefault("fill_delay_ms", 1)
    engine = NautilusPaperEngine(**kw)
    engine.add_instrument(SYM, price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    return engine


def _quote(engine, at, bid, ask, bid_size=1.0, ask_size=1.0):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    ns = int(at.timestamp() * 1e9)
    engine.feed(QuoteTick(
        engine.instrument_id(SYM), Price(bid, 2), Price(ask, 2),
        Quantity(bid_size, 3), Quantity(ask_size, 3),
        ts_event=ns, ts_init=ns))


def _drain(engine):
    out = []
    for _ in range(10):
        batch = engine.poll()
        if not batch:
            break
        out.extend(batch)
    return out


# -- Finding 1: marketable IOC must not use future liquidity ------------------
def test_marketable_ioc_buy_cannot_use_later_quote():
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    try:
        _quote(engine, T0, 99.0, 101.0)
        cid = engine.submit(EngineOrder(
            instrument=SYM, side="BUY", qty=0.001, kind="LIMIT",
            price=101.50, role="entry"))
        engine.advance_to(T0 + timedelta(milliseconds=200))
        early = _drain(engine)
        fills = [e for e in early if e.kind == "fill"]
        # Arrival ask 101.0 is inside the 101.50 cap with size: the IOC
        # fills at the arrival opportunity, not 10s later.
        assert len(fills) == 1, [e.kind for e in early]
        assert fills[0].payload.price == pytest.approx(101.0)
        assert fills[0].payload.client_order_id == cid
        _quote(engine, T0 + timedelta(seconds=10), 89.0, 90.0)
        late = _drain(engine)
        late_prices = [getattr(e.payload, "price", None) for e in late]
        assert 90.0 not in late_prices, "future quote priced the IOC"
        assert [e for e in late
                if getattr(e.payload, "client_order_id", None) == cid] == []
    finally:
        engine.close()


def test_marketable_ioc_sell_mirror():
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    try:
        _quote(engine, T0, 99.0, 101.0)
        cid = engine.submit(EngineOrder(
            instrument=SYM, side="SELL", qty=0.001, kind="LIMIT",
            price=98.50, role="entry"))
        engine.advance_to(T0 + timedelta(milliseconds=200))
        early = _drain(engine)
        fills = [e for e in early if e.kind == "fill"]
        assert len(fills) == 1, [e.kind for e in early]
        assert fills[0].payload.price == pytest.approx(99.0)
        _quote(engine, T0 + timedelta(seconds=10), 110.0, 111.0)
        late = _drain(engine)
        late_prices = [getattr(e.payload, "price", None) for e in late]
        assert 111.0 not in late_prices, "future quote priced the IOC"
        assert [e for e in late
                if getattr(e.payload, "client_order_id", None) == cid] == []
    finally:
        engine.close()


def test_marketable_ioc_partial_remainder_cannot_revive():
    # Thin arrival book (ask 0.0005 < qty 0.002): the venue matches a
    # PARTIAL at the due-time opportunity and the remainder cancels
    # there. Exact matched qty is venue behavior (pinned Nautilus
    # lot/quote-size rule — asserted as a range, not pinned); the
    # causal properties (arrival price, same-opportunity terminal,
    # frozen qty, nothing later) are exact.
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    try:
        _quote(engine, T0, 99.0, 101.0, ask_size=0.0005)
        cid = engine.submit(EngineOrder(
            instrument=SYM, side="BUY", qty=0.002, kind="LIMIT",
            price=101.50, role="entry"))
        engine.advance_to(T0 + timedelta(milliseconds=200))
        early = _drain(engine)
        fills = [e for e in early if e.kind == "fill"]
        assert len(fills) == 1, [e.kind for e in early]
        assert 0.0 < fills[0].payload.qty < 0.002
        assert fills[0].payload.price == pytest.approx(101.0)
        part = engine.filled_qty(cid)
        assert part == pytest.approx(fills[0].payload.qty)
        cancels = [e for e in early if e.kind == "cancel"]
        assert len(cancels) == 1  # remainder canceled at the opportunity.
        assert cancels[0].payload.client_order_id == cid
        _quote(engine, T0 + timedelta(seconds=10), 89.0, 90.0)
        late = _drain(engine)
        assert [e for e in late
                if getattr(e.payload, "client_order_id", None) == cid] == []
        assert engine.filled_qty(cid) == pytest.approx(part)  # frozen.
    finally:
        engine.close()


# -- Finding 2+3: checkpoint preserves the experiment; flat is exact ---------
def _bench_session(tmp_path):
    filters = tmp_path / "filters.json"
    filters.write_text(json.dumps({"symbols": [{
        "symbol": SYM, "pricePrecision": 2, "quantityPrecision": 3,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001",
             "minQty": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}))
    args = argparse.Namespace(config="configs/paper.toml",
                              checkpoint_dir=str(tmp_path / "checkpoint"),
                              engine_seed=42, filters_file=str(filters))
    runner = BenchRunner(args)
    session = runner._build_session("review")
    session.store.create_run("review", "bench", session.config.fingerprint,
                             str(session.workdir), None)
    return runner, session


def _ingest_warmup(session):
    seq = 0
    for second in range(141):
        ts = int(T0.timestamp() * 1000) + second * 1000
        for channel, payload in [
                ("bookTicker", {"bid": 99.99, "ask": 100.01,
                                "bid_qty": 5.0, "ask_qty": 5.0}),
                ("aggTrade", {"agg_id": second + 1, "price": 100.0,
                              "qty": 0.5, "buyer_is_maker": False})]:
            seq += 1
            session._ingest({"channel": channel, "symbol": SYM,
                             "exchange_ts_ms": ts, "local_recv_ms": ts,
                             "seq": seq, "payload": payload}, {}, {})
    return seq


def test_checkpoint_preserves_feeds_and_warmth(tmp_path):
    runner, session = _bench_session(tmp_path)
    try:
        seq = _ingest_warmup(session)
        assert session._warmed
        assert len(session._feeds[SYM].bars) > 0
        runner._commit(session, {"day": "2026-10-01", "seq": seq})
    finally:
        session.engine.close()
        session.store.close()
    restored = runner._build_session("review")
    try:
        runner._restore(restored)
        assert len(restored._feeds) == 1, "feeds lost across restart"
        assert restored._warmed is True, "warmth lost across restart"
        assert len(restored._feeds[SYM].bars) > 0, "bars lost across restart"
    finally:
        restored.engine.close()
        restored.store.close()


def test_orphan_ledger_exposure_is_not_flat(tmp_path):
    runner, session = _bench_session(tmp_path)
    try:
        session.ledger.record_fill("BUY", 0.5, 100.0, 0.05, T0,
                                   "review-orphan")
        assert runner._is_flat(session) is False
    finally:
        session.engine.close()
        session.store.close()


def test_changed_config_resume_refused(tmp_path):
    runner, session = _bench_session(tmp_path)
    try:
        seq = _ingest_warmup(session)
        runner._commit(session, {"day": "2026-10-01", "seq": seq})
    finally:
        session.engine.close()
        session.store.close()
    changed = tmp_path / "changed.toml"
    changed.write_text(Path("configs/paper.toml").read_text().replace(
        "cooldown_s = 300", "cooldown_s = 301"))
    args = argparse.Namespace(config=str(changed),
                              checkpoint_dir=str(tmp_path / "checkpoint"),
                              engine_seed=42,
                              filters_file=str(tmp_path / "filters.json"))
    changed_runner = BenchRunner(args)
    changed_session = changed_runner._build_session("review")
    try:
        with pytest.raises((ValueError, RuntimeError)):
            changed_runner._restore(changed_session)
    finally:
        changed_session.engine.close()
        changed_session.store.close()


# -- Finding 4: freshness is scoped to the candidate symbol -------------------
def _gate_session(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session, ReplayClock
    from cryptobot.app.store import RunStore
    cfg = load_config("configs/paper.toml")
    store = RunStore(tmp_path / "gate.db")
    session = Session(cfg, store, tmp_path / "gate", "gate",
                      clock=ReplayClock(T0))
    return session, store


def _gate_feed(session, symbol, age_s, naive=False):
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed(symbol, 130)
    feed.mark = 100.0
    ts = T0 - timedelta(seconds=age_s)
    feed.mark_ts = ts.replace(tzinfo=None) if naive else ts
    session._feeds[symbol] = feed


def test_gate_scoped_to_candidate_both_directions(tmp_path):
    session, store = _gate_session(tmp_path)
    try:
        _gate_feed(session, "BTCUSDT", 0)
        _gate_feed(session, "ETHUSDT", 60)
        assert session._quote_age_gate("BTCUSDT") is None
        eth = session._quote_age_gate("ETHUSDT")
        assert eth is not None and eth.startswith("gate:"), eth
        _gate_feed(session, "BTCUSDT", 60)
        _gate_feed(session, "ETHUSDT", 0)
        btc = session._quote_age_gate("BTCUSDT")
        assert btc is not None and btc.startswith("gate:"), btc
        assert session._quote_age_gate("ETHUSDT") is None
    finally:
        session.engine.close()
        store.close()


def test_gate_missing_candidate_fails_closed(tmp_path):
    session, store = _gate_session(tmp_path)
    try:
        _gate_feed(session, "BTCUSDT", 0)
        # No ETH feed at all: must reject, never raise, never borrow BTC.
        eth = session._quote_age_gate("ETHUSDT")
        assert eth is not None and eth.startswith("gate:"), eth
    finally:
        session.engine.close()
        store.close()


def test_gate_future_and_malformed_ts_rejected(tmp_path):
    session, store = _gate_session(tmp_path)
    try:
        feed_setup = session._feeds
        _gate_feed(session, "BTCUSDT", -60)  # 60s in the future.
        future = session._quote_age_gate("BTCUSDT")
        assert future is not None and future.startswith("gate:"), future
        feed_setup.clear()
        _gate_feed(session, "BTCUSDT", 0, naive=True)
        malformed = session._quote_age_gate("BTCUSDT")
        assert malformed is not None and malformed.startswith("gate:"), \
            malformed
    finally:
        session.engine.close()
        store.close()


# -- Finding 5: nested deadline stops descendants (platform-sensitive) --------
def test_nested_budget_stops_descendants(tmp_path):
    marker = f"corr-nested-{time.time_ns()}"
    child_code = f"import time; time.sleep(2)  # {marker}"
    inner = [sys.executable, "tools/run_budget.py", "--budget-s", "30",
             "--checkpoint-dir", str(tmp_path / "inner"), "--report-out",
             str(tmp_path / "inner.json"), "--", sys.executable, "-c",
             child_code]
    outer = [sys.executable, "tools/run_budget.py", "--budget-s", "1",
             "--term-grace-s", ".2", "--checkpoint-dir",
             str(tmp_path / "outer"), "--report-out",
             str(tmp_path / "outer.json"), "--", *inner]
    start = time.monotonic()
    done = subprocess.run(outer, capture_output=True, text=True, timeout=15)
    observed = time.monotonic() - start
    assert done.returncode == 124
    # The 2s child must actually stop: observed wall stays near the 1s
    # outer budget instead of stretching past the child's 2s sleep.
    assert observed < 2.0, f"descendants outlived the wrapper: {observed}s"
    time.sleep(0.3)  # let a straggler reparent before the identity check.
    ps = subprocess.run(["pgrep", "-f", marker],
                        capture_output=True, text=True)
    assert ps.stdout.strip() == "", f"orphaned child: {ps.stdout}"
