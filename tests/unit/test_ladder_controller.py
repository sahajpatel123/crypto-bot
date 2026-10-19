"""F5.3: automatic ladder demotion persists; promotion is manual."""
from __future__ import annotations

import json

from cryptobot.risk.ladder_controller import LadderController


def test_slippage_demotes_and_persists(tmp_path):
    c = LadderController(tmp_path / "ladder.json",
                         assumed_slippage_bps=5.0)
    assert c.demoted is False
    c.record_trade(realized_slippage_bps=9.0, net_bps=-2.0)
    assert c.demoted is True
    assert "slippage>1.5x-assumed" in c.reasons
    again = LadderController(tmp_path / "ladder.json",
                             assumed_slippage_bps=5.0)
    assert again.demoted is True
    assert json.loads((tmp_path / "ladder.json").read_text())["demoted"]


def test_negative_expectancy_ci_demotes_after_min_n(tmp_path):
    c = LadderController(tmp_path / "l.json", assumed_slippage_bps=5.0,
                         expectancy_min_n=5)
    for _ in range(5):
        c.record_trade(realized_slippage_bps=4.0, net_bps=-10.0)
    assert c.demoted is True
    assert "expectancy-ci-upper<0" in c.reasons


def test_unknown_and_daily_stop_demote(tmp_path):
    c = LadderController(tmp_path / "l.json", assumed_slippage_bps=5.0,
                         unknown_budget_s=60.0)
    assert c.observe_unknown(61.0) == ("unknown-outcome-aged",)
    assert c.demoted is True
    assert c.daily_stop() == ("operating-daily-stop",)


def test_manual_promotion_clears(tmp_path):
    c = LadderController(tmp_path / "l.json", assumed_slippage_bps=5.0)
    c.daily_stop()
    c.manual_promote()
    assert c.demoted is False and c.reasons == ()
