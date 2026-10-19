"""F2.3: recorded-fixture validation and installation.

Demo/testnet responses are valuable contract evidence, but they must be
redacted before they enter the repository. This module refuses payloads
that look like they contain credentials, validates JSON, writes a
SHA-256 index, and never overwrites an existing different fixture
without ``force=True``.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORBIDDEN_KEYS = {
    "apikey", "api_key", "secret", "secretkey", "signature", "authorization",
    "listenkey", "listen_key", "token", "password", "passphrase",
    "privatekey", "private_key", "x-mbx-apikey",
}
SYNTHETIC_MARKERS = ("synthetic", "simulated fixture", "fake")
MAX_FIXTURE_BYTES = 8 << 20


class FixtureError(RuntimeError):
    pass


def _walk_keys(value: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            norm = str(key).strip().lower().replace("-", "_")
            if norm.replace("_", "") in {k.replace("_", "") for k in FORBIDDEN_KEYS}:
                hits.append(f"{path}.{key}")
            hits.extend(_walk_keys(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            hits.extend(_walk_keys(child, f"{path}[{i}]"))
    return hits


def validate_fixture(path: Path) -> dict:
    if path.stat().st_size > MAX_FIXTURE_BYTES:
        raise FixtureError(f"{path.name}: larger than {MAX_FIXTURE_BYTES} bytes")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FixtureError(f"{path.name}: invalid JSON: {exc}") from exc
    secrets = _walk_keys(doc)
    if secrets:
        raise FixtureError(
            f"{path.name}: credential-like keys must be redacted: {secrets}")
    text = json.dumps(doc).lower()
    if any(marker in text for marker in SYNTHETIC_MARKERS):
        raise FixtureError(
            f"{path.name}: synthetic marker present; recorded fixtures must "
            "be labelled demo-recorded")
    return doc


def ingest_fixtures(source: str | Path, dest: str | Path,
                    *, force: bool = False) -> dict:
    src = Path(source)
    out = Path(dest)
    if not src.is_dir():
        raise FixtureError(f"source is not a directory: {src}")
    files = sorted(p for p in src.glob("*.json") if p.is_file())
    if not files:
        raise FixtureError(f"no *.json fixtures in {src}")
    out.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for path in files:
        doc = validate_fixture(path)
        digest = hashlib.sha256(
            json.dumps(doc, sort_keys=True).encode()).hexdigest()
        target = out / path.name
        entry = {"name": path.name, "sha256": digest,
                 "bytes": path.stat().st_size,
                 "provenance": "demo-recorded",
                 "ingested_utc": datetime.now(timezone.utc).isoformat()}
        if target.exists() and not force:
            old = hashlib.sha256(
                json.dumps(json.loads(target.read_text(encoding="utf-8")),
                           sort_keys=True).encode()).hexdigest()
            if old != digest:
                raise FixtureError(
                    f"{path.name} already exists with different content "
                    "(use --force after reviewing the diff)")
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, target)
        entries.append(entry)
    index = {
        "format": "cryptobot-recorded-fixtures/1",
        "source": str(src),
        "installed_utc": datetime.now(timezone.utc).isoformat(),
        "fixtures": entries,
    }
    index_path = out / "index.json"
    tmp = index_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, index_path)
    return index


__all__ = ["FixtureError", "validate_fixture", "ingest_fixtures",
           "FORBIDDEN_KEYS"]
