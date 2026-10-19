"""Gated chunk loader with hash-chained access log (F3.5).

Access policy (fail closed):

* Unknown chunk, missing/tampered chunk bytes -> refuse.
* ``hypothesis`` given: its freeze record ``<freeze_dir>/<H>.json`` must
  exist, else refuse (a bogus hypothesis name must not downgrade CONFIRM
  data to DEV). DEV loads freely; CONFIRM needs a one-shot token minted
  for that hypothesis covering that chunk.
* ``hypothesis=None`` (DEV exploration): granted only if the chunk is DEV
  against EVERY freeze record present; CONFIRM-for-any is refused.

Every attempt (granted or refused) is appended to
``<root>/access.log.jsonl`` as a hash-chained entry. Raw tokens are never
logged, only a 16-hex-char fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from cryptobot.vault._common import (
    DEFAULT_FREEZE_DIR,
    DEFAULT_VAULT_ROOT,
    GENESIS_HASH,
    VaultRefused,
    VaultSynthetic,
    VaultUnknownChunk,
    append_jsonl,
    canonical_hash,
    sha256_file,
    utc_now_iso,
)
from cryptobot.vault.registry import Registry
from cryptobot.vault.tokens import TokenStore

ACCESS_LOG_FILENAME = "access.log.jsonl"


def get_record(root: str | Path, chunk_id: str) -> dict:
    """Fetch a registry record copy, or raise VaultUnknownChunk."""
    record = Registry(root=root).get(chunk_id)
    if record is None:
        raise VaultUnknownChunk(f"unknown chunk: {chunk_id}")
    return record


def check_provenance(record: Mapping) -> None:
    """Fail-closed provenance gate for verdict/gate wiring.

    Raises VaultSynthetic when provenance is SYNTHETIC (any case) or when
    the record carries no provenance stamp at all.
    """
    provenance = record.get("provenance") if isinstance(record, Mapping) else None
    if provenance is None or str(provenance).upper() == "SYNTHETIC":
        raise VaultSynthetic(f"synthetic or unstamped data refused: {provenance!r}")


def load_chunk(
    root: str | Path,
    chunk_id: str,
    *,
    hypothesis: str | None = None,
    token: str | None = None,
    freeze_dir: str | Path | None = None,
    now_utc: Callable[[], str | datetime] | None = None,
) -> bytes:
    """Load a chunk's bytes under the access policy (every attempt logged)."""
    vault_root = Path(root)
    freeze_path = Path(freeze_dir) if freeze_dir is not None else DEFAULT_FREEZE_DIR
    registry = Registry(root=vault_root)
    record = registry.get(chunk_id)
    if record is None:
        _log_attempt(
            vault_root, chunk_id, hypothesis, "refused", "unknown-chunk", token,
            now_utc=now_utc,
        )
        raise VaultUnknownChunk(f"unknown chunk: {chunk_id}")

    chunk_file = registry.chunk_path(chunk_id)
    if not chunk_file.is_file():
        _log_attempt(
            vault_root, chunk_id, hypothesis, "refused", "chunk-missing", token,
            now_utc=now_utc,
        )
        raise VaultRefused(f"chunk bytes missing for {chunk_id}")
    actual_sha, _ = sha256_file(chunk_file)
    if actual_sha != record.get("sha256"):
        _log_attempt(
            vault_root, chunk_id, hypothesis, "refused", "chunk-hash-mismatch",
            token, now_utc=now_utc,
        )
        raise VaultRefused(f"chunk bytes do not match registry (tamper?): {chunk_id}")

    if hypothesis is None:
        classes = _classify_against_all(
            registry, chunk_id, _read_all_freeze_records(freeze_path)
        )
        if "CONFIRM" in classes.values():
            _log_attempt(
                vault_root, chunk_id, hypothesis, "refused",
                "confirm-needs-hypothesis-token", token, now_utc=now_utc,
            )
            raise VaultRefused(
                f"{chunk_id} is CONFIRM for another hypothesis; "
                "load with hypothesis + one-shot token"
            )
        _log_attempt(
            vault_root, chunk_id, hypothesis, "granted", "dev", token,
            now_utc=now_utc,
        )
        return chunk_file.read_bytes()

    freeze_file = freeze_path / f"{hypothesis}.json"
    if not freeze_file.is_file():
        _log_attempt(
            vault_root, chunk_id, hypothesis, "refused", "no-freeze-record", token,
            now_utc=now_utc,
        )
        raise VaultRefused(f"no freeze record for hypothesis {hypothesis!r}")
    with open(freeze_file, encoding="utf-8") as fh:
        freeze_record = json.load(fh)
    classification = registry.classify(chunk_id, hypothesis, freeze_record)
    if classification == "DEV":
        _log_attempt(
            vault_root, chunk_id, hypothesis, "granted", "dev", token,
            now_utc=now_utc,
        )
        return chunk_file.read_bytes()

    if not token or not TokenStore(root=vault_root).redeem(token, hypothesis, chunk_id):
        _log_attempt(
            vault_root, chunk_id, hypothesis, "refused", "confirm-needs-token",
            token, now_utc=now_utc,
        )
        raise VaultRefused(
            f"{chunk_id} is CONFIRM for {hypothesis!r}; valid one-shot token required"
        )
    _log_attempt(
        vault_root, chunk_id, hypothesis, "granted", "confirm-token", token,
        now_utc=now_utc,
    )
    return chunk_file.read_bytes()


def verify_access_log(
    root: str | Path | None = None,
    *,
    filename: str = ACCESS_LOG_FILENAME,
) -> bool:
    """Verify the hash chain of the access log (missing log == valid/empty)."""
    vault_root = Path(root) if root is not None else DEFAULT_VAULT_ROOT
    log_path = vault_root / filename
    if not log_path.is_file():
        return True
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    prev = GENESIS_HASH
    expected_seq = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            return False
        try:
            if entry.get("seq") != expected_seq:
                return False
            if entry.get("prev_hash") != prev:
                return False
            body = {k: v for k, v in entry.items() if k != "entry_hash"}
            if not entry.get("entry_hash") or not entry.get("decision"):
                return False
            if canonical_hash(body) != entry["entry_hash"]:
                return False
            prev = entry["entry_hash"]
            expected_seq += 1
        except (AttributeError, TypeError, KeyError):
            return False
    return True


def _read_all_freeze_records(freeze_dir: Path) -> dict[str, dict]:
    if not freeze_dir.is_dir():
        return {}
    records = {}
    for path in sorted(freeze_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and "frozen_utc" in data:
            records[path.stem] = data
    return records


def _classify_against_all(
    registry: Registry, chunk_id: str, freeze_records: dict[str, dict]
) -> dict[str, str]:
    classes = {}
    for name, freeze in freeze_records.items():
        try:
            classes[name] = registry.classify(chunk_id, name, freeze)
        except ValueError:
            # Mismatched-owner freeze file: fail closed, treat as CONFIRM.
            classes[name] = "CONFIRM"
    return classes


def _log_attempt(
    root: Path,
    chunk_id: str,
    hypothesis: str | None,
    decision: str,
    reason: str,
    token: str | None,
    *,
    now_utc: Callable[[], str | datetime] | None = None,
) -> dict:
    log_path = root / ACCESS_LOG_FILENAME
    prev = GENESIS_HASH
    seq = 0
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                break
            if isinstance(entry, dict) and "entry_hash" in entry:
                prev = entry["entry_hash"]
                seq = int(entry.get("seq", seq)) + 1
    entry_body = {
        "seq": seq,
        "ts_utc": utc_now_iso(now_utc),
        "chunk_id": chunk_id,
        "hypothesis": hypothesis,
        "decision": decision,
        "reason": reason,
        "token_fp": _token_fingerprint(token),
        "prev_hash": prev,
    }
    entry_body["entry_hash"] = canonical_hash(entry_body)
    append_jsonl(log_path, entry_body)
    return entry_body


def _token_fingerprint(token: str | None) -> str | None:
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
