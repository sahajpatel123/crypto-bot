#!/usr/bin/env python3
"""Independent metric reconciliation for runs and benchmark cells (W5-24H).

Read-only: recomputes economics from canonical records (ledger journal,
engine journal, fills/equity JSONL) and checks agreement with reported
metrics. Verdicts per run:

- RECONCILED: fills exist, books agree, position flat, economics match.
- OPEN: books agree but Clarify position is non-flat at run end (marked
  value needs separate review; never scored as closed profit).
- VACUOUS: zero fills, so entry/protection/exit are UNVERIFIED. Never a
  pass; carries the honest reason (never evaluated / rejected with
  reasons / UNEXPLAINED when even the reason trail is empty).
- MISMATCH: books disagree. Loud failure.

Exit 1 iff any MISMATCH, else 0.

Usage:
    reconcile.py --run runs/<id> [--run ...] [--comparison <comparison.json>
      --runs-root <runs/>] --out <report.json>
"""
import argparse
import json
import sys
from pathlib import Path

TOL = 1e-6


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None


def _load_jsonl(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return [json.loads(line) for line in lines if line.strip()]


def _close(a, b, tol=TOL):
    return abs(float(a) - float(b)) <= tol


def _ledger_fill_key(fill):
    side = str(fill.get("side", "")).upper()
    return (side, round(float(fill.get("qty", 0.0)), 9),
            round(float(fill.get("price", 0.0)), 9),
            round(float(fill.get("fee", 0.0)), 9))


def _economics(fills):
    # BUY opens (cash outflow, +qty); SELL closes (inflow, -qty).
    gross, fees, netqty = 0.0, 0.0, 0.0
    for fill in fills:
        side = str(fill.get("side", "")).upper()
        qty = float(fill.get("qty", 0.0))
        price = float(fill.get("price", 0.0))
        if side == "BUY":
            gross -= qty * price
            netqty += qty
        else:
            gross += qty * price
            netqty -= qty
        fees += float(fill.get("fee", 0.0))
    return {"gross": gross, "fees": fees, "net": gross - fees,
            "net_qty": netqty, "n": len(fills)}


def reconcile_run(run_dir):
    """Reconcile one Session run dir or benchmark cell dir."""
    run_dir = Path(run_dir)
    checks = []
    report = _load_json(run_dir / "report.json")
    ledger = _load_json(run_dir / "ledger.json")
    if report is None or ledger is None:
        return {"run": str(run_dir), "verdict": "MISMATCH", "checks": [{
            "name": "canonical-records-present", "ok": False,
            "detail": "report.json or ledger.json missing"}]}
    fills = [j for j in ledger.get("journal", [])
             if j.get("kind") == "fill"]
    snap = ledger.get("snapshot", {})
    econ = _economics(fills)

    def check(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    # -- canonical identity ------------------------------------------------
    exec_ids = [f.get("exec_id") for f in fills]
    check("exec-ids-unique", len(set(exec_ids)) == len(exec_ids),
          f"n={len(exec_ids)} unique={len(set(exec_ids))}")
    # -- ledger internal agreement ------------------------------------------
    check("fees-agree", _close(econ["fees"], snap.get("paid_costs", 0.0)),
          f"fills {econ['fees']:.6f} vs snapshot {snap.get('paid_costs')}")
    check("realised-agree", _close(econ["net"], snap.get("realised", 0.0)),
          f"fills-net {econ['net']:.6f} vs snapshot {snap.get('realised')}")
    check("ledger-qty-flat", abs(econ["net_qty"]) <= 1e-9
          and abs(float(snap.get("qty", 0.0))) <= 1e-9,
          f"fills-net {econ['net_qty']} snapshot-qty {snap.get('qty')}")
    # -- report agreement ----------------------------------------------------
    check("report-paid-costs",
          _close(report.get("paid_costs", 0.0), snap.get("paid_costs", 0.0)),
          f"report {report.get('paid_costs')} vs ledger "
          f"{snap.get('paid_costs')}")
    check("report-realised",
          _close(report.get("realised", 0.0), snap.get("realised", 0.0)),
          f"report {report.get('realised')} vs ledger "
          f"{snap.get('realised')}")
    check("report-funding",
          _close(report.get("funding_net", 0.0), snap.get("funding_net", 0.0)),
          f"report {report.get('funding_net')} vs ledger "
          f"{snap.get('funding_net')}")
    opening = float(report.get("opening_equity", 0.0))
    closing = float(report.get("closing_equity", 0.0))
    expect_pct = (closing - opening) / opening * 100 if opening else 0.0
    check("report-net-pct", _close(report.get("net_return_pct", 0.0),
                                   expect_pct, tol=1e-4),
          f"report {report.get('net_return_pct')} vs recomputed {expect_pct}")
    cash = snap.get("cash")
    if cash is not None and abs(econ["net_qty"]) <= 1e-9:
        check("cash-closes", _close(cash, opening + econ["net"]
                                    + float(snap.get("funding_net", 0.0))),
              f"cash {cash} vs opening+net+funding "
              f"{opening + econ['net'] + float(snap.get('funding_net', 0.0))}")
    # -- corroborating files --------------------------------------------------
    fills_file = _load_jsonl(run_dir / "fills.jsonl")
    new_layout = any((run_dir / name).exists() for name in
                     ("equity.jsonl", "store.db", "fills.jsonl",
                      "engine_journal.jsonl"))
    if fills_file is None or len(fills_file) == 0:
        check("fills-jsonl-present",
              len(fills) == 0 or not new_layout,
              "fills.jsonl missing/empty; ledger journal is canonical"
              f" (old layout, excused)" if fills and not new_layout else
              (f"fills.jsonl missing/empty but ledger holds {len(fills)}"
               if fills else "no fills anywhere; consistent"))
    else:
        check("fills-jsonl-count", len(fills_file) == len(fills),
              f"file {len(fills_file)} vs ledger {len(fills)}")
    equity = _load_jsonl(run_dir / "equity.jsonl")
    if equity:
        last = equity[-1]
        marked = last.get("marked_equity", last.get("equity"))
        if marked is not None and abs(econ["net_qty"]) <= 1e-9:
            check("equity-curve-closes", _close(marked, closing),
                  f"curve {marked} vs report {closing}")
    else:
        check("equity-curve-present", True, "absent (old layout); skipped")
    journal = _load_jsonl(run_dir / "engine_journal.jsonl")
    if journal is not None:
        jfills = [r.get("detail", r.get("Detail", {})) for r in journal
                  if r.get("event") == "fill"]
        jkeys = sorted((_k("BUY" if str(f.get("venue_side", "")).upper()
                             .startswith("B") else "SELL",
                           f.get("qty"), f.get("price"), f.get("fee"))
                        for f in jfills))
        lkeys = sorted((_k(*k) for k in
                        (_ledger_fill_key(f) for f in fills)))
        check("engine-ledger-fills-agree", jkeys == lkeys,
              f"journal {len(jkeys)} vs ledger {len(lkeys)} fill keys")
    # -- verdict ----------------------------------------------------------------
    if not fills:
        strat_n = ((report.get("latency_ms") or {}).get("strategy_eval")
                   or {}).get("n", 0)
        intents = (report.get("store_counts") or {}).get("intents", 0)
        rej_file = _load_jsonl(run_dir / "rejections.jsonl") or []
        rej_counts = report.get("reject_counts") or {}
        if not strat_n and not intents:
            reason = ("strategies never evaluated "
                      f"(strategy_eval n={strat_n}, intents={intents}); "
                      "warmup/readiness gated the whole run")
        elif rej_file or rej_counts:
            reason = (f"evaluated, all rejected with reasons "
                      f"({len(rej_file)} lines, {len(rej_counts)} classes)")
        else:
            reason = ("UNEXPLAINED: evaluated/intents with no recorded "
                      "rejection reasons")
            checks.append({"name": "rejection-trail-present", "ok": False,
                           "detail": reason})
        econ_ok = all(c["ok"] for c in checks)
        return {"run": str(run_dir), "verdict":
                "MISMATCH" if not econ_ok else "VACUOUS",
                "reason": reason, "checks": checks,
                "economics": econ}
    flat = abs(econ["net_qty"]) <= 1e-9
    econ_ok = all(c["ok"] for c in checks)
    if not econ_ok:
        verdict = "MISMATCH"
    elif not flat:
        verdict = "OPEN"
    else:
        verdict = "RECONCILED"
    return {"run": str(run_dir), "verdict": verdict, "checks": checks,
            "economics": econ,
            "exposure": {"fills": len(fills),
                         "round_trip_flat": flat,
                         "note": "entry+exit legs verified under exposure; "
                                 "per-fill exit-reason attribution "
                                 "unavailable in canonical records"}}


def _k(side, qty, price, fee):
    return (str(side).upper(), round(float(qty or 0.0), 9),
            round(float(price or 0.0), 9), round(float(fee or 0.0), 9))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", default=[])
    parser.add_argument("--comparison", default=None)
    parser.add_argument("--runs-root", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    results = []
    for run in args.run:
        results.append(reconcile_run(run))
    if args.comparison:
        comp = _load_json(args.comparison)
        cells = (comp or {}).get("cells", {})
        for key, cell in cells.items():
            armset, _, split = key.partition("|")
            armset, split = (cell.get("armset"), cell.get("split")) \
                if "armset" in cell else (armset, split or "dev")
            cand = (Path(args.runs_root or "") / split / armset
                    if args.runs_root else None)
            entry = {"cell": key, "metrics": {
                k: cell.get(k) for k in
                ("closing_equity", "net_return_pct", "paid_costs",
                 "funding_net", "realised", "intents_admitted",
                 "events_seen")}}
            if cand is not None and (cand / "report.json").exists():
                entry["run_verdict"] = reconcile_run(cand)
            else:
                entry["run_verdict"] = {
                    "verdict": "MISMATCH", "checks": [{
                        "name": "cell-canonical-present", "ok": False,
                        "detail": f"no run dir at {cand}"}]}
            results.append(entry)
    mismatch = any(
        (r.get("verdict") == "MISMATCH")
        or ((r.get("run_verdict") or {}).get("verdict") == "MISMATCH")
        for r in results)
    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    for r in results:
        if "run_verdict" in r:
            print(f"{r['cell']}: {r['run_verdict']['verdict']}")
        else:
            extra = f" ({r.get('reason', '')})" if r.get("reason") else ""
            print(f"{r['run']}: {r['verdict']}{extra}")
    return 1 if mismatch else 0


if __name__ == "__main__":
    raise SystemExit(main())
