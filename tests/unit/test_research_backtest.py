"""Backtest harness tests (Worker 1, Q-007). Session-driven cells."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cryptobot.research.backtest as backtest_mod
from cryptobot.research.backtest import (
    ARM_SETS,
    DEV_DAYS,
    MECHANISM_SPLIT,
    OverlapDedup,
    _default_symbols,
    assemble_split_capture,
    build_partition,
    SPLITS,
    TEST_DAYS,
    VAL_DAYS,
    compare_runs,
    curve_signature,
    day_events_for,
    day_has_quotes,
    day_ids_for,
    fills_signature,
    filters_for,
    preflight,
    prepare_split_capture,
    run_cell,
    run_comparison,
)
from cryptobot.research.spread import PROFILE_ID, SpreadProfile
from cryptobot.research.synth_benchmark import INPUT_CLASS, SYMBOL, SynthBenchmark

CONFIG = "configs/paper.toml"


def test_splits_frozen_cover_30_days_disjoint():
    assert DEV_DAYS == tuple(range(1, 16))
    assert VAL_DAYS == tuple(range(16, 23))
    assert TEST_DAYS == tuple(range(23, 31))
    assert SPLITS == {"dev": DEV_DAYS, "validation": VAL_DAYS, "test": TEST_DAYS}
    assert sorted(DEV_DAYS + VAL_DAYS + TEST_DAYS) == list(range(1, 31))


def test_arm_sets_exact():
    assert set(ARM_SETS) == {"S1", "S2", "S3", "S4", "S5", "COMBINED", "CASH",
                             "X1", "X1-S", "X1-T", "X1-F"}
    assert ARM_SETS["CASH"] == ()
    assert ARM_SETS["COMBINED"] == ("S1", "S2", "S3", "S4", "S5")
    assert ARM_SETS["X1"] == ("X1",) and ARM_SETS["X1-S"] == ("X1",)
    assert ARM_SETS["X1-T"] == ("X1",) and ARM_SETS["X1-F"] == ("X1",)


def test_prepare_quotes_split_no_spread(tmp_path):
    bench = SynthBenchmark()
    manifest = prepare_split_capture(bench, "dev", tmp_path / "cap",
                                     (SYMBOL,))
    assert manifest["days"] == list(range(1, 16))
    assert manifest["dataset_manifest_sha"] == bench.manifest_sha()
    assert all(d["spread_bps_assumed"] is None
               for d in manifest["day_manifest"])
    lines = (tmp_path / "cap" / "events.jsonl").read_text().splitlines()
    assert len(lines) == manifest["n_events"] == 15 * 1200
    ts = [json.loads(line)["exchange_ts_ms"] for line in lines]
    assert ts == sorted(ts)


def test_prepare_noquotes_applies_labeled_profile(tmp_path):
    bench = SynthBenchmark(dataset_id="synth_noquotes")
    manifest = prepare_split_capture(bench, "validation", tmp_path / "cap",
                                     (SYMBOL,), SpreadProfile())
    assert all(d["spread_profile"] == PROFILE_ID
               for d in manifest["day_manifest"])
    assert all(d["spread_bps_assumed"] == 1.0
               for d in manifest["day_manifest"])
    assert all(not d["quotes_expected"] for d in manifest["day_manifest"])
    assert all("bookTicker" not in d["quotes_observed_channels"]
               for d in manifest["day_manifest"])
    n_bbo = sum(1 for line in
                (tmp_path / "cap" / "events.jsonl").read_text().splitlines()
                if '"bookTicker"' in line
                and f'"{PROFILE_ID}"' in line)
    assert n_bbo == 7 * 600  # one modeled quote per traded second


def test_prepare_noquotes_without_profile_records_absence(tmp_path):
    bench = SynthBenchmark(dataset_id="synth_noquotes")
    manifest = prepare_split_capture(bench, "dev", tmp_path / "cap",
                                     (SYMBOL,))
    assert all(d["spread_profile"] is None
               for d in manifest["day_manifest"])
    assert all(not d["quotes_expected"] for d in manifest["day_manifest"])


def _dense_modeled_quotes(events: list[dict], symbol: str,
                          spread_bps: float = 1.0,
                          step_ms: int = 100) -> list[dict]:
    """Production-density modeled BBO for protected-IOC fill-path cells.

    Protected IOC entries evaluate against the book, and production
    bookTicker is sub-second while the synth grid is 1/s. On a 3bps/s
    rip the 1s grid cancels every IOC (the ask runs past the 2bps band
    before the next quote), so fill-path cells need production-density
    modeled quotes. Quotes are causal (last trade at/before their ts)
    and carry the same modeled labels as apply_profile output.
    """
    from cryptobot.research.spread import _modeled_quote
    trades = sorted((e for e in events if e.get("channel") == "aggTrade"),
                    key=lambda e: int(e["exchange_ts_ms"]))
    if not trades:
        return list(events)
    have_quotes = {int(e["exchange_ts_ms"]) for e in events
                   if e.get("channel") == "bookTicker"}
    out = list(events)
    input_class = trades[0].get("input_class", INPUT_CLASS)
    start = int(trades[0]["exchange_ts_ms"])
    end = int(trades[-1]["exchange_ts_ms"])
    ti = 0
    px = float(trades[0]["payload"]["price"])
    for ts in range(start, end + 1, step_ms):
        while (ti + 1 < len(trades)
               and int(trades[ti + 1]["exchange_ts_ms"]) <= ts):
            ti += 1
            px = float(trades[ti]["payload"]["price"])
        if ts in have_quotes:
            continue
        have_quotes.add(ts)
        out.append(_modeled_quote(symbol, ts, px, spread_bps,
                                  input_class, ""))
    out.sort(key=lambda e: (int(e["exchange_ts_ms"]),
                            0 if e.get("channel") == "bookTicker" else 1))
    return out


def _tiny_capture(path: Path) -> Path:
    # Day 1 (impulse-long) only: fast Session cell with real fills.
    bench = SynthBenchmark()
    path.mkdir(parents=True, exist_ok=True)
    events = []
    for e in bench.events(SYMBOL, 1):
        events.append(e)
    events = _dense_modeled_quotes(events, SYMBOL)
    for seq, e in enumerate(events, start=1):
        e["seq"] = seq
        e["local_mono_ns"] = seq
    (path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n")
    return path


def test_run_cell_rip_protection_cancels_unmarketable(tmp_path):
    # Directive L76: on the day-1 rip the 2bps band is dead on arrival
    # (3bps/s move vs 1s-bar signal + latency), so the protected IOC
    # honestly cancels instead of chasing. Fills>0 under MARKET was the
    # unprotected era; the IOC fill mechanism itself is pinned at engine
    # level (test_submit_protected_fills_at_or_better) and at Session
    # level (test_session_protected_entry IOC fill test).
    cap = _tiny_capture(tmp_path / "cap")
    cell = run_cell(CONFIG, cap, ("S1",), tmp_path / "run", "cell-s1",
                    (SYMBOL,))
    report = cell["report"]
    assert report["execution_model"] == "nautilus-paper"
    # 1200 day-1 trades + production-density modeled BBO (deterministic).
    assert report["events_seen"] == 6592
    assert report["intents_admitted"] >= 1
    assert fills_signature(cell["journal"]) == []
    kinds = [json.loads(line)["event"] for line in open(cell["journal"])
             if line.strip()]
    assert "submitted" in kinds  # arrival journaled (at_arrival trace)...
    assert "terminal" in kinds  # ...and the unreachable touch canceled it.
    details = [json.loads(line)["detail"] for line in open(cell["journal"])
               if line.strip() and json.loads(line)["event"] == "terminal"]
    # 30MIN §4: the IOC cancels AT arrival against the tracked book and
    # never reaches the venue model (supersedes venue-canceled resting).
    assert any(d.get("reason") == "nonmarketable-at-arrival"
               for d in details)
    assert report["filter_profile"]["label"] == "frozen-assumed"


def test_run_cell_cash_never_trades(tmp_path):
    cap = _tiny_capture(tmp_path / "cap")
    cell = run_cell(CONFIG, cap, (), tmp_path / "run", "cell-cash",
                    (SYMBOL,))
    report = cell["report"]
    assert report["intents_admitted"] == 0
    assert fills_signature(cell["journal"]) == []
    assert report["closing_equity"] == report["opening_equity"]


def test_determinism_two_runs_identical(tmp_path):
    cap = _tiny_capture(tmp_path / "cap")
    a = run_cell(CONFIG, cap, ("S1",), tmp_path / "a", "det-a", (SYMBOL,))
    b = run_cell(CONFIG, cap, ("S1",), tmp_path / "b", "det-b", (SYMBOL,))
    diff = compare_runs(a["report"], a["journal"], b["report"], b["journal"])
    # Non-vacuous: submits + cancels happen (protected IOC on the rip),
    # and the full event sequence is identical across runs.
    kinds_a = [json.loads(line)["event"] for line in open(a["journal"])
               if line.strip()]
    kinds_b = [json.loads(line)["event"] for line in open(b["journal"])
               if line.strip()]
    assert "submitted" in kinds_a and "terminal" in kinds_a
    assert kinds_a == kinds_b
    assert diff["fills_equal"] and diff["curve_equal"]
    assert diff["metrics_equal"] and diff["deterministic"]
    assert curve_signature(a["journal"]) == curve_signature(b["journal"])


def _noquotes_day_with_profile(mutate_after_s=None):
    # Day 1 without quotes + causal spread profile. Optional mutation: a
    # second realistic impulse (+30bps over 10s, mirroring the day-1 ramp
    # shape so the gap gate passes it) starting at the cutoff. A 1.5x
    # step used to serve here, but it gap-fails like corrupt data and
    # the protected path then (correctly) shows no post-cutoff activity.
    from cryptobot.research.spread import SpreadProfile, apply_profile
    from cryptobot.research.synth_benchmark import SynthBenchmark
    bench = SynthBenchmark(dataset_id="synth_noquotes")
    events = []
    for e in bench.events("XRPUSDT", 1):
        if mutate_after_s is not None:
            day_start = e["exchange_ts_ms"] // 600000 * 600000
            cutoff = day_start + mutate_after_s * 1000
            if e["exchange_ts_ms"] >= cutoff:
                ramp_s = (e["exchange_ts_ms"] - cutoff) // 1000
                lift = 0.0030 * min(ramp_s + 1, 10) / 10
                e = dict(e)
                e["payload"] = dict(
                    e["payload"], price=e["payload"]["price"] * (1 + lift))
        events.append(e)
    merged, manifest = apply_profile(events, "XRPUSDT",
                                     SpreadProfile().default_bps)
    assert manifest["modeled_windows"] > 0
    merged = _dense_modeled_quotes(
        merged, "XRPUSDT", SpreadProfile().default_bps)
    return merged


def _write_capture(events, path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for seq, e in enumerate(events, start=1):
        e["seq"] = seq
        e["local_mono_ns"] = seq
    (path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _journal_prefix(journal_path, cutoff_ms):
    # Normalized (event, ts, detail) records strictly before the cutoff.
    from datetime import datetime
    out = []
    for line in open(journal_path):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        ts_ms = int(datetime.fromisoformat(rec["ts_utc"]).timestamp() * 1000)
        if ts_ms >= cutoff_ms:
            continue
        det = {k: v for k, v in rec["detail"].items()
               if k not in ("client_id", "reservation_id")}
        out.append((rec["event"], rec["ts_utc"],
                    json.dumps(det, sort_keys=True)))
    return out


def test_future_trades_do_not_move_earlier_fills(tmp_path):
    # Q-008: repricing trades from t=200s leaves every order/fill before
    # the cutoff identical (causal spread + replay); the jump itself
    # SHOULD propagate afterwards (sensitivity sanity: the risen price
    # meets protection legs differently than the flat hold).
    base = _noquotes_day_with_profile()
    variant = _noquotes_day_with_profile(mutate_after_s=200)
    assert base != variant  # sanity: the mutation changed the input
    cutoff_ms = variant[0]["exchange_ts_ms"] // 600000 * 600000 + 200 * 1000
    cap_a = _write_capture([dict(e) for e in base], tmp_path / "cap-a")
    cap_b = _write_capture([dict(e) for e in variant], tmp_path / "cap-b")
    a = run_cell(CONFIG, cap_a, ("S1",), tmp_path / "a", "inv-a", (SYMBOL,))
    b = run_cell(CONFIG, cap_b, ("S1",), tmp_path / "b", "inv-b", (SYMBOL,))
    pre_a = _journal_prefix(a["journal"], cutoff_ms)
    pre_b = _journal_prefix(b["journal"], cutoff_ms)
    # Non-vacuous: submit + cancel before cutoff (protected IOC on the
    # rip cancels; causality = identical prefix under future mutation).
    assert len(pre_a) >= 2
    assert pre_a == pre_b
    # The second impulse propagates: variant decisions respond to the
    # mutation (a second S1 signal the base never sees). Both journals
    # stay [submitted, terminal] — the 300s selector cooldown suppresses
    # the second submit — so sensitivity is read at the decision level
    # (recorded intents), not the engine journal.
    import sqlite3
    from pathlib import Path as _Path

    def _intent_refs(run_dir):
        db = sqlite3.connect(_Path(run_dir) / "store.db")
        try:
            return [r[0] for r in db.execute(
                "SELECT DISTINCT intent_id FROM intents")]
        finally:
            db.close()

    refs_a = _intent_refs(a["run_dir"])
    refs_b = _intent_refs(b["run_dir"])
    assert len(refs_a) >= 1
    assert set(refs_a) < set(refs_b)  # variant sees a second signal.


def test_compare_runs_detects_divergence(tmp_path):
    cap = _tiny_capture(tmp_path / "cap")
    a = run_cell(CONFIG, cap, ("S1",), tmp_path / "a", "div-a", (SYMBOL,))
    c = run_cell(CONFIG, cap, (), tmp_path / "c", "div-c", (SYMBOL,))
    diff = compare_runs(a["report"], a["journal"], c["report"], c["journal"])
    assert not diff["deterministic"]
    assert "intents_admitted" in diff["metric_diff"]


def test_test_split_scored_once_guard(tmp_path):
    bench = SynthBenchmark()
    run_comparison(bench, tmp_path / "cmp", CONFIG, (SYMBOL,),
                   splits=("test",), armsets=("CASH",))
    assert (tmp_path / "cmp" / "test-COMPLETED.json").exists()
    try:
        run_comparison(bench, tmp_path / "cmp", CONFIG, (SYMBOL,),
                       splits=("test",), armsets=("CASH",))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected test-once guard to refuse")


class _FakeVision:
    """Minimal B5-shaped vision handle (in-memory, 2 UTC days of trades)."""

    kind = "vision-archive"

    def __init__(self):
        import datetime as dt
        self.manifest = {
            "dataset": {"name": "fake", "kind": "vision-archive",
                        "window_ist": ["2026-09-12", "2026-09-13"]},
            "source": [],
            "filters": {"symbols": {
                "BTCUSDT": {"tick": 0.1, "step": 0.001, "min_qty": 0.001,
                            "min_notional": 50.0}}},
        }
        base = int(dt.datetime(2026, 9, 11, 18, 30,
                               tzinfo=dt.timezone.utc).timestamp() * 1000)
        self._days = {}
        for day in ("2026-09-11", "2026-09-12", "2026-09-13"):
            self._days[day] = []
        # One trade per hour for 30h from IST-day start + heartbeats.
        for h in range(30):
            ts = base + h * 3600_000
            day = ("2026-09-11" if ts < base + 5.5 * 3600_000
                   else "2026-09-12" if ts < base + 29.5 * 3600_000
                   else "2026-09-13")
            self._days[day].append({
                "channel": "aggTrade", "symbol": "BTCUSDT",
                "exchange_ts_ms": ts, "local_recv_ms": ts,
                "payload": {"agg_id": h + 1, "price": 60000.0, "qty": 0.5,
                            "first_id": h + 1, "last_id": h + 1,
                            "trade_ts_ms": ts, "buyer_is_maker": False}})

    def events(self, symbol, day):
        assert symbol == "BTCUSDT"
        for e in self._days[day]:
            yield None  # B3 idle heartbeat
            yield e

    def coverage(self):
        return {"dataset": "fake", "kind": "vision-archive",
                "manifest_sha": "x" * 64, "sources": [], "gaps": [],
                "filters": self.manifest["filters"]}

    def manifest_sha(self):
        return "x" * 64


def test_day_ids_vision_ist_range():
    assert day_ids_for(_FakeVision()) == ("2026-09-12", "2026-09-13")


def test_day_ids_synth_ints():
    assert day_ids_for(SynthBenchmark()) == tuple(range(1, 31))


def test_ist_window_clips_to_calendar_day():
    evs, info = day_events_for(_FakeVision(), "BTCUSDT", "2026-09-12")
    assert info["calendar"] == "IST"
    assert info["utc_days"] == ["2026-09-11", "2026-09-12"]
    lo, hi = info["window_utc_ms"]
    assert all(e is not None for e in evs)  # heartbeats dropped
    assert all(lo <= e["exchange_ts_ms"] < hi for e in evs)
    assert len(evs) == 24  # exactly the day's hourly trades


def test_quotes_absent_on_trades_only_vision():
    assert not day_has_quotes(_FakeVision(), "BTCUSDT", "2026-09-12")


def test_filters_manifest_first_fallback_labeled():
    filt, origin = filters_for(_FakeVision(), "BTCUSDT")
    assert origin == "manifest-frozen"
    assert filt["tick_size"] == 0.1 and filt["price_precision"] == 1
    assert filt["size_precision"] == 3
    filt2, origin2 = filters_for(SynthBenchmark(), "XRPUSDT")
    assert origin2 == "frozen-assumed"


def test_preflight_passes_present_raises_absent(tmp_path):
    preflight(_FakeVision(), ("BTCUSDT",), ("2026-09-12",))
    preflight(SynthBenchmark(), ("XRPUSDT",), (1,))

    class _Empty:
        def coverage(self):
            return {"dataset": "empty", "sources": [
                {"local_exists": False}, {"local_exists": False}]}
    try:
        preflight(_Empty(), ("BTCUSDT",), ("2026-09-12",))
    except FileNotFoundError as exc:
        assert "fallback" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_default_symbols_is_btc_eth_pair():
    both = SimpleNamespace(manifest={"dataset": {"symbols": ["BTCUSDT",
                                                             "ETHUSDT"]}})
    assert _default_symbols(both) == ["BTCUSDT", "ETHUSDT"]
    one = SimpleNamespace(manifest={"dataset": {"symbols": ["BTCUSDT"]}})
    assert _default_symbols(one) == ["BTCUSDT"]
    other = SimpleNamespace(manifest={"dataset": {"symbols": ["XRPUSDT"]}})
    assert _default_symbols(other) == ["XRPUSDT"]
    bare = SimpleNamespace(manifest={"dataset": {}})
    assert _default_symbols(bare) == ["BTCUSDT"]


def test_mechanism_split_covers_all_days(tmp_path):
    manifest = prepare_split_capture(_FakeVision(), MECHANISM_SPLIT,
                                     tmp_path / "cap", ("BTCUSDT",))
    assert [d["day"] for d in manifest["day_manifest"]] == [
        "2026-09-12", "2026-09-13"]
    assert manifest["n_events"] == 30


def test_partition_checkpoint_reused_across_runs(tmp_path):
    bench = SynthBenchmark()
    path = tmp_path / "parts" / "synth_quotes_XRPUSDT_1.jsonl"
    first = build_partition(bench, SYMBOL, 1, path)
    assert first["reused"] is False
    assert first["n_events"] == 1200
    assert first["channels"] == {"aggTrade": 600, "bookTicker": 600}
    second = build_partition(bench, SYMBOL, 1, path)
    assert second["reused"] is True
    assert second["sha256"] == first["sha256"]
    forced = build_partition(bench, SYMBOL, 1, path, force=True)
    assert forced["reused"] is False
    assert forced["sha256"] == first["sha256"]


def test_partitions_shared_across_spread_profiles(tmp_path):
    bench = SynthBenchmark(dataset_id="synth_noquotes")
    parts = tmp_path / "parts"
    manifest_a = prepare_split_capture(bench, "dev", tmp_path / "cap_a",
                                       (SYMBOL,), SpreadProfile(),
                                       partition_dir=parts)
    manifest_b = prepare_split_capture(bench, "dev", tmp_path / "cap_b",
                                       (SYMBOL,), None,
                                       partition_dir=parts)
    assert all(p["reused"] is False
               for d in manifest_a["day_manifest"]
               for p in [d["partition"]])
    assert all(p["reused"] is True
               for d in manifest_b["day_manifest"]
               for p in [d["partition"]])
    assert all(d["spread_profile"] == PROFILE_ID
               for d in manifest_a["day_manifest"])
    assert all(d["spread_profile"] is None
               for d in manifest_b["day_manifest"])
    lines_a = (tmp_path / "cap_a" / "events.jsonl").read_text().splitlines()
    lines_b = (tmp_path / "cap_b" / "events.jsonl").read_text().splitlines()
    assert len(lines_a) == 15 * 1200 and len(lines_b) == 15 * 600


def test_assembly_max_events_never_reads_tail(tmp_path, monkeypatch):
    bench = SynthBenchmark()
    parts = tmp_path / "parts"
    partitions = [build_partition(bench, SYMBOL, day,
                                  parts / f"synth_quotes_{SYMBOL}_{day}.jsonl")
                  for day in range(1, 6)]
    consumed: list[int] = [0]
    real_events = backtest_mod._partition_events

    def counting(path):
        for event in real_events(path):
            consumed[0] += 1
            yield event

    monkeypatch.setattr(backtest_mod, "_partition_events", counting)
    manifest = assemble_split_capture(partitions, "probe", tmp_path / "cap",
                                      (SYMBOL,), bench, None, 100)
    assert manifest["n_events"] == 100
    assert manifest["truncated_prefix"] is True
    # Five 1200-event partitions merged: heads advance in lockstep, so a
    # 100-event prefix touches a few hundred lines, never all 6000.
    assert consumed[0] < 6000 // 2
    trailing = json.loads(
        (tmp_path / "cap" / "events.jsonl").read_text().splitlines()[-1])
    assert trailing["seq"] == 100


def test_day_has_quotes_is_day_scoped_captured():
    import datetime as _dt

    base = _dt.datetime(2026, 9, 12, tzinfo=_dt.timezone.utc).timestamp()
    manifest = {"source": [{
        "symbol": "BTCUSDT", "channels": ["aggTrade", "bookTicker"],
        "ts_min_ms": int(base * 1000),
        "ts_max_ms": int(base * 1000) + 3_600_000}]}
    handle = SimpleNamespace(kind="captured-runs", manifest=manifest)
    assert day_has_quotes(handle, "BTCUSDT", "2026-09-12") is True
    assert day_has_quotes(handle, "BTCUSDT", "2026-09-13") is False
    assert day_has_quotes(handle, "ETHUSDT", "2026-09-12") is False


def test_day_has_quotes_is_day_scoped_vision():
    manifest = {"source": [
        {"symbol": "BTCUSDT", "channel": "bookTicker",
         "day": "2026-09-12"},
        {"symbol": "BTCUSDT", "channel": "aggTrade",
         "day": "2026-09-13"},
    ]}
    handle = SimpleNamespace(kind="vision-archive", manifest=manifest)
    # 2026-09-13 IST spans UTC 09-12/13: the 09-12 quote entry counts.
    assert day_has_quotes(handle, "BTCUSDT", "2026-09-13") is True
    # 2026-09-12 IST spans UTC 09-11/12: aggTrade-only UTC day outside it.
    assert day_has_quotes(handle, "BTCUSDT", "2026-09-14") is False


def test_max_events_keeps_causal_labeled_prefix(tmp_path):
    bench = SynthBenchmark()
    manifest = prepare_split_capture(bench, "dev", tmp_path / "cap",
                                     (SYMBOL,), None, 500)
    assert manifest["n_events"] == 500
    assert manifest["truncated_prefix"] is True
    assert manifest["max_events"] == 500
    lines = (tmp_path / "cap" / "events.jsonl").read_text().splitlines()
    assert len(lines) == 500
    first = json.loads(lines[0])
    assert first["seq"] == 1  # renumbered from the prefix start


def test_venue_seq_is_event_identity(tmp_path):
    base = {"channel": "bookTicker", "symbol": "BTCUSDT", "source": "v",
            "exchange_ts_ms": 1_700_000_000_000,
            "payload": {"bid": 1.0, "ask": 1.1}}
    first = {**base, "venue_seq": 101}
    distinct = {**base, "venue_seq": 102}
    changed = {**base, "venue_seq": 101,
               "payload": {"bid": 2.0, "ask": 2.1}}
    assert OverlapDedup().fingerprint(first) != \
        OverlapDedup().fingerprint(distinct)
    dedup = OverlapDedup()
    assert dedup.check(first) == "keep"
    assert dedup.check(distinct) == "keep"  # distinct identity: both kept
    assert dedup.check(changed) == "conflict-drop"  # same 101, new body
    assert dedup.conflicts == 1
    zero = OverlapDedup()  # venue_seq 0/None = "no sequence", never identity
    assert zero.check({**base, "venue_seq": 0}) == "keep"
    assert zero.check({**base}) == "drop"  # same body still dedups
    assert zero.conflicts == 0


def _evt(symbol="BTCUSDT", channel="aggTrade", ts=1_700_000_000_000,
         source="v", **payload):
    base = {"price": 100.0, "qty": 0.5} if channel == "aggTrade" else {
        "bid": 99.0, "ask": 101.0}
    base.update(payload)
    return {"channel": channel, "symbol": symbol, "source": source,
            "exchange_ts_ms": ts, "payload": base}


def test_dedup_keeps_cross_symbol_identical_payloads():
    from cryptobot.research.backtest import OverlapDedup
    d = OverlapDedup()
    assert d.check(_evt(symbol="BTCUSDT")) == "keep"
    # Review's case: another symbol, byte-identical payload+ts -> keep.
    assert d.check(_evt(symbol="ETHUSDT")) == "keep"
    assert d.check(_evt(source="other-venue")) == "keep"
    assert d.dropped == 0 and d.conflicts == 0


def test_dedup_drops_exact_overlap_repeats():
    from cryptobot.research.backtest import OverlapDedup
    d = OverlapDedup()
    assert d.check(_evt()) == "keep"
    assert d.check(_evt()) == "drop"
    assert d.dropped == 1


def test_dedup_detects_conflicting_duplicates_keep_first():
    from cryptobot.research.backtest import OverlapDedup
    d = OverlapDedup()
    assert d.check(_evt(agg_id=7, price=100.0)) == "keep"
    # Same venue identity, different body -> conflict, first kept.
    assert d.check(_evt(agg_id=7, price=101.0)) == "conflict-drop"
    assert d.conflicts == 1 and len(d.examples) == 1


def test_dedup_preserves_legitimate_repeats():
    from cryptobot.research.backtest import OverlapDedup
    d = OverlapDedup()
    # Distinct trades, same ms/price/qty, different ids -> both kept.
    assert d.check(_evt(agg_id=1)) == "keep"
    assert d.check(_evt(agg_id=2)) == "keep"
    # Same-ms quote updates without identity, different bodies -> kept.
    assert d.check(_evt(channel="bookTicker", bid=99.0)) == "keep"
    assert d.check(_evt(channel="bookTicker", bid=99.5)) == "keep"
    assert d.dropped == 0 and d.conflicts == 0


def test_dedup_cache_bounded_by_time_window():
    from cryptobot.research.backtest import OverlapDedup
    d = OverlapDedup(window_ms=1000)
    for i in range(10):
        d.check(_evt(ts=1_700_000_000_000 + i * 5000, agg_id=i))
    assert len(d._seen) <= 2  # only the trailing window survives


def test_short_data_refuses_frozen_splits(tmp_path):
    try:
        prepare_split_capture(_FakeVision(), "dev", tmp_path / "cap",
                              ("BTCUSDT",))
    except ValueError as exc:
        assert MECHANISM_SPLIT in str(exc)
    else:
        raise AssertionError("expected ValueError for short data")


def test_cards_cover_b6_fields():
    required = ["## Inputs", "## Setup", "## Trigger", "## Rejects",
                "## Entry bounds", "## Invalidation", "## Stop / target",
                "## Holding", "## Units"]
    for name in ("S1", "S2", "S3", "S4", "S5"):
        text = Path(f"specs/cards/{name}.md").read_text()
        for section in required:
            assert section in text, f"{name} missing {section}"
    s5 = Path("specs/cards/S5.md").read_text()
    assert "research-spread-profile" in s5 and "B4 consumption contract" in s5
