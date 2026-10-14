"""Data-suitability table for research (REL-W3-DATA §5).

Coarse per-capture screen emitted BEFORE any new research round. Reads
each capture's manifest.json (provenance/period) + run_stats.json
(channels/gaps/disorder) WITHOUT re-streaming event files, derives
prior-use by grepping the repo for the run id, and prints one Markdown
table row per capture plus a JSON sidecar.

STATED LIMITS (coarse screen only):
- This table NEVER certifies live readiness and NEVER replaces
  tools/audit_dataset.py, whose SCORABLE verdict is required before
  scoring any capture.
- Funding rates were not captured (no funding channel exists); any
  research assuming measured funding costs is unsuitable on all rows.
- Prior-use is a repo grep: absence means "not referenced", not
  "never used elsewhere".
- Integrity flag covers capture mechanics only (files present,
  exec channels per symbol, malformed/order/gaps). Semantic fitness
  (regime coverage, event overlap) is a separate research decision.

Exit 0 when every capture is internally complete; exit 3 listing the
deficient captures otherwise (fail loudly, still prints the table).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except FileNotFoundError:
        return None, f"missing {path.name}"
    except (OSError, ValueError) as exc:
        return None, f"unreadable {path.name}: {exc}"


def _prior_use(run_id: str) -> str:
    try:
        proc = subprocess.run(
            ["grep", "-rl", "--include=*.json", "--include=*.toml",
             "--include=*.md", "--include=*.py", "--exclude-dir=.git",
             "--exclude-dir=__pycache__", "--exclude-dir=captures",
             "--exclude-dir=node_modules", run_id, "."],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return "unknown (grep unavailable)"
    if proc.returncode not in (0, 1):
        return f"unknown (grep exit {proc.returncode})"
    hits = sorted(p for p in proc.stdout.splitlines() if p)
    if not hits:
        return "none found"
    shown = ", ".join(h.removeprefix("./") for h in hits[:6])
    return shown + (f" (+{len(hits) - 6} more)" if len(hits) > 6 else "")


def _ist_day(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return "?"
    if moment.tzinfo is None:
        return "?"
    return moment.astimezone(IST).date().isoformat()


def assess_capture(path: Path) -> dict:
    """One suitability row for a capture directory (pure data)."""
    row: dict = {"capture": path.name, "reasons": []}
    manifest, err = _load_json(path / "manifest.json")
    if manifest is None:
        row["reasons"].append(f"MISSING-FILE:{err}")
    stats, err = _load_json(path / "run_stats.json")
    if stats is None:
        row["reasons"].append(f"MISSING-FILE:{err}")
    if manifest is None or stats is None:
        row["flag"] = "UNUSABLE"
        row["prior_use"] = _prior_use(path.name)
        return row

    symbols = list(manifest.get("symbols", []))
    row["symbols"] = ",".join(symbols) if symbols else "?"
    row["period_utc"] = (f"{manifest.get('started_utc', '?')}.."
                         f"{manifest.get('ended_utc', '?')}")
    row["ist_day"] = _ist_day(str(manifest.get("started_utc", "")))
    rule = str(manifest.get("capture_set_rule", ""))
    row["provenance"] = (f"{manifest.get('input_class', '?')}"
                         + (f"; {rule[:60]}…" if len(rule) > 60 else
                            (f"; {rule}" if rule else "")))
    row["events_total"] = stats.get("events_total", "?")

    per_channel = stats.get("per_channel", {})
    have = {(c.split("/", 2)[1], c.split("/", 2)[2])
            for c in per_channel if c.count("/") == 2}
    for sym in symbols:
        if ("aggTrade", sym) not in have:
            row["reasons"].append(f"NO-TRADES:{sym}")
        if ("bookTicker", sym) not in have:
            row["reasons"].append(f"NO-BOOK:{sym}")
    row["trades"] = sum(n for c, n in per_channel.items()
                        if "/aggTrade/" in c)
    row["book"] = sum(n for c, n in per_channel.items()
                      if "/bookTicker/" in c)
    row["mark"] = sum(n for c, n in per_channel.items()
                      if "/markPrice/" in c)
    row["depth"] = (f"{stats.get('depth_applied', '?')} applied/"
                    f"{stats.get('depth_resyncs', '?')} resyncs")
    funding = [c for c in per_channel if "fund" in c.lower()]
    row["funding"] = "absent" if not funding else ",".join(funding)
    gaps = stats.get("gaps", {})
    row["gaps"] = (f"natural={gaps.get('natural', '?')} "
                   f"injected={gaps.get('injected', '?')}")
    row["disorder"] = (f"ooo={stats.get('out_of_order', '?')} "
                       f"dup={stats.get('duplicates', '?')} "
                       f"malformed={stats.get('malformed', '?')}")
    for key, label in (("malformed", "MALFORMED"),
                       ("out_of_order", "OUT-OF-ORDER"),
                       ("duplicates", "DUPLICATES")):
        value = stats.get(key, 0)
        if isinstance(value, int) and value > 0:
            row["reasons"].append(f"{label}={value}")
    for key, label in (("natural", "NATURAL-GAPS"),
                       ("injected", "INJECTED-GAPS")):
        value = gaps.get(key, 0)
        if isinstance(value, int) and value > 0:
            row["reasons"].append(f"{label}={value}")
    row["prior_use"] = _prior_use(path.name)
    row["flag"] = "OK" if not row["reasons"] else "NEEDS-AUDIT"
    return row


def to_markdown(rows: list[dict]) -> str:
    lines = ["# Data-suitability table (REL-W3-DATA §5, coarse screen)",
             "",
             ("| capture | symbols | period UTC | IST day | provenance | "
              "events | trades | book | mark | depth | funding | gaps | "
              "disorder | prior use | flag |"),
             ("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"),
             ]
    for row in rows:
        if row.get("flag") == "UNUSABLE":
            lines.append(f"| {row['capture']} | ? | ? | ? | ? | ? | ? | ? "
                         f"| ? | ? | ? | ? | ? | {row['prior_use']} | "
                         f"UNUSABLE ({'; '.join(row['reasons'])}) |")
            continue
        lines.append(
            f"| {row['capture']} | {row['symbols']} | {row['period_utc']} "
            f"| {row['ist_day']} | {row['provenance']} | {row['events_total']} "
            f"| {row['trades']} | {row['book']} | {row['mark']} "
            f"| {row['depth']} | {row['funding']} | {row['gaps']} "
            f"| {row['disorder']} | {row['prior_use']} | {row['flag']}"
            + (f" ({'; '.join(row['reasons'])})" if row["reasons"]
               else "") + " |")
    lines += ["",
              "Limits: coarse screen only; not a live-readiness claim; "
              "tools/audit_dataset.py SCORABLE verdict still required "
              "before scoring; funding absent on all rows."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="?",
                        default=str(ROOT / "data" / "captures"),
                        help="captures root (default: data/captures)")
    parser.add_argument("--out", default="-",
                        help="Markdown output path (default: stdout)")
    parser.add_argument("--json-out", default="",
                        help="optional JSON sidecar path")
    args = parser.parse_args(argv)
    root = Path(args.captures)
    if not root.is_dir():
        print(f"suitability_table: captures root missing: {root}",
              file=sys.stderr)
        return 3
    rows = [assess_capture(p) for p in sorted(root.iterdir())
            if p.is_dir()]
    if not rows:
        print("suitability_table: no capture directories found",
              file=sys.stderr)
        return 3
    text = to_markdown(rows)
    if args.out == "-":
        print(text, end="")
    else:
        Path(args.out).write_text(text, encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=1) + "\n",
                                       encoding="utf-8")
    bad = [r["capture"] for r in rows if r["flag"] != "OK"]
    if bad:
        print(f"suitability_table: NEEDS-AUDIT/UNUSABLE: "
              f"{', '.join(bad)}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
