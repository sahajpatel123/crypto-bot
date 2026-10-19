"""F3 recorder + vault tests (no network)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from cryptobot.recorder import (
    BybitPlugin,
    OKXPlugin,
    Recorder,
    check_disk_budget,
    create_plugin,
    daily_integrity_report,
    verify_manifest,
)
from cryptobot.vault import Vault, assert_no_confirm_readers

BASE = 1704067200000  # 2024-01-01T00:00:00Z


def _agg(i: int, aid: int, ts: int | None = None):
    return {
        "stream": "aggTrade",
        "symbol": "BTCUSDT",
        "ts": ts if ts is not None else BASE + i * 1000,
        "data": {"a": aid, "p": "100.0", "q": "0.1"},
    }


# --- recorder: overflow -------------------------------------------------


def test_overflow_counts_and_gapped_no_silent_drop(tmp_path):
    rec = Recorder(tmp_path / "rec", queue_maxsize=2)
    results = [rec.offer(_agg(i, i + 1)) for i in range(5)]
    assert results.count(False) == 3
    assert rec.dropped == 3
    rec.flush()
    entries = rec.manifest
    assert entries, "expected a chunk after flush"
    assert sum(e["dropped"] for e in entries) == 3
    assert any(e["gapped"] for e in entries)


def test_recorder_run_chunks_and_manifest_fields(tmp_path):
    src = [_agg(i, i + 1) for i in range(3)] + [
        {
            "stream": "openInterest",
            "symbol": "ETHUSDT",
            "ts": BASE,
            "data": {"openInterest": "12.3"},
        }
    ]
    rec = Recorder(tmp_path / "rec", source=src)
    entries = rec.run()
    assert entries
    for e in entries:
        for k in (
            "file",
            "sha256",
            "prev_sha256",
            "stream",
            "t_start",
            "t_end",
            "rows",
            "dropped",
            "gapped",
        ):
            assert k in e
        assert (tmp_path / "rec" / e["file"]).exists()
        assert e["file"].endswith(".jsonl.gz")
    assert verify_manifest(tmp_path / "rec")


def test_writer_thread_start_stop(tmp_path):
    rec = Recorder(tmp_path / "rec", source=[_agg(i, i + 1) for i in range(4)])
    rec.start()
    rec.stop()
    assert rec.manifest
    assert verify_manifest(tmp_path / "rec")


# --- hash chain / tamper -------------------------------------------------


def test_hash_chain_verification_and_tamper(tmp_path):
    rec = Recorder(tmp_path / "rec", source=[_agg(i, i + 1) for i in range(3)])
    rec.run()
    assert verify_manifest(tmp_path / "rec")
    assert rec.verify_chain()
    chunk = tmp_path / "rec" / rec.manifest[0]["file"]
    # tamper: rewrite gz content
    with gzip.open(chunk, "wt", encoding="utf-8") as fh:
        fh.write('{"tampered":true}\n')
    assert not verify_manifest(tmp_path / "rec")


# --- continuity ----------------------------------------------------------


def test_continuity_checks(tmp_path):
    recs = [
        _agg(0, 1, ts=BASE),
        _agg(1, 2, ts=BASE + 1000),
        _agg(2, 4, ts=BASE + 2000),  # id break (missing 3)
        _agg(3, 5, ts=BASE + 1500),  # ts violation (goes back)
        {"stream": "depth", "symbol": "BTCUSDT", "ts": BASE, "data": {"U": 100, "u": 110}},
        {"stream": "depth", "symbol": "BTCUSDT", "ts": BASE + 1000, "data": {"U": 111, "u": 120}},
        {
            "stream": "depth",
            "symbol": "BTCUSDT",
            "ts": BASE + 2000,
            "data": {"U": 999, "u": 1000},
        },  # depth break
    ]
    rec = Recorder(tmp_path / "rec", source=recs)
    rec.run()
    rep = rec.integrity_report()
    assert rep["id_breaks"] >= 1
    assert rep["ts_violations"] >= 1
    assert rep["depth_breaks"] >= 1
    # module-level report reads sidecar/manifest
    rep2 = daily_integrity_report(tmp_path / "rec")
    assert rep2["id_breaks"] >= 1
    assert "gap_rate" in rep2


def test_clean_stream_no_breaks(tmp_path):
    rec = Recorder(tmp_path / "rec", source=[_agg(i, i + 1) for i in range(3)])
    rec.run()
    rep = rec.integrity_report()
    assert rep["id_breaks"] == 0
    assert rep["ts_violations"] == 0
    assert rep["gap_rate"] == 0.0


def test_disk_budget(tmp_path):
    assert check_disk_budget(tmp_path, 0)["alert"] is False
    assert check_disk_budget(tmp_path, 10**18)["alert"] is True
    rec = Recorder(tmp_path / "rec")
    assert rec.check_disk_budget(0)["ok"] is True


# --- venue plugins --------------------------------------------------------


def test_bybit_plugin_normalization():
    p = BybitPlugin()
    t = p.normalize_trade(
        {"symbol": "BTCUSDT", "price": "42000.5", "size": "0.2", "time": BASE, "id": "t1"}
    )
    assert t["stream"] == "aggTrade" and t["symbol"] == "BTCUSDT" and t["ts"] == BASE
    assert t["data"]["price"] == 42000.5 and t["data"]["qty"] == 0.2
    b = p.normalize_book_ticker(
        {
            "symbol": "BTCUSDT",
            "bid1Price": "41999",
            "bid1Size": "1",
            "ask1Price": "42001",
            "ask1Size": "2",
            "ts": BASE,
        }
    )
    assert (
        b["stream"] == "bookTicker"
        and b["data"]["bid_price"] == 41999.0
        and b["data"]["ask_price"] == 42001.0
    )
    assert set(t) == {"stream", "symbol", "ts", "local_ts", "data"}


def test_okx_plugin_normalization():
    p = OKXPlugin()
    t = p.normalize_trade(
        {"instId": "BTC-USDT-SWAP", "px": "42000.5", "sz": "3", "ts": str(BASE), "tradeId": "9"}
    )
    assert t["stream"] == "aggTrade" and t["symbol"] == "BTCUSDT" and t["ts"] == BASE
    assert t["data"]["price"] == 42000.5
    b = p.normalize_book_ticker(
        {
            "instId": "ETH-USDT-SWAP",
            "bidPx": "2000",
            "bidSz": "5",
            "askPx": "2001",
            "askSz": "6",
            "ts": str(BASE),
        }
    )
    assert (
        b["stream"] == "bookTicker"
        and b["symbol"] == "ETHUSDT"
        and b["data"]["bid_price"] == 2000.0
    )
    # injectable transport, no network
    plugin = OKXPlugin(
        transport=lambda ep, symbol=None: [
            {"instId": "BTC-USDT-SWAP", "px": "1", "sz": "1", "ts": str(BASE), "tradeId": "1"}
        ]
    )
    assert plugin.fetch_trades()[0]["data"]["price"] == 1.0


def test_plugin_config_flag_disabled():
    assert create_plugin("bybit", {"bybit_enabled": False}) is None
    assert create_plugin("okx", {"okx_enabled": True}) is not None
    with pytest.raises(RuntimeError):
        BybitPlugin(enabled=False).normalize_trade(
            {"symbol": "BTCUSDT", "price": "1", "size": "1", "time": BASE}
        )


# --- vault ---------------------------------------------------------------


def _chunk(tmp_path: Path, name: str = "chunk.jsonl.gz", content: bytes = b"hello\n") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_seal_confirm_before_freeze_refused(tmp_path):
    vault_dir = tmp_path / "vault"
    v = Vault(vault_dir, frozen_registry={"H1": "2024-06-01T00:00:00+00:00"})
    c = _chunk(tmp_path)
    with pytest.raises(VaultError):
        v.seal_chunk(
            c, "CONFIRM", "OBSERVED", hypothesis="H1", sealed_at="2024-01-01T00:00:00+00:00"
        )
    # after freeze succeeds
    e = v.seal_chunk(
        c, "CONFIRM", "OBSERVED", hypothesis="H1", sealed_at="2024-07-01T00:00:00+00:00"
    )
    assert e["cls"] == "CONFIRM"
    assert v.verify_registry()


def test_synthetic_confirm_refused(tmp_path):
    v = Vault(tmp_path / "vault", frozen_registry={"H1": "2024-01-01T00:00:00+00:00"})
    c = _chunk(tmp_path)
    with pytest.raises(VaultError):
        v.seal_chunk(
            c, "CONFIRM", "SYNTHETIC", hypothesis="H1", sealed_at="2024-07-01T00:00:00+00:00"
        )
    # synthetic DEV is fine
    assert v.seal_chunk(c, "DEV", "SYNTHETIC")["cls"] == "DEV"


def test_token_one_shot_and_access_log_chain(tmp_path):
    v = Vault(tmp_path / "vault", frozen_registry={"H1": "2024-01-01T00:00:00+00:00"})
    c = _chunk(tmp_path)
    v.seal_chunk(c, "CONFIRM", "OBSERVED", hypothesis="H1", sealed_at="2024-07-01T00:00:00+00:00")
    with pytest.raises(PermissionError):
        v.load_confirm("H1")  # no token
    token = v.issue_token("H1")
    assert token.exists()
    got = v.load_confirm("H1", token)
    assert got and got[0]["cls"] == "CONFIRM"
    assert not token.exists(), "token must be consumed on use"
    with pytest.raises(PermissionError):
        v.load_confirm("H1", token)  # second use refused
    assert v.verify_access_log()
    log = json.loads((tmp_path / "vault" / "access-log.json").read_text())
    assert len(log) >= 3
    assert log[0]["prev_entry_sha256"] == ""
    for prev, cur in zip(log, log[1:], strict=False):
        assert cur["prev_entry_sha256"] == prev["entry_sha256"]


def test_load_dev_free_and_registry_chain_tamper(tmp_path):
    v = Vault(tmp_path / "vault")
    c = _chunk(tmp_path)
    v.seal_chunk(c, "DEV", "OBSERVED")
    assert v.load_dev()
    assert v.verify_registry()
    # tamper chunk -> registry verification fails
    c.write_bytes(b"tampered")
    assert not v.verify_registry()


def test_assert_no_confirm_readers(tmp_path):
    (tmp_path / "src" / "cryptobot" / "vault").mkdir(parents=True)
    (tmp_path / "src" / "cryptobot" / "research").mkdir(parents=True)
    (tmp_path / "src" / "cryptobot" / "vault" / "ok.py").write_text("x = load_confirm\n")
    (tmp_path / "src" / "cryptobot" / "research" / "bad.py").write_text(
        "from cryptobot.vault import Vault\nv.load_confirm('H1', t)\n"
    )
    (tmp_path / "src" / "cryptobot" / "research" / "clean.py").write_text("x = 1\n")
    offenders = assert_no_confirm_readers(tmp_path)
    assert any("bad.py" in o for o in offenders)
    assert not any("ok.py" in o for o in offenders)
    assert not any("clean.py" in o for o in offenders)
