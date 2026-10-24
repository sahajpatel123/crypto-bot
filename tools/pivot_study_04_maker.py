"""STUDY-04: P1 maker-spread measurement (read-only, manager-owned).

Preregistered in reports/pivot/P1-CAMPAIGN-PREREG-2026-10-17.md BEFORE the
campaign settled. Streams campaign chunks (chunk-*/events.jsonl.gz, plain
fallback), simulates two-sided $500-notional quotes behind displayed
top-of-book size, depletes queues by causal taker flow through the level,
applies the preregistered 5bps/10s toxicity filter with 30s cooldown, and
scores spread capture net of maker fees + fill+5s markout.

Optimistic by construction: $500 size = no impact, displayed depth fully
real, fills at quoted price. A NONE under these assumptions is robust.

Exit 0 results written; 2 input/contract error.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

EXIT_BLOCKED = 2
SIZE_NOTIONAL = 500.0
FEE_BPS_SIDE = 2.0       # realistic (Binance VIP0 maker, no rebate)
FEE_BPS_SIDE_ADV = 4.0   # adverse 2x
TOX_BPS = 5.0
TOX_S = 10.0
COOLDOWN_S = 30.0
GAP_CANCEL_MS = 5000
MARKOUT_S = 5
MIN_FILLS = 100


def _open_events(path: Path):
    if path.exists():
        return open(path, "rb")
    gz = path.with_suffix(path.suffix + ".gz")
    if gz.exists():
        return gzip.open(gz, "rb")
    raise ValueError(f"{path.parent}: events missing")


def _iter_chunks(campaign: Path):
    chunks = sorted(p for p in campaign.iterdir()
                    if p.is_dir() and p.name.startswith("chunk-"))
    if not chunks:
        raise ValueError(f"{campaign}: no chunks")
    return chunks


class _Side:
    def __init__(self):
        self.px = 0.0
        self.ahead = 0.0
        self.join_ts = 0
        self.join_mid = 0.0
        self.cooldown_until = 0
        self.active = False


def _simulate(events: list[dict], fee_side: float) -> dict:
    """events: time-ordered bookTicker/aggTrade dicts (live schema)."""
    mids: list[tuple[int, float]] = []  # (ts_ms, mid)
    for e in events:
        if e["channel"] == "bookTicker":
            p = e["payload"]
            mids.append((e["exchange_ts_ms"], (p["bid"] + p["ask"]) / 2))
    fills = {"BID": [], "ASK": []}  # (fill_ts, fill_px, mid_at_fill)
    bid, ask = _Side(), _Side()
    last_book_ts = 0
    for e in events:
        ts = e["exchange_ts_ms"]
        if e["channel"] == "bookTicker":
            p = e["payload"]
            mid = (p["bid"] + p["ask"]) / 2
            if last_book_ts and ts - last_book_ts > GAP_CANCEL_MS:
                bid.active = ask.active = False  # blind gap: cancel all
            last_book_ts = ts
            for side, lvl, qty in (("BID", p["bid"], p["bid_qty"]),
                                   ("ASK", p["ask"], p["ask_qty"])):
                st = bid if side == "BID" else ask
                if not st.active and ts >= st.cooldown_until and lvl > 0:
                    st.active, st.px, st.ahead = True, lvl, max(qty, 0.0)
                    st.join_ts, st.join_mid = ts, mid
                elif st.active:
                    adv = (st.join_mid - mid) / st.join_mid * 1e4 \
                        if side == "BID" else \
                        (mid - st.join_mid) / st.join_mid * 1e4
                    if ts - st.join_ts <= TOX_S * 1000 and adv > TOX_BPS:
                        st.active = False  # toxicity wins over chase
                        st.cooldown_until = ts + COOLDOWN_S * 1000
                    elif lvl != st.px:
                        st.px, st.ahead = lvl, max(qty, 0.0)  # back of new level
                        st.join_ts, st.join_mid = ts, mid
        elif e["channel"] == "aggTrade":
            p = e["payload"]
            taker_sell = bool(p.get("buyer_is_maker", p.get("is_buyer_maker")))
            qty = float(p["qty"])
            px = float(p["price"])
            if taker_sell and bid.active and px <= bid.px:
                bid.ahead -= qty
                if bid.ahead <= 0:
                    fills["BID"].append((ts, bid.px, _mid_at(mids, ts)))
                    bid.active = False
            if not taker_sell and ask.active and px >= ask.px:
                ask.ahead -= qty
                if ask.ahead <= 0:
                    fills["ASK"].append((ts, ask.px, _mid_at(mids, ts)))
                    ask.active = False
    out = {}
    for side in ("BID", "ASK"):
        legs = fills[side]
        n = len(legs)
        if n == 0:
            out[side] = {"n": 0, "net_mean_bps": None, "markout_mean_bps": None}
            continue
        nets, mos = [], []
        for fts, fpx, fmid in legs:
            if fmid is None:
                continue
            cap = (fmid - fpx) / fmid * 1e4 if side == "BID" else \
                (fpx - fmid) / fmid * 1e4
            nets.append(cap - 2 * fee_side)
            m5 = _mid_at(mids, fts + MARKOUT_S * 1000, backward=True)
            if m5 is not None:
                mo = (m5 - fpx) / fpx * 1e4 if side == "BID" else \
                    (fpx - m5) / fpx * 1e4
                mos.append(mo)
        out[side] = {"n": n,
                     "n_scored": len(nets),
                     "net_mean_bps": round(sum(nets) / len(nets), 2) if nets else None,
                     "markout_mean_bps": round(sum(mos) / len(mos), 2) if mos else None}
    return out


def _mid_at(mids, ts, backward=False):
    best = None
    for mts, mid in mids:
        if (mts <= ts) if backward else (mts >= ts):
            if backward:
                best = mid
            else:
                return mid
    return best


def main() -> int:
    parser = argparse.ArgumentParser(
        description="STUDY-04 P1 maker measurement (read-only)")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        campaign = Path(args.campaign)
        symbols = [s.strip().upper() for s in args.symbols.split(",")
                   if s.strip()]
        if not symbols:
            raise ValueError("no symbols given")
        per_symbol = {}
        for symbol in symbols:
            per_symbol[symbol] = {"realistic": None, "adverse": None}
            chunk_fills = {"realistic": {"BID": [], "ASK": []},
                           "adverse": {"BID": [], "ASK": []}}
            # Simulate per chunk (quotes reset at boundaries), pool fills.
            for chunk in _iter_chunks(campaign):
                events = []
                with _open_events(chunk / "events.jsonl") as fh:
                    for line in fh:
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        if e.get("channel") not in ("bookTicker", "aggTrade"):
                            continue
                        if (e.get("symbol") or "").upper() != symbol:
                            continue
                        try:
                            if e["channel"] == "bookTicker":
                                e["payload"]["bid"] = float(e["payload"]["bid"])
                                e["payload"]["ask"] = float(e["payload"]["ask"])
                                e["payload"]["bid_qty"] = float(e["payload"]["bid_qty"])
                                e["payload"]["ask_qty"] = float(e["payload"]["ask_qty"])
                            else:
                                e["payload"]["price"] = float(e["payload"]["price"])
                                e["payload"]["qty"] = float(e["payload"]["qty"])
                            e["exchange_ts_ms"] = int(e["exchange_ts_ms"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        events.append(e)
                events.sort(key=lambda e: e["exchange_ts_ms"])
                for leg, fee in (("realistic", FEE_BPS_SIDE),
                                 ("adverse", FEE_BPS_SIDE_ADV)):
                    res = _simulate(events, fee)
                    for side in ("BID", "ASK"):
                        chunk_fills[leg][side].append(res[side])
            for leg in ("realistic", "adverse"):
                pooled = {}
                for side in ("BID", "ASK"):
                    parts = [p for p in chunk_fills[leg][side] if p["n"]]
                    n = sum(p["n"] for p in parts)
                    if n == 0:
                        pooled[side] = {"n": 0, "net_mean_bps": None,
                                        "markout_mean_bps": None}
                        continue
                    wsum = sum(p["net_mean_bps"] * p["n_scored"] for p in parts
                               if p["net_mean_bps"] is not None)
                    nsc = sum(p["n_scored"] for p in parts
                              if p["net_mean_bps"] is not None)
                    msum = sum(p["markout_mean_bps"] * p["n"] for p in parts
                               if p["markout_mean_bps"] is not None)
                    nm = sum(p["n"] for p in parts
                               if p["markout_mean_bps"] is not None)
                    pooled[side] = {
                        "n": n, "n_scored": nsc,
                        "net_mean_bps": round(wsum / nsc, 2) if nsc else None,
                        "markout_mean_bps": round(msum / nm, 2)
                        if nm else None}
                per_symbol[symbol][leg] = pooled
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"campaign": str(campaign), "legs": per_symbol,
                               "fee_side_bps": {"realistic": FEE_BPS_SIDE,
                                                "adverse": FEE_BPS_SIDE_ADV}},
                              indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for symbol in symbols:
        for leg in ("realistic", "adverse"):
            for side in ("BID", "ASK"):
                r = per_symbol[symbol][leg][side]
                print(f"  {symbol}|{leg}|{side}: n={r['n']} "
                      f"net_mean={r['net_mean_bps']} markout={r['markout_mean_bps']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
