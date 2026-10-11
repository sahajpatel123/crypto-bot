"""Risk-outcome callback interface (manager-owned, CONTRACTS v0.2.0 addendum).

Execution calls these per reservation; risk implements them. Deltas are
at-least-once per exec_id (risk dedups); note_fill fires exactly-once on
the first nonzero fill. Single-position pilot: note_flat() takes no
reservation key because at most one position exists.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class RiskOutcomeSink(Protocol):
    """Outcome callbacks execution owes risk for every reservation."""

    def note_fill_delta(
        self,
        reservation_id: str,
        exec_id: str,
        symbol: str,
        venue_side: str,
        qty: float,
        price: float,
        fee: float,
        ts_utc: str,
    ) -> None:
        """Book one fill increment, idempotently by exec_id (v0.2.0)."""
        ...

    def note_fill(self, reservation_id: str) -> None:
        """First nonzero fill: reservation converts to open-position state."""
        ...

    def release(self, reservation_id: str) -> bool:
        """Cancelled/expired/rejected: free the reservation.

        Returns True when a live reservation was freed, False when the id
        was unknown (already released or never issued).
        """
        ...

    def note_flat(self) -> None:
        """Position flat: clear open-position state."""
        ...
