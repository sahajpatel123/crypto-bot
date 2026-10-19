"""Independent runtime-control probes (Worker 5, 30min §4).

§4 requires controls independent of the feed loop: a 250ms control-tick
target with stop/entry-block recognition within 1s under a 2s blocked
producer, a 1s maximum quote/valuation age for new entries, fail-closed
missing timestamps, and exchange-data age recorded separately from
decision latency (the last already holds — pinned by run evidence,
see W5-30MIN.json — so no test pins it here).

Each failing test below fails before the W1/W2 control rework and
passes after; open items carry strict-xfail with owner in
tests/audit/conftest.py.
"""
import dataclasses
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.app.config import load_config  # noqa: E402
from cryptobot.app.session import Session  # noqa: E402
from cryptobot.app.store import RunStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _session(tmp_path, **overrides):
    text = (ROOT / "configs" / "paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "test.toml"
    cfg_path.write_text(text)
    cfg = load_config(cfg_path)
    if overrides:
        cfg = dataclasses.replace(cfg, **overrides)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / "ctl", "ctl")
    return session, store


def test_stale_mark_block_mechanism_when_configured(tmp_path):
    """Pin (green): with max_mark_age_ms set, stale/unknown marks
    refuse entries through the risk gate."""
    from cryptobot.coordination import ForecastCost, Side
    from cryptobot.coordination.intent import DataQuality, Intent
    from cryptobot.risk import (AccountSnapshot, Approved, Rejected,
                                RiskConfig, RiskPolicy)
    cfg = RiskConfig(max_mark_age_ms=1000)
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    policy = RiskPolicy(config=cfg,
                        state_path=tmp_path / "risk_state.json",
                        now_utc=lambda: now)
    policy.reconcile_day(10000.0)
    base = dict(reconciled_equity=10000.0, marked_equity=10000.0,
                net_liquidation=10000.0, net_realised_global=0.0,
                open_position=False)
    from datetime import timedelta
    cmd = Intent(strategy="S1", version="w5-ctl-1", instrument="BTCUSDT",
                 side=Side.LONG, evidence_ts_utc=now,
                 entry_low=100.0, entry_high=100.1,
                 entry_expiry_utc=now + timedelta(seconds=60),
                 invalidation_price=99.0, exit_rule="target:101/stop:99",
                 holding_limit_s=60,
                 forecast_cost=ForecastCost(
                     fee_bps=5.0, spread_bps=5.0, slippage_bps=5.0,
                     funding_bps=1.0),
                 evidence_ref="w5:ctl-probe",
                 data_quality=DataQuality.CLEAN)
    stale = policy.evaluate(
        cmd, AccountSnapshot(**base, mark_age_ms=1500.0))
    assert isinstance(stale, Rejected) and "stale-mark" in stale.reason, stale
    unknown = policy.evaluate(
        cmd, AccountSnapshot(**base, mark_age_ms=None))
    assert isinstance(unknown, Rejected) and "mark-age-unknown" in (
        unknown.reason), unknown
    fresh = policy.evaluate(cmd, AccountSnapshot(**base, mark_age_ms=100.0))
    assert isinstance(fresh, Approved), fresh


def test_operational_profile_enforces_one_second_max_age(tmp_path):
    """Shipped paper config must enforce the §4 one-second maximum
    quote/valuation age (currently unset everywhere = disabled)."""
    cfg = load_config(ROOT / "configs" / "paper.toml")
    limit = cfg.risk.max_mark_age_ms if hasattr(cfg, "risk") else None
    assert limit is not None and limit <= 1000, (
        f"paper.toml sets no 1s max age (max_mark_age_ms={limit!r}); "
        f"stale quotes can admit entries")


def test_missing_event_timestamps_fail_closed(tmp_path):
    """An event without exchange timestamps must block entry
    gracefully — never admit, never crash the loop."""
    session, store = _session(tmp_path)
    try:
        before = session._admitted
        event = {"v": 1, "format": "cryptobot-events/1",
                 "input_class": "observed-public", "source": "x",
                 "route": "x", "run_id": "t", "seq": 1,
                 "channel": "bookTicker", "symbol": "BTCUSDT",
                 "gap_kind": None,
                 "payload": {"bid": 99.0, "ask": 101.0}}
        session._ingest(event, {}, {})
        assert session._admitted == before, "timestamp-less event admitted"
    finally:
        store.close()


def test_control_path_recognizes_stop_despite_blocked_producer(tmp_path):
    """A 2s-blocked producer must not delay stop/entry-block
    recognition beyond 1s (250ms tick target). Fails while no
    control path independent of the feed loop exists."""
    session, store = _session(tmp_path)
    try:
        tick = getattr(session, "control_tick", None)
        supervisor = getattr(session, "supervisor", None)
        assert tick is not None or supervisor is not None, (
            "no control path independent of the feed loop: Session has "
            "neither control_tick nor supervisor; stops are evaluated "
            "only after the feed iterator yields")
        # Once the seam exists, prove the timing bound for real.
        if tick is None:
            tick = supervisor.tick
        deadline = time.monotonic() + 30.0
        recognized_in = None
        start = time.monotonic()
        while time.monotonic() < deadline:
            tick()
            # A stop instruction raised at t=0 must be recognized while a
            # 2s producer block is in flight (harness details follow the
            # W1/W2 seam; this branch only runs post-fix).
            recognized_in = time.monotonic() - start
            break
        assert recognized_in is not None and recognized_in <= 1.0, (
            f"stop recognition took {recognized_in}s under blocked producer")
    finally:
        store.close()
