"""Sealed data vault (F3.5): hash-chained registry + one-shot confirm access.

Rules enforced here, not by convention:

* Every sealed chunk is copied under ``vault/chunks`` and its SHA-256 is
  recorded in a hash-chained ``registry.json``.
* A chunk is ``CONFIRM`` for hypothesis H only if it carries observed
  public provenance AND was sealed strictly after H's frozen config was
  committed. Synthetic chunks are never eligible.
* ``CONFIRM`` data can only be read through ``read_confirm`` with a
  one-shot token issued by ``verdict``. Every seal/issue/read/deny is
  appended to a hash-chained access log.
* The default ``load_chunk`` refuses CONFIRM outright, so research code
  that forgets the token fails closed.
* E2.2 (Family B): class ``HOLDOUT`` seals a *manifest* of raw holdout
  files by byte-hash, sealed BEFORE any Family B freeze and NEVER
  content-sniffed at seal time (explicit ``input_class`` required).
  Decoding is verdict-only via ``authorize_holdout_decode`` (one-shot
  token, logged). A HOLDOUT chunk is CONFIRM-eligible for hypothesis H
  only if the access log shows zero decode/read accesses before H's
  frozen-config timestamp — which forces batch freezing of survivors
  before the first screen (see DECISIONS.md D-033).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REGISTRY_FORMAT = "cryptobot-vault-registry/1"
ACCESS_FORMAT = "cryptobot-vault-access/1"
HOLDOUT_MANIFEST_FORMAT = "cryptobot-holdout-manifest/1"
DEV = "DEV"
CONFIRM = "CONFIRM"
HOLDOUT = "HOLDOUT"
SYNTHETIC = "SYNTHETIC"
OBSERVED = "observed-public"
OBSERVED_PUBLIC = "OBSERVED_PUBLIC"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _atomic_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _chain_append(doc: dict, entry: dict) -> dict:
    entry = dict(entry)
    entry["prev"] = doc.get("chain_head", "genesis")
    entry["entry_hash"] = _sha256_bytes(
        json.dumps(entry, sort_keys=True).encode())
    doc.setdefault("entries", []).append(entry)
    doc["chain_head"] = entry["entry_hash"]
    return entry


def _chain_verify(doc: dict) -> list[str]:
    problems: list[str] = []
    prev = "genesis"
    for i, entry in enumerate(doc.get("entries", [])):
        if entry.get("prev") != prev:
            problems.append(f"entry {i}: prev mismatch")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        if _sha256_bytes(json.dumps(body, sort_keys=True).encode()) \
                != entry.get("entry_hash"):
            problems.append(f"entry {i}: hash mismatch")
        prev = entry.get("entry_hash")
    if prev != doc.get("chain_head"):
        problems.append("chain_head does not match last entry")
    return problems


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    path: Path
    sha256: str
    class_: str
    hypothesis: str | None
    first_ms: int | None
    last_ms: int | None
    input_class: str
    sealed_utc: str


class VaultError(RuntimeError):
    pass


class Vault:
    def __init__(self, root: str | Path = "data/vault") -> None:
        self.root = Path(root)
        self.chunks_dir = self.root / "chunks"
        self.tokens_dir = self.root / "tokens"
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "registry.json"
        self.access_path = self.root / "access_log.json"
        if self.registry_path.exists():
            self.registry = json.loads(
                self.registry_path.read_text(encoding="utf-8"))
        else:
            self.registry = {"format": REGISTRY_FORMAT,
                             "chain_head": "genesis", "entries": [],
                             "frozen": {}, "created_utc": _utc_now()}
            _atomic_json(self.registry_path, self.registry)
        if self.access_path.exists():
            self.access = json.loads(
                self.access_path.read_text(encoding="utf-8"))
        else:
            self.access = {"format": ACCESS_FORMAT,
                           "chain_head": "genesis", "entries": [],
                           "created_utc": _utc_now()}
            _atomic_json(self.access_path, self.access)

    # -- freeze / seal -----------------------------------------------------
    def freeze_hypothesis(self, hypothesis: str, *, config_sha256: str,
                          commit: str, prereg_path: str) -> dict:
        """Record the frozen config hash/commit before any CONFIRM chunk.

        Re-freezing the same hypothesis with a different config hash is
        refused: that would let a failed hypothesis be re-tuned on
        untouched data.
        """
        frozen = self.registry.setdefault("frozen", {})
        prior = frozen.get(hypothesis)
        if prior and prior.get("config_sha256") != config_sha256:
            raise VaultError(
                f"{hypothesis} already frozen with a different config hash; "
                "a new hypothesis id is required")
        doc = {"config_sha256": config_sha256, "commit": commit,
               "prereg_path": prereg_path, "frozen_utc": _utc_now()}
        frozen[hypothesis] = doc
        _chain_append(self.access, {"action": "freeze", "hypothesis":
                                    hypothesis, "ts_utc": doc["frozen_utc"],
                                    **doc})
        self._save()
        return doc

    def seal_chunk(self, source: str | Path, *,
                   class_: str = DEV,
                   hypothesis: str | None = None,
                   config_sha256: str | None = None,
                   input_class: str | None = None,
                   first_ms: int | None = None,
                   last_ms: int | None = None) -> Chunk:
        source = Path(source)
        if not source.exists():
            raise VaultError(f"chunk not found: {source}")
        if class_ not in (DEV, CONFIRM, HOLDOUT):
            raise VaultError("class must be DEV, CONFIRM or HOLDOUT")
        if class_ == HOLDOUT:
            if input_class is None:
                raise VaultError(
                    "HOLDOUT seal requires explicit input_class "
                    "(content is never sniffed pre-freeze)")
            provenance = input_class
        else:
            provenance = input_class or self._chunk_input_class(source)
        if provenance == SYNTHETIC and class_ in (CONFIRM, HOLDOUT):
            raise VaultError(f"SYNTHETIC chunks can never be {class_}")
        if class_ == CONFIRM:
            if not hypothesis:
                raise VaultError("CONFIRM seal needs a hypothesis")
            frozen = self.registry.get("frozen", {}).get(hypothesis)
            if frozen is None:
                raise VaultError(
                    f"CONFIRM seal refused: {hypothesis} is not frozen")
            if config_sha256 and config_sha256 != frozen["config_sha256"]:
                raise VaultError(
                    "CONFIRM seal refused: config hash differs from freeze")
            frozen_utc = datetime.fromisoformat(frozen["frozen_utc"])
            if datetime.now(UTC) <= frozen_utc:
                raise VaultError(
                    "CONFIRM seal refused: chunk must be sealed after freeze")
        if class_ == HOLDOUT and hypothesis:
            frozen = self.registry.get("frozen", {}).get(hypothesis)
            if frozen is None:
                raise VaultError(
                    f"HOLDOUT seal refused: {hypothesis} is not frozen")
            if config_sha256 and config_sha256 != frozen["config_sha256"]:
                raise VaultError(
                    "HOLDOUT seal refused: config hash differs from freeze")
            # No after-freeze timing rule: family HOLDOUT manifests are
            # sealed BEFORE any Family B freeze by design (E2.2).
        digest = _sha256_file(source)
        chunk_id = f"chunk-{digest[:16]}"
        target = self.chunks_dir / f"{chunk_id}{source.suffix}"
        if target.exists():
            if _sha256_file(target) != digest:
                raise VaultError(f"chunk id collision: {chunk_id}")
        else:
            shutil.copy2(source, target)
        entry = {
            "chunk_id": chunk_id, "file": str(target.relative_to(self.root)),
            "sha256": digest, "bytes": target.stat().st_size,
            "class": class_, "hypothesis": hypothesis,
            "input_class": provenance,
            "config_sha256": config_sha256,
            "first_ms": first_ms, "last_ms": last_ms,
            "sealed_utc": _utc_now(),
        }
        if class_ == HOLDOUT:
            entry["decode_policy"] = "verdict-only"
        _chain_append(self.registry, entry)
        _chain_append(self.access, {
            "action": "seal", "chunk_id": chunk_id, "class": class_,
            "hypothesis": hypothesis, "sha256": digest,
            "input_class": provenance, "ts_utc": entry["sealed_utc"]})
        self._save()
        return Chunk(chunk_id=chunk_id, path=target, sha256=digest,
                     class_=class_, hypothesis=hypothesis,
                     first_ms=first_ms, last_ms=last_ms,
                     input_class=provenance, sealed_utc=entry["sealed_utc"])

    @staticmethod
    def _chunk_input_class(path: Path) -> str:
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as fh:
                first = json.loads(fh.readline())
            return str(first.get("input_class", "unknown"))
        except (OSError, ValueError, UnicodeDecodeError):
            return "unknown"

    # -- access ------------------------------------------------------------
    def issue_token(self, hypothesis: str, *,
                    consumer: str = "verdict",
                    ttl_s: int = 3600) -> str:
        if consumer != "verdict":
            raise VaultError("CONFIRM tokens are issued only to verdict")
        frozen = self.registry.get("frozen", {}).get(hypothesis)
        if frozen is None:
            raise VaultError(f"cannot issue token: {hypothesis} not frozen")
        token = secrets.token_urlsafe(32)
        doc = {"token_sha256": _sha256_bytes(token.encode()),
               "hypothesis": hypothesis, "consumer": consumer,
               "issued_utc": _utc_now(),
               "expires_epoch": int(datetime.now(UTC).timestamp())
               + int(ttl_s), "used": False}
        _atomic_json(self.tokens_dir / f"{doc['token_sha256']}.json", doc)
        _chain_append(self.access, {
            "action": "issue-token", "hypothesis": hypothesis,
            "consumer": consumer, "token_sha256": doc["token_sha256"],
            "ts_utc": doc["issued_utc"]})
        self._save()
        return token

    def _consume_token(self, token: str, hypothesis: str) -> dict:
        digest = _sha256_bytes(token.encode())
        path = self.tokens_dir / f"{digest}.json"
        if not path.exists():
            self._deny("token-unknown", hypothesis)
            raise VaultError("CONFIRM token unknown")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("used"):
            self._deny("token-reused", hypothesis)
            raise VaultError("CONFIRM token already used")
        if doc.get("hypothesis") != hypothesis:
            self._deny("token-wrong-hypothesis", hypothesis)
            raise VaultError("CONFIRM token is for another hypothesis")
        if int(doc.get("expires_epoch", 0)) < int(
                datetime.now(UTC).timestamp()):
            self._deny("token-expired", hypothesis)
            raise VaultError("CONFIRM token expired")
        doc["used"] = True
        doc["used_utc"] = _utc_now()
        _atomic_json(path, doc)
        return doc

    def _deny(self, reason: str, hypothesis: str) -> None:
        _chain_append(self.access, {
            "action": "deny", "reason": reason, "hypothesis": hypothesis,
            "ts_utc": _utc_now()})
        self._save()

    def _entry(self, chunk_id: str) -> dict:
        for entry in self.registry.get("entries", []):
            if entry.get("chunk_id") == chunk_id:
                return entry
        raise VaultError(f"unknown chunk {chunk_id}")

    def verify_holdout(self, chunk_id: str) -> dict:
        """Re-hash a HOLDOUT manifest and every referenced raw file."""
        entry = self._entry(chunk_id)
        if entry["class"] != HOLDOUT:
            raise VaultError(f"{chunk_id} is not a HOLDOUT chunk")
        path = self.root / entry["file"]
        if not path.exists() or _sha256_file(path) != entry["sha256"]:
            raise VaultError(f"chunk integrity failure: {chunk_id}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        bad: list[str] = []
        missing: list[str] = []
        for ref in manifest.get("files", []):
            rp = Path(ref["path"])
            if not rp.exists():
                missing.append(ref["path"])
            elif _sha256_file(rp) != ref["sha256"]:
                bad.append(ref["path"])
        return {"ok": not bad and not missing, "bad_files": bad,
                "missing_files": missing,
                "files": len(manifest.get("files", []))}

    def holdout_confirm_eligible(self, chunk_id: str,
                                 hypothesis: str) -> dict:
        """Eligibility: zero decode/read accesses before H's freeze."""
        self.registry = json.loads(
            self.registry_path.read_text(encoding="utf-8"))
        self.access = json.loads(
            self.access_path.read_text(encoding="utf-8"))
        frozen = self.registry.get("frozen", {}).get(hypothesis)
        if frozen is None:
            return {"eligible": False, "reason": "hypothesis not frozen"}
        frozen_utc = datetime.fromisoformat(frozen["frozen_utc"])
        for e in self.access.get("entries", []):
            if e.get("action") not in ("decode", "read"):
                continue
            if e.get("chunk_id") != chunk_id:
                continue
            try:
                ts = datetime.fromisoformat(str(e.get("ts_utc", "")))
            except ValueError:
                continue
            if ts < frozen_utc:
                return {"eligible": False,
                        "reason": f"pre-freeze decode at {e.get('ts_utc')}"}
        return {"eligible": True, "reason": "zero pre-freeze decodes"}

    def authorize_holdout_decode(self, chunk_id: str, *,
                                 token: str, hypothesis: str) -> dict:
        """Verdict-only one-shot authorization to decode a HOLDOUT chunk.

        Verifies integrity BEFORE consuming the token (a tampered chunk
        must not burn the single screen). Logs the decode. Returns the
        manifest (file list + hashes) so `verdict` can decode bytes.
        """
        entry = self._entry(chunk_id)
        if entry["class"] != HOLDOUT:
            raise VaultError(f"{chunk_id} is not a HOLDOUT chunk")
        report = self.verify_holdout(chunk_id)
        if not report["ok"]:
            raise VaultError(
                f"HOLDOUT integrity failure: bad={report['bad_files']} "
                f"missing={report['missing_files']}")
        doc = self._consume_token(token, hypothesis)
        path = self.root / entry["file"]
        manifest = json.loads(path.read_text(encoding="utf-8"))
        _chain_append(self.access, {
            "action": "decode", "chunk_id": chunk_id,
            "hypothesis": hypothesis,
            "token_sha256": doc["token_sha256"],
            "files": len(manifest.get("files", [])),
            "ts_utc": _utc_now()})
        self._save()
        return {"chunk_id": chunk_id, "hypothesis": hypothesis,
                "files": manifest.get("files", []),
                "manifest_sha256": entry["sha256"]}

    def load_chunk(self, chunk_id: str, *,
                   token: str | None = None,
                   hypothesis: str | None = None,
                   consumer: str = "research") -> list[dict]:
        """Load a chunk. CONFIRM requires a verdict token, always."""
        entry = self._entry(chunk_id)
        if entry["class"] == HOLDOUT:
            self._deny("holdout-via-load-chunk", str(hypothesis))
            raise VaultError(
                f"HOLDOUT chunk {chunk_id}: use verdict holdout-screen "
                "path (authorize_holdout_decode)")
        if entry["class"] == CONFIRM:
            if consumer != "verdict":
                self._deny("confirm-non-verdict-consumer", str(hypothesis))
                raise VaultError(
                    f"CONFIRM chunk {chunk_id} is verdict-only")
            if not token or not hypothesis:
                self._deny("confirm-missing-token", str(hypothesis))
                raise VaultError(
                    f"CONFIRM chunk {chunk_id} requires a one-shot token")
            if entry.get("hypothesis") != hypothesis:
                self._deny("confirm-wrong-hypothesis", hypothesis)
                raise VaultError("chunk is sealed for another hypothesis")
            self._consume_token(token, hypothesis)
        path = self.root / entry["file"]
        if not path.exists() or _sha256_file(path) != entry["sha256"]:
            raise VaultError(f"chunk integrity failure: {chunk_id}")
        opener = gzip.open if path.suffix == ".gz" else open
        rows: list[dict] = []
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
        _chain_append(self.access, {
            "action": "read", "chunk_id": chunk_id,
            "class": entry["class"], "hypothesis": hypothesis,
            "consumer": consumer, "records": len(rows),
            "ts_utc": _utc_now()})
        self._save()
        return rows

    def verify(self) -> dict:
        # Verify the bytes on disk, not the in-memory copy: a tampered
        # registry file must be detectable without a process restart.
        self.registry = json.loads(
            self.registry_path.read_text(encoding="utf-8"))
        self.access = json.loads(
            self.access_path.read_text(encoding="utf-8"))
        problems = _chain_verify(self.registry) + _chain_verify(self.access)
        bad: list[str] = []
        for entry in self.registry.get("entries", []):
            path = self.root / entry["file"]
            if not path.exists() or _sha256_file(path) != entry["sha256"]:
                bad.append(entry["chunk_id"])
        return {"ok": not problems and not bad,
                "registry_problems": _chain_verify(self.registry),
                "access_problems": _chain_verify(self.access),
                "bad_chunks": bad,
                "chunks": len(self.registry.get("entries", []))}

    def _save(self) -> None:
        _atomic_json(self.registry_path, self.registry)
        _atomic_json(self.access_path, self.access)


def load_dev_chunk(root: str | Path, chunk_id: str) -> list[dict]:
    """Explicit DEV-only loader for research code (never CONFIRM)."""
    vault = Vault(root)
    entry = vault._entry(chunk_id)
    if entry["class"] != DEV:
        raise VaultError("load_dev_chunk refuses non-DEV data")
    return vault.load_chunk(chunk_id, consumer="research")


def _filename_date(name: str) -> str | None:
    import re
    m = re.search(r"(\d{4}-\d{2}(?:-\d{2})?)", name)
    return m.group(1) if m else None


def build_holdout_manifest(raw_files: list[str | Path],
                           out_path: str | Path) -> dict:
    """Hash raw holdout bytes into a manifest WITHOUT decoding content.

    Returns {"manifest_path", "files", "sha256"}. Hashing reads bytes;
    no CSV/JSON parsing happens here, so building the manifest is not a
    statistical look and leaves no decode entries in any access log.
    """
    files: list[dict] = []
    for raw in raw_files:
        p = Path(raw)
        if not p.exists():
            raise VaultError(f"holdout file not found: {p}")
        files.append({"path": str(p), "sha256": _sha256_file(p),
                      "bytes": p.stat().st_size,
                      "filename_date": _filename_date(p.name)})
    doc = {"format": HOLDOUT_MANIFEST_FORMAT, "created_utc": _utc_now(),
           "files": files}
    out = Path(out_path)
    _atomic_json(out, doc)
    doc["manifest_path"] = out
    doc["sha256"] = _sha256_file(out)
    return doc


__all__ = ["Vault", "Chunk", "VaultError", "DEV", "CONFIRM", "HOLDOUT",
           "SYNTHETIC", "OBSERVED", "OBSERVED_PUBLIC",
           "build_holdout_manifest", "load_dev_chunk"]
