"""Multi-symbol + window bench_run tests (W4, DEEP authorized extension).

Tiny synthetic captured manifests only. Ingestion MECHANICS only
(merge order, cursors, windows, resume identity); no strategy
outcomes are asserted beyond booked-ledger equality across
mechanical run splits.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptobot.bench_run import main

SYM_A = "BTCUSDT"
SYM_B = "ETHUSDT"
DAY1 = "2026-10-11"
DAY2 = "2026-10-12"
T1 = int(datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp() * 1000)
T2 = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp() * 1000)


def _trade(symbol, seq, ts, agg_id, price):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": "observed-public", "source": "synthetic-test",
            "route": "test", "run_id": "t", "seq": seq, "channel": "aggTrade",
            "symbol": symbol, "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
            "local_mono_ns": seq, "gap_kind": None, "venue_seq": agg_id,
            "payload": {"agg_id": agg_id, "price": price, "qty": 0.5,
                        "first_id": agg_id, "last_id": agg_id,
                        "trade_ts_ms": ts, "buyer_is_maker": False}}


def _manifest(tmp_path: Path, n_each=8) -> Path:
    events = []
    for i in range(n_each):
        # Interleaved timestamps across symbols (merge must order).
        events.append(_trade(SYM_A, i + 1, T1 + 60_000 + i * 2000,
                             1000 + i, 100.0))
        events.append(_trade(SYM_B, i + 1, T1 + 61_000 + i * 2000,
                             3000 + i, 50.0))
    for i in range(n_each):
        events.append(_trade(SYM_A, n_each + i + 1,
                             T2 + 60_000 + i * 2000, 2000 + i, 101.0))
        events.append(_trade(SYM_B, n_each + i + 1,
                             T2 + 61_000 + i * 2000, 4000 + i, 51.0))
    ev_path = tmp_path / "events.jsonl"
    ev_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    toml = tmp_path / "cap.toml"
    toml.write_text(
        "[dataset]\nname = \"t\"\nkind = \"captured-runs\"\n"
        "manifest_version = 1\n\n[[source]]\nrun_id = \"t\"\n"
        "file = \"events.jsonl\"\n"
        f"local = \"{ev_path}\"\nsymbols = [\"{SYM_A}\", \"{SYM_B}\"]\n")
    return toml


def _filters(tmp_path: Path) -> Path:
    path = tmp_path / "filters.json"
    syms = []
    for sym in (SYM_A, SYM_B):
        syms.append({
            "symbol": sym, "pricePrecision": 2, "quantityPrecision": 3,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001",
                 "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
            ]})
    path.write_text(json.dumps({"symbols": syms}))
    return path


def _args(tmp_path, manifest, ckpt, report, extra=()):
    base = ["--config", "configs/paper.toml", "--dataset", str(manifest),
            "--symbols", f"{SYM_A},{SYM_B}", "--days", f"{DAY1},{DAY2}",
            "--wall-budget-s", "600", "--checkpoint-dir", str(ckpt),
            "--report-out", str(report),
            "--filters-file", str(_filters(tmp_path))]
    return base + list(extra)


def _booked(report):
    doc = json.loads(report.read_text())
    return doc


def test_multi_fresh_completes_both_symbols(tmp_path):
    manifest = _manifest(tmp_path)
    ckpt, report = tmp_path / "ck", tmp_path / "rep.json"
    assert main(_args(tmp_path, manifest, ckpt, report,
                      ["--run-id", "m1"])) == 0
    doc = _booked(report)
    assert doc["status"] == "COMPLETE"
    assert doc["runner_version"] == "bench-run-v3"
    assert doc["symbols"] == [SYM_A, SYM_B]
    assert doc["symbol"] is None  # multi: no single symbol.
    assert doc["events"]["ingested"] == 32
    assert doc["events"]["skipped_window"] == 0
    assert doc["booked"]["valuation"] == "cash-exact"
    commit = json.loads((ckpt / "bench_checkpoint.json").read_text())
    assert commit["cursor"] == {"day": DAY2,
                                "seqs": {SYM_A: 8, SYM_B: 8}}
    assert set(commit["feeds"]) == {SYM_A, SYM_B}


def test_multi_deterministic_across_runs(tmp_path):
    manifest = _manifest(tmp_path)
    docs = []
    for tag in ("a", "b"):
        ckpt = tmp_path / f"ck-{tag}"
        report = tmp_path / f"rep-{tag}.json"
        assert main(_args(tmp_path, manifest, ckpt, report,
                          ["--run-id", f"det-{tag}"])) == 0
        docs.append(_booked(report))
    for key in ("equity_close", "realised", "commissions", "funding"):
        assert docs[0]["booked"][key] == docs[1]["booked"][key], key
    assert docs[0]["cursor"] == docs[1]["cursor"]
    assert docs[0]["estimated_costs"] == docs[1]["estimated_costs"]


def test_multi_split_resume_matches_reference(tmp_path):
    manifest = _manifest(tmp_path)
    ref_ckpt, ref_rep = tmp_path / "ref-ck", tmp_path / "ref.json"
    assert main(_args(tmp_path, manifest, ref_ckpt, ref_rep,
                      ["--run-id", "ref"])) == 0
    ref = _booked(ref_rep)
    sp_ckpt = tmp_path / "sp-ck"
    rep1, rep2 = tmp_path / "sp1.json", tmp_path / "sp2.json"
    assert main(_args(tmp_path, manifest, sp_ckpt, rep1,
                      ["--run-id", "sp", "--max-events", "10"])) == 124
    assert _booked(rep1)["status"] == "TRUNCATED_MAX_EVENTS"
    assert main(_args(tmp_path, manifest, sp_ckpt, rep2,
                      ["--run-id", "sp", "--resume"])) == 0
    split = _booked(rep2)
    assert split["status"] == "COMPLETE"
    assert split["events"]["replayed_tail"] > 0
    for key in ("equity_close", "realised", "commissions", "funding"):
        assert split["booked"][key] == ref["booked"][key], key
    assert split["estimated_costs"] == ref["estimated_costs"]
    chunk1 = _booked(rep1)["events"]["ingested"]
    assert chunk1 + split["events"]["ingested"] - \
        split["events"]["replayed_tail"] == ref["events"]["ingested"]


def test_v2_checkpoint_migrates_single_symbol(tmp_path):
    manifest = _manifest(tmp_path)
    # Reference: uninterrupted single-symbol run.
    ref_ckpt, ref_rep = tmp_path / "ref-ck", tmp_path / "ref.json"
    args = _args(tmp_path, manifest, ref_ckpt, ref_rep, ["--run-id", "ref"])
    args[args.index("--symbols") + 1] = SYM_A
    assert main(args) == 0
    ref = _booked(ref_rep)
    assert ref["events"]["ingested"] == 16
    # Split run, then downgrade its checkpoint to v2 shape.
    sp_ckpt = tmp_path / "sp-ck"
    rep1, rep2 = tmp_path / "sp1.json", tmp_path / "sp2.json"
    args1 = _args(tmp_path, manifest, sp_ckpt, rep1,
                  ["--run-id", "sp", "--max-events", "5"])
    args1[args1.index("--symbols") + 1] = SYM_A
    assert main(args1) == 124
    ckpt_file = sp_ckpt / "bench_checkpoint.json"
    v3 = json.loads(ckpt_file.read_text())
    v2 = dict(v3)
    v2["runner_version"] = "bench-run-v2"
    (sym, seq), = v3["cursor"]["seqs"].items()
    v2["cursor"] = {"day": v3["cursor"]["day"], "seq": seq}
    ident = dict(v2["identity"])
    dataset = dict(ident["dataset"])
    dataset["symbol"] = dataset.pop("symbols")[0]
    assert sym == dataset["symbol"]
    ident["dataset"] = dataset
    v2["identity"] = ident
    ckpt_file.write_text(json.dumps(v2))
    args2 = _args(tmp_path, manifest, sp_ckpt, rep2,
                  ["--run-id", "sp", "--resume"])
    args2[args2.index("--symbols") + 1] = SYM_A
    assert main(args2) == 0
    split = _booked(rep2)
    assert split["status"] == "COMPLETE"
    for key in ("equity_close", "realised", "commissions", "funding"):
        assert split["booked"][key] == ref["booked"][key], key


def test_v2_refuses_multi_and_windowed(tmp_path):
    manifest = _manifest(tmp_path)
    sp_ckpt, rep1 = tmp_path / "sp-ck", tmp_path / "sp1.json"
    args1 = _args(tmp_path, manifest, sp_ckpt, rep1,
                  ["--run-id", "sp", "--max-events", "5"])
    args1[args1.index("--symbols") + 1] = SYM_A
    assert main(args1) == 124
    ckpt_file = sp_ckpt / "bench_checkpoint.json"
    v3 = json.loads(ckpt_file.read_text())
    v2 = dict(v3)
    v2["runner_version"] = "bench-run-v2"
    (sym, seq), = v3["cursor"]["seqs"].items()
    v2["cursor"] = {"day": v3["cursor"]["day"], "seq": seq}
    ident = dict(v2["identity"])
    dataset = dict(ident["dataset"])
    dataset["symbol"] = dataset.pop("symbols")[0]
    ident["dataset"] = dataset
    v2["identity"] = ident
    ckpt_file.write_text(json.dumps(v2))
    # Multi-symbol resume against a v2 commit: refused.
    assert main(_args(tmp_path, manifest, sp_ckpt, tmp_path / "x.json",
                      ["--run-id", "sp", "--resume"])) == 1
    # Windowed resume against a v2 commit: refused.
    windowed = _args(tmp_path, manifest, sp_ckpt, tmp_path / "y.json",
                     ["--run-id", "sp", "--resume",
                      "--start-ms", str(T1)])
    windowed[windowed.index("--symbols") + 1] = SYM_A
    assert main(windowed) == 1


def test_window_purity_counts_and_bounds(tmp_path):
    manifest = _manifest(tmp_path)
    ckpt, report = tmp_path / "ck", tmp_path / "rep.json"
    # Window isolating exactly one event (SYM_B day-1 first).
    start = T1 + 61_000
    end = T1 + 62_000
    assert main(_args(tmp_path, manifest, ckpt, report,
                      ["--run-id", "w1", "--start-ms", str(start),
                       "--end-ms", str(end)])) == 0
    doc = _booked(report)
    assert doc["status"] == "COMPLETE"
    assert doc["events"]["ingested"] == 1
    assert doc["events"]["skipped_window"] == 31
    assert doc["window_ms"] == [start, end]
    assert doc["cursor"] == {"day": DAY2, "seqs": {SYM_A: 8, SYM_B: 8}}
    # Window excluding everything: complete, nothing ingested.
    ckpt2, report2 = tmp_path / "ck2", tmp_path / "rep2.json"
    assert main(_args(tmp_path, manifest, ckpt2, report2,
                      ["--run-id", "w2", "--start-ms", str(T2 + 10_000_000),
                       "--end-ms", str(T2 + 20_000_000)])) == 0
    doc2 = _booked(report2)
    assert doc2["events"]["ingested"] == 0
    assert doc2["events"]["skipped_window"] == 32
    assert doc2["status"] == "COMPLETE"


def test_single_symbol_flag_matches_plural(tmp_path):
    manifest = _manifest(tmp_path)
    ckpt1, rep1 = tmp_path / "ck1", tmp_path / "rep1.json"
    args1 = _args(tmp_path, manifest, ckpt1, rep1, ["--run-id", "s1"])
    i = args1.index("--symbols")
    args1[i:i + 2] = ["--symbol", SYM_A]
    assert main(args1) == 0
    ckpt2, rep2 = tmp_path / "ck2", tmp_path / "rep2.json"
    args2 = _args(tmp_path, manifest, ckpt2, rep2, ["--run-id", "s2"])
    args2[args2.index("--symbols") + 1] = SYM_A
    assert main(args2) == 0
    d1, d2 = _booked(rep1), _booked(rep2)
    assert d1["symbol"] == d2["symbol"] == SYM_A
    assert d1["events"]["ingested"] == d2["events"]["ingested"] == 16
    for key in ("equity_close", "realised", "commissions", "funding"):
        assert d1["booked"][key] == d2["booked"][key], key


def test_cli_validation_rejects_shapes(tmp_path):
    manifest = _manifest(tmp_path)
    ckpt, report = tmp_path / "ck", tmp_path / "rep.json"
    base = _args(tmp_path, manifest, ckpt, report, ["--run-id", "v"])
    both = list(base) + ["--symbol", SYM_A]
    assert main(both) == 2  # --symbol + --symbols together.
    neither = [a for a in base if a != "--symbols"]
    neither.remove(f"{SYM_A},{SYM_B}")
    assert main(neither) == 2
    dup = list(base)
    dup[dup.index("--symbols") + 1] = f"{SYM_A},{SYM_A}"
    assert main(dup) == 2
    bad_window = list(base) + ["--start-ms", "5", "--end-ms", "5"]
    assert main(bad_window) == 2
