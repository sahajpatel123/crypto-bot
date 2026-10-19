"""Market-data bridge: captured streams -> strategy views + nautilus data (W2, E-007).

Stdlib-only except :func:`to_nautilus_ticks`, which imports nautilus lazily so
this module loads in the stdlib-only project env too.

Receipt order is the replay order: snapshot records and normalized events both
carry local receipt times, and :func:`iter_market_stream` merges them so replay
rebuilds the identical per-symbol book state, including sync boundaries.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .depth import DepthBook
from .events import EVENT_FORMAT
from .recorder import INPUT_OBSERVED

__all__ = [
    "SNAPSHOT_FORMAT",
    "StreamBook",
    "StreamItem",
    "book_features",
    "flow_window",
    "load_snapshots",
    "snapshot_ms",
    "snapshot_record",
    "iter_market_stream",
    "to_nautilus_ticks",
]

SNAPSHOT_FORMAT = "cryptobot-depth-snapshots/1"


def snapshot_record(
    *,
    run_id: str,
    symbol: str,
    last_update_id: int,
    bids: list,
    asks: list,
    rest_recv_ms: int,
    rest_mono_ns: int,
    limit: int,
    outcome: str,
    exchange_ts_ms: int | None = None,
) -> dict[str, Any]:
    """Build one depth-snapshot record (raw REST levels kept verbatim).

    ``exchange_ts_ms`` is the venue transaction time (REST ``"T"``); when
    present, causality comparisons use the exchange clock exactly. Legacy
    records carry None and fall back to ``rest_recv_ms`` (capture-local
    clock, subject to host skew — see ``snapshot_ms``).
    """
    return {
        "v": 1,
        "format": SNAPSHOT_FORMAT,
        "input_class": INPUT_OBSERVED,
        "source": "binance-fapi-rest",
        "run_id": run_id,
        "symbol": symbol,
        "last_update_id": int(last_update_id),
        "bids": bids,
        "asks": asks,
        "rest_recv_ms": int(rest_recv_ms),
        "rest_mono_ns": int(rest_mono_ns),
        "exchange_ts_ms": (int(exchange_ts_ms) if exchange_ts_ms else None),
        "limit": int(limit),
        "outcome": outcome,  # synced | resync (sync boundary marker).
    }


def snapshot_ms(snap: dict[str, Any]) -> int:
    """Exchange-clock time of a snapshot record (causality key).

    Prefers the venue transaction time; legacy records without it fall
    back to capture-local receipt time (documented skew caveat).
    """
    return int(snap.get("exchange_ts_ms") or snap.get("rest_recv_ms", 0))


def load_snapshots(path: str | Path) -> list[dict[str, Any]]:
    """Load snapshot records in file (receipt) order; missing file -> []."""
    p = Path(path)
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


@dataclass
class StreamBook:
    """A symbol book plus stream-timing metadata for staleness gating."""

    book: DepthBook
    last_applied_ms: int | None = None
    ever_synced: bool = False


@dataclass
class StreamItem:
    """One normalized event plus the depth-sync state at its receipt time."""

    record: dict[str, Any]
    books: dict[str, StreamBook] = field(default_factory=dict)


def iter_market_stream(
    events_path: str | Path,
    snapshots_path: str | Path | None = None,
) -> Iterator[StreamItem]:
    """Yield normalized events in receipt order with live per-symbol book state.

    Snapshots merge by ``rest_recv_ms`` against events' ``local_recv_ms`` so
    replay sees the same install/diff interleave as capture. Each item's
    ``books`` maps symbol -> StreamBook AFTER applying that item (a depth
    record updates its book before yield; a snapshot installs before any
    event with a later receipt time).
    """
    snaps = sorted(load_snapshots(snapshots_path) if snapshots_path else [],
                   key=lambda r: (r.get("rest_recv_ms", 0), r.get("rest_mono_ns", 0)))
    books: dict[str, StreamBook] = {}

    def _book(symbol: str) -> StreamBook:
        entry = books.get(symbol)
        if entry is None:
            entry = books[symbol] = StreamBook(DepthBook(symbol))
        return entry

    def _events() -> Iterator[dict[str, Any]]:
        # Stream line-by-line (file order == receipt order); identical
        # sequence to the former full read, bounded memory.
        with open(events_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    snap_idx = 0
    for record in _events():
        recv = int(record.get("local_recv_ms", 0))
        while snap_idx < len(snaps) and int(snaps[snap_idx].get("rest_recv_ms", 0)) <= recv:
            snap = snaps[snap_idx]
            snap_idx += 1
            entry = _book(str(snap["symbol"]))
            outcome = entry.book.on_snapshot(snap["bids"], snap["asks"], snap["last_update_id"])
            if outcome == "synced":
                entry.ever_synced = True
                entry.last_applied_ms = int(snap["rest_recv_ms"])
        if record.get("channel") == "depth":
            entry = _book(str(record["symbol"]))
            payload = record["payload"]
            outcome = entry.book.on_diff({
                "first_update": payload["first_update"],
                "last_update": payload["last_update"],
                "prev_last_update": payload["prev_last_update"],
                "bids": payload["bids"],
                "asks": payload["asks"],
            })
            if outcome == "applied":
                entry.last_applied_ms = int(record["exchange_ts_ms"])
            elif outcome == "resync":
                entry.book.request_resync("chain-break")
        yield StreamItem(record, books)


def book_features(
    entry: StreamBook | None,
    *,
    levels: int = 10,
    now_ms: int | None = None,
    stale_after_ms: int = 5_000,
) -> tuple[dict[str, Any] | None, str]:
    """Synced-only book features, or (None, machine-readable reason).

    Every quantity derives from observed levels only; anything unobserved is
    unavailable, never zero-filled.
    """
    if entry is None:
        return None, "depth:symbol-not-captured"
    state = entry.book.state
    if not state.synced:
        if not entry.ever_synced and state.applied == 0:
            return None, "depth:unsynced-no-snapshot"
        return None, "depth:resync-in-flight"
    if now_ms is not None and entry.last_applied_ms is not None:
        if now_ms < entry.last_applied_ms:
            return None, "depth:future-data"
        if now_ms - entry.last_applied_ms > stale_after_ms:
            return None, "depth:stale-book"
    bid, ask = entry.book.top()
    if bid is None or ask is None:
        return None, "depth:empty-book"
    bid_qty = entry.book.bids.get(bid, 0.0)
    ask_qty = entry.book.asks.get(ask, 0.0)
    bid_notional, ask_notional = entry.book.depth_totals(levels)
    denom = bid_qty + ask_qty
    return {
        "bid": bid, "ask": ask, "bid_qty": bid_qty, "ask_qty": ask_qty,
        "spread_bps": entry.book.spread_bps(),
        f"bid_notional_top{levels}": bid_notional,
        f"ask_notional_top{levels}": ask_notional,
        "imbalance_top1": (bid_qty - ask_qty) / denom if denom > 0 else None,
        "last_update_id": state.last_update_id,
    }, ""


def flow_window(
    trades: list[dict[str, Any]],
    window_start_ms: int,
    *,
    prev_last_id: int | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Signed trade aggregates for one causal 1 s window, or (None, reason).

    Each trade is a normalized aggTrade payload (price, qty, buyer_is_maker,
    first_id, last_id). ``buyer_is_maker=False`` means the buyer took
    liquidity (buy-side aggression). Gapped windows are missing, never
    interpolated — the trade-ID chain must continue from ``prev_last_id``.
    """
    if not trades:
        return None, "flow:empty-window"
    ordered = sorted(trades, key=lambda t: int(t["last_id"]))
    if prev_last_id is not None and int(ordered[0]["first_id"]) != prev_last_id + 1:
        return None, "flow:trade-id-gap"
    for prev, cur in zip(ordered, ordered[1:]):
        if int(cur["first_id"]) != int(prev["last_id"]) + 1:
            return None, "flow:trade-id-gap"
    buy_notional = sell_notional = 0.0
    buy_count = sell_count = 0
    total_qty = 0.0
    px_qty = 0.0
    for trade in ordered:
        notional = float(trade["price"]) * float(trade["qty"])
        total_qty += float(trade["qty"])
        px_qty += notional
        if trade["buyer_is_maker"]:
            sell_notional += notional
            sell_count += 1
        else:
            buy_notional += notional
            buy_count += 1
    return {
        "window_start_ms": int(window_start_ms),
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_qty": total_qty,
        "vwap": px_qty / total_qty if total_qty > 0 else None,
        "last_id": int(ordered[-1]["last_id"]),
    }, ""


def _quantize(value: float, precision: int) -> float:
    quantum = round(float(value), precision)
    if quantum != quantum or quantum in (float("inf"), float("-inf")):
        raise ValueError(f"cannot quantize non-finite value: {value!r}")
    return quantum


def to_nautilus_ticks(
    records: list[dict[str, Any]],
    precisions: dict[str, tuple[int, int]],
    *,
    venue: str = "BINANCE",
) -> list:
    """Map normalized records to nautilus market-data objects (pure mapping, no I/O).

    - bookTicker -> QuoteTick (ts_event=exchange time, ts_init=receipt time)
    - aggTrade   -> TradeTick (aggressor from buyer_is_maker)
    - depth diff -> OrderBookDeltas (level ADD/UPDATE/DELETE; deterministic
      order ids from price level + side; sequence = venue last_update id)
    - markPrice  -> skipped (funding is modeled by the runtime pump, not ticks)

    ``precisions`` maps SYMBOL -> (price_precision, size_precision); values are
    rounded to instrument precision (documented quantization, not fabrication).
    Requires nautilus_trader (ImportError in the stdlib-only project env).
    """
    from nautilus_trader.model.data import BookOrder, OrderBookDelta, OrderBookDeltas
    from nautilus_trader.model.data import QuoteTick as NTQuoteTick
    from nautilus_trader.model.data import TradeTick as NTTradeTick
    from nautilus_trader.model.enums import AggressorSide, BookAction, OrderSide
    from nautilus_trader.model.identifiers import InstrumentId, TradeId
    from nautilus_trader.model.objects import Price, Quantity

    out: list = []
    for record in records:
        symbol = str(record["symbol"]).upper()
        if symbol not in precisions:
            raise KeyError(f"no precisions for symbol: {symbol!r}")
        price_prec, size_prec = precisions[symbol]
        iid = InstrumentId.from_str(f"{symbol}.{venue}")
        ts_event = int(record["exchange_ts_ms"]) * 1_000_000
        ts_init = int(record["local_recv_ms"]) * 1_000_000
        channel = record["channel"]
        payload = record["payload"]
        if channel == "bookTicker":
            out.append(NTQuoteTick(
                instrument_id=iid,
                bid_price=Price(_quantize(payload["bid"], price_prec), price_prec),
                ask_price=Price(_quantize(payload["ask"], price_prec), price_prec),
                bid_size=Quantity(_quantize(payload["bid_qty"], size_prec), size_prec),
                ask_size=Quantity(_quantize(payload["ask_qty"], size_prec), size_prec),
                ts_event=ts_event, ts_init=ts_init,
            ))
        elif channel == "aggTrade":
            aggressor = (AggressorSide.SELLER if payload["buyer_is_maker"]
                         else AggressorSide.BUYER)
            out.append(NTTradeTick(
                instrument_id=iid,
                price=Price(_quantize(payload["price"], price_prec), price_prec),
                size=Quantity(_quantize(payload["qty"], size_prec), size_prec),
                aggressor_side=aggressor,
                trade_id=TradeId(str(payload["agg_id"])),
                ts_event=ts_event, ts_init=ts_init,
            ))
        elif channel == "depth":
            deltas: list = []
            seq = int(record["venue_seq"])
            for side, levels in ((OrderSide.BUY, payload["bids"]),
                                 (OrderSide.SELL, payload["asks"])):
                for price, qty in levels:
                    q_price = _quantize(price, price_prec)
                    q_qty = _quantize(qty, size_prec)
                    # Deterministic level id: price micros + side bit.
                    level_id = (int(round(q_price * 1_000_000)) << 1) | (0 if side == OrderSide.BUY else 1)
                    if q_qty == 0:
                        action = BookAction.DELETE
                        size = Quantity(0, size_prec)
                    else:
                        action = BookAction.UPDATE
                        size = Quantity(q_qty, size_prec)
                    deltas.append(OrderBookDelta(
                        instrument_id=iid, action=action,
                        order=BookOrder(side, Price(q_price, price_prec), size, level_id),
                        flags=0, sequence=seq, ts_event=ts_event, ts_init=ts_init,
                    ))
            if deltas:
                out.append(OrderBookDeltas(instrument_id=iid, deltas=deltas))
        elif channel == "markPrice":
            continue  # funding is modeled by the runtime pump.
        else:
            raise ValueError(f"unmapped channel: {channel!r}")
    return out
