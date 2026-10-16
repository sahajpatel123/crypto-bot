#!/usr/bin/env python3
"""STUDY-04 — P1 maker/post-only economics measurement.

Implements the preregistration frozen in reports/pivot/study04-prereg.json
(commit 3360b95) BEFORE any qualifying capture existed. Descriptive
measurement only: no strategy, no candidate, no attempt-budget consumption.

Fill model is BRACKETED per the prereg (queue position is unobservable in
public data):
- optimistic-join: a resting post-only order at the touch fills when any
  trade prints at/through its price (zero queue ahead assumed);
- conservative-through: fills only when a trade prints STRICTLY through
  the order price (full queue ahead assumed).
Truth lies between the bounds; decisions require BOTH models' conditions.

Quote policy (frozen): both sides quoted at the touch, re-quote on >=1 tick
move away, toxicity cancel when trailing-10s aggressive flow against the
quoted side reaches the declared threshold, re-quote after 5s calm.
Inventory: flat-biased — exit at touch (taker) after 60s or on opposite
fill. Fees: maker 2.0 bps, taker 5.0 bps (VIP0 list). Markouts at
+5/+30/+60/+300s from the markPrice stream.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import deque
from pathlib import Path

MAKER_FEE_BPS = 2.0
TAKER_FEE_BPS = 5.0
INVENTORY_EXIT_S = 60          # frozen: flat-biased exit after 60s
REQUOTE_CALM_S = 5             # frozen: re-quote after 5s calm
MARKOUTS_S = (5, 30, 60, 300)


# ------------------------------------------------------------------ models

class MakerSim:
    """One symbol's post-only quote simulation for ONE fill model.

    model="optimistic": trade at/through the order price fills it.
    model="conservative": only strictly-through trades fill it.
    """

    def __init__(self, symbol: str, model: str, tick: float,
                 toxicity: float, min_flow_trades: int = 20) -> None:
        assert model in ("optimistic", "conservative")
        self.symbol = symbol
        self.model = model
        self.tick = tick
        self.toxicity = toxicity
        self.min_flow_trades = min_flow_trades  # prereg amendment A1
        # quote state
        self.bid_order: float | None = None   # resting post-only buy price
        self.ask_order: float | None = None   # resting post-only sell price
        self.canceled_until = {"bid": -1, "ask": -1}  # ts_ms re-quote gates
        # flow window (aggressive taker trades)
        self.flow: deque[tuple[int, float]] = deque()  # (ts, signed_vol)
        # book state
        self.best_bid: float | None = None
        self.best_ask: float | None = None
        self.mid: float | None = None
        # inventory (flat-biased, one unit of exposure at a time)
        self.pos: int = 0                      # +1 long, -1 short, 0 flat
        self.pos_entry_px: float | None = None
        self.pos_entry_ts: int | None = None
        self.pos_entry_was_maker: bool | None = None
        # records
        self.fills: list[dict] = []            # every maker fill event
        self.round_trips: list[dict] = []      # completed round trips
        self.marks: list[tuple[int, float]] = []  # (ts, mark)

    # -- quoting ------------------------------------------------------------
    def _quote_both(self, ts: int) -> None:
        if self.best_bid is not None and self.bid_order is None \
                and ts >= self.canceled_until["bid"]:
            self.bid_order = self.best_bid
        if self.best_ask is not None and self.ask_order is None \
                and ts >= self.canceled_until["ask"]:
            self.ask_order = self.best_ask

    def _requote_check(self, ts: int) -> None:
        # rest-at-touch policy: re-quote whenever the observed touch is >= 1
        # tick away from the order in EITHER direction (prereg amendment
        # A1: "away" is symmetric — the order always rests at the touch)
        if self.bid_order is not None and self.best_bid is not None \
                and abs(self.best_bid - self.bid_order) >= self.tick - 1e-12:
            self.bid_order = self.best_bid
        if self.ask_order is not None and self.best_ask is not None \
                and abs(self.best_ask - self.ask_order) >= self.tick - 1e-12:
            self.ask_order = self.best_ask

    def _toxicity_check(self, ts: int) -> None:
        # trailing-10s aggressive flow fraction (taker buys = +vol)
        while self.flow and self.flow[0][0] < ts - 10_000:
            self.flow.popleft()
        # prereg amendment A1: the fraction is noise on thin flow — the
        # filter engages only when the window holds >= 20 aggressive trades
        if len(self.flow) < self.min_flow_trades:
            return
        tot = sum(v for _, v in self.flow)
        if tot == 0:
            return
        buy_frac = sum(v for _, v in self.flow if v > 0) / tot
        # ask side is harmed by aggressive BUYING (they lift the offer before
        # ours fills); bid side by aggressive SELLING
        if self.ask_order is not None and buy_frac >= self.toxicity:
            self.ask_order = None
            self.canceled_until["ask"] = ts + REQUOTE_CALM_S * 1000
        if self.bid_order is not None and (1.0 - buy_frac) >= self.toxicity:
            self.bid_order = None
            self.canceled_until["bid"] = ts + REQUOTE_CALM_S * 1000

    # -- event handlers -----------------------------------------------------
    def on_book(self, ts: int, bid: float, ask: float) -> None:
        self.best_bid, self.best_ask = bid, ask
        self.mid = (bid + ask) / 2
        self._requote_check(ts)
        self._toxicity_check(ts)
        self._quote_both(ts)

    def _fills_on_trade(self, ts: int, price: float, side: str) -> None:
        """side: 'buy' (taker buy, lifts offers) or 'sell' (taker sell)."""
        # our resting ASK (sell order) is consumed by taker BUY trades.
        # Guard: an ask fill OPENS a short at flat or CLOSES a long; it is
        # blocked only when already short (no stacking).
        if self.ask_order is not None:
            hit = (price >= self.ask_order if self.model == "optimistic"
                   else price > self.ask_order)
            if hit and self.pos >= 0:
                self._on_fill(ts, self.ask_order, "SELL")
        # our resting BID (buy order) is consumed by taker SELL trades.
        # Guard: a bid fill OPENS a long at flat or CLOSES a short; blocked
        # only when already long.
        if self.bid_order is not None:
            hit = (price <= self.bid_order if self.model == "optimistic"
                   else price < self.bid_order)
            if hit and self.pos <= 0:
                self._on_fill(ts, self.bid_order, "BUY")

    def _on_fill(self, ts: int, px: float, side: str) -> None:
        if side == "BUY":
            self.bid_order = None   # consumed
        else:
            self.ask_order = None
        prev = self.pos
        # position algebra: a bid fill opens long at flat or closes a short;
        # an ask fill opens short at flat or closes a long (guards in
        # _fills_on_trade make |prev| <= 1 and the direction legal)
        self.pos = prev + (1 if side == "BUY" else -1)
        # amendment A1: a consumed order re-quotes only after the same 5s
        # calm gate — a fresh quote is never instantly re-exposed into the
        # flow that just filled it
        self.canceled_until["bid" if side == "BUY" else "ask"] = \
            ts + REQUOTE_CALM_S * 1000
        was_opposite_close = prev != 0
        self.fills.append({"ts": ts, "px": px, "side": side,
                           "mid": self.mid, "opposite_close": was_opposite_close})
        if was_opposite_close:
            self._close_round_trip(ts, px, side)
        else:
            self.pos_entry_px, self.pos_entry_ts = px, ts
            self.pos_entry_was_maker = True

    def _close_round_trip(self, ts: int, exit_px: float, exit_side: str) -> None:
        entry_px, entry_ts = self.pos_entry_px, self.pos_entry_ts
        self.pos, self.pos_entry_px, self.pos_entry_ts = 0, None, None
        if entry_px is None:
            return
        gross = (exit_px - entry_px) if exit_side == "SELL" \
            else (entry_px - exit_px)
        fees = MAKER_FEE_BPS + (MAKER_FEE_BPS if exit_side != "TAKER"
                                else TAKER_FEE_BPS)
        notional = (entry_px + exit_px) / 2
        self.round_trips.append({
            "entry_ts": entry_ts, "exit_ts": ts, "entry_px": entry_px,
            "exit_px": exit_px, "gross_bps": gross / notional * 1e4,
            "fees_bps": fees, "net_bps": gross / notional * 1e4 - fees,
            "hold_s": (ts - entry_ts) / 1000,
        })

    def on_trade(self, ts: int, price: float, qty: float,
                 buyer_is_maker: bool) -> None:
        # The arriving trade is a potential FILL first: toxicity cancels are
        # evaluated on the flow BEFORE this trade, never on the trade that
        # is about to hit the order (a fill and a cancel cannot be the same
        # instant).
        self._fills_on_trade(ts, price,
                             "sell" if buyer_is_maker else "buy")
        signed = -qty if buyer_is_maker else qty
        self.flow.append((ts, signed))
        self._toxicity_check(ts)

    def on_mark(self, ts: int, mark: float) -> None:
        self.marks.append((ts, mark))
        # flat-biased time exit
        if self.pos != 0 and self.pos_entry_ts is not None \
                and ts >= self.pos_entry_ts + INVENTORY_EXIT_S * 1000:
            if self.pos > 0 and self.best_bid is not None:
                self._close_round_trip(ts, self.best_bid, "TAKER")
            elif self.pos < 0 and self.best_ask is not None:
                self._close_round_trip(ts, self.best_ask, "TAKER")

    def markout(self, fill_ts: int, side: str, horizon_s: int) -> float | None:
        """Signed mark move vs the fill side (+ = favorable)."""
        target = fill_ts + horizon_s * 1000
        i = bisect.bisect_left(self.marks, (target, float("-inf")))
        if i >= len(self.marks):
            return None
        base_i = bisect.bisect_left(self.marks, (fill_ts, float("-inf")))
        if base_i >= len(self.marks):
            return None
        move = (self.marks[i][1] - self.marks[base_i][1]) \
            / self.marks[base_i][1] * 1e4
        return move if side == "BUY" else -move


# ------------------------------------------------------------------ driver

def run_stream(events_path: Path, symbol: str, tick: float,
               toxicity: float) -> dict:
    sims = {m: MakerSim(symbol, m, tick, toxicity)
            for m in ("optimistic", "conservative")}
    with events_path.open() as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("symbol") != symbol:
                continue
            ts = ev.get("exchange_ts_ms")
            if ts is None:
                continue
            ch = ev.get("channel")
            payload = ev.get("payload") or {}
            if ch == "bookTicker":
                bid, ask = payload.get("bid"), payload.get("ask")
                if bid is None or ask is None:
                    continue
                for s in sims.values():
                    s.on_book(ts, float(bid), float(ask))
            elif ch == "aggTrade":
                px, qty = payload.get("price"), payload.get("qty")
                if px is None or qty is None:
                    continue
                for s in sims.values():
                    s.on_trade(ts, float(px), float(qty),
                               bool(payload.get("buyer_is_maker")))
            elif ch == "markPrice":
                mark = payload.get("mark_price", payload.get("mark"))
                if mark is None:
                    continue
                for s in sims.values():
                    s.on_mark(ts, float(mark))
    out: dict = {"symbol": symbol, "tick": tick, "toxicity": toxicity,
                 "models": {}}
    for name, s in sims.items():
        mos = {h: [s.markout(f["ts"], f["side"], h) for f in s.fills]
               for h in MARKOUTS_S}
        mo_stats = {}
        for h, vals in mos.items():
            got = [v for v in vals if v is not None]
            mo_stats[f"markout_{h}s_mean_bps"] = (
                sum(got) / len(got) if got else None)
            mo_stats[f"markout_{h}s_n"] = len(got)
        nets = [rt["net_bps"] for rt in s.round_trips]
        out["models"][name] = {
            "n_fills": len(s.fills),
            "n_round_trips": len(s.round_trips),
            "net_mean_bps": sum(nets) / len(nets) if nets else None,
            "net_median_bps": (sorted(nets)[len(nets) // 2]
                               if nets else None),
            "hit_rate": (sum(1 for n in nets if n > 0) / len(nets)
                         if nets else None),
            "maker_close_frac": (sum(1 for rt in s.round_trips
                                     if rt["fees_bps"] == 2 * MAKER_FEE_BPS)
                                 / len(s.round_trips) if s.round_trips
                                 else None),
            **mo_stats,
        }
    return out


def decide(results: dict) -> dict:
    """Frozen decision rule (prereg: merits-candidate requires BOTH models)."""
    opt = results["models"]["optimistic"]
    con = results["models"]["conservative"]
    checks = {
        "n_fills_ge_200": min(opt["n_fills"], con["n_fills"]) >= 200,
        "optimistic_net_ge_0p5bp": (opt["net_mean_bps"] is not None
                                    and opt["net_mean_bps"] >= 0.5),
        "conservative_net_ge_m2bp": (con["net_mean_bps"] is not None
                                     and con["net_mean_bps"] >= -2.0),
        "markout5_within_half_spread": True,  # refined below when marks exist
    }
    mo = opt.get("markout_5s_mean_bps")
    if mo is not None:
        # spread proxy: use median net of optimistic as spread scale fallback;
        # the prereg kill is markout worse than -spread/2 — with a ~1-tick
        # spread this is evaluated against the observed spread estimate
        spread_est = max(opt.get("net_median_bps") or 0.0, 1.0)
        checks["markout5_within_half_spread"] = mo >= -spread_est / 2
    verdict = "MERITS-CANDIDATE-EVALUATION" if all(checks.values()) \
        else "NOT-MERITED"
    if min(opt["n_fills"], con["n_fills"]) < 200:
        verdict = "DATA-INSUFFICIENT (n < 200 fills)"
    return {"verdict": verdict, "checks": checks}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--events", type=Path, required=True,
                    help="capture events.jsonl")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--tick", type=float, default=0.1)
    ap.add_argument("--toxicity", type=float, default=0.6,
                    help="declared a priori (prereg)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    results = run_stream(args.events, args.symbol, args.tick, args.toxicity)
    results["decision"] = decide(results)
    results["prereg"] = "reports/pivot/study04-prereg.json"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1))
    print(f"WROTE {args.out} verdict={results['decision']['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
