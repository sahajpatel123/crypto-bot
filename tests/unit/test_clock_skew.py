"""F2.6: continuous clock-skew guard (halt entries past 80% recvWindow)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class _SkewEngine:
    model_label = "skew-stub"
    assumptions = ()

    def __init__(self, skew_ms=0.0, recv_window_ms=5000):
        self._skew = skew_ms
        self._recv = recv_window_ms
        self.refresh_calls = 0

    def poll(self):
        return []

    def open_orders(self):
        return []

    def clock_skew_ms(self):
        return self._skew

    def recv_window_ms(self):
        return self._recv

    def refresh_clock_offset(self):
        self.refresh_calls += 1
        return self._skew


def _session(tmp_path: Path, engine):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    session = Session(load_config(cfg_path),
                      RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "run", "skew-run", engine=engine)
    session.clock.set_ms(int(datetime(2026, 10, 17,
                                      tzinfo=timezone.utc).timestamp()
                             * 1000))
    session.policy.reconcile_day(10000.0, 0.0)
    session.store.create_run("skew-run", "paper", "fp",
                             str(session.workdir), None)
    return session


def test_skew_beyond_margin_blocks_entries(tmp_path):
    engine = _SkewEngine(skew_ms=4500.0)  # 90% of 5000ms window
    session = _session(tmp_path, engine)
    session._health_tick()  # noqa: SLF001
    assert any("clock-skew" in r
               for r in session._health_halt_reasons)  # noqa: SLF001


def test_skew_inside_margin_flows(tmp_path):
    engine = _SkewEngine(skew_ms=100.0)
    session = _session(tmp_path, engine)
    session._health_tick()  # noqa: SLF001
    assert not any("clock-skew" in r
                   for r in session._health_halt_reasons)  # noqa: SLF001


def test_skew_recovers_level_wise(tmp_path):
    engine = _SkewEngine(skew_ms=4500.0)
    session = _session(tmp_path, engine)
    session._health_tick()  # noqa: SLF001
    assert any("clock-skew" in r  # noqa: SLF001
               for r in session._health_halt_reasons)  # noqa: SLF001
    engine._skew = 50.0
    session._health_tick()  # noqa: SLF001
    assert not any("clock-skew" in r  # noqa: SLF001
                   for r in session._health_halt_reasons)  # noqa: SLF001


def test_skew_refresh_throttled(tmp_path):
    engine = _SkewEngine(skew_ms=100.0)
    session = _session(tmp_path, engine)
    for _ in range(5):
        session._health_tick()  # noqa: SLF001
    assert engine.refresh_calls <= 1
