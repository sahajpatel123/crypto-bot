"""Shared primitives for the sealed data vault (F3.5).

This private module holds the hash-chain helpers, atomic-write helper,
UTC time helpers, and the vault exception hierarchy used by
:mod:`cryptobot.vault.registry`, :mod:`cryptobot.vault.tokens`, and
:mod:`cryptobot.vault.loader`.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64

DEFAULT_VAULT_ROOT = Path("data/vault")
DEFAULT_FREEZE_DIR = Path("research/freeze")


class VaultError(Exception):
    """Base class for all vault failures."""


class VaultRefused(VaultError):
    """A chunk load was refused (fail closed)."""


class VaultUnknownChunk(VaultRefused):
    """The requested chunk_id is not in the registry."""


class VaultSynthetic(VaultError):
    """Provenance gate: the record is synthetic (or unstamped)."""


def canonical_hash(obj: Any) -> str:
    """sha256 over canonical JSON (sorted keys, compact separators)."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    """Return (sha256 hex digest, byte length) of a file."""
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
            total += len(block)
    return digest.hexdigest(), total


def atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON atomically (temp file + fsync + os.replace + dir fsync)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def append_jsonl(path: Path, obj: Any) -> None:
    """Append one JSON object line with fsync (never rewrites history)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def coerce_utc(value: str | datetime) -> str:
    """Normalize a timestamp to an ISO-8601 UTC string."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    return str(value)


def utc_now_iso(now_utc: Callable[[], str | datetime] | None = None) -> str:
    """Current UTC time as ISO-8601 (injectable for deterministic tests)."""
    if now_utc is None:
        return datetime.now(UTC).isoformat()
    return coerce_utc(now_utc())


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp to an aware UTC datetime (naive -> UTC)."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
