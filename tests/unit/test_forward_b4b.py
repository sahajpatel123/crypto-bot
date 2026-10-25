"""B4b forward recorder: window refusal, point-in-time book, gates, one look.

No network: every test drives the pure functions (``plan_files`` with a stub
client, ``simulate``/``evaluate_frames`` with synthetic forward frames).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")

_spec = importlib.util.spec_from_file_location(
    "forward_b4b", Path(__file__).resolve().parents[2] / "tools/forward_b4b.py")
fwd = importlib.util.module_from_spec(_spec)
sys.modules["forward_b4b"] = fwd   # dataclasses need the module registered
_spec.loader.exec_module(fwd)

START = pd.Timestamp("2026-11-01", tz="UTC")


def _ms(idx) -> np.ndarray:
    """UTC nanosecond-safe epoch milliseconds for a tz-aware index."""
    return (idx.tz_convert("UTC").tz_localize(None)
            .astype("datetime64[ms]").astype("int64"))


# -- synthetic forward data ---------------------------------------------------
def _frames(days: int = 400, *, rich: float = 2.0e-3, low: float = 1.0e-5,
            cycle: int = 12, rich_days: int = 8, price: float = 100.0,
            adv: float = 5.0e8, sigma: float = 0.01, drift: float = 0.0,
            warmup_days: int = 1, seed: int = 7):
    """Flat prices, a rich/low funding cycle, plenty of ADV.

    ``warmup_days`` of bars are supplied before the forward clock starts,
    because in production the study fetches bars from 2026-10-18 onward and
    the forward clock only begins on 2026-11-01. ``drift`` is a deterministic
    per-day log trend, used to prove the book is delta-neutral.
    """
    rng = np.random.default_rng(seed)
    begin = START - pd.Timedelta(days=warmup_days)
    hours = pd.date_range(begin, periods=(days + warmup_days) * 24,
                          freq="h", tz="UTC")
    # gentle walk so realized sigma is nonzero, delta-neutral P&L stays small
    steps = rng.normal(0.0, sigma / np.sqrt(24), len(hours))
    trend = drift * np.arange(len(hours)) / 24.0
    closes = price * np.exp(np.cumsum(steps) + trend)
    klines = pd.DataFrame({
        "open_ms": _ms(hours),
        "open": closes, "close": closes,
        "quote_volume": np.full(len(hours), adv / 24.0)})
    settle = pd.date_range(START, periods=days * 3, freq="8h", tz="UTC")
    day_of = ((settle - START) / pd.Timedelta(days=1)).astype(int)
    rates = np.where(day_of % cycle < rich_days, rich, low)
    funding = pd.DataFrame({
        "calc_ms": _ms(settle),
        "rate": rates})
    return {sym: {"spot": klines.copy(), "perp": klines.copy(),
                  "funding": funding.copy()} for sym in fwd.UNIVERSE}


# -- window rules ------------------------------------------------------------
def test_forward_window_rules():
    assert fwd.is_forward_file("BTCUSDT-1h-2026-10-18.zip") is True
    assert fwd.is_forward_file("BTCUSDT-1h-2026-10-17.zip") is False
    assert fwd.is_forward_file("BTCUSDT-1h-2026-03-01.zip") is False
    assert fwd.is_forward_file("BTCUSDT-fundingRate-2026-10.zip") is False
    assert fwd.is_forward_file("BTCUSDT-fundingRate-2026-11.zip") is True
    with pytest.raises(ValueError):
        fwd.is_forward_file("MATICUSDT-fundingRate-1993.zip")


def test_refuses_pre_window_filenames():
    with pytest.raises(fwd.InputBeforeForwardWindow):
        fwd.assert_forward_files(["BTCUSDT-1h-2026-10-17.zip"])
    fwd.assert_forward_files(["BTCUSDT-1h-2026-10-18.zip",
                              "BTCUSDT-fundingRate-2026-11.zip"])


def test_refuses_pre_window_rows_on_disk(tmp_path):
    """A file whose name says forward but whose rows are not is rejected."""
    hours = pd.date_range("2026-10-16", periods=48, freq="h", tz="UTC")
    csv = "\n".join(
        f"{int(t.timestamp()*1000)},1,1,1,1,1,"
        f"{int(t.timestamp()*1000)+3599999},1000,1,1,1,0" for t in hours)
    dest = tmp_path / "spot" / "BTCUSDT" / "BTCUSDT-1h-2026-10-18.zip"
    dest.parent.mkdir(parents=True)
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("x.csv", csv)
    with pytest.raises(fwd.InputBeforeForwardWindow):
        fwd.load_frames(tmp_path)


class _StubBlob:
    """Minimal VisionClient stand-in: serves one blob and its digest."""

    def __init__(self, blob: bytes):
        self.blob = blob
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if url.endswith(".CHECKSUM"):
            digest = hashlib.sha256(self.blob).hexdigest()
            return f"{digest}  data.zip\n".encode()
        return self.blob


def test_resumed_file_is_checksum_verified_against_the_remote(tmp_path):
    """An on-disk file is verified too, not trusted because it exists."""
    blob = b"the published bytes"
    dest = tmp_path / "BTCUSDT-1h-2026-11-01.zip"
    dest.write_bytes(blob)
    ok = _StubBlob(blob)
    rec = fwd.VisionClient.download_verified(ok, "key", dest)
    assert rec["resumed"] is True
    assert rec["verified"] is True
    assert any(u.endswith(".CHECKSUM") for u in ok.calls)

    # A local file that no longer matches the published digest must be
    # re-fetched. The old code returned it as verified without a request.
    dest.write_bytes(b"tampered bytes")
    again = _StubBlob(blob)
    rec2 = fwd.VisionClient.download_verified(again, "key", dest)
    assert rec2["resumed"] is False
    assert rec2["verified"] is True
    assert dest.read_bytes() == blob


def test_refuses_rows_outside_their_own_file_window(tmp_path):
    """A 2026-10 file renamed 2026-11 must not smuggle holdout days.

    Every row must sit inside the file's own date. Checking only the
    earliest row let a holdout-dated funding file renamed to a forward
    month import exactly the 14 days the prereg permanently excludes.
    """
    settle = pd.date_range("2026-10-18", "2026-10-31 16:00", freq="8h",
                           tz="UTC")
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    lines += [f"{int(t.timestamp()*1000)},8,0.0002" for t in settle]
    folder = tmp_path / "funding" / "BTCUSDT"
    folder.mkdir(parents=True)
    # Dated 2026-11 by name, full of October rows.
    with zipfile.ZipFile(folder / "BTCUSDT-fundingRate-2026-11.zip", "w") as zf:
        zf.writestr("data.csv", "\n".join(lines) + "\n")
    with pytest.raises(fwd.InputBeforeForwardWindow, match="own window"):
        fwd.load_frames(tmp_path)


def test_a_day_without_bars_is_not_a_forward_day():
    """Funding without bars must not count: no marking off a stale price."""
    frames = _frames(days=30)
    for per in frames.values():
        for venue in ("spot", "perp"):
            df = per[venue]
            idx = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
            gone = (idx >= pd.Timestamp("2026-11-10", tz="UTC")) & (
                idx < pd.Timestamp("2026-11-11", tz="UTC"))
            per[venue] = df[~gone].reset_index(drop=True)
    sim = fwd.simulate(frames)
    days = [r["day"] for r in sim["rows"]]
    assert "2026-11-11" not in days     # its mark came from 11-10's bars
    assert len(days) == 29


def test_hurdle_matches_prereg():
    # k=1.5 * 53bps * 365/7
    assert fwd.hurdle_apr(1.5, 53.0) == pytest.approx(0.41453571428571427)
    assert fwd.median_hurdle_rate(1.5, 53.0) == pytest.approx(3.7857142857e-4,
                                                              rel=1e-9)


class _StubVision:
    def __init__(self, keys):
        self.keys = keys

    def list_keys(self, prefix):
        return [{"key": k, "size": 1} for k in self.keys if k.startswith(prefix)]


def test_plan_only_takes_forward_files():
    keys = [
        "data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-10-17.zip",
        "data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-10-18.zip",
        "data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-10-18.zip.CHECKSUM",
        "data/futures/um/monthly/fundingRate/BTCUSDT/"
        "BTCUSDT-fundingRate-2026-10.zip",
        "data/futures/um/monthly/fundingRate/BTCUSDT/"
        "BTCUSDT-fundingRate-2026-11.zip",
    ]
    jobs = fwd.plan_files(_StubVision(keys), symbols=("BTCUSDT",))
    names = {j["name"] for j in jobs}
    assert names == {"BTCUSDT-1h-2026-10-18.zip",
                     "BTCUSDT-fundingRate-2026-11.zip"}
    assert all(fwd.is_forward_file(n) for n in names)


# -- costs and sizing --------------------------------------------------------
def test_impact_has_no_one_bp_floor():
    book = fwd.Book(cash=1000.0, cfg=fwd.B4bConfig())
    fee_bps = fwd.FILL_BPS["spot"]
    # A tiny fill relative to ADV must not pay a fixed 1bp slip floor.
    cost, part = book.cost_of(1_000.0, "spot", sigma=0.03, adv=1e9)
    assert part == pytest.approx(1e-6)
    assert cost / 1_000.0 * 1e4 == pytest.approx(fee_bps + 0.15, rel=1e-6)
    assert cost / 1_000.0 * 1e4 < fee_bps + 0.5      # strictly below floor-cost
    # A large fill pays through the square-root law instead.
    big, part_big = book.cost_of(1e7, "spot", sigma=0.03, adv=1e9)
    assert part_big == pytest.approx(0.01)
    assert big / 1e7 * 1e4 == pytest.approx(fee_bps + 0.5 * 0.03 * 0.1 * 1e4)


def test_adverse_run_doubles_only_costs():
    cfg = fwd.B4bConfig()
    adverse = fwd.B4bConfig(**{**cfg.__dict__, "adverse_mult": 2.0})
    base = fwd.Book(cash=1000.0, cfg=cfg).cost_of(1e6, "perp", sigma=0.02,
                                                 adv=1e8)[0]
    hard = fwd.Book(cash=1000.0, cfg=adverse).cost_of(1e6, "perp",
                                                      sigma=0.02, adv=1e8)[0]
    assert hard == pytest.approx(2 * base)


# -- the book ----------------------------------------------------------------
def test_no_trade_before_adv_window_is_filled():
    """Sizing/impact need 20 forward days of bars; no entry before that."""
    frames = _frames(days=40)
    sim = fwd.simulate(frames)
    first_fill = min(f["day"] for f in sim["fills"])
    # Bars start one day before the clock (as production data does), so the
    # 20-day ADV window completes on 2026-11-19 and the first decision that
    # may size a position is 2026-11-20 -- not before.
    assert first_fill == "2026-11-20"
    assert all(f["day"] > "2026-11-19" for f in sim["fills"])
    assert sim["round_trips"] >= 0


def test_every_fill_executes_at_the_next_bar_open():
    """Entry, exit AND rebalance all trade the first bar open after the
    decision (prereg execution rule). Rebalances used to be priced at the
    prior close, a bar the decision was not allowed to trade.

    The fixture jumps the perp price at a day boundary and forces the hedge
    to rebalance every day, so the two conventions give different prices.
    """
    frames = _frames(days=120, cycle=12, rich_days=8)
    boundary = pd.Timestamp("2026-11-30", tz="UTC")
    for per in frames.values():
        df = per["perp"].copy()
        idx = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
        late = (idx >= boundary).to_numpy()
        for col in ("open", "close"):
            vals = df[col].to_numpy(dtype=float).copy()
            vals[late] = vals[late] * 1.25
            df[col] = vals
        per["perp"] = df
    cfg = fwd.B4bConfig(drift_band=-1.0)      # rebalance on every decision
    sim = fwd.simulate(frames, cfg)
    assert sim["fills"]
    perp_fills = [f for f in sim["fills"] if f["venue"] == "perp"]
    assert len(perp_fills) > 2 * sim["round_trips"], "no rebalance exercised"
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    gapped = 0
    for f in sim["fills"]:
        day = pd.Timestamp(f["day"], tz="UTC")
        bars = prep[f["symbol"]]["spot" if f["venue"] == "spot" else "perp"]
        want = float(bars[bars.index >= day]["open"].iloc[0])
        prior = float(bars[bars.index < day]["close"].iloc[-1])
        assert f["price"] == pytest.approx(want), (f, want)
        if abs(want - prior) > 1e-9:
            gapped += 1
    assert gapped > 0, "fixture must contain a gap for this test to bite"


def test_rich_funding_enters_delta_neutral_and_earns():
    frames = _frames(days=120)
    sim = fwd.simulate(frames)
    assert sim["fills"], "rich funding must open the book"
    book = sim["book"]
    spot_fills = [f for f in sim["fills"] if f["venue"] == "spot"]
    perp_fills = [f for f in sim["fills"] if f["venue"] == "perp"]
    assert spot_fills and perp_fills
    # every fill at or below the 1% participation cap
    assert max(f["participation"] for f in sim["fills"]) <= 0.011
    # delta-neutral: spot and perp notional matched at entry
    assert abs(spot_fills[0]["notional"] - perp_fills[0]["notional"]) / \
        spot_fills[0]["notional"] < 0.02
    assert book.cash != 1000.0


def test_forward_days_require_funding_not_just_bars():
    """Bars without funding are not a forward day (no carry, no count)."""
    frames = _frames(days=30)
    for per in frames.values():
        per["funding"] = per["funding"].iloc[0:0]
    sim = fwd.simulate(frames)
    assert sim["rows"] == []
    assert sim["fills"] == []
    doc = fwd.evaluate_frames(frames)
    assert doc["forward_days"] == 0
    assert doc["forward_days_remaining"] == 90
    assert doc["status"] == "UNDERPOWERED"


def test_flat_funding_never_trades():
    frames = _frames(days=120, rich=1.0e-5, low=1.0e-5)
    sim = fwd.simulate(frames)
    assert sim["fills"] == []
    assert sim["round_trips"] == 0
    assert all(r["net_ret"] == 0.0 for r in sim["rows"])


def test_evaluate_und_powered_and_gates_present():
    frames = _frames(days=25)
    doc = fwd.evaluate_frames(frames)
    assert doc["status"] == "UNDERPOWERED"
    assert doc["forward_days"] == 25
    assert doc["forward_days_remaining"] == 65
    assert doc["powered"] is False
    assert set(doc["gates"]) >= {"sharpe", "sharpe_2x", "dsr", "pbo",
                                 "plateau", "drawdown", "years",
                                 "median_participation",
                                 "max_participation", "bootstrap",
                                 "newey_west_t"}
    assert doc["gates"]["pbo"] is None
    assert doc["gates"]["plateau"] is None
    assert set(doc["structural_null_gates"]) == {"pbo", "plateau"}


# -- the four guards the review found unpinned -------------------------------
def test_round_trip_half_of_powering_is_enforced():
    """90 forward days with only 12 round trips stays UNDERPOWERED.

    Pins the round-trip half of ``powered``: dropping it would let a study
    with 90 days and 12 bets write a PASS verdict.
    """
    doc = fwd.evaluate_frames(_frames(days=90, cycle=12, rich_days=8))
    assert doc["forward_days"] == 90
    assert doc["round_trips"] == 12
    assert doc["round_trips_remaining"] == 8
    assert doc["powered"] is False
    assert doc["status"] == "UNDERPOWERED"
    assert doc["status_reason"].startswith("stopping rule")


def test_day_half_of_powering_is_enforced():
    """Enough round trips but under 90 days stays UNDERPOWERED."""
    doc = fwd.evaluate_frames(_frames(days=60, cycle=12, rich_days=8))
    assert doc["forward_days"] == 60
    assert doc["round_trips"] >= 6
    assert doc["powered"] is False
    assert doc["status"] == "UNDERPOWERED"


def test_years_gate_blocks_a_pass_before_two_calendar_years():
    """90-120 forward days is one calendar year: a PASS is impossible.

    Pins ``years`` against being moved into STRUCTURAL_NULL_GATES: with the
    study fully powered on days and round trips, the only thing between it
    and PASS is gate 6, so a non-blocking years gate would produce a verdict
    here instead of UNDERPOWERED.
    """
    doc = fwd.evaluate_frames(_frames(days=100, cycle=8, rich_days=4))
    assert doc["forward_days"] == 100
    assert doc["round_trips"] >= 20
    assert doc["powered"] is True
    assert "years" not in fwd.STRUCTURAL_NULL_GATES
    assert doc["gates"]["years"] is None
    assert doc["failed_gates"] == []
    assert doc["unassessable_gates"] == ["years"]
    assert doc["status"] == "UNDERPOWERED"
    assert doc["status_reason"].startswith("gate(s) not yet assessable")
    # the first date a PASS could exist, stated in the document itself
    assert doc["years_assessable_from_forward_day"] == 121
    assert doc["years_assessable_from"] == "2027-03-01"
    assert doc["forward_days_to_first_possible_pass"] == 21


def test_trial_vector_requires_exactly_nine_dev_cells(monkeypatch, tmp_path):
    """Pins the N = 10 denominator: 8 cells must not pass as 9."""
    doc = json.loads(fwd.B4_DEV_ARTIFACT.read_text())
    short = dict(doc)
    cells = dict(doc["cell_sharpes"])
    cells.pop(sorted(cells)[0])
    short["cell_sharpes"] = cells
    fake = tmp_path / "B4.json"
    fake.write_text(json.dumps(short))
    monkeypatch.setattr(fwd, "B4_DEV_ARTIFACT", fake)
    with pytest.raises(RuntimeError, match="expected the 9 frozen B4 dev cells"):
        fwd.trial_sharpes()


def test_years_gate_arithmetic_matches_the_prereg():
    """121 forward days, not 2028: 2026 gives 61, 2027 reaches 60 on 03-01."""
    assert fwd.years_assessable_forward_day() == 121
    assert str(fwd.years_assessable_on()) == "2027-03-01"
    first = pd.Timestamp(fwd.FORWARD_CLOCK_START, tz="UTC")
    on = first + pd.Timedelta(days=fwd.years_assessable_forward_day() - 1)
    assert str(fwd.years_assessable_on()) == str(on.date())


# -- delta-neutrality (the review's critical finding) ------------------------
def test_book_is_delta_neutral_under_a_strong_trend():
    """Identical spot and perp prices: equity must be funding minus costs.

    The spot leg is a held asset, marked into equity. Accruing its P&L into
    cash as well counts it twice and leaves the book long 1x spot, so equity
    becomes ``E0 + q*(s_t - s_entry) + funding - costs`` and a trend turns
    into equity. Measured on this fixture: the bug reads +169% of equity for
    a +1%/day trend, instead of the +28% the carry alone earns. The
    identity below is exact, so no tolerance rescues it.
    """
    for drift in (0.0, 0.01, -0.01):
        frames = _frames(days=120, drift=drift)
        sim = fwd.simulate(frames)
        doc = fwd.evaluate_frames(frames)
        closes = frames["BTCUSDT"]["spot"]["close"]
        spot_move = closes.iloc[-1] / closes.iloc[24] - 1.0
        if drift:
            assert abs(spot_move) > 0.6, "the fixture must actually trend"
        expected = (fwd.E0 + sim["funding_income"]
                    - sum(f["cost"] for f in sim["fills"]))
        assert sim["rows"][-1]["equity"] == pytest.approx(expected, rel=1e-9)
        # Equity is the carry, not the price path: ~+29% here, from 219% APR
        # funding earned roughly half the time on half the equity.
        assert 0.20 < doc["stats"]["total_net"] < 0.40


def test_evaluate_powered_synthetic_passes_mechanics():
    """400 forward days span two calendar years and >20 round trips."""
    frames = _frames(days=420)
    doc = fwd.evaluate_frames(frames)
    assert doc["forward_days"] >= 90
    assert doc["round_trips"] >= 20
    assert doc["powered"] is True
    assert doc["gates"]["bootstrap"] is True
    assert doc["gates"]["median_participation"] is True
    assert doc["gates"]["max_participation"] is True
    assert doc["gates"]["years"] is True          # 2026 + 2027 both >= 60d
    assert doc["stats"]["sharpe"] > 0
    assert doc["status"] in ("PASS", "KILLED")
    # the reported trial vector is the 9 frozen B4 dev cells + this cell
    assert doc["trial_sharpes_n"] == 10


def test_gate_machine_can_pass_and_permits_a_pass():
    """A strongly funded, long-enough run must be able to reach PASS."""
    doc = fwd.evaluate_frames(_frames(days=420, rich=5.0e-3))
    assert doc["powered"] is True
    assert doc["failed_gates"] == []
    assert doc["unassessable_gates"] == []
    assert doc["gates"]["dsr"] is True
    assert doc["status"] == "PASS"


def test_turnover_is_reported_never_gated():
    doc = fwd.evaluate_frames(_frames(days=420))
    assert doc["gross_turnover_per_year_descriptive"] > 0
    assert "turnover" not in doc["gates"]


# -- one look ----------------------------------------------------------------
def test_evaluate_refuses_while_underpowered(tmp_path):
    root = tmp_path / "fwd"
    _write_tiny_root(root, days=3)
    with pytest.raises(SystemExit, match="UNDERPOWERED"):
        fwd.evaluate(root, out_dir=tmp_path / "out")


def test_evaluate_refuses_second_look(tmp_path):
    root = tmp_path / "fwd"
    _write_tiny_root(root, days=3)
    out = tmp_path / "out"
    out.mkdir()
    (out / fwd.VERDICT_NAME).write_text(json.dumps({"status": "PASS"}))
    with pytest.raises(SystemExit, match="one look"):
        fwd.evaluate(root, force=True, out_dir=out)


def test_evaluate_force_rewrites_underpowered_verdict(tmp_path):
    root = tmp_path / "fwd"
    _write_tiny_root(root, days=3)
    out = tmp_path / "out"
    doc = fwd.evaluate(root, force=True, out_dir=out)
    assert doc["status"] == "UNDERPOWERED"
    assert (out / fwd.VERDICT_NAME).exists()
    doc2 = fwd.evaluate(root, force=True, out_dir=out)
    assert doc2["forward_days"] == doc["forward_days"]


def test_status_reports_remaining_days_and_no_returns(tmp_path):
    root = tmp_path / "fwd"
    _write_tiny_root(root, days=3)
    doc = fwd.status_doc(root)
    assert doc["forward_days"] == 3
    assert doc["forward_days_remaining"] == 87
    assert doc["round_trips_remaining"] == 20
    assert "sharpe" not in dict(doc)
    assert "coverage" in doc


def _write_tiny_root(root: Path, *, days: int) -> None:
    """Write synthetic frames as real Vision-shaped files.

    One zip per UTC day for klines and one per month for funding, each
    carrying only its own window's rows: that is what Vision publishes, and
    the loader now rejects a file whose rows stray outside its own date.
    """
    frames = _frames(days=days)
    for sym, per in frames.items():
        for dataset in ("spot", "perp"):
            df = per[dataset]
            idx = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
            folder = root / dataset / sym
            folder.mkdir(parents=True, exist_ok=True)
            for day, grp in df.groupby(idx.dt.floor("D")):
                lines = [f"{int(t.timestamp()*1000)},{float(o)!r},"
                         f"{float(o)!r},{float(o)!r},{float(c)!r},1,"
                         f"{int(t.timestamp()*1000)+3599999},{float(v)!r},"
                         f"1,1,1,0"
                         for t, o, c, v in zip(
                             pd.to_datetime(grp["open_ms"], unit="ms", utc=True),
                             grp["open"], grp["close"], grp["quote_volume"],
                             strict=True)]
                name = f"{sym}-1h-{day.strftime('%Y-%m-%d')}.zip"
                with zipfile.ZipFile(folder / name, "w") as zf:
                    zf.writestr("data.csv", "\n".join(lines) + "\n")
        fdf = per["funding"]
        fidx = pd.to_datetime(fdf["calc_ms"], unit="ms", utc=True)
        folder = root / "funding" / sym
        folder.mkdir(parents=True, exist_ok=True)
        for month, grp in fdf.groupby(fidx.dt.tz_localize(None).dt.to_period("M")):
            lines = ["calc_time,funding_interval_hours,last_funding_rate"]
            lines += [f"{int(t.timestamp()*1000)},8,{r}" for t, r in zip(
                pd.to_datetime(grp["calc_ms"], unit="ms", utc=True),
                grp["rate"], strict=True)]
            name = f"{sym}-fundingRate-{month}.zip"
            with zipfile.ZipFile(folder / name, "w") as zf:
                zf.writestr("data.csv", "\n".join(lines) + "\n")


# -- frozen-rule audit: each clause of C1/B4b pinned to a test ---------------
def _settlements(rates_by_day: list[float], *, per_day: int = 3):
    """Funding settlements: one rate per forward day, ``per_day`` each."""
    rows = []
    for d, rate in enumerate(rates_by_day):
        for k in range(per_day):
            rows.append({"calc_ms": int(_ms(pd.DatetimeIndex(
                [START + pd.Timedelta(days=d, hours=8 * k)]))[0]),
                "rate": float(rate)})
    return pd.DataFrame(rows)


def _frames_with_rates(rates_by_day: list[float], *, price: float = 100.0,
                       adv: float = 5.0e8, sigma: float = 0.01,
                       seed: int = 11):
    """Bars for len(rates_by_day) forward days + that funding profile."""
    days = len(rates_by_day)
    base = _frames(days=days, warmup_days=1, price=price, adv=adv,
                   sigma=sigma, seed=seed)
    funding = _settlements(rates_by_day)
    return {sym: {"spot": f["spot"].copy(), "perp": f["perp"].copy(),
                  "funding": funding.copy()} for sym, f in base.items()}


def test_decision_clock_is_midnight_utc_and_daily():
    timing = _frames(days=10)["BTCUSDT"]["perp"]
    d = pd.DataFrame({"open_ms": timing["open_ms"], "open": timing["open"],
                      "close": timing["close"],
                      "quote_volume": timing["quote_volume"]})
    # decision_days reads the bar index, exactly as _prep builds it
    d.index = pd.to_datetime(d["open_ms"], unit="ms", utc=True)
    days = fwd.decision_days(d)
    assert days, "the clock must produce decision days"
    for stamp in days:
        assert stamp.hour == 0 and stamp.minute == 0 and stamp.second == 0
        assert stamp.tzinfo is not None
        assert stamp >= fwd.forward_clock_start()
    assert len(days) == len(set(days)), "one decision per UTC day"


def test_settlement_at_the_decision_instant_is_excluded():
    """Prereg: a rate is eligible only if strictly BEFORE the decision."""
    boundary = START + pd.Timedelta(days=20)
    stamps = [boundary - pd.Timedelta(hours=8 * (21 - i)) for i in range(21)]
    series = pd.Series([1.0e-4] * 21, index=stamps)
    series.loc[boundary] = 9.0      # at the decision instant: not eligible
    got = fwd._trailing_funding(series, boundary)
    assert got == pytest.approx(1.0e-4), "the boundary settlement leaked in"


def test_trailing_funding_is_the_median_of_21_settlements():
    boundary = START + pd.Timedelta(days=30)
    stamps = [boundary - pd.Timedelta(hours=8 * (40 - i)) for i in range(40)]
    # the last 21 settlements are 1..21; the 19 older ones are huge
    vals = [1.0e2] * 19 + [float(i + 1) for i in range(21)]
    series = pd.Series(vals, index=stamps)
    assert fwd._trailing_funding(series, boundary) == pytest.approx(11.0)
    assert fwd.TRAIL_SETTLEMENTS == 21
    # warm-up: fewer than 21 settlements is no decision at all
    assert fwd._trailing_funding(series.head(20), boundary) is None


def test_apr_is_median_8h_times_3_times_365():
    rate = fwd.median_hurdle_rate(1.5, 53.0)
    assert rate * 3.0 * 365.0 == pytest.approx(fwd.hurdle_apr(1.5, 53.0))
    assert rate * 3.0 * 365.0 == pytest.approx(0.41453571428571427)
    assert rate == pytest.approx(3.7857142857142856e-4, rel=1e-9)


def test_round_trip_53bps_decomposition():
    """RT = 2x(15 spot + 1 spread + 1 slip) + 2x(7.5 perp + 1 spread + 1 slip)."""
    assert fwd.RT_BPS == 53.0
    assert (fwd.SPOT_TAKER_BPS, fwd.SPOT_SPREAD_BPS) == (15.0, 1.0)
    assert (fwd.PERP_TAKER_BPS, fwd.PERP_SPREAD_BPS) == (7.5, 1.0)
    assert 2 * (15.0 + 1.0 + 1.0) + 2 * (7.5 + 1.0 + 1.0) == 53.0
    # the model actually charged removes the 4bps of slip floor it replaces
    assert fwd.FILL_BPS == {"spot": 16.0, "perp": 8.5}
    assert 2 * 16.0 + 2 * 8.5 == 49.0


def test_hysteresis_needs_three_consecutive_below_hurdle_days():
    """Clause: exit when APR < 0.5 x hurdle for 3 CONSECUTIVE decision days."""
    hurdle = fwd.hurdle_apr(fwd.K_HURDLE, fwd.RT_BPS)
    below = 0.4 * hurdle          # below half the hurdle
    above = 1.5 * hurdle
    # 1st and 2nd below days accrue a streak but never exit
    exit1, s1 = fwd.exit_decision(held_days=30, median_rate=1e-4,
                                  apr=below, streak=0)
    assert (exit1, s1) == (False, 1)
    exit2, s2 = fwd.exit_decision(held_days=30, median_rate=1e-4,
                                  apr=below, streak=s1)
    assert (exit2, s2) == (False, 2)
    # the 3rd consecutive day exits
    exit3, s3 = fwd.exit_decision(held_days=30, median_rate=1e-4,
                                  apr=below, streak=s2)
    assert (exit3, s3) == (True, 3)
    # a day back above the band resets the streak
    _, reset = fwd.exit_decision(held_days=30, median_rate=1e-4,
                                 apr=above, streak=s2)
    assert reset == 0


def test_hysteresis_respects_the_seven_day_minimum_hold():
    hurdle = fwd.hurdle_apr(fwd.K_HURDLE, fwd.RT_BPS)
    below = 0.4 * hurdle
    # 3 consecutive below days but only 6 days held: no exit yet
    exit_now, streak = fwd.exit_decision(held_days=fwd.MIN_HOLD_DAYS - 1,
                                         median_rate=1e-4, apr=below, streak=2)
    assert (exit_now, streak) == (False, 3)
    # one more decision day and the same streak exits
    exit_now, _ = fwd.exit_decision(held_days=fwd.MIN_HOLD_DAYS,
                                    median_rate=1e-4, apr=below, streak=2)
    assert exit_now is True


def test_negative_median_rate_exits_regardless_of_hold_or_streak():
    hurdle = fwd.hurdle_apr(fwd.K_HURDLE, fwd.RT_BPS)
    exit_now, _ = fwd.exit_decision(held_days=1.0, median_rate=-1e-6,
                                    apr=10 * hurdle, streak=0)
    assert exit_now is True, "a funding flip exits with no min-hold"


def test_rich_then_flat_regime_completes_one_round_trip_per_symbol():
    rich, low = 2.0e-3, 1.0e-4
    rates = [rich] * 40 + [low] * 40
    sim = fwd.simulate(_frames_with_rates(rates))
    # "A round trip is one open-and-closed position in one symbol", so the
    # two-symbol universe yields two.
    assert sim["round_trips"] == len(fwd.UNIVERSE) == 2
    assert sim["mean_hold_days"] >= fwd.MIN_HOLD_DAYS


def test_dip_that_does_not_break_the_band_never_exits():
    rich, low = 2.0e-3, 1.0e-4
    # a short low patch, then rich again for the rest of the sample
    rates = [rich] * 20 + [low, low] + [rich] * 40
    sim = fwd.simulate(_frames_with_rates(rates))
    assert sim["round_trips"] == 0


def test_each_leg_is_fifty_percent_of_equity():
    frames = _frames(days=90)
    sim = fwd.simulate(frames)
    spot = [f for f in sim["fills"] if f["venue"] == "spot"]
    assert spot, "the rich regime must open the book"
    assert spot[0]["notional"] == pytest.approx(0.5 * fwd.E0, rel=0.02)
    # and the two legs are matched, so gross is 2 x equity at entry
    perp = [f for f in sim["fills"] if f["venue"] == "perp"]
    assert abs(spot[0]["notional"] - perp[0]["notional"]) <= 0.02 * spot[0]["notional"]


def test_capital_table_is_finite_at_120_1000_10000():
    rows = fwd.capital_table({"BTCUSDT": 100_000.0, "ETHUSDT": 3_000.0})
    assert {r["equity_usdt"] for r in rows} == {120.0, 1000.0, 10_000.0}
    assert len(rows) == 6
    for r in rows:
        assert r["finite"] is True
        assert r["target_notional"] == pytest.approx(0.5 * r["equity_usdt"])
        assert r["qty"] <= r["target_notional"] / r["price"] + 1e-12
        assert r["clears_min_notional"] == (r["notional"] >= fwd.MIN_NOTIONAL)
    # Reported finding, not a defect: at 120 USDT with BTC at 100k the 0.001
    # quantity step floors the 60 USDT leg (0.0006 BTC) to zero, so BTC does
    # NOT clear the minimum while ETH does. The table says so instead of
    # hiding it; it is never a reason to change the 50% leg.
    small = {r["symbol"]: r for r in rows if r["equity_usdt"] == 120.0}
    assert small["BTCUSDT"]["qty"] == 0.0
    assert small["BTCUSDT"]["clears_min_notional"] is False
    assert small["ETHUSDT"]["clears_min_notional"] is True
    assert all(r["clears_min_notional"] for r in rows
               if r["equity_usdt"] >= 1_000.0)


# -- the one command ---------------------------------------------------------
def test_forward_command_reports_insufficient_with_dates(tmp_path):
    doc = fwd.forward_command(tmp_path)
    assert doc["state"] == "INSUFFICIENT FORWARD DATA"
    assert doc["forward_days"] == 0
    assert doc["forward_days_remaining"] == 90
    assert doc["round_trips_remaining"] == 20
    assert doc["earliest_evaluable_on"] == "2027-01-29"
    assert doc["pass_possible_on"] == "2027-03-01"


def test_forward_command_returns_the_verdict_when_powered(monkeypatch, tmp_path):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path)
    monkeypatch.setattr(fwd, "VERDICT_NAME", "v.json")
    monkeypatch.setattr(fwd, "status_doc", lambda root: {
        "prereg": "p", "forward_days": 121, "round_trips": 25,
        "forward_days_required": 90, "forward_days_remaining": 0,
        "round_trips_required": 20, "round_trips_remaining": 0,
        "powered": True, "forward_clock_start": "2026-11-01",
        "years_assessable_from": "2027-03-01",
        "years_assessable_from_forward_day": 121,
        "coverage": {}, "note": "n"})
    monkeypatch.setattr(fwd, "evaluate",
                        lambda root, force=False: {"status": "KILLED",
                                                   "prereg": "p"})
    doc = fwd.forward_command(tmp_path)
    assert doc["state"] == "VERDICT"
    assert doc["verdict"]["status"] == "KILLED"


def test_forward_command_never_overwrites_a_fired_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path)
    monkeypatch.setattr(fwd, "VERDICT_NAME", "v.json")
    (tmp_path / "v.json").write_text(json.dumps({"status": "KILLED"}))
    monkeypatch.setattr(fwd, "status_doc", lambda root: {"powered": True})
    called = []
    monkeypatch.setattr(fwd, "evaluate",
                        lambda root, force=False: called.append(1) or {})
    doc = fwd.forward_command(tmp_path)
    assert doc["state"] == "VERDICT"
    assert called == [], "the one look must not be recomputed"


def test_cli_forward_b4b_prints_insufficient(tmp_path, capsys):
    from cryptobot import cli
    code = cli.main(["forward", "b4b", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 3
    assert "INSUFFICIENT FORWARD DATA" in out
    assert "2027-01-29" in out
    assert "0 of 90" in out


def test_manifest_records_url_bytes_sha256_rows_and_time(monkeypatch, tmp_path):
    """Prereg data rule: every file reproducible by a reviewer."""
    payload = b"col\n1\n2\n"
    digest = hashlib.sha256(payload).hexdigest()

    class _Stub:
        requests = 0

        def plan(self, **_):
            return []

        def list_keys(self, prefix):
            return []

    monkeypatch.setattr(fwd, "plan_files", lambda vision, symbols=None: [{
        "dataset": "spot", "symbol": "BTCUSDT",
        "name": "BTCUSDT-1h-2026-11-01.zip",
        "key": "data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-11-01.zip"}])

    class _Vision(_Stub):
        def download_verified(self, key, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write_kline_zip(dest, 24)
            return {"key": key, "path": str(dest), "sha256": digest,
                    "bytes": len(payload), "resumed": False, "verified": True}

    out = tmp_path / "tracked.json"
    doc = fwd.fetch(tmp_path / "data", _Vision(),
                    manifest_out=out)
    assert out.exists(), "the tracked manifest copy must be written"
    rec = doc["files"][0]
    for field in ("url", "bytes", "sha256", "rows", "retrieved_at"):
        assert field in rec, field
    assert rec["url"].startswith("https://data.binance.vision/")
    assert rec["rows"] == 24
    assert json.loads(out.read_text())["files"] == doc["files"]


def _write_kline_zip(dest: Path, rows: int) -> None:
    stamp = pd.Timestamp("2026-11-01", tz="UTC")
    idx = pd.date_range(stamp, periods=rows, freq="h", tz="UTC")
    body = ("open_time,open,high,low,close,volume,close_time,quote_volume,"
            "count,taker_base,taker_quote,ignore\n")
    lines = [f"{t_ms},100,100,100,100,1,{t_ms + 3599999},1000,5,0.5,50,0"
             for t_ms in (int(_ms(pd.DatetimeIndex([t]))[0]) for t in idx)]
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(dest.with_suffix("").name + ".csv", body + "\n".join(lines))
