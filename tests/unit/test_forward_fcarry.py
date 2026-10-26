"""F-CARRY evaluator tests: file rules, clock, books, cells, stopping, verify.

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

import pandas as pd
import pytest

pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "forward_fcarry", str(ROOT / "tools" / "forward_fcarry.py"))
fwd = importlib.util.module_from_spec(_spec)
sys.modules["forward_fcarry"] = fwd  # dataclasses need it registered
_spec.loader.exec_module(fwd)
_b4spec = importlib.util.spec_from_file_location(
    "forward_b4b_x", str(ROOT / "tools" / "forward_b4b.py"))
b4b = importlib.util.module_from_spec(_b4spec)
sys.modules["forward_b4b_x"] = b4b
_b4spec.loader.exec_module(b4b)

DAY0 = pd.Timestamp("2026-11-01", tz="UTC")
SYMS = ("BTCUSDT", "ETHUSDT")


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
    return {s: {"spot": _bars(n_days, close_fn, **kw),
                "perp": _bars(n_days, close_fn, **kw),
                "funding": _funding(n_days, rate_fn)} for s in symbols}


def _wiggle(d, h, base=100.0, amp=0.001):
    return base * (1.0 + amp * (1 if d % 2 == 0 else -1))


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


def _rt_engine_rate(d, hh, high=5e-4, low=-5e-4, period=8):
    # 4 HIGH days + 4 NEG days: trailing median flips both ways, so books
    # enter and exit about once per 8-day cycle per symbol.
    return high if (d % period) < 4 else low


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
    bad = root / "spot" / "BTCUSDT" / "BTCUSDT-1h-2026-10-17.zip"
    _write_kline_zip(bad, _bars(1, lambda d, h: 100.0,
                               start=pd.Timestamp("2026-10-17", tz="UTC")))
    _write_manifest(root)
    with pytest.raises(fwd.InputBeforeForwardWindow):
        fwd.load_frames(root)


def test_refuses_rows_outside_own_file_window(tmp_path):
    # A November-named daily file carrying October rows (renamed holdout).
    root = tmp_path / "data"
    bad = root / "spot" / "BTCUSDT" / "BTCUSDT-1h-2026-11-05.zip"
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
    p = root / "spot" / "BTCUSDT" / "BTCUSDT-1h-2026-11-01.zip"
    _write_kline_zip(p, _bars(1, lambda d, h: 100.0))
    _write_manifest(root)
    doc = json.loads((root / "manifest.json").read_text())
    doc["files"][0]["sha256"] = "0" * 64  # tampered record
    (root / "manifest.json").write_text(json.dumps(doc))
    with pytest.raises(fwd.ChecksumRefusal, match="mismatch"):
        fwd.load_frames(root)


def test_unpinned_file_refuses(tmp_path):
    root = tmp_path / "data"
    p = root / "spot" / "BTCUSDT" / "BTCUSDT-1h-2026-11-01.zip"
    _write_kline_zip(p, _bars(1, lambda d, h: 100.0))
    (root / "manifest.json").write_text(json.dumps({"files": []}))
    with pytest.raises(fwd.ChecksumRefusal, match="unpinned"):
        fwd.load_frames(root)


def test_valid_forward_zips_load(tmp_path):
    root = tmp_path / "data"
    for s in SYMS:
        for ds in ("spot", "perp"):
            _write_kline_zip(
                root / ds / s / f"{s}-1h-2026-11-01.zip",
                _bars(1, lambda d, h: 100.0))
    _write_funding_zip(
        root / "funding" / "BTCUSDT" / "BTCUSDT-fundingRate-2026-11.zip",
        _funding(1, lambda d, hh: 1e-4))
    _write_funding_zip(
        root / "funding" / "ETHUSDT" / "ETHUSDT-fundingRate-2026-11.zip",
        _funding(1, lambda d, hh: 1e-4))
    _write_manifest(root)
    frames, manifest = fwd.load_frames(root)
    assert len(manifest["files"]) == 6
    assert frames["BTCUSDT"]["spot"].shape[0] == 24
    assert set(frames["BTCUSDT"]) == {"spot", "perp", "funding"}


# -- study clock / stale marks --------------------------------------------------
def test_day_without_bars_is_not_a_forward_day():
    frames = _frames(40, _wiggle, lambda d, hh: 5e-4)
    prep = {s: fwd._prep(f) for s, f in frames.items()}
    full = fwd.study_days(prep)
    assert len(full) == 39
    # Drop all bars for 3 mid-range days (both venues, both symbols).
    for s in SYMS:
        for venue in ("spot", "perp"):
            df = frames[s][venue].copy()
            idx = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
            keep = ~idx.dt.date.isin(
                [dt.date(2026, 11, 20), dt.date(2026, 11, 21),
                 dt.date(2026, 11, 22)])
            frames[s][venue] = df[keep].reset_index(drop=True)
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


# -- costs / accounting -----------------------------------------------------------
def test_cost_identity_49bps_plus_impact():
    book = fwd.Book(cash=1000.0, cfg=fwd.FcarryConfig())
    cost, part = book.cost_of(10_000.0, "spot", sigma=0.02, adv=1_000_000.0)
    assert cost == pytest.approx(16.0 + 10_000.0 * 0.5 * 0.02 * 0.1)
    assert part == pytest.approx(0.01)
    cost_p, _ = book.cost_of(10_000.0, "perp", sigma=0.02, adv=1_000_000.0)
    assert cost_p == pytest.approx(8.5 + 10.0)
    book2 = fwd.Book(cash=1000.0, cfg=fwd.FcarryConfig(adverse_mult=2.0))
    cost2, _ = book2.cost_of(10_000.0, "spot", sigma=0.02, adv=1_000_000.0)
    assert cost2 == pytest.approx(2.0 * cost)  # 2x doubles fee AND impact


def test_cost_matches_b4b():
    mine = fwd.Book(cash=1000.0, cfg=fwd.FcarryConfig())
    theirs = b4b.Book(cash=1000.0, cfg=b4b.B4bConfig())
    for venue, notional, sigma, adv in [
            ("spot", 500.0, 0.01, 800_000.0),
            ("perp", 12_000.0, 0.03, 2_000_000.0),
            ("spot", 0.0, 0.01, 800_000.0)]:
        assert mine.cost_of(notional, venue, sigma=sigma, adv=adv) == \
            theirs.cost_of(notional, venue, sigma=sigma, adv=adv)
    mine2 = fwd.Book(cash=1000.0, cfg=fwd.FcarryConfig(adverse_mult=2.0))
    theirs2 = b4b.Book(cash=1000.0,
                       cfg=b4b.B4bConfig(**{**b4b.B4bConfig().__dict__,
                                            "adverse_mult": 2.0}))
    assert mine2.cost_of(500.0, "perp", sigma=0.01, adv=800_000.0) == \
        theirs2.cost_of(500.0, "perp", sigma=0.01, adv=800_000.0)


@pytest.mark.parametrize("trend", [0.01, 0.0, -0.01])
def test_accounting_identity_per_trend(trend):
    # Book opens ~day 21 on rich funding and holds to the end (no exit):
    # E_t = E0 + funding - costs, exactly, in up/flat/down trends.
    if trend == 0.0:
        def close(d, h):
            return 100.0 * (1.0 + 0.001 * (1 if d % 2 else -1))
    else:
        def close(d, h, t=trend):
            return 100.0 * ((1.0 + t) ** d)
    frames = _frames(45, close, lambda d, hh: 8e-4)
    for cell in fwd.CELLS:
        out = fwd.simulate(frames, fwd.FcarryConfig(k=cell[0]),
                           fwd.UNIVERSE_SPLITS[cell[1]])
        final = out["rows"][-1]["equity"]
        expect = 1000.0 + out["funding_income"] - out["fees_paid"]
        assert final == pytest.approx(expect, rel=1e-9), (trend, cell)
        assert out["round_trips"] == 0  # never exits: pure hold


def test_every_fill_executes_at_next_bar_open():
    frames = _frames(30, lambda d, h: 100.0 + d,
                     lambda d, hh: 8e-4,
                     open_fn=lambda d, h: 100.0 + d)
    out = fwd.simulate(frames, fwd.FcarryConfig(k=1.0), ("BTCUSDT",))
    assert len(out["fills"]) == 2  # one entry, both legs, no exit
    for fill in out["fills"]:
        day = pd.Timestamp(fill["day"], tz="UTC")
        expect = 100.0 + (day - DAY0).days  # open of the 00:00 bar
        assert fill["price"] == pytest.approx(expect)


def test_turnover_is_reported_never_gated():
    frames = _frames(220, _wiggle, _rt_engine_rate)
    doc = fwd.evaluate_frames(frames)
    assert doc["powered"] is True
    assert "turnover" not in doc["gates"]
    assert doc["gross_turnover_per_year_descriptive"] > 0
    # Even extreme turnover cannot appear in any gate verdict path.
    assert all("turnover" not in g for g in
               doc["failed_gates"] + doc["unassessable_gates"])

# -- cells / selection / trial vector ------------------------------------------------
def test_six_cells_run_independently():
    frames = _frames(120, _wiggle, _rt_engine_rate)
    rts = {}
    for cell in fwd.CELLS:
        out = fwd.simulate(frames, fwd.FcarryConfig(k=cell[0]),
                           fwd.UNIVERSE_SPLITS[cell[1]])
        rts[cell] = out["round_trips"]
    assert len(rts) == 6
    # BOTH cells trade both symbols, so at least as many RTs as singles.
    assert rts[(1.0, "BOTH")] >= rts[(1.0, "BTC")]
    assert rts[(1.25, "BOTH")] >= rts[(1.25, "ETH")]
    # Lower hurdle trades at least as often as the higher one.
    assert rts[(1.0, "BTC")] >= rts[(1.25, "BTC")]
    assert sum(rts.values()) > 0


def test_selection_picks_max_sharpe_with_lexicographic_tiebreak():
    cells = list(fwd.CELLS)
    sharpes = {c: 0.1 * i for i, c in enumerate(cells)}
    assert fwd._select_cell(sharpes, set(cells)) == (1.25, "BOTH")
    tied = {c: 0.5 for c in cells}
    assert fwd._select_cell(tied, set(cells)) == (1.0, "BTC")
    # The ASCII trap: 'BOTH' < 'BTC' in raw string order, but the prereg
    # orders BTC < ETH < BOTH.
    trap = {(1.0, "BTC"): 1.0, (1.0, "BOTH"): 1.0,
            (1.0, "ETH"): 0.1, (1.25, "BTC"): 0.1,
            (1.25, "ETH"): 0.1, (1.25, "BOTH"): 0.1}
    assert fwd._select_cell(trap, set(cells)) == (1.0, "BTC")
    # k orders before universe.
    assert fwd._select_cell({(1.0, "ETH"): 0.9, (1.25, "BTC"): 0.9,
                             **{c: 0.0 for c in cells
                                if c not in ((1.0, "ETH"), (1.25, "BTC"))}},
                            set(cells)) == (1.0, "ETH")
    # Non-finite never wins.
    nan_case = {c: 0.3 for c in cells}
    nan_case[(1.0, "BTC")] = float("nan")
    assert fwd._select_cell(nan_case, set(cells)) == (1.0, "ETH")


def test_trial_vector_requires_nine_dev_cells(tmp_path, monkeypatch):
    assert len(fwd._read_b4_dev_sharpes()) == 9
    bad = tmp_path / "B4.json"
    bad.write_text(json.dumps(
        {"cell_sharpes": {f"c{i}": 0.1 * i for i in range(8)}}))
    monkeypatch.setattr(fwd, "B4_DEV_ARTIFACT", bad)
    with pytest.raises(RuntimeError, match="9 frozen B4 dev cells"):
        fwd._read_b4_dev_sharpes()


def test_b4_dev_matches_b4b_reader():
    assert fwd._read_b4_dev_sharpes() == b4b.trial_sharpes()


def test_dsr_trial_count_is_16():
    frames = _frames(45, _wiggle, lambda d, hh: 8e-4)
    doc = fwd.evaluate_frames(frames)
    assert doc["trial_sharpes_n"] == 16
    assert doc["missing_b4b_rule_applied"] is True  # no B4b verdict on disk
    assert doc["b4b_forward_sharpe"] is None
    assert doc["dsr_detail"]["n_for_q"] == 16
    assert set(doc["dsr_sensitivities"]) >= {"n15", "n25", "min_imputed_n16"}


def test_b4b_forward_sharpe_reader(tmp_path):
    assert fwd._read_b4b_forward_sharpe(tmp_path / "missing.json") is None
    under = tmp_path / "under.json"
    under.write_text(json.dumps({"status": "UNDERPOWERED",
                                 "stats": {"sharpe": 2.0}}))
    assert fwd._read_b4b_forward_sharpe(under) is None  # unscored: missing rule
    scored = tmp_path / "scored.json"
    scored.write_text(json.dumps({"status": "KILLED",
                                  "stats": {"sharpe": 1.25}}))
    assert fwd._read_b4b_forward_sharpe(scored) == 1.25
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json")
    assert fwd._read_b4b_forward_sharpe(corrupt) is None


# -- stopping rule / verdict ------------------------------------------------------------
def test_powering_needs_90d_and_20rt_every_cell():
    frames = _frames(100, _wiggle, _rt_engine_rate)
    doc = fwd.evaluate_frames(frames)
    assert doc["forward_days"] == 99
    assert doc["powered"] is False  # singles cannot reach 20 RTs yet
    assert doc["status"] == "UNDERPOWERED"
    assert "stopping rule" in doc["status_reason"]


def test_powered_look_kills_on_failed_gates():
    # The 90-day half of power is covered by test_powering_needs_90d...;
    # here the RT half gates (singles need ~8d per round trip, so power
    # arrives past day 121): a powered look with failed gates KILLs.
    frames = _frames(240, _wiggle, _rt_engine_rate)
    doc = fwd.evaluate_frames(frames)
    assert doc["powered"] is True
    assert doc["forward_days"] >= 90
    assert doc["status"] == "KILLED"
    assert doc["failed_gates"], "whipsaw economics must fail a gate"


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


def test_180d_regime_milestone_report_only():
    frames = _frames(200, _wiggle, lambda d, hh: 1e-4)  # never clears hurdle
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
    assert doc["prereg"] == "research/prereg/F-carry-forward.md"
    assert doc["prereg_sha256"] == (
        "5367ebbd68ad342597983f07089ab9d87b69d7f7139846f9dc6bc1c15bcf5e93")
    assert set(doc["code_sha256"]) == {"forward_fcarry.py", "slow_stats.py"}
    for digest in doc["code_sha256"].values():
        assert len(digest) == 64
    assert doc["config_sha256"] == fwd._config_sha256()
    assert doc["data_manifest"] == {"files": []}


def test_run_refuses_while_underpowered_and_force_rewrites(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path / "reports")
    frames = _frames(60, _wiggle, _rt_engine_rate)
    root = tmp_path / "data"
    _write_root(root, frames)
    with pytest.raises(SystemExit, match="UNDERPOWERED"):
        fwd.run(root)
    assert not (tmp_path / "reports" / fwd.VERDICT_NAME).exists()
    doc = fwd.run(root, force=True)  # manual UNDERPOWERED document only
    assert doc["status"] == "UNDERPOWERED"
    doc2 = fwd.run(root, force=True)  # UNDERPOWERED is rewritable
    assert doc2["status"] == "UNDERPOWERED"


def _write_root(root: Path, frames: dict) -> None:
    # Persist in-memory synthetic frames as forward zips + manifest.
    for s, f in frames.items():
        for ds, col in (("spot", "open_ms"), ("perp", "open_ms")):
            df = f[ds]
            idx = pd.to_datetime(df[col], unit="ms", utc=True)
            for day, grp in df.groupby(idx.dt.date):
                name = f"{s}-1h-{day}.zip"
                _write_kline_zip(root / ds / s / name, grp)
        fdf = f["funding"]
        fidx = pd.to_datetime(fdf["calc_ms"], unit="ms", utc=True)
        for (y, m), grp in fdf.groupby([fidx.dt.year, fidx.dt.month]):
            name = f"{s}-fundingRate-{y}-{m:02d}.zip"
            _write_funding_zip(root / "funding" / s / name, grp)
    _write_manifest(root)


def test_run_refuses_second_look(tmp_path, monkeypatch):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path / "reports")
    frames = _frames(240, _wiggle, _rt_engine_rate)
    root = tmp_path / "data"
    _write_root(root, frames)
    doc = fwd.run(root)
    assert doc["status"] == "KILLED"
    with pytest.raises(SystemExit, match="one look"):
        fwd.run(root)


def test_verify_matches_stored_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(fwd, "VERDICT_DIR", tmp_path / "reports")
    frames = _frames(240, _wiggle, _rt_engine_rate)
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
    frames = _frames(240, _wiggle, _rt_engine_rate)
    root = tmp_path / "data"
    _write_root(root, frames)
    fwd.run(root)
    dest = tmp_path / "reports" / fwd.VERDICT_NAME
    stored = json.loads(dest.read_text())
    stored["gates"]["sharpe"] = True
    dest.write_text(json.dumps(stored))
    got = fwd.verify(root)
    assert got["state"] == "MISMATCH"
    assert any("gates.sharpe" in d for d in got["diffs"])


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


def test_cli_forward_fcarry_insufficient(tmp_path, capsys):
    from cryptobot import cli
    rc = cli.cmd_forward(__import__("argparse").Namespace(
        what="fcarry", dir=str(tmp_path), json=True))
    assert rc == 3
    assert "INSUFFICIENT FORWARD DATA" in capsys.readouterr().out


# -- B4b cross-checks ----------------------------------------------------------------------------
def test_is_forward_file_matches_b4b():
    names = ["X-1h-2026-10-17.zip", "X-1h-2026-10-18.zip",
             "X-1h-2026-11-01.zip", "X-fundingRate-2026-10.zip",
             "X-fundingRate-2026-11.zip", "X-fundingRate-2027-01.zip"]
    for name in names:
        assert fwd.is_forward_file(name) == b4b.is_forward_file(name), name
    for bad in ("junk.zip", "X-1h-.zip"):
        with pytest.raises(ValueError):
            fwd.is_forward_file(bad)
        with pytest.raises(ValueError):
            b4b.is_forward_file(bad)


def test_simulate_matches_b4b_on_both_cell():
    frames = _frames(120, _wiggle, _rt_engine_rate)
    mine = fwd.simulate(frames, fwd.FcarryConfig(k=1.5),
                        ("BTCUSDT", "ETHUSDT"))
    theirs = b4b.simulate(frames)
    assert [r["day"] for r in mine["rows"]] == [r["day"] for r in theirs["rows"]]
    assert [r["equity"] for r in mine["rows"]] == [
        r["equity"] for r in theirs["rows"]]
    assert [r["net_ret"] for r in mine["rows"]] == [
        r["net_ret"] for r in theirs["rows"]]
    assert mine["round_trips"] == theirs["round_trips"]
    assert mine["funding_income"] == theirs["funding_income"]
    assert mine["fees_paid"] == theirs["fees_paid"]
