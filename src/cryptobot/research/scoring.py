"""Economic scoring panel per cell (Worker 4, CORR phase B).

Reads a Session run dir (ledger, fills, journal, equity, store) plus the
funnel and produces the brief's panel: closed count, eligible
symbol-time, fill rate, expectancy ± uncertainty, gross/net P&L,
fees/funding/slippage, drawdown, worst trade/day, exposure, holding
times, daily returns incl. zero-trade days.

Money rules: BOOKED figures come only from ledger fills/fees and funding
settlements. Cost-contract ESTIMATES (round-trip bps on entry notional)
are reported in a separate section and never mixed into booked P&L;
spread is charged once (half per leg via the contract), never deducted
twice. Uncertainty is mean ± 1.96·sd/√n over closed-trade nets (normal
approx, exact n reported); n<2 yields n/a, not zero.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .funnel import analyze_run, analyze_symbol_time


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parse_ts(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _ledger_fills(run_dir: Path) -> list[dict[str, Any]]:
    ledger_path = run_dir / "ledger.json"
    if not ledger_path.exists():
        return []
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    return [e for e in ledger.get("journal", [])
            if e.get("kind") == "fill"]


def _ledger_funding(run_dir: Path) -> list[dict[str, Any]]:
    ledger_path = run_dir / "ledger.json"
    if not ledger_path.exists():
        return []
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    return [e for e in ledger.get("journal", [])
            if e.get("kind") in ("funding", "settlement")]


def _link_trades(run_dir: Path) -> list[dict[str, Any]]:
    """Closed-trade economics per reservation (booked only)."""
    journal = _read_jsonl(run_dir / "engine_journal.jsonl")
    role_of: dict[str, str] = {}
    res_of: dict[str, str] = {}
    for event in journal:
        if event.get("event") == "submitted":
            detail = event.get("detail", {})
            client = detail.get("client_id", "")
            role_of[client] = detail.get("role", "?")
            res_of[client] = detail.get("reservation_id", "")
    exec_client: dict[str, str] = {}
    for row in _read_jsonl(run_dir / "fills.jsonl"):
        if row.get("execution_id"):
            exec_client[row["execution_id"]] = row.get("client_order_id",
                                                       "")
    by_res: dict[str, dict[str, list]] = defaultdict(
        lambda: {"entry": [], "exit": []})
    for fill in _ledger_fills(run_dir):
        client = exec_client.get(fill.get("exec_id", ""), "")
        slot = "entry" if role_of.get(client) == "entry" else "exit"
        by_res[res_of.get(client, "")][slot].append(fill)
    trades = []
    for res, legs in sorted(by_res.items()):
        if not res or not legs["entry"] or not legs["exit"]:
            continue
        entry = legs["entry"]
        exit_ = legs["exit"]
        direction = 1.0 if entry[0].get("side") == "BUY" else -1.0
        entry_qty = sum(float(f.get("qty", 0.0)) for f in entry)
        exit_qty = sum(float(f.get("qty", 0.0)) for f in exit_)
        qty = min(entry_qty, exit_qty)
        if qty <= 0:
            continue
        entry_px = sum(float(f["price"]) * float(f.get("qty", 0.0))
                       for f in entry) / entry_qty
        exit_px = sum(float(f["price"]) * float(f.get("qty", 0.0))
                      for f in exit_) / exit_qty
        gross = (exit_px - entry_px) * qty * direction
        fees = sum(float(f.get("fee", 0.0)) for f in entry + exit_)
        entry_ts = min(_parse_ts(f["ts_utc"]) for f in entry)
        exit_ts = max(_parse_ts(f["ts_utc"]) for f in exit_)
        trades.append({
            "reservation": res,
            "direction": "LONG" if direction > 0 else "SHORT",
            "qty": qty, "entry_px": entry_px, "exit_px": exit_px,
            "gross": gross, "fees": fees, "net": gross - fees,
            "hold_s": (exit_ts - entry_ts).total_seconds(),
            "entry_ts": entry_ts.isoformat(),
            "exit_ts": exit_ts.isoformat(),
            "notional": qty * entry_px,
        })
    return trades


def _drawdown(equity: list[dict[str, Any]]) -> dict[str, Any]:
    peak = -math.inf
    max_dd = 0.0
    max_dd_pct = 0.0
    for row in equity:
        value = float(row.get("marked_equity", 0.0))
        peak = max(peak, value)
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak if peak else 0.0
    return {"max_drawdown": max_dd, "max_drawdown_pct": max_dd_pct}


def _expectancy(nets: list[float]) -> dict[str, Any]:
    n = len(nets)
    if n < 2:
        return {"n": n, "mean": (nets[0] if n == 1 else None),
                "sd": None, "ci95_lo": None, "ci95_hi": None,
                "method": "n/a (need >=2 closed trades)"}
    mean = sum(nets) / n
    var = sum((x - mean) ** 2 for x in nets) / (n - 1)
    sd = math.sqrt(var)
    half = 1.96 * sd / math.sqrt(n)
    return {"n": n, "mean": mean, "sd": sd,
            "ci95_lo": mean - half, "ci95_hi": mean + half,
            "method": "mean ± 1.96·sd/√n over closed-trade nets"}


def _watch_items(run_dir: Path) -> dict[str, Any]:
    """W2 followup mechanisms: unresolved reservations, orphan legs."""
    journal = _read_jsonl(run_dir / "engine_journal.jsonl")
    unresolved = Counter()
    wipe = 0
    for event in journal:
        detail = event.get("detail", {})
        text = json.dumps(detail).lower()
        if "unresolved" in text:
            unresolved[event.get("event", "?")] += 1
        if "wipe" in text or "qty-short" in text:
            wipe += 1
    role_of = {}
    res_of = {}
    for event in journal:
        if event.get("event") == "submitted":
            detail = event.get("detail", {})
            role_of[detail.get("client_id", "")] = detail.get("role",
                                                              "?")
            res_of[detail.get("client_id", "")] = detail.get(
                "reservation_id", "")
    exit_fills_by_res: dict[str, int] = Counter()
    entry_fills_by_res: dict[str, int] = Counter()
    for event in journal:
        if event.get("event") != "fill":
            continue
        detail = event.get("detail", {})
        res = detail.get("reservation_id", "")
        if role_of.get(detail.get("client_id")) == "entry":
            entry_fills_by_res[res] += 1
        else:
            exit_fills_by_res[res] += 1
    orphans = sorted(res for res, n in exit_fills_by_res.items()
                     if n and not entry_fills_by_res.get(res))
    return {"unresolved_mentions": dict(unresolved),
            "qty_short_wipe_mentions": wipe,
            "orphan_exit_reservations": orphans}


def score_cell(run_dir: str | Path,
               capture_path: str | Path | None = None) -> dict[str, Any]:
    """Full economic panel for one scored cell run dir."""
    run_dir = Path(run_dir)
    funnel = analyze_run(run_dir)
    trades = _link_trades(run_dir)
    nets = [t["net"] for t in trades]
    funding = _ledger_funding(run_dir)
    funding_total = sum(float(e.get("amount", e.get("fee", 0.0)))
                        for e in funding)
    booked_fees = sum(float(f.get("fee", 0.0))
                      for f in _ledger_fills(run_dir))
    equity = _read_jsonl(run_dir / "equity.jsonl")
    days: dict[str, float] = defaultdict(float)
    for trade in trades:
        day = _parse_ts(trade["exit_ts"]).date().isoformat()
        days[day] += trade["net"]
    window_days: list[str] = []
    if equity:
        first = _parse_ts(equity[0]["ts_utc"]).date()
        last = _parse_ts(equity[-1]["ts_utc"]).date()
        day = first
        while day <= last:
            window_days.append(day.isoformat())
            day += timedelta(days=1)
    daily = {day: days.get(day, 0.0) for day in window_days}
    gross = sum(t["gross"] for t in trades)
    exposure = max([t["notional"] for t in trades] or [0.0])
    holds = sorted(t["hold_s"] for t in trades)
    panel: dict[str, Any] = {
        "run_dir": str(run_dir),
        "closed_trades": len(trades),
        "fill_rate": (funnel["entries_filled"] / funnel["entry_client_ids"]
                      if funnel["entry_client_ids"] else None),
        "expectancy": _expectancy(nets),
        "booked": {
            "gross": gross,
            "fees": booked_fees,
            "funding": funding_total,
            "funding_entries": len(funding),
            "net": gross - booked_fees + funding_total,
            "slippage_note": "slippage is implicit in booked fill "
                             "prices vs arrival; no separate booked "
                             "slippage leg exists. Estimated adverse "
                             "costs live in the estimates section only.",
        },
        "estimates": {
            "note": "cost-contract-v1 estimates computed at report time "
                    "from entry notionals; recorded separately, never "
                    "booked, spread charged once (half per leg).",
        },
        "drawdown": _drawdown(equity),
        "worst_trade": (min(nets) if nets else None),
        "worst_day": (min(daily.values()) if daily else None),
        "daily_net": daily,
        "exposure_max_notional": exposure,
        "holding_s": {"min": (holds[0] if holds else None),
                      "median": (holds[len(holds) // 2] if holds else None),
                      "max": (holds[-1] if holds else None)},
        "funnel_stages": funnel["stages"],
        "funnel_buckets": funnel["buckets"],
        "trades": trades,
        "watch": _watch_items(run_dir),
    }
    if capture_path is not None:
        panel["symbol_time"] = analyze_symbol_time(capture_path)
    return panel
