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
           "nonmarketable", "ioc_cancelled", "exposure_cooldown")

_UNAVAILABLE_TOKENS = ("gap:fail", "warmup", "book:", "flow:never",
                       "flow:missing", "quality", "stale-book",
                       "empty-book", "unsynced")
_SETUP_TOKENS = ("breakout", "momentum", "pierce", "reclaim", "resume",
                 "pullback", "range", "regime", "trend")


def _side_bucket(token: str) -> str:
    low = token.lower()
    if "sequence:fail" in low:
        return "missing_sequence"
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
        return ""
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
        for bucket in ("unavailable_data", "missing_sequence", "no_setup"):
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
    by_client = _index_submissions(journal)
    entry_ids = [c for c, role in by_client.items() if role == "entry"]
    filled = {c for c in entry_ids
              if any(e["event"] == "fill" and
                     e.get("detail", {}).get("client_id") == c
                     for e in journal)}
    terminal_cancel = {
        c for c in entry_ids
        if any(e["event"] == "terminal" and
               e.get("detail", {}).get("client_id") == c and
               e.get("detail", {}).get("kind") == "cancel"
               for e in journal)}
    unfilled_cancelled = [c for c in entry_ids
                          if c not in filled and c in terminal_cancel]
    open_entries = [c for c in entry_ids
                    if c not in filled and c not in terminal_cancel]
    exec_ids = sorted({e.get("detail", {}).get("exec_id") for e in journal
                       if e["event"] == "fill" and
                       e.get("detail", {}).get("exec_id")})
    ioc_bucket_n = len(unfilled_cancelled)

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
        "healthy_no_trade_seconds": healthy,
        "intent_rows": len(intents),
        "real_intent_rows": len(real),
        "unique_intents": len(unique_intents),
        "intent_rows_per_unique": (round(len(real) / len(unique_intents), 1)
                                   if unique_intents else 0.0),
        "selected_intents": len(selected),
        "selected_by_strategy": dict(Counter(
            r["strategy"] for r in selected)),
        "entry_client_ids": len(entry_ids),
        "entries_filled": len(filled),
        "entries_cancelled_unfilled": ioc_bucket_n,
        "entries_open_at_end": len(open_entries),
        "fill_exec_ids": len(exec_ids),
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
        },
        "notes": [
            "strategy buckets count ROWS; see unique_opportunities for the "
            "deduped count and rows_per_opportunity for repetition.",
            "healthy_no_trade counts eligible seconds with no selected "
            "intent (unique seconds, not rows).",
            "ioc_cancelled counts unique entry client_ids submitted but "
            "venue-canceled unfilled (LIMIT->IOC mechanism); the journal "
            "does not separately label price-band cancels, so "
            "nonmarketable is 0 observed with an instrumentation gap.",
            "stale_expired counts execution-stage expiry rows; 0 observed "
            "means no expiry rows were emitted, not that expiry is "
            "impossible.",
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
    reservations = {e.get("detail", {}).get("reservation_id")
                    for e in journal
                    if e.get("detail", {}).get("reservation_id")}
    by_client = _index_submissions(journal)
    entry_ids = [c for c, role in by_client.items() if role == "entry"]
    filled = {c for c in entry_ids
              if any(e["event"] == "fill" and
                     e.get("detail", {}).get("client_id") == c
                     for e in journal)}
    cancelled = {
        c for c in entry_ids
        if any(e["event"] == "terminal" and
               e.get("detail", {}).get("client_id") == c
               for e in journal)}
    exec_ids = {e.get("detail", {}).get("exec_id") for e in journal
                if e["event"] == "fill"}
    exec_ids.discard(None)
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
        "unique_reservations": len(reservations),
        "entry_client_ids": len(entry_ids),
        "entries_filled": len(filled),
        "entries_cancelled_unfilled": len([c for c in entry_ids
                                           if c not in filled
                                           and c in cancelled]),
        "fill_exec_ids": len(exec_ids),
        "closing_equity": cell.get("closing_equity"),
        "net_return_pct": cell.get("net_return_pct"),
        "note": "row_buckets are REPEATED ROWS from banked aggregates "
                "(per-evaluation rows rerun every second); unique-ID "
                "counts come from the journal only.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signal-to-fill funnel")
    parser.add_argument("--run", action="append", default=[],
                        help="Session run dir (repeatable)")
    parser.add_argument("--banked-cell", action="append", default=[],
                        help="cell.json path (repeatable)")
    parser.add_argument("--banked-journal", action="append", default=[],
                        help="matching engine_journal.jsonl (repeatable)")
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
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"funnel: {len(result['runs'])} runs, "
          f"{len(result['banked'])} banked cells -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
