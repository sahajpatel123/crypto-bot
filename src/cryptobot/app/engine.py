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
           "EngineExpire", "EngineFunding", "EngineEvent", "PaperEngine"]


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
    role: str = "entry"    # entry | stop | target


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


class PaperEngine(Protocol):
    """Single order authority for one run. Implementations: reference, nautilus."""

    model_label: str

    def submit(self, cmd: EngineOrder) -> str:
        """Submit; returns the durable client_order_id."""
        ...

    def cancel(self, client_order_id: str, reason: str) -> None:
        ...

    def poll(self) -> list[EngineEvent]:
        """Non-blocking drain of fills/cancels/rejects/expires/funding."""
        ...

    def note_mark(self, instrument: str, price: float) -> None:
        """Reference-model mark feed (drives fill simulation)."""
        ...

    def close(self) -> None:
        ...
