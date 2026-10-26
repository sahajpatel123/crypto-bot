"""E-COST realized-cost measurement harness (measurement only).

Implements Synapse's E-COST plan: confirm or restate the cost assumptions
the forward studies trade against (B4b/F-CARRY 49 bps RT + sqrt impact,
B4/C1 53 bps, D1 14.0+0.1x|shock| bps + funding). This tool is not a
strategy: it has no gates that pass, no P&L claim, no trial cell, no DSR,
and it can only CONFIRM modeled costs or RESTATE them. Costs move in the
conservative direction only (upward restatements trigger re-gating;
downward restatements are recorded, never adopted without a new prereg).

Owner/agent split: the agent builds this harness + report template +
reconciliation checks; the owner runs the 30-day fills on Binance demo
(trade-only keys) and approves any restatement. This module makes no
live/demo calls and reads no holdout bytes: receipts come from a JSONL
file the owner produces, funding expectations from Vision monthly files
strictly newer than 2026-10.

Fail-closed rules (a refusal exits 2 and writes no verdict):
  * every receipt/config field must be present and observed -- nothing is
    defaulted anywhere (a missing or null field refuses);
  * exactly one venue_path (demo|sim) per sample -- mixed samples refuse;
  * fill_time must be after 2026-10-17 and funding vision months after
    2026-10 (the Oct funding file is holdout-dated, never decoded);
  * funding must reconcile to zero vs Vision or no verdict is emitted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

FORMAT = "cryptobot-ecost-report/1"
CUTOFF_DAY = "2026-10-17"
CUTOFF_MONTH = "2026-10"
MIN_WINDOW_DAYS = 30
MIN_FILLS_PER_LEG = 20
WINDOW_EXTEND_DAYS = 30
WINDOW_MAX_DAYS = 90
FUNDING_TOL_BP = 1e-6  # paid-vs-Vision must reconcile to (numerical) zero

VENUE_PATHS = ("demo", "sim")
LEGS = ("spot", "perp")
SIDES = ("buy", "sell")

FILL_FIELDS = ("fill_id", "venue_path", "symbol", "leg", "side", "qty",
               "notional", "fill_price", "signal_bar_open", "spread_bps",
               "fee_bps", "fill_time", "round_trip_id", "adv20", "sigma_d")
FUNDING_FIELDS = ("record_id", "venue_path", "symbol", "settlement_time",
                  "paid_rate_bp", "vision_rate_bp", "vision_file")
CONFIG_FIELDS = ("study", "modeled_rt_bps", "modeled_fee_bps",
                 "modeled_spread_bps", "fee_tier_evidence")


class ECostRefusal(Exception):
    """The sample cannot support a verdict; fix the data, not the tool."""


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _parse_utc(value: object, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ECostRefusal(f"{field} must be an ISO-8601 UTC string")
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ECostRefusal(f"{field} is not a valid timestamp: {value!r}") from None
    if stamp.tzinfo is None:
        raise ECostRefusal(f"{field} must carry a timezone: {value!r}")
    return stamp.astimezone(dt.UTC)


def _finite(value: object, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ECostRefusal(f"{field} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ECostRefusal(f"{field} must be finite, got {value!r}")
    if minimum is not None and number < minimum:
        raise ECostRefusal(f"{field} must be >= {minimum}, got {value!r}")
    return number


def _required(record: dict, field: str, where: str) -> object:
    if field not in record or record[field] is None:
        raise ECostRefusal(f"{where}: missing observed field {field!r} "
                           f"(nothing is defaulted)")
    return record[field]


def _month_of_vision_file(name: object) -> str:
    if not isinstance(name, str):
        raise ECostRefusal(f"vision_file must be a string, got {name!r}")
    stem = name.rsplit(".", 1)[0]
    month = "-".join(stem.rsplit("-", 2)[-2:])
    try:
        dt.datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise ECostRefusal(
            f"vision_file carries no YYYY-MM month: {name!r}") from None
    return month


def load_receipts(path: Path) -> tuple[list[dict], list[dict]]:
    """Parse and validate a receipts JSONL file (fills + funding records)."""
    fills: list[dict] = []
    funding: list[dict] = []
    venue_path: str | None = None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ECostRefusal(f"cannot read receipts: {exc}") from None
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            raise ECostRefusal(f"line {lineno}: not JSON") from None
        if not isinstance(record, dict):
            raise ECostRefusal(f"line {lineno}: must be an object")
        kind = record.get("kind")
        where = f"line {lineno}"
        if kind == "fill":
            parsed = _parse_fill(record, where)
        elif kind == "funding":
            parsed = _parse_funding(record, where)
        else:
            raise ECostRefusal(f"{where}: kind must be fill|funding, "
                               f"got {kind!r}")
        if venue_path is None:
            venue_path = parsed["venue_path"]
        elif parsed["venue_path"] != venue_path:
            raise ECostRefusal(
                f"{where}: venue_path {parsed['venue_path']!r} mixes with "
                f"{venue_path!r} -- demo and sim are never mixed in one sample")
        (fills if kind == "fill" else funding).append(parsed)
    if not fills:
        raise ECostRefusal("no fill records in sample")
    return fills, funding


def _parse_fill(record: dict, where: str) -> dict:
    for field in FILL_FIELDS:
        _required(record, field, where)
    venue_path = record["venue_path"]
    leg = record["leg"]
    side = record["side"]
    if venue_path not in VENUE_PATHS:
        raise ECostRefusal(f"{where}: venue_path must be demo|sim")
    if leg not in LEGS:
        raise ECostRefusal(f"{where}: leg must be spot|perp")
    if side not in SIDES:
        raise ECostRefusal(f"{where}: side must be buy|sell")
    symbol = record["symbol"]
    fill_id = record["fill_id"]
    round_trip_id = record["round_trip_id"]
    for name, value in (("symbol", symbol), ("fill_id", fill_id),
                        ("round_trip_id", round_trip_id)):
        if not isinstance(value, str) or not value.strip():
            raise ECostRefusal(f"{where}: {name} must be a non-empty string")
    stamp = _parse_utc(record["fill_time"], f"{where}.fill_time")
    if stamp.date().isoformat() <= CUTOFF_DAY:
        raise ECostRefusal(f"{where}: fill_time is not after {CUTOFF_DAY}")
    qty = _finite(record["qty"], f"{where}.qty", minimum=0.0)
    notional = _finite(record["notional"], f"{where}.notional", minimum=0.0)
    fill_price = _finite(record["fill_price"], f"{where}.fill_price",
                         minimum=0.0)
    signal_open = _finite(record["signal_bar_open"],
                          f"{where}.signal_bar_open", minimum=0.0)
    spread_bps = _finite(record["spread_bps"], f"{where}.spread_bps",
                         minimum=0.0)
    fee_bps = _finite(record["fee_bps"], f"{where}.fee_bps", minimum=0.0)
    adv20 = _finite(record["adv20"], f"{where}.adv20", minimum=0.0)
    sigma_d = _finite(record["sigma_d"], f"{where}.sigma_d", minimum=0.0)
    if qty <= 0 or notional <= 0 or fill_price <= 0 or signal_open <= 0:
        raise ECostRefusal(f"{where}: qty/notional/prices must be > 0")
    if adv20 <= 0:
        raise ECostRefusal(f"{where}: adv20 must be > 0 (impact proxy needs it)")
    sign = 1.0 if side == "buy" else -1.0
    slippage_bps = sign * (fill_price - signal_open) / signal_open * 1e4
    modeled_impact_bps = 0.5 * sigma_d * math.sqrt(notional / adv20) * 1e4
    return {"fill_id": fill_id, "venue_path": venue_path,
            "symbol": symbol.upper(), "leg": leg, "side": side, "qty": qty,
            "notional": notional, "fill_price": fill_price,
            "signal_bar_open": signal_open, "spread_bps": spread_bps,
            "fee_bps": fee_bps, "fill_time": stamp.isoformat(),
            "fill_ms": int(stamp.timestamp() * 1000),
            "round_trip_id": round_trip_id, "adv20": adv20, "sigma_d": sigma_d,
            "slippage_bps": slippage_bps,
            "fill_cost_bps": fee_bps + slippage_bps,
            "modeled_impact_bps": modeled_impact_bps}


def _parse_funding(record: dict, where: str) -> dict:
    for field in FUNDING_FIELDS:
        _required(record, field, where)
    if record["venue_path"] not in VENUE_PATHS:
        raise ECostRefusal(f"{where}: venue_path must be demo|sim")
    symbol = record["symbol"]
    record_id = record["record_id"]
    for name, value in (("symbol", symbol), ("record_id", record_id)):
        if not isinstance(value, str) or not value.strip():
            raise ECostRefusal(f"{where}: {name} must be a non-empty string")
    stamp = _parse_utc(record["settlement_time"], f"{where}.settlement_time")
    paid = _finite(record["paid_rate_bp"], f"{where}.paid_rate_bp")
    vision = _finite(record["vision_rate_bp"], f"{where}.vision_rate_bp")
    month = _month_of_vision_file(record["vision_file"])
    if month <= CUTOFF_MONTH:
        raise ECostRefusal(f"{where}: vision_file month {month} is not after "
                           f"{CUTOFF_MONTH} (Oct file is holdout-dated)")
    return {"record_id": record_id, "venue_path": record["venue_path"],
            "symbol": symbol.upper(),
            "settlement_time": stamp.isoformat(),
            "paid_rate_bp": paid, "vision_rate_bp": vision,
            "vision_file": record["vision_file"], "delta_bp": paid - vision}


def load_config(path: Path) -> dict:
    """Parse and validate the modeled-cost + fee-tier config (no defaults)."""
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ECostRefusal(f"cannot read config: {exc}") from None
    if not isinstance(config, dict):
        raise ECostRefusal("config must be an object")
    for field in CONFIG_FIELDS:
        _required(config, field, "config")
    if not isinstance(config["study"], str) or not config["study"].strip():
        raise ECostRefusal("config.study must be a non-empty string")
    modeled_rt = _finite(config["modeled_rt_bps"], "config.modeled_rt_bps",
                         minimum=0.0)
    if modeled_rt <= 0:
        raise ECostRefusal("config.modeled_rt_bps must be > 0")
    for section in ("modeled_fee_bps", "modeled_spread_bps"):
        block = config[section]
        if not isinstance(block, dict):
            raise ECostRefusal(f"config.{section} must be an object")
        for leg in LEGS:
            if leg not in block or block[leg] is None:
                raise ECostRefusal(f"config.{section} is missing {leg!r}")
            _finite(block[leg], f"config.{section}.{leg}", minimum=0.0)
    evidence = config["fee_tier_evidence"]
    if not isinstance(evidence, dict):
        raise ECostRefusal("config.fee_tier_evidence must be an object")
    for field in ("vip_level", "bnb_burn", "source"):
        if field not in evidence or evidence[field] is None:
            raise ECostRefusal(
                f"config.fee_tier_evidence is missing {field!r}")
    return config


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = math.ceil(pct / 100.0 * len(ordered)) - 1
    return ordered[max(0, min(rank, len(ordered) - 1))]


def build_round_trips(fills: list[dict]) -> dict[str, list[dict]]:
    """Group fills into round trips; RT bps weight each fill by notional.

    realized_RT = SUM(fill_cost_bps_i * notional_i / rt_notional) where
    rt_notional is the earliest fill's notional (the entry size). A group
    with fewer than 2 fills is malformed grouping and refuses.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for fill in fills:
        groups.setdefault((fill["symbol"], fill["round_trip_id"]),
                          []).append(fill)
    trips: dict[str, list[dict]] = {}
    for (symbol, trip_id), legs in sorted(groups.items()):
        if len(legs) < 2:
            raise ECostRefusal(
                f"round trip {symbol}/{trip_id} holds {len(legs)} fill(s); "
                f"a round trip needs open + close (>= 2 fills)")
        ordered = sorted(legs, key=lambda row: row["fill_ms"])
        rt_notional = ordered[0]["notional"]
        rt_bps = sum(row["fill_cost_bps"] * row["notional"] / rt_notional
                     for row in ordered)
        trips.setdefault(symbol, []).append(
            {"round_trip_id": trip_id, "fills": len(ordered),
             "rt_notional": rt_notional, "realized_rt_bps": rt_bps,
             "fill_ids": [row["fill_id"] for row in ordered]})
    return trips


def check_power(fills: list[dict]) -> dict:
    """The 30-day / 20-fills-per-leg power gate (UNDER_POWERED if missed)."""
    stamps = sorted(fill["fill_ms"] for fill in fills)
    start = dt.datetime.fromtimestamp(stamps[0] / 1000, tz=dt.UTC)
    end = dt.datetime.fromtimestamp(stamps[-1] / 1000, tz=dt.UTC)
    window_days = (end.date() - start.date()).days + 1
    per_leg: dict[str, int] = {}
    for fill in fills:
        key = f"{fill['symbol']}/{fill['leg']}"
        per_leg[key] = per_leg.get(key, 0) + 1
    short = sorted(key for key, count in per_leg.items()
                   if count < MIN_FILLS_PER_LEG)
    # Legs with zero fills never appear above; they fail the gate too.
    symbols = sorted({fill["symbol"] for fill in fills})
    for symbol in symbols:
        for leg in LEGS:
            key = f"{symbol}/{leg}"
            if key not in per_leg:
                short.append(key)
    short = sorted(set(short))
    powered = window_days >= MIN_WINDOW_DAYS and not short
    guidance = ""
    descriptive_only = False
    if not powered:
        if window_days >= WINDOW_MAX_DAYS:
            descriptive_only = True
            guidance = (f"window is {window_days}d (>= {WINDOW_MAX_DAYS}d): "
                        f"report descriptive statistics only, no confirmation")
        else:
            blocks = 0
            days = window_days
            while days < MIN_WINDOW_DAYS and days < WINDOW_MAX_DAYS:
                days += WINDOW_EXTEND_DAYS
                blocks += 1
            guidance = (f"extend the window in {WINDOW_EXTEND_DAYS}-day "
                        f"blocks (now {window_days}d; next target "
                        f"{min(days, WINDOW_MAX_DAYS)}d, max {WINDOW_MAX_DAYS}d)")
    return {"window_start": start.isoformat(), "window_end": end.isoformat(),
            "window_days": window_days,
            "window_days_required": MIN_WINDOW_DAYS,
            "fills_per_leg": dict(sorted(per_leg.items())),
            "fills_per_leg_required": MIN_FILLS_PER_LEG,
            "short_legs": short, "powered": powered,
            "descriptive_only": descriptive_only, "guidance": guidance}


def decide(trips: dict[str, list[dict]], funding: list[dict],
           config: dict) -> dict:
    """Apply the four frozen decision rules (funding must reconcile)."""
    deltas = [abs(row["delta_bp"]) for row in funding]
    max_delta = max(deltas) if deltas else 0.0
    reconciled = max_delta <= FUNDING_TOL_BP
    if not reconciled:
        raise ECostRefusal(
            f"funding does not reconcile to zero vs Vision "
            f"(max |delta| {max_delta:.6f} bp over {len(funding)} records); "
            f"no verdict -- fix the data")
    modeled = float(config["modeled_rt_bps"])
    per_symbol: dict[str, dict] = {}
    for symbol in sorted(trips):
        rts = [trip["realized_rt_bps"] for trip in trips[symbol]]
        per_symbol[symbol] = {
            "n": len(rts),
            "median_rt_bps": statistics.median(rts),
            "p90_rt_bps": _percentile(rts, 90),
            "min_rt_bps": min(rts),
            "max_rt_bps": max(rts),
        }
    medians = {symbol: stats["median_rt_bps"]
               for symbol, stats in per_symbol.items()}
    tails = {symbol: stats["p90_rt_bps"] for symbol, stats in per_symbol.items()}
    if any(value > 2.0 * modeled for value in medians.values()):
        verdict = "COST-MODEL-KILLED"
        reason = ("median realized RT exceeds 2x modeled RT: the modeled "
                  "cost assumption is dead; dependent studies return to "
                  "UNDERPOWERED-pending-remodel, never to PASS")
    elif any(value > modeled for value in medians.values()):
        verdict = "RESTATE-UP"
        reason = ("median realized RT exceeds modeled RT: dependent cost "
                  "models restate to realized medians and dependent verdicts "
                  "re-gate; no live study continues on the old numbers")
    elif any(value > 2.0 * modeled for value in tails.values()):
        # Conservative extension of the draft (documented, reviewable): the
        # median passes but the tail pays >2x modeled. CONFIRMED is forbidden
        # by its own p90 clause, so the only conservative verdict is a
        # restatement naming the tail -- costs never ease on ambiguity.
        verdict = "RESTATE-UP"
        reason = ("p90 realized RT exceeds 2x modeled RT with median inside "
                  "model: tail restatement, conservative direction only; "
                  "restated medians at/below modeled are recorded, not "
                  "adopted (plan's conservative-direction adoption rule)")
    else:
        verdict = "CONFIRMED"
        reason = ("median realized RT <= modeled RT per symbol, p90 <= 2x "
                  "modeled, funding reconciles to zero")
    restated = {symbol: stats["median_rt_bps"] for symbol, stats in
                per_symbol.items()} if verdict == "RESTATE-UP" else {}
    return {"verdict": verdict, "verdict_reason": reason,
            "per_symbol": per_symbol, "modeled_rt_bps": modeled,
            "restated_rt_bps": restated,
            "funding_reconciled": reconciled,
            "funding_max_abs_delta_bp": max_delta,
            "funding_records": len(funding)}


def component_deltas(fills: list[dict], config: dict) -> dict:
    """Realized-vs-modeled deltas per cost component (diagnostic)."""
    out: dict[str, dict] = {}
    for leg in LEGS:
        rows = [row for row in fills if row["leg"] == leg]
        if not rows:
            continue
        fee = statistics.median(row["fee_bps"] for row in rows)
        spread = statistics.median(row["spread_bps"] for row in rows)
        slip = statistics.median(row["slippage_bps"] for row in rows)
        modeled_fee = float(config["modeled_fee_bps"][leg])
        modeled_spread = float(config["modeled_spread_bps"][leg])
        out[leg] = {"n": len(rows),
                    "median_fee_bps": fee, "modeled_fee_bps": modeled_fee,
                    "fee_delta_bps": fee - modeled_fee,
                    "median_spread_bps": spread,
                    "modeled_spread_bps": modeled_spread,
                    "spread_delta_bps": spread - modeled_spread,
                    "median_slippage_bps": slip}
    return out


def build_report(fills: list[dict], funding: list[dict], config: dict,
                 receipts_path: Path) -> dict:
    """Assemble the full E-COST report document (verdict or UNDERPOWERED)."""
    power = check_power(fills)
    trips = build_round_trips(fills)
    table = [{key: row[key] for key in
              ("fill_id", "symbol", "leg", "side", "qty", "notional",
               "fill_price", "signal_bar_open", "spread_bps", "fee_bps",
               "slippage_bps", "fill_cost_bps", "modeled_impact_bps",
               "fill_time", "round_trip_id", "adv20", "sigma_d")}
             for row in sorted(fills, key=lambda row: row["fill_ms"])]
    config_blob = json.dumps(config, sort_keys=True).encode()
    report: dict = {
        "format": FORMAT,
        "generated_utc": _utc_now(),
        "study": config["study"],
        "measurement_only": True,
        "venue_path": fills[0]["venue_path"],
        "venue_paths_seen": sorted({row["venue_path"] for row in fills}),
        "receipts_file": receipts_path.name,
        "power": power,
        "fills_table": table,
        "round_trips": trips,
        "components": component_deltas(fills, config),
        "fee_tier_evidence": config["fee_tier_evidence"],
        "fee_tier_note": ("assumed VIP-0 taker/maker schedule stands unless "
                          "the filling account proves better, and better is "
                          "never adopted without a new preregistration"),
        "config_hash": hashlib.sha256(config_blob).hexdigest(),
    }
    if not power["powered"]:
        report["verdict"] = "UNDERPOWERED"
        report["verdict_reason"] = power["guidance"]
        report["descriptive_only"] = power["descriptive_only"]
        return report
    decision = decide(trips, funding, config)
    report.update(decision)
    return report


def write_templates(out_dir: Path) -> dict[str, str]:
    """Emit blank receipt + config templates for the owner to fill in."""
    out_dir.mkdir(parents=True, exist_ok=True)
    receipts = out_dir / "receipt-template.jsonl"
    receipts.write_text(
        json.dumps({"kind": "fill", "fill_id": "FILL-0001",
                    "venue_path": "demo", "symbol": "BTCUSDT", "leg": "spot",
                    "side": "buy", "qty": 0.01, "notional": 800.0,
                    "fill_price": 80000.0, "signal_bar_open": 79950.0,
                    "spread_bps": 1.0, "fee_bps": 15.0,
                    "fill_time": "2026-11-05T00:00:07+00:00",
                    "round_trip_id": "RT-0001", "adv20": 500000000.0,
                    "sigma_d": 0.03}) + "\n"
        + json.dumps({"kind": "funding", "record_id": "FUND-0001",
                      "venue_path": "demo", "symbol": "BTCUSDT",
                      "settlement_time": "2026-11-05T00:00:00+00:00",
                      "paid_rate_bp": 1.0, "vision_rate_bp": 1.0,
                      "vision_file": "BTCUSDT-fundingRate-2026-11.zip"}) + "\n",
        encoding="utf-8")
    config = out_dir / "config-template.json"
    config.write_text(json.dumps({
        "study": "B4b",
        "modeled_rt_bps": 49.0,
        "modeled_fee_bps": {"spot": 15.0, "perp": 7.5},
        "modeled_spread_bps": {"spot": 1.0, "perp": 1.0},
        "fee_tier_evidence": {"vip_level": "VIP-0", "bnb_burn": False,
                              "source": "demo account statement 2026-11-05"},
    }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"receipts": str(receipts), "config": str(config)}


def cmd_report(args: argparse.Namespace) -> int:
    try:
        fills, funding = load_receipts(Path(args.receipts))
        config = load_config(Path(args.config))
        report = build_report(fills, funding, config, Path(args.receipts))
    except ECostRefusal as exc:
        print(f"ecost: REFUSED: {exc}", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "ecost-report.json"
    dest.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"],
                      "reason": report["verdict_reason"],
                      "report": str(dest)}, indent=1, sort_keys=True))
    return 0


def cmd_template(args: argparse.Namespace) -> int:
    paths = write_templates(Path(args.out))
    print(json.dumps(paths, indent=1, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ecost",
                                     description="E-COST realized-cost "
                                     "measurement (no live calls)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="validate receipts + write report")
    rep.add_argument("--receipts", required=True)
    rep.add_argument("--config", required=True)
    rep.add_argument("--out", required=True)
    rep.set_defaults(func=cmd_report)
    tpl = sub.add_parser("template", help="emit blank owner templates")
    tpl.add_argument("--out", required=True)
    tpl.set_defaults(func=cmd_template)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
