"""Persisted ladder promotion: audit trail, no skips, no replayed evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryptobot.ops.daily_pnl import build_ladder_evidence
from cryptobot.risk import ladder_controller
from cryptobot.risk.ladder import (
    EVIDENCE_GENERATOR_MODULE,
    PROMOTION_EVIDENCE_FORMAT,
    Promotion,
)
from cryptobot.risk.ladder_controller import LadderController, LadderError

GOOD_LIVE = {"round_trips": 140, "days": 33.0, "sharpe": 0.55,
             "cost_bps": 4.1, "max_drawdown_frac": 0.02, "halted": False}
GOOD_BACKTEST = {"sharpe": 0.80, "cost_bps": 3.5, "max_drawdown_frac": 0.015}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(tmp_path: Path, *, live: dict | None = None,
              backtest: dict | None = None,
              code_sha256: str | None = None) -> Path:
    source = tmp_path / "journal.json"
    source.write_text('{"kind": "journal"}\n', encoding="utf-8")
    doc = {
        "format": PROMOTION_EVIDENCE_FORMAT,
        "study": "B4b",
        "as_of_utc": datetime.now(UTC).isoformat(),
        "generated_by": {
            "module": EVIDENCE_GENERATOR_MODULE,
            "code_sha256": code_sha256 or ladder_controller._generator_sha256(),
        },
        "live": dict(GOOD_LIVE if live is None else live),
        "backtest": dict(GOOD_BACKTEST if backtest is None else backtest),
        "sources": [{"kind": "journal", "path": str(source),
                     "sha256": _sha(source)}],
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


def _controller(tmp_path: Path) -> LadderController:
    return LadderController(tmp_path / "ladder.json", assumed_slippage_bps=5.0)


def test_promotion_persists_the_full_audit_trail(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    assert controller.rung == "canary"
    evidence = _evidence(tmp_path)
    before = datetime.now(UTC)
    outcome = controller.promote(evidence_path=evidence, commit="a" * 40)
    assert outcome["persisted"] is True
    assert outcome["rung"] == "armed"
    assert outcome["from_rung"] == "canary"

    state = json.loads((tmp_path / "ladder.json").read_text(encoding="utf-8"))
    assert state["rung"] == "armed"
    entry = state["history"][-1]
    assert entry["kind"] == "promote"
    assert entry["from_rung"] == "canary" and entry["to_rung"] == "armed"
    assert entry["evidence_path"] == str(evidence)
    assert entry["evidence_sha256"] == _sha(evidence)
    assert entry["commit"] == "a" * 40
    stamp = datetime.fromisoformat(entry["ts_utc"])
    assert stamp.tzinfo is not None and stamp.utcoffset() == stamp.utcoffset()
    assert stamp >= before
    assert state["promotions"][-1]["evidence_sha256"] == _sha(evidence)

    reloaded = LadderController(tmp_path / "ladder.json",
                                assumed_slippage_bps=5.0)
    assert reloaded.rung == "armed"
    assert reloaded.demoted is False


def test_the_same_evidence_cannot_support_two_promotions(
        tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    evidence = _evidence(tmp_path)
    controller.promote(evidence_path=evidence, commit="b" * 40)
    # Walk back down the ladder, then replay the identical document.
    controller.demote("operator drill")
    controller.manual_promote()
    assert controller.rung == "canary"
    with pytest.raises(LadderError, match="already supported a promotion"):
        controller.promote(evidence_path=evidence, commit="b" * 40)


def test_rule_refusal_does_not_touch_the_state(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    weak = _evidence(tmp_path, live={"round_trips": 3, "days": 2.0,
                                     "sharpe": 0.1, "cost_bps": 40.0,
                                     "max_drawdown_frac": 0.5,
                                     "halted": False})
    outcome = controller.promote(evidence_path=weak, commit="c" * 40)
    assert outcome["allowed"] is False
    assert outcome["persisted"] is False
    assert "live-round-trips<100" in outcome["reasons"]
    assert controller.rung == "canary"
    assert controller.state["history"] == []
    on_disk = tmp_path / "ladder.json"
    if on_disk.exists():
        state = json.loads(on_disk.read_text(encoding="utf-8"))
        assert [entry.get("kind") for entry in state["history"]] == []


def test_hand_built_evidence_is_refused(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    forged = _evidence(tmp_path, code_sha256="0" * 64)
    with pytest.raises(LadderError, match="different build"):
        controller.promote(evidence_path=forged, commit="d" * 40)


def test_evidence_whose_source_changed_is_refused(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    evidence = _evidence(tmp_path)
    (tmp_path / "journal.json").write_text('{"kind": "rewritten"}\n',
                                           encoding="utf-8")
    with pytest.raises(LadderError, match="no longer matches"):
        controller.promote(evidence_path=evidence, commit="e" * 40)


def test_a_promotion_must_name_a_commit(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    evidence = _evidence(tmp_path)
    with pytest.raises(LadderError, match="not a git SHA"):
        controller.promote(evidence_path=evidence, commit="HEAD")
    assert controller.rung == "canary"


def test_a_promotion_cannot_skip_a_rung(tmp_path: Path, monkeypatch) -> None:
    controller = _controller(tmp_path)
    controller.demote("halted for the drill")
    evidence = _evidence(tmp_path)
    # Simulate a caller that hands the controller an "allowed armed" decision
    # while the persisted state is halted: the controller must still refuse,
    # because next_rung("halted") is canary, not armed.
    monkeypatch.setattr(ladder_controller, "promotion_decision",
                        lambda **_kwargs: Promotion(True, "armed", ()))
    with pytest.raises(LadderError, match="skips a rung"):
        controller.promote(evidence_path=evidence, commit="f" * 40)
    assert controller.rung == "halted"


def test_promotion_out_of_a_halt_is_refused(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.daily_stop()
    outcome = controller.promote(evidence_path=_evidence(tmp_path),
                                 commit="1" * 40)
    assert outcome["allowed"] is False
    assert "rung-halted" in outcome["reasons"]
    assert controller.rung == "halted"


def test_manual_promotion_lands_on_canary_not_armed(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.demote("manual pause")
    assert controller.rung == "halted"
    controller.manual_promote()
    assert controller.rung == "canary"
    assert controller.demoted is False
    entry = json.loads(
        (tmp_path / "ladder.json").read_text(encoding="utf-8"))["history"][-1]
    assert entry["kind"] == "manual_promote"
    assert entry["to_rung"] == "canary"


def test_automatic_demotion_still_halts_and_persists(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.record_trade(realized_slippage_bps=9.0, net_bps=-2.0)
    assert controller.demoted is True
    assert controller.rung == "halted"
    assert "slippage>1.5x-assumed" in controller.reasons
    entry = json.loads(
        (tmp_path / "ladder.json").read_text(encoding="utf-8"))["history"][-1]
    assert entry["kind"] == "demote" and entry["to_rung"] == "halted"
    again = LadderController(tmp_path / "ladder.json",
                             assumed_slippage_bps=5.0)
    assert again.demoted is True and again.rung == "halted"


def test_old_state_file_backfills_the_rung(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"format": "cryptobot-ladder/1",
                                "demoted": True, "reasons": ["x"],
                                "trades": [], "history": []}),
                    encoding="utf-8")
    controller = LadderController(path, assumed_slippage_bps=5.0)
    assert controller.rung == "halted"
    assert controller.demoted is True


def test_evidence_derived_from_journals_binds_its_sources(
        tmp_path: Path) -> None:
    run = tmp_path / "runs" / "run-1"
    run.mkdir(parents=True)
    ledger = {
        "version": 1, "pilot_equity": 10_000.0, "seq": 0, "snapshot": {},
        "journal": [
            {"kind": "fill", "side": "BUY", "qty": 0.1, "price": 50_000.0,
             "fee": 5.0, "ts_utc": "2026-03-02T09:00:00+00:00",
             "exec_id": "f1", "symbol": "BTCUSDT"},
            {"kind": "fill", "side": "SELL", "qty": 0.1, "price": 50_200.0,
             "fee": 5.0, "ts_utc": "2026-03-02T10:00:00+00:00",
             "exec_id": "f2", "symbol": "BTCUSDT"},
        ],
    }
    (run / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    reference = tmp_path / "backtest.json"
    reference.write_text(json.dumps({
        "format": "cryptobot-backtest-reference/1", "study": "B4b",
        "sharpe": 0.8, "cost_bps": 3.5, "max_drawdown_frac": 0.015}),
        encoding="utf-8")
    out = tmp_path / "evidence.json"
    doc = build_ladder_evidence(
        tmp_path / "runs", backtest_reference=reference, out=out,
        study="B4b", strategy_state=tmp_path / "ladder.json")
    assert doc["format"] == PROMOTION_EVIDENCE_FORMAT
    assert doc["generated_by"]["module"] == EVIDENCE_GENERATOR_MODULE
    assert doc["generated_by"]["code_sha256"] == _sha(
        Path(ladder_controller.__file__).resolve().parent.parent
        / "ops" / "daily_pnl.py")
    assert doc["live"]["round_trips"] == 1
    assert doc["live"]["cost_bps"] is None  # no measured slippage yet
    assert {item["kind"] for item in doc["sources"]} == {"journal", "backtest"}
    assert all(item["sha256"] for item in doc["sources"])

    controller = _controller(tmp_path)
    outcome = controller.promote(evidence_path=out, commit="2" * 40)
    assert outcome["allowed"] is False
    assert "live-round-trips<100" in outcome["reasons"]
    assert "live-cost-missing" in outcome["reasons"]
