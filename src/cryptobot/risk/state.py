"""File-backed risk state: halts, pauses, profit floor, reservations.

Persisted as JSON with sorted keys (byte-deterministic for a fixed clock).
Every mutation saves via tmp-file + atomic rename before the caller observes
the decision, so a crash never leaves an approval unrecorded.

V-004 (F-CEO-03): expired reservations whose outcome is unknown move to the
``unresolved`` set instead of vanishing; only reconciliation (a sink
callback) lifts the block. Flow baselines (F-CEO-06) are persisted values,
robust across restarts. Version 1 snapshots migrate explicitly to version 2.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

STATE_VERSION = 2


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
    qty: float | None = None

    def to_dict(self) -> dict:
        return {
            "intent_ref": self.intent_ref,
            "instrument": self.instrument,
            "side": self.side,
            "notional": self.notional,
            "reserved_risk": self.reserved_risk,
            "created_utc": self.created_utc,
            "expires_utc": self.expires_utc,
            "qty": self.qty,
        }

    @classmethod
    def from_dict(cls, reservation_id: str, raw: dict) -> Reservation:
        return cls(
            reservation_id=reservation_id,
            intent_ref=raw["intent_ref"],
            instrument=raw["instrument"],
            side=raw["side"],
            notional=raw["notional"],
            reserved_risk=raw["reserved_risk"],
            created_utc=raw["created_utc"],
            expires_utc=raw["expires_utc"],
            qty=raw.get("qty"),
        )

    def expired(self, now: datetime) -> bool:
        return datetime.fromisoformat(self.expires_utc) <= now


@dataclass
class RiskState:
    current_day: str | None = None
    day_start_equity: float | None = None
    needs_reconciliation: bool = True
    operating_stop_days: dict[str, str] = field(default_factory=dict)
    pause_days: dict[str, str] = field(default_factory=dict)
    # W3-24H emergency latch: persists across day rolls; cleared only by an
    # explicit reconciled recovery (never by time).
    emergency_latched: bool = False
    emergency_since_utc: str | None = None
    original_equity: float | None = None
    peak_realised: float = 0.0
    profit_floor: float | None = None
    reservations: dict[str, Reservation] = field(default_factory=dict)
    unresolved: dict[str, dict] = field(default_factory=dict)
    booked: dict[str, dict] = field(default_factory=dict)
    flow_baseline_day: float | None = None
    flow_baseline_inception: float | None = None
    open_position: bool = False
    seq: int = 0
    last_tick_utc: str | None = None

    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "current_day": self.current_day,
            "day_start_equity": self.day_start_equity,
            "needs_reconciliation": self.needs_reconciliation,
            "operating_stop_days": dict(self.operating_stop_days),
            "pause_days": dict(self.pause_days),
            "emergency_latched": self.emergency_latched,
            "emergency_since_utc": self.emergency_since_utc,
            "original_equity": self.original_equity,
            "peak_realised": self.peak_realised,
            "profit_floor": self.profit_floor,
            "reservations": {rid: r.to_dict() for rid, r in self.reservations.items()},
            "unresolved": {rid: dict(entry) for rid, entry in self.unresolved.items()},
            "booked": {rid: {"net_qty": e["net_qty"], "exec_ids": list(e["exec_ids"]),
                                "symbol": e["symbol"]} for rid, e in self.booked.items()},
            "flow_baseline_day": self.flow_baseline_day,
            "flow_baseline_inception": self.flow_baseline_inception,
            "open_position": self.open_position,
            "seq": self.seq,
            "last_tick_utc": self.last_tick_utc,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> RiskState:
        version = raw.get("version")
        if version == 1:
            raw = migrate_v1_to_v2(raw)
            version = 2
        if version != STATE_VERSION:
            raise ValueError(f"unsupported risk-state version: {raw.get('version')!r}")
        return cls(
            current_day=raw.get("current_day"),
            day_start_equity=raw.get("day_start_equity"),
            needs_reconciliation=bool(raw.get("needs_reconciliation", True)),
            # Legacy halt_days map to operating stops (same blocking
            # behavior, same daily expiry — safe direction).
            operating_stop_days=dict(raw.get(
                "operating_stop_days", raw.get("halt_days", {}))),
            pause_days=dict(raw.get("pause_days", {})),
            emergency_latched=bool(raw.get("emergency_latched", False)),
            emergency_since_utc=raw.get("emergency_since_utc"),
            original_equity=raw.get("original_equity"),
            peak_realised=float(raw.get("peak_realised", 0.0)),
            profit_floor=raw.get("profit_floor"),
            reservations={
                rid: Reservation.from_dict(rid, r) for rid, r in raw.get("reservations", {}).items()
            },
            unresolved={rid: dict(entry) for rid, entry in raw.get("unresolved", {}).items()},
            booked={rid: {"net_qty": float(e["net_qty"]), "exec_ids": list(e["exec_ids"]),
                           "symbol": e["symbol"]} for rid, e in raw.get("booked", {}).items()},
            flow_baseline_day=raw.get("flow_baseline_day"),
            flow_baseline_inception=raw.get("flow_baseline_inception"),
            open_position=bool(raw.get("open_position", False)),
            seq=int(raw.get("seq", 0)),
            last_tick_utc=raw.get("last_tick_utc"),
        )


def migrate_v1_to_v2(raw: dict) -> dict:
    """Migrate a version-1 snapshot to version 2 (explicit, tested).

    New in v2: the ``unresolved`` exposure set and the flow baselines.
    Migration forces a fresh day reconciliation so the baselines are
    established from live ledger totals (pre-migration flows are absorbed
    into the new baselines by construction).
    """
    if raw.get("version") != 1:
        raise ValueError(f"migrate_v1_to_v2 needs version 1, got {raw.get('version')!r}")
    migrated = dict(raw)
    migrated["version"] = 2
    migrated.setdefault("unresolved", {})
    migrated.setdefault("booked", {})
    migrated["flow_baseline_day"] = None
    migrated["flow_baseline_inception"] = None
    migrated["needs_reconciliation"] = True
    return migrated


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
