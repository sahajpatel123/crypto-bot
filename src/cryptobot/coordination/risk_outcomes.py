"""Risk-outcome callback interface (manager-owned, CONTRACTS v0.1.1 addendum).

Execution calls these exactly-once per reservation; risk implements them.
Signatures mirror the V-001 policy surface so the E-003 recording stub and
the future V-001 wiring agree. Single-position pilot: note_flat() takes no
reservation key because at most one position exists.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class RiskOutcomeSink(Protocol):
    """Outcome callbacks execution owes risk for every reservation."""

    def note_fill(self, reservation_id: str) -> None:
        """Entry filled: reservation converts to open-position state."""
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
