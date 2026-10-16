#!/usr/bin/env python3
"""Quick-trade capture probe — counterfactual diagnostics (not P&L).

Question (predeclared in docs/quick-trade-probe.md): on OUR OWN captures,
can a passive (maker) fade of aggressive-flow dislocations capture enough
short-horizon reversion to clear frozen cost schedules? This is the local
decisive version of the published finding that crypto flow-driven
reversal (compensation for liquidity provision) peaks near 1.3 bp gross
per trade against >=5 bp benchmark round-trip costs (arXiv 2608.21888).

Discipline (frozen before any run; mirrors tools/hr2_diagnostic.py):
- One causal pass per symbol in FILE ORDER (venue order); windows and
  staleness on exchange_ts_ms; a fill must be STRICTLY later in file
  order than the decision event; a fill can never precede its decision.
- No imputation anywhere: stale books, unresolved paths and missing
  resolution data are counted and excluded, never filled forward.
- Both fill sensitivities are reported (touch: a trade prints AT the
  limit; through: a trade prints strictly BEYOND the limit). Both are
  produced by the same code in two full passes.
- Every candidate meeting the predeclared signal is reported, including
  unfilled and unresolved ones. Outputs are COUNTERFACTUAL DIAGNOSTICS
  in basis points, never portfolio P&L and never strategy trades.
- Funding: settled only on a real 8h boundary (00/08/16 UTC) strictly
  inside the hold, at a fixed 1.0 bp per boundary (documented
  placeholder; captures carry no funding channel). Counted when applied.

FROZEN signal (primary): at an aggTrade event t = (ts, seq):
  flow_W = sum(+qty*price taker-buy / -qty*price taker-sell) over
           (t-5000ms, t] INCLUDING the current trade
  spike  = |flow_W| >= 5 x median(|flow_W| of earlier window samples
           in (t-60s, t)) with >= 20 prior samples
  disp   = (last trade price - last trade price at/before t-5000ms)/px*1e4
  candidate: spike AND |disp| >= 3.0 bps.
  Primary decision band: |disp| >= 5.0 bps (frozen before outcomes).
  Dose-response buckets reported in full: [3,5) [5,8) [8,12) [12,inf).

FROZEN execution (per pass; the fade side opposes the displacement):
  entry = passive limit at the decision-time best quote on our side
          (SELL fade -> best ask; BUY fade -> best bid); the book must
          be <= 1000ms old at decision else the candidate is stale
          (counted, excluded); resting cap 3000ms -> unfilled.
  stop = 10 bps adverse through the book (SELL fill: ask >= P*(1+10bp);
          BUY fill: bid <= P*(1-10bp)) -> taker exit at the first book
          >= trigger+100ms (ARRIVAL_MS).
  target exit = passive limit at the opposite best quote observed
          within 1000ms after the fill (SELL entry -> BUY at bid; BUY
          entry -> SELL at ask); fills on later trades by the pass's
          rule; resting cap 10000ms -> taker exit (arrival rule).
  horizon = 120000ms after fill -> taker exit (arrival rule).
  No fresh book within 1000ms of the fill -> target exit unavailable;
  the hold falls back to the horizon taker exit (counted).
  One episode per symbol at a time; 1s cooldown after an exit resolves.
  Fill price is always OUR limit (maker); taker exits cross the book.
  Notional unit $20 per episode (label); bookTicker carries no sizes so
  no size caps are simulated (retail-size assumption, documented).

Costs (frozen): maker 2.0 bps, taker 5.0 bps per leg (USDT-M VIP0).
Columns: actual-path fees; all-maker (2/2); all-taker (5/5);
BNB-discount (1.8/4.5 on the actual path); ADVERSE (2x actual path).
Win rate is reported on the actual-path base schedule.

Markouts (diagnostic): dir * (mid at fill+5000/+30000ms - P) in bps;
first book at/after the target within 5000ms, else unscorable.

SECOND MODE (predeclared): `continuous` — two-sided passive quotes at
the touch while idle, re-armed every cycle (rest 3000ms, 1000ms
cooldown, requires >= 20 trades seen and a book <= 1000ms old). The
first later trade decides the fill side (aggressor direction on a
crossing print); the other side cancels. Exit logic identical to the
flow mode. This measures the "pile small spreads" economics directly:
what a resting maker actually nets after adverse selection, per fill,
on our tape.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

W_MS = 5_000
MEDIAN_MS = 60_000
SPIKE_MULT = 5.0
MIN_SAMPLES = 20
DISP_MIN_BPS = 3.0
PRIMARY_DISP_BPS = 5.0
BOOK_MAX_AGE_MS = 1_000
ENTRY_RESTING_MS = 3_000
EXIT_RESTING_MS = 10_000
HORIZON_MS = 120_000
STOP_BPS = 10.0
ARRIVAL_MS = 100
PENDING_MAX_MS = 60_000
COOLDOWN_MS = 1_000
MARKOUT_MS = (5_000, 30_000)
MARKOUT_COVER_MS = 5_000
FEE_MAKER_BPS = 2.0
FEE_TAKER_BPS = 5.0
BNB_MAKER_BPS = 1.8
BNB_TAKER_BPS = 4.5

BUCKETS = (
    ("[3,5)", 3.0, 5.0),
    ("[5,8)", 5.0, 8.0),
    ("[8,12)", 8.0, 12.0),
    ("[12,inf)", 12.0, float("inf")),
)


def bucket_of(disp_bps: float) -> str:
    a = abs(disp_bps)
    for name, lo, hi in BUCKETS:
        if lo <= a < hi:
            return name
    return "below"


@dataclass
class Episode:
    sym: str
    side: int  # +1 BUY fade, -1 SELL fade; 0 = continuous two-sided armed
    decision_ts: int
    decision_seq: int
    disp_bps: float
    flow_usd: float
    bucket: str
    state: str = "entry_resting"
    entry_limit: float = 0.0
    entry_expiry: int = 0
    bid_limit: float = 0.0  # continuous mode: resting bid
    ask_limit: float = 0.0  # continuous mode: resting ask
    fill_ts: int = 0
    fill_price: float = 0.0
    fill_order: tuple = (0, 0)
    exit_limit: float | None = None
    exit_expiry: int = 0
    pending_ts: int | None = None
    pending_how: str = ""
    exit_ts: int = 0
    exit_price: float = 0.0
    exit_how: str = ""
    fee_out: float = 0.0
    markout: dict = field(default_factory=dict)
    funding_bps: float = 0.0

    def gross_bps(self) -> float:
        return self.side * (self.exit_price - self.fill_price) \
            / self.fill_price * 1e4

    def net(self, fee_in: float, fee_out: float) -> float:
        return self.gross_bps() - fee_in - fee_out - self.funding_bps


class SymState:
    def __init__(self) -> None:
        self.book_bid = 0.0
        self.book_ask = 0.0
        self.book_ts = 0
        self.trade_ts: list[int] = []
        self.trade_px: list[float] = []
        self.samp_ts: list[int] = []   # |flow_W| samples, one per trade
        self.samp_flow: list[float] = []
        self.episode: Episode | None = None
        self.cooldown_until = 0
        self.watching: list[Episode] = []  # filled, awaiting markouts


def _maker_fill(side: int, limit: float, px: float, through: bool) -> bool:
    if side > 0:
        return px < limit if through else px <= limit
    return px > limit if through else px >= limit


def _advance_triggers(st: SymState, ep: Episode | None, ts: int) -> None:
    """stop / horizon / exit-expiry — checked on trades AND books."""
    if ep is None or ep.state != "filled" or ep.pending_ts is not None:
        return
    adv = st.book_ask if ep.side < 0 else st.book_bid
    if adv > 0 and st.book_ts > 0 and ts - st.book_ts <= BOOK_MAX_AGE_MS:
        hit = (adv >= ep.fill_price * (1 + STOP_BPS / 1e4)
               if ep.side < 0 else
               adv <= ep.fill_price * (1 - STOP_BPS / 1e4))
        if hit:
            ep.pending_ts, ep.pending_how = ts, "stop"
    if ep.pending_ts is None and ts >= ep.fill_ts + HORIZON_MS:
        ep.pending_ts, ep.pending_how = ep.fill_ts + HORIZON_MS, "horizon"
    if ep.pending_ts is None and ep.exit_limit is not None \
            and ts > ep.exit_expiry:
        ep.pending_ts, ep.pending_how = ep.exit_expiry, "exit-expiry"


def _expire_entry(st: SymState, ep: Episode | None,
                  ts: int) -> tuple[Episode | None, bool]:
    """Pending entry past its resting cap -> unfilled (fail-closed: no
    late fills are simulated; the episode is recorded, never resurrected)."""
    if ep is not None and ep.state == "entry_resting" and ts > ep.entry_expiry:
        ep.state = "unfilled"
        st.episode = None
        st.cooldown_until = ts + COOLDOWN_MS
        return None, True
    return ep, False


def probe_stream(events, symbols, through: bool,
                 mode: str = "flow-fade") -> tuple:
    """One causal pass. mode: "flow-fade" (predeclared signal) or
    "continuous" (two-sided passive quotes re-armed while idle; the
    first later trade decides which side fills; the other cancels)."""
    st_map: dict[str, SymState] = {s: SymState() for s in symbols}
    resolved: list[Episode] = []
    counts = {"candidates": 0, "stale_book": 0, "unfilled_entry": 0,
              "filled": 0, "filled_unresolved_eof": 0,
              "unresolved_eof": 0, "requotes": 0}
    exits = {"target-maker": 0, "stop": 0, "horizon": 0, "exit-expiry": 0}
    # per-trade signed notionals are kept alongside prices for windows
    signed_list: dict[str, list[float]] = {s: [] for s in symbols}

    for ev in events:
        sym = ev.get("symbol")
        st = st_map.get(sym)
        if st is None:
            continue
        ch = ev.get("channel")
        ts = ev.get("exchange_ts_ms")
        seq = ev.get("seq")
        if not isinstance(ts, int) or not isinstance(seq, int):
            continue
        order = (ts, seq)
        ep = st.episode
        ep, expired = _expire_entry(st, ep, ts)
        if expired:
            counts["unfilled_entry"] += 1

        # ---- book events ---------------------------------------------
        if ch == "bookTicker":
            try:
                bid = float(ev["payload"]["bid"])
                ask = float(ev["payload"]["ask"])
            except (KeyError, TypeError, ValueError):
                continue
            st.book_bid, st.book_ask, st.book_ts = bid, ask, ts
            # pending taker exits resolve at the first book >= trigger+100
            if ep is not None and ep.pending_ts is not None \
                    and ts >= ep.pending_ts + ARRIVAL_MS \
                    and ts - ep.pending_ts <= PENDING_MAX_MS:
                # cross the spread out: LONG sells at the bid, SHORT buys
                # at the ask
                px = ask if ep.side < 0 else bid
                if px > 0:
                    ep.exit_ts, ep.exit_price = ts, px
                    ep.exit_how = ep.pending_how
                    ep.fee_out = FEE_TAKER_BPS
                    ep.state = "done"
                    exits[ep.exit_how] += 1
                    resolved.append(ep)
                    st.episode = None
                    st.cooldown_until = ts + COOLDOWN_MS
                    ep = None
            # stop / horizon / exit-expiry also age on book events
            _advance_triggers(st, ep, ts)
            # markouts for watching filled episodes
            for w in [w for w in st.watching]:
                for target in MARKOUT_MS:
                    key = int(target / 1000)
                    if key in w.markout:
                        continue
                    t0 = w.fill_ts + target
                    if t0 <= ts <= t0 + MARKOUT_COVER_MS:
                        mid = (bid + ask) / 2.0
                        w.markout[key] = round(
                            w.side * (mid - w.fill_price)
                            / w.fill_price * 1e4, 3)
                if all(int(t / 1000) in w.markout for t in MARKOUT_MS):
                    st.watching.remove(w)
            continue

        if ch != "aggTrade":
            continue

        # ---- aggregate trade -----------------------------------------
        try:
            px = float(ev["payload"]["price"])
            qty = float(ev["payload"]["qty"])
            is_buy = not bool(ev["payload"]["buyer_is_maker"])
        except (KeyError, TypeError, ValueError):
            continue
        signed = qty * px * (1.0 if is_buy else -1.0)

        # 1) advance the open episode on this trade
        if ep is not None and ep.state == "entry_resting":
            chosen = None
            if mode == "continuous":
                if order > (ep.decision_ts, ep.decision_seq):
                    buy_fill = _maker_fill(1, ep.bid_limit, px, through)
                    sell_fill = _maker_fill(-1, ep.ask_limit, px, through)
                    if buy_fill and sell_fill:
                        chosen = -1 if is_buy else 1
                    elif buy_fill:
                        chosen = 1
                    elif sell_fill:
                        chosen = -1
                    if chosen is not None:
                        ep.side = chosen
                        ep.entry_limit = (ep.bid_limit if chosen > 0
                                          else ep.ask_limit)
            elif order > (ep.decision_ts, ep.decision_seq) and \
                    _maker_fill(ep.side, ep.entry_limit, px, through):
                chosen = ep.side
            if chosen is not None:
                assert order > (ep.decision_ts, ep.decision_seq)
                ep.state = "filled"
                ep.fill_ts, ep.fill_price, ep.fill_order = \
                    ts, ep.entry_limit, order
                counts["filled"] += 1
                st.watching.append(ep)
                if st.book_ts > 0 and ts - st.book_ts <= BOOK_MAX_AGE_MS:
                    ep.exit_limit = st.book_bid if ep.side < 0 else st.book_ask
                    ep.exit_expiry = ts + EXIT_RESTING_MS

        elif ep is not None and ep.state == "filled" \
                and ep.pending_ts is None and ep.exit_limit is not None:
            if order > ep.fill_order and \
                    _maker_fill(-ep.side, ep.exit_limit, px, through):
                ep.exit_ts, ep.exit_price = ts, ep.exit_limit
                ep.exit_how = "target-maker"
                ep.fee_out = FEE_MAKER_BPS
                ep.state = "done"
                exits["target-maker"] += 1
                resolved.append(ep)
                st.episode = None
                st.cooldown_until = ts + COOLDOWN_MS
                ep = None

        # 2) stop / horizon / exit-expiry triggers on the trade clock
        _advance_triggers(st, ep, ts)

        # 3) candidate detection (idle only)
        flow = signed
        i = len(st.trade_ts) - 1
        while i >= 0 and st.trade_ts[i] > ts - W_MS:
            flow += signed_list[sym][i]
            i -= 1
        prior = [(st.samp_ts[k], st.samp_flow[k])
                 for k in range(len(st.samp_ts) - 1, -1, -1)
                 if st.samp_ts[k] > ts - MEDIAN_MS]
        st.trade_ts.append(ts)
        st.trade_px.append(px)
        signed_list[sym].append(signed)
        st.samp_ts.append(ts)
        st.samp_flow.append(flow)

        if st.episode is not None or ts < st.cooldown_until:
            continue
        if len(prior) < MIN_SAMPLES:
            continue
        if mode == "continuous":
            # two-sided passive quotes at the touch, re-armed while idle
            if st.book_ts == 0 or ts - st.book_ts > BOOK_MAX_AGE_MS:
                continue
            if not (st.book_bid > 0 and st.book_ask > st.book_bid):
                continue
            st.episode = Episode(
                sym=sym, side=0, decision_ts=ts, decision_seq=seq,
                disp_bps=0.0, flow_usd=0.0, bucket="continuous",
                bid_limit=st.book_bid, ask_limit=st.book_ask,
                entry_limit=st.book_ask,
                entry_expiry=ts + ENTRY_RESTING_MS)
            counts["requotes"] += 1
            continue
        med = statistics.median(abs(f) for _, f in prior)
        if med <= 0 or abs(flow) < SPIKE_MULT * med:
            continue
        j = bisect_right(st.trade_ts, ts - W_MS) - 1
        px_old = st.trade_px[j] if j >= 0 else None
        if px_old is None or px_old <= 0:
            continue
        counts["candidates"] += 1
        disp = (px - px_old) / px_old * 1e4
        if abs(disp) < DISP_MIN_BPS:
            continue
        if st.book_ts == 0 or ts - st.book_ts > BOOK_MAX_AGE_MS:
            counts["stale_book"] += 1
            continue
        side = -1 if disp > 0 else 1
        limit = st.book_ask if side < 0 else st.book_bid
        if not limit or limit <= 0:
            counts["stale_book"] += 1
            continue
        st.episode = Episode(
            sym=sym, side=side, decision_ts=ts, decision_seq=seq,
            disp_bps=disp, flow_usd=flow, bucket=bucket_of(disp),
            entry_limit=limit, entry_expiry=ts + ENTRY_RESTING_MS)

    # end of stream
    for st in st_map.values():
        if st.episode is not None:
            ep = st.episode
            if ep.state == "filled":
                counts["filled_unresolved_eof"] += 1
            else:
                counts["unresolved_eof"] += 1
            ep.state = "unresolved-eof"
            st.episode = None
    return resolved, counts, exits


def apply_funding(ep: Episode) -> None:
    if not ep.fill_ts or not ep.exit_ts:
        return
    b = ep.fill_ts // 28_800_000 + 1
    n = 0
    while True:
        boundary = b * 28_800_000
        if boundary >= ep.exit_ts:
            break
        if boundary > ep.fill_ts:
            n += 1
        b += 1
    ep.funding_bps = n * 1.0


def _rows(eps: list[Episode]) -> list[dict]:
    rows = []
    for e in eps:
        apply_funding(e)
        rows.append({
            "sym": e.sym, "bucket": e.bucket, "exit_how": e.exit_how,
            "gross": e.gross_bps(),
            "net_actual": e.net(FEE_MAKER_BPS, e.fee_out),
            "net_allmaker": e.net(FEE_MAKER_BPS, FEE_MAKER_BPS),
            "net_alltaker": e.net(FEE_TAKER_BPS, FEE_TAKER_BPS),
            "net_bnb": e.net(BNB_MAKER_BPS,
                             e.fee_out * BNB_TAKER_BPS / FEE_TAKER_BPS),
            "net_adverse": e.net(2 * FEE_MAKER_BPS, 2 * e.fee_out),
            "hold_ms": e.exit_ts - e.fill_ts,
            "markout_5": e.markout.get(5),
            "markout_30": e.markout.get(30),
            "abs_disp": abs(e.disp_bps),
        })
    return rows


def _stats(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    def mean(vals):
        vals = [v for v in vals if v is not None]
        return round(statistics.mean(vals), 3) if vals else None
    return {
        "n": len(rows),
        "gross_mean_bps": mean([r["gross"] for r in rows]),
        "gross_median_bps": round(statistics.median(
            [r["gross"] for r in rows]), 3),
        "net_actual_mean_bps": mean([r["net_actual"] for r in rows]),
        "net_actual_median_bps": round(statistics.median(
            [r["net_actual"] for r in rows]), 3),
        "net_allmaker_mean_bps": mean([r["net_allmaker"] for r in rows]),
        "net_alltaker_mean_bps": mean([r["net_alltaker"] for r in rows]),
        "net_bnb_mean_bps": mean([r["net_bnb"] for r in rows]),
        "net_adverse_mean_bps": mean([r["net_adverse"] for r in rows]),
        "win_rate_pct": round(100.0 * sum(
            1 for r in rows if r["net_actual"] > 0) / len(rows), 1),
        "hold_ms_mean": round(statistics.mean(
            [r["hold_ms"] for r in rows]), 0),
        "markout_5s_mean_bps": mean([r["markout_5"] for r in rows]),
        "markout_30s_mean_bps": mean([r["markout_30"] for r in rows]),
    }


def aggregate(eps: list[Episode]) -> dict:
    rows = _rows(eps)
    buckets = [n for n, _, _ in BUCKETS] + ["continuous"]
    return {
        "overall": _stats(rows),
        "primary_disp_ge_5": _stats(
            [r for r in rows if r["abs_disp"] >= PRIMARY_DISP_BPS]),
        "by_bucket": {name: _stats([r for r in rows if r["bucket"] == name])
                      for name in buckets},
        "by_sym": {s: _stats([r for r in rows if r["sym"] == s])
                   for s in sorted({r["sym"] for r in rows})},
        "by_exit": {h: _stats([r for r in rows if r["exit_how"] == h])
                    for h in sorted({r["exit_how"] for r in rows})},
    }


def load_events(path: Path):
    with open(path, "rb") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def run_capture(events_path: Path, symbols: list[str]) -> dict:
    report = {"capture": str(events_path), "symbols": symbols}
    for mode in ("flow-fade", "continuous"):
        for label, through in (("through", True), ("touch", False)):
            eps, counts, exits = probe_stream(
                load_events(events_path), symbols, through, mode=mode)
            key = label if mode == "flow-fade" else f"continuous_{label}"
            report[key] = {
                "counts": counts, "exits": exits,
                "unresolved": counts["unresolved_eof"]
                + counts["filled_unresolved_eof"],
                "aggregate": aggregate(eps)}
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True,
                    help="capture dir or events.jsonl path")
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--out", default="")
    ap.add_argument("--mode", default="both",
                    choices=["flow-fade", "continuous", "both"])
    args = ap.parse_args(argv)
    p = Path(args.capture)
    if p.is_dir():
        p = p / "events.jsonl"
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    report = run_capture(p, symbols)
    if args.mode != "both":
        report = {k: v for k, v in report.items()
                  if k in ("capture", "symbols")
                  or (k.startswith("continuous_") if args.mode == "continuous"
                      else not k.startswith("continuous_"))}
    text = json.dumps(report, indent=1)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
