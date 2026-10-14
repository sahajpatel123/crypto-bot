#!/usr/bin/env python3
"""H-R2 counterfactual diagnostic (manager-owned, release §6).

Measures executable forward outcomes for the 61 frozen S1/S3 candidates
on the reused captures. Outputs are COUNTERFACTUAL DIAGNOSTICS, never
portfolio P&L or strategy trades. 30/60/120/300s markouts are predeclared.

Method (disclosed; see outputs/hr2/report.json for per-candidate rows):
- Windows extracted in ONE bounded-memory streaming pass per capture:
  [evidence_ts - 5s, evidence_ts + 320s], ETHUSDT bookTicker/aggTrade/
  markPrice only. No replay, no strategy re-evaluation.
- Arrival = first bookTicker at/after evidence_ts. Latency reported.
  No book → unscorable(no-book); arrival past entry_expiry → unfilled.
- IOC at arrival touch (LONG: ask ≤ entry_high cap; SHORT: bid ≥
  entry_low floor), else unfilled(unmarketable). Fill qty =
  min(unit_qty, displayed size); short size → partial, remainder
  cancels. Unit qty = $20 notional at arrival (DIAGNOSTIC CONSTANT,
  disclosed; top-of-book cannot justify unlimited size).
- Forward: aggTrade prints in (ts, agg_id) order; stop/target first
  touch wins; equal-ts → stop first (conservative). Time exit at the
  candidate's time_exit_utc at then-touch (reported leg).
- Costs: 5bps/leg labeled schedule fees; spread ZERO added (touch
  fills contain it); slippage ZERO added (latency move is implicit in
  arrival price); funding EXCLUDED with quantified bound (≤300s hold
  vs 8h settlement ≈ 0.01bp at 1bp/8h — negligible, stated).
- Markouts at 30/60/120/300s from fill on markPrice, net of the above.
  Capture end before a horizon → that horizon unscorable (per-leg).
- Portfolio overlay: time-ordered selection with one-position rule +
  300s strategy cooldown; overlapping candidates queue/skip (reported).
Subcommands: extract | evaluate | portfolio | all
"""
import argparse
import json
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "outputs" / "ready-phasea" / "candidates.json"
OUT = ROOT / "outputs" / "hr2"
CAPTURES = {
    "cap-30min": "/Users/sahajpatel/Code/cryto-bot/data/captures/cap-30min/events.jsonl",
    "cap-2h": "/Users/sahajpatel/Code/cryto-bot/data/captures/cap-2h/events.jsonl",
}
FEE_BPS_PER_LEG = 5.0
UNIT_NOTIONAL_USDT = 20.0
COOLDOWN_S = 300.0
MARKOUT_S = (30, 60, 120, 300)
KEEP_CHANNELS = ("bookTicker", "aggTrade", "markPrice")


def _ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def load_candidates():
    rows = json.load(open(CANDIDATES))
    for r in rows:
        r["_ev_ms"] = _ms(r["evidence_ts_utc"])
    return rows


def _capture_span(path):
    """(first_ms, last_ms) from head/tail (captures are ts-ordered)."""
    with open(path, encoding="utf-8") as fh:
        head = [json.loads(next(fh)) for _ in range(5)]
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 65536))
        tail = [json.loads(ln) for ln in fh.read().decode().splitlines()
                if ln.strip().startswith("{")]
    first = min(int(e.get("exchange_ts_ms", 0) or 0) for e in head)
    last = max(int(e.get("exchange_ts_ms", 0) or 0) for e in tail[-5:])
    return first, last


def cmd_extract(_args):
    OUT.mkdir(parents=True, exist_ok=True)
    win_dir = OUT / "windows"
    win_dir.mkdir(exist_ok=True)
    # Clear stale windows from earlier runs (namespaced per capture).
    for old in win_dir.glob("*.jsonl"):
        old.unlink()
    cands = sorted(load_candidates(), key=lambda r: r["_ev_ms"])
    manifest = {}
    for cap, path in CAPTURES.items():
        cap_first, cap_last = _capture_span(path)
        # Only candidates whose window intersects this capture's span.
        mine = [r for r in cands
                if r["_ev_ms"] - 5000 <= cap_last
                and r["_ev_ms"] + 320000 >= cap_first]
        starts = {r["_ev_ms"] - 5000: r for r in mine}
        active = {}
        counts = {"events_seen": 0, "events_kept": 0, "windows": 0,
                  "span": [_iso(cap_first), _iso(cap_last)]}
        order = deque(sorted(starts))
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                counts["events_seen"] += 1
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("symbol") != "ETHUSDT":
                    continue
                if e.get("channel") not in KEEP_CHANNELS:
                    continue
                ts = int(e.get("exchange_ts_ms", 0) or 0)
                while order and order[0] <= ts:
                    r = starts[order.popleft()]
                    key = r["evidence_ref"]
                    active[key] = {
                        "fh": open(win_dir / f"{key}.{cap}.jsonl", "w"),
                        "end": r["_ev_ms"] + 320000}
                done = [k for k, a in active.items() if ts > a["end"]]
                for k in done:
                    active[k]["fh"].close()
                    del active[k]
                    counts["windows"] += 1
                for a in active.values():
                    a["fh"].write(json.dumps(e) + "\n")
                    counts["events_kept"] += 1
        for k, a in active.items():
            a["fh"].close()
            counts["windows"] += 1
        manifest[cap] = counts
    json.dump(manifest, open(OUT / "extract_manifest.json", "w"), indent=1)
    print(json.dumps(manifest, indent=1))


def _load_window(ref):
    books, prints, marks = [], [], []
    for cap in CAPTURES:
        path = OUT / "windows" / f"{ref}.{cap}.jsonl"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                ch = e.get("channel")
                ts = int(e.get("exchange_ts_ms", 0) or 0)
                p = e.get("payload", {})
                if ch == "bookTicker":
                    books.append((ts, float(p["bid"]), float(p["ask"]),
                                  float(p.get("bid_qty", 0) or 0),
                                  float(p.get("ask_qty", 0) or 0)))
                elif ch == "aggTrade":
                    prints.append((ts, int(p.get("agg_id", 0)),
                                   float(p["price"]),
                                   float(p.get("qty", 0) or 0)))
                elif ch == "markPrice":
                    marks.append((ts, float(p["mark"])))
    books.sort()
    prints.sort()
    marks.sort()
    return books, prints, marks


def _touch_at(books, ts):
    best = None
    for b in books:
        if b[0] <= ts:
            best = b
        else:
            break
    return best


def _mark_at(marks, ts):
    best = None
    for m in marks:
        if m[0] <= ts:
            best = m
        else:
            break
    return best[1] if best else None


def evaluate_one(row):
    """Counterfactual diagnostic for one candidate (never a trade)."""
    out = {"ref": row["evidence_ref"], "strategy": row["strategy"],
           "side": row["side"], "instrument": row["instrument"]}
    ev = row["_ev_ms"]
    expiry = _ms(row["entry_expiry_utc"])
    books, prints, marks = _load_window(row["evidence_ref"])
    after = [b for b in books if b[0] >= ev]
    if not after:
        out["entry"] = "unscorable(no-book)"
        return out
    arr = after[0]
    out["arrival_latency_ms"] = arr[0] - ev
    if arr[0] > expiry:
        out["entry"] = "unfilled(expired)"
        return out
    long = row["side"] == "LONG"
    touch, size = (arr[2], arr[4]) if long else (arr[1], arr[3])
    cap = row["entry_high"] if long else row["entry_low"]
    marketable = (touch <= cap) if long else (touch >= cap)
    if not marketable:
        out["entry"] = "unfilled(unmarketable)"
        out["arrival_touch"] = touch
        return out
    unit_qty = UNIT_NOTIONAL_USDT / touch
    fill_qty = min(unit_qty, size) if size > 0 else 0.0
    if fill_qty <= 0:
        out["entry"] = "unscorable(zero-size)"
        return out
    out["entry"] = "filled" if fill_qty >= unit_qty else "partial"
    out["fill_ts_utc"] = _iso(arr[0])
    out["fill_price"] = touch
    out["fill_qty"] = fill_qty
    out["unit_qty"] = unit_qty
    stop, target = row["stop_price"], row["target_price"]
    t_exit = _ms(row["time_exit_utc"])
    # Forward exits in causal print order; equal-ts → stop first.
    winner, exit_px, exit_ts = None, None, None
    for ts, _aid, px, _q in prints:
        if ts < arr[0]:
            continue
        if ts > t_exit:
            break
        hit_stop = (px <= stop) if long else (px >= stop)
        hit_tgt = (px >= target) if long else (px <= target)
        if hit_stop:
            winner, exit_px, exit_ts = "stop", px, ts
            break
        if hit_tgt:
            winner, exit_px, exit_ts = "target", px, ts
            break
    last_print_ts = max([p[0] for p in prints] or [0])
    if winner is None:
        if t_exit > last_print_ts and last_print_ts > 0:
            out["exit"] = "unscorable(capture-ends-before-time-exit)"
            return out
        tb = _touch_at(books, t_exit)
        if tb is None:
            out["exit"] = "unscorable(no-book-at-time-exit)"
            return out
        exit_px = tb[1] if long else tb[2]  # exit at adverse touch.
        exit_ts, winner = t_exit, "time"
    out["exit"] = winner
    out["exit_ts_utc"] = _iso(exit_ts)
    out["exit_price"] = exit_px
    sgn = 1.0 if long else -1.0
    gross_bps = sgn * (exit_px - touch) / touch * 10000.0
    out["gross_bps"] = round(gross_bps, 4)
    out["net_bps"] = round(gross_bps - 2 * FEE_BPS_PER_LEG, 4)
    out["cost_note"] = ("fees 5bps/leg labeled; spread/slippage 0 added "
                        "(in touch fills); funding excluded (≤0.01bp bound)")
    out["markouts_bps"] = {}
    for horizon in MARKOUT_S:
        mts = arr[0] + horizon * 1000
        mpx = _mark_at(marks, mts)
        if mpx is None:
            out["markouts_bps"][str(horizon)] = "unscorable(no-mark)"
        else:
            out["markouts_bps"][str(horizon)] = round(
                sgn * (mpx - touch) / touch * 10000.0
                - 2 * FEE_BPS_PER_LEG, 4)
    return out


def cmd_evaluate(_args):
    rows = [evaluate_one(r) for r in load_candidates()]
    json.dump(rows, open(OUT / "diagnostics.json", "w"), indent=1)
    by_entry, by_exit = {}, {}
    for r in rows:
        by_entry[r.get("entry", "?")] = by_entry.get(r.get("entry"), 0) + 1
        by_exit[r.get("exit", "-")] = by_exit.get(r.get("exit"), 0) + 1
    print(json.dumps({"n": len(rows), "entry": by_entry,
                      "exit": by_exit}, indent=1))


def cmd_portfolio(_args):
    diags = {d["ref"]: d
             for d in json.load(open(OUT / "diagnostics.json"))}
    cands = sorted(load_candidates(), key=lambda r: r["_ev_ms"])
    admitted, skipped, busy_until = [], [], 0
    last_by_strategy = {}
    for r in cands:
        d = diags[r["evidence_ref"]]
        if d.get("entry") not in ("filled", "partial") or "exit" not in d \
                or str(d["exit"]).startswith("unscorable"):
            skipped.append((r["evidence_ref"], "no-executable-outcome"))
            continue
        if r["_ev_ms"] < busy_until:
            skipped.append((r["evidence_ref"], "one-position-busy"))
            continue
        if r["_ev_ms"] - last_by_strategy.get(r["strategy"], -10**18) \
                < COOLDOWN_S * 1000:
            skipped.append((r["evidence_ref"], "cooldown"))
            continue
        admitted.append(r["evidence_ref"])
        last_by_strategy[r["strategy"]] = r["_ev_ms"]
        busy_until = _ms(r["time_exit_utc"])
    seq = [diags[ref] for ref in admitted]
    nets = [d["net_bps"] for d in seq]
    rep = {"admitted": admitted, "skipped": skipped,
           "n": len(seq),
           "sum_net_bps": round(sum(nets), 4) if nets else 0.0,
           "mean_net_bps": round(sum(nets) / len(nets), 4) if nets else None,
           "label": "COUNTERFACTUAL DIAGNOSTIC SEQUENCE, not portfolio P&L"}
    json.dump(rep, open(OUT / "portfolio.json", "w"), indent=1)
    print(json.dumps({k: (v if k != "skipped" else len(v))
                      for k, v in rep.items()}, indent=1))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("command", choices=("extract", "evaluate", "portfolio",
                                       "all"))
    args = p.parse_args(argv)
    if args.command in ("extract", "all"):
        cmd_extract(args)
    if args.command in ("evaluate", "portfolio", "all"):
        if args.command in ("evaluate", "all"):
            cmd_evaluate(args)
        cmd_portfolio(args)


if __name__ == "__main__":
    main()
