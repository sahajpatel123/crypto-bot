"""V-007: metrics + independent reconciliation on the fixture run."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from cryptobot.accounting import Ledger
from cryptobot.reporting.episodes import build_episodes
from cryptobot.reporting.metrics import (
    ReconciliationError, compute_metrics, reconcile,
)
from cryptobot.reporting.schemas import load_run

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "v007_run"


def _built(run_dir=FIX):
    run = load_run(run_dir)
    journal = run.ledger.to_dict()["journal"]
    funding = [(datetime.fromisoformat(e["ts_utc"]), e["amount"])
               for e in journal if e["kind"] == "funding"]
    end = datetime.fromisoformat(str(run.config["run"]["window_end_utc"]))
    eps = build_episodes(run.fills, funding, end, strategy="S1")
    return run, eps


def test_fixture_metrics_values():
    run, eps = _built()
    m = compute_metrics(run, eps)
    assert m.reconciliation["status"] == "agree"
    assert m.net_return["net_return"] == pytest.approx(0.00053)
    assert m.n_episodes == 1
    assert m.expectancy["label"] == "insufficient: n<30"
    assert m.win_loss["profit_factor"] is None
    assert "no losing episodes" in m.win_loss["profit_factor_label"]
    assert m.costs["entry_fees"] == pytest.approx(1.0)
    assert m.costs["exit_fees"] == pytest.approx(2.0)
    assert "unmodeled" in m.costs["execution_effects"]
    assert m.splits["status"].startswith("unassigned")
    assert m.speed_resources["status"].startswith("not recorded")
    assert m.behavior["per_strategy"]["S1"]["net"] == pytest.approx(5.3)


def test_reconcile_raises_on_corrupt_episode_rebuild():
    import dataclasses
    run, eps = _built()
    # Simulate a rebuild that disagrees with the ledger.
    corrupt = [dataclasses.replace(eps[0], net=eps[0].net + 1.0)]
    with pytest.raises(ReconciliationError, match="realised"):
        reconcile(run, corrupt)


def test_reconcile_raises_on_dropped_episode():
    run, eps = _built()
    with pytest.raises(ReconciliationError, match="realised"):
        reconcile(run, eps[1:])


def test_no_trade_run_labels_not_fakes(tmp_path):
    run_dir = tmp_path / "run"
    shutil.copytree(FIX, run_dir)
    (run_dir / "fills.jsonl").write_text("")
    Ledger(10000.0).save(run_dir / "ledger.json")
    eq = (run_dir / "equity.jsonl").read_text().splitlines()
    flat = []
    for line in eq:
        row = json.loads(line)
        row.update(marked_equity=10000.0, cash=10000.0, position_qty=0.0,
                   position_symbol="", open_pnl=0.0)
        flat.append(json.dumps(row))
    (run_dir / "equity.jsonl").write_text("\n".join(flat) + "\n")
    run, eps = _built(run_dir)
    m = compute_metrics(run, eps)
    assert eps == []
    assert any("no-trades" in label for label in m.labels)
    assert m.expectancy["n"] == 0
    assert m.win_loss["win_rate"] is None
    assert m.net_return["net_return"] == pytest.approx(0.0)


def test_no_trade_day_kept_with_label(tmp_path):
    run_dir = tmp_path / "run"
    shutil.copytree(FIX, run_dir)
    cfg = (run_dir / "config.toml").read_text()
    cfg = cfg.replace("2026-10-10T17:00:00+00:00", "2026-10-11T17:00:00+00:00")
    (run_dir / "config.toml").write_text(cfg)
    eq = (run_dir / "equity.jsonl").read_text().splitlines()
    last = json.loads(eq[-1])
    last["ts_utc"] = "2026-10-11T12:00:00+00:00"
    eq.append(json.dumps(last))
    (run_dir / "equity.jsonl").write_text("\n".join(eq) + "\n")
    run, eps = _built(run_dir)
    m = compute_metrics(run, eps)
    days = {d["date"]: d for d in m.daily["days"]}
    assert days["2026-10-11"]["label"] == "no-trade"
    assert days["2026-10-11"]["ret"] == pytest.approx(0.0)


def test_declared_splits_reported_per_bucket(tmp_path):
    run_dir = tmp_path / "run"
    shutil.copytree(FIX, run_dir)
    (run_dir / "splits.json").write_text(json.dumps({
        "in_sample": {"start": "2026-10-10T12:00:00+00:00",
                      "end": "2026-10-10T14:00:00+00:00"},
        "out_of_sample": {"start": "2026-10-10T14:00:00+00:00",
                          "end": "2026-10-10T17:00:00+00:00"},
    }))
    run, eps = _built(run_dir)
    m = compute_metrics(run, eps)
    assert m.splits["buckets"]["in_sample"]["n"] == 0
    assert m.splits["buckets"]["out_of_sample"]["n"] == 1
    assert "no blended" in m.splits["note"]


def test_mark_provenance_counts_and_open_unmarked():
    run, eps = _built()
    m = compute_metrics(run, eps)
    prov = m.reliability["mark_provenance"]
    assert prov["by_source"] == {"unrecorded": 5}
    assert prov["max_age_ms"] is None
    n_open = sum(1 for r in run.equity if r.position_qty != 0)
    assert prov["open_rows_without_mark"] == n_open
    assert n_open > 0


def test_mark_provenance_with_recorded_marks(tmp_path):
    run_dir = tmp_path / "run"
    shutil.copytree(FIX, run_dir)
    eq = (run_dir / "equity.jsonl").read_text().splitlines()
    marked = []
    for i, line in enumerate(eq):
        row = json.loads(line)
        row["mark_source"] = "exchange"
        row["mark_age_ms"] = 100.0 * (i + 1)
        marked.append(json.dumps(row))
    (run_dir / "equity.jsonl").write_text("\n".join(marked) + "\n")
    run, eps = _built(run_dir)
    prov = compute_metrics(run, eps).reliability["mark_provenance"]
    assert prov["by_source"] == {"exchange": 5}
    assert prov["max_age_ms"] == 500.0
    assert prov["open_rows_without_mark"] == 0
