"""Live-safety row 9: every operator-alert trigger reaches the sink, offline.

The runtime records each alert durably per run and delivers it through
``cryptobot.monitoring.alerts.AlertSink`` (memory/log/webhook). These
tests inject a MemorySink, so the check needs no network, no credentials
and no venue: a kill, a breaching loss limit, a stream outage and an
order rejection each produce an operator-visible alert.

Before this wiring the sinks existed but nothing called them — alerts
stayed in a per-process list, and stream outage / order rejection /
daily-loss breach raised no alert at all.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.engine import EngineEvent, EngineReject
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.monitoring.alerts import MemorySink
from cryptobot.risk.types import AccountSnapshot


class _StubEngine:
    """Minimal engine double: no orders, no venue, records halt mirrors."""

    model_label = "alert-stub"
    assumptions = ("stub: alerts",)

    def __init__(self) -> None:
        self.exit_only: list[tuple[bool, str]] = []

    def poll(self) -> list:
        return []

    def open_orders(self) -> list:
        return []

    def set_exit_only(self, halted: bool, reason: str = "") -> None:
        self.exit_only.append((halted, reason))

    def cancel(self, client_id: str, reason: str = "") -> None:
        return None


class _HaltedStream:
    halted = True

    def halt_reasons(self) -> tuple[str, ...]:
        return ("stream-gap",)


def _session(tmp_path: Path, sink: MemorySink | None) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    return Session(load_config(cfg_path), store, tmp_path / "run",
                   "alert-run", engine=_StubEngine(), alert_sink=sink)


def _sent_kinds(sink: MemorySink) -> list[str]:
    return [kind for kind, _ in sink.sent]


def _account(netliq: float) -> AccountSnapshot:
    return AccountSnapshot(
        reconciled_equity=netliq, marked_equity=netliq,
        net_liquidation=netliq, net_realised_global=0.0,
        open_position=False, available_margin_usdt=netliq,
        mark_age_ms=0.0)


def test_kill_switch_alert_reaches_the_sink(tmp_path):
    """Safe-mode kill (halt + flatten + alert) delivers 'safe-mode'."""
    sink = MemorySink()
    session = _session(tmp_path, sink)
    session._flatten = lambda reason: None  # type: ignore[method-assign]
    out = session.enter_safe_mode("operator-kill")
    assert out["flatten_attempted"] is True
    assert _sent_kinds(sink) == ["safe-mode"]
    kind, payload = sink.sent[-1]
    assert payload["reason"] == "operator-kill"
    # Durable copy in the run record survives a missing/failing sink.
    assert session.alerts[-1]["kind"] == "safe-mode"


def test_emergency_loss_limit_breach_alerts(tmp_path):
    """A 1.5% loss breaches the 1% emergency stop and alerts the operator."""
    sink = MemorySink()
    session = _session(tmp_path, sink)
    session.policy.reconcile_day(10_000.0, 0.0)
    account = _account(9_850.0)
    health = session.policy.monitor_tick(session.now_utc(), account)
    assert "halt:emergency" in health.reasons, health
    session._snapshot_account = lambda *a, **k: account  # type: ignore[method-assign]
    session._flatten = lambda reason: None  # type: ignore[method-assign]
    session._run_stop_actions()
    assert "emergency-stop" in _sent_kinds(sink), sink.sent
    _, payload = sink.sent[-1]
    assert payload["reason"] == "halt:emergency:exposure-reduction"
    assert "alert_operator" in payload["actions"]
    # One alert per latch, not one per supervision tick.
    session._run_stop_actions()
    assert _sent_kinds(sink).count("emergency-stop") == 1


def test_daily_loss_limit_breach_alerts_once_per_day(tmp_path):
    """The 0.5% operating (daily) stop alerts once, and only once, per day."""
    sink = MemorySink()
    session = _session(tmp_path, sink)
    session.policy.reconcile_day(10_000.0, 0.0)
    account = _account(9_930.0)  # 0.7% loss: operating stop, below emergency
    health = session.policy.monitor_tick(session.now_utc(), account)
    assert "halt:operating-stop" in health.reasons, health
    assert "halt:emergency" not in health.reasons
    session._snapshot_account = lambda *a, **k: account  # type: ignore[method-assign]
    session._flatten = lambda reason: None  # type: ignore[method-assign]
    session._run_stop_actions()
    session._run_stop_actions()
    assert _sent_kinds(sink).count("daily-stop") == 1, sink.sent


def test_stream_outage_alerts_and_blocks_entries(tmp_path):
    """A halt-flagged user stream blocks entries and alerts once per reason set."""
    sink = MemorySink()
    session = _session(tmp_path, sink)
    session._user_stream_attachment = _HaltedStream()
    assert session._admission_hold() == "stream:stream-gap"
    assert _sent_kinds(sink) == ["stream-outage"]
    _, payload = sink.sent[-1]
    assert payload["reasons"] == ["stream-gap"]
    # Repeated supervision ticks inside the same outage do not re-alert.
    assert session._admission_hold() == "stream:stream-gap"
    assert _sent_kinds(sink).count("stream-outage") == 1


def test_order_rejection_alerts_once_per_event(tmp_path):
    """A venue order rejection is operator-visible; redelivery is deduped."""
    sink = MemorySink()
    session = _session(tmp_path, sink)
    ts = session.now_utc()
    reject = EngineReject(client_order_id="cid-1", instrument="BTCUSDT",
                          reason="venue:-2010:insufficient-margin",
                          ts_utc=ts)
    event = EngineEvent("reject", reject, ts)
    assert session._apply_engine_event(event) == "recorded"
    assert _sent_kinds(sink) == ["order-rejected"]
    assert sink.sent[-1][1]["reason"] == "venue:-2010:insufficient-margin"
    assert session._apply_engine_event(event) == "duplicate"
    assert _sent_kinds(sink).count("order-rejected") == 1


def test_a_failing_sink_never_breaks_the_run(tmp_path):
    """Alert delivery is best-effort: a broken webhook cannot stop a flatten."""
    class _Boom(MemorySink):
        def send(self, kind, payload):
            raise RuntimeError("relay down")

    session = _session(tmp_path, _Boom())
    session._flatten = lambda reason: None  # type: ignore[method-assign]
    out = session.enter_safe_mode("venue-down")
    assert out["flatten_attempted"] is True
    assert session.alerts[-1]["kind"] == "safe-mode"


def test_alert_record_is_written_as_a_run_checkpoint(tmp_path):
    """The durable run record (checkpoints) carries the same alert offline."""
    sink = MemorySink()
    session = _session(tmp_path, sink)
    ts = session.now_utc() + timedelta(seconds=1)
    reject = EngineReject(client_order_id="cid-2", instrument="BTCUSDT",
                          reason="venue:-2013", ts_utc=ts)
    session._apply_engine_event(EngineEvent("reject", reject, ts))
    with session.store._db:  # noqa: SLF001 — read the durable record
        rows = session.store._db.execute(  # noqa: SLF001
            "SELECT kind FROM checkpoints WHERE run_id=?",
            (session.run_id,)).fetchall()
    assert ("order-rejected",) in rows
