"""F2.5: credential handling without ever exposing secrets.

Keys may come from the environment (preferred) or a 0600 file. This
module returns only presence/permission facts; it never logs, prints or
returns key material. Withdrawal permission cannot be checked without a
signed endpoint, so readiness emits an explicit manual checklist item.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

MANUAL_CHECKLIST = (
    "API key is trade-only: withdrawals disabled",
    "API key is IP-allowlisted to the bot host",
    "API key has no universal-transfer permission",
    "Demo/testnet keys are separate from production keys",
)


class CredentialError(RuntimeError):
    pass


def load_credentials(*, key_env: str, secret_env: str,
                     key_file: str | None = None,
                     secret_file: str | None = None) -> tuple[str, str]:
    """Load keys from env or 0600 files. Never print or persist them."""
    key = os.environ.get(key_env, "")
    secret = os.environ.get(secret_env, "")
    if key_file:
        key = _read_secret_file(key_file)
    if secret_file:
        secret = _read_secret_file(secret_file)
    if not key or not secret:
        raise CredentialError(
            f"missing credentials: set {key_env}/{secret_env} or 0600 files")
    return key, secret


def _read_secret_file(path: str) -> str:
    p = Path(path)
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
    except OSError as exc:
        raise CredentialError(f"credential file unreadable: {p}") from exc
    if mode & 0o077:
        raise CredentialError(
            f"credential file {p} has mode {mode:04o}; require 0600")
    return p.read_text(encoding="utf-8").strip()


def credential_readiness(*, key_env: str = "BINANCE_API_KEY",
                         secret_env: str = "BINANCE_API_SECRET",
                         key_file: str | None = None,
                         secret_file: str | None = None) -> dict:
    """Report presence/permissions only; values are never included."""
    rows: list[dict] = []
    key_present = bool(os.environ.get(key_env)) or bool(key_file)
    secret_present = bool(os.environ.get(secret_env)) or bool(secret_file)
    rows.append({"check": "api-key-present",
                 "status": "PASS" if key_present else "FAIL",
                 "detail": f"env {key_env} or 0600 file"})
    rows.append({"check": "api-secret-present",
                 "status": "PASS" if secret_present else "FAIL",
                 "detail": f"env {secret_env} or 0600 file"})
    for name, path in (("key-file-mode", key_file),
                       ("secret-file-mode", secret_file)):
        if not path:
            rows.append({"check": name, "status": "N/A",
                         "detail": "env-based credential"})
            continue
        try:
            mode = stat.S_IMODE(Path(path).stat().st_mode)
            ok = not (mode & 0o077)
        except OSError:
            mode, ok = 0, False
        rows.append({"check": name, "status": "PASS" if ok else "FAIL",
                     "detail": f"mode={mode:04o} require 0600"})
    rows.append({"check": "manual-key-permissions", "status": "MANUAL",
                 "detail": list(MANUAL_CHECKLIST)})
    return {"check": "credential-readiness",
            "verdict": "PASS" if all(
                r["status"] in ("PASS", "N/A", "MANUAL") for r in rows)
            else "FAIL", "rows": rows}


__all__ = ["CredentialError", "load_credentials", "credential_readiness",
           "MANUAL_CHECKLIST"]
