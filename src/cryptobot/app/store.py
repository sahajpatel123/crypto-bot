"""Transactional single-writer run store, SQLite WAL (manager-owned, S5).

Authoritative source for run IDs, intent decisions, execution events,
ownership, risk transitions and checkpoints. JSON logs stay diagnostic
views; crash recovery reads this store.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["RunStore"]

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, config_hash TEXT NOT NULL,
  state TEXT NOT NULL, pid INTEGER, started_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL, heartbeat_utc TEXT, workdir TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  intent_id TEXT NOT NULL, strategy TEXT NOT NULL, instrument TEXT NOT NULL,
  side TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
  ts_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intents_run ON intents(run_id);
CREATE TABLE IF NOT EXISTS execution_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  execution_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
  ts_utc TEXT NOT NULL, UNIQUE(run_id, kind, execution_id)
);
CREATE TABLE IF NOT EXISTS risk_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  ts_utc TEXT NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL,
  reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  ts_utc TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stop_requests (
  run_id TEXT PRIMARY KEY, requested_utc TEXT NOT NULL, mode TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    """Single-writer store. One instance owns writes per process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    # -- runs ------------------------------------------------------------
    def create_run(self, run_id: str, mode: str, config_hash: str,
                   workdir: str, pid: int | None) -> None:
        now = _now()
        self._db.execute(
            "INSERT INTO runs(run_id, mode, config_hash, state, pid, started_utc,"
            " updated_utc, heartbeat_utc, workdir) VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id, mode, config_hash, "starting", pid, now, now, now, workdir))
        self._db.commit()

    def set_state(self, run_id: str, state: str, reason: str = "") -> None:
        row = self._db.execute(
            "SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown run {run_id}")
        self._db.execute("UPDATE runs SET state=?, updated_utc=?, heartbeat_utc=?"
                         " WHERE run_id=?", (state, _now(), _now(), run_id))
        self._db.execute("INSERT INTO risk_transitions(run_id, ts_utc, from_state,"
                         " to_state, reason) VALUES(?,?,?,?,?)",
                         (run_id, _now(), row[0], state, reason))
        self._db.commit()

    def heartbeat(self, run_id: str, pid: int | None = None) -> None:
        if pid is None:
            self._db.execute("UPDATE runs SET heartbeat_utc=?, updated_utc=?"
                             " WHERE run_id=?", (_now(), _now(), run_id))
        else:
            self._db.execute("UPDATE runs SET heartbeat_utc=?, updated_utc=?, pid=?"
                             " WHERE run_id=?", (_now(), _now(), pid, run_id))
        self._db.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT run_id, mode, config_hash, state, pid, started_utc,"
            " updated_utc, heartbeat_utc, workdir FROM runs WHERE run_id=?",
            (run_id,)).fetchone()
        if row is None:
            return None
        keys = ("run_id", "mode", "config_hash", "state", "pid", "started_utc",
                "updated_utc", "heartbeat_utc", "workdir")
        return dict(zip(keys, row))

    # -- intents / events / checkpoints ----------------------------------
    def record_intent(self, run_id: str, intent_id: str, strategy: str,
                      instrument: str, side: str, decision: str,
                      reason: str, ts_utc: str | None = None) -> None:
        self._db.execute(
            "INSERT INTO intents(run_id, intent_id, strategy, instrument, side,"
            " decision, reason, ts_utc) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, intent_id, strategy, instrument, side, decision, reason,
             ts_utc or _now()))
        self._db.commit()

    def record_event(self, run_id: str, execution_id: str, kind: str,
                     payload: dict[str, Any], ts_utc: str | None = None) -> bool:
        """Insert-or-ignore by (run, kind, execution_id). False when dup."""
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO execution_events(run_id, execution_id, kind,"
            " payload, ts_utc) VALUES(?,?,?,?,?)",
            (run_id, execution_id, kind, json.dumps(payload, sort_keys=True),
             ts_utc or _now()))
        self._db.commit()
        return cursor.rowcount == 1

    def checkpoint(self, run_id: str, kind: str,
                   payload: dict[str, Any], ts_utc: str | None = None) -> None:
        self._db.execute("INSERT INTO checkpoints(run_id, ts_utc, kind, payload)"
                         " VALUES(?,?,?,?)",
                         (run_id, ts_utc or _now(), kind,
                          json.dumps(payload, sort_keys=True)))
        self._db.commit()

    def counts(self, run_id: str) -> dict[str, int]:
        out = {}
        for table in ("intents", "execution_events", "risk_transitions", "checkpoints"):
            out[table] = self._db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)).fetchone()[0]
        return out

    # -- stop -------------------------------------------------------------
    def request_stop(self, run_id: str, mode: str = "graceful") -> None:
        if mode not in ("graceful", "flatten"):
            raise ValueError(f"stop mode must be graceful|flatten, got {mode!r}")
        self._db.execute("INSERT OR REPLACE INTO stop_requests(run_id, requested_utc, mode)"
                         " VALUES(?,?,?)", (run_id, _now(), mode))
        self._db.commit()

    def stop_requested(self, run_id: str) -> str | None:
        row = self._db.execute("SELECT mode FROM stop_requests WHERE run_id=?",
                               (run_id,)).fetchone()
        return row[0] if row else None
