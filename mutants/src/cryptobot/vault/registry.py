"""Hash-chained chunk registry for the sealed data vault (F3.5).

Layout under the vault root (default ``data/vault``)::

    registry.json        {"version": 1, "entries": [...]} (hash-chained)
    chunks/<chunk_id>    sealed chunk bytes (content-addressed by sha256)
    tokens.json          one-shot verdict tokens (see tokens.py)
    access.log.jsonl     hash-chained access log (see loader.py)

A registry entry covers the chunk bytes (sha256), the time range the chunk
spans, provenance, the seal timestamp, and the previous entry hash, so any
tampering with an entry breaks :meth:`Registry.verify_chain`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from cryptobot.vault._common import (
    DEFAULT_VAULT_ROOT,
    GENESIS_HASH,
    VaultUnknownChunk,
    atomic_write_json,
    canonical_hash,
    coerce_utc,
    parse_utc,
    sha256_file,
    utc_now_iso,
)

REGISTRY_VERSION = 1
REGISTRY_FILENAME = "registry.json"
CHUNKS_DIRNAME = "chunks"


class Registry:
    """Append-only, hash-chained registry of sealed chunks."""

    def __init__(
        self,
        root: str | Path | None = None,
        now_utc: Callable[[], str | datetime] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else DEFAULT_VAULT_ROOT
        self._now_utc = now_utc

    # -- paths ---------------------------------------------------------
    @property
    def registry_path(self) -> Path:
        return self.root / REGISTRY_FILENAME

    @property
    def chunks_dir(self) -> Path:
        return self.root / CHUNKS_DIRNAME

    def chunk_path(self, chunk_id: str) -> Path:
        return self.chunks_dir / chunk_id

    # -- persistence ---------------------------------------------------
    def _load_entries(self) -> list[dict]:
        if not self.registry_path.is_file():
            return []
        with open(self.registry_path, encoding="utf-8") as fh:
            data = json.load(fh)
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("registry.json corrupt: 'entries' is not a list")
        return entries

    def _save_entries(self, entries: list[dict]) -> None:
        atomic_write_json(
            self.registry_path, {"version": REGISTRY_VERSION, "entries": entries}
        )

    # -- sealing -------------------------------------------------------
    def seal_chunk(
        self,
        path: str | Path,
        *,
        time_start_utc: str | datetime,
        time_end_utc: str | datetime,
        provenance: str,
    ) -> dict:
        """Seal a chunk file into the vault and return its registry record.

        The chunk file is copied to ``<root>/chunks/<chunk_id>`` where
        ``chunk_id`` is the source file's name (must be unique). Re-sealing
        an existing chunk_id is rejected: the registry is append-only.
        """
        src = Path(path)
        if not src.is_file():
            raise FileNotFoundError(f"chunk source not found: {src}")
        chunk_id = src.name
        if not chunk_id or chunk_id in (".", ".."):
            raise ValueError(f"invalid chunk_id derived from path: {path!r}")

        start = coerce_utc(time_start_utc)
        end = coerce_utc(time_end_utc)
        if parse_utc(start) > parse_utc(end):
            raise ValueError("time_start_utc must be <= time_end_utc")

        entries = self._load_entries()
        if any(e.get("chunk_id") == chunk_id for e in entries):
            raise ValueError(f"chunk already sealed: {chunk_id}")

        dest = self.chunk_path(chunk_id)
        if dest.exists() and not _same_file(src, dest):
            raise ValueError(f"chunks/ name collision with different bytes: {chunk_id}")
        if not dest.exists():
            self.chunks_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())

        sha256, nbytes = sha256_file(dest)
        prev_hash = entries[-1]["entry_hash"] if entries else GENESIS_HASH
        record = {
            "chunk_id": chunk_id,
            "sha256": sha256,
            "bytes": nbytes,
            "time_range": {"start": start, "end": end},
            "provenance": str(provenance),
            "sealed_utc": utc_now_iso(self._now_utc),
            "prev_hash": prev_hash,
        }
        record["entry_hash"] = canonical_hash(record)
        entries.append(record)
        self._save_entries(entries)
        return dict(record)

    # -- reads ---------------------------------------------------------
    def get(self, chunk_id: str) -> dict | None:
        """Return a copy of the registry record, or None if unknown."""
        for entry in self._load_entries():
            if entry.get("chunk_id") == chunk_id:
                return dict(entry)
        return None

    def chunk_ids(self) -> list[str]:
        return [e["chunk_id"] for e in self._load_entries() if "chunk_id" in e]

    def classify(
        self,
        chunk_id: str,
        hypothesis: str,
        freeze_record: dict | str | Path,
    ) -> str:
        """Classify a chunk as DEV or CONFIRM for a hypothesis.

        CONFIRM iff the chunk was sealed strictly AFTER the hypothesis
        freeze timestamp AND its provenance is not SYNTHETIC. Synthetic
        data is never CONFIRM. ``freeze_record`` is the
        ``research/freeze/<X>.json`` mapping
        ``{config_hash, frozen_commit, frozen_utc}`` (or a path to one).
        """
        record = self.get(chunk_id)
        if record is None:
            raise VaultUnknownChunk(f"unknown chunk: {chunk_id}")
        freeze = _load_freeze_record(freeze_record)
        owner = freeze.get("hypothesis")
        if owner is not None and owner != hypothesis:
            raise ValueError(
                f"freeze record is for {owner!r}, not hypothesis {hypothesis!r}"
            )
        try:
            frozen_utc = freeze["frozen_utc"]
        except KeyError:
            raise ValueError("freeze record missing 'frozen_utc'") from None
        if str(record.get("provenance", "")).upper() == "SYNTHETIC":
            return "DEV"
        sealed = parse_utc(record["sealed_utc"])
        frozen = parse_utc(str(frozen_utc))
        return "CONFIRM" if sealed > frozen else "DEV"

    # -- tamper evidence -----------------------------------------------
    def verify_chain(self) -> bool:
        """Re-read registry.json from disk and verify the hash chain."""
        try:
            entries = self._load_entries()
        except (OSError, ValueError):
            return False
        prev = GENESIS_HASH
        for entry in entries:
            try:
                if entry.get("prev_hash") != prev:
                    return False
                body = {k: v for k, v in entry.items() if k != "entry_hash"}
                if not body.get("chunk_id") or not entry.get("entry_hash"):
                    return False
                if canonical_hash(body) != entry["entry_hash"]:
                    return False
                prev = entry["entry_hash"]
            except (AttributeError, TypeError, KeyError):
                return False
        return True


def seal_chunk(
    path: str | Path,
    *,
    time_start_utc: str | datetime,
    time_end_utc: str | datetime,
    provenance: str,
    root: str | Path | None = None,
    now_utc: Callable[[], str | datetime] | None = None,
) -> dict:
    """Module-level convenience wrapper around :meth:`Registry.seal_chunk`."""
    return Registry(root=root, now_utc=now_utc).seal_chunk(
        path,
        time_start_utc=time_start_utc,
        time_end_utc=time_end_utc,
        provenance=provenance,
    )


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _load_freeze_record(freeze_record: dict | str | Path) -> dict:
    if isinstance(freeze_record, dict):
        return freeze_record
    with open(freeze_record, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("freeze record file must contain a JSON object")
    return data
