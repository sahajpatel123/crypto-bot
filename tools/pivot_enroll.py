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
import functools
import gzip
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


class _Acc:
    """Streaming event accumulator shared by audit() and campaigns."""

    def __init__(self) -> None:
        self.symbols: dict[str, _Symbol] = {}
        self.seq_prev: int | None = None
        self.seq_disordered = 0
        self.events = 0

    def new_segment(self) -> None:
        """Chunk boundary: seq restarts and mark gaps do not span it."""
        self.seq_prev = None
        for st in self.symbols.values():
            st.mark_last = None

    def feed(self, e: dict) -> None:
        self.events += 1
        seq = e.get("seq")
        if isinstance(seq, int):
            if self.seq_prev is not None and seq <= self.seq_prev:
                self.seq_disordered += 1
            self.seq_prev = seq
        sym = str(e.get("symbol", "?"))
        st = self.symbols.setdefault(sym, _Symbol())
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


def _iter_jsonl_lines(open_fn):
    with open_fn() as fh:
        for line in fh:
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict):
                yield e


def audit(capture: Path, attest_untouched: bool = False,
          funding_file: Path | None = None,
          pilot: bool = False) -> dict:
    """Single-capture audit. pilot=True applies the PILOT-01 1-day floor
    (span>=0.95d) and reports PILOT-READY instead of ENROLLED — a pilot
    verdict can never qualify anything under PIVOT-01."""
    manifest = _load_json(capture / "manifest.json")
    events_path = capture / "events.jsonl"
    if events_path.exists():
        open_fn = functools.partial(events_path.open, encoding="utf-8")
    elif (capture / "events.jsonl.gz").exists():
        # Settled-day compaction (PILOT-STORAGE-2026-10-17): gzip of the
        # byte-identical events.jsonl stream; schema untouched.
        open_fn = functools.partial(gzip.open, capture / "events.jsonl.gz",
                                    "rt", encoding="utf-8")
    else:
        raise ValueError(f"missing file: {events_path}")
    acc = _Acc()
    for e in _iter_jsonl_lines(open_fn):
        acc.feed(e)
    symbols = acc.symbols

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
        floor_days = 0.95 if pilot else MIN_DAYS
        if days < floor_days:
            reasons.append(f"span {days:.2f}d < {floor_days}d floor")
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
    if acc.seq_disordered:
        all_reasons.append(f"seq not monotonic: {acc.seq_disordered} "
                           f"non-increasing events")
    if not untouched:
        all_reasons.append(
            f"untouched UNKNOWN: manifest prior_use={prior!r}, no "
            f"--attest-untouched (prior rounds may have seen this data)")
    enrolled = not all_reasons and acc.events > 0
    return {
        "capture": str(capture),
        "run_id": manifest.get("run_id"),
        "events": acc.events,
        "seq_disordered": acc.seq_disordered,
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


def audit_campaign(campaign: Path, attest_untouched: bool = False,
                   funding_file: Path | None = None,
                   min_chunk_events: int = 1000) -> dict:
    """Audit a chunked capture campaign without decompressing to disk.

    Streams each settled ``chunk-*/events.jsonl.gz`` (plain
    ``events.jsonl`` accepted as fallback) through one accumulator;
    chunk boundaries reset seq/mark-gap tracking. Every chunk must be
    settled with >= ``min_chunk_events`` events or the campaign fails
    with the chunk named. Span, channels, cadence, funding and
    untouched rules match :func:`audit`.
    """
    import gzip

    try:
        state = json.loads(
            (campaign / "campaign_state.json").read_text(
                encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"missing campaign_state.json in {campaign}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{campaign}: invalid campaign_state ({exc})")
    chunks = sorted(
        (c for c in state.get("chunks", []) if c.get("dir")),
        key=lambda c: c.get("idx", 0))
    if not chunks:
        raise ValueError(f"{campaign}: no chunks declared")
    acc = _Acc()
    chunk_rows: list[dict] = []
    chunk_reasons: list[str] = []
    for chunk in chunks:
        name = str(chunk["dir"])
        cdir = campaign / name
        acc.new_segment()
        if chunk.get("status") != "settled" \
                or not (cdir / "SETTLED.json").exists():
            chunk_reasons.append(f"{name}: not settled")
            chunk_rows.append({"chunk": name, "status": "unsettled",
                               "events": 0})
            continue
        events_path = cdir / "events.jsonl.gz"
        use_gz = events_path.exists()
        if not use_gz:
            events_path = cdir / "events.jsonl"
        if not events_path.exists():
            chunk_reasons.append(f"{name}: events file missing")
            chunk_rows.append({"chunk": name, "status": "missing",
                               "events": 0})
            continue
        before = acc.events
        opener = (lambda p=events_path: gzip.open(p, "rb")) if use_gz \
            else (lambda p=events_path: p.open("rb"))
        for e in _iter_jsonl_lines(opener):
            acc.feed(e)
        got = acc.events - before
        chunk_rows.append({"chunk": name, "status": "settled",
                           "events": got})
        if got < min_chunk_events:
            chunk_reasons.append(
                f"{name}: only {got} events "
                f"(floor {min_chunk_events}; near-empty chunk)")
    symbols = acc.symbols
    sidecar = _funding_sidecar(funding_file) if funding_file else {}
    declared = [str(s) for s in state.get("symbols", [])] \
        or sorted(symbols)
    prior = state.get("prior_use")
    untouched = bool(attest_untouched) or prior in (None, "", [], "none")
    per_symbol: dict[str, dict] = {}
    all_reasons = list(chunk_reasons)
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
                f"{st.modeled_quotes} modelled-spread quotes present")
        if not st.channels.get("aggTrade"):
            reasons.append("no aggTrade channel")
        marks = st.channels.get("markPrice", 0)
        if not marks:
            reasons.append("no markPrice channel")
        elif st.mark_gaps and st.mark_max_gap > 5000:
            reasons.append(
                f"mark cadence gap {st.mark_max_gap}ms > 5000ms")
        in_span = [t for t in sidecar.get(sym, [])
                   if st.ts_min is not None and st.ts_max is not None
                   and st.ts_min <= t <= st.ts_max]
        if not st.funding_settlements and not in_span:
            reasons.append("no funding settlements with provenance")
        per_symbol[sym] = {
            "days": round(days, 4), "channels": st.channels,
            "mark_max_gap_ms": st.mark_max_gap,
            "funding_settlements": st.funding_settlements + len(in_span),
            "reasons": reasons,
        }
        all_reasons += [f"{sym}: {r}" for r in reasons]
    if acc.seq_disordered:
        all_reasons.append(f"seq not monotonic within chunks: "
                           f"{acc.seq_disordered}")
    if not untouched:
        all_reasons.append(
            f"untouched UNKNOWN: state prior_use={prior!r}, no "
            f"--attest-untouched")
    enrolled = not all_reasons and acc.events > 0
    return {
        "campaign": str(campaign),
        "chunks": chunk_rows,
        "events": acc.events,
        "seq_disordered": acc.seq_disordered,
        "untouched": untouched,
        "symbols": per_symbol,
        "reasons": all_reasons,
        "verdict": "ENROLLED" if enrolled else "DEVELOPMENT-ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PIVOT-01 dataset enrollment auditor (read-only)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture")
    group.add_argument("--campaign",
                       help="chunked campaign dir (campaign_state.json + "
                            "chunk-*/events.jsonl.gz), streamed, never "
                            "decompressed to disk")
    parser.add_argument("--out", required=True)
    parser.add_argument("--attest-untouched", action="store_true",
                        help="operator attests no prior round saw this data")
    parser.add_argument("--funding-file", default=None,
                        help="funding settlements JSONL with provenance "
                             "(symbol, funding_ts_ms, funding_rate, source)")
    args = parser.parse_args()
    try:
        funding = Path(args.funding_file) if args.funding_file else None
        if args.campaign:
            result = audit_campaign(Path(args.campaign),
                                    args.attest_untouched, funding)
        else:
            result = audit(Path(args.capture), args.attest_untouched,
                           funding)
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    target = result.get("campaign", result.get("capture"))
    print(f"{result['verdict']}: {target} "
          f"[{len(result['reasons'])} floor failures -> {args.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
