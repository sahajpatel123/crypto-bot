"""Daily P&L report over the existing run journals (operational reporting).

Sources, all already written by the app; this module invents no schema:

* ``ledger.json`` — :class:`cryptobot.accounting.ledger.Ledger` ``to_dict()``
  format. Its ordered ``journal`` is replayed through a real ``Ledger`` here,
  so fees, funding and partial-reduction basis behave exactly as they do in
  the application. Nothing is re-derived with a second accounting rule.
* ``equity.jsonl`` — the ``marked_equity`` / ``open_pnl`` / ``position_qty``
  rows the session samples (see ``reporting/schemas.py``).
* ``fills.jsonl`` — only counted, for the fill count per symbol.

The report is read-only and quotes nothing: realised P&L is net of fees and
includes signed funding, unrealised marks come from the equity journal, and a
day with no journal produces an explicit empty report with null numbers rather
than a zero that looks like a flat result.

It also carries the operational half of the capital ladder: ``live_statistics``
turns the same journals into the live side of an evidence document, and
``build_ladder_evidence`` binds those statistics and a backtest reference to
the sha256 of every file they came from. No number in that document is typed
by a human.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any

from cryptobot.accounting.ledger import Ledger
from cryptobot.risk.ladder import (
    EVIDENCE_GENERATOR_MODULE,
    PROMOTION_EVIDENCE_FORMAT,
    BacktestReference,
    LiveStatistics,
)

SCHEMA_VERSION = "cryptobot-daily-pnl/1"
BACKTEST_REFERENCE_FORMAT = "cryptobot-backtest-reference/1"
#: Journals are read at most this far below ``--root`` (a run dir is root/x).
MAX_DEPTH = 3

CORRUPTION = "corruption"


# --------------------------------------------------------------------------
# small file helpers
# --------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corrupt(path: Path, line: int, error: str) -> dict[str, Any]:
    return {"file": str(path), "line": line, "error": error}


def _read_jsonl(
        path: Path) -> tuple[list[tuple[int, dict[str, Any]]],
                              list[dict[str, Any]]]:
    """Parse a JSONL journal, keeping each row's real line number."""
    rows: list[tuple[int, dict[str, Any]]] = []
    bad: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [_corrupt(path, 0, f"unreadable: {exc}")]
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except ValueError as exc:
            bad.append(_corrupt(path, number, f"not JSON: {exc}"))
            continue
        if not isinstance(row, dict):
            bad.append(_corrupt(path, number, "line is not a JSON object"))
            continue
        rows.append((number, row))
    return rows, bad


def _parse_ts(raw: Any) -> datetime:
    stamp = datetime.fromisoformat(str(raw))
    if stamp.tzinfo is None:
        raise ValueError("timestamp must carry a UTC offset")
    return stamp.astimezone(UTC)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _num(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


# --------------------------------------------------------------------------
# journal replay (no second accounting rule: it runs the real Ledger)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class JournalEvent:
    ts: datetime
    kind: str
    symbol: str
    net: float          # change in the ledger's realised P&L, fees/funding included
    fee: float
    funding: float      # signed: positive means received
    qty_after: float
    notional: float     # one-way notional this fill closed, 0 for non-fills


@dataclass(frozen=True)
class RoundTrip:
    ts: datetime
    symbol: str
    net: float
    fee: float
    funding: float
    close_notional: float


@dataclass(frozen=True)
class EquityPoint:
    ts: datetime
    equity: float
    open_pnl: float | None
    qty: float


@dataclass(frozen=True)
class RunData:
    name: str
    ledger_path: Path | None
    pilot_equity: float
    events: tuple[JournalEvent, ...]
    round_trips: tuple[RoundTrip, ...]
    equity: tuple[EquityPoint, ...]
    corrupt: tuple[dict[str, Any], ...]
    files: tuple[Path, ...]


def _discover(root: Path) -> dict[Path, dict[str, Path]]:
    """Map run dir -> the journal files it holds (bounded depth)."""
    found: dict[Path, dict[str, Path]] = {}

    def walk(directory: Path, depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        try:
            children = sorted(directory.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_dir():
                walk(child, depth + 1)
                continue
            if child.name in ("ledger.json", "equity.jsonl", "fills.jsonl"):
                found.setdefault(child.parent, {})[child.name] = child

    if root.is_file():
        found[root.parent] = {root.name: root}
        return found
    if not root.exists():
        return found
    walk(root, 0)
    return found


def _replay_ledger(path: Path, corrupt: list[dict[str, Any]]
                   ) -> tuple[float, list[JournalEvent], list[RoundTrip]]:
    """Replay a ledger journal through ``Ledger`` and record per-entry delta."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        corrupt.append(_corrupt(path, 0, f"unreadable ledger: {exc}"))
        return 0.0, [], []
    if not isinstance(doc, dict):
        corrupt.append(_corrupt(path, 0, "ledger document is not an object"))
        return 0.0, [], []
    pilot = _finite(doc.get("pilot_equity"))
    if pilot is None:
        corrupt.append(_corrupt(path, 0,
                                "ledger has no finite pilot_equity"))
        pilot = 0.0
    journal = doc.get("journal")
    if not isinstance(journal, list):
        corrupt.append(_corrupt(path, 0, "ledger has no journal list"))
        return pilot, [], []

    ledger = Ledger(pilot)
    events: list[JournalEvent] = []
    trips: list[RoundTrip] = []
    trip: dict[str, Any] | None = None

    for index, entry in enumerate(journal, start=1):
        if not isinstance(entry, dict):
            corrupt.append(_corrupt(path, index, "journal entry is not an object"))
            continue
        try:
            kind = str(entry["kind"])
            ts = _parse_ts(entry["ts_utc"])
            before_qty = ledger.position_qty()
            before_net = ledger.net_realised()
            if kind == "fill":
                ok = ledger.record_fill(
                    str(entry["side"]), float(entry["qty"]),
                    float(entry["price"]), float(entry["fee"]), ts,
                    str(entry["exec_id"]), symbol=str(entry.get("symbol") or ""))
                fee = float(entry["fee"])
                funding = 0.0
                symbol = str(entry.get("symbol") or "")
                signed = float(entry["qty"]) * (
                    1.0 if str(entry["side"]) == "BUY" else -1.0)
                price = float(entry["price"])
            elif kind == "funding":
                ok = ledger.record_funding(
                    float(entry["amount"]), ts, str(entry["event_id"]))
                fee = 0.0
                funding = float(entry["amount"])
                symbol = ""
                signed = 0.0
                price = 0.0
            elif kind == "flow":
                # Flows move equity, never realised P&L; they are replayed so
                # the ledger's replay identity holds, and nothing else.
                ok = ledger.record_flow(
                    float(entry["amount"]), str(entry["flow_kind"]), ts,
                    str(entry["event_id"]))
                fee = 0.0
                funding = 0.0
                symbol = ""
                signed = 0.0
                price = 0.0
            else:
                raise ValueError(f"unknown journal kind {kind!r}")
        except (KeyError, TypeError, ValueError) as exc:
            corrupt.append(_corrupt(path, index, f"invalid journal entry: {exc}"))
            continue
        if not ok:
            corrupt.append(_corrupt(path, index, "duplicate event id"))
            continue

        after_qty = ledger.position_qty()
        net = ledger.net_realised() - before_net
        closed = 0.0
        if before_qty != 0.0 and signed != 0.0:
            same_way = (before_qty > 0) == (signed > 0)
            if not same_way:
                closed = min(abs(before_qty), abs(signed)) * price
        events.append(JournalEvent(ts, kind, symbol, net, fee, funding,
                                   after_qty, closed))

        if before_qty == 0.0 and after_qty != 0.0:
            trip = {"symbol": symbol, "net": 0.0, "fee": 0.0, "funding": 0.0,
                    "notional": 0.0}
        if trip is not None:
            trip["net"] += net
            trip["fee"] += fee
            trip["funding"] += funding
            trip["notional"] += closed
            if symbol:
                trip["symbol"] = symbol
            flipped = (before_qty != 0.0 and after_qty != 0.0
                       and (before_qty > 0) != (after_qty > 0))
            if after_qty == 0.0 or flipped:
                trips.append(RoundTrip(
                    ts, str(trip["symbol"]), float(trip["net"]),
                    float(trip["fee"]), float(trip["funding"]),
                    float(trip["notional"])))
                trip = {"symbol": symbol, "net": 0.0, "fee": 0.0,
                        "funding": 0.0, "notional": 0.0} if flipped else None
    return pilot, events, trips


def _read_equity(path: Path, corrupt: list[dict[str, Any]]) -> list[EquityPoint]:
    rows, bad = _read_jsonl(path)
    corrupt.extend(bad)
    points: list[EquityPoint] = []
    for number, row in rows:
        try:
            ts = _parse_ts(row["ts_utc"])
            equity = _finite(row["marked_equity"])
            if equity is None:
                raise ValueError("marked_equity is not finite")
            qty = _finite(row.get("position_qty"))
            open_pnl = _finite(row.get("open_pnl"))
        except (KeyError, TypeError, ValueError) as exc:
            corrupt.append(
                _corrupt(path, number, f"invalid equity row: {exc}"))
            continue
        points.append(EquityPoint(ts, equity, open_pnl, qty or 0.0))
    points.sort(key=lambda point: point.ts)
    return points


def _load_run(directory: Path, files: dict[str, Path]) -> RunData:
    corrupt: list[dict[str, Any]] = []
    ledger_path = files.get("ledger.json")
    pilot = 0.0
    events: list[JournalEvent] = []
    trips: list[RoundTrip] = []
    if ledger_path is not None:
        pilot, events, trips = _replay_ledger(ledger_path, corrupt)
    equity: list[EquityPoint] = []
    if "equity.jsonl" in files:
        equity = _read_equity(files["equity.jsonl"], corrupt)
    return RunData(directory.name, ledger_path, pilot, tuple(events),
                   tuple(trips), tuple(equity), tuple(corrupt),
                   tuple(files.values()))


def _load_all(root: Path) -> list[RunData]:
    runs = [_load_run(directory, files)
            for directory, files in sorted(_discover(root).items())]
    return [run for run in runs
            if run.ledger_path is not None or run.equity]


# --------------------------------------------------------------------------
# equity curve: journal marks where an equity journal exists
# --------------------------------------------------------------------------
def _samples(runs: list[RunData]) -> list[tuple[datetime, float, float | None]]:
    """(ts, summed equity, summed open P&L or None) across runs.

    A run contributes its latest equity sample (or its pilot equity before the
    first sample), so several run directories aggregate rather than overwrite
    each other. Without any equity journal the only honest curve is realised
    P&L while flat, which is what the fallback builds.
    """
    have_equity = any(run.equity for run in runs)
    per_run: dict[str, list[tuple[datetime, float, float | None]]] = {}
    for run in runs:
        if have_equity and run.equity:
            per_run[run.name] = [(p.ts, p.equity, p.open_pnl) for p in run.equity]
        elif not have_equity:
            cumulative = 0.0
            points: list[tuple[datetime, float, float | None]] = []
            if run.events:
                # The opening equity is a real sample: without it a run that
                # only loses from its first fill has no peak to draw down from.
                points.append((run.events[0].ts, run.pilot_equity, 0.0))
            for event in run.events:
                cumulative += event.net
                if event.qty_after == 0.0:
                    points.append((event.ts, run.pilot_equity + cumulative, 0.0))
            per_run[run.name] = points
        else:
            per_run[run.name] = []
    times = sorted({ts for points in per_run.values() for ts, _, _ in points})
    out: list[tuple[datetime, float, float | None]] = []
    for ts in times:
        total = 0.0
        unrealised = 0.0
        closed = True
        for run in runs:
            points = per_run.get(run.name, [])
            latest = None
            for point in points:
                if point[0] <= ts:
                    latest = point
                else:
                    break
            if latest is None:
                total += run.pilot_equity
                unrealised += 0.0
            else:
                total += latest[1]
                if latest[2] is None:
                    closed = False
                else:
                    unrealised += latest[2]
        out.append((ts, total, unrealised if closed else None))
    return out


def _drawdown(points: list[tuple[datetime, float, float | None]]
              ) -> tuple[float | None, float | None]:
    """Peak-to-trough depth in USDT and as a fraction of the running peak."""
    if not points:
        return None, None
    peak = points[0][1]
    worst = 0.0
    peak_at_worst = peak
    for _, equity, _ in points:
        peak = max(peak, equity)
        drop = peak - equity
        if drop > worst:
            worst = drop
            peak_at_worst = peak
    fraction = None if peak_at_worst <= 0 else worst / peak_at_worst
    return worst, fraction


def _position_at(run: RunData, instant: datetime) -> float:
    qty = 0.0
    for event in run.events:
        if event.ts <= instant:
            qty = event.qty_after
    return qty


# --------------------------------------------------------------------------
# the daily report
# --------------------------------------------------------------------------
def daily_report(root: str | Path, *, day: date | None = None) -> dict[str, Any]:
    root_path = Path(root)
    target = day or datetime.now(UTC).date()
    day_start = datetime.combine(target, dtime(0, 0), tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    runs = _load_all(root_path)
    corrupt = [item for run in runs for item in run.corrupt]
    sources = sorted(
        ({"kind": path.name, "path": str(path), "sha256": _sha256(path)}
         for run in runs for path in run.files),
        key=lambda item: str(item["path"]))

    events = sorted((event for run in runs for event in run.events),
                    key=lambda event: event.ts)
    today = [event for event in events
             if day_start <= event.ts < day_end]
    trip_recent = sorted(
        (trip for run in runs for trip in run.round_trips
         if day_start <= trip.ts < day_end), key=lambda trip: trip.ts)

    realised = sum(event.net for event in today)
    fees = sum(event.fee for event in today)
    funding = sum(event.funding for event in today)
    fills = sum(1 for event in today if event.kind == "fill")

    per_symbol: dict[str, dict[str, float]] = {}
    for event in today:
        if event.kind != "fill":
            continue
        row = per_symbol.setdefault(
            event.symbol or "UNKNOWN",
            {"fills": 0.0, "realised_net_usdt": 0.0, "fees_usdt": 0.0,
             "round_trips": 0.0})
        row["fills"] += 1
        row["realised_net_usdt"] += event.net
        row["fees_usdt"] += event.fee
    for trip in trip_recent:
        row = per_symbol.setdefault(
            trip.symbol or "UNKNOWN",
            {"fills": 0.0, "realised_net_usdt": 0.0, "fees_usdt": 0.0,
             "round_trips": 0.0})
        row["round_trips"] += 1

    wins = sum(1 for trip in trip_recent if trip.net > 0)
    losses = sum(1 for trip in trip_recent if trip.net < 0)
    win_rate = None if not trip_recent else wins / len(trip_recent)

    samples = _samples(runs)
    pilot_total = sum(run.pilot_equity for run in runs)
    have_equity = any(run.equity for run in runs)
    before = [point for point in samples if point[0] < day_start]
    during = [point for point in samples if day_start <= point[0] < day_end]
    up_to_now = [point for point in samples if point[0] < day_end]
    equity_start = before[-1][1] if before else (pilot_total if samples else None)
    latest = during[-1] if during else (up_to_now[-1] if up_to_now else None)
    equity_end = latest[1] if latest is not None else None
    unrealised = latest[2] if latest is not None else None
    basis = ("equity_journal" if have_equity and samples
             else "realised_only" if samples else "none")

    open_at_eod = any(_position_at(run, day_end) != 0.0 for run in runs)
    if open_at_eod and basis != "equity_journal":
        equity_end = None
        unrealised = None

    day_points = ([((day_start), equity_start, None)] if equity_start is not None
                  else []) + during
    dd_day, dd_day_pct = _drawdown(day_points)
    dd_cum, dd_cum_pct = _drawdown(up_to_now)

    journal_present = bool(runs)
    activity = bool(today)
    notes: list[str] = []
    if not journal_present:
        notes.append(f"no ledger.json, equity.jsonl or fills.jsonl under {root_path}")
    elif not activity:
        notes.append("journals present; no journal entry falls on this date")
    if basis == "realised_only":
        notes.append("no equity.jsonl: end-of-day equity is the realised P&L "
                     "curve while flat, so an open position is not marked")
    if basis == "equity_journal" and latest is not None \
            and latest[0] < day_start:
        notes.append("the last equity sample predates this date; the mark is "
                     "stale")
    if basis == "none":
        notes.append("no equity samples: equity and drawdown are not computed")
    if open_at_eod and basis != "equity_journal":
        notes.append("a position was open at the end of the day and no mark "
                     "exists, so end-of-day equity is left null")
    if funding:
        notes.append("funding is signed: positive means received")
    if corrupt:
        notes.append(f"{len(corrupt)} corrupt journal entr"
                     f"{'y' if len(corrupt) == 1 else 'ies'} were reported, "
                     "not dropped")

    doc: dict[str, Any] = {
        "format": SCHEMA_VERSION,
        "generated_utc": datetime.now(UTC).isoformat(),
        "date": target.isoformat(),
        "gate": "NO-GO",
        "journal_present": journal_present,
        "activity": activity,
        "empty": not activity,
        "complete": not corrupt,
        "runs": [run.name for run in runs],
        "sources": sources,
        "realised": {
            "net_usdt": _num(realised) if activity else None,
            "gross_usdt": _num(realised + fees - funding
                              if activity else None),
            "fees_usdt": _num(fees) if activity else None,
            "funding_usdt": _num(funding) if activity else None,
        },
        "fills": fills,
        "round_trips": {
            "count": len(trip_recent),
            "wins": wins,
            "losses": losses,
            "win_rate": _num(win_rate, 4),
        },
        "per_symbol": {
            symbol: {"fills": int(row["fills"]),
                     "realised_net_usdt": _num(row["realised_net_usdt"]),
                     "fees_usdt": _num(row["fees_usdt"]),
                     "round_trips": int(row["round_trips"])}
            for symbol, row in sorted(per_symbol.items())
        },
        "equity": {
            "start_usdt": _num(equity_start),
            "end_usdt": _num(equity_end),
            "unrealised_usdt": _num(unrealised),
            "basis": basis,
        },
        "drawdown": {
            "day_usdt": _num(dd_day),
            "day_pct": _num(dd_day_pct, 4),
            "cumulative_usdt": _num(dd_cum),
            "cumulative_pct": _num(dd_cum_pct, 4),
            "basis": basis,
        },
        "corruption": corrupt,
        "notes": notes,
    }
    return doc


def _cell(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return str(value)


def render_markdown(doc: dict[str, Any]) -> str:
    day = doc["date"]
    lines = [f"# Daily P&L — {day}", ""]
    if not doc["journal_present"]:
        lines.append("**Empty report.** No journals were found, so there is "
                     "nothing to report for this date.")
        lines.append("")
        for note in doc["notes"]:
            lines.append(f"- {note}")
        return "\n".join(lines)
    if not doc["activity"]:
        lines.append("**No activity on this date** (journals present).")
        lines.append("")
    realised = doc["realised"]
    trips = doc["round_trips"]
    equity = doc["equity"]
    drawdown = doc["drawdown"]
    lines += [
        "| metric | value |",
        "| --- | --- |",
        f"| realised net of fees (USDT) | {_cell(realised['net_usdt'])} |",
        f"| gross P&L before fees and funding (USDT) | "
        f"{_cell(realised['gross_usdt'])} |",
        f"| fees paid (USDT) | {_cell(realised['fees_usdt'])} |",
        f"| funding, signed (USDT) | {_cell(realised['funding_usdt'])} |",
        f"| fills | {doc['fills']} |",
        f"| round trips | {trips['count']} ({trips['wins']} win / "
        f"{trips['losses']} loss) |",
        f"| win rate | {_cell(trips['win_rate'], 4)} |",
        f"| equity start (USDT) | {_cell(equity['start_usdt'])} |",
        f"| equity end (USDT) | {_cell(equity['end_usdt'])} |",
        f"| unrealised (USDT) | {_cell(equity['unrealised_usdt'])} |",
        f"| drawdown today (USDT / %) | {_cell(drawdown['day_usdt'])} / "
        f"{_cell(drawdown['day_pct'], 4)} |",
        f"| drawdown cumulative (USDT / %) | "
        f"{_cell(drawdown['cumulative_usdt'])} / "
        f"{_cell(drawdown['cumulative_pct'], 4)} |",
        "",
        f"Equity basis: `{equity['basis']}`. Gate: {doc['gate']}.",
        "",
    ]
    if doc["per_symbol"]:
        lines += ["| symbol | fills | round trips | realised net (USDT) | "
                  "fees (USDT) |", "| --- | --- | --- | --- | --- |"]
        for symbol, row in doc["per_symbol"].items():
            lines.append(
                f"| {symbol} | {row['fills']} | {row['round_trips']} | "
                f"{_cell(row['realised_net_usdt'])} | "
                f"{_cell(row['fees_usdt'])} |")
        lines.append("")
    if doc["corruption"]:
        lines += ["## Corrupt journal entries", "",
                  "| file | line | error |", "| --- | --- | --- |"]
        for item in doc["corruption"]:
            lines.append(f"| {item['file']} | {item['line']} | "
                         f"{item['error']} |")
        lines.append("")
    if doc["notes"]:
        lines += ["## Notes", ""] + [f"- {note}" for note in doc["notes"]]
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# live statistics and the ladder evidence document
# --------------------------------------------------------------------------
def _daily_net(events: list[JournalEvent]) -> list[tuple[date, float]]:
    by_day: dict[date, float] = {}
    for event in events:
        by_day[event.ts.date()] = by_day.get(event.ts.date(), 0.0) + event.net
    if not by_day:
        return []
    first = min(by_day)
    last = max(by_day)
    series: list[tuple[date, float]] = []
    day = first
    while day <= last:
        series.append((day, by_day.get(day, 0.0)))
        day += timedelta(days=1)
    return series


def _annualised_sharpe(returns: list[float]) -> float | None:
    """Mean/stdev of daily returns, annualised by sqrt(365); None if flat."""
    if len(returns) < 2:
        return None
    mean = statistics.fmean(returns)
    sd = statistics.pstdev(returns)
    if sd <= 0:
        return None
    return mean / sd * math.sqrt(365.0)


def live_statistics(root: str | Path, *,
                    risk_state: str | Path | None = None,
                    halted: bool = False
                    ) -> tuple[LiveStatistics, dict[str, Any], list[Path]]:
    """Live statistics for a ladder promotion, derived from the journals.

    ``round_trips`` counts closed trips, ``days`` counts distinct UTC days with
    at least one fill (an active day, not a calendar span), Sharpe is
    annualised by sqrt(365) over every calendar day between the first and last
    entry, and ``cost_bps`` is fees + funding + measured slippage over the
    one-way notional of closing fills. Slippage comes from the ladder's own
    per-trade attribution file, because the journal records executed prices and
    not a predicted one; without that file the cost is *unknown* and the rule
    refuses rather than assuming zero.
    """
    root_path = Path(root)
    runs = _load_all(root_path)
    files = sorted({path for run in runs for path in run.files})
    events = sorted((event for run in runs for event in run.events),
                    key=lambda event: event.ts)
    trips = [trip for run in runs for trip in run.round_trips]
    active_days = sorted({event.ts.date() for event in events
                          if event.kind == "fill"})
    pilot_total = sum(run.pilot_equity for run in runs)

    detail: dict[str, Any] = {
        "runs": [run.name for run in runs],
        "journals": [str(path) for path in files],
        "active_days": [day.isoformat() for day in active_days],
        "pilot_equity_usdt": _num(pilot_total),
        "round_trips": len(trips),
        "fees_usdt": _num(sum(event.fee for event in events)),
        "funding_usdt": _num(sum(event.funding for event in events)),
        "close_notional_usdt": _num(sum(trip.close_notional for trip in trips)),
        "corruption": [item for run in runs for item in run.corrupt],
    }

    sharpe = None
    if pilot_total > 0:
        returns = [net / pilot_total for _, net in _daily_net(events)]
        sharpe = _annualised_sharpe(returns)
    detail["sharpe_basis"] = (
        "daily net realised / opening pilot equity, annualised sqrt(365)")

    cost_bps: float | None = None
    notional = sum(trip.close_notional for trip in trips)
    slippage_bps: float | None = None
    if risk_state is not None:
        state_path = Path(risk_state)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"risk state {state_path} is unreadable: {exc}") from None
        trades = state.get("trades") if isinstance(state, dict) else None
        values = [float(t["realized_slippage_bps"]) for t in trades or []
                  if _finite(t.get("realized_slippage_bps")) is not None]
        if values:
            slippage_bps = statistics.fmean(values)
        files = sorted({*files, state_path})
    detail["slippage_bps"] = _num(slippage_bps, 4)
    detail["slippage_source"] = (
        str(risk_state) if risk_state is not None else None)
    if notional > 0:
        fees_bps = sum(event.fee for event in events) / notional * 1e4
        funding_bps = -sum(event.funding for event in events) / notional * 1e4
        detail["fees_bps"] = _num(fees_bps, 4)
        detail["funding_bps"] = _num(funding_bps, 4)
        if slippage_bps is not None:
            cost_bps = fees_bps + funding_bps + slippage_bps
    detail["cost_note"] = (
        "fees + funding + measured slippage, per one-way closing notional"
        if cost_bps is not None else
        "cost unknown: no measured slippage in the ladder attribution file")

    points = _samples(runs)
    _, dd_fraction = _drawdown(points)
    live = LiveStatistics(
        round_trips=len(trips),
        days=float(len(active_days)),
        sharpe=sharpe,
        cost_bps=cost_bps,
        max_drawdown_frac=dd_fraction,
        halted=halted,
    )
    return live, detail, files


def _load_backtest_reference(path: Path) -> tuple[BacktestReference, dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"backtest reference {path} is unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("format") != BACKTEST_REFERENCE_FORMAT:
        raise ValueError(
            f"backtest reference {path} must be a "
            f"{BACKTEST_REFERENCE_FORMAT} document "
            f"(got {doc.get('format') if isinstance(doc, dict) else type(doc)})")
    reference = BacktestReference(
        sharpe=_finite(doc.get("sharpe")),
        cost_bps=_finite(doc.get("cost_bps")),
        max_drawdown_frac=_finite(doc.get("max_drawdown_frac")),
    )
    return reference, doc


def build_ladder_evidence(root: str | Path, *, backtest_reference: str | Path,
                          out: str | Path, study: str,
                          risk_state: str | Path | None = None,
                          strategy_state: str | Path | None = None) -> dict[str, Any]:
    """Write the evidence document a promotion must cite.

    Every number is derived here from hashed journals plus a referenced
    backtest document; the document carries this module's own source hash so a
    hand-edited number cannot pass :meth:`LadderController.promote`.
    """
    reference_path = Path(backtest_reference)
    reference, reference_doc = _load_backtest_reference(reference_path)
    halted = False
    if strategy_state is not None:
        try:
            ladder_state = json.loads(
                Path(strategy_state).read_text(encoding="utf-8"))
            halted = bool(ladder_state.get("demoted", False))
        except (OSError, ValueError):
            halted = True  # unreadable risk state is not "not halted"
    live, detail, files = live_statistics(
        root, risk_state=risk_state, halted=halted)

    doc: dict[str, Any] = {
        "format": PROMOTION_EVIDENCE_FORMAT,
        "study": study,
        "as_of_utc": datetime.now(UTC).isoformat(),
        "gate": "NO-GO",
        "generated_by": {
            "module": EVIDENCE_GENERATOR_MODULE,
            "code_sha256": _sha256(Path(__file__)),
            "note": ("derived from the journals below; a hand-typed number is "
                     "refused by the ladder controller"),
        },
        "live": {
            "round_trips": live.round_trips,
            "days": live.days,
            "sharpe": _num(live.sharpe, 6),
            "cost_bps": _num(live.cost_bps, 4),
            "max_drawdown_frac": _num(live.max_drawdown_frac, 6),
            "halted": live.halted,
            "detail": detail,
        },
        "backtest": {
            "reference": str(reference_path),
            "sharpe": reference.sharpe,
            "cost_bps": reference.cost_bps,
            "max_drawdown_frac": reference.max_drawdown_frac,
            "study": reference_doc.get("study"),
        },
        "sources": [
            {"kind": "journal", "path": str(path), "sha256": _sha256(path)}
            for path in files
        ] + [{"kind": "backtest", "path": str(reference_path),
              "sha256": _sha256(reference_path)}],
    }
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    return doc


def cmd_pnl(args: argparse.Namespace) -> int:
    """``cryptobot pnl daily`` (thin command wrapper)."""
    command = getattr(args, "pnl_cmd", None)
    if command != "daily":
        print(f"pnl: unknown command {command!r}", file=sys.stderr)
        return 2
    try:
        day = date.fromisoformat(args.date) if args.date else None
    except ValueError:
        print(f"pnl: bad --date {args.date!r}; want YYYY-MM-DD", file=sys.stderr)
        return 2
    doc = daily_report(args.root, day=day)
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    if args.json:
        sys.stdout.write(text)
    else:
        sys.stdout.write(render_markdown(doc))
        if args.out:
            print(f"pnl: wrote {args.out}")
    if doc["corruption"]:
        print(f"pnl: {len(doc['corruption'])} corrupt journal entr"
              f"{'y' if len(doc['corruption']) == 1 else 'ies'} reported",
              file=sys.stderr)
        return 1
    return 0


__all__ = [
    "BACKTEST_REFERENCE_FORMAT",
    "SCHEMA_VERSION",
    "build_ladder_evidence",
    "cmd_pnl",
    "daily_report",
    "live_statistics",
    "render_markdown",
]
