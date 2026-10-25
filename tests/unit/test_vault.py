"""F3.5 vault: hash chains, CONFIRM gating, one-shot tokens, access log."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest


def _chunk(path: Path, rows: list[dict], *,
           input_class: str = "observed-public") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "header", "input_class": input_class}) + "\n")
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def test_dev_seal_verify_and_load(tmp_path):
    from cryptobot.data.vault import Vault

    vault = Vault(tmp_path / "vault")
    chunk = vault.seal_chunk(_chunk(tmp_path / "d.gz", [{"x": 1}]))
    assert chunk.class_ == "DEV"
    assert vault.verify()["ok"] is True
    rows = vault.load_chunk(chunk.chunk_id)
    assert rows[-1] == {"x": 1}
    report = vault.verify()
    assert report["chunks"] == 1
    assert json.loads((tmp_path / "vault" / "registry.json").read_text())[
        "entries"][0]["sha256"] == chunk.sha256


def test_synthetic_cannot_be_confirm(tmp_path):
    from cryptobot.data.vault import Vault, VaultError

    vault = Vault(tmp_path / "vault")
    vault.freeze_hypothesis("H1", config_sha256="abc", commit="c1",
                            prereg_path="research/prereg/H1.md")
    source = _chunk(tmp_path / "s.gz", [{"x": 1}],
                    input_class="SYNTHETIC")
    with pytest.raises(VaultError, match="SYNTHETIC"):
        vault.seal_chunk(source, class_="CONFIRM", hypothesis="H1")


def test_confirm_requires_freeze_then_one_shot_token(tmp_path):
    from cryptobot.data.vault import Vault, VaultError

    vault = Vault(tmp_path / "vault")
    source = _chunk(tmp_path / "c.gz", [{"x": 1}])
    with pytest.raises(VaultError, match="not frozen"):
        vault.seal_chunk(source, class_="CONFIRM", hypothesis="H1")
    vault.freeze_hypothesis("H1", config_sha256="abc", commit="c1",
                            prereg_path="research/prereg/H1.md")
    with pytest.raises(VaultError, match="config hash"):
        vault.seal_chunk(source, class_="CONFIRM", hypothesis="H1",
                         config_sha256="different")
    chunk = vault.seal_chunk(source, class_="CONFIRM", hypothesis="H1",
                             config_sha256="abc")
    with pytest.raises(VaultError, match="verdict-only"):
        vault.load_chunk(chunk.chunk_id)
    with pytest.raises(VaultError, match="one-shot token"):
        vault.load_chunk(chunk.chunk_id, consumer="verdict",
                         hypothesis="H1")
    token = vault.issue_token("H1")
    assert vault.load_chunk(chunk.chunk_id, token=token, hypothesis="H1",
                            consumer="verdict")[-1] == {"x": 1}
    with pytest.raises(VaultError, match="already used"):
        vault.load_chunk(chunk.chunk_id, token=token, hypothesis="H1",
                         consumer="verdict")
    log = json.loads((tmp_path / "vault" / "access_log.json").read_text())
    actions = [e["action"] for e in log["entries"]]
    assert "seal" in actions and "issue-token" in actions
    assert "deny" in actions


def test_refreeze_with_different_config_is_refused(tmp_path):
    from cryptobot.data.vault import Vault, VaultError

    vault = Vault(tmp_path / "vault")
    vault.freeze_hypothesis("H1", config_sha256="a", commit="c1",
                            prereg_path="p")
    with pytest.raises(VaultError, match="different config"):
        vault.freeze_hypothesis("H1", config_sha256="b", commit="c2",
                                prereg_path="p")
    assert vault.freeze_hypothesis("H2", config_sha256="b", commit="c2",
                                   prereg_path="p")["config_sha256"] == "b"


def test_tampered_registry_and_chunk_are_detected(tmp_path):
    from cryptobot.data.vault import Vault

    vault = Vault(tmp_path / "vault")
    vault.seal_chunk(_chunk(tmp_path / "d.gz", [{"x": 1}]))
    registry = json.loads((tmp_path / "vault" / "registry.json").read_text())
    registry["entries"][0]["records"] = 999
    (tmp_path / "vault" / "registry.json").write_text(
        json.dumps(registry))
    assert vault.verify()["ok"] is False
    # Fresh vault to prove chunk-byte tampering is caught independently.
    vault2 = Vault(tmp_path / "vault2")
    chunk2 = vault2.seal_chunk(_chunk(tmp_path / "e.gz", [{"y": 2}]))
    with open(chunk2.path, "ab") as fh:
        fh.write(b"x")
    assert vault2.verify()["bad_chunks"] == [chunk2.chunk_id]


def test_dev_loader_refuses_confirm(tmp_path):
    from cryptobot.data.vault import Vault, VaultError, load_dev_chunk

    vault = Vault(tmp_path / "vault")
    vault.freeze_hypothesis("H1", config_sha256="a", commit="c1",
                            prereg_path="p")
    chunk = vault.seal_chunk(_chunk(tmp_path / "c.gz", [{"x": 1}]),
                             class_="CONFIRM", hypothesis="H1")
    with pytest.raises(VaultError, match="non-DEV"):
        load_dev_chunk(tmp_path / "vault", chunk.chunk_id)


def test_import_lint_confirm_access_is_verdict_only():
    """No module other than verdict/CLI/vault may touch CONFIRM access."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "cryptobot"
    allowed = {"cli.py", "research/verdict.py", "data/vault.py"}
    offenders = []
    for path in root.rglob("*.py"):
        rel = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8")
        if "read_confirm" in text or "issue_token" in text:
            if rel not in allowed:
                offenders.append(rel)
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) \
                    and node.module == "cryptobot.data.vault" \
                    and rel not in allowed:
                offenders.append(f"{rel}:import")
    assert not offenders, f"CONFIRM vault imports outside verdict path: {offenders}"
