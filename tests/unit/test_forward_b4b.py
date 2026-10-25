"""B4b forward recorder: window refusal, point-in-time book, gates, one look.

No network: every test drives the pure functions (``plan_files`` with a stub
client, ``simulate``/``evaluate_frames`` with synthetic forward frames).
"""
from __future__ import annotations

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
            adv: float = 5.0e8, sigma: float = 0.01):
    """Flat prices, a rich/low funding cycle, plenty of ADV."""
    rng = np.random.default_rng(7)
    hours = pd.date_range(START, periods=days * 24, freq="h", tz="UTC")
    # gentle walk so realized sigma is nonzero, delta-neutral P&L stays small
    steps = rng.normal(0.0, sigma / np.sqrt(24), len(hours))
    closes = price * np.exp(np.cumsum(steps))
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
    # day 21 of the forward clock is the earliest entry the prereg allows
    assert first_fill >= "2026-11-21"
    assert sim["round_trips"] >= 0


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
                                 "drawdown", "years", "median_participation",
                                 "max_participation", "bootstrap",
                                 "newey_west_t"}
    assert doc["gates"]["pbo"] is None
    assert "pbo" in doc["structural_null_gates"]


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
    frames = _frames(days=days)
    for sym, per in frames.items():
        for dataset, df, stamp in (("spot", per["spot"], "open_ms"),
                                   ("perp", per["perp"], "open_ms"),
                                   ("funding", per["funding"], "calc_ms")):
            folder = root / dataset / sym
            folder.mkdir(parents=True, exist_ok=True)
            idx = pd.to_datetime(df[stamp], unit="ms", utc=True)
            if dataset == "funding":
                lines = ["calc_time,funding_interval_hours,last_funding_rate"]
                lines += [f"{int(t.timestamp()*1000)},8,{r}"
                          for t, r in zip(idx, df["rate"], strict=True)]
                name = f"{sym}-fundingRate-{idx.min().strftime('%Y-%m')}.zip"
            else:
                lines = [f"{int(t.timestamp()*1000)},{float(o)!r},"
                         f"{float(o)!r},{float(o)!r},{float(c)!r},1,"
                         f"{int(t.timestamp()*1000)+3599999},{float(v)!r},"
                         f"1,1,1,0"
                         for t, o, c, v in zip(idx, df["open"], df["close"],
                                               df["quote_volume"],
                                               strict=True)]
                name = f"{sym}-1h-{idx.min().strftime('%Y-%m-%d')}.zip"
            with zipfile.ZipFile(folder / name, "w") as zf:
                zf.writestr("data.csv", "\n".join(lines) + "\n")
