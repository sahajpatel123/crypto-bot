"""H1 maker-OFI evaluator over depth snapshots (preregistered rules).

Signal: top-5 notional imbalance beyond +/-0.6. Entry: post-only at
best bid/ask, cancel after 30s unfilled, filled only via the
conservative queue model (fill_realism.maker_fill: touches earn
nothing). Exit: stop 25bps / target 50bps, taker. Max 1 position.
Dev archives carry no book channel, so this runs only on captured
depth snapshots (see research/prereg/H1-book-capture.md).
"""
from __future__ import annotations

from dataclasses import dataclass

from cryptobot.execution.fill_realism import maker_fill
from cryptobot.research.cost_model_v2 import CostModel
from cryptobot.research.h_eval import Trade, _day_of, _net

LEVELS = 5
THRESHOLD = 0.6
CANCEL_MS = 30_000
MAX_HOLD_MS = 900_000


@dataclass(frozen=True)
class Snapshot:
    ts_ms: int
    bids: tuple[tuple[float, float], ...]  # (price, qty), best first
    asks: tuple[tuple[float, float], ...]


def imbalance(snap: Snapshot, levels: int = LEVELS) -> float | None:
    bid_n = sum(p * q for p, q in snap.bids[:levels])
    ask_n = sum(p * q for p, q in snap.asks[:levels])
    total = bid_n + ask_n
    return (bid_n - ask_n) / total if total > 0 else None


def _mid(snap: Snapshot) -> float | None:
    if not snap.bids or not snap.asks:
        return None
    return (snap.bids[0][0] + snap.asks[0][0]) / 2


def h1_trades(snaps: list[Snapshot], prints: list[tuple[int, float, float]],
              qty: float = 1.0, model: CostModel | None = None) -> list[Trade]:
    """prints: (ts_ms, price, qty) agg trades in time order."""
    model = model or CostModel()
    trades: list[Trade] = []
    i = 0
    while i < len(snaps):
        snap = snaps[i]
        imb = imbalance(snap)
        mid = _mid(snap)
        if imb is None or mid is None or abs(imb) <= THRESHOLD:
            i += 1
            continue
        direction = 1 if imb > 0 else -1
        side = "BUY" if direction > 0 else "SELL"
        limit = snap.bids[0][0] if direction > 0 else snap.asks[0][0]
        ahead = snap.bids[0][1] if direction > 0 else snap.asks[0][1]
        window = [(p, q) for ts, p, q in prints
                  if snap.ts_ms < ts <= snap.ts_ms + CANCEL_MS]
        if maker_fill(side=side, limit_price=limit, qty=qty,
                      queue_ahead_qty=ahead, trades=window) < qty * 0.999:
            i += 1  # cancelled unfilled: no trade, next snapshot
            continue
        exit_mid = None
        j = i + 1
        while j < len(snaps) and snaps[j].ts_ms <= snap.ts_ms + MAX_HOLD_MS:
            m = _mid(snaps[j])
            if m is None:
                j += 1
                continue
            move = direction * (m / limit - 1) * 10000
            if move <= -25.0 or move >= 50.0:
                exit_mid = m
                break
            j += 1
        if exit_mid is None:
            later = [s for s in snaps[i + 1:] if _mid(s) is not None]
            if not later:
                break
            exit_mid = _mid(later[-1])
            j = i + 1 + len(later) - 1
        gross = direction * (exit_mid / limit - 1) * 10000
        net, adv = _net(gross, maker=True, model=model)
        trades.append(Trade(day=_day_of(snap.ts_ms), gross_bps=gross,
                            net_bps=net, adverse_bps=adv))
        i = j + 1  # max 1 position: resume after exit
    return trades
