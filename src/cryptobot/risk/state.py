"""File-backed risk state: halts, pauses, profit floor, reservations.

Persisted as JSON with sorted keys (byte-deterministic for a fixed clock).
Every mutation saves via tmp-file + atomic rename before the caller observes
the decision, so a crash never leaves an approval unrecorded.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

STATE_VERSION = 1


@dataclass
class Reservation:
    reservation_id: str
    intent_ref: str
    instrument: str
    side: str
    notional: float
    reserved_risk: float
    created_utc: str
    expires_utc: str

    def to_dict(self) -> dict:
        return {
            "intent_ref": self.intent_ref,
            "instrument": self.instrument,
            "side": self.side,
            "notional": self.notional,
            "reserved_risk": self.reserved_risk,
            "created_utc": self.created_utc,
            "expires_utc": self.expires_utc,
        }

    @classmethod
    def from_dict(cls, reservation_id: str, raw: dict) -> "Reservation":
        return cls(
            reservation_id=reservation_id,
            intent_ref=raw["intent_ref"],
            instrument=raw["instrument"],
            side=raw["side"],
            notional=raw["notional"],
            reserved_risk=raw["reserved_risk"],
            created_utc=raw["created_utc"],
            expires_utc=raw["expires_utc"],
        )

    def expired(self, now: datetime) -> bool:
        return datetime.fromisoformat(self.expires_utc) <= now


@dataclass
class RiskState:
    current_day: str | None = None
    day_start_equity: float | None = None
    needs_reconciliation: bool = True
    halt_days: dict[str, str] = field(default_factory=dict)
    pause_days: dict[str, str] = field(default_factory=dict)
    original_equity: float | None = None
    peak_realised: float = 0.0
    profit_floor: float | None = None
    reservations: dict[str, Reservation] = field(default_factory=dict)
    open_position: bool = False
    seq: int = 0

    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "current_day": self.current_day,
            "day_start_equity": self.day_start_equity,
            "needs_reconciliation": self.needs_reconciliation,
            "halt_days": dict(self.halt_days),
            "pause_days": dict(self.pause_days),
            "original_equity": self.original_equity,
            "peak_realised": self.peak_realised,
            "profit_floor": self.profit_floor,
            "reservations": {rid: r.to_dict() for rid, r in self.reservations.items()},
            "open_position": self.open_position,
            "seq": self.seq,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "RiskState":
        if raw.get("version") != STATE_VERSION:
            raise ValueError(f"unsupported risk-state version: {raw.get('version')!r}")
        return cls(
            current_day=raw.get("current_day"),
            day_start_equity=raw.get("day_start_equity"),
            needs_reconciliation=bool(raw.get("needs_reconciliation", True)),
            halt_days=dict(raw.get("halt_days", {})),
            pause_days=dict(raw.get("pause_days", {})),
            original_equity=raw.get("original_equity"),
            peak_realised=float(raw.get("peak_realised", 0.0)),
            profit_floor=raw.get("profit_floor"),
            reservations={
                rid: Reservation.from_dict(rid, r) for rid, r in raw.get("reservations", {}).items()
            },
            open_position=bool(raw.get("open_position", False)),
            seq=int(raw.get("seq", 0)),
        )


def load_state(path: str | Path) -> RiskState:
    path = Path(path)
    if not path.exists():
        return RiskState()
    return RiskState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_state(path: str | Path, state: RiskState) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), sort_keys=True, indent=2) + "\n"
    with NamedTemporaryFile("w", dir=str(path.parent), delete=False, encoding="utf-8") as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)
