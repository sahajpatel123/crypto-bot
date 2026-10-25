"""E6.3: Family B autopilot states (synthetic artifacts, tmp registry)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def _bot(tmp_path: Path, family: str = "B"):
    from cryptobot.research.autopilot import Autopilot

    return Autopilot(tmp_path / "autopilot_b", family=family)


def _register(bot, tmp_path: Path):
    prereg = tmp_path / "B1.md"
    prereg.write_text("# B1\n")
    return bot.register("B1", prereg=str(prereg), config_sha256="abc123",
                        commit="c1", family_size=7)


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def test_b_dev_kill_and_freeze(tmp_path):
    bot = _bot(tmp_path)
    _register(bot, tmp_path)
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "DEV_EVAL"
    _write(bot.root / "dev" / "B1.json",
           {"promotes": False, "gates": {"oos_sharpe": False}})
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "KILLED"


def test_b_freeze_requires_matching_vault_record(tmp_path):
    bot = _bot(tmp_path)
    _register(bot, tmp_path)
    bot.run_once()
    _write(bot.root / "dev" / "B1.json",
           {"promotes": True, "gates": {},
            "vault_frozen": {"commit": "c1", "config_sha256": "WRONG"}})
    out = bot.run_once()["hypotheses"]["B1"]
    assert out["state"] == "DEV_EVAL" and "freeze" in out["blocked"]
    _write(bot.root / "dev" / "B1.json",
           {"promotes": True, "gates": {},
            "vault_frozen": {"commit": "c1", "config_sha256": "abc123"}})
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "FROZEN"


def _to_frozen(tmp_path):
    bot = _bot(tmp_path)
    _register(bot, tmp_path)
    bot.run_once()
    _write(bot.root / "dev" / "B1.json",
           {"promotes": True, "gates": {},
            "vault_frozen": {"commit": "c1", "config_sha256": "abc123"}})
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "FROZEN"
    return bot


def test_b_holdout_screen_pass_and_fail(tmp_path):
    bot = _to_frozen(tmp_path)
    _write(bot.root.parent / "verdicts_b" / "B1.json",
           {"verdict": "SCREEN_PASS", "data_provenance": "SEALED-HOLDOUT",
            "metrics": {"point_sharpe": 0.9}})
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "HOLDOUT_SCREEN"
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "SCREEN_PASS"


def test_b_holdout_wrong_provenance_fails(tmp_path):
    bot = _to_frozen(tmp_path)
    _write(bot.root.parent / "verdicts_b" / "B1.json",
           {"verdict": "SCREEN_PASS", "data_provenance": "OBSERVED",
            "metrics": {}})
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "FAIL"


def test_b_forward_paper_compare_gate_ready(tmp_path):
    bot = _to_frozen(tmp_path)
    _write(bot.root.parent / "verdicts_b" / "B1.json",
           {"verdict": "SCREEN_PASS", "data_provenance": "SEALED-HOLDOUT",
            "metrics": {"point_sharpe": 0.9}})
    bot.run_once()
    bot.run_once()
    started = (datetime.now(UTC) - timedelta(days=61)).isoformat()
    _write(bot.root / "forward" / "B1.json",
           {"paper_started_utc": started, "rebalances": 40,
            "realized_sharpe": 0.6, "max_dd": 0.2, "turnover": 3.0,
            "turnover_budget": 6.0})
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "FORWARD_PAPER"
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "FORWARD_COMPARE"
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "GATE_READY"
    assert bot.verify_log() == []


def test_b_forward_incomplete_blocks(tmp_path):
    bot = _to_frozen(tmp_path)
    _write(bot.root.parent / "verdicts_b" / "B1.json",
           {"verdict": "SCREEN_PASS", "data_provenance": "SEALED-HOLDOUT",
            "metrics": {"point_sharpe": 0.9}})
    bot.run_once()
    bot.run_once()
    started = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    _write(bot.root / "forward" / "B1.json",
           {"paper_started_utc": started, "rebalances": 40,
            "realized_sharpe": 0.6, "max_dd": 0.2, "turnover": 3.0,
            "turnover_budget": 6.0})
    assert bot.run_once()["hypotheses"]["B1"]["state"] == "FORWARD_PAPER"
    out = bot.run_once()["hypotheses"]["B1"]
    assert out["state"] == "FORWARD_PAPER" and "incomplete" in out["blocked"]


def test_family_isolation(tmp_path):
    from cryptobot.research.autopilot import Autopilot

    a = Autopilot(tmp_path / "auto_a", family="A")
    a.register("H9", prereg="p", config_sha256="x", commit="c")
    with pytest.raises(ValueError, match="Family A cannot enter"):
        a._transition("H9", "FROZEN", reason="x")
    b = _bot(tmp_path)
    _register(b, tmp_path)
    with pytest.raises(ValueError, match="Family B cannot enter"):
        b._transition("B1", "AWAIT_CONFIRM_DATA", reason="x")


def test_b_synthetic_dev_refused(tmp_path):
    _to_frozen(tmp_path)  # frozen first...
    # ...then a synthetic forward artifact is refused (regression shape:
    # use a fresh hypothesis to test the dev guard instead).
    bot2 = _bot(tmp_path / "r2")
    _register(bot2, tmp_path / "r2")
    bot2.run_once()
    _write(bot2.root / "dev" / "B1.json",
           {"promotes": True, "provenance": "SYNTHETIC", "gates": {}})
    out = bot2.run_once()["hypotheses"]["B1"]
    assert out["state"] == "DEV_EVAL" and "synthetic" in out["blocked"]
