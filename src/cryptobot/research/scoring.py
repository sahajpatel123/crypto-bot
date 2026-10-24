"""Economic scoring panel per cell (Worker 4, CORR phase B; W2 READY).

Reads a Session run dir (ledger, fills, journal, equity, store) plus the
funnel and produces the brief's panel: closed count, eligible
symbol-time, fill rate, expectancy ± uncertainty, gross/net P&L,
fees/funding/slippage, drawdown, worst trade/day, exposure, holding
times, daily returns incl. zero-trade days.

Money rules: BOOKED figures come only from ledger fills/fees and funding
settlements. Cost-contract ESTIMATES (round-trip bps on entry notional)
are reported in a separate section and never mixed into booked P&L;
spread is charged once (half per leg via the contract), never deducted
twice. Uncertainty is mean ± 1.96·sd/√n over closed-trade nets
(descriptive only: per-trade normal approx, never an independent-day
promotion gate; exact n reported); n<2 yields n/a, not zero.

Episodes: a reservation is OPEN (entries, no exits), PARTIALLY closed
(exits cover some but not all of the filled entry quantity), or CLOSED
(exits cover the full filled quantity). Only CLOSED episodes count as
closed trades. Signed funding attributes to episodes open at the
funding timestamp (equal split, documented) and to the day otherwise;
trade, account, and daily views all include it. Days are Asia/Kolkata
accounting days. A missing ledger never scores as valid-flat.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptobot.accounting.day import accounting_date

from .funnel import analyze_run, analyze_symbol_time

# Quantity dust below this is treated as zero for episode closure.
_QTY_EPS = 1e-9


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parse_ts(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
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


def _ledger_flows(run_dir: Path) -> list[dict[str, Any]]:
    """External cash flows: move equity, never realised P&L."""
    ledger_path = run_dir / "ledger.json"
    if not ledger_path.exists():
        return []
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    return [e for e in ledger.get("journal", [])
            if e.get("kind") == "flow"]


def _ist_day(moment: datetime) -> str:
    """Accounting-day label (Asia/Kolkata) for a timestamp."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return accounting_date(moment).isoformat()


FUNDING_RULE = ("equal split among episodes holding an open "
                "remainder at the funding timestamp; funding with no "
                "open episode attributes to the day only")


def _link_episodes(run_dir: Path) -> dict[str, Any]:
    """Per-reservation episodes: open / partial / closed (booked only).

    Linkage is ledger fills -> fills.jsonl exec->client -> journal
    submitted role/reservation. Closed legs are valued at
    volume-weighted average prices; fees are sunk to the episode that
    incurred them (never pro-rated away). The open remainder carries
    no P&L, only a disclosed cost basis. Returns episodes plus the
    unlinked fills that booked cash without a reservation.
    """
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

    episodes = []
    unlinked: dict[str, list] = {"entry": [], "exit": []}
    for res, legs in sorted(by_res.items()):
        entry = legs["entry"]
        exit_ = legs["exit"]
        if not res:
            # Slot + side sign these exactly (entry BUY = cost,
            # entry SELL = short proceeds, ...); no reservation needed.
            unlinked["entry"].extend(entry)
            unlinked["exit"].extend(exit_)
            continue
        direction = 1.0
        if entry:
            direction = 1.0 if entry[0].get("side") == "BUY" else -1.0
        elif exit_:
            # Exit without entry: infer from the exit side (a SELL
            # exit closes a LONG). Reported, never silently dropped.
            direction = 1.0 if exit_[0].get("side") == "SELL" else -1.0
        entry_qty = sum(float(f.get("qty", 0.0)) for f in entry)
        exit_qty = sum(float(f.get("qty", 0.0)) for f in exit_)
        closed_qty = min(entry_qty, exit_qty)
        open_qty = entry_qty - closed_qty
        overfill_qty = exit_qty - closed_qty
        if entry_qty <= _QTY_EPS and exit_qty > _QTY_EPS:
            status = "orphan-exit"
        elif exit_qty <= _QTY_EPS:
            status = "open"
        elif open_qty <= _QTY_EPS:
            status = "closed"
        else:
            status = "partial"
        entry_px = (sum(float(f["price"]) * float(f.get("qty", 0.0))
                        for f in entry) / entry_qty) if entry else None
        exit_px = (sum(float(f["price"]) * float(f.get("qty", 0.0))
                       for f in exit_) / exit_qty) if exit_ else None
        if status == "orphan-exit":
            closed_gross = direction * exit_px * closed_qty
        elif closed_qty > _QTY_EPS:
            closed_gross = (exit_px - entry_px) * closed_qty * direction
        else:
            closed_gross = 0.0
        overfill_proceeds = (direction * exit_px * overfill_qty
                             if overfill_qty > _QTY_EPS else 0.0)
        fees = sum(float(f.get("fee", 0.0)) for f in entry + exit_)
        entry_ts = min((_parse_ts(f["ts_utc"]) for f in entry),
                       default=None)
        exit_ts = max((_parse_ts(f["ts_utc"]) for f in exit_),
                      default=None)
        open_basis = (-direction * entry_px * open_qty
                      if open_qty > _QTY_EPS else 0.0)
        episodes.append({
            "reservation": res,
            "status": status,
            "direction": "LONG" if direction > 0 else "SHORT",
            "qty": closed_qty, "entry_px": entry_px, "exit_px": exit_px,
            "entry_qty": entry_qty, "exit_qty": exit_qty,
            "closed_qty": closed_qty, "open_qty": open_qty,
            "overfill_qty": overfill_qty,
            "gross": closed_gross + overfill_proceeds,
            "closed_gross": closed_gross,
            "overfill_proceeds": overfill_proceeds,
            "open_basis_flow": open_basis,
            "fees": fees, "funding": 0.0,
            "net": closed_gross + overfill_proceeds - fees,
            "hold_s": ((exit_ts - entry_ts).total_seconds()
                       if entry_ts and exit_ts else None),
            "entry_ts": entry_ts.isoformat() if entry_ts else None,
            "exit_ts": exit_ts.isoformat() if exit_ts else None,
            "notional": closed_qty * (entry_px or 0.0),
            "_entry_dt": entry_ts, "_exit_dt": exit_ts,
        })
    unattributed = _attribute_funding(episodes, _ledger_funding(run_dir))
    for episode in episodes:
        episode["net"] = (episode["closed_gross"]
                          + episode["overfill_proceeds"]
                          - episode["fees"] + episode["funding"])
        del episode["_entry_dt"]
        del episode["_exit_dt"]
    return {"episodes": episodes, "unlinked": unlinked,
            "unattributed_funding": unattributed}


def _attribute_funding(episodes: list[dict[str, Any]],
                       funding: list[dict[str, Any]]) -> list[dict]:
    """Split each funding settlement over episodes open at its ts.

    An episode is open at ts when its first entry is at/before ts and
    it still holds an open remainder then (open and partial episodes
    match any ts from entry on; closed episodes match ts up to their
    last exit). Orphan-exits have no holding window and never match.
    Returns the unattributed funding entries (day-level only).
    """
    unattributed = []
    for entry in funding:
        amount = float(entry.get("amount", entry.get("fee", 0.0)))
        moment = _parse_ts(entry["ts_utc"])
        holders = [e for e in episodes
                   if e["_entry_dt"] is not None
                   and e["_entry_dt"] <= moment
                   and (e["status"] in ("open", "partial")
                        or (e["_exit_dt"] is not None
                            and moment <= e["_exit_dt"]))]
        if not holders:
            unattributed.append(entry)
            continue
        share = amount / len(holders)
        for episode in holders:
            episode["funding"] += share
    return unattributed


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


CI_METHOD = ("descriptive only: mean ± 1.96·sd/√n over "
             "closed-trade nets (per-trade normal approx); not an "
             "independent-day promotion gate")


def _expectancy(nets: list[float]) -> dict[str, Any]:
    n = len(nets)
    if n < 2:
        return {"n": n, "mean": (nets[0] if n == 1 else None),
                "sd": None, "ci95_lo": None, "ci95_hi": None,
                "method": "n/a (need >=2 closed trades); descriptive "
                          "only, not a promotion gate"}
    mean = sum(nets) / n
    var = sum((x - mean) ** 2 for x in nets) / (n - 1)
    sd = math.sqrt(var)
    half = 1.96 * sd / math.sqrt(n)
    return {"n": n, "mean": mean, "sd": sd,
            "ci95_lo": mean - half, "ci95_hi": mean + half,
            "method": CI_METHOD}


def _read_checkpoints(db_path: Path) -> dict[str, Any]:
    """Protection/flatten checkpoint evidence from the run store."""
    if not db_path.exists():
        return {"status": "store-missing", "kinds": {}}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in
                  con.execute("select name from sqlite_master where "
                              "type='table'").fetchall()}
        if "checkpoints" not in tables:
            return {"status": "table-missing", "kinds": {}}
        rows = con.execute("select kind, payload from checkpoints").fetchall()
    finally:
        con.close()
    kinds: Counter = Counter()
    legs_verified: set[str] = set()
    legs_unverified: set[str] = set()
    for kind, payload_raw in rows:
        kinds[kind] += 1
        try:
            payload = json.loads(payload_raw or "{}")
        except ValueError:
            continue
        if kind == "protection-verified":
            legs_verified.update(payload.get("legs", []))
        elif kind == "protection-unverified":
            leg = payload.get("leg")
            if leg:
                legs_unverified.add(leg)
    return {"status": "ok", "kinds": dict(sorted(kinds.items())),
            "legs_verified": sorted(legs_verified),
            "legs_unverified": sorted(legs_unverified)}


def _read_risk_state(run_dir: Path) -> dict[str, Any]:
    """Persisted risk reservations/unresolved/booked (or missing)."""
    path = run_dir / "risk_state.json"
    if not path.exists():
        return {"status": "missing", "reservations": {},
                "unresolved": {}, "booked": {}, "open_position": None}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {"status": "ok",
            "reservations": raw.get("reservations", {}),
            "unresolved": raw.get("unresolved", {}),
            "booked": raw.get("booked", {}),
            "open_position": raw.get("open_position")}


def _watch_items(run_dir: Path,
                 episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """State-based exposure/orphan/quantity evidence (no journal grep).

    Reads submitted/fill/terminal order states, the persisted risk
    reservations, and protection checkpoints. Anything unreadable is
    reported as unknown, never as clean.
    """
    journal = _read_jsonl(run_dir / "engine_journal.jsonl")
    submitted: dict[str, dict[str, Any]] = {}
    filled_qty: dict[str, float] = defaultdict(float)
    terminal: dict[str, str] = {}
    for event in journal:
        detail = event.get("detail", {})
        client = detail.get("client_id", "")
        if event.get("event") == "submitted" and client:
            submitted[client] = {
                "role": detail.get("role", "?"),
                "reservation_id": detail.get("reservation_id", ""),
                "qty": detail.get("qty"),
                "instrument": detail.get("instrument", "?")}
        elif event.get("event") == "fill" and client:
            filled_qty[client] += float(detail.get("qty", 0.0) or 0.0)
        elif event.get("event") == "terminal" and client:
            terminal[client] = str(detail.get("kind", "?"))
    live = sorted(
        ({"client_id": client,
          "role": info["role"],
          "reservation_id": info["reservation_id"],
          "instrument": info["instrument"]}
         for client, info in submitted.items()
         if client not in terminal
         and filled_qty.get(client, 0.0) <= _QTY_EPS),
        key=lambda item: item["client_id"])
    risk = _read_risk_state(run_dir)
    checkpoints = _read_checkpoints(run_dir / "store.db")
    orphans = sorted(e["reservation"] for e in episodes
                     if e["status"] == "orphan-exit")
    by_res = {e["reservation"]: e for e in episodes}
    mismatches = []
    approved = {}
    for rid, raw in risk.get("reservations", {}).items():
        approved[rid] = raw.get("qty")
    for rid, entry in risk.get("unresolved", {}).items():
        reservation = entry.get("reservation", entry)
        approved.setdefault(rid, reservation.get("qty")
                            if isinstance(reservation, dict) else None)
    for rid, episode in sorted(by_res.items()):
        qty_approved = approved.get(rid)
        record = {"reservation": rid,
                  "approved_qty": qty_approved,
                  "entry_filled_qty": episode["entry_qty"],
                  "exit_filled_qty": episode["exit_qty"]}
        bad = False
        if qty_approved is not None and episode["entry_qty"] > _QTY_EPS:
            if abs(float(qty_approved)
                   - episode["entry_qty"]) > _QTY_EPS:
                bad = True
        leg_qtys = sorted({float(submitted[c]["qty"])
                           for c, info in submitted.items()
                           if info["reservation_id"] == rid
                           and info["role"] in ("stop", "target")
                           and submitted[c]["qty"] is not None})
        record["leg_qtys"] = leg_qtys
        if leg_qtys and episode["entry_qty"] > _QTY_EPS:
            if max(leg_qtys) + _QTY_EPS < episode["entry_qty"]:
                bad = True
        if bad:
            mismatches.append(record)
    return {"live_client_ids": live,
            "unresolved_reservations": sorted(risk.get("unresolved", {})),
            "live_reservations": sorted(risk.get("reservations", {})),
            "risk_open_position": risk.get("open_position"),
            "risk_state": risk.get("status"),
            "booked_nonzero": sorted(
                rid for rid, entry in risk.get("booked", {}).items()
                if abs(float(entry.get("net_qty", 0.0) or 0.0)) > _QTY_EPS),
            "orphan_exit_reservations": orphans,
            "quantity_mismatches": mismatches,
            "protection_checkpoints": checkpoints}


def _signed_cashflow(slot: str, fill: dict[str, Any]) -> float:
    """Signed cash proceeds of one fill (+in, -out)."""
    amount = float(fill.get("qty", 0.0)) * float(fill["price"])
    side = fill.get("side")
    if slot == "entry":
        return -amount if side == "BUY" else amount
    return amount if side == "SELL" else -amount


def score_cell(run_dir: str | Path,
               capture_path: str | Path | None = None) -> dict[str, Any]:
    """Full economic panel for one scored cell run dir."""
    run_dir = Path(run_dir)
    funnel = analyze_run(run_dir)
    linked = _link_episodes(run_dir)
    episodes = linked["episodes"]
    trades = [e for e in episodes if e["status"] == "closed"]
    partials = [e for e in episodes if e["status"] == "partial"]
    opens = [e for e in episodes if e["status"] == "open"]
    orphan_exits = [e for e in episodes if e["status"] == "orphan-exit"]
    nets = [t["net"] for t in trades]
    funding = _ledger_funding(run_dir)
    funding_total = sum(float(e.get("amount", e.get("fee", 0.0)))
                        for e in funding)
    flows = _ledger_flows(run_dir)
    flows_total = sum(float(e.get("amount", 0.0)) for e in flows)
    fills = _ledger_fills(run_dir)
    booked_fees = sum(float(f.get("fee", 0.0)) for f in fills)
    ledger_ok = (run_dir / "ledger.json").exists()

    unlinked = linked["unlinked"]
    unlinked_cf = (
        sum(_signed_cashflow("entry", f) for f in unlinked["entry"])
        + sum(_signed_cashflow("exit", f) for f in unlinked["exit"]))
    unlinked_fees = sum(float(f.get("fee", 0.0))
                        for f in unlinked["entry"] + unlinked["exit"])
    unlinked_net = unlinked_cf - unlinked_fees
    unattributed = linked["unattributed_funding"]
    unattributed_total = sum(
        float(e.get("amount", e.get("fee", 0.0))) for e in unattributed)

    equity = _read_jsonl(run_dir / "equity.jsonl")
    # Realized daily: episode nets (closed, partial, open-fee, orphan)
    # by completion day plus day-level funding. Open episodes carry
    # only sunk fees/funding here; their remainder is unrealized.
    days_realized: dict[str, float] = defaultdict(float)
    for episode in episodes:
        stamp = episode["exit_ts"] or episode["entry_ts"]
        if stamp is None:
            continue
        days_realized[_ist_day(_parse_ts(stamp))] += episode["net"]
    for entry in unattributed:
        days_realized[_ist_day(_parse_ts(entry["ts_utc"]))] += float(
            entry.get("amount", entry.get("fee", 0.0)))
    # The window spans every evidence day (equity, episodes, funding,
    # flows): a day with economics outside the equity range must still
    # appear, and zero-trade days inside the range are preserved.
    evidence_days = set()
    for row in equity:
        evidence_days.add(accounting_date(_parse_ts(row["ts_utc"])))
    for episode in episodes:
        for stamp in (episode["entry_ts"], episode["exit_ts"]):
            if stamp is not None:
                evidence_days.add(accounting_date(_parse_ts(stamp)))
    for entry in funding + flows:
        evidence_days.add(accounting_date(_parse_ts(entry["ts_utc"])))
    window_days: list[str] = []
    if evidence_days:
        day = min(evidence_days)
        end = max(evidence_days)
        while day <= end:
            window_days.append(day.isoformat())
            day += timedelta(days=1)
    daily = {day: days_realized.get(day, 0.0) for day in window_days}
    # Marked daily: first/last equity marks per accounting day. Marked
    # includes unrealized; realized does not. Their difference is the
    # unrealized mark delta, never booked as P&L.
    marked_by_day: dict[str, dict[str, float]] = {}
    for row in equity:
        day = _ist_day(_parse_ts(row["ts_utc"]))
        value = float(row.get("marked_equity", 0.0))
        slot = marked_by_day.setdefault(day, {"first": value,
                                              "last": value})
        slot["last"] = value
    daily_marked = {day: {"first": slot["first"], "last": slot["last"],
                          "change": slot["last"] - slot["first"]}
                    for day, slot in sorted(marked_by_day.items())}

    gross = sum(e["gross"] for e in episodes) + unlinked_cf
    if ledger_ok:
        booked: dict[str, Any] = {
            "gross": gross,
            "fees": booked_fees,
            "funding": funding_total,
            "funding_entries": len(funding),
            "funding_rule": FUNDING_RULE,
            "flows": flows_total,
            "flow_entries": len(flows),
            "net": gross - booked_fees + funding_total,
            "slippage_note": "slippage is implicit in booked fill "
                             "prices vs arrival; no separate booked "
                             "slippage leg exists. Estimated adverse "
                             "costs live in the estimates section only.",
        }
    else:
        # Missing ledger: nothing booked, never a valid flat zero.
        booked = {"gross": None, "fees": None, "funding": None,
                  "funding_entries": 0, "funding_rule": FUNDING_RULE,
                  "flows": None, "flow_entries": 0, "net": None,
                  "slippage_note": "ledger missing: no booked figures."}
    realized_total = sum(e["net"] for e in episodes)
    open_basis_total = sum(e["open_basis_flow"] for e in episodes)
    identity_lhs = booked["net"]
    identity_rhs = (realized_total + open_basis_total + unlinked_net
                    + unattributed_total)
    reconciliation = {
        "realized_episodes_net": realized_total,
        "open_basis_flow": open_basis_total,
        "unlinked_net": unlinked_net,
        "unlinked_fills": len(unlinked["entry"]) + len(unlinked["exit"]),
        "unattributed_funding": unattributed_total,
        "booked_net": identity_lhs,
        "identity_holds": (
            identity_lhs is not None
            and abs(identity_lhs - (realized_total + unlinked_net
                                    + unattributed_total)) < 1e-9),
        "identity": "booked.net = realized episodes + unlinked fills "
                    "+ day-level funding (open basis is unrealized "
                    "inventory, disclosed separately, never in net)",
        "cash_net_incl_open_basis": (
            None if identity_lhs is None
            else identity_rhs),
    }
    if equity and ledger_ok:
        marked_first = float(equity[0].get("marked_equity", 0.0))
        marked_last = float(equity[-1].get("marked_equity", 0.0))
        marked_change = marked_last - marked_first
        account_gap = marked_change - realized_total - flows_total
        account_check: dict[str, Any] = {
            "marked_first": marked_first, "marked_last": marked_last,
            "marked_change": marked_change,
            "realized_total": realized_total, "flows_total": flows_total,
            "gap": account_gap,
            "gap_is": "unrealized mark delta on open remainders plus "
                      "anything unmodeled; zero when flat with no "
                      "unlinked fills.",
        }
    else:
        account_check = {"marked_first": None, "marked_last": None,
                         "marked_change": None,
                         "realized_total": realized_total,
                         "flows_total": flows_total, "gap": None,
                         "gap_is": "unavailable without equity + ledger."}

    watch = _watch_items(run_dir, episodes)
    exposure_holds = (
        [e["reservation"] for e in episodes if e["status"] != "closed"]
        or [c["client_id"] for c in watch["live_client_ids"]]
        or watch["unresolved_reservations"]
        or watch["live_reservations"]
        or watch["booked_nonzero"])
    flat_valid = bool(ledger_ok) and not exposure_holds
    if not ledger_ok:
        flat_reason = "ledger missing: flatness unverifiable"
    elif exposure_holds:
        flat_reason = f"exposure held: {exposure_holds}"
    else:
        flat_reason = "ledger present, no open/partial/orphan episodes, "\
            "no live orders, no live/unresolved/booked exposure"

    exposure = max([e["entry_qty"] * (e["entry_px"] or 0.0)
                    for e in episodes] or [0.0])
    holds = sorted(t["hold_s"] for t in trades
                   if t["hold_s"] is not None)
    panel: dict[str, Any] = {
        "run_dir": str(run_dir),
        "ledger_status": "ok" if ledger_ok else "missing",
        "flat_valid": flat_valid,
        "flat_reason": flat_reason,
        "closed_trades": len(trades),
        "partial_episodes": len(partials),
        "open_episodes": len(opens),
        "orphan_exit_episodes": len(orphan_exits),
        "fill_rate": (funnel["entries_filled"] / funnel["entry_client_ids"]
                      if funnel["entry_client_ids"] else None),
        "expectancy": _expectancy(nets),
        "booked": booked,
        "estimates": {
            "note": "cost-contract-v1 estimates computed at report time "
                    "from entry notionals; recorded separately, never "
                    "booked, spread charged once (half per leg).",
        },
        "reconciliation": reconciliation,
        "account_check": account_check,
        "drawdown": _drawdown(equity),
        "worst_trade": (min(nets) if nets else None),
        "worst_day": (min(daily.values()) if daily else None),
        "daily_net": daily,
        "daily_realized_note": "realized only (closed/partial economics "
                               "+ sunk episode fees + funding) by "
                               "Asia/Kolkata day; zero-trade days "
                               "preserved from the equity window.",
        "daily_marked": daily_marked,
        "daily_marked_note": "first/last equity marks per "
                             "Asia/Kolkata day; includes unrealized, "
                             "never booked as P&L.",
        "exposure_max_notional": exposure,
        "holding_s": {"min": (holds[0] if holds else None),
                      "median": (holds[len(holds) // 2] if holds else None),
                      "max": (holds[-1] if holds else None)},
        "funnel_stages": funnel["stages"],
        "funnel_buckets": funnel["buckets"],
        "trades": trades,
        "partial_episode_list": partials,
        "open_episode_list": opens,
        "orphan_exit_list": orphan_exits,
        "unlinked_fills": unlinked,
        "watch": watch,
    }
    if capture_path is not None:
        panel["symbol_time"] = analyze_symbol_time(capture_path)
    return panel
