"""Dataset compatibility audit before expensive scoring (CORR-DATA §4).

Streams a capture dir (events.jsonl + manifest.json + optional
depth_snapshots.jsonl) in O(1) memory and reports: required channels,
timestamp meaning/usability, observed cadence, continuity, marks,
snapshots, funding, sizing filters, and exact coverage — all labeled
with the rule profile the verdict assumes.

Verdict SCORABLE (exit 0) or UNSCORABLE (exit 3) with explicit
reasons when essential evidence is missing. A coarse diagnostic
profile (configs/research_coarse.toml) may be audited against, but
its verdicts are labeled DIAGNOSTIC and never certify live readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.app.config import load_config  # noqa: E402
from cryptobot.research.backtest import FROZEN_FILTERS  # noqa: E402

EXEC_CHANNELS = ("aggTrade", "bookTicker")


class _Stream:
    __slots__ = ("count", "ts_min", "ts_max", "prev", "gap_sum",
                 "gap_n", "gap_max", "disordered", "missing_ts",
                 "skew_sum", "skew_n", "skew_neg", "skew_max",
                 "trade_seconds")

    def __init__(self) -> None:
        self.count = 0
        self.ts_min: int | None = None
        self.ts_max: int | None = None
        self.prev: int | None = None
        self.gap_sum = 0
        self.gap_n = 0
        self.gap_max = 0
        self.disordered = 0
        self.missing_ts = 0
        self.skew_sum = 0
        self.skew_n = 0
        self.skew_neg = 0
        self.skew_max: int | None = None
        self.trade_seconds: set[int] = set()


def _usable_ms(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def audit_capture(capture: Path, *, symbols: list[str] | None = None,
                  profile: Path | None = None,
                  filters: dict | None = None) -> dict:
    """Audit one capture dir. Always returns a verdict dict."""
    report: dict = {
        "capture": str(capture), "verdict": "UNSCORABLE",
        "reasons": [], "warnings": [], "manifest": {},
        "files": {}, "streams": {}, "symbols": {},
        "marks": {}, "funding": {}, "snapshots": {},
        "filters": {}, "profile": {}, "coverage": {},
    }
    fatal: list[str] = []
    events_path = capture / "events.jsonl"
    if not events_path.exists():
        fatal.append("events.jsonl missing")
        report["reasons"] = fatal
        return report

    manifest_path = capture / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (ValueError, OSError) as exc:
            report["warnings"].append(f"manifest.json unreadable: {exc}")
    else:
        report["warnings"].append("manifest.json missing (no provenance)")
    report["manifest"] = {
        "run_id": manifest.get("run_id"),
        "input_class": manifest.get("input_class"),
        "symbols": manifest.get("symbols"),
        "started_utc": manifest.get("started_utc"),
        "ended_utc": manifest.get("ended_utc"),
        "config": manifest.get("config"),
    }
    required = list(symbols or manifest.get("symbols") or [])
    if not required:
        fatal.append("no required symbols (manifest lacks symbols and "
                     "--symbols not given)")
        report["reasons"] = fatal
        return report

    profile_path = profile or (ROOT / "configs" / "paper.toml")
    try:
        cfg = load_config(profile_path)
    except Exception as exc:
        fatal.append(f"profile {profile_path} does not load: {exc}")
        report["reasons"] = fatal
        return report
    diagnostic = "diag" in (cfg.profile_version or "")
    report["profile"] = {
        "path": str(profile_path), "fingerprint": cfg.fingerprint,
        "profile_version": cfg.profile_version,
        "mode": cfg.mode, "quote_max_age_s": cfg.quote_max_age_s,
        "max_mark_age_ms": cfg.risk.max_mark_age_ms,
        "warmup_bars": cfg.warmup_bars,
        "diagnostic_only": diagnostic,
    }
    if diagnostic:
        report["warnings"].append(
            "DIAGNOSTIC profile: verdict does not certify live readiness")

    filt = dict(FROZEN_FILTERS)
    if filters:
        filt.update(filters)
    for symbol in required:
        known = filt.get(symbol) or filt.get(symbol.upper())
        report["filters"][symbol] = {
            "known": known is not None,
            "source": "frozen-labeled-assumption",
        }
        if known is None:
            fatal.append(f"no sizing filters for {symbol}")

    streams: dict[tuple[str, str], _Stream] = {}
    marks_seen: dict[str, int] = {}
    funding_seen: dict[str, int] = {}
    funding_missing: dict[str, int] = {}
    rows = 0
    bad_rows = 0
    first_seq: int | None = None
    last_seq: int | None = None
    seq_jumps = 0
    sha = hashlib.sha256()
    span_min: int | None = None
    span_max: int | None = None
    with open(events_path, "rb") as fh:
        for line in fh:
            sha.update(line)
            rows += 1
            try:
                event = json.loads(line)
            except ValueError:
                bad_rows += 1
                continue
            channel = event.get("channel")
            symbol = event.get("symbol")
            if not channel or not symbol:
                bad_rows += 1
                continue
            seq = event.get("seq")
            if isinstance(seq, int):
                if first_seq is None:
                    first_seq = seq
                if last_seq is not None and seq != last_seq + 1:
                    seq_jumps += 1
                last_seq = seq
            key = (str(channel), str(symbol))
            st = streams.setdefault(key, _Stream())
            st.count += 1
            ts = _usable_ms(event.get("exchange_ts_ms"))
            if ts is None:
                st.missing_ts += 1
            else:
                if st.ts_min is None or ts < st.ts_min:
                    st.ts_min = ts
                if st.ts_max is None or ts > st.ts_max:
                    st.ts_max = ts
                if span_min is None or ts < span_min:
                    span_min = ts
                if span_max is None or ts > span_max:
                    span_max = ts
                if st.prev is not None:
                    if ts < st.prev:
                        st.disordered += 1
                    else:
                        gap = ts - st.prev
                        st.gap_sum += gap
                        st.gap_n += 1
                        if gap > st.gap_max:
                            st.gap_max = gap
                st.prev = ts
                recv = _usable_ms(event.get("local_recv_ms"))
                if recv is not None:
                    skew = recv - ts
                    st.skew_sum += skew
                    st.skew_n += 1
                    if skew < 0:
                        st.skew_neg += 1
                    if st.skew_max is None or skew > st.skew_max:
                        st.skew_max = skew
            if channel in EXEC_CHANNELS and ts is not None:
                st.trade_seconds.add(ts // 1000)
            if channel == "markPrice":
                marks_seen[symbol] = marks_seen.get(symbol, 0) + 1
                payload = event.get("payload") or {}
                if payload.get("funding_rate") is not None:
                    funding_seen[symbol] = funding_seen.get(symbol, 0) + 1
                else:
                    funding_missing[symbol] = funding_missing.get(symbol, 0) + 1
    report["files"] = {
        "events.jsonl": {"bytes": events_path.stat().st_size,
                         "sha256": sha.hexdigest(), "rows": rows,
                         "bad_rows": bad_rows,
                         "seq": {"first": first_seq, "last": last_seq,
                                 "jumps": seq_jumps}},
    }
    if rows == 0:
        fatal.append("events.jsonl is empty")
    if bad_rows:
        report["warnings"].append(f"{bad_rows} malformed rows skipped")

    for (channel, symbol), st in sorted(streams.items()):
        mean_gap = st.gap_sum / st.gap_n if st.gap_n else None
        report["streams"][f"{channel}/{symbol}"] = {
            "count": st.count, "ts_min_ms": st.ts_min,
            "ts_max_ms": st.ts_max, "missing_exchange_ts": st.missing_ts,
            "mean_gap_ms": mean_gap, "max_gap_ms": st.gap_max,
            "disordered_rows": st.disordered,
            "recv_skew_mean_ms": (st.skew_sum / st.skew_n
                                  if st.skew_n else None),
            "recv_skew_max_ms": st.skew_max,
            "recv_before_exchange": st.skew_neg,
            "executable_seconds": len(st.trade_seconds),
        }
        if st.disordered:
            report["warnings"].append(
                f"{channel}/{symbol}: {st.disordered} out-of-order rows "
                f"(no reorder applied)")
        if channel in EXEC_CHANNELS and st.gap_max > cfg.quote_max_age_s * 1000:
            report["warnings"].append(
                f"{channel}/{symbol}: max executable gap {st.gap_max}ms "
                f"exceeds quote_max_age_s={cfg.quote_max_age_s} "
                f"(admission starves across the gap)")

    for symbol in required:
        usable = sum(
            st.count - st.missing_ts for (ch, sym), st in streams.items()
            if sym == symbol and ch in EXEC_CHANNELS)
        union: set[int] = set()
        for (ch, sym), st in streams.items():
            if sym == symbol and ch in EXEC_CHANNELS:
                union |= st.trade_seconds
        exec_seconds = len(union)
        report["symbols"][symbol] = {
            "executable_rows_usable": usable,
            "executable_seconds": exec_seconds,
            "warmup_bars": cfg.warmup_bars,
            "warmup_coverable": exec_seconds >= cfg.warmup_bars,
        }
        if usable == 0:
            fatal.append(
                f"{symbol}: no executable rows with usable exchange_ts_ms "
                f"(essential admission evidence missing)")
        if not report["symbols"][symbol]["warmup_coverable"]:
            report["warnings"].append(
                f"{symbol}: only {exec_seconds} executable seconds for "
                f"{cfg.warmup_bars} warmup bars")

    for symbol in required:
        n_marks = marks_seen.get(symbol, 0)
        report["marks"][symbol] = {
            "rows": n_marks,
            "valuation_path": ("exchange-mark" if n_marks else "feed-fallback"),
        }
        if not n_marks:
            report["warnings"].append(
                f"{symbol}: no markPrice rows (valuation falls back to "
                f"feed; mark age gate not required)")
    report["funding"] = {
        symbol: {"rows_with_rate": funding_seen.get(symbol, 0),
                 "rows_missing_rate": funding_missing.get(symbol, 0)}
        for symbol in required}
    if any(funding_missing.values()):
        report["warnings"].append("some markPrice rows lack funding_rate")

    snaps_path = capture / "depth_snapshots.jsonl"
    if snaps_path.exists():
        n_snaps = 0
        snap_symbols: set[str] = set()
        try:
            with open(snaps_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    n_snaps += 1
                    try:
                        snap_symbols.add(json.loads(line).get("symbol", "?"))
                    except ValueError:
                        pass
        except OSError as exc:
            report["warnings"].append(f"depth_snapshots.jsonl unreadable: {exc}")
        report["snapshots"] = {"present": True, "count": n_snaps,
                               "symbols": sorted(snap_symbols)}
    else:
        report["snapshots"] = {"present": False, "count": 0, "symbols": []}
        report["warnings"].append(
            "depth_snapshots.jsonl absent: books stay unsynced in replay; "
            "depth-dependent strategy views degrade")

    if span_min is not None and span_max is not None:
        from datetime import datetime, timezone
        report["coverage"] = {
            "ts_min_ms": span_min, "ts_max_ms": span_max,
            "span_s": (span_max - span_min) / 1000.0,
            "start_utc": datetime.fromtimestamp(
                span_min / 1000, tz=timezone.utc).isoformat(),
            "end_utc": datetime.fromtimestamp(
                span_max / 1000, tz=timezone.utc).isoformat(),
        }
    else:
        fatal.append("no usable exchange timestamps anywhere in events.jsonl")

    report["reasons"] = fatal
    report["verdict"] = "UNSCORABLE" if fatal else "SCORABLE"
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dataset compatibility audit.")
    ap.add_argument("--capture", required=True, type=Path)
    ap.add_argument("--symbols", default=None,
                    help="comma-separated required symbols")
    ap.add_argument("--profile", default=None, type=Path)
    ap.add_argument("--filters", default=None, type=Path,
                    help="JSON file with extra sizing filters")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None, type=Path)
    args = ap.parse_args(argv)
    extra = None
    if args.filters:
        extra = json.loads(args.filters.read_text())
    report = audit_capture(
        args.capture,
        symbols=args.symbols.split(",") if args.symbols else None,
        profile=args.profile, filters=extra)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text)
    if args.json:
        print(text)
    else:
        print(f"audit {report['capture']}: {report['verdict']} "
              f"(profile={report['profile'].get('profile_version')})")
        for reason in report["reasons"]:
            print(f"  [FATAL] {reason}")
        for warning in report["warnings"][:15]:
            print(f"  [warn] {warning}")
        if len(report["warnings"]) > 15:
            print(f"  ... +{len(report['warnings']) - 15} warnings")
    return 0 if report["verdict"] == "SCORABLE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
