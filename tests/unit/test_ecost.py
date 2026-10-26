"""E-COST harness tests. All receipts are SYNTHETIC fixtures.

No live/demo calls, no holdout, no network. Every guard ships with a
deletion proof: each test fails if the guard it pins is removed --
especially the no-defaulting rule (delete any required-field check and
the parametrized refusal test below goes red).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from tools.ecost import (
    FILL_FIELDS,
    ECostRefusal,
    build_report,
    build_round_trips,
    check_power,
    decide,
    load_config,
    load_receipts,
)


def _fill(**overrides):
    record = {"kind": "fill", "fill_id": "F1", "venue_path": "demo",
              "symbol": "BTCUSDT", "leg": "spot", "side": "buy", "qty": 0.01,
              "notional": 800.0, "fill_price": 80000.0,
              "signal_bar_open": 80000.0, "spread_bps": 1.0, "fee_bps": 15.0,
              "fill_time": "2026-11-05T00:00:07+00:00",
              "round_trip_id": "RT1", "adv20": 500000000.0, "sigma_d": 0.03}
    record.update(overrides)
    return record


def _funding(**overrides):
    record = {"kind": "funding", "record_id": "U1", "venue_path": "demo",
              "symbol": "BTCUSDT",
              "settlement_time": "2026-11-05T00:00:00+00:00",
              "paid_rate_bp": 1.0, "vision_rate_bp": 1.0,
              "vision_file": "BTCUSDT-fundingRate-2026-11.zip"}
    record.update(overrides)
    return record


def _config(**overrides):
    config = {"study": "B4b", "modeled_rt_bps": 49.0,
              "modeled_fee_bps": {"spot": 15.0, "perp": 7.5},
              "modeled_spread_bps": {"spot": 1.0, "perp": 1.0},
              "fee_tier_evidence": {"vip_level": "VIP-0", "bnb_burn": False,
                                    "source": "synthetic-test"}}
    config.update(overrides)
    return config


def _write_lines(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in records) + "\n",
                    encoding="utf-8")
    return path


def _write_json(path: Path, doc: dict) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# -- no-defaulting: every required field observed --------------------------------


@pytest.mark.parametrize("field", list(FILL_FIELDS))
def test_missing_any_fill_field_refuses(tmp_path, field):
    record = _fill()
    del record[field]
    path = _write_lines(tmp_path / "r.jsonl", [record])
    with pytest.raises(ECostRefusal, match="missing observed field"):
        load_receipts(path)


@pytest.mark.parametrize("field", ["fee_bps", "signal_bar_open", "adv20",
                                   "round_trip_id", "fill_time"])
def test_null_fill_field_refuses(tmp_path, field):
    record = _fill(**{field: None})
    path = _write_lines(tmp_path / "r.jsonl", [record])
    with pytest.raises(ECostRefusal, match="missing observed field"):
        load_receipts(path)


@pytest.mark.parametrize("field", ["record_id", "venue_path", "symbol",
                                   "settlement_time", "paid_rate_bp",
                                   "vision_rate_bp", "vision_file"])
def test_missing_any_funding_field_refuses(tmp_path, field):
    record = _funding()
    del record[field]
    path = _write_lines(tmp_path / "r.jsonl", [_fill(), record])
    with pytest.raises(ECostRefusal, match="missing observed field"):
        load_receipts(path)


@pytest.mark.parametrize("field", ["study", "modeled_rt_bps",
                                   "modeled_fee_bps", "modeled_spread_bps",
                                   "fee_tier_evidence"])
def test_missing_any_config_field_refuses(tmp_path, field):
    config = _config()
    del config[field]
    path = _write_json(tmp_path / "c.json", config)
    with pytest.raises(ECostRefusal):
        load_config(path)


def test_bad_enums_and_nonfinite_refuse(tmp_path):
    for bad in ({"venue_path": "live"}, {"leg": "margin"}, {"side": "hold"},
                {"qty": -1.0}, {"notional": 0.0}, {"fee_bps": float("nan")},
                {"adv20": 0.0}, {"symbol": "  "}, {"kind": "dividend"},
                {"fill_time": "2026-11-05"}, {"fill_time": "not-a-time"}):
        path = _write_lines(tmp_path / "r.jsonl", [_fill(**bad)])
        with pytest.raises(ECostRefusal):
            load_receipts(path)


def test_pre_window_fill_and_oct_funding_file_refuse(tmp_path):
    old = _fill(fill_time="2026-10-17T00:00:00+00:00")
    with pytest.raises(ECostRefusal, match="not after"):
        load_receipts(_write_lines(tmp_path / "a.jsonl", [old]))
    october = _funding(vision_file="BTCUSDT-fundingRate-2026-10.zip")
    with pytest.raises(ECostRefusal, match="holdout-dated"):
        load_receipts(_write_lines(tmp_path / "b.jsonl", [_fill(), october]))
    undated = _funding(vision_file="mystery.zip")
    with pytest.raises(ECostRefusal, match="no YYYY-MM month"):
        load_receipts(_write_lines(tmp_path / "c.jsonl", [_fill(), undated]))


def test_mixed_venue_paths_refuse(tmp_path):
    other = _fill(fill_id="F2", venue_path="sim")
    path = _write_lines(tmp_path / "r.jsonl", [_fill(), other])
    with pytest.raises(ECostRefusal, match="never mixed"):
        load_receipts(path)


def test_empty_and_malformed_inputs_refuse(tmp_path):
    with pytest.raises(ECostRefusal, match="no fill records"):
        load_receipts(_write_lines(tmp_path / "a.jsonl", [_funding()]))
    bad = tmp_path / "b.jsonl"
    bad.write_text("{nope\n", encoding="utf-8")
    with pytest.raises(ECostRefusal, match="not JSON"):
        load_receipts(bad)
    with pytest.raises(ECostRefusal, match="cannot read"):
        load_config(tmp_path / "missing.json")


def test_round_trip_needs_open_and_close(tmp_path):
    fills, _ = load_receipts(_write_lines(tmp_path / "r.jsonl", [_fill()]))
    with pytest.raises(ECostRefusal, match="needs open \\+ close"):
        build_round_trips(fills)


# -- math ------------------------------------------------------------------------


def test_slippage_sign_and_rt_weighting(tmp_path):
    day = "2026-11-05T00:00:07+00:00"
    buy = _fill(fill_id="B", side="buy", fill_price=80100.0,
                signal_bar_open=80000.0, fee_bps=10.0, fill_time=day,
                notional=800.0)
    sell = _fill(fill_id="S", side="sell", fill_price=79900.0,
                 signal_bar_open=80000.0, fee_bps=10.0, fill_time=day,
                 notional=1600.0)
    fills, _ = load_receipts(_write_lines(tmp_path / "r.jsonl", [buy, sell]))
    assert fills[0]["slippage_bps"] == pytest.approx(12.5)  # adverse buy
    assert fills[1]["slippage_bps"] == pytest.approx(12.5)  # adverse sell
    trips = build_round_trips(fills)
    # RT notional = earliest fill (800): 22.5*800/800 + 22.5*1600/800.
    assert trips["BTCUSDT"][0]["realized_rt_bps"] == pytest.approx(67.5)
    impact = fills[0]["modeled_impact_bps"]
    assert impact == pytest.approx(0.5 * 0.03 * (800.0 / 500000000.0) ** 0.5
                                   * 1e4)


def _powered_sample(fee_by_trip: list[float], symbol: str = "BTCUSDT",
                    legs: tuple[str, ...] = ("spot", "perp")) -> list[dict]:
    """40 fills over 40 days, 4 fills per RT, zero slippage, exact RT math.

    With equal notionals, realized RT = 2*fee_spot + 2*fee_perp per trip;
    fee_by_trip sets every fill fee in that trip so RT = 4*fee.
    """
    base = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    records = []
    index = 0
    for trip, fee in enumerate(fee_by_trip):
        for leg in ("spot", "spot", "perp", "perp"):
            if leg not in legs:
                continue
            stamp = (base + dt.timedelta(days=index)).isoformat()
            records.append(_fill(fill_id=f"F{index}", symbol=symbol, leg=leg,
                                 fee_bps=fee, fill_time=stamp,
                                 round_trip_id=f"RT{trip}"))
            index += 1
    return records


def test_percentile_and_median_edges(tmp_path):
    from tools.ecost import _percentile

    assert _percentile([5.0], 90) == 5.0
    assert _percentile([1.0, 3.0], 50) == 1.0  # nearest-rank, guarded
    assert _percentile([10.0, 20.0, 30.0], 90) == 30.0


# -- power gate --------------------------------------------------------------------


def test_power_gate_boundaries(tmp_path):
    fills, _ = load_receipts(_write_lines(
        tmp_path / "a.jsonl", _powered_sample([11.25] * 10)))
    power = check_power(fills)
    assert power["powered"] is True
    assert power["fills_per_leg"] == {"BTCUSDT/perp": 20, "BTCUSDT/spot": 20}
    assert power["window_days"] == 40

    short = [row for row in _powered_sample([11.25] * 10)
             if not (row["leg"] == "spot" and row["fill_id"] == "F0")]
    fills, _ = load_receipts(_write_lines(tmp_path / "b.jsonl", short))
    power = check_power(fills)
    assert power["powered"] is False
    assert "BTCUSDT/spot" in power["short_legs"]
    assert "extend the window" in power["guidance"]

    early = _powered_sample([11.25] * 10)
    for row in early:  # squeeze into 10 days
        stamp = dt.datetime(2026, 11, 1, tzinfo=dt.UTC) + dt.timedelta(
            days=int(row["fill_id"][1:]) % 10)
        row["fill_time"] = stamp.isoformat()
    fills, _ = load_receipts(_write_lines(tmp_path / "c.jsonl", early))
    assert check_power(fills)["powered"] is False


def test_power_gate_descriptive_only_past_90d(tmp_path):
    base = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    records = []
    for day in range(0, 95, 5):  # 19 fills/leg over 95 days
        for leg in ("spot", "perp"):
            stamp = (base + dt.timedelta(days=day)).isoformat()
            records.append(_fill(fill_id=f"{leg}{day}", leg=leg,
                                 fill_time=stamp,
                                 round_trip_id=f"RT{day // 5}"))
    fills, _ = load_receipts(_write_lines(tmp_path / "r.jsonl", records))
    power = check_power(fills)
    assert power["powered"] is False
    assert power["descriptive_only"] is True
    assert "descriptive statistics only" in power["guidance"]


# -- the four decision rules -----------------------------------------------------------


def _decide(tmp_path, fee_by_trip, **funding_kw):
    records = _powered_sample(fee_by_trip) + [_funding(**funding_kw)]
    fills, funding = load_receipts(_write_lines(tmp_path / "r.jsonl",
                                                records))
    config = load_config(_write_json(tmp_path / "c.json", _config()))
    assert check_power(fills)["powered"] is True
    return decide(build_round_trips(fills), funding, config)


def test_verdict_confirmed(tmp_path):
    out = _decide(tmp_path, [11.25] * 10)  # RT 45 <= 49, p90 45 <= 98
    assert out["verdict"] == "CONFIRMED"
    assert out["per_symbol"]["BTCUSDT"]["median_rt_bps"] == pytest.approx(45.0)
    assert out["funding_reconciled"] is True
    assert out["restated_rt_bps"] == {}


def test_verdict_restate_up_on_median(tmp_path):
    out = _decide(tmp_path, [12.5] * 10)  # RT 50 > 49, <= 98
    assert out["verdict"] == "RESTATE-UP"
    assert out["restated_rt_bps"]["BTCUSDT"] == pytest.approx(50.0)


def test_verdict_killed_past_twice_modeled(tmp_path):
    out = _decide(tmp_path, [25.0] * 10)  # RT 100 > 98
    assert out["verdict"] == "COST-MODEL-KILLED"
    assert out["restated_rt_bps"] == {}


def test_verdict_restate_up_on_fat_tail(tmp_path):
    fees = [11.25] * 8 + [30.0] * 2  # median 45, p90 120 > 98
    out = _decide(tmp_path, fees)
    assert out["verdict"] == "RESTATE-UP"
    assert "p90" in out["verdict_reason"]


def test_verdict_underpowered(tmp_path):
    records = _powered_sample([11.25] * 2)  # 4 fills/leg, 8 days
    fills, funding = load_receipts(_write_lines(
        tmp_path / "r.jsonl", records + [_funding()]))
    config = load_config(_write_json(tmp_path / "c.json", _config()))
    report = build_report(fills, funding, config, tmp_path / "r.jsonl")
    assert report["verdict"] == "UNDERPOWERED"
    assert report["descriptive_only"] is False
    assert len(report["fills_table"]) == 8  # table still reported


def test_funding_mismatch_blocks_verdict(tmp_path):
    with pytest.raises(ECostRefusal, match="does not reconcile"):
        _decide(tmp_path, [11.25] * 10, paid_rate_bp=1.5)


# -- report + CLI ----------------------------------------------------------------------


def test_report_binds_provenance_and_components(tmp_path):
    records = _powered_sample([11.25] * 10) + [_funding()]
    fills, funding = load_receipts(_write_lines(
        tmp_path / "r.jsonl", records))
    config = load_config(_write_json(tmp_path / "c.json", _config()))
    report = build_report(fills, funding, config, tmp_path / "r.jsonl")
    assert report["format"] == "cryptobot-ecost-report/1"
    assert report["measurement_only"] is True
    assert report["venue_path"] == "demo"
    assert report["fee_tier_evidence"]["vip_level"] == "VIP-0"
    assert len(report["config_hash"]) == 64
    spot = report["components"]["spot"]
    assert spot["fee_delta_bps"] == pytest.approx(11.25 - 15.0)
    assert spot["spread_delta_bps"] == pytest.approx(0.0)
    assert report["verdict"] == "CONFIRMED"


def test_cli_report_and_template(tmp_path):
    import tools.ecost as ecost

    paths = ecost.write_templates(tmp_path / "tpl")
    assert Path(paths["receipts"]).exists()
    assert Path(paths["config"]).exists()

    records = _powered_sample([11.25] * 10) + [_funding()]
    receipts = _write_lines(tmp_path / "r.jsonl", records)
    config = _write_json(tmp_path / "c.json", _config())

    class Args:
        pass

    args = Args()
    args.receipts, args.config, args.out = (str(receipts), str(config),
                                            str(tmp_path / "out"))
    assert ecost.cmd_report(args) == 0
    doc = json.loads((tmp_path / "out" / "ecost-report.json").read_text())
    assert doc["verdict"] == "CONFIRMED"
    assert len(doc["fills_table"]) == 40

    bad = _write_lines(tmp_path / "bad.jsonl", [_fill(venue_path="live")])
    args.receipts = str(bad)
    assert ecost.cmd_report(args) == 2  # refusal, no verdict file touched
