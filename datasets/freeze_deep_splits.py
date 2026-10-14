#!/usr/bin/env python3
"""Freeze DEEP round-1 splits on a benchmark manifest (W3, DEEP-D5).

Maps frozen day indices (backtest DEV 1-15 / VAL 16-22 / TEST 23-30)
to IST dates from the manifest ``window_ist`` and records, per
(idx, symbol, channel), EXACT row counts inside the IST window
(counted from Parquet, never estimated) plus funding sourced/absent
status in-window. Bytes are day-file granularity (spanned UTC-day
parquet bytes, labeled as such); byte-exact slice materialization is
W4's ``build_partition`` step (sidecar-cached, sha-pinned).

Prior use is recorded from the project record (OP-001 perf profile on
idx1, no strategy scoring anywhere on bench30d). TEST is BURNED for
round 1 (scoring_allowed=false); VAL is scored-once.

IST window bounds are computed independently (zoneinfo Asia/Kolkata)
and CROSS-CHECKED against the harness helper
(``backtest._ist_window_ms``) for all 30 days; any drift fails loudly.

Usage:
    python datasets/freeze_deep_splits.py --manifest datasets/benchmark_30d.toml \
        --out datasets/splits_deep.toml
    python datasets/freeze_deep_splits.py --manifest datasets/benchmark_30d.toml \
        --out datasets/splits_deep.toml --verify   # recompute + compare
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

IST = ZoneInfo("Asia/Kolkata")
DEV = tuple(range(1, 16))
VAL = tuple(range(16, 23))
TEST = tuple(range(23, 31))

PRIOR_USE = {
    1: "OP-001 perf profile only (297k events streamed, no strategy scoring)",
}
PRIOR_DEFAULT = "unused (no strategy scoring on bench30d in project record)"


def ist_window_ms(ist_day: str) -> tuple[int, int]:
    day = date.fromisoformat(ist_day)
    lo = datetime(day.year, day.month, day.day, tzinfo=IST)
    hi = lo + timedelta(days=1)
    return int(lo.timestamp() * 1000), int(hi.timestamp() * 1000)


def crosscheck_ist(all_ist: list[str]) -> None:
    try:
        from cryptobot.research.backtest import _ist_window_ms as harness
    except ImportError as exc:
        raise SystemExit(f"harness helper missing, refusing: {exc}")
    for ist_day in all_ist:
        if harness(ist_day) != ist_window_ms(ist_day):
            raise SystemExit(f"IST window drift on {ist_day}: "
                             f"{harness(ist_day)} != {ist_window_ms(ist_day)}")


def window_counts(parquet: Path, lo: int, hi: int,
                  status_col: str | None = None) -> tuple[int, int, int]:
    """(rows in [lo,hi), sourced, absent) from one channel parquet."""
    import pyarrow.parquet as pq
    table = pq.read_table(str(parquet),
                          columns=(["ts_ms", status_col] if status_col
                                   else ["ts_ms"]))
    cols = table.to_pydict()
    rows = sourced = absent = 0
    if status_col:
        for ts, st in zip(cols["ts_ms"], cols[status_col]):
            if lo <= ts < hi:
                rows += 1
                if st == "sourced":
                    sourced += 1
                else:
                    absent += 1
    else:
        for ts in cols["ts_ms"]:
            if lo <= ts < hi:
                rows += 1
    return rows, sourced, absent


def freeze(manifest_path: Path) -> dict:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    info = manifest["dataset"]
    if info.get("transform_version") != 2:
        raise SystemExit("refusing: manifest transform_version != 2")
    start, end = info["window_ist"]
    days: list[str] = []
    day = date.fromisoformat(start)
    while day.isoformat() <= end:
        days.append(day.isoformat())
        day += timedelta(days=1)
    if len(days) != 30:
        raise SystemExit(f"refusing: window_ist has {len(days)} days, want 30")
    crosscheck_ist(days)
    base = manifest_path.parent
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    symbols = list(info["symbols"])
    splits = []
    for idx, ist_day in enumerate(days, start=1):
        role = "dev" if idx in DEV else ("validation" if idx in VAL else "test")
        lo, hi = ist_window_ms(ist_day)
        utc_days = sorted({datetime.fromtimestamp(ms / 1000,
                                                  tz=timezone.utc).date().isoformat()
                           for ms in (lo, hi - 1)})
        coverage = []
        for symbol in symbols:
            for channel, status_col in (("aggTrade", None),
                                        ("markPrice", "funding_status")):
                rows = sourced = absent = 0
                day_bytes = 0
                for utc in utc_days:
                    pq = (base / "cache" / f"symbol={symbol}" / f"date={utc}"
                          / f"channel={channel}" / "part.parquet")
                    if not pq.exists():
                        continue
                    day_bytes += pq.stat().st_size
                    r, s, a = window_counts(pq, lo, hi, status_col)
                    rows += r
                    sourced += s
                    absent += a
                coverage.append({"idx": idx, "symbol": symbol, "channel": channel,
                                 "rows": rows, "funding_sourced": sourced,
                                 "funding_absent": absent,
                                 "spanned_day_file_bytes": day_bytes})
        splits.append({"idx": idx, "ist_date": ist_day, "role": role,
                       "status": ("burned-round1" if role == "test"
                                  else ("score-once" if role == "validation"
                                        else "open")),
                       "scoring_allowed": role != "test",
                       "utc_days": utc_days,
                       "prior_use": PRIOR_USE.get(idx, PRIOR_DEFAULT),
                       "coverage": coverage})
    return {"manifest_sha": manifest_sha,
            "manifest_file": manifest_path.name,
            "transform_version": info["transform_version"],
            "tz_accounting": info.get("tz_accounting"),
            "symbols": symbols,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "splits": splits}


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_toml(frozen: dict, path: Path) -> None:
    lines = ["# DEEP round-1 split freeze (W3, D5).",
             "# Generated by datasets/freeze_deep_splits.py; never edit by hand.",
             "# Rows are EXACT IST-window counts from Parquet; bytes are",
             "# spanned-UTC-day parquet bytes (day-file granularity).",
             "", "[freeze]",
             f"manifest_sha = {_q(frozen['manifest_sha'])}",
             f"manifest_file = {_q(frozen['manifest_file'])}",
             f"transform_version = {frozen['transform_version']}",
             f"tz_accounting = {_q(frozen['tz_accounting'])}",
             "symbols = [{}]".format(", ".join(_q(s) for s in frozen["symbols"])),
             f"created_utc = {_q(frozen['created_utc'])}", ""]
    for split in frozen["splits"]:
        lines.append("[[split]]")
        lines.append(f"idx = {split['idx']}")
        lines.append(f"ist_date = {_q(split['ist_date'])}")
        lines.append(f"role = {_q(split['role'])}")
        lines.append(f"status = {_q(split['status'])}")
        lines.append(f"scoring_allowed = {'true' if split['scoring_allowed'] else 'false'}")
        lines.append("utc_days = [{}]".format(
            ", ".join(_q(d) for d in split["utc_days"])))
        lines.append(f"prior_use = {_q(split['prior_use'])}")
        lines.append("")
        for cov in split["coverage"]:
            lines.append("[[split.coverage]]")
            lines.append(f"symbol = {_q(cov['symbol'])}")
            lines.append(f"channel = {_q(cov['channel'])}")
            lines.append(f"rows = {cov['rows']}")
            lines.append(f"funding_sourced = {cov['funding_sourced']}")
            lines.append(f"funding_absent = {cov['funding_absent']}")
            lines.append(f"spanned_day_file_bytes = {cov['spanned_day_file_bytes']}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def verify(manifest_path: Path, frozen_path: Path) -> int:
    want = tomllib.loads(frozen_path.read_text(encoding="utf-8"))
    got = freeze(manifest_path)
    errors = []
    if want["freeze"]["manifest_sha"] != got["manifest_sha"]:
        errors.append(f"manifest sha drift: file pins "
                      f"{want['freeze']['manifest_sha'][:12]} vs current "
                      f"{got['manifest_sha'][:12]}")
    want_cov = {(s["idx"], c["symbol"], c["channel"]): c
                for s in want["split"] for c in s["coverage"]}
    got_cov = {(c["idx"], c["symbol"], c["channel"]): c
               for s in got["splits"] for c in s["coverage"]}
    if set(want_cov) != set(got_cov):
        errors.append("coverage key set differs")
    for key in set(want_cov) & set(got_cov):
        for field in ("rows", "funding_sourced", "funding_absent"):
            if want_cov[key][field] != got_cov[key][field]:
                errors.append(f"{key} {field}: file={want_cov[key][field]} "
                              f"recomputed={got_cov[key][field]}")
    for wsplit, gsplit in zip(want["split"], got["splits"]):
        for field in ("idx", "ist_date", "role", "status",
                      "scoring_allowed", "prior_use"):
            if wsplit[field] != gsplit[field]:
                errors.append(f"idx{wsplit['idx']} {field} differs")
    if errors:
        print(f"VERIFY FAILED ({len(errors)}):")
        for err in errors[:20]:
            print(f"  {err}")
        return 1
    print(f"VERIFY OK: manifest {got['manifest_sha'][:12]}, "
          f"{len(got_cov)} coverage cells, 30 splits")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        return verify(Path(args.manifest), Path(args.out))
    frozen = freeze(Path(args.manifest))
    write_toml(frozen, Path(args.out))
    print(f"froze {args.out}: manifest {frozen['manifest_sha'][:12]}, "
          f"{len(frozen['splits'])} splits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
