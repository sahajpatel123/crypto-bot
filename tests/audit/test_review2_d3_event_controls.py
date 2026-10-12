"""Review-2 defect 3: event controls disabled (W5-24H).

events_enabled=False in paper.toml, r2.toml and r3.toml. The anomaly
policy has no runtime caller (zero references in app/session.py; the
gate seam exists but is never built while disabled).

Required: supply an explicitly protected operational profile and wire
calendar and measured anomaly decisions. Preserve explicit
research-only profiles when historical calendar availability is
unknown.

Fails on base 3cadfca (bug reproduced); passes once W4 wires the
protected profile + anomaly caller. Strict-xfail marked in
tests/audit/conftest.py while open.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.app.config import load_config

ROOT = Path(__file__).resolve().parents[2]
OPERATIONAL = ("configs/paper.toml", "configs/r2.toml", "configs/r3.toml")


def test_operational_configs_enable_events():
    """Paper/r2/r3 must run under an explicitly protected profile."""
    disabled = [name for name in OPERATIONAL
                if not load_config(ROOT / name).events_enabled]
    assert not disabled, (
        f"event controls disabled in: {disabled} "
        f"(gate seam exists but is never built)")


def test_anomaly_policy_has_runtime_caller():
    """Admission must consult the measured anomaly policy."""
    text = (ROOT / "src" / "cryptobot" / "app" / "session.py").read_text(
        encoding="utf-8")
    assert "anomaly" in text.lower(), (
        "no anomaly reference in app/session.py: the policy has no "
        "runtime caller, so measured shocks cannot gate entries")
