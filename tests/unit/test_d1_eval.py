"""D1 forward evaluator: frozen-rule conformance on synthetic forward data.

Every number in this file is synthetic. Nothing here reads the sealed holdout,
real returns or a strategy P&L: the fixtures are generated in a temp directory
from a fixed formula, and the only "market" they describe is an invented one.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import inspect
import json
import math
from pathlib import Path

import numpy as np
import pytest

from cryptobot.research import d1_eval as D
from cryptobot.research import d1_trials

REPO = Path(__file__).resolve().parents[2]
PREREG = REPO / "research/prereg"
MINUTE = D.MIN_MS
DAY = D.DAY_MS
START = D._utc_ms(2026, 10, 18)  # first forward instant, synthetic data only


# --------------------------------------------------------------------------
# Fixtures: a synthetic recorder chunk chain
# --------------------------------------------------------------------------


def _price_record(instant_ms: int, price: float, symbol: str) -> dict:
    return {"type": "kline", "symbol": symbol, "event_ms": instant_ms,
            "exchange_open_ms": instant_ms, "o": f"{price:.10f}",
            "h": f"{price * 1.0001:.10f}", "l": f"{price * 0.9999:.10f}",
            "c": f"{price:.10f}", "v": "1.0"}


def _oi_record(instant_ms: int, value: float, symbol: str) -> dict:
    return {"type": "open_interest", "symbol": symbol, "event_ms": instant_ms,
            "payload": {"openInterest": f"{value:.4f}", "time": instant_ms}}


def _funding_record(instant_ms: int, rate: float, symbol: str) -> dict:
    return {"type": "funding", "symbol": symbol, "event_ms": instant_ms,
            "payload": {"fundingRate": f"{rate:.8f}"}}


def _stream_of(record: dict) -> str:
    kind = record.get("type")
    if kind == "kline":
        return "kline_1m"
    if kind == "agg_trade":
        return "aggTrade"
    if kind == "open_interest":
        return "open_interest"
    if kind == "funding":
        return "funding"
    if kind == "book_ticker":
        return "bookTicker"
    if kind == "kline_1d":
        return "klines_1d"
    return str(kind)


def _write_store(root: Path, chunks: list[list[dict]]) -> Path:
    """Write a manifest + gzip chunks with the recorder's hash chain."""
    (root / "chunks").mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    previous = "genesis"
    for index, records in enumerate(chunks):
        events = [r["event_ms"] for r in records if isinstance(r.get("event_ms"), int)]
        first, last = min(events), max(events)
        stamp = dt.datetime.fromtimestamp(first / 1000, tz=dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"rec-{index:06d}-{stamp}.jsonl.gz"
        payload = ("\n".join(json.dumps(record) for record in records) + "\n").encode()
        blob = gzip.compress(payload)
        digest = hashlib.sha256(blob).hexdigest()
        entry_hash = hashlib.sha256(f"{previous}:{digest}".encode()).hexdigest()
        (root / "chunks" / name).write_bytes(blob)
        entries.append({
            "chunk": f"chunks/{name}",
            "class": "DEV",
            "records": len(records),
            "first_ms": first,
            "last_ms": last,
            "sha256": digest,
            "entry_hash": entry_hash,
            "prev": previous,
            "streams": sorted({_stream_of(record) for record in records}),
        })
        previous = entry_hash
    manifest = {"chain_head": previous, "created_utc": "2026-10-18T00:00:00+00:00",
                "entries": entries}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return root


def _patched_prereg(destination: Path, **substitutions: str) -> Path:
    """Copy the frozen prereg and apply explicit text substitutions.

    The evaluator parses every frozen number out of these files, so a
    substitution only takes effect if the value really comes from the text; a
    hardcoded constant in code would ignore it and these tests would fail.
    """
    destination.mkdir(parents=True, exist_ok=True)
    sources = [*sorted(PREREG.glob("D1-*.md")), PREREG / "SPLIT.md"]
    applied: set[str] = set()
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for key, pair in substitutions.items():
            old_text, new_text = pair.split("=>")
            if old_text in text:
                text = text.replace(old_text, new_text)
                applied.add(key)
        (destination / source.name).write_text(text, encoding="utf-8")
    missing = set(substitutions) - applied
    assert not missing, f"substitutions that matched nothing: {sorted(missing)}"
    return destination


def _market_records(*, symbol: str, days: int, flushes_per_day: int = 3,
                    oi_lag_minutes: int = 0, continuation_minutes: int = 30,
                    continuation_rate: float = -0.0006,
                    with_funding: bool = True) -> list[dict]:
    """A synthetic 1m market: oscillation plus scheduled flushes.

    Bars are emitted only at the instants D1 can look at (the 5-minute grid and
    the ``+1`` minute offset that entry and exit land on), so the fixture stays
    small while remaining exactly readable by the evaluator.
    """
    total = days * 1440
    prices = np.empty(total, dtype=float)
    open_interest = np.empty(total, dtype=float)
    price = 100.0
    oi = 1.0e6
    # (hour, minute) instants: the loop below tests flattened clock pairs, so a
    # set of raw minute counts would never match and no flush would exist.
    flush_minutes = {(2, 0), (10, 0), (18, 0)}
    flush_minutes = set(sorted(flush_minutes)[:flushes_per_day])
    continuing = 0
    for minute in range(total):
        minute_of_day = minute % 1440
        if (minute_of_day // 60, minute_of_day % 60) in flush_minutes:
            # The cascade: a sharp price fall with a simultaneous OI collapse.
            price *= 1.0 - 0.02
            oi *= 0.97
            continuing = continuation_minutes
        else:
            price *= 1.0 + 0.0004 * math.sin(minute / 37.0)
            oi *= 1.0 + 0.0001 * math.cos(minute / 53.0)
            if continuing:
                # The flush keeps going: forced flow is not exhausted after the
                # trigger bar, so a fade keeps losing. This is what the
                # immediate-kill fixture has to contain to test the rule.
                price *= 1.0 + continuation_rate
                oi *= 1.0 - 0.0002
                continuing -= 1
        prices[minute] = price
        open_interest[minute] = oi

    # A flush that keeps going compounds: after a few hundred days the level
    # underflows the 10-decimal record format and every bar would round to zero.
    # Rescaling the whole path by one constant leaves every return, sigma and
    # bps figure identical (they are all ratios) and only moves the level.
    if float(prices.min()) < 1.0:
        prices *= 1.0 / float(prices.min())
    # The OI collapse compounds the same way and its records carry four
    # decimals; a constant rescale keeps every OI change -- and therefore every
    # z_g -- identical while stopping the level at zero.
    if float(open_interest.min()) < 1.0:
        open_interest *= 1.0 / float(open_interest.min())

    shifted = np.empty(total, dtype=float)
    lag = int(oi_lag_minutes)
    shifted[:] = open_interest
    if lag:
        shifted[lag:] = open_interest[:-lag]

    records: list[dict] = []
    for minute in range(total):
        minute_of_day = minute % 1440
        instant = START + minute * MINUTE
        if minute_of_day % 5 == 0:
            records.append(_price_record(instant, float(prices[minute]), symbol))
            records.append(_oi_record(instant, float(shifted[minute]), symbol))
        elif minute_of_day % 5 == 1:
            records.append(_price_record(instant, float(prices[minute]), symbol))
        if with_funding and minute_of_day % 60 == 0 and minute_of_day % 8 == 0:
            records.append(_funding_record(instant, 0.0001, symbol))
    return records


def _daily_klines(symbol: str, first: dt.date, last: dt.date,
                  volume: float = 1.0e9) -> list[dict]:
    """Daily kline records: the universe ranking's only input."""
    records: list[dict] = []
    day = first
    while day <= last:
        stamp = D._utc_ms(day.year, day.month, day.day)
        records.append({"type": "kline_1d", "symbol": symbol, "event_ms": stamp,
                        "exchange_open_ms": stamp,
                        "payload": {"quote_volume": f"{volume:.1f}"}})
        day += dt.timedelta(days=1)
    return records


def _chunks(records: list[dict], per_chunk: int = 4000) -> list[list[dict]]:
    return [records[index:index + per_chunk] for index in range(0, len(records), per_chunk)]


def _series(symbol: str = "AAAUSDT") -> D.SymbolSeries:
    """A tiny hand-built series: known prices, known OI, known funding."""
    item = D.SymbolSeries(symbol=symbol)
    base = D._utc_ms(2026, 10, 25)
    for minute in range(0, 240, 1):
        # Bars exist at every minute here: the reader is what truncates to the
        # instants D1 asks for, and this fixture must answer every lookup.
        item.bar_open[base + minute * MINUTE] = 100.0 + 0.01 * minute
    for step in range(0, 240, 5):
        item.oi[base + step * MINUTE] = 1000.0 + step
    item.funding[base] = 0.0001
    item.first_ms = base
    item.last_ms = base + 240 * MINUTE
    return item


# --------------------------------------------------------------------------
# 1. The frozen rules come out of the preregistration text
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rules() -> D.Rules:
    return D.load_rules(PREREG)


# The frozen constant is the only legal source of a trial count. Tests that need
# the DSR gate to evaluate set it the way R2 will -- by freezing the constant in
# d1_trials next to its amendment -- and never by passing a number to the
# evaluator. ``monkeypatch`` restores ``None`` when the test ends.
FROZEN_TEST_TRIALS = 1000


@pytest.fixture
def frozen_trials(monkeypatch) -> int:
    monkeypatch.setattr(d1_trials, "N_TRIALS", FROZEN_TEST_TRIALS)
    return FROZEN_TEST_TRIALS


def test_rules_are_the_frozen_ones(rules: D.Rules) -> None:
    assert rules.cells == (
        D.Cell(5, 3.0, 15), D.Cell(5, 3.0, 60), D.Cell(5, 4.0, 15),
        D.Cell(5, 4.0, 60), D.Cell(15, 3.0, 15), D.Cell(15, 3.0, 60),
        D.Cell(15, 4.0, 15), D.Cell(15, 4.0, 60),
    )
    assert rules.oi_z_max == -2.0
    assert (rules.sigma_lookback_days, rules.sigma_min_fraction) == (7, 0.70)
    assert (rules.universe_size, rules.universe_min_age_days) == (30, 90)
    assert (rules.metrics_lag_min, rules.entry_offset_min) == (5, 6)
    assert (rules.taker_fee_bps, rules.half_spread_bps) == (5.0, 1.0)
    assert (rules.slippage_base_bps, rules.slippage_shock_coef) == (1.0, 0.05)
    assert rules.funding_hours == (0, 8, 16)
    assert rules.funding_impute_days == 365
    assert rules.stress_multiple == 2
    assert (rules.min_events, rules.min_event_days) == (300, 100)
    assert (rules.bootstrap_resamples, rules.bootstrap_seed) == (5000, 7)
    assert (rules.dsr_min, rules.pbo_max, rules.pbo_partitions) == (0.80, 0.30, 8)
    assert rules.months_positive_fraction == 0.60
    assert rules.month_window == ((2020, 10), (2023, 12))
    assert rules.month_count == 39
    assert rules.dev_years == (2020, 2021, 2022, 2023)
    assert (rules.min_positive_years, rules.year_min_trades) == (3, 30)
    assert rules.concentration_drop == 3
    assert rules.holdout_start_ms == D._utc_ms(2024, 1, 1)
    assert rules.forward_start_ms == D._utc_ms(2026, 10, 18)
    assert len(rules.hashes) >= 3
    assert rules.nominal_sigma_obs(5) == 2016
    assert rules.nominal_sigma_obs(15) == 672
    assert rules.min_sigma_obs(5) == 1412
    assert rules.min_sigma_obs(15) == 471


def test_numbers_come_from_the_text_not_from_code(tmp_path: Path) -> None:
    patched = _patched_prereg(
        tmp_path / "prereg",
        min_events="n >= 300 events=>n >= 301 events",
        universe="take the top N = 30=>take the top N = 12",
        entry="bar starting at T + 6 minutes=>bar starting at T + 7 minutes",
    )
    changed = D.load_rules(patched)
    assert changed.min_events == 301
    assert changed.universe_size == 12
    assert changed.entry_offset_min == 7
    # The same documents, unpatched, still say 300 / 30 / 6.
    assert D.load_rules(PREREG).min_events == 300


def test_missing_frozen_text_is_a_hard_error(tmp_path: Path) -> None:
    patched = _patched_prereg(tmp_path / "prereg", dropped="taker fee 5.0 bps=>taker fee")
    with pytest.raises(D.PreregParseError, match="taker_fee_bps"):
        D.load_rules(patched)
    with pytest.raises(D.PreregParseError, match="no D1 preregistration"):
        D.load_rules(tmp_path / "empty")


# --------------------------------------------------------------------------
# 2. Timestamp convention, sigma windows and the latency rule
# --------------------------------------------------------------------------


def test_trailing_sigma_matches_the_literal_window_rule(rules: D.Rules) -> None:
    rng = np.random.default_rng(11)
    values = rng.normal(0.0, 1.0, 4000)
    for stride in (1, 3):
        count, minimum = 200, 140
        fast = D._rolling_sd(values, stride, count, minimum)
        checked = 0
        for index in range(count * stride, len(values)):
            slow = D._trailing_sd(values, index, stride, count, minimum)
            if slow is None:
                assert np.isnan(fast[index])
                continue
            assert fast[index] == pytest.approx(slow, rel=1e-10, abs=1e-12)
            checked += 1
        assert checked > 100
    # The current window is never inside its own sigma: nothing is defined
    # before `count` complete non-overlapping windows exist.
    assert np.all(np.isnan(D._rolling_sd(values, 1, 200, 140)[:200]))


def test_entry_bar_is_t_plus_6_after_metrics_availability_lag(rules: D.Rules) -> None:
    item = _series()
    grid = D._utc_ms(2026, 10, 25) + 120 * MINUTE
    # P(T+5m) must never be the entry price: make it visibly different.
    item.bar_open[grid + 5 * MINUTE] = 999.0
    event = D.Event(cell=D.Cell(5, 3.0, 15), symbol=item.symbol, grid_ms=grid,
                    direction=1, shock_bps=200.0)
    trades, dropped = D.simulate(item, [event], event.cell, rules,
                                 window_end_ms=item.last_ms)
    assert dropped["no_entry_bar"] == 0
    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_ms == grid + rules.entry_offset_min * MINUTE
    assert trade.entry_ms - grid == 6 * MINUTE
    assert trade.entry_px == pytest.approx(item.bar_open[grid + 6 * MINUTE])
    assert trade.exit_ms == trade.entry_ms + event.cell.h * MINUTE


def test_metrics_shift_lookahead_is_detected(tmp_path: Path) -> None:
    """OI stamped after T must not enter the signal for T.

    The synthetic flush puts the price shock at grid instant T and the OI
    collapse 5 minutes later.  Under the frozen convention (the row stamped T
    is the snapshot at T) that instant has no OI change and therefore no event;
    shifting the OI series one 5-minute row -- the mutation the prereg names --
    makes the same instant look like an event.  The sigma lookback is shortened
    in a temp copy of the prereg so the fixture stays small; that value is
    parsed, so this also re-proves the rule is read from the text.
    """
    patched = _patched_prereg(
        tmp_path / "prereg",
        sigma="covering the trailing 7 days=>covering the trailing 2 days",
    )
    quick = D.load_rules(patched)
    assert quick.sigma_lookback_days == 2

    base = D._utc_ms(2026, 10, 25)
    minutes = 3 * 1440 + 600
    flush = 3 * 1440 + 60
    item = D.SymbolSeries(symbol="AAAUSDT")
    for minute in range(minutes):
        price = 100.0 * (1.0 + 0.0004 * math.sin(minute / 37.0))
        if minute >= flush:
            price *= 0.98
        item.bar_open[base + minute * MINUTE] = price
    for minute in range(0, minutes, 5):
        value = 1.0e6 * (1.0 + 0.0001 * math.cos(minute / 53.0))
        if minute >= flush + 5:
            value *= 0.97
        item.oi[base + minute * MINUTE] = value
    item.first_ms = base
    item.last_ms = base + (minutes - 1) * MINUTE

    cell = D.Cell(5, 3.0, 15)
    honest = [event for event in D.detect_events(item, cell, quick,
                                                 window_start_ms=base,
                                                 window_end_ms=item.last_ms)
              if event.grid_ms == base + flush * MINUTE]
    assert honest == []

    mutant = D.SymbolSeries(
        symbol=item.symbol,
        bar_open=dict(item.bar_open),
        oi={stamp - 5 * MINUTE: value for stamp, value in item.oi.items()},
        first_ms=item.first_ms,
        last_ms=item.last_ms,
    )
    mutated = [event for event in D.detect_events(mutant, cell, quick,
                                                  window_start_ms=base,
                                                  window_end_ms=mutant.last_ms)
               if event.grid_ms == base + flush * MINUTE]
    assert mutated, "shifting the OI series one 5-minute row must create the event"


def test_pending_signal_overlap_is_checked_at_entry(rules: D.Rules) -> None:
    item = _series()
    cell = D.Cell(5, 3.0, 60)
    base = D._utc_ms(2026, 10, 25) + 60 * MINUTE
    events = [
        D.Event(cell=cell, symbol=item.symbol, grid_ms=base, direction=1, shock_bps=200.0),
        # entry at +16m lands inside the first position (exit at +66m)
        D.Event(cell=cell, symbol=item.symbol, grid_ms=base + 10 * MINUTE,
                direction=1, shock_bps=200.0),
        # entry at +76m is after that exit, so it is allowed
        D.Event(cell=cell, symbol=item.symbol, grid_ms=base + 70 * MINUTE,
                direction=1, shock_bps=200.0),
    ]
    trades, dropped = D.simulate(item, events, cell, rules, window_end_ms=item.last_ms)
    assert [t.entry_ms - base for t in trades] == [6 * MINUTE, 76 * MINUTE]
    assert dropped["overlap"] == 1


def test_no_exit_at_or_after_dev_cutoff(rules: D.Rules) -> None:
    """Amendment 1 section 2: an entry is forbidden when its scheduled exit
    reaches the cutoff, so the trade is not booked at all -- and when the exit
    bar is merely missing inside the window, the exit moves to the next bar."""
    item = _series()
    cell = D.Cell(5, 3.0, 60)
    base = min(item.bar_open)
    cutoff = base + 200 * MINUTE
    early = D.Event(cell=cell, symbol=item.symbol, grid_ms=base + 40 * MINUTE,
                    direction=1, shock_bps=200.0)
    late = D.Event(cell=cell, symbol=item.symbol, grid_ms=base + 140 * MINUTE,
                   direction=1, shock_bps=200.0)
    # early: entry +46m, scheduled exit +106m, both before the cutoff -> booked
    # late:  entry +146m, scheduled exit +206m >= cutoff -> forbidden
    trades, dropped = D.simulate(item, [early, late], cell, rules,
                                 window_end_ms=cutoff)
    assert [trade.entry_ms for trade in trades] == [base + 46 * MINUTE]
    assert dropped["past_data_end"] == 1
    assert all(trade.exit_ms < cutoff for trade in trades)
    assert trades[0].forced_exit_data_end is False


def test_missing_exit_bar_closes_at_the_last_available_bar(rules: D.Rules) -> None:
    """If the scheduled exit bar is missing, the rule moves the exit inside the
    window and flags the truncation instead of using a bar at or past the end."""
    item = _series()
    cell = D.Cell(5, 3.0, 60)
    last_bar = max(item.bar_open)
    event = D.Event(cell=cell, symbol=item.symbol, grid_ms=last_bar - 30 * MINUTE,
                    direction=1, shock_bps=200.0)
    trades, _dropped = D.simulate(item, [event], cell, rules,
                                  window_end_ms=last_bar + 37 * MINUTE)
    assert len(trades) == 1
    trade = trades[0]
    assert trade.forced_exit_data_end is True
    assert trade.exit_ms == last_bar
    assert trade.exit_ms < last_bar + 37 * MINUTE


# --------------------------------------------------------------------------
# 3. Costs and funding stress
# --------------------------------------------------------------------------


def test_cost_stress_doubles_every_component(rules: D.Rules) -> None:
    # Prereg identity: round trip 1x = 14.0 + 0.1*|r_W| bps.
    assert D.round_trip_cost_bps(75.0, rules) == pytest.approx(14.0 + 0.1 * 75.0)
    assert D.round_trip_cost_bps(75.0, rules, stress=True) == pytest.approx(
        2.0 * (14.0 + 0.1 * 75.0))
    assert D.round_trip_cost_bps(0.0, rules) == pytest.approx(14.0)


def test_funding_is_signed_and_stressed(rules: D.Rules) -> None:
    item = _series()
    entry = D._utc_ms(2026, 10, 25) + 60 * MINUTE
    exit_ms = entry + 16 * 3600 * 1000  # crosses 08:00 and 16:00
    item.funding = {D._utc_ms(2026, 10, 25, 8): 0.0002,
                    D._utc_ms(2026, 10, 25, 16): 0.0002}
    item.first_ms = D._utc_ms(2026, 10, 25, 0)
    long_cost, long_stress, imputed, eligible = D._funding_cost(
        item, entry, exit_ms, +1, rules)
    short_cost, short_stress, _i2, _e2 = D._funding_cost(
        item, entry, exit_ms, -1, rules)
    assert eligible is True and imputed is False
    assert long_cost == pytest.approx(2 * 0.0002 * 1e4)
    assert long_stress == pytest.approx(2 * 2 * 0.0002 * 1e4)
    assert short_cost == pytest.approx(-2 * 0.0002 * 1e4)
    # A credit is set to zero under stress, never doubled.
    assert short_stress == pytest.approx(0.0)


def test_missing_funding_is_not_booked_as_zero(rules: D.Rules) -> None:
    item = _series()
    entry = D._utc_ms(2026, 10, 25) + 60 * MINUTE
    exit_ms = entry + 8 * 3600 * 1000
    item.first_ms = D._utc_ms(2026, 10, 25)  # no full trailing year available
    cost, _stress, imputed, eligible = D._funding_cost(item, entry, exit_ms, +1, rules)
    assert imputed is True
    assert eligible is False
    assert cost == 0.0


def _long_barfill_short_funding() -> tuple[D.SymbolSeries, int, int]:
    """Bars reach back a year, funding starts ten days before entry."""
    item = D.SymbolSeries(symbol="AAAUSDT")
    base = D._utc_ms(2026, 10, 18)
    entry = base + 400 * DAY  # 400 days of bars, so first_ms looks like a year
    item.bar_open = {base: 100.0, entry: 100.0, entry + 8 * D.HOUR_MS: 100.0}
    item.oi = {entry: 1000.0}
    item.funding = {entry - 10 * DAY: 0.0003}  # only ten days of settlements
    item.first_ms = base  # the bar/OI clock, not the funding clock
    item.last_ms = entry + DAY
    return item, entry, entry + 8 * D.HOUR_MS


def test_funding_eligibility_uses_the_funding_clock_not_the_bar_clock(
        rules: D.Rules) -> None:
    """Prereg: without a full trailing year of *funding* the symbol is
    ineligible at entry. A year of klines plus weeks of funding is not one."""
    item, entry, exit_ms = _long_barfill_short_funding()
    assert item.first_ms <= entry - 365 * DAY  # the masked, pre-fix reading
    assert item.funding_first_ms > entry - 365 * DAY
    cost, stress, imputed, eligible = D._funding_cost(item, entry, exit_ms, +1, rules)
    assert imputed is True
    assert eligible is False, "a short funding history must not impute a year"
    assert (cost, stress) == (0.0, 0.0)


def test_mutation_funding_eligibility_on_the_bar_clock_is_caught(
        rules: D.Rules) -> None:
    """Mutation of the funding guard: test against ``first_ms`` (bars, OI and
    funding together) and the short funding history wrongly becomes eligible."""
    mutant = _mutated_module(
        "            if not item.funding_first_ms or item.funding_first_ms > span_start:",
        "            if not item.first_ms or item.first_ms > span_start:")
    item, entry, exit_ms = _long_barfill_short_funding()
    _cost, _stress, imputed, eligible = mutant._funding_cost(
        item, entry, exit_ms, +1, rules)
    assert imputed is True
    assert eligible is True, "the mutated rule is what the guard test forbids"


# --------------------------------------------------------------------------
# 4. Structural holdout refusal
# --------------------------------------------------------------------------


def _streams_only_store(tmp_path: Path) -> Path:
    """What the recorder carries today: book, depth, OI and the premium index."""
    base = D._utc_ms(2026, 10, 25, 7)
    records = [
        {"type": "book_ticker", "symbol": "BTCUSDT", "event_ms": base + i * 1000,
         "bid": "100.0", "ask": "100.1", "stream": "btcusdt@bookTicker"}
        for i in range(60)
    ] + [
        {"type": "open_interest", "symbol": "BTCUSDT", "event_ms": base + i * MINUTE,
         "payload": {"openInterest": "1000.0"}} for i in range(30)
    ] + [
        {"type": "premium_index", "symbol": "BTCUSDT", "event_ms": base + i * MINUTE,
         "payload": {"lastFundingRate": "0.0001", "markPrice": "100.0"}}
        for i in range(30)
    ]
    return _write_store(tmp_path / "recorder", [records])


def test_sealed_holdout_path_is_refused(tmp_path: Path, rules: D.Rules) -> None:
    sealed = tmp_path / "data/lake/holdout_raw"
    sealed.mkdir(parents=True)
    (sealed / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(D.HoldoutRefusal):
        D.scan_store(sealed, rules)
    with pytest.raises(D.HoldoutRefusal):
        D.assert_not_sealed_path(sealed / "BTCUSDT-1m-2024-06.zip")


def test_chunk_window_inside_the_holdout_is_refused(tmp_path: Path, rules: D.Rules) -> None:
    sealed_instant = D._utc_ms(2024, 6, 1)
    root = _write_store(tmp_path / "recorder", [[
        {"type": "kline", "symbol": "BTCUSDT", "event_ms": sealed_instant,
         "exchange_open_ms": sealed_instant, "o": "100.0"},
        {"type": "kline", "symbol": "BTCUSDT", "event_ms": sealed_instant + 60_000,
         "exchange_open_ms": sealed_instant + 60_000, "o": "101.0"},
    ]])
    with pytest.raises(D.HoldoutRefusal):
        D.scan_store(root, rules)


def test_record_stamped_in_the_holdout_is_refused(tmp_path: Path,
                                                  rules: D.Rules) -> None:
    """Defence in depth: even a chunk that declares a forward window may not
    carry a holdout-dated record, because the guard is per record too."""
    forward = D._utc_ms(2026, 10, 25, 7)
    root = _write_store(tmp_path / "recorder", [[
        {"type": "open_interest", "symbol": "BTCUSDT", "event_ms": forward,
         "payload": {"openInterest": "1000.0"}},
        {"type": "open_interest", "symbol": "BTCUSDT",
         "event_ms": D._utc_ms(2025, 1, 5), "payload": {"openInterest": "1000.0"}},
    ]])
    stored = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    declared = stored["entries"][0]
    digest = hashlib.sha256((root / declared["chunk"]).read_bytes()).hexdigest()
    entry = D.ChunkEntry(
        path=root / declared["chunk"], first_ms=forward,
        last_ms=forward + 30 * MINUTE, records=2, streams=("open_interest",),
        sha256=digest, entry_hash="h", prev="genesis", stamp_ms=forward,
    )
    store = D.Store(root=root, entries=[entry], chain_head="h", created_utc=None)
    with pytest.raises(D.HoldoutRefusal, match="inside the sealed holdout"):
        list(D.read_records(store, [entry], rules))


def test_window_starting_before_forward_is_refused(rules: D.Rules) -> None:
    with pytest.raises(D.HoldoutRefusal):
        D.assert_forward_window(D._utc_ms(2024, 3, 1), D._utc_ms(2026, 10, 26), rules)
    with pytest.raises(D.HoldoutRefusal):
        D.assert_forward_window(D._utc_ms(2020, 1, 1), D._utc_ms(2026, 10, 26), rules)
    assert D.assert_forward_window(D._utc_ms(2026, 10, 20), D._utc_ms(2026, 10, 26),
                                   rules) == (D._utc_ms(2026, 10, 20),
                                              D._utc_ms(2026, 10, 26))


# --------------------------------------------------------------------------
# 5. INSUFFICIENT FORWARD DATA, with the exact shortfall
# --------------------------------------------------------------------------


def test_insufficient_forward_data_names_every_missing_stream(tmp_path: Path) -> None:
    root = _streams_only_store(tmp_path)
    doc = D.evaluate_forward(root)
    assert doc["verdict"] == "INSUFFICIENT_FORWARD_DATA"
    assert doc["shortfall_stage"] == "streams"
    missing = {item["missing"] for item in doc["stream_shortfalls"]}
    assert missing == {"price_bars_1m", "funding_settlements", "universe_daily_klines"}
    text = D.render(doc)
    assert text.splitlines()[0] == "INSUFFICIENT FORWARD DATA"
    assert "fix: record the aggTrade stream" in text
    assert "premium index's next-rate estimate is not a settlement" in text


def test_universe_shortfall_blocks_a_two_symbol_sample(tmp_path: Path) -> None:
    records = []
    for symbol in ("AAAUSDT", "BBBUSDT"):
        records.extend(_market_records(symbol=symbol, days=2))
        records.append({"type": "kline_1d", "symbol": symbol, "event_ms": START,
                        "payload": {"quote_volume": "1000000000.0"}})
    root = _write_store(tmp_path / "recorder", _chunks(records))
    doc = D.evaluate_forward(root)
    assert doc["verdict"] == "INSUFFICIENT_FORWARD_DATA"
    assert doc["shortfall_stage"] == "universe"
    detail = doc["stream_shortfalls"][0]["detail"]
    assert "0 of 30 ranked symbols" in detail
    assert "2026-09 quote volume" in detail
    assert "every day of 2026-09 required" in detail


def test_cli_reports_the_same_shortfall(tmp_path: Path, capsys) -> None:
    root = _streams_only_store(tmp_path)
    assert D.main(["--recorder-root", str(root)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "INSUFFICIENT FORWARD DATA"
    assert D.main(["--recorder-root", str(root),
                   "--start", "2024-06-01T00:00:00Z"]) == 2
    assert "refused" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 6. Gates, DSR and the immediate-kill rule
# --------------------------------------------------------------------------


def _trade(cell: D.Cell, symbol: str, day_index: int, net_1x: float,
           funding_1x: float = 0.0) -> D.Trade:
    cost_1x = 14.0
    cost_2x = 15.0
    gross = net_1x + cost_1x + funding_1x
    return D.Trade(
        cell=cell, symbol=symbol, direction=1,
        entry_ms=START + day_index * DAY + 12 * 3600 * 1000,
        exit_ms=START + day_index * DAY + 13 * 3600 * 1000,
        entry_px=100.0, exit_px=100.0, gross_bps=gross,
        cost_1x_bps=cost_1x, cost_2x_bps=cost_2x,
        funding_1x_bps=funding_1x, funding_2x_bps=funding_1x,
        net_1x_bps=net_1x, net_2x_bps=gross - cost_2x - funding_1x,
        imputed_funding=False, forced_exit_data_end=False,
    )


def _synthetic_cells(rules: D.Rules, *, days: int = 220) -> dict[D.Cell, list[D.Trade]]:
    """A synthetic trade set with a known ordering across the eight cells."""
    rng = np.random.default_rng(3)
    symbols = [f"S{index}USDT" for index in range(6)]
    trades: dict[D.Cell, list[D.Trade]] = {}
    for rank, cell in enumerate(rules.cells):
        drift = 4.0 - 0.3 * rank
        rows: list[D.Trade] = []
        for day_index in range(days):
            for slot in range(2):
                net = float(drift + rng.normal(0.0, 0.5))
                rows.append(_trade(cell, symbols[(day_index + slot) % len(symbols)],
                                   day_index, net))
        trades[cell] = rows
    return trades


def test_known_answer_gates_and_verdict(rules: D.Rules, frozen_trials: int) -> None:
    trades = _synthetic_cells(rules)
    calendar = sorted({trade.entry_day for rows in trades.values() for trade in rows})
    doc = D.evaluate_cells(trades, rules, n_trials=frozen_trials,
                           calendar_days=calendar)
    gates = {item["gate"]: item for item in doc["gates"]}
    assert doc["verdict"] == "FAIL_DEV"
    assert doc["immediate_kill"]["fired"] is False
    assert gates[1]["status"] == "pass"
    assert gates[2]["status"] == "pass"
    assert gates[3]["status"] == "pass"
    assert gates[4]["status"] == "pass"
    assert gates[5]["status"] == "pass"
    assert gates[8]["status"] == "pass"
    # Gates 6 and 7 are frozen to the DEV calendar and a forward window cannot
    # cover it: that is a known, reported outcome, not an accident.
    assert gates[6]["status"] == "fail"
    assert "0/39 frozen-calendar months positive" in gates[6]["detail"]
    assert gates[7]["status"] == "fail"
    assert gates[5]["pbo"] <= rules.pbo_max
    assert gates[4]["dsr"] >= rules.dsr_min
    assert doc["selection"]["selected_cell"] == str(rules.cells[0])


def test_dsr_is_fail_closed_without_a_frozen_trial_count(rules: D.Rules) -> None:
    trades = _synthetic_cells(rules)
    calendar = sorted({trade.entry_day for rows in trades.values() for trade in rows})
    doc = D.evaluate_cells(trades, rules, n_trials=None,
                           n_trials_problem="trial count not frozen: test",
                           calendar_days=calendar)
    gates = {item["gate"]: item for item in doc["gates"]}
    assert gates[4]["status"] == "not_evaluable"
    assert gates[4]["dsr"] is None
    assert "trial count not frozen: test" in gates[4]["detail"]
    assert doc["verdict"] != "PASS_DEV"


def test_immediate_kill_when_no_cell_covers_cost(rules: D.Rules) -> None:
    rng = np.random.default_rng(5)
    trades: dict[D.Cell, list[D.Trade]] = {}
    for cell in rules.cells:
        trades[cell] = [_trade(cell, "AAAUSDT", day, float(-5.0 + rng.normal(0, 0.5)))
                        for day in range(120)]
    doc = D.evaluate_cells(trades, rules, n_trials=None)
    assert doc["verdict"] == "KILL"
    assert doc["immediate_kill"]["fired"] is True
    margin = doc["immediate_kill"]["per_cell"][str(rules.cells[0])]
    assert margin["gross_bps"] - margin["all_in_cost_1x_bps"] < 0
    assert doc["gates"] == []  # no further gate is evaluated


def test_one_covering_cell_stops_the_kill(rules: D.Rules) -> None:
    trades: dict[D.Cell, list[D.Trade]] = {
        cell: [_trade(cell, "AAAUSDT", day, -5.0) for day in range(120)]
        for cell in rules.cells
    }
    good = rules.cells[0]
    trades[good] = [_trade(good, "AAAUSDT", day, 20.0) for day in range(120)]
    doc = D.evaluate_cells(trades, rules, n_trials=None)
    assert doc["immediate_kill"]["fired"] is False
    assert doc["verdict"] != "KILL"


def test_dsr_intermediates_match_the_frozen_formula(rules: D.Rules) -> None:
    # SR is the selected cell's own unannualised day Sharpe, so the fixture
    # keeps the passed SR and the day series consistent.
    day_values = [1.0, -0.5, 0.9, -0.2, 1.4, 0.3, -0.8, 0.6, 1.1, -0.1,
                  0.7, -0.4, 1.2, 0.2, -0.6, 0.8, 0.4, -0.3, 1.0, 0.5]
    series = np.array(day_values)
    sr = float(series.mean() / series.std(ddof=1))
    cell_srs = {cell: 0.10 * (index + 1) for index, cell in enumerate(rules.cells)}
    selected = rules.cells[-1]
    cell_srs[selected] = sr
    result = D.deflated_sharpe(sr, cell_srs, day_values, 1000)

    srs = np.array(list(cell_srs.values()))
    variance = float(np.var(srs, ddof=1))
    gamma = 0.5772156649
    normal = __import__("statistics").NormalDist()
    sr0 = math.sqrt(variance) * (
        (1 - gamma) * normal.inv_cdf(1 - 1 / 1000)
        + gamma * normal.inv_cdf(1 - 1 / (1000 * math.e)))
    values = np.array(day_values)
    skew = float(np.mean((values - values.mean()) ** 3) / values.std(ddof=1) ** 3)
    kurt = float(np.mean((values - values.mean()) ** 4) / values.std(ddof=0) ** 4)
    denominator = math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2)
    expected = normal.cdf((sr - sr0) * math.sqrt(len(day_values) - 1) / denominator)

    assert result["V"] == pytest.approx(variance)
    assert result["SR0"] == pytest.approx(sr0)
    assert result["n_days"] == 20
    assert result["skew"] == pytest.approx(skew)
    assert result["kurtosis"] == pytest.approx(kurt)
    assert result["DSR"] == pytest.approx(expected)
    # A larger trial count can only raise SR0 and lower the DSR.
    assert D.deflated_sharpe(sr, cell_srs, day_values, 5000)["DSR"] < result["DSR"]


def test_pbo_is_zero_when_the_same_cell_always_wins(rules: D.Rules) -> None:
    days = 200
    daily = {}
    for rank, cell in enumerate(rules.cells):
        level = 5.0 - 0.1 * rank
        daily[cell] = [level + (0.01 if index % 2 else -0.01) for index in range(days)]
    assert D.pbo_cscv(daily, rules)["PBO"] == pytest.approx(0.0, abs=0.0)
    choppy = {cell: [float(value) * (1 if index % 3 else -1)
                     for index, value in enumerate(values)]
              for cell, values in daily.items()}
    assert 0.0 <= D.pbo_cscv(choppy, rules)["PBO"] <= 1.0


# --------------------------------------------------------------------------
# 7. Trial count: one constant, fail-closed
# --------------------------------------------------------------------------


def test_trial_count_is_refused_without_the_amendment(tmp_path: Path) -> None:
    value, problem = d1_trials.trial_count_ready(tmp_path)
    assert value is None
    assert d1_trials.N_TRIALS_AMENDMENT in problem
    assert "N_TRIALS is unset" in problem
    assert d1_trials.N_TRIALS is None  # the shipped constant must stay unset


def test_trial_count_refuses_when_only_one_half_is_present(tmp_path: Path,
                                                           monkeypatch) -> None:
    value, problem = d1_trials.trial_count_ready(tmp_path)
    assert value is None
    monkeypatch.setattr(d1_trials, "N_TRIALS", 990)
    value, problem = d1_trials.trial_count_ready(tmp_path)
    assert value is None and "is missing" in problem
    monkeypatch.setattr(d1_trials, "N_TRIALS", None)
    amendment = tmp_path / d1_trials.N_TRIALS_AMENDMENT
    amendment.parent.mkdir(parents=True, exist_ok=True)
    amendment.write_text("frozen\n", encoding="utf-8")
    value, problem = d1_trials.trial_count_ready(tmp_path)
    assert value is None and "N_TRIALS is unset" in problem
    monkeypatch.setattr(d1_trials, "N_TRIALS", 990)
    value, problem = d1_trials.trial_count_ready(tmp_path)
    assert (value, problem) == (990, None)


# Numbers a reader might be tempted to hand the DSR gate. Amendment 3 names
# them and forbids each one as N_TRIALS: they are a documented-opportunity
# subtotal (1406), a rejected proposed bound (1187), and two retracted floors
# (470, 442). None of them may appear as a code constant, so no substitution can
# happen without this test failing first.
FORBIDDEN_TRIAL_COUNTS = (1406, 1187, 470, 442)


def test_amendment_3_is_bound_and_every_candidate_number_is_absent() -> None:
    """A3 is the sole source for N_TRIALS, and it says None. Check both halves."""
    amendment = REPO / d1_trials.N_TRIALS_AMENDMENT
    assert amendment.is_file(), "amendment 3 must be in the frozen prereg set"
    text = amendment.read_text(encoding="utf-8")
    assert "`N_TRIALS` remains `None`" in text
    assert "must not be used by the evaluator" in text
    assert "cannot replace `None`" in text
    # The parser binds every D1 document in the directory, A3 included: a
    # rebase that dropped it would change the hash set, not silently pass.
    assert amendment.name in D.load_rules(PREREG).hashes
    # Fail-closed today, with the amending file present but holding no number.
    assert d1_trials.N_TRIALS is None
    value, problem = d1_trials.trial_count_ready(REPO)
    assert value is None
    assert problem is not None and d1_trials.N_TRIALS_AMENDMENT in problem
    # No source file a user can run carries any of them as a substitute, not
    # only the package: a helper script is just as much a place to hide one.
    scanned = [(REPO / area).rglob("*.py") for area in ("src", "tools", "scripts")]
    for path in sorted(path for files in scanned for path in files):
        body = path.read_text(encoding="utf-8")
        for number in FORBIDDEN_TRIAL_COUNTS:
            assert str(number) not in body, f"{path} carries {number}"


def _dev_calendar_trades(rules: D.Rules) -> dict[D.Cell, list[D.Trade]]:
    """A PASS-shaped synthetic set on the frozen DEV calendar.

    Every gate that can pass on DEV passes: the ranking across cells is stable,
    every one of the 39 frozen months and all four DEV years carry positive
    trades. Gates 6 and 7 are the frozen DEV calendar itself, so this is the
    only shape in which a D1 PASS is reachable at all -- which makes it the
    right fixture for proving that an unfrozen trial count blocks the PASS.
    """
    rng = np.random.default_rng(17)
    start = dt.date(2020, 10, 1)
    end = dt.date(2023, 12, 31)
    days = [start + dt.timedelta(days=offset)
            for offset in range((end - start).days + 1)]
    trades: dict[D.Cell, list[D.Trade]] = {}
    for rank, cell in enumerate(rules.cells):
        drift = 4.0 - 0.3 * rank
        rows: list[D.Trade] = []
        for index, day in enumerate(days):
            net = float(drift + rng.normal(0.0, 0.5))
            entry = D._utc_ms(day.year, day.month, day.day, 12)
            cost_1x, cost_2x = 14.0, 15.0
            rows.append(D.Trade(
                cell=cell, symbol=f"S{index % 6}USDT", direction=1,
                entry_ms=entry, exit_ms=entry + 3600 * 1000,
                entry_px=100.0, exit_px=100.0, gross_bps=net + cost_1x,
                cost_1x_bps=cost_1x, cost_2x_bps=cost_2x,
                funding_1x_bps=0.0, funding_2x_bps=0.0,
                net_1x_bps=net, net_2x_bps=net + cost_1x - cost_2x,
                imputed_funding=False, forced_exit_data_end=False,
            ))
        trades[cell] = rows
    return trades


def test_pass_is_impossible_while_the_trial_count_is_unset(rules: D.Rules,
                                                           frozen_trials: int) -> None:
    trades = _dev_calendar_trades(rules)
    calendar = sorted({trade.entry_day for rows in trades.values() for trade in rows})

    # With a number the fixture is a clean PASS: the guard below is the only
    # thing standing between it and a PASS_DEV verdict.
    frozen = D.evaluate_cells(trades, rules, n_trials=frozen_trials,
                              calendar_days=calendar)
    assert frozen["verdict"] == "PASS_DEV"
    assert {item["gate"]: item["status"] for item in frozen["gates"]}[4] == "pass"

    # Unset: no DSR number, gate 4 not evaluable, and no PASS of any spelling.
    blocked = D.evaluate_cells(trades, rules, n_trials=None,
                               n_trials_problem="trial count not frozen: test",
                               calendar_days=calendar)
    gate4 = {item["gate"]: item for item in blocked["gates"]}[4]
    assert gate4["status"] == "not_evaluable"
    assert gate4["dsr"] is None
    assert blocked["verdict"] == "BLOCKED"
    assert "PASS" not in blocked["verdict"]
    rendered = D.render(blocked)
    assert "PASS" not in rendered.splitlines()[0]
    assert "no PASS is possible" in rendered


# --------------------------------------------------------------------------
# 7b. The frozen monthly universe, the holdout gaps, and the mutation guards
# --------------------------------------------------------------------------


def _universe_series() -> dict[str, D.SymbolSeries]:
    """Four synthetic symbols whose ranking is deliberately unambiguous.

    AAA has enormous *earlier* volume and almost none in September; BBB and CCC
    carry the September volume; CCC stops trading on 5 October (delisted
    mid-month); DDD has only September, so it cannot satisfy the 90-day age rule
    however much volume it carries. Series are built directly because the daily
    klines of September 2026 sit before the forward window and are therefore not
    something the evaluator may read from the recorder.
    """
    def series(symbol: str, days: dict[str, float]) -> D.SymbolSeries:
        return D.SymbolSeries(symbol=symbol, daily_quote_volume=days)

    def month_days(year: int, month: int) -> list[str]:
        return D._month_days(year, month)

    june_to_august = (month_days(2026, 6) + month_days(2026, 7) + month_days(2026, 8))
    september = month_days(2026, 9)
    october_november = month_days(2026, 10) + month_days(2026, 11)
    return {
        "AAAUSDT": series("AAAUSDT", {**{day: 1.0e12 for day in june_to_august},
                                      **{day: 1.0 for day in september},
                                      **{day: 1.0 for day in october_november}}),
        "BBBUSDT": series("BBBUSDT", {**{day: 1.0 for day in june_to_august},
                                      **{day: 100.0 for day in september},
                                      **{day: 100.0 for day in october_november}}),
        "CCCUSDT": series("CCCUSDT", {**{day: 1.0 for day in june_to_august},
                                      **{day: 50.0 for day in september},
                                      **{day: 50.0 for day in month_days(2026, 10)[:5]}}),
        "DDDUSDT": series("DDDUSDT", {day: 1.0e9 for day in september}),
    }


def test_monthly_universe_uses_prior_dev_quote_volume_and_delisted_candidates() -> None:
    """Amendment 1 section 5 guard: prior-month volume, not lifetime volume, and
    a delisted candidate stays in the ranking until its data ends."""
    import tempfile

    rules = D.load_rules(_patched_prereg(
        Path(tempfile.mkdtemp(dir="/tmp")) / "prereg",
        universe="take the top N = 30=>take the top N = 2"))
    assert rules.universe_size == 2

    rankings = D.monthly_rankings(_universe_series(), rules, START, START + 60 * DAY)
    october = rankings["2026-10"]
    assert october.prior_month == "2026-09"
    # BBB (100/day) then CCC (50/day) by September volume. AAA carries 1e12 a
    # day for three months and is still excluded: lifetime volume is not the
    # rule. DDD is nine digits a day in September and is excluded by age.
    assert october.ranked == ("BBBUSDT", "CCCUSDT")
    assert "AAAUSDT" not in october.ranked
    assert "DDDUSDT" not in october.ranked
    assert october.candidates == 4
    assert october.age_qualified == 3
    # CCC was delisted on 5 October: it stays for October and is gone in
    # November, which ranks on a month CCC does not cover.
    assert "CCCUSDT" in rankings["2026-10"].ranked
    assert "CCCUSDT" not in rankings["2026-11"].ranked
    assert rankings["2026-11"].ranked == ("BBBUSDT", "AAAUSDT")
    # Active at 00:06 UTC on the second calendar day, never on the first.
    assert october.active_from_ms == D._utc_ms(2026, 10, 2) + 6 * MINUTE


def test_universe_months_without_a_full_previous_month_take_no_signals() -> None:
    """The first forward month cannot be ranked, and that is the rule working:
    the window is evaluable only once some month has a complete M-1."""
    import tempfile

    rules = D.load_rules(_patched_prereg(
        Path(tempfile.mkdtemp(dir="/tmp")) / "prereg",
        universe="take the top N = 30=>take the top N = 2"))
    series = _universe_series()
    # Forward data only: nothing before the forward start is readable, so the
    # first month has no previous month to rank on.
    forward_only = {
        symbol: D.SymbolSeries(
            symbol=symbol,
            daily_quote_volume={day: volume for day, volume
                                in item.daily_quote_volume.items()
                                if day >= "2026-10-18"})
        for symbol, item in series.items()
    }
    narrow = D.monthly_rankings(forward_only, rules, START, START + 15 * DAY)
    assert D.complete_rankings(narrow, rules) == {}
    problem = D.universe_shortfall(narrow, rules, START)
    assert problem is not None
    assert "ranked symbols from" in problem.detail
    # Once a whole forward month exists, November ranks on October and the
    # earlier unranked month simply takes no signals.
    wide = D.monthly_rankings(series, rules, START, START + 90 * DAY)
    assert "2026-11" in D.complete_rankings(wide, rules)
    assert D.universe_shortfall(wide, rules, START) is None


def test_stage0_counts_apply_the_no_overlap_rule(rules: D.Rules) -> None:
    """Stage 0 counts the trigger AND the no-overlap rule, and no price."""
    cell = D.Cell(5, 3.0, 60)
    base = D._utc_ms(2026, 10, 25)
    events = [
        D.Event(cell=cell, symbol="AAAUSDT", grid_ms=base, direction=1, shock_bps=200.0),
        # entry +6m, inside the first position (exit +66m) -> not a trade
        D.Event(cell=cell, symbol="AAAUSDT", grid_ms=base + 5 * MINUTE,
                direction=1, shock_bps=200.0),
        # entry +71m, after that exit -> a trade
        D.Event(cell=cell, symbol="AAAUSDT", grid_ms=base + 65 * MINUTE,
                direction=1, shock_bps=200.0),
    ]
    kept = D.overlap_filtered(events, cell, rules, window_end_ms=base + 400 * MINUTE)
    assert [event.grid_ms for event in kept] == [base, base + 65 * MINUTE]
    report = D.stage0_report({cell: kept}, rules)
    assert report["cells"][str(cell)]["events"] == 2


def test_holdout_chunk_without_a_declared_window_is_refused(tmp_path: Path,
                                                            rules: D.Rules) -> None:
    """An unprovable window is refused rather than read and screened later."""
    root = _write_store(tmp_path / "recorder", [[
        {"type": "open_interest", "symbol": "BTCUSDT",
         "event_ms": D._utc_ms(2026, 10, 25), "payload": {"openInterest": "1.0"}},
    ]])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["entries"][0].pop("first_ms")
    manifest["entries"][0].pop("last_ms")
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(D.HoldoutRefusal, match="cannot be shown"):
        D.scan_store(root, rules)


def test_holdout_record_without_a_timestamp_is_refused(tmp_path: Path,
                                                       rules: D.Rules) -> None:
    forward = D._utc_ms(2026, 10, 25, 7)
    root = _write_store(tmp_path / "recorder", [[
        {"type": "open_interest", "symbol": "BTCUSDT", "event_ms": forward,
         "payload": {"openInterest": "1000.0"}},
        {"type": "open_interest", "symbol": "BTCUSDT",
         "payload": {"openInterest": "1000.0"}},
    ]])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    declared = manifest["entries"][0]
    digest = hashlib.sha256((root / declared["chunk"]).read_bytes()).hexdigest()
    entry = D.ChunkEntry(
        path=root / declared["chunk"], first_ms=forward,
        last_ms=forward + 30 * MINUTE, records=2, streams=("open_interest",),
        sha256=digest, entry_hash="h", prev="genesis", stamp_ms=forward,
    )
    store = D.Store(root=root, entries=[entry], chain_head="h", created_utc=None)
    with pytest.raises(D.HoldoutRefusal, match="no integer"):
        list(D.read_records(store, [entry], rules))


def test_dsr_cannot_be_forced_by_an_argument(rules: D.Rules) -> None:
    """Amendments 2 and 3: no evaluator may substitute a number -- not through a
    call argument, not through a keyword escape hatch, not through a flag."""
    trades = {cell: [_trade(cell, "AAAUSDT", day, 5.0) for day in range(320)]
              for cell in rules.cells}
    for number in FORBIDDEN_TRIAL_COUNTS:
        with pytest.raises(D.D1Error, match="unverified trial count"):
            D.evaluate_cells(trades, rules, n_trials=number)
    with pytest.raises(SystemExit):
        D.main(["--recorder-root", ".", "--n-trials", "470"])
    # The forward path has no trial-count parameter at all, and the cells path
    # has no permissive flag: the count is resolved from the frozen constant.
    forward_params = inspect.signature(D.evaluate_forward).parameters
    assert "n_trials" not in forward_params
    assert "n_trials_problem" not in forward_params
    cells_params = inspect.signature(D.evaluate_cells).parameters
    assert "trial_count_trusted" not in cells_params
    with pytest.raises(TypeError):
        D.evaluate_forward(Path("."), n_trials=470)
    # Without the frozen constant the gate is not evaluable, whatever the data.
    doc = D.evaluate_cells(trades, rules, n_trials=None,
                           n_trials_problem="trial count not frozen: test")
    gate4 = {item["gate"]: item for item in doc["gates"]}[4]
    assert gate4["status"] == "not_evaluable" and gate4["dsr"] is None


def test_frozen_constant_is_the_only_way_the_dsr_gate_evaluates(
        rules: D.Rules, tmp_path: Path, monkeypatch) -> None:
    """Prove the guard is the constant's value, not a disabled code path.

    R2 freezes the count by setting ``N_TRIALS`` in ``d1_trials`` next to the
    amendment. This test does exactly that (and reverses it) to show gate 4
    comes alive with that value -- then shows a different number is still
    refused while it is frozen.
    """
    trades = _synthetic_cells(rules)
    calendar = sorted({trade.entry_day for rows in trades.values() for trade in rows})
    assert d1_trials.N_TRIALS is None
    monkeypatch.setattr(d1_trials, "N_TRIALS", 1000)
    # Read the constant back instead of repeating the literal at the call site: a
    # copy of this test must not become a way to hand the gate a number that the
    # constant does not actually hold.
    frozen = d1_trials.N_TRIALS
    assert frozen == 1000
    amendment = tmp_path / d1_trials.N_TRIALS_AMENDMENT
    amendment.parent.mkdir(parents=True, exist_ok=True)
    amendment.write_text("frozen for this test only\n", encoding="utf-8")
    assert d1_trials.trial_count_ready(tmp_path) == (frozen, None)
    doc = D.evaluate_cells(trades, rules, n_trials=frozen, calendar_days=calendar)
    gate4 = {item["gate"]: item for item in doc["gates"]}[4]
    assert gate4["status"] in {"pass", "fail"}
    assert gate4["n_trials"] == frozen and gate4["dsr"] is not None
    for number in FORBIDDEN_TRIAL_COUNTS:
        with pytest.raises(D.D1Error, match="unverified trial count"):
            D.evaluate_cells(trades, rules, n_trials=number, calendar_days=calendar)


def _mutated_module(original: str, mutation: str):
    """Execute a source-mutated copy of the evaluator and hand it back.

    The prereg (amendment 1, section 5) requires each named guard to be shown
    failing under its mutation. Mutating the source text and running that copy
    in-process proves it against the real module instead of a stand-in: if the
    rule the guard asserts were not actually implemented, the mutated copy
    would behave identically and these tests would fail.
    """
    import sys
    import types

    path = REPO / "src/cryptobot/research/d1_eval.py"
    source = path.read_text(encoding="utf-8")
    assert original in source, f"mutation anchor missing: {original[:60]!r}"
    name = f"d1_mutant_{abs(hash((original, mutation))) % 10**8}"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    # dataclasses resolves field annotations through sys.modules, so the mutant
    # has to be registered before it runs (the same reason the CLI does it for
    # tools/forward_b4b.py).
    sys.modules[name] = module
    try:
        exec(compile(source.replace(original, mutation, 1), str(path), "exec"),
             module.__dict__)
    finally:
        sys.modules.pop(name, None)
    return module


def test_mutation_entry_offset_is_caught(rules: D.Rules) -> None:
    """Mutation of test_entry_bar_is_t_plus_6...: move the entry to T+5m."""
    mutant = _mutated_module(
        "        entry_ms = event.grid_ms + entry_offset\n"
        "        if entry_ms in scheduled:",
        "        entry_ms = event.grid_ms + 5 * MIN_MS\n"
        "        if entry_ms in scheduled:")
    item = _series()
    grid = min(item.bar_open) + 120 * MINUTE
    event = D.Event(cell=D.Cell(5, 3.0, 15), symbol=item.symbol, grid_ms=grid,
                    direction=1, shock_bps=200.0)
    trades, _dropped = mutant.simulate(item, [event], event.cell, rules,
                                       window_end_ms=item.last_ms)
    assert trades and trades[0].entry_ms == grid + 5 * MINUTE


def test_mutation_lifetime_universe_volume_is_caught() -> None:
    """Mutation of test_monthly_universe...: rank on lifetime volume and AAA,
    which has almost no September volume, takes the slot."""
    import tempfile

    rules = D.load_rules(_patched_prereg(
        Path(tempfile.mkdtemp(dir="/tmp")) / "prereg",
        universe="take the top N = 30=>take the top N = 2"))
    series = _universe_series()
    honest = D.monthly_rankings(series, rules, START, START + 60 * DAY)
    assert "AAAUSDT" not in honest["2026-10"].ranked

    mutant = _mutated_module(
        "            total = sum(item.daily_quote_volume[day] for day in required_days)",
        "            total = sum(item.daily_quote_volume.values())")
    leaked = mutant.monthly_rankings(series, rules, START, START + 60 * DAY)
    assert "AAAUSDT" in leaked["2026-10"].ranked


def test_mutation_missing_immediate_kill_gate_is_caught(rules: D.Rules) -> None:
    """Mutation of test_immediate_kill_when_no_cell_covers_cost: remove the gate
    and a sample where no cell covers its cost is no longer killed."""
    mutant = _mutated_module(
        "    immediate_kill = bool(traded) and max(margin[cell] for cell in traded) < 0",
        "    immediate_kill = False")
    trades = {cell: [_trade(cell, "AAAUSDT", day, -5.0) for day in range(120)]
              for cell in rules.cells}
    doc = mutant.evaluate_cells(trades, rules, n_trials=None,
                               n_trials_problem="trial count not frozen: test")
    assert doc["immediate_kill"]["fired"] is False
    assert doc["verdict"] != "KILL"


def test_mutation_weakened_cutoff_is_caught(rules: D.Rules) -> None:
    """Mutation of test_no_exit_at_or_after_dev_cutoff: stop forbidding entries
    whose scheduled exit reaches the cutoff and a truncated hold is booked."""
    mutant = _mutated_module(
        "        if entry_ms >= window_end_ms or exit_target >= window_end_ms:",
        "        if entry_ms >= window_end_ms:")
    item = _series()
    cell = D.Cell(5, 3.0, 60)
    base = min(item.bar_open)
    cutoff = base + 200 * MINUTE
    late = D.Event(cell=cell, symbol=item.symbol, grid_ms=base + 140 * MINUTE,
                   direction=1, shock_bps=200.0)
    trades, _dropped = mutant.simulate(item, [late], cell, rules,
                                       window_end_ms=cutoff)
    assert trades, "the weakened rule books the entry the frozen rule forbids"


# --------------------------------------------------------------------------
# 8. End to end on a fully synthetic forward chunk chain
# --------------------------------------------------------------------------

# The frozen sigma lookback is 7 days, so the first week of any fixture is
# warm-up and cannot produce an event; the power gate then needs >=100
# distinct event days, so the window must be materially longer than 107.
# The frozen timeline is unforgiving: no symbol can be ranked until it has 90
# days of listing inside forward data and a whole previous calendar month, so
# the first tradeable month is 2027-02 and the window must run well past it to
# reach the power gate's 100 distinct event days.
KILL_DAYS = 170


@pytest.fixture(scope="module")
def kill_store(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("d1-kill")
    prereg = _patched_prereg(
        root / "prereg",
        universe="take the top N = 30=>take the top N = 2",
        age="listing age >= 90 days=>listing age >= 5 days",
    )
    records: list[dict] = []
    for symbol in ("AAAUSDT", "BBBUSDT"):
        records.extend(_market_records(symbol=symbol, days=KILL_DAYS))
        # Daily klines start where forward data starts: the ranking for a month
        # needs the *whole* previous month inside forward data, so the first
        # tradeable month is the second full one (2026-12) and the window has to
        # be long enough to reach 100 distinct event days after that.
        records.extend(_daily_klines(symbol, dt.date(2026, 10, 18),
                                     dt.date(2027, 7, 31)))
    # One chronological stream, the way the recorder writes it.
    records.sort(key=lambda record: record["event_ms"])
    return _write_store(root / "recorder", _chunks(records)), prereg


def test_known_answer_kill_on_synthetic_forward_chunks(kill_store) -> None:
    """A flush that keeps going never pays for the 1x round trip -> KILL."""
    root, prereg = kill_store
    doc = D.evaluate_forward(root, prereg_dir=prereg)
    assert doc["verdict"] == "KILL", doc.get("stream_shortfalls")
    assert doc["immediate_kill"]["fired"] is True
    assert doc["prereg"]["sha256"]  # frozen rules are bound into the output
    assert doc["protocol"]["window"][0] >= "2026-10-18"
    stage0 = doc["stage0"]
    assert stage0["eligible_cells"] >= 1
    assert all(row["events"] >= 300 for row in stage0["cells"].values())
    trade = next(iter(doc["trade_summary"].values()))
    assert trade["mean_gross_bps"] < 0
    text = D.render(doc)
    assert text.splitlines()[0] == "VERDICT: KILL"
    assert "gross" in text and "all-in" in text
    assert D.main(["--recorder-root", str(root), "--prereg-dir", str(prereg)]) == 1


def test_entry_latency_end_to_end(kill_store) -> None:
    """The synthetic flush at grid T must produce an entry exactly at T+6m."""
    root, prereg = kill_store
    rules = D.load_rules(prereg)
    store = D.scan_store(root, rules)
    entries = store.entries
    series, _inventory = D.build_series(store, entries, rules)
    item = series["AAAUSDT"]
    cell = D.Cell(5, 3.0, 15)
    events = D.detect_events(item, cell, rules,
                             window_start_ms=START, window_end_ms=START + KILL_DAYS * DAY)
    assert events, "the synthetic flush must trigger"
    trade = next(iter(events))
    trades, _dropped = D.simulate(item, [trade], cell, rules,
                                  window_end_ms=START + KILL_DAYS * DAY)
    assert trades[0].entry_ms - trade.grid_ms == 6 * MINUTE
