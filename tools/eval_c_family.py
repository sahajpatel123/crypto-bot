"""Family C evaluator (prereg: research/prereg/C-family-daily.md).

  .venv/bin/python tools/eval_c_family.py dev            # DEV 2022-2024 only
  .venv/bin/python tools/eval_c_family.py holdout C2     # ONE shot, DEV-passers

DEV writes reports/hypotheses/C-dev.json. HOLDOUT refuses unless the
hypothesis passed DEV and no holdout report for it exists yet; it then
writes reports/hypotheses/<id>-holdout.json exactly once.
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_h2_history import CACHE, MONTHS, UNIVERSE_B  # noqa: E402

from cryptobot.research import c_family  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FUND_CACHE = ROOT / "datasets/history_funding"
FUND_URL = ("https://data.binance.vision/data/futures/um/monthly/"
            "fundingRate/{s}/{s}-fundingRate-{m}.zip")
DEV = ("2022-01-01", "2024-12-31")
HOLDOUT = ("2025-01-01", "2026-08-31")
ALPHA = 0.05 / 4


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def daily_closes(symbol: str) -> dict[str, float]:
    """UTC daily close = close of the 23:00 hourly mark bar."""
    out: dict[str, float] = {}
    for month in MONTHS:
        path = CACHE / symbol / f"{month}.csv"
        if not path.exists():
            continue
        for row in csv.reader(io.StringIO(path.read_text())):
            if row and row[0].isdigit():
                ts = int(row[0])
                if (ts // 3_600_000) % 24 == 23:
                    out[_day(ts)] = float(row[4])
    return out


def _fetch_funding(symbol: str, month: str) -> None:
    out = FUND_CACHE / symbol / f"{month}.csv"
    if out.exists() or out.with_suffix(".absent").exists():
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(FUND_URL.format(s=symbol, m=month),
                                 headers={"User-Agent": "cryptobot-c-family"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            out.with_suffix(".absent").write_text("404\n")
            return
        raise
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    out.with_suffix(".tmp").write_text(text)
    out.with_suffix(".tmp").replace(out)


def daily_funding(symbol: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for month in MONTHS:
        path = FUND_CACHE / symbol / f"{month}.csv"
        if not path.exists():
            continue
        for row in csv.reader(io.StringIO(path.read_text())):
            if row and row[0].isdigit():
                day = _day(int(row[0]))
                out[day] = out.get(day, 0.0) + float(row[2])
    return out


def load() -> tuple[dict, dict]:
    jobs = [(s, m) for s in UNIVERSE_B for m in MONTHS]
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda j: _fetch_funding(*j), jobs))
    closes = {s: daily_closes(s) for s in UNIVERSE_B}
    funding = {s: daily_funding(s) for s in UNIVERSE_B}
    return {s: c for s, c in closes.items() if c}, funding


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()


def cmd_dev() -> int:
    closes, funding = load()
    doc = {"family": "C", "prereg": "research/prereg/C-family-daily.md",
           "split": "DEV", "window": DEV, "code_commit": _commit(),
           "alpha": ALPHA, "results": {}}
    for hid, spec in c_family.SPECS.items():
        stats = c_family.score(c_family.run(spec, closes, funding,
                                            start=DEV[0], end=DEV[1]))
        fails = c_family.dev_pass(stats, years=("2022", "2023", "2024"),
                                  alpha=ALPHA)
        doc["results"][hid] = {"name": spec.name,
                               "dev_verdict": "PASS" if not fails else "FAIL",
                               "fails": fails, **stats}
        print(f"{hid} {spec.name}: {doc['results'][hid]['dev_verdict']} "
              f"mean={stats['mean_net_bps']:.2f}bps/day "
              f"2x={stats['mean_adverse_bps']:.2f} "
              f"CI={[round(x, 2) for x in stats['ci95_week_block']]} "
              f"p={stats['p_value']:.4f} sharpe={stats['sharpe_annual']} "
              f"years={ {y: round(v, 2) for y, v in stats['by_year'].items()} } "
              f"turn={stats['mean_turnover']:.3f} fails={fails}")
    out = ROOT / "reports/hypotheses/C-dev.json"
    out.write_text(json.dumps(doc, indent=1) + "\n")
    return 0


def cmd_holdout(hid: str) -> int:
    dev = json.loads((ROOT / "reports/hypotheses/C-dev.json").read_text())
    if dev["results"].get(hid, {}).get("dev_verdict") != "PASS":
        print(f"holdout: REFUSED — {hid} did not pass DEV", file=sys.stderr)
        return 2
    out = ROOT / f"reports/hypotheses/{hid}-holdout.json"
    if out.exists():
        print(f"holdout: REFUSED — {out.name} exists (exactly once)",
              file=sys.stderr)
        return 2
    closes, funding = load()
    spec = c_family.SPECS[hid]
    stats = c_family.score(c_family.run(spec, closes, funding,
                                        start=HOLDOUT[0], end=HOLDOUT[1]))
    ok = (stats["mean_net_bps"] > 0 and stats["p_value"] <= 0.05
          and stats["mean_adverse_bps"] > 0)
    doc = {"hypothesis": spec.name, "split": "HOLDOUT", "window": HOLDOUT,
           "code_commit": _commit(), "dev_commit": dev["code_commit"],
           "verdict": "CONFIRMED" if ok else "KILLED", **stats}
    out.write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "dev":
        raise SystemExit(cmd_dev())
    if len(sys.argv) == 3 and sys.argv[1] == "holdout":
        raise SystemExit(cmd_holdout(sys.argv[2]))
    print(__doc__)
    raise SystemExit(2)
