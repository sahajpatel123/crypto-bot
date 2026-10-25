"""E2.2 vault HOLDOUT class: byte-hash sealing, verdict-only decode, access-log eligibility."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _raw(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _sealed_holdout(tmp_path, vault, n: int = 2):
    from cryptobot.data.vault import build_holdout_manifest

    raws = [_raw(tmp_path / f"raw-{i}.zip", b"PK\x03\x04 holdout-bytes-%d" % i)
            for i in range(n)]
    manifest = build_holdout_manifest(raws, tmp_path / "holdout.manifest.json")
    chunk = vault.seal_chunk(manifest["manifest_path"], class_="HOLDOUT",
                             input_class="OBSERVED_PUBLIC")
    return chunk, manifest, raws


def test_holdout_seal_hashes_bytes_without_decoding(tmp_path):
    from cryptobot.data.vault import Vault

    vault = Vault(tmp_path / "vault")
    # First bytes look like a different class; sealing must NOT sniff.
    raw = _raw(tmp_path / "r.zip", b'{"input_class": "SYNTHETIC"}\nmore-bytes')
    from cryptobot.data.vault import build_holdout_manifest
    manifest = build_holdout_manifest([raw], tmp_path / "m.json")
    chunk = vault.seal_chunk(manifest["manifest_path"], class_="HOLDOUT",
                             input_class="OBSERVED_PUBLIC")
    assert chunk.class_ == "HOLDOUT"
    assert chunk.input_class == "OBSERVED_PUBLIC"
    log = json.loads((tmp_path / "vault" / "access_log.json").read_text())
    actions = [e["action"] for e in log["entries"]]
    assert "seal" in actions
    assert "decode" not in actions and "read" not in actions
    # Manifest records raw-byte hashes (not content).
    entry = next(e for e in manifest["files"])
    assert entry["sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()


def test_holdout_seal_requires_explicit_input_class(tmp_path):
    from cryptobot.data.vault import Vault, VaultError, build_holdout_manifest

    vault = Vault(tmp_path / "vault")
    raw = _raw(tmp_path / "r.zip", b"bytes")
    manifest = build_holdout_manifest([raw], tmp_path / "m.json")
    with pytest.raises(VaultError, match="input_class"):
        vault.seal_chunk(manifest["manifest_path"], class_="HOLDOUT")


def test_holdout_decode_requires_verdict_token(tmp_path):
    from cryptobot.data.vault import Vault, VaultError

    vault = Vault(tmp_path / "vault")
    chunk, _, _ = _sealed_holdout(tmp_path, vault)
    vault.freeze_hypothesis("B1", config_sha256="abc", commit="c1",
                            prereg_path="research/prereg/B1.md")
    with pytest.raises(VaultError, match="token"):
        vault.authorize_holdout_decode(chunk.chunk_id, token="bogus",
                                       hypothesis="B1")
    token = vault.issue_token("B1")
    auth = vault.authorize_holdout_decode(chunk.chunk_id, token=token,
                                          hypothesis="B1")
    assert auth["chunk_id"] == chunk.chunk_id
    assert len(auth["files"]) == 2
    with pytest.raises(VaultError, match="already used"):
        vault.authorize_holdout_decode(chunk.chunk_id, token=token,
                                       hypothesis="B1")


def test_holdout_confirm_eligibility_gated_on_access_log(tmp_path):
    from cryptobot.data.vault import Vault

    vault = Vault(tmp_path / "vault")
    chunk, _, _ = _sealed_holdout(tmp_path, vault)
    # Not frozen -> not eligible.
    assert vault.holdout_confirm_eligible(
        chunk.chunk_id, "B1")["eligible"] is False
    vault.freeze_hypothesis("B1", config_sha256="abc", commit="c1",
                            prereg_path="research/prereg/B1.md")
    # Sealed pre-freeze, zero decodes -> eligible.
    ok = vault.holdout_confirm_eligible(chunk.chunk_id, "B1")
    assert ok == {"eligible": True, "reason": "zero pre-freeze decodes"}
    # Simulate a leaked pre-freeze decode (hand-dated entry, valid chain).
    from cryptobot.data.vault import _chain_append
    frozen_utc = vault.registry["frozen"]["B1"]["frozen_utc"]
    import datetime
    earlier = (datetime.datetime.fromisoformat(frozen_utc)
               - datetime.timedelta(days=1)).isoformat()
    _chain_append(vault.access, {"action": "decode", "chunk_id": chunk.chunk_id,
                                 "hypothesis": "B0", "ts_utc": earlier})
    vault._save()
    bad = vault.holdout_confirm_eligible(chunk.chunk_id, "B1")
    assert bad["eligible"] is False
    assert "pre-freeze decode" in bad["reason"]


def test_holdout_verify_detects_tampered_referenced_file(tmp_path):
    from cryptobot.data.vault import Vault

    vault = Vault(tmp_path / "vault")
    chunk, _, raws = _sealed_holdout(tmp_path, vault)
    assert vault.verify_holdout(chunk.chunk_id)["ok"] is True
    with open(raws[0], "ab") as fh:
        fh.write(b"tamper")
    rep = vault.verify_holdout(chunk.chunk_id)
    assert rep["ok"] is False
    assert len(rep["bad_files"]) == 1


def test_load_chunk_refuses_holdout(tmp_path):
    from cryptobot.data.vault import Vault, VaultError

    vault = Vault(tmp_path / "vault")
    chunk, _, _ = _sealed_holdout(tmp_path, vault)
    vault.freeze_hypothesis("B1", config_sha256="abc", commit="c1",
                            prereg_path="research/prereg/B1.md")
    token = vault.issue_token("B1")
    with pytest.raises(VaultError, match="verdict holdout"):
        vault.load_chunk(chunk.chunk_id, token=token, hypothesis="B1",
                         consumer="verdict")


def test_holdout_import_lint_verdict_only():
    """Only cli/verdict/vault may reference HOLDOUT decode entry points."""
    from pathlib import Path as P

    root = P(__file__).resolve().parents[2] / "src" / "cryptobot"
    allowed = {"cli.py", "research/verdict.py", "data/vault.py"}
    offenders = []
    for path in root.rglob("*.py"):
        rel = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8")
        if "authorize_holdout_decode" in text or "decode_holdout" in text \
                or "holdout_frames" in text:
            if rel not in allowed:
                offenders.append(rel)
    assert not offenders, f"HOLDOUT decode refs outside verdict path: {offenders}"


def test_vault_cli_holdout_roundtrip(tmp_path, capsys):
    import argparse

    from cryptobot import cli
    from cryptobot.data.vault import build_holdout_manifest

    raw = tmp_path / "r.zip"
    raw.write_bytes(b"PK holdout")
    manifest = build_holdout_manifest([raw], tmp_path / "m.json")
    root = str(tmp_path / "vault")
    rc = cli.cmd_vault(argparse.Namespace(
        vault_cmd="seal", root=root, source=str(manifest["manifest_path"]),
        hypothesis=None, config=None, config_sha256=None, commit=None,
        prereg=None, data_class="HOLDOUT", input_class="OBSERVED_PUBLIC",
        first_ms=None, last_ms=None))
    assert rc == 0
    out = capsys.readouterr().out
    chunk_id = json.loads(out)["chunk_id"]
    rc = cli.cmd_vault(argparse.Namespace(
        vault_cmd="verify-holdout", root=root, source=chunk_id,
        hypothesis="B1", config=None, config_sha256=None, commit=None,
        prereg=None, data_class="HOLDOUT", input_class=None,
        first_ms=None, last_ms=None))
    assert rc == 0
    # Not frozen -> ineligible (rc 2), machine-readable reason.
    rc = cli.cmd_vault(argparse.Namespace(
        vault_cmd="holdout-eligible", root=root, source=chunk_id,
        hypothesis="B1", config=None, config_sha256=None, commit=None,
        prereg=None, data_class="HOLDOUT", input_class=None,
        first_ms=None, last_ms=None))
    assert rc == 2
    assert "not frozen" in capsys.readouterr().out
