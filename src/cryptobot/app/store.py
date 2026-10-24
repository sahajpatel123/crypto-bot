"""Transactional single-writer run store, SQLite WAL (manager-owned, S5).

Authoritative source for run IDs, intent decisions, execution events,
ownership, risk transitions and checkpoints. JSON logs stay diagnostic
views; crash recovery reads this store.

Release contract v1 §4 (W1): command intentions + normalized execution
events persist BEFORE application processing is acknowledged; one
transaction where applicable; a transaction is never held across
network I/O. Single-instance lock, crash-consistent cursors, versioned
reader + backup, refuse-unsafe-state.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["RunStore", "UnsafeState", "StoreLocked"]

#: Current schema version (PRAGMA user_version). v1 = pre-release tables
#: (runs/intents/execution_events/risk_transitions/checkpoints/
#: stop_requests) with no version stamp; v2 adds commands + meta.
_SCHEMA_VERSION = 2


class UnsafeState(Exception):
    """Refuse-unsafe-state: the store cannot be trusted (v1 §4)."""


class StoreLocked(Exception):
    """Single-instance lock held by another live process (v1 §4)."""

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

#: v2 additions: durable command intentions (persisted BEFORE submit so a
#: crash at the submit boundary reconciles by durable client ID instead
#: of resubmitting) + meta (durability mode record).
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS commands (
  cmd_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
  payload TEXT NOT NULL, engine_client_id TEXT, status TEXT NOT NULL,
  ts_utc TEXT NOT NULL, updated_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commands_run ON commands(run_id);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_utc TEXT NOT NULL
);
"""

_OPEN_STATUSES = ("intended", "submitted", "unknown")

_DURABILITY_NOTE = (
    "WAL + synchronous=NORMAL: process-crash safe (a killed process "
    "restarts from a consistent store). Power-loss durability is NOT "
    "claimed without synchronous=FULL on tested media."
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunStore:
    """Single-writer store. One instance owns writes per process.

    Contract v1 §4: the constructor runs the versioned reader (fresh →
    full v2 schema; legacy v1 → backup + migrate; unknown/future →
    UnsafeState; integrity failure → UnsafeState). The single-instance
    lock is explicit via acquire_lock/release_lock (production run
    paths hold it; tests and readers do not).
    """

    #: Same-process re-entrant guard: {resolved path: refcount}. flock
    #: conflicts across file descriptions even in one process, so nested
    #: production/test opens of one path refcount instead of blocking.
    _held: dict[str, int] = {}

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._lock_fd: int | None = None
        self._open_store()

    def _open_store(self) -> None:
        tables = {row[0] for row in self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "runs" not in tables:
            self._db.executescript(_SCHEMA)
            self._db.executescript(_SCHEMA_V2)
            self._db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            self._db.commit()
        else:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > _SCHEMA_VERSION:
                raise UnsafeState(
                    f"store {self.path} schema v{version} newer than "
                    f"reader v{_SCHEMA_VERSION}: refusing to guess")
            if version < _SCHEMA_VERSION:
                self.backup(auto=True)
                self._db.executescript(_SCHEMA)
                self._db.executescript(_SCHEMA_V2)
                self._db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                self._db.commit()
        check = self._db.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise UnsafeState(f"store {self.path} failed quick_check: {check}")
        self._db.execute(
            "INSERT OR REPLACE INTO meta(key, value, updated_utc)"
            " VALUES('durability', ?, ?)",
            (json.dumps(self.durability_mode(), sort_keys=True), _now()))
        self._db.commit()

    def close(self) -> None:
        self.release_lock()
        self._db.commit()
        self._db.close()

    # -- durability ------------------------------------------------------
    def durability_mode(self) -> dict[str, Any]:
        """Recorded durability posture (contract v1 §4).

        WAL + synchronous=NORMAL is process-crash safe; power-loss
        safety is explicitly NOT claimed. Persisted in meta on open;
        the release config records the same mode.
        """
        journal = self._db.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = self._db.execute("PRAGMA synchronous").fetchone()[0]
        return {"journal_mode": journal, "synchronous": synchronous,
                "process_crash_safe": True, "power_loss_safe": False,
                "note": _DURABILITY_NOTE}

    # -- single-instance lock ---------------------------------------------
    def acquire_lock(self) -> None:
        """Hold the single-instance lock for this store path (v1 §4).

        Raises StoreLocked when another LIVE process holds it. A stale
        lock (holder pid dead) is taken over: SQLite WAL already makes
        the survivor's view crash-consistent, and the takeover is
        recorded in meta. Same-process re-acquire refcounts.
        """
        key = str(self.path.resolve())
        if key in RunStore._held:
            RunStore._held[key] += 1
            return
        lock_path = self.path.with_name(self.path.name + ".lock")
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                # A held flock always means a live holder (the OS
                # releases a dead process's flock, and a merely stale
                # pid in the file takes the success path above). An
                # unseen live writer may exist: refuse, never guess.
                holder = self._lock_holder(fd)
                raise StoreLocked(
                    f"store {self.path} locked by live holder "
                    f"(pid file: {holder})") from exc
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
            self._lock_fd = fd
            RunStore._held[key] = 1
            self._db.execute(
                "INSERT OR REPLACE INTO meta(key, value, updated_utc)"
                " VALUES('lock_holder', ?, ?)", (str(os.getpid()), _now()))
            self._db.commit()
        except BaseException:
            if self._lock_fd is None:
                os.close(fd)
            raise

    @staticmethod
    def _lock_holder(fd: int) -> int | None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 32).decode("ascii").strip()
        except OSError:
            return None
        return int(raw) if raw.isdigit() else None

    def release_lock(self) -> None:
        """Release one refcount level of the single-instance lock."""
        key = str(self.path.resolve())
        held = RunStore._held.get(key, 0)
        if held > 1:
            RunStore._held[key] = held - 1
            return
        RunStore._held.pop(key, None)
        if self._lock_fd is not None:
            import fcntl
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None

    def backup(self, dest: str | Path | None = None,
               *, auto: bool = False) -> Path:
        """Online backup via the SQLite backup API (v1 §4).

        Auto backups (pre-migration) land beside the store with a UTC
        timestamp suffix. The destination must not be an existing live
        store (refuse to clobber).
        """
        if dest is None:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            dest = self.path.with_name(f"{self.path.name}.bak-{stamp}")
        dest = Path(dest)
        if dest.exists():
            raise UnsafeState(f"backup destination {dest} already exists")
        target = sqlite3.connect(str(dest))
        try:
            self._db.backup(target)
        finally:
            target.close()
        return dest

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
        return dict(zip(keys, row, strict=False))

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

    # -- command intentions (contract v1 §4) ------------------------------
    def record_command(self, run_id: str, cmd_id: str, kind: str,
                       payload: dict[str, Any],
                       ts_utc: str | None = None) -> None:
        """Persist a command intention BEFORE it is submitted.

        A command that might already have reached the venue must
        reconcile by its durable client ID before any resubmission;
        this row is the anchor. Duplicate cmd_id is a programmer
        error (raise, never silently merge two commands).
        """
        if kind not in ("submit", "cancel", "flatten"):
            raise ValueError(f"command kind must be submit|cancel|flatten, "
                             f"got {kind!r}")
        now = ts_utc or _now()
        try:
            self._db.execute(
                "INSERT INTO commands(cmd_id, run_id, kind, payload,"
                " engine_client_id, status, ts_utc, updated_utc)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (cmd_id, run_id, kind, json.dumps(payload, sort_keys=True),
                 None, "intended", now, now))
        except sqlite3.IntegrityError:
            raise ValueError(f"duplicate command id {cmd_id!r}") from None
        self._db.commit()

    def update_command(self, cmd_id: str, status: str,
                       engine_client_id: str | None = None) -> None:
        """Advance a command: intended → submitted → resolved|failed.

        Terminal statuses (resolved/failed) never regress; unknown
        marks a submitted command whose outcome needs lookup. Unknown
        cmd_id raises KeyError (refuse to invent history).
        """
        if status not in ("intended", "submitted", "unknown", "resolved",
                          "failed"):
            raise ValueError(f"bad command status {status!r}")
        row = self._db.execute("SELECT status FROM commands WHERE cmd_id=?",
                               (cmd_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown command {cmd_id}")
        if row[0] in ("resolved", "failed") and status not in ("resolved",
                                                               "failed"):
            raise ValueError(f"command {cmd_id} already terminal ({row[0]})")
        if engine_client_id is None:
            self._db.execute("UPDATE commands SET status=?, updated_utc=?"
                             " WHERE cmd_id=?", (status, _now(), cmd_id))
        else:
            self._db.execute("UPDATE commands SET status=?, updated_utc=?,"
                             " engine_client_id=? WHERE cmd_id=?",
                             (status, _now(), engine_client_id, cmd_id))
        self._db.commit()

    def open_commands(self, run_id: str) -> list[dict[str, Any]]:
        """Commands needing reconciliation (intended/submitted/unknown)."""
        rows = self._db.execute(
            "SELECT cmd_id, kind, payload, engine_client_id, status, ts_utc"
            " FROM commands WHERE run_id=? AND status IN (?,?,?)"
            " ORDER BY ts_utc, cmd_id", (run_id, *_OPEN_STATUSES)).fetchall()
        return [{"cmd_id": r[0], "kind": r[1],
                 "payload": json.loads(r[2]), "engine_client_id": r[3],
                 "status": r[4], "ts_utc": r[5]} for r in rows]

    # -- crash-consistent cursors (contract v1 §4) -------------------------
    def read_events(self, run_id: str, after_id: int = 0,
                    kinds: tuple[str, ...] | None = None,
                    limit: int = 10000) -> list[dict[str, Any]]:
        """Execution events after a cursor (autoincrement id, monotonic).

        Recovery replays from its last applied cursor; rows are
        immutable once committed, so re-reading is always safe.
        """
        if kinds is None:
            rows = self._db.execute(
                "SELECT id, execution_id, kind, payload, ts_utc"
                " FROM execution_events WHERE run_id=? AND id>?"
                " ORDER BY id LIMIT ?", (run_id, after_id, limit)).fetchall()
        else:
            marks = ",".join("?" for _ in kinds)
            rows = self._db.execute(
                "SELECT id, execution_id, kind, payload, ts_utc"
                f" FROM execution_events WHERE run_id=? AND id>? AND kind IN ({marks})"
                " ORDER BY id LIMIT ?", (run_id, after_id, *kinds,
                                         limit)).fetchall()
        return [{"cursor": r[0], "execution_id": r[1], "kind": r[2],
                 "payload": json.loads(r[3]), "ts_utc": r[4]} for r in rows]

    def command_count(self, run_id: str) -> int:
        """Rows in commands for a run (dense cmd seq seeding on resume)."""
        return self._db.execute("SELECT COUNT(*) FROM commands WHERE run_id=?",
                                (run_id,)).fetchone()[0]

    def applied_exec_ids(self, run_id: str,
                         kind: str = "fill") -> set[str]:
        """Durable set of persisted event keys (idempotency rebuild)."""
        rows = self._db.execute(
            "SELECT execution_id FROM execution_events WHERE run_id=?"
            " AND kind=?", (run_id, kind)).fetchall()
        return {r[0] for r in rows}

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

    def clear_stop(self, run_id: str) -> bool:
        """Withdraw a stop request (explicit operator action).

        A consumed stop is never cleared by the loop itself: an
        unattended restart must not silently continue a run the
        operator stopped. Resume-after-stop requires this explicit
        call. Returns True when a request was actually withdrawn.
        """
        cur = self._db.execute("DELETE FROM stop_requests WHERE run_id=?",
                               (run_id,))
        self._db.commit()
        return cur.rowcount > 0
