"""Mutation-proven audit guards for the C2 forward recorder/scorer."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import random
import sys
from pathlib import Path

import pytest

from cryptobot.research import c_family

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
_spec = importlib.util.spec_from_file_location(
    "forward_c2_audit", Path(__file__).resolve().parents[2] / "tools/forward_c2.py")
fwd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fwd)

D0 = dt.date(2027, 1, 4)
DAYS = [(D0 + dt.timedelta(days=k)).isoformat() for k in range(160)]


class AuditFetcher:
    def __init__(self, n: int = 30):
        self.closes = {}
        self.funds = {}
        self.fail_volume: set[str] = set()
        self.missing_funding: set[str] = set()
        self.missing_closes: set[tuple[str, str]] = set()
        for i in range(n):
            sym = f"S{i:02d}USDT"
            # deterministic, distinct momentum ranks and nonzero daily returns
            self.closes[sym] = {d: (100 + i * 5) * (1 + i / 10_000) ** k
                                for k, d in enumerate(DAYS)}
            self.funds[sym] = {d: 0.0001 for d in DAYS}

    def universe_snapshot(self, day, *, observed_at, include_volume):
        symbols = {s: {"status": "TRADING", "onboard_date": "2026-11-01"}
                   for s in sorted(self.closes)}
        volumes = {}
        if include_volume:
            if self.fail_volume:
                raise fwd.RefusedToBook("unreadable 30-day volume snapshot")
            volumes = {s: float(int(s[1:3]) + 1) for s in self.closes}
        return {"day": day, "observed_at_utc": observed_at.isoformat(),
                "source": "synthetic", "symbols": symbols,
                "quote_volume_30d": volumes}

    def quote_volume_30d(self, symbol, end_day):
        if symbol in self.fail_volume:
            raise OSError("synthetic partial outage")
        return float(int(symbol[1:3]) + 1)

    def mark_closes(self, symbol, start, end):
        return {d: v for d, v in self.closes[symbol].items()
                if start <= d <= end and (symbol, d) not in self.missing_closes}

    def funding(self, symbol, start, end):
        if symbol in self.missing_funding:
            return {}
        return {d: v for d, v in self.funds[symbol].items() if start <= d <= end}

    def funding_events(self, symbol, start_day, end_day):
        if symbol in self.missing_funding:
            return []
        total = self.funds[symbol].get(start_day, 0.0)
        start_ms = fwd._ms(start_day)
        return [(start_ms + 8 * 3_600_000, total / 3),
                (start_ms + 16 * 3_600_000, total / 3),
                (fwd._ms(end_day), total / 3)]


def _seed(root: Path, *, last: str, held: dict | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps({
        "last_booked": last, "universe": [f"S{i:02d}USDT" for i in range(12)],
        "held": held or {}, "bootstrap_anchor": True}))


def _snapshot(fetcher, day: str, *, include_volume: bool = False,
              close: bool = False) -> dict:
    observed_day = fwd._shift(day, 1) if close else day
    observed_time = dt.time(0, 5) if close else dt.time(18, 0)
    observed = dt.datetime.combine(dt.date.fromisoformat(observed_day),
                                   observed_time, tzinfo=dt.UTC)
    snapshot = fetcher.universe_snapshot(day, observed_at=observed,
                                         include_volume=include_volume)
    if close:
        snapshot["source"] = "post-close-status"
    if include_volume:
        volume_time = dt.datetime.combine(dt.date.fromisoformat(fwd._shift(day, 1)),
                                          dt.time(0, 5), tzinfo=dt.UTC)
        snapshot["volume_observed_at_utc"] = volume_time.isoformat()
    return snapshot


def _ledger(root: Path, n: int, mean: float, seed: int = 4) -> None:
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "ledger.jsonl").open("w") as fh:
        for k in range(n):
            x = rng.gauss(mean, 150.0)
            fh.write(json.dumps({
                "day": (D0 + dt.timedelta(days=k)).isoformat(), "net_bps": x,
                "adverse_bps": x - 9.0, "gross_bps": x + 9.0, "turnover": 1.0}) + "\n")


def test_refuses_low_coverage_missing_funding_and_volume_outage(tmp_path):
    fetcher = AuditFetcher()
    fetcher.missing_closes.update((s, DAYS[60]) for s in fetcher.closes if int(s[1:3]) >= 2)
    with pytest.raises(fwd.RefusedToBook, match="stale or partial"):
        fwd.book_day(fetcher, {"universe": sorted(fetcher.closes), "held": {}},
                     DAYS[59], snapshot=_snapshot(fetcher, DAYS[59]),
                     next_snapshot=_snapshot(fetcher, DAYS[60], close=True))

    fetcher = AuditFetcher()
    target = c_family.signal_xsmom(
        fetcher.closes, {}, DAYS, DAYS.index(DAYS[63]), sorted(fetcher.closes))
    exposed = next(iter(target))
    fetcher.missing_funding.add(exposed)
    with pytest.raises(fwd.RefusedToBook, match="funding"):
        fwd.book_day(fetcher, {"universe": sorted(fetcher.closes), "held": {}},
                     DAYS[63], snapshot=_snapshot(fetcher, DAYS[63], include_volume=True),
                     next_snapshot=_snapshot(fetcher, DAYS[64], close=True))

    # Missing funding for a symbol with no target exposure is irrelevant.
    fetcher = AuditFetcher()
    target = c_family.signal_xsmom(
        fetcher.closes, {}, DAYS, DAYS.index(DAYS[63]), sorted(fetcher.closes))
    nonexposed = next(sym for sym in fetcher.closes if sym not in target)
    fetcher.missing_funding.add(nonexposed)
    row = fwd.book_day(fetcher, {"universe": sorted(fetcher.closes), "held": {}},
                        DAYS[63], snapshot=_snapshot(fetcher, DAYS[63], include_volume=True),
                        next_snapshot=_snapshot(fetcher, DAYS[64], close=True))
    assert nonexposed not in row["weights"]

    fetcher = AuditFetcher()
    fetcher.fail_volume.update(fetcher.closes)
    with pytest.raises(fwd.RefusedToBook, match="unreadable"):
        fwd.book_day(fetcher, {"universe": [], "held": {}}, DAYS[59],
                     snapshot=_snapshot(fetcher, DAYS[59], include_volume=True),
                     next_snapshot=_snapshot(fetcher, DAYS[60], close=True))


def test_listing_age_cutoff_is_35_calendar_days_inclusive():
    fetcher = AuditFetcher(n=31)
    day = DAYS[63]
    snapshot = _snapshot(fetcher, day, include_volume=True)
    snapshot["symbols"]["S29USDT"]["onboard_date"] = fwd._shift(day, -35)
    snapshot["symbols"]["S30USDT"]["onboard_date"] = fwd._shift(day, -34)
    universe = fwd._universe(snapshot, day)
    assert "S29USDT" in universe  # exactly 35 calendar days is eligible
    assert "S30USDT" not in universe  # 34 days is too young
    assert len(universe) == 30


def test_universe_refuses_incomplete_top30():
    fetcher = AuditFetcher(n=29)
    day = DAYS[63]
    with pytest.raises(fwd.RefusedToBook, match="fewer than 30"):
        fwd._universe(_snapshot(fetcher, day, include_volume=True), day)


def test_universe_snapshot_rejects_future_or_stale_membership():
    fetcher = AuditFetcher()
    day = DAYS[59]
    future = _snapshot(fetcher, day)
    future["observed_at_utc"] = dt.datetime.combine(
        dt.date.fromisoformat(fwd._shift(day, 1)), dt.time(0, 5),
        tzinfo=dt.UTC).isoformat()
    with pytest.raises(fwd.RefusedToBook, match="before its UTC close"):
        fwd._validate_snapshot(future, day)
    future["observed_at_utc"] = 17
    with pytest.raises(fwd.RefusedToBook, match="invalid snapshot timestamp"):
        fwd._validate_snapshot(future, day)

    stale = _snapshot(fetcher, day)
    stale["observed_at_utc"] = dt.datetime.combine(
        dt.date.fromisoformat(day), dt.time(12, 0), tzinfo=dt.UTC).isoformat()
    with pytest.raises(fwd.RefusedToBook, match="stale"):
        fwd._require_fresh_selection(stale, day)

    future = _snapshot(fetcher, day)
    future["observed_at_utc"] = dt.datetime.combine(
        dt.date.fromisoformat(day), dt.time(23, 0), tzinfo=dt.UTC).isoformat()
    observed_by = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(18, 0),
                                      tzinfo=dt.UTC)
    with pytest.raises(fwd.RefusedToBook, match="future point-in-time"):
        fwd._require_fresh_selection(future, day, observed_by)


def test_confirmed_delisting_is_not_confused_with_a_candle_gap():
    fetcher = AuditFetcher()
    day, nxt = DAYS[59], DAYS[60]
    fetcher.missing_closes.add(("S11USDT", nxt))
    snapshot = _snapshot(fetcher, day)
    next_snapshot = _snapshot(fetcher, nxt, close=True)
    next_snapshot["symbols"].pop("S11USDT")
    state = {"universe": sorted(fetcher.closes), "held": {"S11USDT": 1.0}}
    row = fwd.book_day(fetcher, state, day, snapshot=snapshot,
                       next_snapshot=next_snapshot)
    assert "S11USDT" in row["retired_symbols"]
    assert "S11USDT" not in row["held_after"]
    assert row["retired_exit_mark_day"] == day
    assert row["retired_exit_turnover"] == pytest.approx(1.0)
    assert row["turnover"] == pytest.approx(1.0)
    assert row["gross_bps"] == pytest.approx(0.0)
    assert row["net_bps"] == pytest.approx(-9.0)
    assert row["adverse_bps"] == pytest.approx(-18.0)

    fetcher = AuditFetcher()
    fetcher.missing_closes.add(("S11USDT", nxt))
    with pytest.raises(fwd.RefusedToBook, match="next candle"):
        fwd.book_day(fetcher, {"universe": sorted(fetcher.closes), "held": {"S11USDT": 1.0}},
                     day, snapshot=_snapshot(fetcher, day),
                     next_snapshot=_snapshot(fetcher, nxt, close=True))

    with pytest.raises(fwd.RefusedToBook, match="unconfirmed missing candle"):
        fwd.book_day(fetcher, {"universe": sorted(fetcher.closes),
                               "held": {"S11USDT": 1.0}},
                     day, snapshot=_snapshot(fetcher, day), next_snapshot=None)

    halted = _snapshot(fetcher, nxt, close=True)
    halted["symbols"]["S11USDT"]["status"] = "SETTLING"
    with pytest.raises(fwd.RefusedToBook, match="not a confirmed delisting"):
        fwd.book_day(fetcher, {"universe": sorted(fetcher.closes), "held": {"S11USDT": 1.0}},
                     day, snapshot=_snapshot(fetcher, day), next_snapshot=halted)


def test_t_plus_one_data_cannot_change_signal_eligibility():
    fetcher = AuditFetcher()
    t_day = DAYS[63]
    start = fwd._shift(t_day, -fwd.HISTORY_DAYS)
    days = [fwd._shift(start, k) for k in range(fwd.HISTORY_DAYS + 2)]
    t = days.index(t_day)
    closes = {s: {d: fetcher.closes[s][d] for d in days if d in fetcher.closes[s]}
              for s in fetcher.closes}
    before = fwd._eligible_at(closes, days, t)
    weights_before = c_family.signal_xsmom(closes, {}, days, t, before)
    closes["S11USDT"].pop(days[t + 1])
    after = fwd._eligible_at(closes, days, t)
    weights_after = c_family.signal_xsmom(closes, {}, days, t, after)
    assert after == before
    assert weights_after == weights_before
    assert "S11USDT" in after


def test_signal_eligibility_requires_36_closes_across_35_intervals():
    assert fwd.HISTORY_DAYS == 35
    fetcher = AuditFetcher()
    days = DAYS[:37]
    t = 35
    eligible = fwd._eligible_at(fetcher.closes, days, t)
    assert eligible == sorted(fetcher.closes)

    missing_oldest = eligible[0]
    fetcher.closes[missing_oldest].pop(days[0])
    assert missing_oldest not in fwd._eligible_at(fetcher.closes, days, t)

    missing_decision_close = eligible[1]
    fetcher.closes[missing_decision_close].pop(days[t])
    assert missing_decision_close not in fwd._eligible_at(fetcher.closes, days, t)


def test_scoring_rejects_gaps_duplicates_and_bad_look_counts(tmp_path):
    root = tmp_path / "ledger"
    _ledger(root, 365, 0.0)
    rows = (root / "ledger.jsonl").read_text().splitlines()
    rows[100] = rows[99]
    (root / "ledger.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(fwd.LedgerError, match="not consecutive"):
        fwd.score_look(root, tmp_path / "report", 1)
    _ledger(root, 400, 0.0)
    assert fwd.health(root)["looks_due"] == []
    assert fwd.health(root)["missed_looks"] == [1]
    with pytest.raises(RuntimeError, match="exactly 365"):
        fwd.score_look(root, tmp_path / "report", 1)
    _ledger(root, 365, 0.0)
    with pytest.raises(ValueError, match="1..3"):
        fwd.score_look(root, tmp_path / "report", 0)
    # A look requires its prior look to have completed and exactly its row count.
    out = tmp_path / "ordered"
    out.mkdir()
    (out / "C2-forward-look1.json").write_text('{"verdict":"CONTINUE"}')
    with pytest.raises(RuntimeError, match="does not match its scored ledger"):
        fwd.score_look(root, out, 2)
    _ledger(root, 730, 0.0)
    with pytest.raises(RuntimeError, match="does not match its scored ledger"):
        fwd.score_look(root, out, 2)


def test_negative_ledger_scores_without_inverse_cdf_crash(tmp_path):
    _ledger(tmp_path / "ledger", 365, -50.0)
    doc = fwd.score_look(tmp_path / "ledger", tmp_path / "out", 1)
    assert doc["verdict"] == "CONTINUE"
    assert doc["z"] is None  # p=1 maps to z=-infinity internally, JSON null externally


def test_frozen_boundary_and_adverse_condition_are_applied_inclusively(tmp_path, monkeypatch):
    root = tmp_path / "ledger"
    root.mkdir()
    with (root / "ledger.jsonl").open("w") as fh:
        for k in range(365):
            fh.write(json.dumps({"day": (D0 + dt.timedelta(days=k)).isoformat(),
                                 "net_bps": 1.0, "adverse_bps": 1.0,
                                 "gross_bps": 1.0, "turnover": 1.0}) + "\n")
    monkeypatch.setattr(fwd, "BOOTSTRAP_ROUNDS", 100)

    def fake_score(results, *, rounds):
        return {"p_value": 0.001, "mean_adverse_bps": 1.0,
                "mean_net_bps": 1.0, "n_days": 365}

    monkeypatch.setattr(fwd.c_family, "score", fake_score)
    passed = fwd.score_look(root, tmp_path / "pass", 1)
    assert passed["z"] >= fwd.OBF_BOUNDS[0]
    assert passed["verdict"] == "FORWARD-PASS"

    def adverse_fail(results, *, rounds):
        return {"p_value": 0.001, "mean_adverse_bps": 0.0,
                "mean_net_bps": 1.0, "n_days": 365}

    monkeypatch.setattr(fwd.c_family, "score", adverse_fail)
    failed = fwd.score_look(root, tmp_path / "adverse", 1)
    assert failed["verdict"] == "CONTINUE"


def test_forward_score_uses_pinned_bootstrap_rounds_and_gatekeeps_vm(tmp_path, monkeypatch):
    root = tmp_path / "ledger"
    _ledger(root, 365, mean=0.0)
    monkeypatch.setattr(fwd, "BOOTSTRAP_ROUNDS", 50_000)
    calls = []

    def fake_score(results, *, rounds):
        calls.append(rounds)
        p = 0.001 if len(calls) == 1 else 0.5
        return {"p_value": p, "mean_adverse_bps": 1.0,
                "mean_net_bps": 1.0, "n_days": len(results)}

    monkeypatch.setattr(fwd.c_family, "score", fake_score)
    doc = fwd.score_look(root, tmp_path / "pass", 1)
    assert calls == [50_000, 50_000]
    assert doc["verdict"] == "FORWARD-PASS"
    assert doc["secondary_C2_VM_test"]["bound"] == fwd.OBF_BOUNDS[0]
    assert doc["secondary_C2_VM_test"]["status"] == "NOT-PASS"

    calls.clear()
    def primary_fail(results, *, rounds):
        calls.append(rounds)
        return {"p_value": 0.5, "mean_adverse_bps": 1.0,
                "mean_net_bps": 1.0, "n_days": len(results)}

    monkeypatch.setattr(fwd.c_family, "score", primary_fail)
    no_leak = fwd.score_look(root, tmp_path / "continue", 1)
    assert calls == [50_000]
    assert no_leak["secondary_C2_VM_test"]["status"] == "NOT-TESTED"
    assert "mean_bps" not in no_leak["secondary_C2_VM_test"]


def test_health_never_reports_return_statistics(tmp_path):
    _ledger(tmp_path / "ledger", 5, mean=1.0)
    report = fwd.health(tmp_path / "ledger")
    assert not {"mean", "mean_bps", "net_bps", "sharpe", "p_value"} & report.keys()


def test_health_does_not_mark_corrupt_row_count_as_look_due(tmp_path):
    root = tmp_path / "ledger"
    _ledger(root, 365, mean=0.0)
    lines = (root / "ledger.jsonl").read_text().splitlines()
    lines[100] = lines[99]
    (root / "ledger.jsonl").write_text("\n".join(lines) + "\n")
    report = fwd.health(root)
    assert report["duplicates"] == 1
    assert report["looks_due"] == []


def test_prior_look_report_is_bound_to_look_ledger_and_recomputed_verdict(tmp_path):
    root, out = tmp_path / "ledger", tmp_path / "out"
    _ledger(root, 365, 0.0)
    original = fwd.score_look(root, out, 1)
    assert original["verdict"] == "CONTINUE"
    _ledger(root, 730, 0.0)

    path = out / "C2-forward-look1.json"
    wrong_look = {**original, "look": 2}
    path.write_text(json.dumps(wrong_look))
    with pytest.raises(RuntimeError, match="does not match its scored ledger"):
        fwd.score_look(root, out, 2)

    wrong_hash = {**original, "ledger_sha256": "0" * 64}
    path.write_text(json.dumps(wrong_hash))
    with pytest.raises(RuntimeError, match="does not match its scored ledger"):
        fwd.score_look(root, out, 2)

    forged_continue = {**original, "verdict": "FORWARD-PASS"}
    path.write_text(json.dumps(forged_continue))
    with pytest.raises(RuntimeError, match="inconsistent with its ledger"):
        fwd.score_look(root, out, 2)


def test_score_stops_after_pass_and_is_reproducible(tmp_path, monkeypatch):
    root, out = tmp_path / "ledger", tmp_path / "out"
    # Constant positive returns make every bootstrap mean positive, so the
    # minimum smoothed p crosses the first frozen boundary deterministically.
    root.mkdir(parents=True)
    with (root / "ledger.jsonl").open("w") as fh:
        for k in range(365):
            x = 60.0
            fh.write(json.dumps({"day": (D0 + dt.timedelta(days=k)).isoformat(),
                                 "net_bps": x, "adverse_bps": x - 9,
                                 "gross_bps": x + 9, "turnover": 1.0}) + "\n")
    monkeypatch.setattr(fwd, "BOOTSTRAP_ROUNDS", 1000)
    first = fwd.score_look(root, out, 1)
    assert first["verdict"] == "FORWARD-PASS"
    with pytest.raises(RuntimeError, match="already stopped"):
        fwd.score_look(root, out, 2)
    assert first["ledger_sha256"] == fwd.hashlib.sha256(
        "\n".join(json.dumps(r, sort_keys=True) for r in fwd._rows(root)[:365]).encode()
    ).hexdigest()


def test_exchange_info_requires_complete_fresh_server_response(monkeypatch):
    now = dt.datetime(2027, 1, 5, 0, 15, tzinfo=dt.UTC)
    server_now = now - dt.timedelta(minutes=2)
    info = {"timezone": "UTC", "serverTime": int(server_now.timestamp() * 1000),
            "rateLimits": [], "exchangeFilters": [],
            "symbols": [{"contractType": "PERPETUAL", "quoteAsset": "USDT",
                         "symbol": "BTCUSDT", "status": "TRADING",
                         "onboardDate": fwd._ms("2020-01-01")}]
            }
    fetcher = fwd.RestFetcher(now=lambda: now)
    monkeypatch.setattr(fetcher, "_get", lambda *args, **kwargs: info)
    snapshot = fetcher.universe_snapshot(
        now.date().isoformat(), observed_at=now, include_volume=False)
    assert snapshot["symbols"]["BTCUSDT"]["status"] == "TRADING"
    assert snapshot["observed_at_utc"] == server_now.isoformat()

    info["serverTime"] -= 60 * 60 * 1000
    with pytest.raises(fwd.RefusedToBook, match="server time is stale"):
        fetcher.universe_snapshot(now.date().isoformat(), observed_at=now,
                                  include_volume=False)


def test_mark_fetch_rejects_unfinished_candle_and_incomplete_volume_window(monkeypatch):
    day = DAYS[20]
    close_time = fwd._ms(day) + 86_399_999
    row = [fwd._ms(day), 1, 1, 1, 123.0, 0, close_time, 1.0]
    stale = fwd.RestFetcher(now_ms=lambda: close_time - 1)
    monkeypatch.setattr(stale, "_get", lambda *args, **kwargs: [row])
    assert stale.mark_closes("S00USDT", day, day) == {}
    final = fwd.RestFetcher(now_ms=lambda: close_time)
    monkeypatch.setattr(final, "_get", lambda *args, **kwargs: [row])
    assert final.mark_closes("S00USDT", day, day) == {day: 123.0}
    malformed = [fwd._ms(day) + 1000, 1, 1, 1, 123.0, 0, close_time, 1.0]
    monkeypatch.setattr(final, "_get", lambda *args, **kwargs: [malformed])
    with pytest.raises(fwd.RefusedToBook, match="malformed UTC mark candle"):
        final.mark_closes("S00USDT", day, day)

    volume = fwd.RestFetcher()
    monkeypatch.setattr(volume, "_get", lambda *args, **kwargs: [[0] * 7 + [1.0]] * 29)
    with pytest.raises(fwd.RefusedToBook, match="30"):
        volume.quote_volume_30d("S00USDT", day)


def test_candle_completion_uses_exchange_server_time_not_ahead_local_clock(monkeypatch):
    day = DAYS[20]
    start = fwd._shift(day, -29)
    rows = [[fwd._ms(fwd._shift(start, i)), 1, 1, 1, 1, 0,
             fwd._ms(fwd._shift(start, i)) + 86_399_999, 1.0]
            for i in range(30)]
    close_time = rows[-1][6]
    local_now = dt.datetime.fromtimestamp((close_time + 60_000) / 1000, dt.UTC)
    fetcher = fwd.RestFetcher(now=lambda: local_now)
    fetcher._exchange_server_time_ms = close_time - 1
    monkeypatch.setattr(fetcher, "_get", lambda *args, **kwargs: rows)
    with pytest.raises(fwd.RefusedToBook, match="stale or invalid volume candle"):
        fetcher.quote_volume_30d("S00USDT", day)

    mark = fwd.RestFetcher(now=lambda: local_now)
    mark._exchange_server_time_ms = close_time - 1
    monkeypatch.setattr(mark, "_get", lambda *args, **kwargs: [rows[-1]])
    assert mark.mark_closes("S00USDT", day, day) == {}


def test_funding_requires_full_settlement_coverage(monkeypatch):
    day = DAYS[63]
    start = fwd._ms(day)
    events = [{"fundingTime": start + hours * 3_600_000, "fundingRate": "0.0001"}
              for hours in (8, 16)]
    events.append({"fundingTime": start + 86_400_000, "fundingRate": "0.0001"})
    fetcher = fwd.RestFetcher()
    monkeypatch.setattr(
        fetcher, "_get",
        lambda path, **kwargs: [] if path.endswith("fundingInfo") else events)
    parsed = fetcher.funding_events("S10USDT", day, fwd._shift(day, 1))
    assert [stamp for stamp, _ in parsed] == [start + 8 * 3_600_000,
                                             start + 16 * 3_600_000,
                                             start + 86_400_000]
    monkeypatch.setattr(
        fetcher, "_get",
        lambda path, **kwargs: [] if path.endswith("fundingInfo") else events[:2])
    with pytest.raises(fwd.RefusedToBook, match="funding coverage"):
        fetcher.funding_events("S10USDT", day, fwd._shift(day, 1))


def test_four_hour_funding_refuses_a_missing_settlement(monkeypatch):
    day = DAYS[63]
    start = fwd._ms(day)
    info = [{"symbol": "S10USDT", "fundingIntervalHours": 4}]
    events = [{"fundingTime": start + hours * 3_600_000,
               "fundingRate": "0.0001"} for hours in (4, 8, 12, 16, 20, 24)]
    fetcher = fwd.RestFetcher()
    monkeypatch.setattr(
        fetcher, "_get",
        lambda path, **kwargs: info if path.endswith("fundingInfo") else events)
    assert len(fetcher.funding_events("S10USDT", day, fwd._shift(day, 1))) == 6

    partial = [event for event in events if event["fundingTime"] != start + 12 * 3_600_000]
    fetcher = fwd.RestFetcher()
    monkeypatch.setattr(
        fetcher, "_get",
        lambda path, **kwargs: info if path.endswith("fundingInfo") else partial)
    with pytest.raises(fwd.RefusedToBook, match="funding coverage"):
        fetcher.funding_events("S10USDT", day, fwd._shift(day, 1))


def test_record_repairs_torn_tail_and_recovers_after_append_before_state(tmp_path):
    fetcher = AuditFetcher()
    root = tmp_path / "store"
    _seed(root, last=DAYS[50])
    # Simulate a completed append followed by process death before state replace.
    state = json.loads((root / "state.json").read_text())
    row = fwd.book_day(fetcher, state, DAYS[50],
                       snapshot=_snapshot(fetcher, DAYS[50]),
                       next_snapshot=_snapshot(fetcher, DAYS[51], close=True))
    line = json.dumps(row, sort_keys=True)
    with (root / "ledger.jsonl").open("wb") as fh:
        fh.write((json.dumps({"day": DAYS[50], "net_bps": 0.0,
                              "adverse_bps": 0.0, "gross_bps": 0.0,
                              "turnover": 0.0, "universe": sorted(fetcher.closes),
                              "weights": {}, "held_after": {}}) + "\n").encode())
        fh.write((line[:-3]).encode())  # torn JSON tail
    now = dt.datetime.combine(dt.date.fromisoformat(DAYS[52]), dt.time(0, 5), tzinfo=dt.UTC)
    assert fwd.record(root, fetcher, today=DAYS[52], now=now) == 1
    rows = fwd._rows(root)
    assert [r["day"] for r in rows] == [DAYS[50], DAYS[51]]
    assert len(rows) == len(set(r["day"] for r in rows)) == 2
    assert (root / "ledger.torn").exists()


def test_fresh_recorder_bootstraps_from_captured_day_only(tmp_path):
    fetcher = AuditFetcher()
    day = DAYS[64]
    root = tmp_path / "fresh"
    at_midnight = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(0, 5),
                                     tzinfo=dt.UTC)
    assert fwd.record(root, fetcher, today=day, now=at_midnight) == 0
    assert json.loads((root / "state.json").read_text())["last_booked"] == day

    # A later scheduled run refreshes the same day's point-in-time membership.
    at_evening = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(18, 0),
                                     tzinfo=dt.UTC)
    assert fwd.record(root, fetcher, today=day, now=at_evening) == 0
    next_day = fwd._shift(day, 1)
    next_midnight = dt.datetime.combine(dt.date.fromisoformat(next_day), dt.time(0, 5),
                                        tzinfo=dt.UTC)
    assert fwd.record(root, fetcher, today=next_day, now=next_midnight) == 0
    assert (root / "universe" / f"{day}.json").exists()
    following_day = fwd._shift(next_day, 1)
    following_midnight = dt.datetime.combine(
        dt.date.fromisoformat(following_day), dt.time(0, 5), tzinfo=dt.UTC)
    assert fwd.record(root, fetcher, today=following_day, now=following_midnight) == 1
    assert [row["day"] for row in fwd._rows(root)] == [next_day]


def test_backfill_refuses_missing_monday_membership_snapshot(tmp_path):
    fetcher = AuditFetcher()
    root = tmp_path / "missing-history"
    root.mkdir()
    (root / "state.json").write_text(json.dumps({
        "last_booked": DAYS[63], "universe": sorted(fetcher.closes),
        "held": {}, "bootstrap_anchor": True}))
    today = DAYS[65]
    now = dt.datetime.combine(dt.date.fromisoformat(today), dt.time(0, 5), tzinfo=dt.UTC)
    with pytest.raises(fwd.RefusedToBook, match="point-in-time universe snapshot unavailable"):
        fwd.record(root, fetcher, today=today, now=now)
    assert not (root / "ledger.jsonl").exists()


def test_record_reconciles_append_before_state_crash_without_duplicate(tmp_path):
    fetcher = AuditFetcher()
    root = tmp_path / "store"
    _seed(root, last=DAYS[50])
    row = {"day": DAYS[51], "weights": {}, "universe": sorted(fetcher.closes),
           "net_bps": 0.0, "adverse_bps": 0.0, "gross_bps": 0.0, "turnover": 0.0}
    (root / "ledger.jsonl").write_text(json.dumps(row, sort_keys=True) + "\n")
    # Stale state models a crash after the ledger append but before state replace.
    assert fwd.record(root, fetcher, today=DAYS[53],
                      now=dt.datetime.combine(dt.date.fromisoformat(DAYS[53]),
                                              dt.time(0, 5), tzinfo=dt.UTC)) == 1
    days = [r["day"] for r in fwd._rows(root)]
    assert days == [DAYS[51], DAYS[52]]
    assert len(days) == len(set(days))


def test_recorder_lock_refuses_concurrent_writer(tmp_path):
    root = tmp_path / "store"
    fetcher = AuditFetcher()
    now = dt.datetime.combine(dt.date.fromisoformat(DAYS[53]), dt.time(0, 5), tzinfo=dt.UTC)
    with fwd._locked(root), pytest.raises(fwd.RefusedToBook, match="lock"):
        fwd.record(root, fetcher, today=DAYS[53], now=now)
    assert not (root / "ledger.jsonl").exists()


def test_record_uses_ledger_as_truth_and_preserves_once_daily(tmp_path):
    fetcher = AuditFetcher()
    root = tmp_path / "store"
    _seed(root, last=DAYS[50])
    now = dt.datetime.combine(dt.date.fromisoformat(DAYS[53]), dt.time(0, 5), tzinfo=dt.UTC)
    assert fwd.record(root, fetcher, today=DAYS[53], now=now) == 2
    assert fwd.record(root, fetcher, today=DAYS[53], now=now) == 0
    rows = fwd._rows(root)
    assert [r["day"] for r in rows] == [DAYS[51], DAYS[52]]
    assert fwd.health(root)["duplicates"] == 0


def test_utc_settlement_boundary_and_daily_job_separation(tmp_path, monkeypatch, capsys):
    before = dt.datetime(2027, 1, 5, 0, 4, 59, tzinfo=dt.UTC)
    after = dt.datetime(2027, 1, 5, 0, 5, 0, tzinfo=dt.UTC)
    assert fwd.today_utc(before) == "2027-01-04"
    assert fwd.today_utc(after) == "2027-01-05"
    fetcher = AuditFetcher()
    with pytest.raises(fwd.RefusedToBook, match="00:05 UTC"):
        fwd.record(tmp_path / "early", fetcher, today="2027-01-05", now=before)
    report = tmp_path / "reports"
    monkeypatch.setattr(fwd, "REPORTS", report)
    fetcher = AuditFetcher()
    _seed(tmp_path / "daily", last=DAYS[50])
    fwd.main(["record", "--root", str(tmp_path / "daily")], fetcher=fetcher,
             now=dt.datetime(2027, 2, 26, 0, 5, tzinfo=dt.UTC))
    assert not report.exists()


def _independent_fwer(c: float, step: float = 0.04) -> float:
    """2D Gaussian quadrature of the three-look Brownian crossing probability."""
    threshold = c * math.sqrt(3.0)  # S_k boundary for OBF z_k=c*sqrt(3/k)
    def pdf(x: float) -> float:
        return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

    def cdf(x: float) -> float:
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    x1_n = math.ceil((threshold + 9.0) / step)
    dx1 = (threshold + 9.0) / x1_n
    survival = 0.0
    for i in range(x1_n):
        x1 = -9.0 + (i + 0.5) * dx1
        upper = threshold - x1
        x2_n = max(1, math.ceil((upper + 9.0) / step))
        dx2 = (upper + 9.0) / x2_n
        inner = sum(pdf(x2) * cdf(threshold - x1 - x2)
                    for j in range(x2_n)
                    for x2 in [-9.0 + (j + 0.5) * dx2])
        survival += pdf(x1) * inner * dx2 * dx1
    return 1.0 - survival


def test_preregistered_obf_boundaries_match_independent_integration():
    assert fwd.LOOKS == (365, 730, 1095)
    assert fwd.OBF_BOUNDS == (2.973, 2.102, 1.717)
    # Solve for c independently from the amendment's equal-information
    # O'Brien-Fleming rule b_k=c*sqrt(3/k), target familywise alpha=.05.
    lo, hi = 1.5, 2.0
    for _ in range(18):
        mid = (lo + hi) / 2
        if _independent_fwer(mid) > 0.05:
            lo = mid
        else:
            hi = mid
    c = (lo + hi) / 2
    recomputed = (c * math.sqrt(3), c * math.sqrt(1.5), c)
    assert all(abs(a - b) < 0.015
               for a, b in zip(recomputed, fwd.OBF_BOUNDS, strict=True))
    alpha_frozen = _independent_fwer(fwd.OBF_BOUNDS[-1])
    assert 0.048 < alpha_frozen <= 0.05


def test_funding_sign_and_cost_are_booked_once_per_leg():
    fetcher = AuditFetcher(n=30)
    day = DAYS[63]
    nxt = fwd._shift(day, 1)
    for closes in fetcher.closes.values():
        closes[day] = closes[nxt] = 100.0
    state = {"universe": sorted(fetcher.closes), "held": {}}
    target = c_family.signal_xsmom(
        fetcher.closes, {}, DAYS, DAYS.index(day), state["universe"])
    long = next(s for s, w in target.items() if w > 0)
    short = next(s for s, w in target.items() if w < 0)
    fetcher.funds[long][nxt] = 0.001
    fetcher.funds[short][nxt] = 0.002

    row = fwd.book_day(fetcher, state, day,
                       snapshot=_snapshot(fetcher, day, include_volume=True),
                       next_snapshot=_snapshot(fetcher, nxt, close=True))

    expected_funding = (target[long] * 0.001 + target[short] * 0.002) * 10_000
    assert row["gross_bps"] == pytest.approx(-expected_funding)
    assert row["turnover"] == pytest.approx(1.0)
    assert row["net_bps"] == pytest.approx(-expected_funding - 9.0)
    assert row["adverse_bps"] == pytest.approx(-expected_funding - 18.0)


def test_ledger_replace_failure_cannot_leave_a_partial_booking(tmp_path, monkeypatch):
    root = tmp_path / "store"
    _seed(root, last=DAYS[50])
    original = fwd.os.replace

    def fail_replace(source, target):
        if str(target).endswith("ledger.jsonl"):
            raise OSError("synthetic crash before ledger swap")
        return original(source, target)

    monkeypatch.setattr(fwd.os, "replace", fail_replace)
    now = dt.datetime.combine(dt.date.fromisoformat(DAYS[52]), dt.time(0, 5), tzinfo=dt.UTC)
    with pytest.raises(OSError, match="synthetic crash"):
        fwd.record(root, AuditFetcher(), today=DAYS[52], now=now)
    assert not (root / "ledger.jsonl").exists()
    assert json.loads((root / "state.json").read_text())["last_booked"] == DAYS[50]


def test_failed_atomic_look_write_leaves_no_report(tmp_path, monkeypatch):
    root, out = tmp_path / "ledger", tmp_path / "reports"
    _ledger(root, 365, mean=0.0)
    original = fwd.os.link

    def fail_link(source, target):
        if str(target).endswith("C2-forward-look1.json"):
            raise OSError("synthetic crash before report swap")
        return original(source, target)

    monkeypatch.setattr(fwd.os, "link", fail_link)
    with pytest.raises(OSError, match="synthetic crash"):
        fwd.score_look(root, out, 1)
    assert not (out / "C2-forward-look1.json").exists()
