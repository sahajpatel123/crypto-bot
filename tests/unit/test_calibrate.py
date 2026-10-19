"""F2.2: calibrate — fit slippage/latency, versioned cost model.

Inputs are SYNTHETIC test observations (tmp files only, stamped) plus
paper fills_drift rows (latency + predicted drift): fits are exact
quantiles; auto-update only tightens (relax refused without an
explicit reason); versions chain by hash; output loads via
PaperFillParams.from_dict (provenance MEASURED).
"""
from __future__ import annotations

import json
from pathlib import Path


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _obs(realized, latency_ms=None, source="SYNTHETIC-TEST"):
    row = {"symbol": "BTCUSDT", "realized_slip_bps": realized,
           "source": source}
    if latency_ms is not None:
        row["latency_ms"] = latency_ms
    return row


def test_fit_is_exact_quantiles(tmp_path):
    from cryptobot.research.calibrate import fit_cost_model

    obs = _write_jsonl(tmp_path / "obs.jsonl",
                       [_obs(float(v), latency_ms=float(v) * 10.0)
                        for v in (1, 2, 3, 4, 5, 6, 7, 8, 9, 20)])
    doc = fit_cost_model([obs], [], current=None, now_utc="2026-10-18T00:00:00+00:00")
    assert doc["version"] == 1
    # p90 of realized [1..9,20] == 9 (nearest-rank); p95 latency of
    # [10..90,200] == 200 (nearest-rank takes the max at n=10 —
    # conservative by construction for cost fitting).
    assert doc["fit_stats"]["p90_realized_slip_bps"] == 9.0
    assert doc["fit_stats"]["p95_latency_ms"] == 200.0
    assert doc["params"]["slippage_bps"] == 9.0
    assert doc["params"]["latency_ms_p95"] == 200
    assert doc["params"]["provenance"] == "MEASURED"
    assert doc["prev_sha256"] == "0" * 64


def test_auto_update_only_tightens(tmp_path):
    from cryptobot.research.calibrate import fit_cost_model

    obs = _write_jsonl(tmp_path / "obs.jsonl", [_obs(1.0)])
    current = {"version": 3, "document_sha256": "abc",
               "params": {"version": 1, "spread_bps": 2.0,
                          "slippage_bps": 8.0, "latency_ms_p95": 50,
                          "latency_bps": 2.0, "empty_book_bps": 25.0,
                          "provenance": "MEASURED", "source": "x",
                          "asof_utc": None,
                          "fill_model_note": "n"}}
    doc = fit_cost_model([obs], [], current=current,
                         now_utc="2026-10-18T00:00:00+00:00")
    assert doc["version"] == 4
    assert doc["params"]["slippage_bps"] == 8.0  # relax refused
    assert doc["relax_refused"] == ["slippage_bps"]
    assert doc["prev_sha256"] == "abc"
    # Explicit relax with a recorded reason is allowed (verdict-gated
    # downstream at F5; the reason is what the gate audits).
    doc2 = fit_cost_model([obs], [], current=current, allow_relax=True,
                          relax_reason="fresh verdict V-9 PASS",
                          now_utc="2026-10-18T00:00:00+00:00")
    assert doc2["params"]["slippage_bps"] == 1.0
    assert doc2["relax_reason"] == "fresh verdict V-9 PASS"


def test_paper_drift_rows_feed_latency_only(tmp_path):
    from cryptobot.research.calibrate import fit_cost_model

    drift = _write_jsonl(tmp_path / "fills_drift.jsonl", [
        {"execution_id": f"x{i}", "instrument": "BTCUSDT",
         "raw_fee": 1.0, "slippage_drift_bps": 30.0, "drift_fee": 2.0,
         "booked_fee": 3.0, "dispatch_ms": 40.0 + i,
         "ts_utc": "2026-10-18T00:00:00+00:00"}
        for i in range(5)])
    doc = fit_cost_model([], [drift], current=None,
                         now_utc="2026-10-18T00:00:00+00:00")
    # Paper predicted drift (30bps model output) must NOT fit realized
    # slippage (sim has no adverse selection); latency fits from
    # dispatch_ms (p95 of 40..44 == 44).
    assert doc["fit_stats"]["n_realized"] == 0
    assert doc["params"]["slippage_bps"] == 6.0  # default kept
    assert doc["params"]["latency_ms_p95"] == 44


def test_output_loads_as_fill_params(tmp_path):
    from cryptobot.execution.fill_realism import PaperFillParams
    from cryptobot.research.calibrate import fit_cost_model

    obs = _write_jsonl(tmp_path / "obs.jsonl", [_obs(7.0, 60.0)])
    doc = fit_cost_model([obs], [], current=None,
                         now_utc="2026-10-18T00:00:00+00:00")
    params = PaperFillParams.from_dict(dict(doc["params"]))
    assert params.provenance == "MEASURED"
    assert params.slippage_bps == 7.0


def test_cli_calibrate_end_to_end(tmp_path, capsys):
    import argparse

    from cryptobot import cli

    obs = _write_jsonl(tmp_path / "obs.jsonl", [_obs(4.0, 55.0)])
    out = tmp_path / "cost-model.json"
    rc = cli.cmd_calibrate(argparse.Namespace(
        fills=[], observations=[str(obs)], current=None, out=str(out),
        allow_relax=False, relax_reason=None))
    assert rc == 0
    doc = json.loads(out.read_text())
    assert doc["params"]["slippage_bps"] == 4.0
    assert "calibrate" in capsys.readouterr().out
