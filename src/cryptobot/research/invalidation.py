"""Hash-chained invalidation of machine verdicts (closeout C1/C2).

A verdict whose ``document_sha256`` appears in a valid chain must not
be consumed by verdict, autopilot, or gate. Editing or deleting an
entry breaks ``prev`` / ``entry_hash`` / ``chain_head`` and
``verify_invalidation_chain`` reports it. A broken chain fails closed:
consumers refuse every verdict that relied on that file.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = "cryptobot-verdict-invalidations/1"


def _sha(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def empty_chain() -> dict:
    return {"format": FORMAT, "chain_head": "genesis", "entries": []}


def verify_invalidation_chain(doc: dict | None) -> list[str]:
    """Problems in the chain. Empty means intact."""
    if not isinstance(doc, dict):
        return ["invalidation record missing or not an object"]
    if doc.get("format") != FORMAT:
        return [f"format {doc.get('format')!r} != {FORMAT}"]
    problems: list[str] = []
    prev = "genesis"
    for i, entry in enumerate(doc.get("entries", [])):
        if not isinstance(entry, dict):
            problems.append(f"entry {i}: not an object")
            break
        if entry.get("prev") != prev:
            problems.append(f"entry {i}: prev mismatch")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        if _sha(body) != entry.get("entry_hash"):
            problems.append(f"entry {i}: hash mismatch")
        prev = entry.get("entry_hash")
    if prev != doc.get("chain_head"):
        problems.append("chain_head mismatch")
    return problems


def load_chain(path: str | Path | None) -> dict | None:
    if not path:
        return None
    file = Path(path)
    if not file.exists():
        return None
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"format": "unreadable", "chain_head": None, "entries": []}


def sibling_chain(verdict_path: str | Path | None) -> Path | None:
    if not verdict_path:
        return None
    sibling = Path(verdict_path).parent / "invalidations.json"
    return sibling if sibling.exists() else None


def invalidated_hashes(doc: dict | None) -> set[str]:
    """Hashes named by an intact chain. A broken chain yields nothing
    here; callers must check ``verify_invalidation_chain`` and fail
    closed separately.
    """
    if verify_invalidation_chain(doc):
        return set()
    out: set[str] = set()
    for entry in (doc or {}).get("entries", []):
        if entry.get("action") == "invalidate" and entry.get("verdict_sha256"):
            out.add(str(entry["verdict_sha256"]))
    return out


def verdict_consumption(verdict: dict | None,
                        chain: dict | None) -> tuple[bool, str]:
    """(allowed, reason). Broken chain or a listed hash is not allowed."""
    if chain is None:
        return True, ""
    problems = verify_invalidation_chain(chain)
    if problems:
        return False, "invalidation chain broken: " + "; ".join(problems)
    digest = str((verdict or {}).get("document_sha256") or "")
    if digest and digest in invalidated_hashes(chain):
        return False, f"verdict {digest[:16]} invalidated"
    return True, ""


def holdout_burned(hypothesis: str, chain: dict | None = None,
                   path: str | Path | None = None) -> bool:
    """B4 and any B4* variant are burned once an intact chain says so."""
    doc = chain if chain is not None else load_chain(path)
    if not doc or verify_invalidation_chain(doc):
        # A broken chain does not silently un-burn; callers that need
        # fail-closed already refused via verdict_consumption. Burn
        # lookups on a broken chain are treated as burned for B4*.
        if doc and verify_invalidation_chain(doc) and _is_b4(hypothesis):
            return True
        if not doc:
            return False
    for entry in doc.get("entries", []):
        if entry.get("holdout") != "BURNED":
            continue
        for name in entry.get("burned_hypotheses", []):
            if hypothesis == name or (
                _is_b4(hypothesis) and _is_b4(str(name))):
                return True
        rule = str(entry.get("rule") or "")
        if _is_b4(hypothesis) and "B4" in rule:
            return True
    return False


def _is_b4(hypothesis: str) -> bool:
    return hypothesis == "B4" or hypothesis.startswith("B4")


def append_invalidation(path: str | Path, body: dict[str, Any]) -> dict:
    """Append one entry. ``body`` must not include prev or entry_hash."""
    file = Path(path)
    doc = load_chain(file) or empty_chain()
    problems = verify_invalidation_chain(doc)
    if problems and doc.get("entries"):
        raise ValueError("refusing to append to a broken chain: "
                         + "; ".join(problems))
    if not doc.get("entries"):
        doc = empty_chain()
    entry = dict(body)
    entry["ts_utc"] = entry.get("ts_utc") or _utc_now()
    entry["prev"] = doc.get("chain_head", "genesis")
    entry["entry_hash"] = _sha(
        {k: v for k, v in entry.items() if k != "entry_hash"})
    doc.setdefault("entries", []).append(entry)
    doc["chain_head"] = entry["entry_hash"]
    doc["format"] = FORMAT
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(file.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(file)
    return doc


__all__ = [
    "FORMAT", "append_invalidation", "empty_chain", "holdout_burned",
    "invalidated_hashes", "load_chain", "sibling_chain",
    "verdict_consumption", "verify_invalidation_chain",
]
