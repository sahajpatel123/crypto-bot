"""Backtest harness tests (Worker 1, Q-007). Session-driven cells."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.backtest import (
    ARM_SETS,
    DEV_DAYS,
    MECHANISM_SPLIT,
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
    assert set(ARM_SETS) == {"S1", "S2", "S3", "S4", "S5", "COMBINED", "CASH"}
    assert ARM_SETS["CASH"] == ()
    assert ARM_SETS["COMBINED"] == ("S1", "S2", "S3", "S4", "S5")


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
    assert all(not d["quotes_observed"] for d in manifest["day_manifest"])
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
    assert all(not d["quotes_observed"] for d in manifest["day_manifest"])


def _tiny_capture(path: Path) -> Path:
    # Day 1 (impulse-long) only: fast Session cell with real fills.
    bench = SynthBenchmark()
    path.mkdir(parents=True, exist_ok=True)
    events = []
    for seq, e in enumerate(bench.events(SYMBOL, 1), start=1):
        e["seq"] = seq
        e["local_mono_ns"] = seq
        events.append(e)
    (path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n")
    return path


def test_run_cell_through_session_with_fills(tmp_path):
    cap = _tiny_capture(tmp_path / "cap")
    cell = run_cell(CONFIG, cap, ("S1",), tmp_path / "run", "cell-s1",
                    (SYMBOL,))
    report = cell["report"]
    assert report["execution_model"] == "nautilus-paper"
    assert report["events_seen"] == 1200
    assert report["intents_admitted"] >= 1
    fills = fills_signature(cell["journal"])
    assert len(fills) >= 2  # entry + protective/time exit legs
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
    assert diff["n_fills"] >= 2
    assert diff["fills_equal"] and diff["curve_equal"]
    assert diff["metrics_equal"] and diff["deterministic"]
    assert curve_signature(a["journal"]) == curve_signature(b["journal"])


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


def test_mechanism_split_covers_all_days(tmp_path):
    manifest = prepare_split_capture(_FakeVision(), MECHANISM_SPLIT,
                                     tmp_path / "cap", ("BTCUSDT",))
    assert [d["day"] for d in manifest["day_manifest"]] == [
        "2026-09-12", "2026-09-13"]
    assert manifest["n_events"] == 30


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
