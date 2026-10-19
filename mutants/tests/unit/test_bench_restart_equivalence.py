"""CORR W2 standing regression: restart equivalence with real trading.

Deterministic 6240-event tape (warmup -> ramp -> LONG partial entry ->
stop exit at a LOSS -> dip -> IST-midnight roll -> rebound -> flat):
reference, determinism re-run, flat interrupt, and exposed interrupt
(all) must reach COMPLETE with full parity on status, booked costs,
estimates, cursor, fills, risk state, and store tables. Restart must
preserve the experiment — not merely event counts or zero-trade balances.

Derived from W2's /tmp acceptance tape+harness (durable here).
~10s for 6 bench runs. No network.
"""
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cryptobot.bench_run import main as bench_main

SYM = "BTCUSDT"
T0 = int(datetime(2026, 10, 11, 18, 24, tzinfo=timezone.utc).timestamp() * 1000)


def _gen_events():
    events = []
    seq = 0
    agg = 0

    def emit(ts, channel, payload):
        nonlocal seq
        seq += 1
        events.append({"channel": channel, "symbol": SYM,
                       "exchange_ts_ms": ts, "local_recv_ms": ts,
                       "seq": seq, "payload": payload})

    def second(i, price, aq=5.0, qty=0.5, tps=4):
        nonlocal agg
        for q in range(tps):
            ts = T0 + i * 1000 + q * (1000 // tps)
            emit(ts, "bookTicker", {"bid": round(price - 0.01, 2),
                                    "ask": round(price + 0.01, 2),
                                    "bid_qty": 5.0, "ask_qty": aq})
            agg += 1
            emit(ts + 10, "aggTrade",
                 {"agg_id": agg, "price": price, "qty": qty,
                  "buyer_is_maker": False})
            emit(ts + 100, "markPrice", {"mark": price})

    i = 0
    for _ in range(135):
        second(i, 100.00)
        i += 1
    for k in range(20):
        second(i, round(100.00 + 0.20 * (k + 1) / 20, 2))
        i += 1
    for k in range(30):
        second(i, round(100.20 + 0.06 * (k + 1) / 30, 2), aq=0.1)
        i += 1
    for k in range(12):
        second(i, 100.26, aq=0.1 if k < 3 else 5.0)
        i += 1
    for k in range(45):
        second(i, round(100.26 - (100.26 - 99.85) * (k + 1) / 45, 2))
        i += 1
    while i < 360:
        second(i, 99.85)
        i += 1
    for k in range(60):
        second(i, round(99.85 + (100.60 - 99.85) * (k + 1) / 60, 2))
        i += 1
    for _ in range(100):
        second(i, round(100.60 - 0.05, 2))
        i += 1
    return events


def _write_tape(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    events = _gen_events()
    ev_path = root / "events.jsonl"
    ev_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    toml = root / "cap.toml"
    toml.write_text(
        "[dataset]\nname = \"t\"\nkind = \"captured-runs\"\n"
        "manifest_version = 1\n\n[[source]]\nrun_id = \"t\"\n"
        "file = \"events.jsonl\"\n"
        f"local = \"{ev_path}\"\nsymbols = [\"{SYM}\"]\n")
    (root / "filters.json").write_text(json.dumps({"symbols": [{
        "symbol": SYM, "pricePrecision": 2, "quantityPrecision": 3,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001",
             "minQty": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5.0"}]}]}))
    return toml, root / "filters.json"


def _run_case(root: Path, name, toml, filters, resume_from=None,
              max_events=None):
    ck = root / name / "ck"
    if resume_from is None:
        shutil.rmtree(root / name, ignore_errors=True)
        (root / name).mkdir(parents=True)
    else:
        shutil.rmtree(ck, ignore_errors=True)
        shutil.copytree(root / resume_from / "ck", ck)
    args = ["--config", "configs/paper.toml", "--dataset", str(toml),
            "--symbol", SYM, "--days", "2026-10-11,2026-10-12",
            "--wall-budget-s", "600", "--commit-every", "250",
            "--checkpoint-dir", str(ck),
            "--report-out", str(root / name / "rep.json"),
            "--filters-file", str(filters), "--run-id", "acc"]
    if resume_from is not None:
        args.append("--resume")
    if max_events is not None:
        args += ["--max-events", str(max_events)]
    rc = bench_main(args)
    rep = json.loads((root / name / "rep.json").read_text())
    return rc, rep


def _evidence(root: Path, name):
    ck = root / name / "ck"
    rep = json.loads((root / name / "rep.json").read_text())
    work = ck / "work"
    db = sqlite3.connect(str(ck / "store.db"))
    try:
        store = {}
        for tbl in ("intents", "execution_events"):
            store[tbl] = db.execute(
                f"SELECT * FROM {tbl} ORDER BY id").fetchall()
        # risk_transitions stamps wall-clock in col 2: normalize.
        store["risk_transitions"] = [
            (r[0], r[1], r[3], r[4], r[5]) for r in db.execute(
                "SELECT * FROM risk_transitions ORDER BY id").fetchall()]
        cps = db.execute(
            "SELECT kind, payload FROM checkpoints ORDER BY id").fetchall()
    finally:
        db.close()
    store["checkpoints"] = [c for c in cps if c[0] != "bench-resume"]
    markers = sum(1 for c in cps if c[0] == "bench-resume")
    fills = work / "fills.jsonl"
    risk_state = work / "risk_state.json"
    return {
        "status": rep["status"],
        "booked": rep["booked"],
        "estimated_costs": rep.get("estimated_costs"),
        "cursor": rep.get("cursor"),
        "fills": fills.read_text() if fills.exists() else None,
        "risk_state": risk_state.read_text() if risk_state.exists() else None,
        "store": store,
        "resume_markers": markers,
    }


def test_restart_equivalence_with_trading_and_day_roll(tmp_path):
    root = tmp_path / "acc"
    root.mkdir()
    toml, filters = _write_tape(root / "tape")

    rc_ref, ref = _run_case(root, "ref", toml, filters)
    assert rc_ref == 0, ref
    assert ref["status"] == "COMPLETE", ref["status"]
    # The tape must actually trade at a loss (not a zero-trade parity).
    assert ref["booked"]["realised"] < 0, ref["booked"]
    assert ref["booked"]["commissions"] > 0, ref["booked"]
    assert ref["booked"]["valuation"] == "cash-exact", ref["booked"]

    _run_case(root, "det", toml, filters)
    _run_case(root, "flat_stop", toml, filters, max_events=1200)
    rc_flat, flat = _run_case(root, "flat", toml, filters,
                              resume_from="flat_stop")
    assert rc_flat == 0, flat
    _run_case(root, "expo_stop", toml, filters, max_events=3000)
    rc_expo, expo = _run_case(root, "expo", toml, filters,
                              resume_from="expo_stop")
    assert rc_expo == 0, expo

    base = _evidence(root, "ref")
    assert base["fills"], "reference run must have fills"
    for name in ("det", "flat", "expo"):
        got = _evidence(root, name)
        assert got["status"] == "COMPLETE", (name, got["status"])
        for key in ("booked", "estimated_costs", "cursor", "fills",
                    "risk_state"):
            assert got[key] == base[key], f"{name}: {key} differs"
        for tbl, rows in base["store"].items():
            assert got["store"][tbl] == rows, \
                f"{name}: store.{tbl} differs " \
                f"({len(got['store'][tbl])} vs {len(rows)} rows)"
        if name == "det":
            assert got["resume_markers"] == 0
        else:
            assert got["resume_markers"] == 1, name
