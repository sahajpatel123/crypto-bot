"""Paper-engine seam: canonical protocol + event types (manager-owned, S3).

E-007's Nautilus adapter implements :class:`PaperEngine` and MUST import
these types (no competing definitions). The reference adapter in
``app/reference.py`` implements the same seam for replay/tests only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

__all__ = ["EngineOrder", "EngineFill", "EngineCancel", "EngineReject",
           "EngineExpire", "EngineFunding", "EngineEvent", "EngineOrderStatus",
           "AccountPosition", "AccountSnapshot", "PaperEngine"]


@dataclass(frozen=True)
class EngineOrder:
    instrument: str
    side: str              # BUY | SELL (venue side)
    qty: float
    kind: str              # MARKET | LIMIT | STOP_MARKET | TAKE_PROFIT_MARKET
    price: float | None = None
    stop_price: float | None = None
    reduce_only: bool = False
    reservation_id: str | None = None
    expire_at_utc: datetime | None = None
    role: str = "entry"    # entry | stop | target (flatten/time-exit closes
                           # reuse role="target"; there is no separate "exit")


@dataclass(frozen=True)
class EngineFill:
    execution_id: str      # globally unique; ledger dedup key
    client_order_id: str
    instrument: str
    side: str              # BUY | SELL
    qty: float
    price: float           # modeled executable price, never assumed mid
    fee: float             # modeled commission in quote (>= 0, labeled rate)
    ts_utc: datetime
    liquidity: str         # taker (maker disabled until a queue model exists)


@dataclass(frozen=True)
class EngineCancel:
    client_order_id: str
    instrument: str
    reason: str
    ts_utc: datetime


@dataclass(frozen=True)
class EngineReject:
    client_order_id: str
    instrument: str
    reason: str
    ts_utc: datetime


@dataclass(frozen=True)
class EngineExpire:
    client_order_id: str
    instrument: str
    reason: str
    ts_utc: datetime


@dataclass(frozen=True)
class EngineFunding:
    event_id: str
    instrument: str
    amount: float          # signed cash flow in quote
    ts_utc: datetime


@dataclass(frozen=True)
class EngineEvent:
    kind: str              # fill | cancel | reject | expire | funding
    payload: Any
    ts_utc: datetime


@dataclass(frozen=True)
class EngineOrderStatus:
    client_order_id: str
    instrument: str
    # open | partial | filled | rejected | cancelled | expired | unknown.
    # "unknown" = tracked but outcome unresolved (needs lookup); None
    # from order_status() (not this state) means never seen.
    state: str
    qty: float
    filled_qty: float
    reservation_id: str | None = None
    role: str = "entry"    # entry | stop | target
    # Per-order monotonic transition counter (contract v1 §2): adapters
    # bump on every transition; Session applies only strictly newer
    # versions so out-of-order updates cannot roll state backwards.
    version: int = 0


@dataclass(frozen=True)
class AccountPosition:
    instrument: str
    qty: float             # signed base quantity (long > 0)
    entry_price: float | None = None
    mark_price: float | None = None


@dataclass(frozen=True)
class AccountSnapshot:
    """Authoritative positions/account/margin with timestamp+completeness."""
    wallet_equity_usdt: float
    available_margin_usdt: float
    margin_balance_usdt: float | None = None
    positions: tuple[AccountPosition, ...] = ()
    asof_utc: datetime | None = None
    # False when any leg of the snapshot is missing/failed: consumers
    # must treat incomplete snapshots as unknown, never as flat.
    complete: bool = True
    # Venue-reported unrealized PnL across open positions. The equity the
    # daily-loss cap must see is wallet + this (totalMarginBalance), not the
    # wallet leg alone: a position bleeding through the stop has to move the
    # figure the cap polices.
    unrealized_pnl_usdt: float | None = None


class PaperEngine(Protocol):
    """Single order authority for one run. Implementations: reference, nautilus."""

    model_label: str

    def submit(self, cmd: EngineOrder) -> str:
        """Submit (modeled delays may apply); returns a client id for resolve()."""
        ...

    def submit_immediate(self, cmd: EngineOrder) -> str:
        """Submit bypassing modeled delays. Exits/flatten ONLY, never entries."""
        ...

    def submit_protected(self, cmd: EngineOrder, limit_price: float) -> str:
        """Price-protected marketable IOC: fill at-or-better or not at all.

        Session uses this for ALL economic entries (B2). E-008 implements.
        """
        ...

    def resolve(self, client_id: str) -> str | None:
        """Map a submit-time id to the durable order id (None while queued)."""
        ...

    def cancel(self, client_order_id: str, reason: str) -> None:
        ...

    def poll(self) -> list[EngineEvent]:
        """Non-blocking drain of fills/cancels/rejects/expires/funding."""
        ...

    def attach_protection(self, entry_client_id: str, stop_price: float,
                          target_price: float | None) -> list[str]:
        """Independent reduce-only exit legs sized to filled qty. No OCO.

        Returns [stop_id] or [stop_id, target_id] — STOP FIRST, always.
        """
        ...

    def open_orders(self) -> list[EngineOrderStatus]:
        """Currently-open/partial bot orders ONLY, every adapter.

        A missing order here proves nothing about cancellation, fills,
        or flatness — use order_status() for tracked truth.
        """
        ...

    def order_status(self, client_order_id: str) -> EngineOrderStatus | None:
        """Tracked order truth incl. terminal + unknown states.

        None ONLY when the id was never seen. Versions rise
        monotonically per order (see EngineOrderStatus.version).
        """
        ...

    def unknown_ids(self) -> tuple[str, ...]:
        """Tracked ids whose outcome is unresolved (need lookup)."""
        ...

    def bind_sink(self, handler: Any) -> None:
        """Register the Session execution-event handler (contract v1 §2).

        The adapter invokes it on EVERY emission (stream, lookup-adopt,
        recovery-adopt, simulated callbacks). poll() drains only
        pre-binding emissions.
        """
        ...

    def account_snapshot(self) -> AccountSnapshot | None:
        """Authoritative positions/account/margin, timestamped + complete.

        None (or complete=False) means unknown — never flat.
        """
        ...

    def filled_qty(self, client_order_id: str) -> float:
        ...

    def set_exit_only(self, halted: bool, reason: str = "") -> None:
        """Reason-keyed halt (R3): entries refuse while any reason held.

        Lifting clears ONLY the named reason; subsystems never clear
        each other's halts. Empty reason on lift clears all (escape).
        """

    def note_mark(self, instrument: str, price: float) -> None:
        """Reference-model mark feed (drives fill simulation)."""
        ...

    def account_margin(self) -> tuple[float, float] | None:
        """(available_margin, free_margin); None when unmodelled (V-008)."""
        ...

    def valuation_mark_ts(self, instrument: str) -> datetime | None:
        """Observation time of the latest valuation mark, if tracked."""
        ...

    def recover(self, outcome_sink: Any) -> None:
        """Rebuild order state from the engine's durable journal after restart."""
        ...

    def close(self) -> None:
        ...
