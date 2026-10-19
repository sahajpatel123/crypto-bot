"""Vault registry: sealing, hash chain, tamper evidence, DEV/CONFIRM classify."""

import json
from pathlib import Path

import pytest

from cryptobot.vault._common import VaultUnknownChunk
from cryptobot.vault.registry import Registry


class Clock:
    """Deterministic now_utc: returns stamps from a script in order."""

    def __init__(self, stamps: list[str]):
        self._stamps = list(stamps)
        self._idx = 0

    def __call__(self) -> str:
        stamp = self._stamps[min(self._idx, len(self._stamps) - 1)]
        self._idx += 1
        return stamp


def _make_source(tmp_path: Path, name: str, content: bytes) -> Path:
    src = tmp_path / "sources" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(content)
    return src


def _seal_three(tmp_path: Path, clock: Clock) -> tuple[Registry, list[dict]]:
    reg = Registry(root=tmp_path / "vault", now_utc=clock)
    records = []
    for i, stamp_date in enumerate(["01", "02", "03"]):
        _ = stamp_date
        src = _make_source(tmp_path, f"chunk{i}.bin", f"payload-{i}".encode())
        records.append(
            reg.seal_chunk(
                src,
                time_start_utc=f"2026-01-0{i + 1}T00:00:00+00:00",
                time_end_utc=f"2026-01-0{i + 1}T01:00:00+00:00",
                provenance="OBSERVED",
            )
        )
    return reg, records


def test_seal_three_chunks_chain_verifies(tmp_path: Path) -> None:
    clock = Clock(
        [
            "2026-02-01T00:00:00+00:00",
            "2026-02-02T00:00:00+00:00",
            "2026-02-03T00:00:00+00:00",
        ]
    )
    reg, records = _seal_three(tmp_path, clock)
    assert [r["chunk_id"] for r in records] == ["chunk0.bin", "chunk1.bin", "chunk2.bin"]
    for record in records:
        for key in (
            "chunk_id", "sha256", "bytes", "time_range", "provenance",
            "sealed_utc", "prev_hash", "entry_hash",
        ):
            assert key in record
    assert records[0]["prev_hash"] == "0" * 64
    assert records[1]["prev_hash"] == records[0]["entry_hash"]
    assert records[2]["prev_hash"] == records[1]["entry_hash"]
    # Fresh instance re-reads from disk.
    assert Registry(root=tmp_path / "vault").verify_chain() is True
    assert reg.get("chunk1.bin")["sha256"] == records[1]["sha256"]


def test_tamper_registry_entry_breaks_chain(tmp_path: Path) -> None:
    clock = Clock(["2026-02-01T00:00:00+00:00"] * 3)
    _seal_three(tmp_path, clock)
    reg_path = tmp_path / "vault" / "registry.json"
    data = json.loads(reg_path.read_text(encoding="utf-8"))
    data["entries"][1]["sealed_utc"] = "2025-01-01T00:00:00+00:00"
    reg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    assert Registry(root=tmp_path / "vault").verify_chain() is False


def test_tamper_prev_hash_breaks_chain(tmp_path: Path) -> None:
    clock = Clock(["2026-02-01T00:00:00+00:00"] * 3)
    _seal_three(tmp_path, clock)
    reg_path = tmp_path / "vault" / "registry.json"
    data = json.loads(reg_path.read_text(encoding="utf-8"))
    data["entries"][2]["prev_hash"] = "0" * 64
    reg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    assert Registry(root=tmp_path / "vault").verify_chain() is False


def test_classify_dev_before_freeze_confirm_after(tmp_path: Path) -> None:
    clock = Clock(
        [
            "2026-02-01T00:00:00+00:00",
            "2026-02-02T00:00:00+00:00",
            "2026-02-03T00:00:00+00:00",
        ]
    )
    reg, _ = _seal_three(tmp_path, clock)
    freeze = {
        "hypothesis": "H1",
        "config_hash": "abc123",
        "frozen_commit": "deadbeef",
        "frozen_utc": "2026-02-01T12:00:00+00:00",
    }
    assert reg.classify("chunk0.bin", "H1", freeze) == "DEV"
    assert reg.classify("chunk1.bin", "H1", freeze) == "CONFIRM"
    assert reg.classify("chunk2.bin", "H1", freeze) == "CONFIRM"


def test_classify_equal_timestamp_is_dev(tmp_path: Path) -> None:
    clock = Clock(["2026-02-01T12:00:00+00:00"])
    reg = Registry(root=tmp_path / "vault", now_utc=clock)
    src = _make_source(tmp_path, "edge.bin", b"edge")
    reg.seal_chunk(
        src,
        time_start_utc="2026-01-01T00:00:00+00:00",
        time_end_utc="2026-01-01T01:00:00+00:00",
        provenance="OBSERVED",
    )
    freeze = {"config_hash": "c", "frozen_commit": "f", "frozen_utc": clock._stamps[0]}
    assert reg.classify("edge.bin", "H1", freeze) == "DEV"


def test_synthetic_never_confirm(tmp_path: Path) -> None:
    clock = Clock(["2026-03-01T00:00:00+00:00"])
    reg = Registry(root=tmp_path / "vault", now_utc=clock)
    src = _make_source(tmp_path, "synth.bin", b"fake")
    reg.seal_chunk(
        src,
        time_start_utc="2026-01-01T00:00:00+00:00",
        time_end_utc="2026-01-01T01:00:00+00:00",
        provenance="SYNTHETIC",
    )
    freeze = {
        "config_hash": "c",
        "frozen_commit": "f",
        "frozen_utc": "2026-01-15T00:00:00+00:00",
    }
    assert reg.classify("synth.bin", "H1", freeze) == "DEV"


def test_classify_unknown_chunk_raises(tmp_path: Path) -> None:
    reg = Registry(root=tmp_path / "vault")
    with pytest.raises(VaultUnknownChunk):
        reg.classify("nope.bin", "H1", {"frozen_utc": "2026-01-01T00:00:00+00:00"})


def test_classify_rejects_wrong_owner_freeze(tmp_path: Path) -> None:
    clock = Clock(["2026-02-01T00:00:00+00:00"])
    reg = Registry(root=tmp_path / "vault", now_utc=clock)
    src = _make_source(tmp_path, "c.bin", b"x")
    reg.seal_chunk(
        src,
        time_start_utc="2026-01-01T00:00:00+00:00",
        time_end_utc="2026-01-01T01:00:00+00:00",
        provenance="OBSERVED",
    )
    with pytest.raises(ValueError, match="not hypothesis"):
        reg.classify(
            "c.bin", "H1",
            {"hypothesis": "H2", "frozen_utc": "2026-01-01T00:00:00+00:00"},
        )


def test_reseal_rejected_and_bad_range_rejected(tmp_path: Path) -> None:
    reg = Registry(root=tmp_path / "vault", now_utc=Clock(["2026-02-01T00:00:00+00:00"]))
    src = _make_source(tmp_path, "dup.bin", b"data")
    reg.seal_chunk(
        src,
        time_start_utc="2026-01-01T00:00:00+00:00",
        time_end_utc="2026-01-01T01:00:00+00:00",
        provenance="OBSERVED",
    )
    with pytest.raises(ValueError, match="already sealed"):
        reg.seal_chunk(
            src,
            time_start_utc="2026-01-01T00:00:00+00:00",
            time_end_utc="2026-01-01T01:00:00+00:00",
            provenance="OBSERVED",
        )
    bad = _make_source(tmp_path, "bad.bin", b"data")
    with pytest.raises(ValueError, match="time_start_utc"):
        reg.seal_chunk(
            bad,
            time_start_utc="2026-01-02T00:00:00+00:00",
            time_end_utc="2026-01-01T00:00:00+00:00",
            provenance="OBSERVED",
        )


def test_default_root_is_data_vault_without_io() -> None:
    assert Registry().root == Path("data/vault")
