"""pivot_enroll unit tests (manager-owned, self-contained).

Covers: short capture -> DEVELOPMENT-ONLY with span reason, modelled
quotes fail the floor, funding rates are not settlements, qualifying
synthetic (10d, all channels, settlements, attested) -> ENROLLED,
unattested prior use blocks enrollment. Loads tool by path, no src/.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "pivot_enroll", REPO / "tools" / "pivot_enroll.py")
assert SPEC and SPEC.loader
pivot_enroll = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pivot_enroll)

DAY = 86_400_000
T0 = 1_700_000_000_000


def _ev(seq, chan, sym="BTCUSDT", ts=T0, payload=None):
    return {"v": 1, "format": "cryptobot-events/1", "seq": seq,
            "channel": chan, "symbol": sym, "exchange_ts_ms": ts,
            "payload": payload or {}}


def _capture(tmp_path, events, manifest=None):
    cap = tmp_path / "cap"
    cap.mkdir()
    (cap / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    (cap / "manifest.json").write_text(json.dumps(
        manifest or {"run_id": "synthetic", "symbols": ["BTCUSDT"]}),
        encoding="utf-8")
    return cap


def _qualifying_events():
    evs, seq = [], 0

    def add(chan, ts, payload=None):
        nonlocal seq
        seq += 1
        evs.append(_ev(seq, chan, ts=ts, payload=payload))

    for d in range(11):
        base = T0 + d * DAY
        add("bookTicker", base, {"bid": 1.0, "ask": 1.1})
        add("aggTrade", base + 1, {"price": 1.0, "qty": 1.0})
        add("fundingSettlement", base + 3000,
            {"settlement": True, "amount": 0.01})
    # Marks at the 5s floor cadence across the whole 10d span.
    ts = T0
    while ts <= T0 + 10 * DAY:
        add("markPrice", ts, {"mark": 1.0})
        ts += 5000
    evs.sort(key=lambda e: e["exchange_ts_ms"])
    for i, e in enumerate(evs, 1):
        e["seq"] = i
    return evs


def test_short_capture_is_development_only(tmp_path):
    evs = [_ev(1, "bookTicker", payload={"bid": 1, "ask": 2}),
           _ev(2, "aggTrade", ts=T0 + 1000)]
    res = pivot_enroll.audit(_capture(tmp_path, evs), False)
    assert res["verdict"] == "DEVELOPMENT-ONLY"
    assert any("span" in r for r in res["reasons"])


def test_modeled_quotes_and_rates_fail_floor(tmp_path):
    evs = _qualifying_events()
    evs[0]["payload"]["quote_source"] = "research-spread-profile"
    res = pivot_enroll.audit(_capture(tmp_path, evs), True)
    assert res["verdict"] == "DEVELOPMENT-ONLY"
    assert any("modelled" in r for r in res["reasons"])


def test_funding_rates_are_not_settlements(tmp_path):
    evs = [e for e in _qualifying_events()
           if e["channel"] != "fundingSettlement"]
    for e in evs:
        if e["channel"] == "markPrice":
            e["payload"]["funding_rate"] = 0.0001
    res = pivot_enroll.audit(_capture(tmp_path, evs), True)
    assert res["verdict"] == "DEVELOPMENT-ONLY"
    assert any("not settlements" in r for r in res["reasons"])


def test_qualifying_synthetic_enrolls_when_attested(tmp_path):
    res = pivot_enroll.audit(
        _capture(tmp_path, _qualifying_events()), True)
    assert res["verdict"] == "ENROLLED", res["reasons"]
    assert res["reasons"] == []


def _sidecar(tmp_path, records):
    p = tmp_path / "funding.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in records),
                 encoding="utf-8")
    return p


def test_funding_sidecar_with_provenance_enrolls(tmp_path):
    evs = [e for e in _qualifying_events()
           if e["channel"] != "fundingSettlement"]
    cap = _capture(tmp_path, evs)
    fund = _sidecar(tmp_path, [
        {"symbol": "BTCUSDT", "funding_ts_ms": T0 + DAY,
         "funding_rate": 0.0001, "source": "GET /fapi/v1/fundingRate"}])
    res = pivot_enroll.audit(cap, True, fund)
    assert res["verdict"] == "ENROLLED", res["reasons"]
    assert res["symbols"]["BTCUSDT"]["funding_sidecar_in_span"] == 1


def test_funding_sidecar_without_provenance_rejected(tmp_path):
    fund = _sidecar(tmp_path, [
        {"symbol": "BTCUSDT", "funding_ts_ms": T0, "funding_rate": 0.1}])
    import pytest
    with pytest.raises(ValueError, match="provenance"):
        pivot_enroll._funding_sidecar(fund)


def test_funding_sidecar_outside_span_does_not_count(tmp_path):
    evs = [e for e in _qualifying_events()
           if e["channel"] != "fundingSettlement"]
    cap = _capture(tmp_path, evs)
    fund = _sidecar(tmp_path, [
        {"symbol": "BTCUSDT", "funding_ts_ms": T0 - DAY,
         "funding_rate": 0.0001, "source": "GET /fapi/v1/fundingRate"}])
    res = pivot_enroll.audit(cap, True, fund)
    assert res["verdict"] == "DEVELOPMENT-ONLY"
    assert any("outside capture span" in r for r in res["reasons"])


def _campaign(tmp_path, chunks, symbols=("BTCUSDT",)):
    import gzip

    camp = tmp_path / "camp"
    camp.mkdir()
    state = {"symbols": list(symbols), "chunks": []}
    for i, events in enumerate(chunks):
        name = f"chunk-{i:03d}"
        cdir = camp / name
        cdir.mkdir()
        with gzip.open(cdir / "events.jsonl.gz", "wt",
                       encoding="utf-8") as fh:
            for e in events:
                fh.write(json.dumps(e) + "\n")
        (cdir / "SETTLED.json").write_text("{}")
        state["chunks"].append({"idx": i, "dir": name,
                                "status": "settled"})
    (camp / "campaign_state.json").write_text(json.dumps(state))
    return camp


def _seg_events(base_ts, n_each=3):
    evs = []
    seq = 0

    def add(chan, ts, payload=None):
        nonlocal seq
        seq += 1
        evs.append(_ev(seq, chan, ts=ts, payload=payload))

    for k in range(n_each):
        add("bookTicker", base_ts + k * 1000, {"bid": 1.0, "ask": 1.1})
        add("aggTrade", base_ts + k * 1000 + 1, {"price": 1.0})
        add("markPrice", base_ts + k * 1000 + 2, {"mark": 1.0})
    return evs


def test_campaign_streams_gz_and_resets_seq(tmp_path):
    camp = _campaign(tmp_path, [_seg_events(T0),
                                _seg_events(T0 + 3600_000)])
    res = pivot_enroll.audit_campaign(camp, True, min_chunk_events=1)
    # Short span + no funding fail; seq restart must NOT count.
    assert res["verdict"] == "DEVELOPMENT-ONLY"
    assert res["seq_disordered"] == 0
    assert res["events"] == 18
    assert len(res["chunks"]) == 2
    assert not any("seq" in r for r in res["reasons"])


def test_campaign_flags_empty_chunk(tmp_path):
    camp = _campaign(tmp_path, [_seg_events(T0), []])
    res = pivot_enroll.audit_campaign(camp, True)
    assert any("near-empty chunk" in r for r in res["reasons"])


def test_campaign_flags_unsettled_chunk(tmp_path):
    camp = _campaign(tmp_path, [_seg_events(T0)])
    (camp / "chunk-000" / "SETTLED.json").unlink()
    res = pivot_enroll.audit_campaign(camp, True)
    assert any("not settled" in r for r in res["reasons"])


def test_unattested_prior_use_blocks_enrollment(tmp_path):
    cap = _capture(tmp_path, _qualifying_events(),
                   {"run_id": "seen", "symbols": ["BTCUSDT"],
                    "prior_use": "X1 round-1 scoring"})
    res = pivot_enroll.audit(cap, False)
    assert res["verdict"] == "DEVELOPMENT-ONLY"
    assert any("untouched UNKNOWN" in r for r in res["reasons"])
