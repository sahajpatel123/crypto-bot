"""Bounded-runner tests (W2, 30MIN §6). Tiny synthetic manifests only."""
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptobot.bench_run import main

SYM = "BTCUSDT"
DAY1 = "2026-10-11"
DAY2 = "2026-10-12"
T1 = int(datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp() * 1000)
T2 = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp() * 1000)


def _trade(seq, ts, agg_id, price):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": "observed-public", "source": "synthetic-test",
            "route": "test", "run_id": "t", "seq": seq, "channel": "aggTrade",
            "symbol": SYM, "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
            "local_mono_ns": seq, "gap_kind": None, "venue_seq": agg_id,
            "payload": {"agg_id": agg_id, "price": price, "qty": 0.5,
                        "first_id": agg_id, "last_id": agg_id,
                        "trade_ts_ms": ts, "buyer_is_maker": False}}


def _manifest(tmp_path: Path, n1=12, n2=12) -> Path:
    events = [_trade(i + 1, T1 + 60_000 + i * 1000, 1000 + i, 100.0)
              for i in range(n1)]
    events += [_trade(n1 + i + 1, T2 + 60_000 + i * 1000, 2000 + i, 101.0)
               for i in range(n2)]
    ev_path = tmp_path / "events.jsonl"
    ev_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    toml = tmp_path / "cap.toml"
    toml.write_text(
        "[dataset]\nname = \"t\"\nkind = \"captured-runs\"\n"
        "manifest_version = 1\n\n[[source]]\nrun_id = \"t\"\n"
        "file = \"events.jsonl\"\n"
        f"local = \"{ev_path}\"\nsymbols = [\"{SYM}\"]\n")
    return toml


def _filters(tmp_path: Path) -> Path:
    path = tmp_path / "filters.json"
    path.write_text(json.dumps({
        "symbols": [{
            "symbol": SYM, "pricePrecision": 2, "quantityPrecision": 3,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001",
                 "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
            ]}]}))
    return path


def _args(tmp_path, manifest, ckpt, report, extra=()):
    base = ["--config", "configs/paper.toml", "--dataset", str(manifest),
            "--symbol", SYM, "--days", f"{DAY1},{DAY2}",
            "--wall-budget-s", "600", "--checkpoint-dir", str(ckpt),
            "--report-out", str(report),
            "--filters-file", str(_filters(tmp_path))]
    return base + list(extra)


def test_fresh_run_completes_and_commits(tmp_path):
    manifest = _manifest(tmp_path)
    ckpt, report = tmp_path / "ck", tmp_path / "rep.json"
    rc = main(_args(tmp_path, manifest, ckpt, report, ["--run-id", "r1"]))
    assert rc == 0
    doc = json.loads(report.read_text())
    assert doc["status"] == "COMPLETE"
    assert doc["events"]["ingested"] == 24
    assert doc["events"]["commits"] >= 2  # day-boundary commits.
    assert set(doc["booked"]) == {"equity_open", "equity_close", "valuation",
                                  "valuation_reason", "realised",
                                  "commissions", "funding"}
    assert doc["booked"]["valuation"] == "cash-exact"  # flat: no mark needed.
    assert "estimated_costs" in doc and "profile" in doc
    assert (ckpt / "bench_checkpoint.json").exists()


def test_split_resume_matches_reference(tmp_path):
    manifest = _manifest(tmp_path, n1=12, n2=12)
    ref_ckpt, ref_rep = tmp_path / "ref-ck", tmp_path / "ref.json"
    assert main(_args(tmp_path, manifest, ref_ckpt, ref_rep,
                      ["--run-id", "ref"])) == 0
    ref = json.loads(ref_rep.read_text())
    # Split mid-day-1, resume across the day boundary.
    sp_ckpt, sp_rep1, sp_rep2 = (tmp_path / "sp-ck", tmp_path / "sp1.json",
                                 tmp_path / "sp2.json")
    rc1 = main(_args(tmp_path, manifest, sp_ckpt, sp_rep1,
                     ["--run-id", "sp", "--max-events", "8"]))
    assert rc1 == 124
    assert json.loads(sp_rep1.read_text())["status"] == "TRUNCATED_MAX_EVENTS"
    rc2 = main(_args(tmp_path, manifest, sp_ckpt, sp_rep2,
                     ["--run-id", "sp", "--resume"]))
    assert rc2 == 0
    split = json.loads(sp_rep2.read_text())
    assert split["status"] == "COMPLETE"
    assert split["events"]["replayed_tail"] > 0  # tail replayed, not dropped.
    for key in ("equity_close", "realised", "commissions", "funding"):
        assert split["booked"][key] == ref["booked"][key], key
    assert split["estimated_costs"] == ref["estimated_costs"]
    chunk1 = json.loads(sp_rep1.read_text())["events"]["ingested"]
    assert chunk1 + split["events"]["ingested"] - \
        split["events"]["replayed_tail"] == ref["events"]["ingested"]


def test_wall_budget_reports_incomplete_never_pass(tmp_path):
    manifest = _manifest(tmp_path, n1=30, n2=30)
    ckpt, report = tmp_path / "ck", tmp_path / "rep.json"
    rc = main(_args(tmp_path, manifest, ckpt, report,
                    ["--run-id", "b1", "--wall-budget-s", "0.000001"]))
    assert rc == 124
    doc = json.loads(report.read_text())
    assert doc["status"] == "INCOMPLETE_BUDGET"
    assert doc["stop_reason"] == "wall_budget"
    assert doc["events"]["ingested"] >= 1


def test_resume_requires_checkpoint_and_fresh_refuses_overwrite(tmp_path):
    manifest = _manifest(tmp_path)
    ckpt, report = tmp_path / "ck", tmp_path / "rep.json"
    rc = main(_args(tmp_path, manifest, ckpt, report,
                    ["--run-id", "x", "--resume"]))
    assert rc == 1  # no checkpoint.
    assert main(_args(tmp_path, manifest, ckpt, report,
                      ["--run-id", "y"])) == 0
    rc = main(_args(tmp_path, manifest, ckpt, report, ["--run-id", "z"]))
    assert rc == 1  # exists without --resume.


def test_checkpoint_preserves_position_economics(tmp_path):
    """Snapshot/restore round-trips ledger, risk, cooldowns, journal."""
    import argparse
    from datetime import timedelta

    from cryptobot.bench_run import BenchRunner

    args = argparse.Namespace(
        config="configs/paper.toml", checkpoint_dir=str(tmp_path / "ck"),
        engine_seed=42, filters_file=str(_filters(tmp_path)))
    runner = BenchRunner(args)
    session = runner._build_session("mech")
    try:
        now = datetime(2026, 10, 11, 1, tzinfo=timezone.utc)
        session.clock.set_ms(int(now.timestamp() * 1000))
        session.policy.reconcile_day(120.0, 0.0)
        session._day = "2026-10-11"
        session.ledger.record_fill("BUY", 0.5, 100.0, 0.05, now, "e1")
        session.selector._cooldowns[("S1", SYM)] = now
        session.engine._journal("submitted", {"client_id": "pe-1"})
        session._events_seen, session._admitted = 41, 2
        session._reject_counts = {"a:b": 3}
        session._last_seq = 40
        cursor = {"day": DAY1, "seq": 40}
        # Orphan exposure: the flat gate must refuse a commit here.
        assert runner._is_flat(session) is False
        assert runner._commit(session, cursor) is False
        # Snapshot/restore round-trip still preserves the economics.
        record = runner._snapshot(session, cursor)
        (tmp_path / "ck" / "bench_checkpoint.json").write_text(
            json.dumps(record), encoding="utf-8")
        snap = record
        assert snap["ledger"]["snapshot"]["qty"] == 0.5
        assert snap["counts"] == {"events_seen": 41, "admitted": 2,
                                  "reject_counts": {"a:b": 3},
                                  "dispatch_ms": 0}
        assert set(snap["run_files"]) == {"fills.jsonl", "equity.jsonl",
                                          "rejections.jsonl", "risk.jsonl"}
        assert snap["cooldowns"] == {f"S1|{SYM}": now.isoformat()}
        journal = tmp_path / "ck" / "work" / "engine_journal.jsonl"
        assert snap["engine"]["journal_bytes"] == journal.stat().st_size > 0
        committed_journal = journal.read_bytes()
        # Mutate everything past the commit, then restore.
        session.ledger.record_fill("SELL", 0.5, 101.0, 0.05, now, "e2")
        session.selector._cooldowns[("S2", SYM)] = now + timedelta(seconds=1)
        session.engine._journal("fill", {"client_id": "pe-1"})
        session._events_seen = 999
        restored = runner._restore(session)
        assert restored == cursor
        assert session.ledger.position_qty() == 0.5
        assert session.ledger.net_realised() == -0.05  # one fee booked.
        assert session.selector._cooldowns == {("S1", SYM): now}
        # Truncated to the commit, plus recover's inert "recovered" marker.
        assert journal.read_bytes()[:snap["engine"]["journal_bytes"]] == \
            committed_journal
        assert b'"fill"' not in journal.read_bytes()
        assert session._events_seen == 41 and session._admitted == 2
        assert session._reject_counts == {"a:b": 3}
        assert session._last_seq == 40 and session._day == "2026-10-11"
    finally:
        session.engine.close()
        session.store.close()


def test_replay_clock_tracks_event_time(tmp_path):
    # 30MIN scoring fix (manager): the session clock must follow event
    # exchange timestamps on the bench path. Before the fix the clock
    # advanced only 1s per heartbeat, so the 1s quote-age gate compared
    # a lagged clock against event-time marks and every strategy
    # candidate died stale (0 intents on an 811k-event slice).
    manifest = _manifest(tmp_path)
    ckpt, report = tmp_path / "ck", tmp_path / "rep.json"
    rc = main(_args(tmp_path, manifest, ckpt, report, ["--run-id", "rclock"]))
    assert rc == 0
    commit = json.loads((ckpt / "bench_checkpoint.json").read_text())
    assert commit["clock_ms"] == T2 + 71_000  # last event exchange_ts.


def _corr_runner(tmp_path):
    import argparse

    from cryptobot.bench_run import BenchRunner

    args = argparse.Namespace(
        config="configs/paper.toml", checkpoint_dir=str(tmp_path / "ck"),
        engine_seed=42, filters_file=str(_filters(tmp_path)))
    runner = BenchRunner(args)
    runner._adapter_names, runner._dataset_id, runner._last_mark = [], {}, {}
    return runner


def test_is_flat_terminal_orders_are_history_not_exposure(tmp_path):
    from types import SimpleNamespace

    from cryptobot.bench_run import BenchRunner

    runner = _corr_runner(tmp_path)
    filled = [SimpleNamespace(state="filled"), SimpleNamespace(state="filled")]
    engine = SimpleNamespace(open_orders=lambda: filled, _submit_queue=[],
                             _pending=[], _ioc_open={}, _cache=None)
    assert BenchRunner._is_flat(None, SimpleNamespace(
        _position=None, engine=engine)) is True
    live = [SimpleNamespace(state="filled"), SimpleNamespace(state="partial")]
    engine2 = SimpleNamespace(open_orders=lambda: live, _submit_queue=[],
                              _pending=[], _ioc_open={}, _cache=None)
    assert runner._is_flat(SimpleNamespace(
        _position=None, engine=engine2)) is False
    queued = SimpleNamespace(open_orders=lambda: filled, _submit_queue=[1],
                             _pending=[], _ioc_open={}, _cache=None)
    assert runner._is_flat(SimpleNamespace(
        _position=None, engine=queued)) is False


def test_is_flat_orphan_and_pending_and_reservations(tmp_path):
    from types import SimpleNamespace

    runner = _corr_runner(tmp_path)
    session = runner._build_session("flatcases")
    try:
        assert runner._is_flat(session) is True
        now = datetime(2026, 10, 11, 1, tzinfo=timezone.utc)
        session.ledger.record_fill("BUY", 0.5, 100.0, 0.05, now, "o1")
        assert runner._is_flat(session) is False  # orphan exposure.
        session.ledger.record_fill("SELL", 0.5, 100.0, 0.05, now, "o2")
        assert runner._is_flat(session) is True
        session.engine._submit_queue.append(("x", 1))
        assert runner._is_flat(session) is False  # pending command.
        session.engine._submit_queue.clear()
        session._flatten_pending = True
        assert runner._is_flat(session) is False
        session._flatten_pending = False
        assert runner._is_flat(session) is True
    finally:
        session.engine.close()
        session.store.close()


def test_feeds_and_warmed_restore_exactly(tmp_path):
    runner = _corr_runner(tmp_path)
    session = runner._build_session("feeds")
    try:
        session.store.create_run("feeds", "bench", session.config.fingerprint,
                                 str(session.workdir), None)
        t0 = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
        seq = 0
        for second in range(141):
            ts = t0 + second * 1000
            for channel, payload in [
                    ("bookTicker", {"bid": 99.99, "ask": 100.01,
                                    "bid_qty": 5.0, "ask_qty": 5.0}),
                    ("aggTrade", {"agg_id": second + 1, "price": 100.0,
                                  "qty": 0.5, "buyer_is_maker": False})]:
                seq += 1
                session._ingest({"channel": channel, "symbol": SYM,
                                 "exchange_ts_ms": ts, "local_recv_ms": ts,
                                 "seq": seq, "payload": payload}, {}, {})
        feed0 = session._feeds[SYM]
        assert len(feed0.bars) == 135 and session._warmed is True
        bars0 = [None if b is None else (b.ts_utc.isoformat(), b.open,
                                         b.high, b.low, b.close, b.volume,
                                         b.trades, b.buy_frac, b.spread_bps,
                                         b.source) for b in feed0.bars]
        agg0 = feed0.agg.to_dict()
        assert runner._commit(session, {"day": "2026-10-01", "seq": seq})
        session2 = runner._build_session("feeds")
        try:
            runner._restore(session2)
            feed1 = session2._feeds[SYM]
            bars1 = [None if b is None else (b.ts_utc.isoformat(), b.open,
                                             b.high, b.low, b.close,
                                             b.volume, b.trades, b.buy_frac,
                                             b.spread_bps, b.source)
                     for b in feed1.bars]
            assert bars1 == bars0 and len(feed1.bars) == 135
            assert feed1.agg.to_dict() == agg0
            assert session2._warmed is True
            assert feed1.mark == feed0.mark and feed1.missing == feed0.missing
        finally:
            session2.engine.close()
            session2.store.close()
    finally:
        session.engine.close()
        session.store.close()


def test_identity_refuses_changed_config(tmp_path):
    runner = _corr_runner(tmp_path)
    session = runner._build_session("ident")
    try:
        session.store.create_run("ident", "bench", session.config.fingerprint,
                                 str(session.workdir), None)
        assert runner._commit(session, {"day": DAY1, "seq": 0})
        changed = tmp_path / "changed.toml"
        changed.write_text(Path("configs/paper.toml").read_text().replace(
            "cooldown_s = 300", "cooldown_s = 301"))
        runner.args.config = str(changed)
        session2 = runner._build_session("ident")
        try:
            import pytest

            with pytest.raises(ValueError, match="identity mismatch"):
                runner._restore(session2)
        finally:
            session2.engine.close()
            session2.store.close()
    finally:
        session.engine.close()
        session.store.close()


def test_store_rollback_removes_tail_dupes(tmp_path):
    runner = _corr_runner(tmp_path)
    session = runner._build_session("store")
    try:
        session.store.create_run("store", "bench", session.config.fingerprint,
                                 str(session.workdir), None)
        session.store.checkpoint("store", "admit", {"a": 1})
        cursors = runner._snapshot_store(session)
        session.store.checkpoint("store", "admit", {"a": 2})  # tail row.
        n_before = session.store._db.execute(
            "SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        assert n_before == cursors["checkpoints"] + 1
        runner._restore_store(session, {"store_cursors": cursors})
        n_after = session.store._db.execute(
            "SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        assert n_after == cursors["checkpoints"]
    finally:
        session.engine.close()
        session.store.close()


def test_closing_valuation_never_zero(tmp_path):
    runner = _corr_runner(tmp_path)
    session = runner._build_session("val")
    try:
        close = runner._value_close(session)
        assert close["valuation"] == "cash-exact"
        assert close["equity_close"] == 120.0
        now = datetime(2026, 10, 11, 1, tzinfo=timezone.utc)
        session.ledger.record_fill("BUY", 0.5, 100.0, 0.05, now, "v1")
        runner._last_mark = {}
        close = runner._value_close(session)
        assert close["equity_close"] is None
        assert close["valuation"] == "unavailable"
        runner._last_mark = {"price": 101.0, "ts_ms": 1, "source": "aggTrade"}
        close = runner._value_close(session)
        assert close["valuation"] == "sourced-mark"
        assert close["equity_close"] == session.ledger.marked_equity(101.0)
    finally:
        session.engine.close()
        session.store.close()
