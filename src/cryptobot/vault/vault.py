"""F3 vault: hash-chained registry, CONFIRM gating, one-shot tokens, access log."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CLS_DEV = "DEV"
CLS_CONFIRM = "CONFIRM"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _entry_hash(prev: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256((prev + _canonical(payload)).encode()).hexdigest()


def _parse_time(v: Any) -> float:
    """Parse ISO string / datetime / epoch s or ms into epoch seconds."""
    if v is None:
        raise ValueError("missing timestamp")
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=UTC)
        return dt.timestamp()
    if isinstance(v, (int, float)):
        # ms if large
        return float(v) / 1000.0 if float(v) > 1e12 else float(v)
    s = str(v).strip()
    # numeric string
    try:
        f = float(s)
        return f / 1000.0 if f > 1e12 else f
    except ValueError:
        pass
    iso = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class VaultError(Exception):
    pass


class Vault:
    """Hash-chained vault over a directory (registry.json + access-log.json)."""

    def __init__(
        self,
        root_dir: str | Path,
        frozen_registry: Any = None,
        *,
        root: str | Path | None = None,
        frozen_at: dict[str, Any] | None = None,
        frozen: Any = None,
    ):
        base = root if root is not None else root_dir
        self.root = Path(base)  # type: ignore[arg-type]
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "registry.json"
        self.access_log_path = self.root / "access-log.json"
        self.tokens_dir = self.root / "tokens"
        # frozen registry: dict hypothesis->time, path, or {"frozen_at": {...}} / {"hypotheses": {...}}
        self.frozen: dict[str, Any] = {}
        src = (
            frozen_registry
            if frozen_registry is not None
            else (frozen if frozen is not None else frozen_at)
        )
        if src is not None:
            if isinstance(src, (str, Path)) and Path(src).exists():  # type: ignore[arg-type]
                obj = json.loads(Path(src).read_text(encoding="utf-8"))  # type: ignore[arg-type]
                self.frozen = self._extract_frozen(obj)
            elif isinstance(src, dict):
                self.frozen = self._extract_frozen(src)
        if frozen_at and isinstance(frozen_at, dict):
            # explicit kwarg overrides/merges
            self.frozen.update(self._extract_frozen(frozen_at))
        self._entries: list[dict[str, Any]] = self._load_entries(self.registry_path)
        self._access: list[dict[str, Any]] = self._load_entries(self.access_log_path)

    @staticmethod
    def _extract_frozen(obj: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(obj, dict):
            return {}
        for key in ("frozen_at", "frozen", "freezes", "hypotheses"):
            if key in obj and isinstance(obj[key], dict):
                inner = obj[key]
                # hypotheses may be {X: {"frozen_at": ...}}
                out: dict[str, Any] = {}
                for k, v in inner.items():
                    if isinstance(v, dict):
                        out[k] = v.get("frozen_at", v.get("frozen", v.get("at")))
                    else:
                        out[k] = v
                return out
        # direct mapping hypothesis->time, ignore non-time values heuristically
        return dict(obj)

    @staticmethod
    def _load_entries(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            return list(obj.get("entries") or obj.get("chunks") or obj.get("access") or [])
        return []

    def _write_entries(self, path: Path, entries: list[dict[str, Any]]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        tmp.replace(path)

    # -- seal ------------------------------------------------------------
    def seal_chunk(
        self,
        path: str | Path,
        cls: str = "DEV",
        provenance: str = "OBSERVED",
        *,
        classification: str | None = None,
        hypothesis: str | None = None,
        sealed_at: Any = None,
        chunk_path: str | Path | None = None,
    ) -> dict[str, Any]:
        p = Path(chunk_path) if chunk_path is not None else Path(path)
        if not p.exists():
            raise VaultError(f"chunk not found: {p}")
        cls_u = str(classification or cls).strip().upper()
        if cls_u not in ("DEV", "CONFIRM"):
            raise VaultError(f"invalid cls {cls!r}; want DEV or CONFIRM")
        prov = str(provenance or "").strip().upper()
        if prov == "SYNTHETIC" and cls_u == "CONFIRM":
            raise VaultError("SYNTHETIC provenance chunks can never be CONFIRM")
        sealed = sealed_at if sealed_at is not None else _now_iso()
        sealed_iso = sealed.isoformat() if isinstance(sealed, datetime) else str(sealed)
        if cls_u == "CONFIRM":
            if hypothesis is not None:
                if hypothesis not in self.frozen:
                    raise VaultError(f"CONFIRM refused: no frozen_at for hypothesis {hypothesis!r}")
                frozen_v = self.frozen[hypothesis]
                if _parse_time(sealed) <= _parse_time(frozen_v):
                    raise VaultError(
                        f"CONFIRM refused: sealed_at {sealed_iso} <= frozen_at[{hypothesis!r}]={frozen_v}"
                    )
            elif self.frozen:
                raise VaultError(
                    "CONFIRM refused: hypothesis required when frozen registry is present"
                )
        sha = _sha256_file(p)
        prev_entry = self._entries[-1].get("entry_sha256", "") if self._entries else ""
        prev_sha = self._entries[-1].get("sha256", "") if self._entries else ""
        payload: dict[str, Any] = {
            "file": str(p),
            "chunk": str(p.name),
            "sha256": sha,
            "cls": cls_u,
            "provenance": prov,
            "hypothesis": hypothesis,
            "sealed_at": sealed_iso,
        }
        entry_hash = _entry_hash(prev_entry, payload)
        entry = {
            **payload,
            "prev_sha256": prev_sha,
            "prev_entry_sha256": prev_entry,
            "entry_sha256": entry_hash,
        }
        self._entries.append(entry)
        self._write_entries(self.registry_path, self._entries)
        return entry

    # alias
    seal = seal_chunk

    # -- tokens ----------------------------------------------------------
    def issue_token(self, hypothesis: str, *, token: str | None = None) -> Path:
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        tok = token or secrets.token_urlsafe(24)
        tid = uuid.uuid4().hex[:12]
        path = self.tokens_dir / f"{hypothesis}_{tid}.token"
        payload = {"token": tok, "hypothesis": hypothesis, "issued_at": _now_iso()}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    create_token = issue_token

    def _validate_and_consume_token(self, hypothesis: str, token: Any) -> bool:
        if token is None:
            return False
        # token as Path / path string to existing file
        cand: Path | None = None
        if isinstance(token, Path):
            cand = token
        elif isinstance(token, str):
            pp = Path(token)
            if pp.exists():
                cand = pp
            elif (self.tokens_dir / token).exists():
                cand = self.tokens_dir / token
            else:
                # raw token string: search tokens dir
                if self.tokens_dir.exists():
                    for f in self.tokens_dir.iterdir():
                        try:
                            obj = json.loads(f.read_text(encoding="utf-8"))
                        except Exception:
                            continue
                        if obj.get("token") == token and obj.get("hypothesis") == hypothesis:
                            cand = f
                            break
                if cand is None:
                    return False
        if cand is None or not cand.exists():
            return False
        try:
            obj = json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            return False
        if obj.get("hypothesis") != hypothesis:
            return False
        if not obj.get("token"):
            return False
        # one-shot: consume
        try:
            cand.unlink()
        except FileNotFoundError:
            return False
        return True

    # -- access log ------------------------------------------------------
    def _log_access(
        self, hypothesis: str | None, action: str, granted: bool, detail: str = ""
    ) -> dict[str, Any]:
        prev = self._access[-1].get("entry_sha256", "") if self._access else ""
        payload = {
            "ts": _now_iso(),
            "hypothesis": hypothesis,
            "action": action,
            "granted": bool(granted),
            "detail": detail,
        }
        h = _entry_hash(prev, payload)
        entry = {
            **payload,
            "prev_entry_sha256": prev,
            "prev_sha256": prev,
            "entry_sha256": h,
            "sha256": h,
        }
        self._access.append(entry)
        self._write_entries(self.access_log_path, self._access)
        return entry

    def verify_access_log(self) -> bool:
        prev = ""
        for e in self._access:
            if e.get("prev_entry_sha256", e.get("prev_sha256", "")) != prev:
                return False
            payload = {
                "ts": e.get("ts"),
                "hypothesis": e.get("hypothesis"),
                "action": e.get("action"),
                "granted": e.get("granted"),
                "detail": e.get("detail", ""),
            }
            if _entry_hash(prev, payload) != e.get("entry_sha256"):
                return False
            prev = e.get("entry_sha256", "")
        return True

    def verify_registry(self) -> bool:
        prev_entry = ""
        prev_sha = ""
        for e in self._entries:
            if e.get("prev_entry_sha256", "") != prev_entry:
                return False
            if e.get("prev_sha256", "") != prev_sha:
                return False
            payload = {
                "file": e.get("file"),
                "chunk": e.get("chunk"),
                "sha256": e.get("sha256"),
                "cls": e.get("cls"),
                "provenance": e.get("provenance"),
                "hypothesis": e.get("hypothesis"),
                "sealed_at": e.get("sealed_at"),
            }
            if _entry_hash(prev_entry, payload) != e.get("entry_sha256"):
                return False
            # chunk hash check if file exists (skip if moved)
            f = Path(e["file"])
            if f.exists() and _sha256_file(f) != e.get("sha256"):
                return False
            prev_entry = e.get("entry_sha256", "")
            prev_sha = e.get("sha256", "")
        return True

    verify_chain = verify_registry

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    @property
    def access_log(self) -> list[dict[str, Any]]:
        return list(self._access)

    # -- loaders ---------------------------------------------------------
    def load_confirm(self, hypothesis: str, token: Any = None, **kw: Any) -> list[dict[str, Any]]:
        if token is None and "token_path" in kw:
            token = kw["token_path"]
        ok = self._validate_and_consume_token(hypothesis, token)
        if not ok:
            self._log_access(hypothesis, "load_confirm", False, "invalid or consumed token")
            raise PermissionError("load_confirm refused: valid one-shot token required")
        self._log_access(hypothesis, "load_confirm", True)
        return [
            dict(e)
            for e in self._entries
            if e.get("cls") == "CONFIRM" and e.get("hypothesis") == hypothesis
        ]

    def load_dev(self, hypothesis: str | None = None, **kw: Any) -> list[dict[str, Any]]:
        self._log_access(hypothesis, "load_dev", True)
        out = [dict(e) for e in self._entries if e.get("cls") == "DEV"]
        if hypothesis is not None:
            out = [e for e in out if e.get("hypothesis") in (hypothesis, None)]
        return out


def assert_no_confirm_readers(repo_root: str | Path) -> list[str]:
    """Scan src/ for CONFIRM vault access outside vault/verdict modules.

    Returns list of offender paths (relative to repo_root where possible).
    Allowed: any path containing 'vault' or 'verdict' segment.
    Flags: files calling load_confirm, or referencing CONFIRM together with vault.
    """
    root = Path(repo_root)
    src = root / "src" if (root / "src").exists() else root
    offenders: list[str] = []
    for p in sorted(src.rglob("*.py")):
        parts = {part.lower() for part in p.parts}
        rel_parts = (
            [x.lower() for x in p.relative_to(root).parts]
            if p.is_relative_to(root)
            else list(parts)
        )
        if "vault" in rel_parts or "verdict" in rel_parts:
            continue
        if any("verdict" in x for x in rel_parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        hit = False
        if "load_confirm" in text or "CONFIRM" in text and "vault" in text.lower():
            hit = True
        if hit:
            try:
                offenders.append(str(p.relative_to(root)))
            except Exception:
                offenders.append(str(p))
    return offenders


# alias names
scan_confirm_readers = assert_no_confirm_readers
