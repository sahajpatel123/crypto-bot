"""V-REG evaluator tests: file rules, clock, signal, books, cells, stopping, verify.

All fixtures are SYNTHETIC (hand-built bars/funding in tmp dirs or memory).
No Vision pull, no forward-dated real file is ever decoded, no holdout/Oct
file is touched. Guard-deletion proofs: each named guard below was deleted
in a scratch copy and the named test was confirmed to fail (see PR body).
"""
from __future__ import annotations

import datetime as dt
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

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "forward_vreg", str(ROOT / "tools" / "forward_vreg.py"))
fwd = importlib.util.module_from_spec(_spec)
sys.modules["forward_vreg"] = fwd  # dataclasses need it registered
_spec.loader.exec_module(fwd)
_fcspec = importlib.util.spec_from_file_location(
    "forward_fcarry_x", str(ROOT / "tools" / "forward_fcarry.py"))
fcarry = importlib.util.module_from_spec(_fcspec)
sys.modules["forward_fcarry_x"] = fcarry
_fcspec.loader.exec_module(fcarry)

DAY0 = pd.Timestamp("2026-11-01", tz="UTC")
SYMS = ("BTCUSDT", "ETHUSDT")
VREG_SHA256 = ("78eb46aa5a2acb7897b7c39e44fda24fcb2e29c0eee07c0def8f8721dd3e3784")


# -- synthetic fixture builders -----------------------------------------------
def _bars(n_days, close_fn, qv=1_000_000.0, start=DAY0, open_fn=None):
    rows = []
    for d in range(n_days):
        for h in range(24):
            t = start + pd.Timedelta(days=d, hours=h)
            c = float(close_fn(d, h))
            o = float(open_fn(d, h)) if open_fn else c
            rows.append({"open_ms": int(t.value // 1_000_000), "open": o,
                         "close": c, "quote_volume": qv / 24.0})
    return pd.DataFrame(rows)


def _funding(n_days, rate_fn, start=DAY0):
    rows = []
    for d in range(n_days):
        for hh in (0, 8, 16):
            t = start + pd.Timedelta(days=d, hours=hh)
            rows.append({"calc_ms": int(t.value // 1_000_000),
                         "rate": float(rate_fn(d, hh))})
    return pd.DataFrame(rows)


def _frames(n_days, close_fn, rate_fn, symbols=SYMS, **kw):
    return {s: {"perp": _bars(n_days, close_fn, **kw),
                "funding": _funding(n_days, rate_fn)} for s in symbols}


def _wiggle(d, h, base=100.0, amp=0.001):
    return base * (1.0 + amp * (1 if d % 2 == 0 else -1))


def _spike_closes(spacing=14, growth=1.45, s0=0.001, calm=65, span=210,
                  revert=False, seed=7):
    """Growing alternating single-hour spikes after a calm warmup.

    Concentrated spikes keep the 5d short window hot while older, smaller
    spikes fade in the 60d long window, so Ratio(D) clears R=2.5 on most
    post-spike days. With revert=True each spike fully mean-reverts over
    the next 48h (profitable fades); otherwise moves are permanent
    (fades earn ~zero gross, below all-in cost).
    """
    rng = np.random.RandomState(seed)
    n = calm + span
    noise = [1e-6 * rng.randn() for _ in range(n * 24)]
    extra = [0.0] * (n * 24)
    for i, d in enumerate(range(calm, calm + span, spacing)):
        s = s0 * (growth ** i) * (1 if i % 2 == 0 else -1)
        extra[d * 24 + 12] += s
        if revert:
            for k in range(1, 49):
                idx = d * 24 + 12 + k
                if idx < len(extra):
                    extra[idx] += -s / 48.0
    closes = [100.0]
    for k in range(n * 24):
        closes.append(closes[-1] * (1 + noise[k] + extra[k]))
    return closes[1:]


def _spike_frames(**kw):
    closes = _spike_closes(**kw)
    n_days = len(closes) // 24
    out = {}
    for s in SYMS:
        rows = []
        t = DAY0
        for c in closes:
            rows.append({"open_ms": int(t.value // 1_000_000), "open": c,
                         "close": c, "quote_volume": 1_000_000.0 / 24.0})
            t += pd.Timedelta(hours=1)
        out[s] = {"perp": pd.DataFrame(rows),
                  "funding": _funding(n_days, lambda d, hh: 1e-4)}
    return out


def _write_kline_zip(path: Path, df: pd.DataFrame) -> None:
    lines = []
    for r in df.itertuples():
        lines.append(f"{int(r.open_ms)},{r.open},{r.open},{r.open},{r.close},"
                     f"1.0,{int(r.open_ms) + 3600000},{r.quote_volume},"
                     f"10,0.5,0.5,0")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(path.stem + ".csv", "\n".join(lines) + "\n")


def _write_funding_zip(path: Path, df: pd.DataFrame) -> None:
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    for r in df.itertuples():
        lines.append(f"{int(r.calc_ms)},8,{r.rate}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(path.stem + ".csv", "\n".join(lines) + "\n")


def _write_manifest(root: Path) -> None:
    files = []
    for p in sorted(root.rglob("*.zip")):
        rel = p.relative_to(root)
        files.append({"dataset": rel.parts[0], "symbol": rel.parts[1],
                      "name": p.name,
                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    (root / "manifest.json").write_text(json.dumps({"files": files}))


def _write_root(root: Path, frames: dict) -> None:
    # Persist in-memory synthetic frames as forward zips + manifest.
    for s, f in frames.items():
        df = f["perp"]
        idx = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
        for day, grp in df.groupby(idx.dt.date):
            name = f"{s}-1h-{day}.zip"
            _write_kline_zip(root / "perp" / s / name, grp)
        fdf = f["funding"]
        fidx = pd.to_datetime(fdf["calc_ms"], unit="ms", utc=True)
        for (y, m), grp in fdf.groupby([fidx.dt.year, fidx.dt.month]):
            name = f"{s}-fundingRate-{y}-{m:02d}.zip"
            _write_funding_zip(root / "funding" / s / name, grp)
    _write_manifest(root)


# -- file rules -----------------------------------------------------------------
def test_forward_window_rules():
    assert fwd.is_forward_file("BTCUSDT-1h-2026-11-01.zip") is True
    assert fwd.is_forward_file("BTCUSDT-1h-2026-10-17.zip") is False
    assert fwd.is_forward_file("BTCUSDT-1h-2026-10-18.zip") is True
    assert fwd.is_forward_file("BTCUSDT-fundingRate-2026-11.zip") is True
    assert fwd.is_forward_file("BTCUSDT-fundingRate-2026-10.zip") is False
    with pytest.raises(ValueError):
        fwd.is_forward_file("undated-junk.zip")


def test_refuses_pre_window_filenames_on_disk(tmp_path):
    root = tmp_path / "data"
    bad = root / "perp" / "BTCUSDT" / "BTCUSDT-1h-2026-10-17.zip"
    _write_kline_zip(bad, _bars(1, lambda d, h: 100.0,
                               start=pd.Timestamp("2026-10-17", tz="UTC")))
    _write_manifest(root)
    with pytest.raises(fwd.InputBeforeForwardWindow):
        fwd.load_frames(root)


def test_refuses_rows_outside_own_file_window(tmp_path):
    # A November-named daily file carrying October rows (renamed holdout).
    root = tmp_path / "data"
    bad = root / "perp" / "BTCUSDT" / "BTCUSDT-1h-2026-11-05.zip"
    _write_kline_zip(bad, _bars(1, lambda d, h: 100.0,
                               start=pd.Timestamp("2026-10-20", tz="UTC")))
    _write_manifest(root)
    with pytest.raises(fwd.InputBeforeForwardWindow, match="outside"):
        fwd.load_frames(root)


def test_refuses_renamed_october_funding(tmp_path):
    # The 14-day smuggle: Oct 18..31 rows in a file renamed to 2026-11.
    root = tmp_path / "data"
    bad = root / "funding" / "ETHUSDT" / "ETHUSDT-fundingRate-2026-11.zip"
    _write_funding_zip(bad, _funding(
        14, lambda d, hh: 1e-4,
        start=pd.Timestamp("2026-10-18", tz="UTC")))
    _write_manifest(root)
    with pytest.raises(fwd.InputBeforeForwardWindow, match="outside"):
        fwd.load_frames(root)


def test_checksum_mismatch_refuses(tmp_path):
    root = tmp_path / "data"
    p = root / "perp" / "BTCUSDT" / "BTCUSDT-1h-2026-11-01.zip"
    _write_kline_zip(p, _bars(1, lambda d, h: 100.0))
    _write_manifest(root)
    doc = json.loads((root / "manifest.json").read_text())
    doc["files"][0]["sha256"] = "0" * 64  # tampered record
    (root / "manifest.json").write_text(json.dumps(doc))
    with pytest.raises(fwd.ChecksumRefusal, match="mismatch"):
        fwd.load_frames(root)


def test_unpinned_file_refuses(tmp_path):
    root = tmp_path / "data"
    p = root / "perp" / "BTCUSDT" / "BTCUSDT-1h-2026-11-01.zip"
    _write_kline_zip(p, _bars(1, lambda d, h: 100.0))
    (root / "manifest.json").write_text(json.dumps({"files": []}))
    with pytest.raises(fwd.ChecksumRefusal, match="unpinned"):
        fwd.load_frames(root)


def test_valid_forward_zips_load(tmp_path):
    root = tmp_path / "data"
    for s in SYMS:
        _write_kline_zip(
            root / "perp" / s / f"{s}-1h-2026-11-01.zip",
            _bars(1, lambda d, h: 100.0))
        _write_funding_zip(
            root / "funding" / s / f"{s}-fundingRate-2026-11.zip",
            _funding(1, lambda d, hh: 1e-4))
    _write_manifest(root)
    frames, manifest = fwd.load_frames(root)
    assert len(manifest["files"]) == 4
    assert frames["BTCUSDT"]["perp"].shape[0] == 24
    assert set(frames["BTCUSDT"]) == {"perp", "funding"}


def test_spot_files_are_not_inputs(tmp_path):
    # Perp-only execution: stray spot zips are never planned or decoded.
    assert "spot" not in fwd.wanted_prefixes("BTCUSDT")
    root = tmp_path / "data"
    for s in SYMS:
        _write_kline_zip(
            root / "perp" / s / f"{s}-1h-2026-11-01.zip",
            _bars(1, lambda d, h: 100.0))
        _write_kline_zip(
            root / "spot" / s / f"{s}-1h-2026-11-01.zip",
            _bars(1, lambda d, h: 999.0))  # ignored junk price
        _write_funding_zip(
            root / "funding" / s / f"{s}-fundingRate-2026-11.zip",
            _funding(1, lambda d, hh: 1e-4))
    _write_manifest(root)
    (root / "manifest.json").write_text(json.dumps({
        "files": [r for r in json.loads(
            (root / "manifest.json").read_text())["files"]
            if r["dataset"] != "spot"]}))
    frames, manifest = fwd.load_frames(root)
    assert set(frames["BTCUSDT"]) == {"perp", "funding"}
    assert float(frames["BTCUSDT"]["perp"]["close"].iloc[0]) == 100.0


# -- study clock / stale marks --------------------------------------------------
def test_day_without_bars_is_not_a_forward_day():
    frames = _frames(40, _wiggle, lambda d, hh: 5e-4)
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    full = fwd.study_days(prep)
    assert len(full) == 39
    # Drop all bars for 3 mid-range days (both symbols).
    for s in SYMS:
        df = frames[s]["perp"].copy()
        idx = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
        keep = ~idx.dt.date.isin(
            [dt.date(2026, 11, 20), dt.date(2026, 11, 21),
             dt.date(2026, 11, 22)])
        frames[s]["perp"] = df[keep].reset_index(drop=True)
    prep2 = {s: fwd._prep(f) for s, f in frames.items()}
    gap = fwd.study_days(prep2)
    assert len(gap) == len(full) - 3
    assert "2026-11-21" not in [str(d.date()) for d in gap]


def test_forward_days_require_funding_not_just_bars():
    frames = _frames(40, _wiggle, lambda d, hh: 5e-4)
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    full = fwd.study_days(prep)
    # Drop TWO consecutive days of settlements: that empties the
    # (day-1d, day] window of the day in the middle. (Dropping one day
    # never empties a window: windows span day boundaries by design.)
    for s in SYMS:
        df = frames[s]["funding"].copy()
        idx = pd.to_datetime(df["calc_ms"], unit="ms", utc=True)
        keep = ~idx.dt.date.isin([dt.date(2026, 11, 20),
                                  dt.date(2026, 11, 21)])
        frames[s]["funding"] = df[keep].reset_index(drop=True)
    prep2 = {s: fwd._prep(f) for s, f in frames.items()}
    gap = fwd.study_days(prep2)
    assert len(gap) < len(full)
    assert "2026-11-21" not in [str(d.date()) for d in gap]


def test_years_gate_arithmetic():
    assert fwd.years_assessable_forward_day() == 121
    assert str(fwd.years_assessable_on()) == "2027-03-01"
    rows = [{"day": f"2026-12-{d:02d}", "net_ret": 0.001} for d in range(1, 32)]
    rows += [{"day": f"2027-01-{d:02d}", "net_ret": 0.001} for d in range(1, 32)]
    ok, stats = fwd._year_gate(rows)
    assert ok is None  # only 31+31 days: no 60-day year yet
    rows += [{"day": f"2027-02-{d:02d}", "net_ret": 0.001} for d in range(1, 30)]
    rows += [{"day": f"2026-11-{d:02d}", "net_ret": 0.001} for d in range(1, 31)]
    ok, stats = fwd._year_gate(rows)
    assert ok is True  # 61 + 60 days, both positive


# -- signal / RV windows ----------------------------------------------------------
def test_rv_warmup_blocks_early_decisions():
    frames = _frames(70, _wiggle, lambda d, hh: 1e-4)
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    bars = prep["BTCUSDT"]["perp"]
    assert fwd._rv_signal(bars, DAY0 + pd.Timedelta(days=30)) is None
    assert fwd._rv_signal(bars, DAY0 + pd.Timedelta(days=56)) is None
    sig = fwd._rv_signal(bars, DAY0 + pd.Timedelta(days=65))
    assert sig is not None
    assert sig["ratio"] > 0 and np.isfinite(sig["tr"])


def test_rv_ratio_fires_on_vol_expansion():
    frames = _spike_frames(span=80)
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    bars = prep["BTCUSDT"]["perp"]
    calm = fwd._rv_signal(bars, DAY0 + pd.Timedelta(days=64))
    assert calm is not None and calm["ratio"] < 1.5
    hot = fwd._rv_signal(bars, DAY0 + pd.Timedelta(days=67))
    assert hot is not None and hot["ratio"] >= 2.5


def test_rv_lookahead_guard():
    # A bar AT the decision day must not move the signal: windows are
    # strictly before D. Widening to <= D changes the answer (proven by
    # deleting the guard in a scratch copy: this test then fails).
    frames = _frames(70, _wiggle, lambda d, hh: 1e-4)
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    day = DAY0 + pd.Timedelta(days=65)
    before = fwd._rv_signal(prep["BTCUSDT"]["perp"], day)
    poisoned = prep["BTCUSDT"]["perp"].copy()
    at_d = poisoned.index.get_loc(day)
    poisoned.iloc[at_d, poisoned.columns.get_loc("close")] *= 2.0
    after = fwd._rv_signal(poisoned, day)
    assert before is not None and after is not None
    assert after == before
    # The vectorized twin must exclude D the same way.
    mkt = fwd._Market(prep["BTCUSDT"]["perp"])
    mkt_p = fwd._Market(poisoned)
    mb = fwd._rv_signal_from_market(mkt, day)
    ma = fwd._rv_signal_from_market(mkt_p, day)
    assert mb is not None and ma is not None
    assert ma == mb == before


def test_tr_zero_blocks_trade():
    # Alternating daily closes (100/101: sigma > 0, ADV filled) with one
    # exact intraday round trip (base -> base+10 -> base) mid-short-window:
    # first/last short-window closes share day parity, so TR(D) ==
    # ln(x/x) == 0.0 exactly while the vol ratio still clears 2.5 --
    # and TR == 0.0 is then the SOLE reason no trade prints.
    n_days = 70
    closes = []
    for d in range(n_days):
        base = 100.0 if d % 2 == 0 else 101.0
        for h in range(24):
            c = base
            if d == 62 and h == 12:
                c = base + 10.0
            closes.append(c)
    rows = []
    t = DAY0
    for c in closes:
        rows.append({"open_ms": int(t.value // 1_000_000), "open": c,
                     "close": c, "quote_volume": 1_000_000.0 / 24.0})
        t += pd.Timedelta(hours=1)
    frames = {s: {"perp": pd.DataFrame(rows),
                  "funding": _funding(n_days, lambda d, hh: 1e-4)}
              for s in SYMS}
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    for dd in (64, 65):
        sig = fwd._rv_signal(prep["BTCUSDT"]["perp"],
                             DAY0 + pd.Timedelta(days=dd))
        assert sig is not None and sig["ratio"] >= 2.5
        assert sig["tr"] == 0.0
        s2, a2 = fwd._trailing_stats(prep["BTCUSDT"]["perp"],
                                     DAY0 + pd.Timedelta(days=dd))
        assert s2 > 0 and a2 > 0  # sizing windows filled: TR is the blocker
    for cell in fwd.CELLS:
        out = fwd.simulate(frames, fwd.VregConfig(r=cell[0], h=cell[1]))
        assert out["round_trips"] == 0, cell
        assert out["trades"] == []


def test_reference_matches_market_twins():
    # The vectorized hot loop must equal the readable reference on gappy,
    # spiky data (drops 30 scattered hours + keeps Oct-style edges out).
    frames = _spike_frames(span=80)
    rng = np.random.RandomState(11)
    for s in SYMS:
        df = frames[s]["perp"]
        drop = rng.choice(len(df), size=30, replace=False)
        frames[s]["perp"] = df.drop(index=drop).reset_index(drop=True)
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    days = fwd.study_days(prep)
    assert len(days) > 60
    for day in days[::7]:
        for s in SYMS:
            p = prep[s]
            a = fwd._rv_signal(p["perp"], day)
            b = fwd._rv_signal_from_market(p["market"], day)
            assert (a is None) == (b is None), (day, s)
            if a is not None:
                for k in ("ratio", "tr", "rv_short", "rv_long"):
                    assert a[k] == pytest.approx(b[k], rel=1e-9), (day, s, k)
            ta = fwd._trailing_stats(p["perp"], day)
            tb = fwd._trailing_from_market(p["market"], day)
            assert ta[0] == pytest.approx(tb[0], rel=1e-9, abs=1e-18)
            assert ta[1] == pytest.approx(tb[1], rel=1e-9)


def test_presence_rule_blocks_thin_windows():
    frames = _spike_frames(span=80)
    day = DAY0 + pd.Timedelta(days=67)
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    assert fwd._rv_signal(prep["BTCUSDT"]["perp"], day) is not None
    # Drop 10 of the 120 short-window bars (-> 110 < 114): no decision.
    df = frames["BTCUSDT"]["perp"]
    idx = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
    in_short = (idx >= day - pd.Timedelta(hours=120)) & (idx < day)
    victims = df[in_short].index[:10]
    frames["BTCUSDT"]["perp"] = df.drop(index=victims).reset_index(drop=True)
    prep2 = {s: fwd._prep(f) for s, f in frames.items()}
    assert fwd._rv_signal(prep2["BTCUSDT"]["perp"], day) is None


# -- costs / accounting -----------------------------------------------------------
def test_cost_identity_17bps_plus_impact():
    book = fwd.Book(cash=1000.0, cfg=fwd.VregConfig())
    cost, part = book.cost_of(10_000.0, sigma=0.02, adv=1_000_000.0)
    assert cost == pytest.approx(8.5 + 10_000.0 * 0.5 * 0.02 * 0.1)
    assert part == pytest.approx(0.01)
    book2 = fwd.Book(cash=1000.0, cfg=fwd.VregConfig(adverse_mult=2.0))
    cost2, _ = book2.cost_of(10_000.0, sigma=0.02, adv=1_000_000.0)
    assert cost2 == pytest.approx(2.0 * cost)  # 2x doubles fee AND impact
    assert pytest.approx(17.0) == fwd.FEES_PER_ROUND_TRIP_BPS


def test_accounting_identity_flat_marks():
    # One jump then flat: entry/exit marks equal, so E = E0 + funding -
    # costs exactly, in every cell that trades.
    closes = [100.0] * (70 * 24)
    for i in range(63 * 24, 70 * 24):
        closes[i] = 105.0
    rows = []
    t = DAY0
    for c in closes:
        rows.append({"open_ms": int(t.value // 1_000_000), "open": c,
                     "close": c, "quote_volume": 1_000_000.0 / 24.0})
        t += pd.Timedelta(hours=1)
    frames = {s: {"perp": pd.DataFrame(rows),
                  "funding": _funding(70, lambda d, hh: 1e-4)}
              for s in SYMS}
    for cell in fwd.CELLS:
        out = fwd.simulate(frames, fwd.VregConfig(r=cell[0], h=cell[1]))
        assert out["round_trips"] >= 2, cell
        final = out["rows"][-1]["equity"]
        expect = 1000.0 + out["funding_income"] - out["fees_paid"]
        assert final == pytest.approx(expect, rel=1e-9), cell


def test_every_fill_executes_at_next_bar_open():
    frames = _frames(70, lambda d, h: 100.0 + d,
                      lambda d, hh: 1e-4,
                      open_fn=lambda d, h: 100.0 + d)
    # Graft one jump so the fade actually fires on the ramp.
    for s in SYMS:
        df = frames[s]["perp"]
        j = 63 * 24 + 12
        df.loc[j:, "close"] = df.loc[j:, "close"] * 1.05
        frames[s]["perp"] = df
    out = fwd.simulate(frames, fwd.VregConfig(r=1.5, h=2))
    assert len(out["fills"]) >= 2
    for fill in out["fills"]:
        day = pd.Timestamp(fill["day"], tz="UTC")
        expect = 100.0 + (day - DAY0).days  # open of the 00:00 bar
        assert fill["price"] == pytest.approx(expect)


def test_sizing_caps():
    # Low ADV binds the 1% cap exactly; deep ADV leaves 0.5*E sizing.
    tiny = _spike_frames()
    for s in SYMS:
        tiny[s]["perp"]["quote_volume"] = 100.0 / 24.0
    out = fwd.simulate(tiny, fwd.VregConfig(r=1.5, h=2))
    assert out["fills"]
    assert out["fills"][0]["participation"] == pytest.approx(0.01)
    deep = _spike_frames()
    for s in SYMS:
        deep[s]["perp"]["quote_volume"] = 1e12 / 24.0
    out2 = fwd.simulate(deep, fwd.VregConfig(r=1.5, h=2))
    assert out2["fills"]
    assert out2["fills"][0]["notional"] == pytest.approx(500.0)
    assert out2["fills"][0]["participation"] < 0.01


def test_same_day_exits_before_entries():
    # Jump at day 63 (entry day 64, H=2 -> exit day 66) plus a second jump
    # at day 65: day 66 must exit AND re-enter, chaining round trips.
    closes = [100.0] * (70 * 24)
    for i in range(63 * 24, 65 * 24):
        closes[i] = 105.0
    for i in range(65 * 24, 70 * 24):
        closes[i] = 99.0
    rows = []
    t = DAY0
    for c in closes:
        rows.append({"open_ms": int(t.value // 1_000_000), "open": c,
                     "close": c, "quote_volume": 1_000_000.0 / 24.0})
        t += pd.Timedelta(hours=1)
    frames = {s: {"perp": pd.DataFrame(rows),
                  "funding": _funding(70, lambda d, hh: 1e-4)}
              for s in SYMS}
    out = fwd.simulate(frames, fwd.VregConfig(r=1.5, h=2))
    by_sym: dict[str, list] = {}
    for tr in out["trades"]:
        by_sym.setdefault(tr["symbol"], []).append(tr)
    chained = any(
        any(b["entry_day"] == a["exit_day"]
            for a in legs for b in legs if a is not b)
        for legs in by_sym.values())
    assert chained, "exit day must also accept a new entry"


# -- funding / imputation -----------------------------------------------------------
def _jump_frames(jump, n_days=70, rate=2e-4):
    closes = [100.0] * (n_days * 24)
    for i in range(63 * 24, n_days * 24):
        closes[i] = 100.0 * (1 + jump)
    rows = []
    t = DAY0
    for c in closes:
        rows.append({"open_ms": int(t.value // 1_000_000), "open": c,
                     "close": c, "quote_volume": 1_000_000.0 / 24.0})
        t += pd.Timedelta(hours=1)
    return {s: {"perp": pd.DataFrame(rows),
                "funding": _funding(n_days, lambda d, hh: rate)}
            for s in SYMS}


def test_funding_signs():
    # Up-jump -> TR>0 -> SHORT receives +rate; down-jump -> LONG pays it.
    short_book = fwd.simulate(_jump_frames(0.05), fwd.VregConfig(r=1.5, h=2))
    long_book = fwd.simulate(_jump_frames(-0.05), fwd.VregConfig(r=1.5, h=2))
    assert short_book["round_trips"] >= 2
    assert long_book["round_trips"] >= 2
    assert short_book["funding_income"] > 0
    assert long_book["funding_income"] < 0
    sides = {t["side"] for t in short_book["trades"]}
    assert sides == {"SHORT"}
    sides = {t["side"] for t in long_book["trades"]}
    assert sides == {"LONG"}


def test_missing_settlement_imputes_adverse():
    frames = _jump_frames(0.05)
    whole = fwd.simulate(frames, fwd.VregConfig(r=1.5, h=2))
    assert whole["round_trips"] >= 2
    # Drop the 08:00 settlement on a hold day for BTC only: the day keeps
    # its other settlements (still counts) but the position imputes.
    gapped = _jump_frames(0.05)
    df = gapped["BTCUSDT"]["funding"]
    idx = pd.to_datetime(df["calc_ms"], unit="ms", utc=True)
    victim = (idx.dt.date == dt.date(2027, 1, 5)) & (idx.dt.hour == 8)
    assert victim.sum() == 1
    gapped["BTCUSDT"]["funding"] = df[~victim].reset_index(drop=True)
    gap = fwd.simulate(gapped, fwd.VregConfig(r=1.5, h=2))
    flagged = [t for t in gap["trades"]
               if t["symbol"] == "BTCUSDT" and t["imputed_funding"]]
    assert len(flagged) == 1 and flagged[0]["n_imputed"] == 1
    assert gap["funding_income"] < whole["funding_income"]  # SHORT pays it


def test_imputation_uses_point_in_time_baseline():
    # Rising rates: the missing slot imputes the max seen strictly before
    # it, never the larger rates that print later.
    n_days = 70
    frames = _jump_frames(0.05, n_days=n_days, rate=1e-4)
    df = frames["BTCUSDT"]["funding"].copy()
    idx = pd.to_datetime(df["calc_ms"], unit="ms", utc=True)
    df["rate"] = [1e-4 * (1 + (ts - DAY0).days) for ts in idx]
    frames["BTCUSDT"]["funding"] = df
    frames["ETHUSDT"]["funding"] = df.copy()
    slot_day = dt.date(2027, 1, 5)
    slot_ts = pd.Timestamp("2027-01-05 08:00", tz="UTC")
    victim = (idx.dt.date == slot_day) & (idx.dt.hour == 8)
    gapped = {s: {"perp": f["perp"], "funding": f["funding"].copy()}
              for s, f in frames.items()}
    gdf = gapped["BTCUSDT"]["funding"]
    gapped["BTCUSDT"]["funding"] = gdf[~victim].reset_index(drop=True)
    gap = fwd.simulate(gapped, fwd.VregConfig(r=1.5, h=2))
    flagged = [t for t in gap["trades"]
               if t["symbol"] == "BTCUSDT" and t["imputed_funding"]]
    assert len(flagged) == 1
    before = df[pd.to_datetime(df["calc_ms"], unit="ms", utc=True) < slot_ts]
    pit_max = float(before["rate"].abs().max())
    later_max = float(df["rate"].abs().max())
    assert later_max > pit_max  # the trap: future rates are bigger
    # Helper-level exactness: one missing slot among observed dust.
    fund = fwd._prep(gapped["BTCUSDT"])["funding"]
    lo = pd.Timestamp("2027-01-05", tz="UTC")
    hi = pd.Timestamp("2027-01-06", tz="UTC")
    delta, n_imp = fwd._funding_accrual(
        fund, entry_time=pd.Timestamp("2026-11-02", tz="UTC"),
        lo=lo, hi=hi, exit_bound=None, qty=1.0, side=1, mark=100.0,
        adverse=False, symbol="BTCUSDT", day=hi)
    assert n_imp == 1
    obs = fund[(fund.index > lo) & (fund.index <= hi)]
    expect = -sum(obs) * 100.0 - pit_max * 100.0
    assert delta == pytest.approx(expect)


def test_imputation_refused_without_baseline():
    p = {"funding": pd.Series(dtype=float)}
    with pytest.raises(fwd.FundingImputationRefused):
        fwd._funding_accrual(
            p["funding"], entry_time=pd.Timestamp("2026-11-02", tz="UTC"),
            lo=pd.Timestamp("2026-11-02", tz="UTC"),
            hi=pd.Timestamp("2026-11-03", tz="UTC"), exit_bound=None,
            qty=1.0, side=1, mark=100.0, adverse=False,
            symbol="BTCUSDT", day=pd.Timestamp("2026-11-03", tz="UTC"))


def test_run_cell_set_drops_refused_day(monkeypatch):
    frames = _frames(40, _wiggle, lambda d, hh: 1e-4)
    calls = []
    victim = pd.Timestamp("2026-11-20", tz="UTC")

    def fake_simulate(frames_by_symbol, cfg, exclude_days=None):
        calls.append(set(exclude_days or set()))
        if not exclude_days:
            raise fwd.FundingImputationRefused("BTCUSDT", victim, victim)
        return {"round_trips": 0}

    monkeypatch.setattr(fwd, "simulate", fake_simulate)
    out, dropped = fwd._run_cell_set(frames, adverse=False)
    assert dropped == ["2026-11-20"]
    assert set(fwd.CELLS) == set(out)
    assert any(victim in c for c in calls)  # re-ran with the day excluded


def test_adverse_funding_doubles_debits_zeroes_credits():
    idx = pd.to_datetime(["2026-11-02 08:00", "2026-11-02 16:00",
                          "2026-11-03 00:00"], utc=True)
    funding = pd.Series([1e-4, -2e-4, 3e-4], index=idx)
    kw = dict(entry_time=pd.Timestamp("2026-11-01", tz="UTC"),
              lo=pd.Timestamp("2026-11-02", tz="UTC"),
              hi=pd.Timestamp("2026-11-03", tz="UTC"), exit_bound=None,
              qty=2.0, mark=100.0, symbol="BTCUSDT",
              day=pd.Timestamp("2026-11-03", tz="UTC"))
    base, _ = fwd._funding_accrual(funding, side=1, adverse=False, **kw)
    adv, _ = fwd._funding_accrual(funding, side=1, adverse=True, **kw)
    # LONG: debits (1e-4, 3e-4) double; the -2e-4 credit goes to zero.
    assert base == pytest.approx(-(1e-4 - 2e-4 + 3e-4) * 200.0)
    assert adv == pytest.approx(-(2e-4 + 6e-4) * 200.0)
    base_s, _ = fwd._funding_accrual(funding, side=-1, adverse=False, **kw)
    adv_s, _ = fwd._funding_accrual(funding, side=-1, adverse=True, **kw)
    assert adv_s == pytest.approx(2 * -2e-4 * 200.0)  # only debit doubles


def test_turnover_and_diagnostics_reported_never_gated():
    frames = _spike_frames(revert=True)
    doc = fwd.evaluate_frames(frames)
    assert doc["powered"] is True
    assert "turnover" not in doc["gates"]
    assert doc["gross_turnover_per_year_descriptive"] > 0
    assert set(doc["diagnostics"]) >= {"per_side", "per_symbol"}
    assert all("turnover" not in g for g in
               doc["failed_gates"] + doc["unassessable_gates"])
    for side in ("LONG", "SHORT"):
        assert doc["diagnostics"]["per_side"][side]["n"] > 0


# -- cells / selection / trial vector ------------------------------------------------
def test_six_cells_run_independently():
    frames = _spike_frames()
    rts = {}
    for cell in fwd.CELLS:
        out = fwd.simulate(frames, fwd.VregConfig(r=cell[0], h=cell[1]))
        rts[cell] = out["round_trips"]
    assert len(rts) == 6
    assert all(v >= 20 for v in rts.values())
    # A lower vol-ratio bar fires at least as often (same H).
    assert rts[(1.5, 2)] >= rts[(2.5, 2)]
    assert rts[(1.5, 5)] >= rts[(2.5, 5)]
    # A shorter hold completes at least as many trips (same R).
    assert rts[(1.5, 2)] >= rts[(1.5, 5)]
    assert rts[(2.5, 2)] >= rts[(2.5, 5)]


def test_selection_picks_max_sharpe_with_lexicographic_tiebreak():
    cells = list(fwd.CELLS)
    sharpes = {c: 0.1 * i for i, c in enumerate(cells)}
    assert fwd._select_cell(sharpes, set(cells)) == (2.5, 5)
    tied = {c: 0.5 for c in cells}
    assert fwd._select_cell(tied, set(cells)) == (1.5, 2)
    # R orders before H.
    trap = {(1.5, 5): 1.0, (2.0, 2): 1.0,
            **{c: 0.1 for c in cells if c not in ((1.5, 5), (2.0, 2))}}
    assert fwd._select_cell(trap, set(cells)) == (1.5, 5)
    # Non-finite never wins.
    nan_case = {c: 0.3 for c in cells}
    nan_case[(1.5, 2)] = float("nan")
    assert fwd._select_cell(nan_case, set(cells)) == (1.5, 5)


def test_dsr_trial_count_is_6():
    frames = _spike_frames(revert=True)
    doc = fwd.evaluate_frames(frames)
    assert doc["trial_sharpes_n"] == 6
    assert doc["dsr_detail"]["n_trials"] == 6
    assert doc["dsr_detail"]["n_for_q"] == 6
    assert set(doc["dsr_sensitivities"]) >= {"n12", "n25"}


def test_no_external_numbers():
    # The prereg refuses any B4/B4b/F-CARRY/H/B/D1 number as evidence:
    # no readers exist and no entry point accepts an external Sharpe.
    import inspect
    for name in ("B4_DEV_ARTIFACT", "B4B_VERDICT_DEFAULT",
                 "_read_b4_dev_sharpes", "_read_b4b_forward_sharpe"):
        assert not hasattr(fwd, name), name
    for fn in (fwd.evaluate_frames, fwd.run, fwd.verify,
               fwd.forward_command, fwd.status_doc):
        params = set(inspect.signature(fn).parameters)
        assert not (params & {"b4b_verdict", "b4b_sharpe", "external_sharpe"})


# -- stopping rule / verdict ------------------------------------------------------------
def test_powering_needs_90d_and_20rt_every_cell():
    frames = _frames(100, _wiggle, lambda d, hh: 1e-4)
    doc = fwd.evaluate_frames(frames)
    assert doc["forward_days"] == 99
    assert doc["powered"] is False  # calm: no cell reaches 20 RTs
    assert doc["status"] == "UNDERPOWERED"
    assert "stopping rule" in doc["status_reason"]
    assert doc["immediate_kill"] is None  # never screened before power


def test_immediate_kill_fires_before_gates():
    frames = _spike_frames()  # fades earn ~zero gross ex costs
    doc = fwd.evaluate_frames(frames)
    assert doc["powered"] is True
    assert doc["status"] == "KILLED"
    assert "immediate-kill" in doc["status_reason"]
    kill = doc["immediate_kill"]
    assert kill["triggered"] is True
    assert kill["max_net_bps"] < 0
    assert len(kill["per_cell"]) == 6
    # Gates 1-10 are NOT evaluated on the kill path.
    assert all(v is None for v in doc["gates"].values())
    assert doc["failed_gates"] == []
    assert doc["selection"]["selected"] is None
    # ...but the screen inputs are exactly the trade means (recomputed here).
    check = fwd._immediate_kill(
        {c: {"out": {"base": fwd.simulate(
            frames, fwd.VregConfig(r=c[0], h=c[1]))},
            "round_trips": 0} for c in fwd.CELLS})
    assert check["triggered"] is True
    assert check["max_net_bps"] == pytest.approx(kill["max_net_bps"])


def test_powered_look_evaluates_gates_without_kill():
    frames = _spike_frames(revert=True)  # fades are profitable
    doc = fwd.evaluate_frames(frames)
    assert doc["powered"] is True
    assert doc["immediate_kill"]["triggered"] is False
    assert doc["immediate_kill"]["max_net_bps"] > 0
    # PBO + plateau are COMPUTED (never null at power).
    assert doc["pbo_detail"]["pbo"] is not None
    assert doc["plateau_detail"]["value"] is not None
    assert doc["dsr_detail"]["dsr"] is not None
    assert doc["status"] == "KILLED"  # fails real gates (years + NW t)
    assert set(doc["failed_gates"]) == {"newey_west_t", "years"}


def test_decide_paths():
    gates = {k: True for k in ("sharpe", "dsr", "pbo")}
    assert fwd._decide(powered=True, gates=gates)[0] == "PASS"
    assert fwd._decide(powered=False, gates=gates)[0] == "UNDERPOWERED"
    assert fwd._decide(powered=True,
                       gates={**gates, "dsr": False})[0] == "KILLED"
    assert fwd._decide(powered=True,
                       gates={**gates, "years": None})[0] == "UNDERPOWERED"


def test_121d_makes_years_assessable():
    frames = _frames(100, _wiggle, lambda d, hh: 1e-4)
    early = fwd.evaluate_frames(frames)
    assert early["gates"]["years"] is None
    assert early["forward_days_to_first_possible_pass"] > 0
    frames = _frames(130, _wiggle, lambda d, hh: 1e-4)
    late = fwd.evaluate_frames(frames)
    assert late["gates"]["years"] is not None  # assessed (True or False)
    assert late["forward_days_to_first_possible_pass"] == 0
    # A 90-day look can only KILL: gate 6 blocks PASS before day 121.
    assert late["forward_days"] >= 121


def test_180d_regime_milestone_report_only():
    frames = _frames(200, _wiggle, lambda d, hh: 1e-4)  # never triggers
    doc = fwd.evaluate_frames(frames)
    assert doc["forward_days"] >= 180
    assert sorted(doc["regime_absent_cells"]) == sorted(
        fwd._cell_key(c) for c in fwd.CELLS)
    assert doc["status"] == "UNDERPOWERED"  # never converted to KILL
    assert "stopping rule" in doc["status_reason"]


# -- status / run / verify ------------------------------------------------------------------
def test_status_reports_counters_and_no_returns(tmp_path):
    doc = fwd.status_doc(tmp_path)  # empty root: zero coverage, no raise
    assert doc["forward_days"] == 0
    assert doc["forward_days_required"] == 90
    assert doc["powered"] is False
    assert doc["blocking_gate"] == "forward_days"
    assert set(doc["per_cell"]) == {fwd._cell_key(c) for c in fwd.CELLS}
    for blob in (doc,):
        assert "sharpe" not in blob
        assert "net_daily" not in blob
        assert "stats" not in blob


def test_bindings_present_and_prereg_pinned(tmp_path):
    doc = fwd.status_doc(tmp_path)
    assert doc["prereg"] == "research/prereg/V-reg-forward.md"
    assert doc["prereg_sha256"] == VREG_SHA256
    assert set(doc["code_sha256"]) == {"forward_vreg.py", "slow_stats.py"}
    for digest in doc["code_sha256"].values():
        assert len(digest) == 64
    assert doc["config_sha256"] == fwd._config_sha256()
    assert doc["data_manifest"] == {"files": []}


def test_run_refuses_while_underpowered_and_force_rewrites(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path / "reports")
    frames = _frames(60, _wiggle, lambda d, hh: 1e-4)
    root = tmp_path / "data"
    _write_root(root, frames)
    with pytest.raises(SystemExit, match="UNDERPOWERED"):
        fwd.run(root)
    assert not (tmp_path / "reports" / fwd.VERDICT_NAME).exists()
    doc = fwd.run(root, force=True)  # manual UNDERPOWERED document only
    assert doc["status"] == "UNDERPOWERED"
    doc2 = fwd.run(root, force=True)  # UNDERPOWERED is rewritable
    assert doc2["status"] == "UNDERPOWERED"


def test_run_refuses_second_look(tmp_path, monkeypatch):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path / "reports")
    frames = _spike_frames()
    root = tmp_path / "data"
    _write_root(root, frames)
    doc = fwd.run(root)
    assert doc["status"] == "KILLED"  # immediate-kill verdict, written once
    with pytest.raises(SystemExit, match="one look"):
        fwd.run(root)


def test_verify_matches_stored_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path / "reports")
    frames = _spike_frames()
    root = tmp_path / "data"
    _write_root(root, frames)
    fwd.run(root)
    before = (tmp_path / "reports" / fwd.VERDICT_NAME).read_bytes()
    got = fwd.verify(root)
    assert got["state"] == "MATCH"
    assert got["n_diffs"] == 0
    after = (tmp_path / "reports" / fwd.VERDICT_NAME).read_bytes()
    assert before == after  # verify never writes


def test_verify_detects_tamper(tmp_path, monkeypatch):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path / "reports")
    frames = _spike_frames()
    root = tmp_path / "data"
    _write_root(root, frames)
    fwd.run(root)
    dest = tmp_path / "reports" / fwd.VERDICT_NAME
    stored = json.loads(dest.read_text())
    stored["immediate_kill"]["max_net_bps"] = 123.456
    dest.write_text(json.dumps(stored))
    got = fwd.verify(root)
    assert got["state"] == "MISMATCH"
    assert any("immediate_kill.max_net_bps" in d for d in got["diffs"])


def test_verify_refuses_while_underpowered(tmp_path):
    root = tmp_path / "data"
    with pytest.raises(SystemExit, match="UNDERPORERED|UNDERPOWERED"):
        fwd.verify(root)


def test_forward_command_insufficient_before_power(tmp_path):
    doc = fwd.forward_command(tmp_path)
    assert doc["state"] == "INSUFFICIENT FORWARD DATA"
    assert doc["forward_days_required"] == 90
    assert set(doc["per_cell"]) == {fwd._cell_key(c) for c in fwd.CELLS}
    assert doc["pass_possible_on"] == "2027-03-01"


# -- fcarry cross-checks ----------------------------------------------------------------------------
def test_is_forward_file_matches_fcarry():
    names = ["X-1h-2026-10-17.zip", "X-1h-2026-10-18.zip",
             "X-1h-2026-11-01.zip", "X-fundingRate-2026-10.zip",
             "X-fundingRate-2026-11.zip", "X-fundingRate-2027-01.zip"]
    for name in names:
        assert fwd.is_forward_file(name) == fcarry.is_forward_file(name), name
    for bad in ("junk.zip", "X-1h-.zip"):
        with pytest.raises(ValueError):
            fwd.is_forward_file(bad)
        with pytest.raises(ValueError):
            fcarry.is_forward_file(bad)
