"""Protection runtime + evidence tests (Worker 4, W4-24H)."""
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cryptobot.events as _evpkg  # noqa: E402
from cryptobot.events.anomaly import AnomalyBaseline, AnomalyReading  # noqa: E402
from cryptobot.events.evidence import read_evidence, replay_evidence  # noqa: E402
from cryptobot.events.freshness import FreshnessTracker, HttpResponse  # noqa: E402
from cryptobot.events.runtime import ProtectionRuntime  # noqa: E402
from cryptobot.events.sources import CpiSource, FomcSource  # noqa: E402
from cryptobot.events.store import EventStore  # noqa: E402

CANNED = Path(_evpkg.__file__).parent / "fixtures" / "canned"
T0 = datetime(2026, 10, 12, 13, 0, tzinfo=UTC)


def _canned(url, timeout_s=20):
    name = ("fomc_page_2026.txt" if "federalreserve" in url
            else "bls_cpi_page_2026.txt")
    return HttpResponse(status=200, body=(CANNED / name).read_bytes(),
                        url=url)


def _verified_store(tmp_path, now):
    store = EventStore()
    tracker = FreshnessTracker(tmp_path / "state.json",
                               [FomcSource(), CpiSource()])
    tracker.local_load(store, now)
    tracker.refresh_once(store, _canned, now)
    return store


def test_clear_entry_passes_and_logs(tmp_path):
    runtime = ProtectionRuntime(_verified_store(tmp_path, T0),
                                evidence_path=tmp_path / "ev.jsonl")
    decision = runtime.check_entry(T0)
    assert decision.blocked is False
    assert decision.reason == "protect:clear"
    assert decision.seq == 1
    header, records = read_evidence(tmp_path / "ev.jsonl")
    assert header["profile"] == "protected-operational"
    assert records[0]["kind"] == "entry-check"
    assert records[0]["final"]["blocked"] is False


def test_gate_block_wins_and_logs_inputs(tmp_path):
    cpi = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    store = EventStore()
    tracker = FreshnessTracker(tmp_path / "state.json",
                               [FomcSource(), CpiSource()])
    tracker.local_load(store, T0)
    tracker.refresh_once(store, _canned, T0)
    runtime = ProtectionRuntime(store,
                                evidence_path=tmp_path / "ev.jsonl")
    decision = runtime.check_entry(cpi, AnomalyReading(latency_ms=50.0))
    assert decision.blocked is True
    assert decision.reason == "event:in-window:CPI-2026-10-14"
    _, records = read_evidence(tmp_path / "ev.jsonl")
    assert records[0]["inputs"]["latency_ms"] == 50.0
    assert records[0]["gate"]["event_ids"] == ["CPI-2026-10-14"]


def test_anomaly_action_blocks_quiet_calendar(tmp_path):
    runtime = ProtectionRuntime(_verified_store(tmp_path, T0),
                                evidence_path=tmp_path / "ev.jsonl")
    decision = runtime.check_entry(
        T0, AnomalyReading(latency_ms=5000.0), AnomalyBaseline())
    assert decision.blocked is True
    assert decision.reason == "anomaly:halt-entries:latency"
    assert decision.anomaly_action == "halt-entries"


def test_advisory_mode_logs_would_block_without_enforcing(tmp_path):
    cpi = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    store = EventStore()
    tracker = FreshnessTracker(tmp_path / "state.json",
                               [FomcSource(), CpiSource()])
    tracker.local_load(store, T0)
    tracker.refresh_once(store, _canned, T0)
    runtime = ProtectionRuntime(store,
                                evidence_path=tmp_path / "ev.jsonl",
                                advisory_only=True)
    decision = runtime.check_entry(cpi)
    assert decision.blocked is False
    assert decision.advisory is True
    assert decision.reason.startswith("advisory-would-block:event:")


def test_observe_folds_without_blocking(tmp_path):
    runtime = ProtectionRuntime(_verified_store(tmp_path, T0),
                                evidence_path=tmp_path / "ev.jsonl")
    first = runtime.observe(T0, AnomalyReading(spread_bps=30.0))
    assert first.action == "reject-entries"
    _, records = read_evidence(tmp_path / "ev.jsonl")
    assert records[0]["kind"] == "observation"
    assert records[0]["anomaly"]["triggered"] == ["spread"]


def test_replay_reproduces_decisions(tmp_path):
    store = _verified_store(tmp_path, T0)
    runtime = ProtectionRuntime(store,
                                evidence_path=tmp_path / "ev.jsonl")
    runtime.check_entry(T0)
    runtime.observe(T0, AnomalyReading(spread_bps=30.0))
    runtime.check_entry(T0, AnomalyReading(spread_bps=5.0))

    def rebuild(header):
        assert header["schedule"]["events"] == 28
        return ProtectionRuntime(_verified_store(tmp_path, T0),
                                 evidence_path=None)

    report = replay_evidence(tmp_path / "ev.jsonl", rebuild)
    assert report["ok"] is True
    assert report["compared"] == 3
    assert report["mismatches"] == []


def test_replay_detects_tampering(tmp_path):
    store = _verified_store(tmp_path, T0)
    runtime = ProtectionRuntime(store,
                                evidence_path=tmp_path / "ev.jsonl")
    runtime.check_entry(T0, AnomalyReading(latency_ms=5000.0))
    lines = (tmp_path / "ev.jsonl").read_text().splitlines()
    tampered = lines[1].replace("halt-entries", "allow")
    (tmp_path / "ev.jsonl").write_text(
        "\n".join([lines[0], tampered]) + "\n")

    def rebuild(header):
        return ProtectionRuntime(_verified_store(tmp_path, T0),
                                 evidence_path=None)

    report = replay_evidence(tmp_path / "ev.jsonl", rebuild)
    assert report["ok"] is False
    assert len(report["mismatches"]) == 1
