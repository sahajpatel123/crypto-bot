"""Gated loader: DEV free, CONFIRM token-only, chained access log, provenance gate."""

import json
from pathlib import Path

import pytest

from cryptobot.vault._common import VaultRefused, VaultSynthetic, VaultUnknownChunk
from cryptobot.vault.loader import (
    check_provenance,
    get_record,
    load_chunk,
    verify_access_log,
)
from cryptobot.vault.registry import Registry
from cryptobot.vault.tokens import mint_verdict_token

FREEZE_UTC = "2026-02-01T12:00:00+00:00"


@pytest.fixture()
def vault(tmp_path: Path) -> dict:
    root = tmp_path / "vault"
    freeze_dir = tmp_path / "freeze"
    freeze_dir.mkdir()
    (freeze_dir / "H1.json").write_text(
        json.dumps(
            {
                "hypothesis": "H1",
                "config_hash": "cfg",
                "frozen_commit": "c0ffee",
                "frozen_utc": FREEZE_UTC,
            }
        ),
        encoding="utf-8",
    )
    (freeze_dir / "H2.json").write_text(
        json.dumps({"hypothesis": "H2", "frozen_utc": "2026-01-15T00:00:00+00:00"}),
        encoding="utf-8",
    )
    stamps = iter(
        [
            "2026-01-10T00:00:00+00:00",  # dev.bin: before H1 freeze
            "2026-02-10T00:00:00+00:00",  # confirm.bin: after H1 freeze
            "2026-02-11T00:00:00+00:00",  # synth.bin: after freeze, synthetic
        ]
    )
    reg = Registry(root=root, now_utc=lambda: next(stamps))
    srcs = {}
    for name, payload in [
        ("dev.bin", b"dev-bytes"),
        ("confirm.bin", b"confirm-bytes"),
        ("synth.bin", b"synth-bytes"),
    ]:
        src = tmp_path / "src" / name
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(payload)
        srcs[name] = src
    reg.seal_chunk(
        srcs["dev.bin"],
        time_start_utc="2026-01-01T00:00:00+00:00",
        time_end_utc="2026-01-02T00:00:00+00:00",
        provenance="OBSERVED",
    )
    reg.seal_chunk(
        srcs["confirm.bin"],
        time_start_utc="2026-02-01T00:00:00+00:00",
        time_end_utc="2026-02-02T00:00:00+00:00",
        provenance="OBSERVED",
    )
    reg.seal_chunk(
        srcs["synth.bin"],
        time_start_utc="2026-02-01T00:00:00+00:00",
        time_end_utc="2026-02-02T00:00:00+00:00",
        provenance="SYNTHETIC",
    )
    assert reg.classify("dev.bin", "H1", json.loads((freeze_dir / "H1.json").read_text())) == "DEV"
    assert reg.classify("confirm.bin", "H1", json.loads((freeze_dir / "H1.json").read_text())) == "CONFIRM"
    return {"root": root, "freeze_dir": freeze_dir}


def test_dev_loads_free(vault: dict) -> None:
    assert load_chunk(vault["root"], "dev.bin", freeze_dir=vault["freeze_dir"]) == b"dev-bytes"
    assert (
        load_chunk(vault["root"], "dev.bin", hypothesis="H1", freeze_dir=vault["freeze_dir"])
        == b"dev-bytes"
    )


def test_confirm_without_token_raises(vault: dict) -> None:
    with pytest.raises(VaultRefused):
        load_chunk(vault["root"], "confirm.bin", freeze_dir=vault["freeze_dir"])
    with pytest.raises(VaultRefused):
        load_chunk(
            vault["root"], "confirm.bin", hypothesis="H1", freeze_dir=vault["freeze_dir"]
        )


def test_confirm_with_token_loads_once_then_exhausted(vault: dict) -> None:
    token = mint_verdict_token("H1", ["confirm.bin"], root=vault["root"])
    assert (
        load_chunk(
            vault["root"], "confirm.bin", hypothesis="H1", token=token,
            freeze_dir=vault["freeze_dir"],
        )
        == b"confirm-bytes"
    )
    with pytest.raises(VaultRefused):
        load_chunk(
            vault["root"], "confirm.bin", hypothesis="H1", token=token,
            freeze_dir=vault["freeze_dir"],
        )


def test_confirm_token_wrong_hypothesis_refused(vault: dict) -> None:
    token = mint_verdict_token("H1", ["confirm.bin"], root=vault["root"])
    with pytest.raises(VaultRefused):
        load_chunk(
            vault["root"], "confirm.bin", hypothesis="H2", token=token,
            freeze_dir=vault["freeze_dir"],
        )


def test_bogus_hypothesis_cannot_downgrade(vault: dict) -> None:
    with pytest.raises(VaultRefused):
        load_chunk(
            vault["root"], "confirm.bin", hypothesis="NOFREEZE",
            freeze_dir=vault["freeze_dir"],
        )


def test_unknown_chunk_refused(vault: dict) -> None:
    with pytest.raises(VaultUnknownChunk):
        load_chunk(vault["root"], "missing.bin", freeze_dir=vault["freeze_dir"])


def test_tampered_chunk_bytes_refused(vault: dict) -> None:
    (vault["root"] / "chunks" / "dev.bin").write_bytes(b"tampered!")
    with pytest.raises(VaultRefused, match="tamper"):
        load_chunk(vault["root"], "dev.bin", freeze_dir=vault["freeze_dir"])


def test_access_log_chained_and_covers_refusals(vault: dict) -> None:
    load_chunk(vault["root"], "dev.bin", freeze_dir=vault["freeze_dir"])
    with pytest.raises(VaultRefused):
        load_chunk(vault["root"], "confirm.bin", freeze_dir=vault["freeze_dir"])
    token = mint_verdict_token("H1", ["confirm.bin"], root=vault["root"])
    load_chunk(
        vault["root"], "confirm.bin", hypothesis="H1", token=token,
        freeze_dir=vault["freeze_dir"],
    )
    assert verify_access_log(vault["root"]) is True
    lines = (vault["root"] / "access.log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    decisions = [json.loads(line)["decision"] for line in lines]
    assert decisions == ["granted", "refused", "granted"]
    # Raw token must never appear in the log.
    assert token not in (vault["root"] / "access.log.jsonl").read_text(encoding="utf-8")


def test_access_log_tamper_detected(vault: dict) -> None:
    load_chunk(vault["root"], "dev.bin", freeze_dir=vault["freeze_dir"])
    log_path = vault["root"] / "access.log.jsonl"
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    entry["decision"] = "refused"
    log_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    assert verify_access_log(vault["root"]) is False


def test_check_provenance_rejects_synthetic(vault: dict) -> None:
    with pytest.raises(VaultSynthetic):
        check_provenance(get_record(vault["root"], "synth.bin"))
    with pytest.raises(VaultSynthetic):
        check_provenance({"chunk_id": "x"})  # unstamped: fail closed
    check_provenance(get_record(vault["root"], "dev.bin"))  # no raise
    check_provenance(get_record(vault["root"], "confirm.bin"))  # no raise
