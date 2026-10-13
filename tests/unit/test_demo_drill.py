"""READY §7: demo-drill kill criteria (credential-free, fully stubbed).

No network, no keys. The stub engine/quote stand in for the venue;
every kill path must FAIL + abort with no further phases.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "audit"))
import demo_drill  # noqa: E402


class _Status:
    def __init__(self, state):
        self.state = state


class FakeEngine:
    def __init__(self, mark=100.0, stop_state="open", out_mult=1.0,
                 unknowns=(), entry_state="filled", entry_fill=None):
        self._filters = {"BTCUSDT": {"step": 0.001, "min_notional": 5.0}}
        self._mark = mark
        self._stop_state = stop_state
        self._out_mult = out_mult
        self._unknowns = list(unknowns)
        self._entry_state = entry_state
        self._entry_fill = entry_fill
        self._transport = self
        self.submitted = []
        self.cancelled = []
        self._cids = 0

    # -- engine surface used by the drill --
    def _ensure_ready(self, symbol):
        pass

    def request(self, method, path, params, headers):
        return {"serverTime": int(time.time() * 1000)}

    def submit(self, order):
        self._cids += 1
        cid = f"stub-{self._cids}"
        self.submitted.append((cid, order))
        return cid

    def lookup(self, cid):
        for sid, order in self.submitted:
            if sid == cid:
                if getattr(order, "role", "") == "stop":
                    return _Status(self._stop_state)
                return _Status(self._entry_state)
        return _Status("cancelled")

    def filled_qty(self, cid):
        for sid, order in self.submitted:
            if sid == cid:
                if getattr(order, "role", "") == "target":
                    return round(order.qty * self._out_mult, 8)
                if self._entry_fill is not None:
                    return self._entry_fill
                return order.qty if self._entry_state == "filled" else 0.0
        return 0.0

    def unknown_ids(self):
        return list(self._unknowns)

    def cancel(self, cid, reason):
        self.cancelled.append(cid)

    def _read_journal(self):
        return []

    def open_orders(self):
        return []


@pytest.fixture
def drill(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    d = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    monkeypatch.setattr(d, "live_quote",
                        lambda: (100.0, int(time.time() * 1000)))
    return d


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")


def _phases(drill):
    return [ln for ln in
            drill.evidence_path.read_text().splitlines() if ln]


def test_no_creds_blocked(drill, monkeypatch):
    monkeypatch.delenv("BINANCE_DEMO_KEY", raising=False)
    monkeypatch.delenv("BINANCE_DEMO_SECRET", raising=False)
    assert demo_drill.cmd_drill(drill) == 2
    assert demo_drill.cmd_preflight(drill) == 2


def test_non_demo_host_refused(drill, creds):
    drill.base_url = "https://fapi.binance.com"
    assert demo_drill.cmd_drill(drill) == 2


def test_stale_quote_kills_drill(drill, creds, monkeypatch):
    monkeypatch.setattr(drill, "live_quote",
                        lambda: (100.0, int(time.time() * 1000) - 60000))
    assert demo_drill.cmd_drill(drill) == 1
    assert "drill/quote-fresh" in _phases(drill)[-1]
    assert "KILL" in _phases(drill)[-1]


def test_unknown_quote_time_fails_closed(drill, creds, monkeypatch):
    monkeypatch.setattr(drill, "live_quote", lambda: (100.0, None))
    assert demo_drill.cmd_drill(drill) == 1


def test_exposure_cap_breach_kills(drill, creds, monkeypatch):
    eng = FakeEngine()
    eng._filters["BTCUSDT"]["min_notional"] = 100000.0
    monkeypatch.setattr(drill, "engine", lambda transport=None: eng)
    assert demo_drill.cmd_drill(drill) == 1
    assert eng.submitted == []


def test_unknowns_at_gate_kill(drill, creds, monkeypatch):
    eng = FakeEngine(unknowns=["abc"])
    monkeypatch.setattr(drill, "engine", lambda transport=None: eng)
    assert demo_drill.cmd_drill(drill) == 1
    assert eng.submitted == []


def test_protection_miss_aborts_before_later_phases(drill, creds,
                                                    monkeypatch):
    eng = FakeEngine(stop_state="cancelled")
    monkeypatch.setattr(drill, "engine", lambda transport=None: eng)
    assert demo_drill.cmd_drill(drill) == 1
    phases = "\n".join(_phases(drill))
    assert "drill/protection" in phases and "KILL" in phases
    assert "ambiguous-submit" not in phases
    assert "restart-adopt" not in phases


def test_exit_mismatch_aborts(drill, creds, monkeypatch):
    eng = FakeEngine(out_mult=0.5)
    monkeypatch.setattr(drill, "engine", lambda transport=None: eng)
    assert demo_drill.cmd_drill(drill) == 1
    assert "reduce-only-exit" in "\n".join(_phases(drill))


def test_honest_no_trade_blocks_protection(drill, creds, monkeypatch):
    eng = FakeEngine(entry_state="cancelled", entry_fill=0.0)
    monkeypatch.setattr(drill, "engine", lambda transport=None: eng)

    class _Done:
        returncode = 0
        stdout = "adopted journal=x unknowns=0 open=0"

    monkeypatch.setattr(demo_drill.subprocess, "run", lambda *a, **k: _Done())
    rc = demo_drill.cmd_drill(drill)
    phases = "\n".join(_phases(drill))
    assert "protection-exit" in phases
    assert "KILL" not in phases
    # rc==1 here is a stub artifact: FakeEngine.submit never raises the
    # UNKNOWN phase 3 injects (covered against the real adapter by the
    # credentialed drill + W5's adapter tests). This test pins no-KILL.
    assert rc == 1
    assert "ambiguous-submit" in phases
