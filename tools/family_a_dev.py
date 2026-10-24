"""Z2.2: existing Family A dev evaluation on pilot + benchmark_30d.

Reads manifests and the frozen dataset coverage only. Does not write
into the pilot or the benchmark. A hypothesis whose required channel
is absent stays UNDERPOWERED / AWAIT_DATA. There is no Family A trade
simulator in this tree; dev_promotes is the promotion rule, and it is
not applied to an empty list when the data the prereg names is missing.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.market_data.datasets import open_dataset  # noqa: E402
from cryptobot.research.data_root import resolve_data_roots  # noqa: E402
from cryptobot.research.power import estimate_power  # noqa: E402

# Floors copied from the frozen preregs. This file does not edit them.
NEEDS = {
    "H1": {
        "dev_trades": 100, "dev_days": 10, "confirm_trades": 300,
        "channel": "top-of-book L2 depth",
        "absent_if": "no_book",
    },
    "H2": {
        "dev_trades": 100, "dev_days": 20, "confirm_trades": 300,
        "channel": "5-minute bars (book-walk only if depth is recorded)",
        "absent_if": "no_trade_list",
    },
    "H3": {
        "dev_trades": 100, "dev_days": 30, "confirm_trades": 300,
        "channel": "funding plus a position-timed trade list",
        "absent_if": "no_trade_list",
    },
    "H4": {
        "dev_trades": 100, "dev_days": 10, "confirm_trades": 300,
        "channel": "Binance plus Bybit and OKX books",
        "absent_if": "no_other_venue",
    },
    "H5": {
        "dev_trades": 50, "dev_days": 10, "confirm_trades": 300,
        "channel": "liquidation prints plus depth",
        "absent_if": "no_liquidation",
    },
    "H6": {
        "dev_trades": 100, "dev_days": 20, "confirm_trades": 300,
        "channel": "H2 and H3 trade lists (H6 is a filter on them)",
        "absent_if": "no_trade_list",
    },
}


def _pilot(path: Path) -> dict:
    days = []
    caveats: set[str] = set()
    names: Counter[str] = Counter()
    symbols: set[str] = set()
    if not path.is_dir():
        return {"present": False, "days": [], "caveats": [], "files": {}}
    for day in sorted(p for p in path.iterdir() if p.is_dir()):
        manifest = day / "manifest.json"
        if not manifest.is_file():
            continue
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        days.append(str(doc.get("date") or day.name))
        caveats.update(str(c) for c in doc.get("caveats") or [])
        symbols.update(str(s) for s in doc.get("symbols") or [])
        for child in day.iterdir():
            names[child.name] += 1
    return {
        "present": True,
        "days": days,
        "n_days": len(days),
        "symbols": sorted(symbols),
        "caveats": sorted(caveats),
        "files": dict(names),
        "has_book": any("book" in n or "depth" in n or "quote" in n
                        for n in names),
        "has_liquidation": any("liquidat" in n for n in names),
        "has_other_venue": any(v in "".join(names)
                               for v in ("bybit", "okx")),
        "has_trade_list": any(n.startswith("trades") for n in names),
    }


def _benchmark(path: Path) -> dict:
    if not path.is_file():
        return {"present": False}
    handle = open_dataset(path)
    cov = handle.coverage()
    channels: Counter[str] = Counter()
    missing_local = 0
    for source in cov["sources"]:
        channels[str(source.get("channel"))] += 1
        if not source.get("local_exists"):
            missing_local += 1
    notes = str(handle.manifest.get("dataset", {}).get("notes") or "")
    return {
        "present": True,
        "path": str(path),
        "manifest_sha": cov["manifest_sha"],
        "channels": dict(channels),
        "missing_local": missing_local,
        "notes": notes,
        "has_book": "book" in notes.lower() and "never-synced" not in notes.lower(),
        "books_unevaluable": "never-synced" in notes.lower()
        or "no archive BBO" in notes,
        "has_other_venue": any(v in notes.lower() for v in ("bybit", "okx")),
        "has_liquidation": "liquidat" in notes.lower(),
    }


def _blocked(flag: str, pilot: dict, bench: dict) -> str | None:
    if flag == "no_book":
        if pilot.get("has_book") or bench.get("has_book"):
            return None
        return "no L2 / top-of-book history in the pilot or the benchmark"
    if flag == "no_other_venue":
        if pilot.get("has_other_venue") or bench.get("has_other_venue"):
            return None
        return "no Bybit or OKX history"
    if flag == "no_liquidation":
        if pilot.get("has_liquidation") or bench.get("has_liquidation"):
            return None
        return "no liquidation-print history"
    if flag == "no_trade_list":
        if pilot.get("has_trade_list"):
            return None
        return "no strategy trade list; the existing dev rule needs trades"
    return "unknown requirement"


def evaluate(repo: Path) -> dict:
    roots = resolve_data_roots(repo)
    pilot = _pilot(roots.pilot)
    bench = _benchmark(roots.benchmark)
    power = estimate_power([], trades_per_day=1.0).as_dict()
    rows = {}
    out_dir = repo / "research" / "autopilot" / "dev"
    out_dir.mkdir(parents=True, exist_ok=True)
    for hyp, spec in NEEDS.items():
        why = _blocked(spec["absent_if"], pilot, bench)
        if why is None:
            outcome = "UNEVALUATED"
            status = "AWAIT_DATA"
            reason = "required channel is present but no Family A simulator is in this tree"
        else:
            outcome = "UNDERPOWERED"
            status = "AWAIT_DATA"
            reason = (
                f"UNDERPOWERED/AWAIT_DATA: {why}. "
                f"power status {power['status']}: {power['reason']}. "
                f"Prereg floor {spec['dev_trades']} dev trades / "
                f"{spec['dev_days']} days, confirm {spec['confirm_trades']}."
            )
        doc = {
            "hypothesis": hyp,
            "provenance": "OBSERVED",
            "outcome": outcome,
            "status": status,
            "trades": [],
            "data_required": spec["channel"],
            "required_dev_trades": spec["dev_trades"],
            "required_dev_days": spec["dev_days"],
            "required_confirm_trades": spec["confirm_trades"],
            "power": power,
            "reason": reason,
            "pilot_source": roots.pilot_source,
            "pilot": str(roots.pilot),
            "benchmark_source": roots.benchmark_source,
            "benchmark_manifest_sha": bench.get("manifest_sha"),
            "inspection": {"pilot": pilot, "benchmark": {
                k: bench[k] for k in bench if k != "notes"},
                "benchmark_notes": bench.get("notes")},
        }
        (out_dir / f"{hyp}.json").write_text(
            json.dumps(doc, indent=1, sort_keys=True) + "\n")
        rows[hyp] = {"outcome": outcome, "status": status, "reason": reason}
    report = {
        "pilot_source": roots.pilot_source,
        "pilot": str(roots.pilot),
        "benchmark_source": roots.benchmark_source,
        "benchmark": str(roots.benchmark),
        "pilot_days": pilot.get("n_days"),
        "benchmark_channels": bench.get("channels"),
        "hypotheses": rows,
    }
    dest = repo / "research" / "autopilot" / "reports" / "family-a-z2.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    return report


def main() -> int:
    report = evaluate(ROOT)
    print(json.dumps({
        "pilot": report["pilot"],
        "pilot_source": report["pilot_source"],
        "pilot_days": report["pilot_days"],
        "benchmark_channels": report["benchmark_channels"],
        "states": {k: v["status"] for k, v in report["hypotheses"].items()},
    }, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
