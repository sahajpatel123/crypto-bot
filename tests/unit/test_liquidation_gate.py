"""F0.4a: liquidation/bracket gate in the LIVE admission path."""
from __future__ import annotations

from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

BRACKETS = [
    {"bracket": 1, "notionalCap": 50000.0, "maintMarginRatio": 0.004,
     "cum": 0.0},
    {"bracket": 2, "notionalCap": 250000.0, "maintMarginRatio": 0.005,
     "cum": 50.0},
]


class _StubEngine:
    model_label = "f04a-stub"
    assumptions = ("stub: f04a",)
    brackets = BRACKETS
    stale = False

    def poll(self):
        return []

    def open_orders(self):
        return []

    def leverage_brackets(self, symbol):
        return (list(self.brackets), self.stale)


def _session(tmp_path: Path) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    return Session(load_config(cfg_path), store, tmp_path / "run",
                   "f04a-run", engine=_StubEngine())


def test_gate_passes_when_liquidation_far(tmp_path):
    s = _session(tmp_path)
    # Long 0.01 @60000 (notional 600), lev 3 -> margin 200, mm 2.4
    # liq = 60000 - (200-2.4)/0.01 = 40240; stop 59400 (1% away)
    out = s.liquidation_gate(symbol="BTCUSDT", side="LONG", qty=0.01,
                             entry=60000.0, stop=59400.0)
    assert out is None


def test_gate_rejects_when_liquidation_too_close(tmp_path):
    s = _session(tmp_path)
    # Huge qty: notional 600k at tier2 mm; margin=200k? lev3 margin
    # 200000, mm=2950 -> liq dist = (200000-2950)/10 = 19705 vs entry
    # 60000 stop 59400 dist 600; 3x=1800, liq 40295 far -> passes.
    # Instead tiny margin via leverage 3 but stop very wide:
    out = s.liquidation_gate(symbol="BTCUSDT", side="LONG", qty=0.01,
                             entry=60000.0, stop=40000.0)
    assert out is not None and "liquidation" in out


def test_gate_rejects_stale_brackets(tmp_path):
    s = _session(tmp_path)
    s.engine.stale = True
    out = s.liquidation_gate(symbol="BTCUSDT", side="LONG", qty=0.01,
                             entry=60000.0, stop=59400.0)
    assert out is not None and "stale" in out


def test_gate_skips_non_live_engine(tmp_path):
    s = _session(tmp_path)
    s.engine.leverage_brackets = None
    out = s.liquidation_gate(symbol="BTCUSDT", side="LONG", qty=0.01,
                             entry=60000.0, stop=59400.0)
    assert out is None  # paper/reference: no venue brackets, no gate
