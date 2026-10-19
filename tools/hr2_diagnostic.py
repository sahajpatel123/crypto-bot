#!/usr/bin/env python3
"""H-R2 counterfactual diagnostic v2 (W4, REV2 R5 — CAUSAL CORRECTION).

Supersedes the v1 diagnostic reviewed in §3 (fills before decisions,
trigger-as-fill exits, mark carry-forward, invented funding bound).
Old figures are archived under outputs/hr2/superseded/.

Outputs are COUNTERFACTUAL DIAGNOSTICS, never portfolio P&L or
strategy trades. 30/60/120/300s markouts are predeclared.

Corrected method (all timestamps exchange-time, ms):
- Decision = candidate evaluated_now_utc (strategy evaluation time).
  Submission = decision + 50ms (R01 submit_delay_ms); fill observation
  = first bookTicker at/after decision + 100ms (+50ms fill_delay_ms).
  NO FILL CAN PRECEDE THE DECISION (asserted per row + audited).
- Quote-age rule: latest book-or-trade at/before decision must be
  within 1000ms (R01 quote_max_age_s); else unscorable(stale).
- Entry: IOC at arrival touch vs band cap (LONG ask<=entry_high,
  SHORT bid>=entry_low), else unfilled(unmarketable); arrival past
  entry_expiry -> unfilled(expired); fill qty = min($20 unit,
  displayed size); short size -> partial.
- Exits: aggTrade prints strictly after fill_ts in (ts, agg_id)
  order; stop/target first touch is a TRIGGER ONLY. Executable exit
  = exit-side touch of first book at/after trigger+100ms (LONG->bid,
  SHORT->ask); equal-ts stop/target -> stop first. No book after
  trigger -> unscorable. Time exit: decision at time_exit_utc ->
  first book at/after time_exit+100ms.
- Coverage: exits/markouts require capture data through the event;
  horizons without book/trade coverage within 5s are
  unscorable(unsupported-horizon). Marks older than 5s are never
  carried forward (markPrice cadence is 1s).
- Costs: 5bps/leg schedule fees; spread/slippage 0 added (contained
  in touch fills + arrival latency); funding from ASSERTED
  next_funding_ms boundaries only (engine rule: settle iff a sourced
  boundary falls in (fill, exit], at the latest asserted rate;
  rate>0 longs pay). No boundary -> 0 with provenance. No
  markPrice in window -> funding unknown (never invented, never
  silently zero).
- Portfolio overlay: time-ordered on DECISION ts, one-position rule
  (busy until exit fill), 300s strategy cooldown; diagnostic only.
Subcommands: extract | evaluate | portfolio | all | audit
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
# Frozen execution semantics (R01 engine config + app defaults).
SUBMIT_DELAY_MS = 50
FILL_DELAY_MS = 50
ARRIVAL_OFFSET_MS = SUBMIT_DELAY_MS + FILL_DELAY_MS  # 100
QUOTE_MAX_AGE_MS = 1000
MARK_MAX_AGE_MS = 5000
COVERAGE_MS = 5000
FEE_BPS_PER_LEG = 5.0
UNIT_NOTIONAL_USDT = 20.0
COOLDOWN_S = 300.0
MARKOUT_S = (30, 60, 120, 300)
KEEP_CHANNELS = ("bookTicker", "aggTrade", "markPrice")
WIN_PRE_MS = 5000
WIN_POST_MS = 320000

WORKDIR = OUT / "windows"


def _ms(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def load_candidates():
    rows = json.load(open(CANDIDATES))
    for r in rows:
        r["_ev_ms"] = _ms(r["evidence_ts_utc"])
        r["_dec_ms"] = _ms(r["evaluated_now_utc"])
    return rows


def _capture_span(path):
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
    WORKDIR.mkdir(exist_ok=True)
    for old in WORKDIR.glob("*.jsonl"):
        old.unlink()
    cands = sorted(load_candidates(), key=lambda r: r["_dec_ms"])
    manifest = {}
    for cap, path in CAPTURES.items():
        cap_first, cap_last = _capture_span(path)
        mine = [r for r in cands
                if r["_dec_ms"] - WIN_PRE_MS <= cap_last
                and r["_dec_ms"] + WIN_POST_MS >= cap_first]
        starts = {r["_dec_ms"] - WIN_PRE_MS: r for r in mine}
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
                        "fh": open(WORKDIR / f"{key}.{cap}.jsonl", "w"),
                        "end": r["_dec_ms"] + WIN_POST_MS}
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
        path = WORKDIR / f"{ref}.{cap}.jsonl"
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
                    marks.append((ts, float(p["mark"]),
                                  p.get("funding_rate"),
                                  p.get("next_funding_ms")))
    books.sort()
    prints.sort()
    marks.sort()
    return books, prints, marks


def _first_book_at_or_after(books, ts):
    for b in books:
        if b[0] >= ts:
            return b
    return None


def _latest_obs_at_or_before(books, prints, ts):
    best = None
    for seq in (books, prints):
        for row in seq:
            if row[0] <= ts:
                if best is None or row[0] > best:
                    best = row[0]
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
    return best


def _funding_for_hold(marks, fill_ms, exit_ms, side, qty, ref_px):
    """Engine-rule funding: settle iff a SOURCED boundary falls in hold.

    Returns (amount_usdt_or_None, provenance). None amount = unknown
    (no markPrice in window); never invented, never silently zero.
    """
    if not marks:
        return None, "unknown(no-markPrice-in-window)"
    rate, boundary = None, None
    for ts, _mark, fr, nfm in marks:
        if ts > exit_ms:
            break
        if fr is not None:
            rate = float(fr)
        if nfm:
            boundary = int(nfm)
    if boundary is None:
        return None, "unknown(no-asserted-boundary)"
    if not (fill_ms < boundary <= exit_ms):
        return 0.0, "zero(no-settlement-boundary-in-hold)"
    if rate is None:
        return None, "unknown(no-asserted-rate)"
    sgn = 1.0 if side == "LONG" else -1.0
    amount = -sgn * qty * ref_px * rate  # rate>0: longs pay.
    return amount, (f"settled boundary {boundary} at rate {rate}")


def evaluate_one(row):
    """Causal counterfactual diagnostic for one candidate (never a trade)."""
    out = {"ref": row["evidence_ref"], "strategy": row["strategy"],
           "side": row["side"], "instrument": row["instrument"]}
    ev = row["_ev_ms"]
    dec = row["_dec_ms"]
    out["evidence_ts_utc"] = _iso(ev)
    out["decision_ts_utc"] = _iso(dec)
    out["submit_ts_utc"] = _iso(dec + SUBMIT_DELAY_MS)
    expiry = _ms(row["entry_expiry_utc"])
    books, prints, marks = _load_window(row["evidence_ref"])
    # Quote-age rule at decision: market must be observable then.
    latest = _latest_obs_at_or_before(books, prints, dec)
    if latest is None or dec - latest > QUOTE_MAX_AGE_MS:
        out["entry"] = "unscorable(stale-at-decision)"
        return out
    arr = _first_book_at_or_after(books, dec + ARRIVAL_OFFSET_MS)
    if arr is None:
        out["entry"] = "unscorable(no-book-after-arrival)"
        return out
    out["arrival_latency_ms"] = arr[0] - dec
    assert arr[0] >= dec, "CAUSALITY: fill book precedes decision"
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


    def exit_fill(trigger_ms):
        book = _first_book_at_or_after(books, trigger_ms + FILL_DELAY_MS)
        if book is None:
            return None
        px = book[1] if long else book[2]  # exit-side touch.
        return px, book[0]

    # Triggers on prints strictly after the fill (same-ms unorderable).
    trig_stop = trig_tgt = None
    for ts, _aid, px, _q in prints:
        if ts <= arr[0]:
            continue
        if ts > t_exit:
            break
        hit_stop = (px <= stop) if long else (px >= stop)
        hit_tgt = (px >= target) if long else (px <= target)
        if hit_stop and trig_stop is None:
            trig_stop = ts
        if hit_tgt and trig_tgt is None:
            trig_tgt = ts
        if trig_stop is not None and trig_tgt is not None:
            break
    winner = None
    if trig_stop is not None and (trig_tgt is None
                                  or trig_stop <= trig_tgt):
        winner = "stop"
        trig = trig_stop
    elif trig_tgt is not None:
        winner = "target"
        trig = trig_tgt
    if winner is not None:
        got = exit_fill(trig)
        if got is None:
            out["exit"] = "unscorable(no-book-after-trigger)"
            return out
        exit_px, exit_ts = got
        out["trigger_ts_utc"] = _iso(trig)
    else:
        last_ev = max([b[0] for b in books] + [p[0] for p in prints]
                      or [0])
        if t_exit > last_ev:
            out["exit"] = "unscorable(capture-ends-before-time-exit)"
            return out
        got = exit_fill(t_exit)
        if got is None:
            out["exit"] = "unscorable(no-book-at-time-exit)"
            return out
        exit_px, exit_ts = got
        winner = "time"
    out["exit"] = winner
    out["exit_ts_utc"] = _iso(exit_ts)
    out["exit_price"] = exit_px
    sgn = 1.0 if long else -1.0
    gross_bps = sgn * (exit_px - touch) / touch * 10000.0
    fund_amt, fund_prov = _funding_for_hold(
        marks, arr[0], exit_ts, row["side"], fill_qty, touch)
    fund_bps = (fund_amt / (fill_qty * touch) * 10000.0
                if fund_amt else 0.0)
    out["gross_bps"] = round(gross_bps, 4)
    out["funding_usdt"] = fund_amt
    out["funding_bps"] = round(fund_bps, 4) if fund_amt is not None else None
    out["funding_provenance"] = fund_prov
    out["net_bps"] = round(gross_bps - 2 * FEE_BPS_PER_LEG + fund_bps, 4)
    out["cost_note"] = ("fees 5bps/leg labeled; spread/slippage 0 added "
                        "(in touch fills); funding: " + fund_prov)
    out["markouts_bps"] = {}
    for horizon in MARKOUT_S:
        mts = arr[0] + horizon * 1000
        mark = _mark_at(marks, mts)
        cov = _latest_obs_at_or_before(books, prints, mts)
        if mark is None or mts - mark[0] > MARK_MAX_AGE_MS:
            out["markouts_bps"][str(horizon)] = "unscorable(stale-mark)"
        elif cov is None or mts - cov > COVERAGE_MS:
            out["markouts_bps"][str(horizon)] = \
                "unscorable(unsupported-horizon)"
        else:
            out["markouts_bps"][str(horizon)] = round(
                sgn * (mark[1] - touch) / touch * 10000.0
                - 2 * FEE_BPS_PER_LEG, 4)
    return out


def cmd_evaluate(_args):
    rows = [evaluate_one(r) for r in load_candidates()]
    json.dump(rows, open(OUT / "diagnostics.json", "w"), indent=1)
    by_entry, by_exit = {}, {}
    for r in rows:
        by_entry[r.get("entry", "?")] = by_entry.get(r.get("entry"), 0) + 1
        by_exit[str(r.get("exit", "-"))] = \
            by_exit.get(str(r.get("exit", "-")), 0) + 1
    print(json.dumps({"n": len(rows), "entry": by_entry,
                      "exit": by_exit}, indent=1))


def cmd_portfolio(_args):
    diags = {d["ref"]: d
             for d in json.load(open(OUT / "diagnostics.json"))}
    cands = sorted(load_candidates(), key=lambda r: r["_dec_ms"])
    admitted, skipped, busy_until = [], [], 0
    last_by_strategy = {}
    for r in cands:
        d = diags[r["evidence_ref"]]
        if d.get("entry") not in ("filled", "partial") or "exit" not in d \
                or str(d["exit"]).startswith("unscorable"):
            skipped.append((r["evidence_ref"], "no-executable-outcome"))
            continue
        if r["_dec_ms"] < busy_until:
            skipped.append((r["evidence_ref"], "one-position-busy"))
            continue
        if r["_dec_ms"] - last_by_strategy.get(r["strategy"], -10**18) \
                < COOLDOWN_S * 1000:
            skipped.append((r["evidence_ref"], "cooldown"))
            continue
        admitted.append(r["evidence_ref"])
        last_by_strategy[r["strategy"]] = r["_dec_ms"]
        busy_until = _ms(d["exit_ts_utc"])
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


def cmd_audit(_args):
    """Independent causality audit over diagnostics.json (fails loud)."""
    diags = json.load(open(OUT / "diagnostics.json"))
    cands = {r["evidence_ref"]: r for r in load_candidates()}
    assert len(diags) == 61, f"expected 61 rows, got {len(diags)}"
    assert {d["ref"] for d in diags} == set(cands), "ref set mismatch"
    violations = []
    for d in diags:
        ref = d["ref"]
        dec = cands[ref]["_dec_ms"]
        if "fill_ts_utc" in d:
            fill = _ms(d["fill_ts_utc"])
            if fill < dec + ARRIVAL_OFFSET_MS:
                violations.append((ref, "fill-before-arrival", d["fill_ts_utc"]))
        if "exit_ts_utc" in d and "fill_ts_utc" in d:
            if _ms(d["exit_ts_utc"]) < _ms(d["fill_ts_utc"]):
                violations.append((ref, "exit-before-fill", d["exit_ts_utc"]))
        if "trigger_ts_utc" in d and "fill_ts_utc" in d:
            if _ms(d["trigger_ts_utc"]) <= _ms(d["fill_ts_utc"]):
                violations.append((ref, "trigger-not-after-fill",
                                   d["trigger_ts_utc"]))
    print(json.dumps({"rows": len(diags), "violations": violations,
                      "verdict": "CAUSAL" if not violations else "VIOLATED"},
                     indent=1))
    if violations:
        raise SystemExit(1)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("command", choices=("extract", "evaluate", "portfolio",
                                       "all", "audit"))
    args = p.parse_args(argv)
    if args.command in ("extract", "all"):
        cmd_extract(args)
    if args.command in ("evaluate", "all"):
        cmd_evaluate(args)
    if args.command in ("portfolio", "all"):
        cmd_portfolio(args)
    if args.command in ("audit", "all"):
        cmd_audit(args)


if __name__ == "__main__":
    main()
