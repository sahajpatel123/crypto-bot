"""Position-episode builder (V-007, B9).

One episode per completed position: legs (partial fills are legs, never
episodes), fees, funding share, exit reason, holding time. Open exposure at
end-of-data closes synthetically at the last fill price, labeled
``end-of-data``. Funding events overlapping an episode window attribute to it
(split equally across simultaneously open episodes; the pilot holds one).
MFE/MAE are null unless bar data is supplied (fills alone cannot observe
excursion).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class EpisodeLeg:
    execution_id: str
    ts_utc: datetime
    side: str
    qty: float
    price: float
    fee: float
    client_order_id: str | None = None


@dataclass(frozen=True)
class Episode:
    episode_id: int
    symbol: str
    side: str  # LONG opened by BUY, SHORT opened by SELL
    strategy: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    holding_s: float
    qty: float  # peak open quantity
    entry_px: float  # qty-weighted open price
    exit_px: float  # qty-weighted close price
    gross: float
    fees: float
    funding: float
    net: float
    exit_reason: str
    legs: tuple[EpisodeLeg, ...]
    end_of_data: bool = False
    mfe_usdt: float | None = None
    mae_usdt: float | None = None


@dataclass
class _OpenPosition:
    symbol: str
    direction: float  # +1 long, -1 short
    strategy: str
    open_ts: datetime
    qty: float = 0.0
    cost: float = 0.0  # cash spent opening the remainder (ex-fee)
    fees: float = 0.0
    realized: float = 0.0  # gross closed so far across partial closes
    legs: list = field(default_factory=list)


def build_episodes(fills, funding_events: list[tuple[datetime, float]],
                   end_ts: datetime, end_reason: str = "end-of-data",
                   strategy: str = "unknown") -> list[Episode]:
    """Group fills into completed position episodes (fills pre-sorted).

    Fills carry no strategy tag, so every episode attributes the run-level
    strategy (or "unknown", labeled). Fills carry no exit reason either:
    closes report "unknown" except labeled end-of-data closes.
    """
    episodes: list[Episode] = []
    open_pos: dict[str, _OpenPosition] = {}
    episode_id = 0

    def funding_share(open_ts: datetime, close_ts: datetime) -> float:
        return sum(amount for ts, amount in funding_events if open_ts <= ts <= close_ts)

    for fill in fills:
        signed = fill.qty if fill.side == "BUY" else -fill.qty
        pos = open_pos.get(fill.instrument)
        if pos is None:
            open_pos[fill.instrument] = _OpenPosition(
                symbol=fill.instrument, direction=1.0 if signed > 0 else -1.0,
                strategy=strategy, open_ts=fill.ts_utc, qty=abs(signed),
                cost=abs(signed) * fill.price, fees=fill.fee,
                legs=[_leg(fill)])
            continue
        if (signed > 0) == (pos.direction > 0):
            pos.qty += abs(signed)
            pos.cost += abs(signed) * fill.price
            pos.fees += fill.fee
            pos.legs.append(_leg(fill))
            continue
        # Opposing fill: closes (part of) the position.
        close_qty = min(pos.qty, abs(signed))
        avg_open = pos.cost / pos.qty
        pos.realized += close_qty * (fill.price - avg_open) * pos.direction
        pos.qty -= close_qty
        pos.cost -= close_qty * avg_open
        fee_share = fill.fee * close_qty / abs(signed)
        pos.fees += fee_share
        pos.legs.append(_leg(fill))
        if pos.qty > 0:
            continue  # partial close: episode stays open.
        episode_id += 1
        episodes.append(_finish(episode_id, pos, fill.ts_utc, "unknown",
                                funding_share(pos.open_ts, fill.ts_utc), False,
                                pos.realized))
        del open_pos[fill.instrument]
        remainder = abs(signed) - close_qty
        if remainder > 0:  # flip: leftover opens the other side.
            open_pos[fill.instrument] = _OpenPosition(
                symbol=fill.instrument, direction=-pos.direction, strategy=strategy,
                open_ts=fill.ts_utc, qty=remainder, cost=remainder * fill.price,
                fees=fill.fee - fee_share, legs=[_leg(fill, remainder)])
    # End-of-data synthetic closes, valued at the last fill price (labeled).
    last_px: dict[str, float] = {}
    for fill in fills:
        last_px[fill.instrument] = fill.price
    for symbol in sorted(open_pos):
        pos = open_pos[symbol]
        px = last_px[symbol]
        gross = pos.qty * (px - pos.cost / pos.qty) * pos.direction
        episode_id += 1
        episodes.append(_finish(episode_id, pos, end_ts, end_reason,
                                funding_share(pos.open_ts, end_ts), True, gross))
    return episodes


def _leg(fill, qty: float | None = None) -> EpisodeLeg:
    return EpisodeLeg(fill.execution_id, fill.ts_utc, fill.side,
                      fill.qty if qty is None else qty,
                      fill.price, fill.fee, fill.client_order_id)


def _finish(episode_id: int, pos: _OpenPosition, close_ts: datetime,
            reason: str, funding: float, end_of_data: bool,
            gross: float) -> Episode:
    peak = 0.0
    running = 0.0
    for leg in pos.legs:
        signed = leg.qty if (leg.side == "BUY") == (pos.direction > 0) else -leg.qty
        running += signed
        peak = max(peak, abs(running))
    opens = [leg for leg in pos.legs
             if (leg.side == "BUY") == (pos.direction > 0)]
    closes = [leg for leg in pos.legs
              if (leg.side == "BUY") != (pos.direction > 0)]
    open_qty = sum(leg.qty for leg in opens) or 1.0
    close_qty = sum(leg.qty for leg in closes) or 0.0
    entry_px = sum(leg.qty * leg.price for leg in opens) / open_qty
    if end_of_data and close_qty == 0:
        exit_px = entry_px + gross / peak if peak else entry_px
    else:
        exit_px = sum(leg.qty * leg.price for leg in closes) / (close_qty or 1.0)
    net = gross - pos.fees + funding
    return Episode(
        episode_id=episode_id, symbol=pos.symbol,
        side="LONG" if pos.direction > 0 else "SHORT", strategy=pos.strategy,
        open_ts_utc=pos.open_ts, close_ts_utc=close_ts,
        holding_s=(close_ts - pos.open_ts).total_seconds(),
        qty=peak, entry_px=entry_px, exit_px=exit_px, gross=gross,
        fees=pos.fees, funding=funding, net=net, exit_reason=reason,
        legs=tuple(pos.legs), end_of_data=end_of_data,
    )
