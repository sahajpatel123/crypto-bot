"""Protection replay test (Worker 4, W4-24H).

Scripted scenario through ProtectionRuntime: a quiet entry, a CPI
pre/in-window block, an anomaly halt on a quiet calendar, cooldown, and
recovery — then replay_evidence proves the log reproduces every decision.
This is the committed form of the W4-24H gated-window/anomaly replay demo.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cryptobot.events as _evpkg  # noqa: E402
from cryptobot.events.anomaly import (AnomalyBaseline,  # noqa: E402
                                      AnomalyReading)
from cryptobot.events.evidence import replay_evidence  # noqa: E402
from cryptobot.events.freshness import (FreshnessTracker,  # noqa: E402
                                        HttpResponse)
from cryptobot.events.runtime import ProtectionRuntime  # noqa: E402
from cryptobot.events.sources import CpiSource, FomcSource  # noqa: E402
from cryptobot.events.store import EventStore  # noqa: E402

CANNED = Path(_evpkg.__file__).parent / "fixtures" / "canned"


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


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


def _scenario(runtime):
    """Returns the (label, blocked, reason) trail."""
    trail = []

    def entry(ts, reading=None):
        decision = runtime.check_entry(ts, reading or AnomalyReading())
        trail.append((ts.isoformat(), decision.blocked, decision.reason))
        return decision

    def tick(ts, reading):
        runtime.observe(ts, reading)

    t0 = _utc(2026, 10, 14, 11, 0)
    entry(t0)  # quiet: allow
    entry(_utc(2026, 10, 14, 12, 20))  # CPI pre-window: block
    entry(_utc(2026, 10, 14, 12, 30))  # CPI release: block
    entry(_utc(2026, 10, 14, 13, 0))  # clear again: allow
    tick(_utc(2026, 10, 14, 13, 1),
         AnomalyReading(latency_ms=9000.0))  # feed stalls
    entry(_utc(2026, 10, 14, 13, 2))  # anomaly halt: block
    tick(_utc(2026, 10, 14, 13, 3), AnomalyReading(latency_ms=100.0))
    tick(_utc(2026, 10, 14, 13, 4), AnomalyReading(latency_ms=100.0))
    tick(_utc(2026, 10, 14, 13, 5), AnomalyReading(latency_ms=100.0))
    entry(_utc(2026, 10, 14, 13, 6))  # cooldown: still reject
    return trail


def test_scenario_shows_gate_and_anomaly(tmp_path):
    runtime = ProtectionRuntime(
        _verified_store(tmp_path, _utc(2026, 10, 14, 11, 0)),
        evidence_path=tmp_path / "ev.jsonl")
    trail = _scenario(runtime)
    assert trail[0][1:] == (False, "protect:clear")
    assert trail[1][1:] == (True, "event:pre-window:CPI-2026-10-14")
    assert trail[2][1:] == (True, "event:in-window:CPI-2026-10-14")
    assert trail[3][1:] == (False, "protect:clear")
    assert trail[4][1:] == (True, "anomaly:halt-entries:latency")
    assert trail[5][1:] == (True, "anomaly:cooldown")


def test_evidence_replay_reproduces_scenario(tmp_path):
    runtime = ProtectionRuntime(
        _verified_store(tmp_path, _utc(2026, 10, 14, 11, 0)),
        evidence_path=tmp_path / "ev.jsonl")
    first_trail = _scenario(runtime)

    def rebuild(header):
        assert header["schedule"]["events"] == 28
        assert header["profile"] == "protected-operational"
        return ProtectionRuntime(
            _verified_store(tmp_path, _utc(2026, 10, 14, 11, 0)),
            evidence_path=None)

    report = replay_evidence(tmp_path / "ev.jsonl", rebuild)
    assert report["ok"] is True
    assert report["compared"] == 10  # 6 entry-checks + 4 observations
    assert report["mismatches"] == []
    assert len(first_trail) == 6
