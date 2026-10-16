"""PIVOT-01 dataset enrollment auditor (read-only, manager-owned).

Checks a capture dir (events.jsonl + manifest.json, cryptobot-events/1)
against the frozen PIVOT-01 enrollment floor in coord/pivot/PIVOT-01.json:

  >=10 days untouched tick, per symbol: observed quotes (bookTicker or
  depth, never modelled spread), aggTrades, marks at >=1s cadence,
  funding settlements with provenance, monotonic seq.

Never imputes: anything absent or unprovable is an explicit failure
reason. Funding *rates* on markPrice are noted but are NOT settlements.
Untouched status is UNKNOWN unless the manifest declares prior_use
none/empty or the operator passes --attest-untouched; UNKNOWN can
never enroll.

Verdicts: ENROLLED (qualification-eligible) / DEVELOPMENT-ONLY
(descriptive only, never qualifying) written to --out as JSON.
Exit: 0 verdict written; 2 input/contract error.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXIT_BLOCKED = 2
MIN_DAYS = 10.0
MS_PER_DAY = 86_400_000
QUOTE_CHANNELS = ("bookTicker", "depth")
MODELED_SOURCES = ("research-spread-profile",)


def _load_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})")
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected JSON object")
    return doc


class _Symbol:
    __slots__ = ("channels", "ts_min", "ts_max", "mark_gaps",
                 "mark_last", "mark_max_gap", "modeled_quotes",
                 "funding_rates", "funding_settlements")

    def __init__(self) -> None:
        self.channels: dict[str, int] = {}
        self.ts_min: int | None = None
        self.ts_max: int | None = None
        self.mark_gaps = 0
        self.mark_last: int | None = None
        self.mark_max_gap = 0
        self.modeled_quotes = 0
        self.funding_rates = 0
        self.funding_settlements = 0


def _funding_sidecar(path: Path) -> dict[str, list[int]]:
    """Load funding settlements JSONL: symbol -> [funding_ts_ms].

    Every record must carry symbol, funding_ts_ms, funding_rate and a
    non-empty ``source`` (provenance, per datasets/backfill_funding.py).
    Records missing any field are rejected loudly, never skipped.
    """
    out: dict[str, list[int]] = {}
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{i}: invalid JSON ({exc})")
            if not isinstance(rec, dict) or not rec.get("symbol") \
                    or not isinstance(rec.get("funding_ts_ms"), int) \
                    or not isinstance(rec.get("funding_rate"),
                                      (int, float)) \
                    or not str(rec.get("source", "")).strip():
                raise ValueError(
                    f"{path}:{i}: settlement needs symbol, "
                    f"funding_ts_ms, funding_rate, source (provenance)")
            out.setdefault(str(rec["symbol"]), []).append(
                int(rec["funding_ts_ms"]))
    return out


def audit(capture: Path, attest_untouched: bool = False,
          funding_file: Path | None = None) -> dict:
    manifest = _load_json(capture / "manifest.json")
    events_path = capture / "events.jsonl"
    if not events_path.exists():
        raise ValueError(f"missing file: {events_path}")
    symbols: dict[str, _Symbol] = {}
    seq_prev: int | None = None
    seq_disordered = 0
    events = 0
    with events_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(e, dict):
                continue
            events += 1
            seq = e.get("seq")
            if isinstance(seq, int):
                if seq_prev is not None and seq <= seq_prev:
                    seq_disordered += 1
                seq_prev = seq
            sym = str(e.get("symbol", "?"))
            st = symbols.setdefault(sym, _Symbol())
            chan = str(e.get("channel", "?"))
            st.channels[chan] = st.channels.get(chan, 0) + 1
            ts = e.get("exchange_ts_ms")
            if isinstance(ts, (int, float)):
                ts = int(ts)
                st.ts_min = ts if st.ts_min is None else min(st.ts_min, ts)
                st.ts_max = ts if st.ts_max is None else max(st.ts_max, ts)
                if chan == "markPrice":
                    if st.mark_last is not None:
                        st.mark_max_gap = max(st.mark_max_gap,
                                              ts - st.mark_last)
                        st.mark_gaps += 1
                    st.mark_last = ts
            payload = e.get("payload") or {}
            if chan in QUOTE_CHANNELS and \
                    payload.get("quote_source") in MODELED_SOURCES:
                st.modeled_quotes += 1
            if chan == "markPrice" and "funding_rate" in payload:
                st.funding_rates += 1
            if "funding" in chan.lower() or \
                    payload.get("settlement") is True:
                st.funding_settlements += 1

    sidecar = _funding_sidecar(funding_file) if funding_file else {}
    declared = [str(s) for s in manifest.get("symbols", [])] \
        or sorted(symbols)
    prior = manifest.get("prior_use")
    untouched = bool(attest_untouched) or prior in (None, "", [], "none")
    per_symbol: dict[str, dict] = {}
    all_reasons: list[str] = []
    for sym in declared:
        st = symbols.get(sym)
        reasons: list[str] = []
        if st is None:
            reasons.append("no events for symbol")
            per_symbol[sym] = {"reasons": reasons, "channels": {}}
            all_reasons += [f"{sym}: {r}" for r in reasons]
            continue
        days = ((st.ts_max or 0) - (st.ts_min or 0)) / MS_PER_DAY \
            if st.ts_min is not None else 0.0
        if days < MIN_DAYS:
            reasons.append(f"span {days:.2f}d < {MIN_DAYS}d floor")
        if not any(st.channels.get(c) for c in QUOTE_CHANNELS):
            reasons.append("no observed quote channel (bookTicker/depth)")
        if st.modeled_quotes:
            reasons.append(
                f"{st.modeled_quotes} modelled-spread quotes present "
                f"(floor requires observed quotes, no modelled spread)")
        if not st.channels.get("aggTrade"):
            reasons.append("no aggTrade channel")
        marks = st.channels.get("markPrice", 0)
        if not marks:
            reasons.append("no markPrice channel")
        elif st.mark_gaps and st.mark_max_gap > 5000:
            reasons.append(
                f"mark cadence gap {st.mark_max_gap}ms > 5000ms "
                f"(floor: marks >=1s)")
        in_span = [t for t in sidecar.get(sym, [])
                   if st.ts_min is not None and st.ts_max is not None
                   and st.ts_min <= t <= st.ts_max]
        settlements = st.funding_settlements + len(in_span)
        if not settlements:
            note = (f" ({st.funding_rates} funding-rate observations "
                    f"on marks are not settlements)") \
                if st.funding_rates else ""
            if sidecar.get(sym):
                note += (f"; {len(sidecar[sym])} sidecar settlements "
                         f"all outside capture span")
            reasons.append("no funding settlements with provenance"
                           + note)
        per_symbol[sym] = {
            "days": round(days, 4), "channels": st.channels,
            "mark_max_gap_ms": st.mark_max_gap,
            "modeled_quotes": st.modeled_quotes,
            "funding_settlements": settlements,
            "funding_sidecar_in_span": len(in_span),
            "reasons": reasons,
        }
        all_reasons += [f"{sym}: {r}" for r in reasons]
    if seq_disordered:
        all_reasons.append(f"seq not monotonic: {seq_disordered} "
                           f"non-increasing events")
    if not untouched:
        all_reasons.append(
            f"untouched UNKNOWN: manifest prior_use={prior!r}, no "
            f"--attest-untouched (prior rounds may have seen this data)")
    enrolled = not all_reasons and events > 0
    return {
        "capture": str(capture),
        "run_id": manifest.get("run_id"),
        "events": events,
        "seq_disordered": seq_disordered,
        "untouched": untouched,
        "floor": {"min_days": MIN_DAYS,
                  "per_symbol": ["observed quotes (no modelled)",
                                 "aggTrade", "marks >=1s",
                                 "funding settlements+provenance",
                                 "monotonic seq"]},
        "symbols": per_symbol,
        "reasons": all_reasons,
        "verdict": "ENROLLED" if enrolled else "DEVELOPMENT-ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PIVOT-01 dataset enrollment auditor (read-only)")
    parser.add_argument("--capture", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--attest-untouched", action="store_true",
                        help="operator attests no prior round saw this data")
    parser.add_argument("--funding-file", default=None,
                        help="funding settlements JSONL with provenance "
                             "(symbol, funding_ts_ms, funding_rate, source)")
    args = parser.parse_args()
    try:
        result = audit(Path(args.capture), args.attest_untouched,
                       Path(args.funding_file) if args.funding_file
                       else None)
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"{result['verdict']}: {result['capture']} "
          f"[{len(result['reasons'])} floor failures -> {args.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
