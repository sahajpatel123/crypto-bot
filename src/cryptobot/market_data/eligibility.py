"""Per-symbol gap semantics + exact eligible intervals (READY-DATA Track A).

Offline market-data analysis over capture bytes (no replay needed).
Every excluded span carries exactly one gap class — never a generic
gap reason:

- quiet-no-trade: aggregate message sequence continuous across the
  empty second (healthy inactivity; the bar is still missing under
  current rules).
- missing-trade-ids: aggregate message sequence break (venue_seq/agg_id
  jump); trade messages were lost in transport. Raw single-ID skips with
  a continuous aggregate sequence are venue-side ID consumption (fills
  not published to this stream), counted as a volume caveat only — they
  never exclude time and the second's bar stands.
- transport-gap: capture-wide or symbol-wide row silence, or an explicit
  gap marker row. A lone marker with no silence/ID loss is ledger-noted
  but excludes nothing (evidence, not assumption).
- stale-executable: >quote bound with no bookTicker/aggTrade observation.
- stale-mark: >mark bound with no markPrice observation (only when the
  profile sets a mark bound and marks flow for the symbol).
- unsynced-depth: reported as a span-wide condition (no snapshots), not
  a time-bounded exclusion; S5-ineligible, S1-S4 unaffected.
- unknown-provenance: leading/trailing edges and unparseable rows.

Mechanical warmup (first 130 closed windows) and market eligibility
(data conditions) are separate clocks; research-ready spans are their
labeled intersection. No forward-fill anywhere: missing bars stay
missing. All timestamps are causal exchange event times.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

QUIET_NO_TRADE = "quiet-no-trade"
MISSING_TRADE_IDS = "missing-trade-ids"
TRANSPORT_GAP = "transport-gap"
STALE_EXECUTABLE = "stale-executable"
STALE_MARK = "stale-mark"
UNSYNCED_DEPTH = "unsynced-depth"
UNKNOWN_PROVENANCE = "unknown-provenance"


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _usable_ms(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def _stale_spans(obs_ms: list[int], bound_ms: int) -> list[tuple[int, int]]:
    """(start, end] spans where trailing observation age exceeds bound."""
    spans = []
    ordered = sorted(obs_ms)
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        if cur - prev > bound_ms:
            spans.append((prev + bound_ms, cur))
    return spans


def _trade_seconds_present(trade_ms: list[int]) -> set[int]:
    return {t // 1000 for t in trade_ms}


def classify_capture(capture: Path, symbols: list[str], *,
                     quote_bound_ms: int = 1000,
                     mark_bound_ms: int | None = 1000,
                     warmup_bars: int = 130) -> dict:
    """Stream events.jsonl once; return gap ledger + eligible intervals."""
    report: dict = {"capture": str(capture), "symbols": {},
                    "mechanical": {}, "gap_ledger": [],
                    "depth": {}, "bounds_ms": {
                        "quote": quote_bound_ms, "mark": mark_bound_ms},
                    "warmup_bars": warmup_bars}
    events_path = capture / "events.jsonl"
    if not events_path.exists():
        report["error"] = "events.jsonl missing"
        return report

    exec_ms: dict[str, list[int]] = {s: [] for s in symbols}
    mark_ms: dict[str, list[int]] = {s: [] for s in symbols}
    trade_ms: dict[str, list[int]] = {s: [] for s in symbols}
    any_second: set[int] = set()
    sym_second: dict[str, set[int]] = {s: set() for s in symbols}
    last_agg: dict[str, int] = {}
    last_raw: dict[str, int] = {}
    last_trade_ts: dict[str, int] = {}
    raw_skips: dict[str, int] = {s: 0 for s in symbols}
    raw_skipped_ids: dict[str, int] = {s: 0 for s in symbols}
    markers: list[dict] = []
    bad_rows = 0
    span_min: int | None = None
    span_max: int | None = None
    jumps: list[dict] = []

    with open(events_path, "rb") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except ValueError:
                bad_rows += 1
                continue
            channel = event.get("channel")
            symbol = event.get("symbol")
            ts = _usable_ms(event.get("exchange_ts_ms"))
            if ts is None or not channel or not symbol:
                bad_rows += 1
                continue
            if span_min is None or ts < span_min:
                span_min = ts
            if span_max is None or ts > span_max:
                span_max = ts
            any_second.add(ts // 1000)
            if event.get("gap_kind"):
                markers.append({"ts_ms": ts, "ts_utc": _iso(ts),
                                "channel": channel, "symbol": symbol,
                                "gap_kind": event.get("gap_kind")})
            if symbol not in exec_ms:
                continue
            sym_second[symbol].add(ts // 1000)
            if channel in ("aggTrade", "bookTicker"):
                exec_ms[symbol].append(ts)
            if channel == "markPrice":
                mark_ms[symbol].append(ts)
            if channel == "aggTrade":
                trade_ms[symbol].append(ts)
                payload = event.get("payload") or {}
                agg = payload.get("agg_id", event.get("venue_seq"))
                first_id = payload.get("first_id")
                last = payload.get("last_id")
                if (isinstance(agg, int) and not isinstance(agg, bool)
                        and symbol in last_agg and agg > last_agg[symbol] + 1):
                    jumps.append({
                        "symbol": symbol,
                        "from_ms": last_trade_ts[symbol], "to_ms": ts,
                        "missing_agg": [last_agg[symbol] + 1, agg - 1]})
                if (isinstance(first_id, int) and isinstance(last, int)
                        and symbol in last_raw
                        and first_id > last_raw[symbol] + 1):
                    # Venue-side ID consumption (aggregate sequence is the
                    # loss detector; see module docstring): volume caveat.
                    raw_skips[symbol] += 1
                    raw_skipped_ids[symbol] += first_id - last_raw[symbol] - 1
                if isinstance(agg, int) and not isinstance(agg, bool):
                    if symbol not in last_agg or agg > last_agg[symbol]:
                        last_agg[symbol] = agg
                        last_trade_ts[symbol] = ts
                if isinstance(last, int) and not isinstance(last, bool):
                    if symbol not in last_raw or last > last_raw[symbol]:
                        last_raw[symbol] = last
    if span_min is None or span_max is None:
        report["error"] = "no usable exchange timestamps"
        return report
    report["bad_rows"] = bad_rows
    report["capture_span"] = {"start_ms": span_min, "end_ms": span_max,
                              "start_utc": _iso(span_min),
                              "end_utc": _iso(span_max)}
    report["gap_markers"] = markers

    first_s, last_s = span_min // 1000, span_max // 1000
    silent_global = [s for s in range(first_s, last_s + 1)
                     if s not in any_second]
    for symbol in symbols:
        present = _trade_seconds_present(trade_ms[symbol])
        # Mechanical clock: 130th closed window. Windows close in order
        # (present or missing); the 130th window ends 130s after the
        # first trade window, plus sub-second watermark close latency.
        first_trade_s = min(present) if present else None
        ready_ms = (first_trade_s * 1000 + warmup_bars * 1000
                    if first_trade_s is not None else None)
        report["mechanical"][symbol] = {
            "first_trade_second_utc": (
                _iso(first_trade_s * 1000) if first_trade_s else None),
            "ready_ms": ready_ms,
            "ready_utc": _iso(ready_ms) if ready_ms else None,
            "note": ("130th closed window end; measured replay ready "
                     "lags this by watermark close latency (~0.5-1s)")}

        ledger: list[dict] = []
        # Missing-ID spans (evidence: aggregate message breaks).
        for jump in jumps:
            if jump["symbol"] != symbol:
                continue
            ledger.append({"class": MISSING_TRADE_IDS,
                           "start_ms": jump["from_ms"], "end_ms": jump["to_ms"],
                           "detail": (f"agg {jump['missing_agg'][0]}.."
                                      f"{jump['missing_agg'][1]} absent")})
        # Transport spans: global + symbol silence.
        for sec in silent_global:
            ledger.append({"class": TRANSPORT_GAP, "second": sec,
                           "second_utc": _iso(sec * 1000),
                           "detail": "no rows on any channel/symbol"})
        for sec in range(first_s, last_s + 1):
            if sec not in sym_second[symbol] and sec not in silent_global:
                ledger.append({"class": TRANSPORT_GAP, "second": sec,
                               "second_utc": _iso(sec * 1000),
                               "detail": f"no rows for {symbol}"})
        # Quiet vs unknown empty trade-seconds.
        jump_seconds: set[int] = set()
        for jump in jumps:
            if jump["symbol"] == symbol:
                a, b = jump["from_ms"] // 1000, jump["to_ms"] // 1000
                jump_seconds.update(range(a, b + 1))
        for sec in range(first_s, last_s + 1):
            if sec in present:
                continue
            if sec in jump_seconds:
                continue  # already ledgered as missing-ids.
            if sec in sym_second[symbol]:
                ledger.append({"class": QUIET_NO_TRADE, "second": sec,
                               "second_utc": _iso(sec * 1000),
                               "detail": ("aggregate sequence continuous; "
                                          "quotes/marks flowing; venue had "
                                          "no trades")})
            # Symbol-silent seconds are ledgered as transport-gap above.
        # Stale spans from observation cadence, including the trailing
        # edge (age past the last observation grows deterministically).
        for start, end in _stale_spans(exec_ms[symbol], quote_bound_ms):
            ledger.append({"class": STALE_EXECUTABLE, "start_ms": start,
                           "end_ms": end,
                           "detail": f">{quote_bound_ms}ms without executable"})
        if exec_ms[symbol] and span_max > max(exec_ms[symbol]) + quote_bound_ms:
            ledger.append({"class": STALE_EXECUTABLE,
                           "start_ms": max(exec_ms[symbol]) + quote_bound_ms,
                           "end_ms": span_max,
                           "detail": "past last executable observation"})
        marks_required = (mark_bound_ms is not None and mark_ms[symbol])
        if marks_required:
            assert mark_bound_ms is not None
            for start, end in _stale_spans(mark_ms[symbol], mark_bound_ms):
                ledger.append({"class": STALE_MARK, "start_ms": start,
                               "end_ms": end,
                               "detail": f">{mark_bound_ms}ms without mark"})
            if span_max > max(mark_ms[symbol]) + mark_bound_ms:
                ledger.append({"class": STALE_MARK,
                               "start_ms": (max(mark_ms[symbol])
                                            + mark_bound_ms),
                               "end_ms": span_max,
                               "detail": "past last mark observation"})
        # Provenance edge: before the first observation no age is
        # knowable at all (the trailing edge is determinable staleness,
        # handled above — never unknown).
        first_obs = min(exec_ms[symbol]) if exec_ms[symbol] else None
        if first_obs is not None and first_obs > span_min:
            ledger.append({"class": UNKNOWN_PROVENANCE,
                           "start_ms": span_min, "end_ms": first_obs,
                           "detail": "before first executable observation"})

        # Eligible intervals: trade-present seconds minus exclusions.
        excluded: list[tuple[int, int]] = []
        for entry in ledger:
            if entry["class"] in (MISSING_TRADE_IDS, STALE_EXECUTABLE,
                                  STALE_MARK, UNKNOWN_PROVENANCE):
                excluded.append((entry["start_ms"], entry["end_ms"]))
            elif entry["class"] == TRANSPORT_GAP:
                sec = entry["second"]
                excluded.append((sec * 1000, sec * 1000 + 1000))
        # Trade-present runs (consecutive seconds with bars).
        ordered = sorted(present)
        runs: list[tuple[int, int]] = []
        if ordered:
            run_start = prev = ordered[0]
            for sec in ordered[1:]:
                if sec == prev + 1:
                    prev = sec
                else:
                    runs.append((run_start * 1000, (prev + 1) * 1000))
                    run_start = prev = sec
            runs.append((run_start * 1000, (prev + 1) * 1000))

        def subtract(intervals, cuts):
            out = []
            for a, b in intervals:
                pieces = [(a, b)]
                for c, d in cuts:
                    nxt = []
                    for x, y in pieces:
                        if d <= x or c >= y:
                            nxt.append((x, y))
                        else:
                            if x < c:
                                nxt.append((x, c))
                            if d < y:
                                nxt.append((d, y))
                    pieces = nxt
                out.extend(p for p in pieces if p[1] > p[0])
            return out

        eligible = subtract(runs, excluded)
        intervals = [{"start_ms": a, "end_ms": b, "start_utc": _iso(a),
                      "end_utc": _iso(b), "duration_s": (b - a) / 1000.0}
                     for a, b in eligible]
        eligible_s = sum(i["duration_s"] for i in intervals)
        # Research-ready: market eligibility after mechanical ready.
        research = ([{"start_ms": max(a, ready_ms), "end_ms": b}
                     for a, b in eligible
                     if ready_ms is not None and b > ready_ms]
                    if ready_ms is not None else [])
        research = [r for r in research if r["end_ms"] > r["start_ms"]]
        report["symbols"][symbol] = {
            "trade_seconds": len(present),
            "venue_raw_id_skips": raw_skips[symbol],
            "venue_raw_ids_skipped": raw_skipped_ids[symbol],
            "mechanical_ready_ms": ready_ms,
            "market_intervals": intervals,
            "market_eligible_s": eligible_s,
            "research_intervals": [
                {"start_ms": r["start_ms"], "end_ms": r["end_ms"],
                 "start_utc": _iso(r["start_ms"]),
                 "end_utc": _iso(r["end_ms"]),
                 "duration_s": (r["end_ms"] - r["start_ms"]) / 1000.0}
                for r in research],
            "research_eligible_s": sum(
                (r["end_ms"] - r["start_ms"]) / 1000.0 for r in research),
        }
        report["gap_ledger"].extend(
            [dict(entry, symbol=symbol) for entry in ledger])

    snaps_path = capture / "depth_snapshots.jsonl"
    if snaps_path.exists():
        count, snap_syms, lo, hi = 0, set(), None, None
        with open(snaps_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                count += 1
                try:
                    snap = json.loads(line)
                except ValueError:
                    continue
                snap_syms.add(snap.get("symbol", "?"))
                ts = _usable_ms(snap.get("exchange_ts_ms"))
                if ts is not None:
                    lo = ts if lo is None or ts < lo else lo
                    hi = ts if hi is None or ts > hi else hi
        report["depth"] = {"class": UNSYNCED_DEPTH, "present": True,
                           "count": count, "symbols": sorted(snap_syms),
                           "span_ms": [lo, hi],
                           "note": ("snapshots present; delta-chain "
                                    "continuity is established by replay "
                                    "DepthStore, not assumed here")}
    else:
        report["depth"] = {"class": UNSYNCED_DEPTH, "present": False,
                           "count": 0,
                           "note": ("no snapshots: replay books stay "
                                    "unsynced; depth-dependent views "
                                    "degrade; S5-ineligible")}
    return report
