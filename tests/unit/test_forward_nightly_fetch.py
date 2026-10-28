"""Nightly forward-data catch-up wrapper: no-op gate, fan-out, sorting, summary.

All fixtures are SYNTHETIC (hand-built zip bytes served by a fake Vision
client into tmp dirs). No network: an autouse fixture blocks urlopen/socket
and every loaded study module's real VisionClient is replaced by a raising
stub, so any real fetch attempt fails the test. No forward-dated real file
is ever read; no holdout/Oct file is touched; the real data/ tree is never
written (study modules are exercised as copies under tmp_path, so even
their default roots land in tmp).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import io
import json
import re
import shutil
import socket
import sys
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[2]
WRAPPER_SRC = ROOT / "tools" / "forward_nightly_fetch.py"
sys.path.insert(0, str(ROOT / "src"))  # study copies resolve cryptobot here


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses need it registered
    spec.loader.exec_module(mod)
    return mod


wrap = _load("forward_nightly_fetch", WRAPPER_SRC)

SYMS = ("BTCUSDT", "ETHUSDT")
OCT_DAYS = [f"2026-10-{d:02d}" for d in range(18, 32)]


def _days(start: str, end: str) -> list[str]:
    out, day = [], dt.date.fromisoformat(start)
    last = dt.date.fromisoformat(end)
    while day <= last:
        out.append(day.isoformat())
        day += dt.timedelta(days=1)
    return out


# -- synthetic fixture builders -------------------------------------------------
def _kline_zip(day: str, rows: int = 3) -> bytes:
    """Minimal Vision-shaped 1h kline zip (decodes under lake readers)."""
    idx = pd.date_range(pd.Timestamp(day, tz="UTC"), periods=rows, freq="h",
                        tz="UTC")
    body = ("open_time,open,high,low,close,volume,close_time,quote_volume,"
            "count,taker_base,taker_quote,ignore\n")
    lines = [f"{ms},100,100,100,100,1,{ms + 3599999},1000,5,0.5,50,0"
             for ms in (int(t.value // 1_000_000) for t in idx)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"klines-{day}.csv", body + "\n".join(lines) + "\n")
    return buf.getvalue()


def _funding_zip(month: str, days: int = 2) -> bytes:
    """Minimal Vision-shaped monthly fundingRate zip."""
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    start = pd.Timestamp(month + "-01", tz="UTC")
    for d in range(days):
        for hh in (0, 8, 16):
            t = start + pd.Timedelta(days=d, hours=hh)
            lines.append(f"{int(t.value // 1_000_000)},8,0.0001")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"funding-{month}.csv", "\n".join(lines) + "\n")
    return buf.getvalue()


class FakeVision:
    """Canned Vision CDN: serves hand-built bytes + matching digests."""

    def __init__(self, blobs: dict[str, bytes],
                 corrupt: frozenset[str] = frozenset()) -> None:
        self.blobs = dict(blobs)
        self.corrupt = set(corrupt)
        self.got: list[str] = []

    def list_keys(self, prefix: str) -> list[dict]:
        return [{"key": k, "size": len(v)}
                for k, v in sorted(self.blobs.items())
                if k.startswith(prefix)]

    def _key_of(self, url: str) -> str:
        base = "https://data.binance.vision/"
        assert url.startswith(base), url
        return url[len(base):]

    def get(self, url: str) -> bytes:
        self.got.append(url)
        if url.endswith(".CHECKSUM"):
            key = self._key_of(url[:-len(".CHECKSUM")])
            digest = hashlib.sha256(self.blobs[key]).hexdigest()
            if key in self.corrupt:
                digest = "0" * 64  # published digest disagrees with bytes
            return f"{digest}  {key.rsplit('/', 1)[-1]}\n".encode()
        return self.blobs[self._key_of(url)]

    def download_verified(self, key: str, dest: Path) -> dict:
        """B4b calls this method on the client; mirror resume semantics."""
        base = "https://data.binance.vision/"
        want = self.get(base + key + ".CHECKSUM").decode().split()[0]
        if dest.exists():
            local = hashlib.sha256(dest.read_bytes()).hexdigest()
            if local == want:
                return {"key": key, "path": str(dest), "resumed": True,
                        "sha256": local, "verified": True}
            dest.unlink()
        blob = self.get(base + key)
        got = hashlib.sha256(blob).hexdigest()
        if got != want:
            raise RuntimeError(
                f"checksum mismatch for {key}: "
                f"want={want[:16]} got={got[:16]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        return {"key": key, "path": str(dest), "sha256": got,
                "bytes": len(blob), "resumed": False, "verified": True}


def _universe(days: list[str], months: list[str],
              extra: dict[str, bytes] | None = None,
              corrupt: frozenset[str] = frozenset()) -> FakeVision:
    blobs: dict[str, bytes] = {}
    for sym in SYMS:
        for day in days:
            blobs[f"data/spot/daily/klines/{sym}/1h/{sym}-1h-{day}.zip"] = (
                _kline_zip(day))
            blobs[f"data/futures/um/daily/klines/{sym}/1h/"
                  f"{sym}-1h-{day}.zip"] = _kline_zip(day)
        for month in months:
            blobs[f"data/futures/um/monthly/fundingRate/{sym}/"
                  f"{sym}-fundingRate-{month}.zip"] = _funding_zip(month)
    if extra:
        blobs.update(extra)
    return FakeVision(blobs, corrupt=corrupt)


class _RefuseReal:
    def __init__(self, *a, **k) -> None:
        raise AssertionError("real VisionClient must never be built in tests")


def _factory(fakes: FakeVision | dict[str, FakeVision]):
    def make(study_id: str, module):
        module.VisionClient = _RefuseReal  # live-loaded module: no network
        if isinstance(fakes, dict):
            return fakes[study_id]
        return fakes
    return make


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("network is forbidden in these tests")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


@pytest.fixture()
def tool_dir(tmp_path):
    """Copies of the real study files; V-REG absent unless a test adds it.

    The prereg docs ride along because F-CARRY's fetch binds the prereg
    sha256 into its manifest; the copies resolve them via their own ROOT.
    """
    d = tmp_path / "tools"
    d.mkdir()
    shutil.copy(ROOT / "tools/forward_b4b.py", d / "forward_b4b.py")
    shutil.copy(ROOT / "tools/forward_fcarry.py", d / "forward_fcarry.py")
    shutil.copytree(ROOT / "research" / "prereg",
                    tmp_path / "research" / "prereg")
    return d


def _roots(tmp_path) -> dict:
    return {sid: tmp_path / f"root-{sid}" for sid in ("b4b", "fcarry", "vreg")}


def _run(tool_dir, fake, today: dt.date, tmp_path, *, roots=None) -> dict:
    summary_path = tmp_path / "summary.json"
    summary = wrap.fetch_all(
        today=today, roots=_roots(tmp_path) if roots is None else roots,
        summary_path=summary_path, make_client=_factory(fake),
        tool_dir=tool_dir)
    assert summary_path.exists()
    assert json.loads(summary_path.read_text()) == summary
    return summary


def _by_id(summary) -> dict:
    return {p["study"]: p for p in summary["studies"]}


# -- no-op gate -------------------------------------------------------------------
def test_noop_before_clock_start(tmp_path, tool_dir, monkeypatch, capsys):
    monkeypatch.setattr(wrap, "TOOL_DIR", tool_dir)
    out = tmp_path / "s.json"
    roots = [tmp_path / f"r-{s}" for s in ("b4b", "fcarry", "vreg")]
    rc = wrap.main(["--date", "2026-10-28", "--out", str(out),
                    "--root-b4b", str(roots[0]),
                    "--root-fcarry", str(roots[1]),
                    "--root-vreg", str(roots[2])])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "nothing to fetch yet"
    assert not out.exists()
    assert all(not r.exists() for r in roots)  # fetch never attempted


def test_noop_on_last_day_before_start(tmp_path, tool_dir, monkeypatch,
                                        capsys):
    monkeypatch.setattr(wrap, "TOOL_DIR", tool_dir)
    rc = wrap.main(["--date", "2026-10-31", "--out",
                    str(tmp_path / "s.json")])
    assert rc == 0
    assert "nothing to fetch yet" in capsys.readouterr().out


# -- classification ------------------------------------------------------------------
def test_first_day_fetch_reports_ok(tmp_path, tool_dir):
    """2026-11-01: only warm-up files exist; nothing expected, nothing due."""
    fake = _universe(OCT_DAYS, [])
    summary = _run(tool_dir, fake, dt.date(2026, 11, 1), tmp_path)
    by_id = _by_id(summary)
    assert by_id["b4b"]["status"] == "OK"
    assert by_id["fcarry"]["status"] == "OK"
    assert by_id["b4b"]["files"] > 0 and by_id["b4b"]["fetched"] > 0
    assert by_id["vreg"]["status"] == "ABSENT"
    assert summary["overall"] == "OK" and summary["exit_code"] == 0
    assert summary["date"] == "2026-11-01"


def test_ok_mid_november_current_month_funding_untracked(tmp_path, tool_dir):
    """Nov funding cannot exist before month-end; its absence is not pending."""
    days = OCT_DAYS + _days("2026-11-01", "2026-11-14")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 11, 15),
                   tmp_path)
    by_id = _by_id(summary)
    assert by_id["b4b"]["status"] == "OK"
    assert by_id["fcarry"]["status"] == "OK"
    assert summary["exit_code"] == 0


def test_gap_on_missing_kline_day(tmp_path, tool_dir):
    days = OCT_DAYS + _days("2026-11-01", "2026-11-09")
    fake = _universe(days, [])
    hole = ("data/futures/um/daily/klines/ETHUSDT/1h/"
            "ETHUSDT-1h-2026-11-05.zip")
    del fake.blobs[hole]
    summary = _run(tool_dir, fake, dt.date(2026, 11, 10), tmp_path)
    by_id = _by_id(summary)
    assert by_id["b4b"]["status"] == "GAP"
    assert by_id["fcarry"]["status"] == "GAP"
    assert "ETHUSDT/perp/2026-11-05" in by_id["b4b"]["missing"]
    assert summary["overall"] == "GAP" and summary["exit_code"] == 1


def test_funding_pending_within_grace(tmp_path, tool_dir):
    days = OCT_DAYS + _days("2026-11-01", "2026-12-02")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 12, 3),
                   tmp_path)
    by_id = _by_id(summary)
    assert by_id["b4b"]["status"] == "FUNDING-PENDING"
    assert by_id["fcarry"]["status"] == "FUNDING-PENDING"
    assert "BTCUSDT/funding/2026-11" in by_id["b4b"]["pending"]
    assert summary["overall"] == "FUNDING-PENDING"
    assert summary["exit_code"] == 0  # expected lag never pages


def test_funding_gap_after_grace(tmp_path, tool_dir):
    days = OCT_DAYS + _days("2026-11-01", "2026-12-09")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 12, 10),
                   tmp_path)
    assert _by_id(summary)["b4b"]["status"] == "GAP"
    assert "BTCUSDT/funding/2026-11" in _by_id(summary)["b4b"]["missing"]
    assert summary["exit_code"] == 1


def test_funding_present_is_ok(tmp_path, tool_dir):
    days = OCT_DAYS + _days("2026-11-01", "2026-12-09")
    fake = _universe(days, ["2026-11"])
    summary = _run(tool_dir, fake, dt.date(2026, 12, 10), tmp_path)
    assert _by_id(summary)["b4b"]["status"] == "OK"
    assert summary["exit_code"] == 0


def test_checksum_refusal_continues_and_exits_2(tmp_path, tool_dir):
    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    bad_key = ("data/spot/daily/klines/BTCUSDT/1h/"
               "BTCUSDT-1h-2026-11-02.zip")
    fakes = {"b4b": _universe(days, [], corrupt=frozenset({bad_key})),
             "fcarry": _universe(days, []),
             "vreg": _universe(days, [])}
    summary = _run(tool_dir, fakes, dt.date(2026, 11, 5), tmp_path)
    by_id = _by_id(summary)
    assert by_id["b4b"]["status"] == "CHECKSUM-REFUSAL"
    assert by_id["b4b"]["refused"] == 1
    assert "checksum mismatch" in (by_id["b4b"]["error"] or "")
    assert by_id["fcarry"]["status"] == "OK"  # one refusal stops nothing
    assert summary["overall"] == "CHECKSUM-REFUSAL"
    assert summary["exit_code"] == 2


def test_unexpected_error_is_loud_and_continues(tmp_path, tool_dir):
    class _Boom:
        def list_keys(self, prefix):
            raise ConnectionError("vision unreachable")
        get = list_keys
        download_verified = list_keys

    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    fakes = {"b4b": _Boom(), "fcarry": _universe(days, []),
             "vreg": _universe(days, [])}
    summary = _run(tool_dir, fakes, dt.date(2026, 11, 5), tmp_path)
    by_id = _by_id(summary)
    assert by_id["b4b"]["status"] == "ERROR"
    assert "ConnectionError" in (by_id["b4b"]["error"] or "")
    assert by_id["fcarry"]["status"] == "OK"
    assert summary["overall"] == "ERROR" and summary["exit_code"] == 3


def test_clock_drift_fails_closed(tmp_path, tool_dir):
    text = (tool_dir / "forward_fcarry.py").read_text().replace(
        'FORWARD_CLOCK_START = "2026-11-01"',
        'FORWARD_CLOCK_START = "2026-12-01"')
    (tool_dir / "forward_fcarry.py").write_text(text)
    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 11, 5),
                   tmp_path)
    by_id = _by_id(summary)
    assert by_id["fcarry"]["status"] == "ERROR"
    assert "clock" in (by_id["fcarry"]["error"] or "").lower()
    assert summary["exit_code"] == 3


def test_resume_second_run(tmp_path, tool_dir):
    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    fake = _universe(days, [])
    roots = _roots(tmp_path)
    first = _run(tool_dir, fake, dt.date(2026, 11, 5), tmp_path, roots=roots)
    assert _by_id(first)["b4b"]["fetched"] > 0
    (tmp_path / "summary.json").unlink()
    second = _run(tool_dir, fake, dt.date(2026, 11, 5), tmp_path, roots=roots)
    by_id = _by_id(second)
    assert by_id["b4b"]["fetched"] == 0
    assert by_id["b4b"]["resumed"] > 0
    assert by_id["b4b"]["status"] == "OK"


def test_default_roots_land_in_tmp_not_repo(tmp_path, tool_dir):
    """roots=None resolves each study's own default (tmp here, by copy)."""
    days = OCT_DAYS + _days("2026-11-01", "2026-11-02")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 11, 3),
                   tmp_path, roots={})
    by_id = _by_id(summary)
    assert by_id["b4b"]["root"] == str(tmp_path / "data" / "forward_b4b")
    assert (tmp_path / "data" / "forward_b4b" / "manifest.json").exists()
    # the real tree is untouched: the copy's ROOT pointed at tmp_path
    assert Path(by_id["b4b"]["root"]).is_relative_to(tmp_path)


# -- V-REG presence ---------------------------------------------------------------------
def test_vreg_absent_is_skipped_cleanly(tmp_path, tool_dir):
    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 11, 5),
                   tmp_path)
    vreg = _by_id(summary)["vreg"]
    assert vreg["status"] == "ABSENT" and vreg["present"] is False
    assert (vreg["fetched"], vreg["resumed"], vreg["refused"]) == (0, 0, 0)
    assert summary["exit_code"] == 0


def test_vreg_present_runs_its_fetch(tmp_path, tool_dir):
    shutil.copy(tool_dir / "forward_fcarry.py", tool_dir / "forward_vreg.py")
    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 11, 5),
                   tmp_path)
    vreg = _by_id(summary)["vreg"]
    assert vreg["present"] is True and vreg["status"] == "OK"
    assert vreg["files"] > 0 and vreg["manifest_sha256"] is not None


_STUB_VREG = '''"""Minimal stand-in: pins the exact surface the wrapper needs."""
import datetime as dt
import json
from pathlib import Path

FORWARD_CLOCK_START = "2026-11-01"
CUTOFF_DAY = dt.date(2026, 10, 17)
CUTOFF_MONTH = "2026-10"
UNIVERSE = ("BTCUSDT", "ETHUSDT")
DEFAULT_ROOT = Path("/nonexistent-stub-default")


class VisionClient:
    def __init__(self, *a, **k):
        raise AssertionError("stub client never used")


def file_window(name):
    import re
    m = re.search(r"-(\\d{4}-\\d{2}-\\d{2})\\.zip$", name)
    if m:
        return "day", m.group(1)
    m = re.search(r"-(\\d{4}-\\d{2})\\.zip$", name)
    if m:
        return "month", m.group(1)
    raise ValueError(f"no date in {name!r}")


def wanted_prefixes(symbol):
    return {"perp": f"data/futures/um/daily/klines/{symbol}/1h/"}


PLAN = [
    {"key": "data/futures/um/daily/klines/%s/1h/%s-1h-%s.zip"
     % (s, s, d), "dataset": "perp", "symbol": s,
     "name": "%s-1h-%s.zip" % (s, d)}
    for s in UNIVERSE for d in ("2026-11-01", "2026-11-02")]


def fetch(root, client, manifest_out=None):
    files = []
    for job in PLAN:
        dest = Path(root) / job["dataset"] / job["symbol"] / job["name"]
        rec = client.download_verified(job["key"], dest)
        rec.update({"key": job["key"], "dataset": job["dataset"],
                    "symbol": job["symbol"], "name": job["name"]})
        files.append(rec)
    manifest = {"files": files}
    Path(root, "manifest.json").write_text(json.dumps(manifest))
    return manifest
'''


def test_vreg_minimal_interface_surface(tmp_path, tool_dir):
    """The wrapper needs exactly: fetch/VisionClient/file_window/
    wanted_prefixes/UNIVERSE/DEFAULT_ROOT/FORWARD_CLOCK_START/CUTOFF_*."""
    (tool_dir / "forward_vreg.py").write_text(_STUB_VREG)
    days = OCT_DAYS + _days("2026-11-01", "2026-11-02")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 11, 3),
                   tmp_path)
    vreg = _by_id(summary)["vreg"]
    assert vreg["present"] is True and vreg["status"] == "OK"
    assert vreg["files"] == 4  # the stub's whole PLAN made it to disk


# -- window + summary proofs ---------------------------------------------------------------
def test_pre_window_files_never_fetched(tmp_path, tool_dir):
    extra = {
        "data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-10-17.zip":
            _kline_zip("2026-10-17"),
        "data/futures/um/monthly/fundingRate/BTCUSDT/"
        "BTCUSDT-fundingRate-2026-10.zip": _funding_zip("2026-10"),
        "data/spot/daily/klines/BTCUSDT/1h/undated-junk.zip": b"junk",
    }
    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    fake = _universe(days, [], extra=extra)
    summary = _run(tool_dir, fake, dt.date(2026, 11, 5), tmp_path)
    for p in summary["studies"]:
        if not p["present"]:
            continue
        manifest = json.loads(
            (Path(p["root"]) / "manifest.json").read_text())
        for rec in manifest["files"]:
            assert "2026-10-17" not in rec["name"]
            assert "2026-10.zip" not in rec["name"]
            assert rec["name"] != "undated-junk.zip"
    for url in fake.got:
        assert "2026-10-17" not in url and "2026-10.zip" not in url
        assert "undated-junk" not in url


def test_summary_schema_and_manifest_hashes(tmp_path, tool_dir):
    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    summary = _run(tool_dir, _universe(days, []), dt.date(2026, 11, 5),
                   tmp_path)
    assert set(summary) == {"format", "date", "generated_utc", "overall",
                            "exit_code", "wrapper_sha256", "clock_start",
                            "funding_publish_grace_days", "studies"}
    assert summary["format"] == "cryptobot-forward-nightly-summary/1"
    assert summary["wrapper_sha256"] == hashlib.sha256(
        WRAPPER_SRC.read_bytes()).hexdigest()
    want_study = {"study", "file", "root", "present", "status", "fetched",
                  "resumed", "refused", "files", "manifest_sha256",
                  "missing", "pending", "error"}
    for p in summary["studies"]:
        assert set(p) == want_study, p["study"]
        if p["present"] and p["manifest_sha256"] is not None:
            assert p["manifest_sha256"] == hashlib.sha256(
                (Path(p["root"]) / "manifest.json").read_bytes()
            ).hexdigest()


def test_cli_prints_counts_and_no_figures(tmp_path, tool_dir, monkeypatch,
                                           capsys):
    """End-to-end CLI: per-study counts line + overall line, nothing else."""
    monkeypatch.setattr(wrap, "TOOL_DIR", tool_dir)
    days = OCT_DAYS + _days("2026-11-01", "2026-11-04")
    monkeypatch.setattr(wrap, "_default_client",
                        _factory(_universe(days, [])))
    out = tmp_path / "nightly.json"
    rc = wrap.main(["--date", "2026-11-05", "--out", str(out),
                    "--root-b4b", str(tmp_path / "rb"),
                    "--root-fcarry", str(tmp_path / "rf"),
                    "--root-vreg", str(tmp_path / "rv")])
    assert rc == 0
    text = capsys.readouterr().out
    assert "b4b: status=OK fetched=" in text
    assert "fcarry: status=OK fetched=" in text
    assert "vreg: status=ABSENT" in text
    assert "resumed=" in text and "refused=" in text
    assert "overall=OK exit=0" in text
    for word in ("sharpe", "returns", "verdict", "equity", "pnl", "profit"):
        assert word not in text.lower(), word
    assert out.exists()


def test_cli_gap_exit_code(tmp_path, tool_dir, monkeypatch, capsys):
    monkeypatch.setattr(wrap, "TOOL_DIR", tool_dir)
    fake = _universe(OCT_DAYS + _days("2026-11-01", "2026-11-04"), [])
    hole = ("data/futures/um/daily/klines/BTCUSDT/1h/"
            "BTCUSDT-1h-2026-11-03.zip")
    del fake.blobs[hole]
    monkeypatch.setattr(wrap, "_default_client", _factory(fake))
    rc = wrap.main(["--date", "2026-11-05", "--out",
                    str(tmp_path / "nightly.json"),
                    "--root-b4b", str(tmp_path / "rb"),
                    "--root-fcarry", str(tmp_path / "rf")])
    assert rc == 1
    assert "overall=GAP exit=1" in capsys.readouterr().out


# -- fetch-only guards --------------------------------------------------------------------------
def test_no_network_fixture_is_live():
    with pytest.raises(AssertionError):
        urllib.request.urlopen("https://data.binance.vision/x")


def test_real_client_refuser_works():
    with pytest.raises(AssertionError):
        _RefuseReal()


def test_static_fetch_only_guard():
    """The wrapper may call each study's fetch (and pure planning helpers)
    and nothing else: no decision entry point, no decoder, no network or
    archive primitive of its own, and no performance word anywhere."""
    src = WRAPPER_SRC.read_text()
    assert "def fetch_all" in src and "def main" in src  # right file
    forbidden = ["sharpe", "verdict", "pnl", "p&l", "equity", "equities",
                 "evaluat", "status_doc", "score", "backtest", "profit",
                 "load_frames", "read_klines", "read_funding", "simulate",
                 "pandas", "numpy", "urllib", "socket", "zipfile"]
    low = src.lower()
    for word in forbidden:
        assert word not in low, word
    calls = re.findall(r"\b(run|verify)\s*\(", src)
    assert calls == [], calls
