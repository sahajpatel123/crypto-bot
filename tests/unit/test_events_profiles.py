"""Event profile tests (Worker 4, W4-24H). Protected vs research-only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cryptobot.events as _evpkg  # noqa: E402
from cryptobot.events.profiles import (  # noqa: E402
    OperationalProfile,
    ReplayCutoff,
    ResearchProfile,
    load_profile,
)
from cryptobot.events.sources import FomcSource, apply_snapshot  # noqa: E402
from cryptobot.events.store import EventStore  # noqa: E402
from cryptobot.events.timezones import parse_iso_utc  # noqa: E402

REPO = Path(_evpkg.__file__).resolve().parents[3]


def _toml(tmp_path, body):
    path = tmp_path / "t.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_protected_reference_profile_loads():
    profile = load_profile(REPO / "configs" / "paper-protected.toml")
    assert isinstance(profile, OperationalProfile)
    assert profile.posture == "protected-operational"
    assert profile.require_verified is True
    assert profile.anomaly_enabled is True
    assert profile.advisory_only is False
    assert profile.gate.pre_buffer_s == 900
    assert profile.anomaly.latency_ms == 2000.0


def test_stock_configs_are_explicitly_research_only():
    for name in ("paper.toml", "r2.toml", "r3.toml"):
        profile = load_profile(REPO / "configs" / name)
        assert isinstance(profile, ResearchProfile), name
        assert profile.posture == "research-only"
        assert profile.advisory_only is True
        assert "research-only" in profile.reason


def test_events_on_without_verification(tmp_path):
    path = _toml(tmp_path, "[run]\nevents_enabled = true\nmode = \"paper\"\n"
                           "[events]\nenable_anomaly = true\n")
    profile = load_profile(path)
    assert isinstance(profile, ResearchProfile)
    assert "verified freshness not required" in profile.reason


def test_events_on_without_anomaly_stays_research(tmp_path):
    path = _toml(tmp_path, "[run]\nevents_enabled = true\nmode = \"paper\"\n"
                           "[events]\nrequire_verified_freshness = true\n")
    profile = load_profile(path)
    assert isinstance(profile, ResearchProfile)
    assert "anomaly decisions off" in profile.reason


def test_advisory_flag_forces_research(tmp_path):
    path = _toml(tmp_path, "[run]\nevents_enabled = true\nmode = \"paper\"\n"
                           "[events]\nrequire_verified_freshness = true\n"
                           "enable_anomaly = true\nadvisory_only = true\n")
    profile = load_profile(path)
    assert isinstance(profile, ResearchProfile)
    assert "advisory_only=true" in profile.reason


def test_replay_without_cutoff_stays_research(tmp_path):
    path = _toml(tmp_path, "[run]\nevents_enabled = true\nmode = \"replay\"\n"
                           "[events]\nrequire_verified_freshness = true\n"
                           "enable_anomaly = true\n")
    profile = load_profile(path)
    assert isinstance(profile, ResearchProfile)
    assert "first_seen cutoff" in profile.reason


def test_bad_values_fail_closed(tmp_path):
    path = _toml(tmp_path, "[run]\nevents_enabled = true\nmode = \"paper\"\n"
                           "[events]\nrequire_verified_freshness = true\n"
                           "enable_anomaly = true\ncache_ttl_days = 0\n")
    with pytest.raises(ValueError, match="positive"):
        load_profile(path)
    missing = tmp_path / "nope.toml"
    with pytest.raises(ValueError, match="unreadable"):
        load_profile(missing)


def test_replay_cutoff_drops_future_knowledge():
    store = EventStore()
    apply_snapshot(store, FomcSource().load(
        parse_iso_utc("2026-10-12T13:10:00+00:00")))
    assert len(store) == 16
    # Fixtures were first seen Oct 12: a September replay knows nothing.
    filtered, counts = ReplayCutoff.apply(
        store, parse_iso_utc("2026-09-01T00:00:00+00:00"))
    assert counts == {"kept": 0, "dropped_future": 16}
    assert len(filtered) == 0
    filtered, counts = ReplayCutoff.apply(
        store, parse_iso_utc("2026-10-12T14:00:00+00:00"))
    assert counts == {"kept": 16, "dropped_future": 0}
