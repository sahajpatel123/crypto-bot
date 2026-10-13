"""Signal-to-fill funnel with unique candidate IDs + eligible time.

30-minute plan section 5: audit the funnel using unique candidate IDs and
eligible time, NOT millions of repeated rejection rows. Buckets:
unavailable data, missing sequence, healthy no-trade, no setup,
below-cost, below-minimum, stale/expired, nonmarketable band,
IOC cancellation, exposure/cooldown blocking.

Stages: (0) strategy evaluations (rejections.jsonl, deduped by
strategy/instrument/second), (1) intents (store.db, unique intent_id),
(2) submissions (journal client_id), (3) fills (journal exec_id).
Banked cells (aggregates only) are mapped with row counts explicitly
labeled as repeated rows.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

BUCKETS = ("unavailable_data", "missing_sequence", "healthy_no_trade",
           "no_setup", "below_cost", "below_minimum", "stale_expired",
           "nonmarketable", "ioc_cancelled", "exposure_cooldown",
           "startup", "stale_input", "missing_depth", "other_hold")

_UNAVAILABLE_TOKENS = ("gap:fail", "warmup", "flow:never",
                       "flow:missing", "quality")
_DEPTH_TOKENS = ("book:", "stale-book", "empty-book", "unsynced")
_STALE_INPUT_TOKENS = ("gate:stale", "quote-age", "quote_age", "mark-age",
                       "mark_age", "stale-quote", "stale-mark")
_SETUP_TOKENS = ("breakout", "momentum", "pierce", "reclaim", "resume",
                 "pullback", "range", "regime", "trend")


def _side_bucket(token: str) -> str:
    low = token.lower()
    if low.startswith("strategy:"):
        low = low[len("strategy:"):]
    if low.startswith("no-fire:"):
        # Variant-arm evaluation reasons: no-fire:<first-failed-check>.
        gate = low[len("no-fire:"):]
        if gate in ("history", "insufficient-history", "gap-1", "gap-2",
                    "gap") or "gap" in gate:
            return "unavailable_data"
        if any(key in gate for key in _DEPTH_TOKENS):
            return "missing_depth"
        if "sequence" in gate:
            return "missing_sequence"
        # Spread/confirm/position(trade-location)/range/vwap/stall and
        # all other setup gates: condition evaluated, no setup.
        return "no_setup"
    if "sequence:fail" in low:
        return "missing_sequence"
    if any(key in low for key in _DEPTH_TOKENS):
        return "missing_depth"
    if any(key in low for key in _UNAVAILABLE_TOKENS):
        return "unavailable_data"
    if any(key in low for key in _SETUP_TOKENS):
        return "no_setup"
    return ""


def map_reason(stage: str, reason: str) -> str:
    """Map one rejection row to a funnel bucket ('' = unmapped)."""
    if stage == "selection":
        if "reward-below-cost" in reason:
            return "below_cost"
        if "cooldown" in reason or "position-busy" in reason:
            return "exposure_cooldown"
        if "expired" in reason:
            return "stale_expired"
        return ""
    if stage in ("gate", "hold"):
        low = reason.lower()
        if any(key in low for key in _STALE_INPUT_TOKENS):
            return "stale_input"
        if "restart-pending" in low:
            return "startup"
        return "other_hold"
    if stage == "reconcile":
        if "restart-pending" in reason.lower():
            return "startup"
        return "other_hold"
    if stage in ("event", "anomaly", "config", "protection"):
        return "other_hold"
    if stage == "risk":
        if "min-notional" in reason or "minimum" in reason:
            return "below_minimum"
        return ""
    if stage == "execution":
        low = reason.lower()
        if ("expir" in low or "timeout" in low or "stale" in low
                or "past-window" in low or "past_window" in low):
            return "stale_expired"
        if "ioc" in low or "remainder" in low:
            return "ioc_cancelled"
        if "band" in low or "nonmarketable" in low or "lift" in low:
            return "nonmarketable"
        return ""
    if stage == "strategy":
        sides = [_side_bucket(part) for part in reason.split("|")]
        for bucket in ("unavailable_data", "missing_depth",
                       "missing_sequence", "no_setup"):
            if bucket in sides:
                return bucket
        return ""
    return ""


def _second(ts_utc: str) -> str:
    return datetime.fromisoformat(ts_utc).replace(
        microsecond=0).isoformat()


def analyze_run(run_dir: str | Path) -> dict[str, Any]:
    """Candidate-level funnel for one Session run directory."""
    run_dir = Path(run_dir)
    rej_path = run_dir / "rejections.jsonl"
    rows = [json.loads(line) for line in
            rej_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    buckets: Counter = Counter()
    unmapped: Counter = Counter()
    opps: dict[tuple[str, str], set[str]] = {}
    elig: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        bucket = map_reason(row.get("stage", ""), row.get("reason", ""))
        # Strategy-stage rows carry instrument=unknown; only selection+
        # rows are instrument-attributed. Eligible time is per strategy.
        key = row.get("strategy", "?")
        sec = _second(row["ts_utc"])
        opps.setdefault(key, set()).add(sec)
        if bucket:
            buckets[bucket] += 1
            if bucket != "unavailable_data":
                elig.setdefault(key, set()).add(sec)
        else:
            unmapped[f"{row.get('stage')}:{row.get('reason')}"] += 1
    for key in opps:
        elig.setdefault(key, set())

    intents = _read_intents(run_dir / "store.db")
    # Strategy-stage rows in the intents table reuse one placeholder id per
    # strategy and prove nothing about data; only selection-stage rows
    # (real intents, incl. admitted) count as unique candidates.
    real = [row for row in intents
            if not row.get("reason", "").startswith("strategy:")]
    unique_intents = {row["intent_id"] for row in real}
    # Admitted seconds emit intent rows but no rejection rows; a real
    # intent's existence proves its second was eligible-time.
    for row in real:
        sec = _second(row["ts_utc"])
        opps.setdefault(row["strategy"], set()).add(sec)
        elig.setdefault(row["strategy"], set()).add(sec)
    selected = [row for row in intents if row["decision"] == "selected"]
    selected_secs: dict[str, set[str]] = {}
    for row in selected:
        key = row["strategy"]
        selected_secs.setdefault(key, set()).add(_second(row["ts_utc"]))
    healthy = {strategy: len(elig.get(strategy, set())
                             - selected_secs.get(strategy, set()))
               for strategy in elig}

    journal = _read_journal(run_dir / "engine_journal.jsonl")
    outcomes = _reservation_outcomes(journal)
    ioc_bucket_n = outcomes["entries_cancelled_unfilled"]

    # Startup: evaluation seconds strictly before the strategy's first
    # eligible second (warmup/causal prefix). Never-eligible strategies
    # report 0 startup: their time is data-denied, not startup.
    startup: dict[str, int] = {}
    for strategy, secs in opps.items():
        first_elig = min(elig.get(strategy, set()), default=None)
        if first_elig is None:
            startup[strategy] = 0
        else:
            startup[strategy] = sum(1 for s in secs if s < first_elig)

    paths = _intent_stage_paths(real)
    terminal_counts: Counter = Counter(
        p["terminal_bucket"] for p in paths.values())
    cost_pass = sum(1 for p in paths.values()
                    if p["terminal_bucket"] != "below_cost")
    usable_seconds = len({s for secs in opps.values() for s in secs})

    unique_opps = sum(len(v) for v in opps.values())
    return {
        "run_dir": str(run_dir),
        "rejection_rows": len(rows),
        "unique_opportunities": unique_opps,
        "rows_per_opportunity": (round(len(rows) / unique_opps, 2)
                                 if unique_opps else 0.0),
        "strategy_row_buckets": dict(buckets),
        "unmapped_reasons": dict(unmapped),
        "eligible_seconds": {strategy: len(v)
                             for strategy, v in sorted(elig.items())},
        "opportunity_seconds": {strategy: len(v)
                                for strategy, v in sorted(opps.items())},
        "startup_seconds": startup,
        "healthy_no_trade_seconds": healthy,
        "intent_rows": len(intents),
        "real_intent_rows": len(real),
        "unique_intents": len(unique_intents),
        "intent_rows_per_unique": (round(len(real) / len(unique_intents), 1)
                                   if unique_intents else 0.0),
        "selected_intents": len(selected),
        "selected_by_strategy": dict(Counter(
            r["strategy"] for r in selected)),
        "intent_terminal_gates": dict(terminal_counts),
        "intent_stage_paths": paths,
        "entry_client_ids": outcomes["entry_client_ids"],
        "entries_filled": outcomes["entries_filled"],
        "entries_cancelled_unfilled": ioc_bucket_n,
        "entries_open_at_end": outcomes["entries_open_at_end"],
        "fill_exec_ids": outcomes["fill_exec_ids"],
        "reservations": outcomes["reservations"],
        "closed_reservations": outcomes["closed_reservations"],
        "stages": {
            "usable_data_seconds": usable_seconds,
            "strategy_eligible_seconds": {
                s: len(v) for s, v in sorted(elig.items())},
            "setup_unique_intents": len(unique_intents),
            "cost_pass_unique_intents": cost_pass,
            "portfolio_risk_pass_unique": outcomes["reservations"],
            "submitted_entries": outcomes["entry_client_ids"],
            "filled_entries": outcomes["entries_filled"],
            "closed_reservations": outcomes["closed_reservations"],
        },
        "buckets": {
            "unavailable_data": buckets["unavailable_data"],
            "missing_sequence": buckets["missing_sequence"],
            "healthy_no_trade": sum(healthy.values()),
            "no_setup": buckets["no_setup"],
            "below_cost": buckets["below_cost"],
            "below_minimum": buckets["below_minimum"],
            "stale_expired": buckets["stale_expired"],
            "nonmarketable": 0,
            "ioc_cancelled": ioc_bucket_n,
            "exposure_cooldown": buckets["exposure_cooldown"],
            "startup_seconds": sum(startup.values()),
            "stale_input": buckets["stale_input"],
            "missing_depth": buckets["missing_depth"],
            "other_hold": buckets["other_hold"],
        },
        "notes": [
            "strategy buckets count ROWS; see unique_opportunities for the "
            "deduped count and rows_per_opportunity for repetition.",
            "healthy_no_trade counts eligible seconds with no selected "
            "intent (unique seconds, not rows).",
            "startup counts pre-first-eligible seconds per strategy; "
            "never-eligible time stays in data buckets, not startup.",
            "ioc_cancelled counts unique entry client_ids submitted but "
            "venue-canceled unfilled (LIMIT->IOC mechanism); the journal "
            "does not separately label price-band cancels, so "
            "nonmarketable is 0 observed with an instrumentation gap.",
            "stale_expired counts selection:expired + execution expiry "
            "rows; 0 observed means none were emitted.",
            "intent_stage_paths preserve each candidate's original "
            "strategy verdict (admitted) alongside its terminal gate.",
            "stages.cost_pass counts unique intents not terminally "
            "below-cost; portfolio_risk_pass counts journal "
            "reservations (risk Approved).",
        ],
    }


def _read_intents(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in
                con.execute("pragma table_info(intents)").fetchall()]
        return [dict(zip(cols, row)) for row in
                con.execute("select * from intents").fetchall()]
    finally:
        con.close()


def _read_journal(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _index_submissions(journal: list[dict[str, Any]]) -> dict[str, str]:
    by_client: dict[str, str] = {}
    for event in journal:
        if event.get("event") == "submitted":
            detail = event.get("detail", {})
            by_client[detail.get("client_id", "")] = detail.get("role", "?")
    return by_client


def _reservation_outcomes(journal: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-reservation fill/close linkage (shared run + banked)."""
    roles = _index_submissions(journal)
    res_of: dict[str, str] = {}
    for event in journal:
        if event.get("event") == "submitted":
            detail = event.get("detail", {})
            if detail.get("client_id"):
                res_of[detail["client_id"]] = detail.get("reservation_id",
                                                         "")
    entry_ids = [c for c, role in roles.items() if role == "entry"]
    fills_by_res: dict[str, dict[str, bool]] = {}
    exec_ids: set[str] = set()
    for event in journal:
        if event.get("event") != "fill":
            continue
        detail = event.get("detail", {})
        res = detail.get("reservation_id", "")
        slot = fills_by_res.setdefault(res, {"entry": False, "exit": False})
        slot["entry" if roles.get(detail.get("client_id")) == "entry"
             else "exit"] = True
        if detail.get("exec_id"):
            exec_ids.add(detail["exec_id"])
    terminal_cancel = {
        c for c in entry_ids
        if any(e["event"] == "terminal" and
               e.get("detail", {}).get("client_id") == c and
               e.get("detail", {}).get("kind") == "cancel"
               for e in journal)}
    filled = {c for c in entry_ids
              if any(e["event"] == "fill" and
                     e.get("detail", {}).get("client_id") == c
                     for e in journal)}
    reservations = {r for r in
                    [res_of.get(c, "") for c in entry_ids] if r}
    closed = sorted(r for r, slot in fills_by_res.items()
                    if slot["entry"] and slot["exit"])
    return {
        "entry_client_ids": len(entry_ids),
        "entries_filled": len(filled),
        "entries_cancelled_unfilled": len(
            [c for c in entry_ids if c not in filled
             and c in terminal_cancel]),
        "entries_open_at_end": len(
            [c for c in entry_ids if c not in filled
             and c not in terminal_cancel]),
        "reservations": len(reservations),
        "closed_reservations": len(closed),
        "fill_exec_ids": len(exec_ids),
    }


def _intent_stage_paths(
        real: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Original strategy verdict + terminal gate per unique intent.

    Every real intent row proves the strategy ADMITTED (reaching
    selection); the terminal row shows the latest downstream gate.
    """
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in real:
        by_id.setdefault(row["intent_id"], []).append(row)
    paths: dict[str, dict[str, Any]] = {}
    for intent_id, rows in by_id.items():
        ordered = sorted(rows, key=lambda r: r["ts_utc"])
        last = ordered[-1]
        if last["decision"] == "selected":
            terminal_bucket = "admitted"
        else:
            stage = last["reason"].split(":")[0] \
                if ":" in last["reason"] else "unknown"
            terminal_bucket = map_reason(stage, last["reason"]) or \
                "unmapped"
        paths[intent_id] = {
            "strategy": ordered[0]["strategy"],
            "strategy_verdict": "admitted",
            "terminal": f"{last['decision']}:{last['reason']}",
            "terminal_bucket": terminal_bucket,
            "rows": len(ordered),
        }
    return paths


def analyze_symbol_time(capture_path: str | Path) -> dict[str, Any]:
    """Usable symbol-time from a capture events.jsonl (W4-CORR).

    A (symbol, second) counts usable when the second carries a trade or
    quote event for the symbol. Independent of strategy evaluation.
    """
    seconds: dict[str, set[str]] = {}
    n_events = 0
    with open(capture_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            channel = str(event.get("channel", ""))
            if channel not in ("aggTrade", "bookTicker", "trade",
                               "quote", "depth"):
                continue
            symbol = str(event.get("symbol", "?"))
            ts_ms = event.get("exchange_ts_ms",
                              event.get("local_recv_ms", 0))
            try:
                sec = datetime.fromtimestamp(
                    int(ts_ms) / 1000,
                    tz=datetime.now().astimezone().tzinfo).replace(
                        microsecond=0).isoformat()
            except (ValueError, TypeError, OSError):
                continue
            seconds.setdefault(symbol, set()).add(sec)
            n_events += 1
    per_symbol = {symbol: len(secs) for symbol, secs in sorted(seconds.items())}
    return {"events_scanned": n_events,
            "usable_symbol_seconds": per_symbol,
            "usable_symbol_seconds_total": sum(per_symbol.values())}


def analyze_banked(cell: dict[str, Any], journal_path: str | Path,
                   ) -> dict[str, Any]:
    """Funnel from a banked cell.json + engine journal (aggregates)."""
    buckets: Counter = Counter()
    unmapped: Counter = Counter()
    for reason, count in cell.get("reject_counts", {}).items():
        stage, _, rest = reason.partition(":")
        bucket = map_reason(stage, rest)
        if bucket:
            buckets[bucket] += count
        else:
            unmapped[reason] += count
    journal = _read_journal(Path(journal_path))
    outcomes = _reservation_outcomes(journal)
    stream = cell.get("replay_stream", {})
    return {
        "armset": cell.get("armset"), "split": cell.get("split"),
        "days": cell.get("days"),
        "events_seen": cell.get("events_seen"),
        "window_ms": [stream.get("first_ms"), stream.get("last_ms")],
        "reject_rows_total": sum(cell.get("reject_counts", {}).values()),
        "row_buckets": dict(buckets),
        "unmapped_reasons": dict(unmapped),
        "intents_admitted": cell.get("intents_admitted"),
        "unique_reservations": outcomes["reservations"],
        "entry_client_ids": outcomes["entry_client_ids"],
        "entries_filled": outcomes["entries_filled"],
        "entries_cancelled_unfilled":
            outcomes["entries_cancelled_unfilled"],
        "entries_open_at_end": outcomes["entries_open_at_end"],
        "closed_reservations": outcomes["closed_reservations"],
        "fill_exec_ids": outcomes["fill_exec_ids"],
        "closing_equity": cell.get("closing_equity"),
        "net_return_pct": cell.get("net_return_pct"),
        "note": "row_buckets are REPEATED ROWS from banked aggregates "
                "(per-evaluation rows rerun every second); unique-ID "
                "counts come from the journal only. Startup/stale-input "
                "time splits need per-second rows or capture and are "
                "not measurable from aggregates.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signal-to-fill funnel")
    parser.add_argument("--run", action="append", default=[],
                        help="Session run dir (repeatable)")
    parser.add_argument("--banked-cell", action="append", default=[],
                        help="cell.json path (repeatable)")
    parser.add_argument("--banked-journal", action="append", default=[],
                        help="matching engine_journal.jsonl (repeatable)")
    parser.add_argument("--capture", action="append", default=[],
                        help="events.jsonl for usable symbol-time "
                             "(repeatable, optional)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if len(args.banked_cell) != len(args.banked_journal):
        parser.error("--banked-cell/--banked-journal must pair up")
    result: dict[str, Any] = {
        "runs": [analyze_run(path) for path in args.run],
        "banked": [
            analyze_banked(json.loads(Path(cell).read_text()),
                           journal)
            for cell, journal in zip(args.banked_cell,
                                     args.banked_journal)],
        "symbol_time": [analyze_symbol_time(path)
                        for path in args.capture],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"funnel: {len(result['runs'])} runs, "
          f"{len(result['banked'])} banked cells -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
