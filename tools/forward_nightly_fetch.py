#!/usr/bin/env python3
"""Nightly forward-data catch-up for the frozen forward studies.

Calls each study's ``fetch`` in turn -- B4b (``tools/forward_b4b.py``),
F-CARRY (``tools/forward_fcarry.py``) and V-REG (``tools/forward_vreg.py``,
only when the file is present) -- then sorts each outcome into one of:

* ``OK`` -- fetch completed; every published-window file is on disk.
* ``FUNDING-PENDING`` -- the only thing missing is a funding month that is
  still inside its post-month-end publish lag (expected; exits 0).
* ``GAP`` -- a kline day inside the window, or a funding month past its
  publish lag, is missing (exits 1).
* ``CHECKSUM-REFUSAL`` -- a study's fetch rejected a file against its
  published .CHECKSUM (exits 2).

Anything else a study raises is reported as ``ERROR`` (exits 3). A missing
V-REG file is reported as ``ABSENT`` and skipped (exits 0), so this wrapper
works unchanged before and after the V-REG file lands: one failing
study never stops the remaining ones, and the exit code always reflects
the worst outcome.

Usage
-----
    python tools/forward_nightly_fetch.py [--date YYYY-MM-DD] [--out PATH]
        [--root-b4b DIR] [--root-fcarry DIR] [--root-vreg DIR]

Before the forward clock starts (2026-11-01) this is a no-op that prints
``nothing to fetch yet`` and exits 0 without touching any study.

What this wrapper never does (pinned by test, deletion-proved):

* it only ever calls each study module's ``fetch`` (plus the pure planning
  helpers ``file_window``/``wanted_prefixes`` and the frozen constants);
  the one-shot decision entry points stay untouched;
* it never widens the file window: every byte on disk arrives through the
  study's own ``fetch``, which applies the frozen ``is_forward_file`` rule
  (daily strictly after 2026-10-17, monthly strictly after 2026-10);
* it never writes the tracked manifest copies: per-study manifests stay in
  their data roots, and only the combined summary below is written;
* it decodes no data file and prints no performance figure of any kind --
  per-study output is file counts, a classification, and digests.

The combined summary (JSON) records the UTC date, the per-study
classifications with missing/pending items, and the sha256 of every study
manifest written, e.g. ``data/forward_nightly/summary-2026-11-02.json``.
Scheduled shape (an OpenBot routine owns the schedule; this tool only
fetches)::

    uv run --locked python tools/forward_nightly_fetch.py \
        --out data/forward_nightly/summary-$(date -u +%F).json
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[1]

CLOCK_START = dt.date(2026, 11, 1)  # frozen forward clock, shared by studies
FUNDING_PUBLISH_GRACE_DAYS = 7  # a just-completed month's funding file is
# "pending" (not a gap) until this many days after month-end

EXIT_OK = 0
EXIT_GAP = 1
EXIT_REFUSAL = 2
EXIT_ERROR = 3

_OVERALL_EXIT = {"OK": EXIT_OK, "FUNDING-PENDING": EXIT_OK, "GAP": EXIT_GAP,
                 "CHECKSUM-REFUSAL": EXIT_REFUSAL, "ERROR": EXIT_ERROR}

STUDIES = (
    {"id": "b4b", "file": "forward_b4b.py", "required": True},
    {"id": "fcarry", "file": "forward_fcarry.py", "required": True},
    {"id": "vreg", "file": "forward_vreg.py", "required": False},
)


def _load_module(tool_dir: Path, filename: str):
    """Import a study file by path; None when the file is absent."""
    path = tool_dir / filename
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load study file: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module  # dataclasses need it registered
    spec.loader.exec_module(module)
    return module


def _next_month(stamp: str) -> str:
    year, month = int(stamp[:4]), int(stamp[5:7])
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def _prev_month(stamp: str) -> str:
    year, month = int(stamp[:4]), int(stamp[5:7])
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def _planned_datasets(module) -> dict[str, str]:
    """dataset name -> "day" | "month", from the study's own prefixes."""
    kinds: dict[str, str] = {}
    for symbol in module.UNIVERSE:
        for dataset, prefixes in module.wanted_prefixes(symbol).items():
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            for prefix in prefixes:
                if "/daily/" in prefix:
                    kinds.setdefault(dataset, "day")
                elif "/monthly/" in prefix:
                    kinds.setdefault(dataset, "month")
    return kinds


def _expected(module, today: dt.date) -> tuple[set, set, set]:
    """Expected (kline days, funding months, pending months).

    Each item is a (symbol, dataset, stamp) triple. Kline days run from the
    frozen clock start through yesterday (today's file is never published
    yet). Funding months run strictly after the frozen cutoff month and
    strictly before the current month; the just-completed month stays
    "pending" through the publish grace window instead of paging as a gap.
    The current month is untracked: its file cannot exist before month-end.
    """
    kinds = _planned_datasets(module)
    kline_ds = sorted(d for d, k in kinds.items() if k == "day")
    fund_ds = sorted(d for d, k in kinds.items() if k == "month")
    exp_days: set = set()
    exp_months: set = set()
    pending: set = set()
    day = CLOCK_START
    yesterday = today - dt.timedelta(days=1)
    while day <= yesterday:
        stamp = day.isoformat()
        for symbol in module.UNIVERSE:
            for dataset in kline_ds:
                exp_days.add((symbol, dataset, stamp))
        day += dt.timedelta(days=1)
    current = today.strftime("%Y-%m")
    mstamp = _next_month(str(module.CUTOFF_MONTH))
    while mstamp < current:
        last_done = mstamp == _prev_month(current)
        grace = today.day <= FUNDING_PUBLISH_GRACE_DAYS
        bucket = pending if (last_done and grace) else exp_months
        for symbol in module.UNIVERSE:
            for dataset in fund_ds:
                bucket.add((symbol, dataset, mstamp))
        mstamp = _next_month(mstamp)
    return exp_days, exp_months, pending


def _present(module, files: list) -> set:
    """(symbol, dataset, stamp) triples found in a study manifest."""
    have: set = set()
    for rec in files:
        try:
            _kind, stamp = module.file_window(rec["name"])
        except (ValueError, KeyError):
            continue
        have.add((rec.get("symbol"), rec.get("dataset"), stamp))
    return have


def _fmt_triples(items: list) -> list:
    return [f"{s}/{d}/{t}" for s, d, t in items]


def _classify(module, files: list, today: dt.date) -> tuple[str, list, list]:
    exp_days, exp_months, pending = _expected(module, today)
    have = _present(module, files)
    missing = sorted((exp_days | exp_months) - have)
    still_pending = sorted(m for m in pending if m not in have)
    if missing:
        return "GAP", _fmt_triples(missing), _fmt_triples(still_pending)
    if still_pending:
        return "FUNDING-PENDING", [], _fmt_triples(still_pending)
    return "OK", [], []


def _blank(spec: dict, root: Path | None) -> dict:
    return {"study": spec["id"], "file": spec["file"],
            "root": None if root is None else str(root),
            "present": False, "status": "ERROR",
            "fetched": 0, "resumed": 0, "refused": 0, "files": 0,
            "manifest_sha256": None, "missing": [], "pending": [],
            "error": None}


def _fetch_study(spec: dict, *, root: Path | None, today: dt.date,
                 make_client, tool_dir: Path) -> dict:
    """Fetch one study via its own ``fetch``; classify; never raise."""
    rec = _blank(spec, root)
    try:
        module = _load_module(tool_dir, spec["file"])
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        rec["error"] = f"load failed: {type(exc).__name__}: {exc}"[:300]
        return rec
    if module is None:
        if spec["required"]:
            rec["error"] = f"required study file missing: {spec['file']}"
            return rec
        rec["status"] = "ABSENT"
        return rec
    rec["present"] = True
    if str(module.FORWARD_CLOCK_START) != CLOCK_START.isoformat():
        rec["error"] = ("clock drift: study clock "
                        f"{module.FORWARD_CLOCK_START} != {CLOCK_START}")
        return rec
    if root is None:
        root = Path(module.DEFAULT_ROOT)
    rec["root"] = str(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        manifest = module.fetch(root, make_client(spec["id"], module))
    except Exception as exc:  # noqa: BLE001 - classified below
        text = f"{type(exc).__name__}: {exc}"
        if "checksum" in text.lower():
            rec["status"] = "CHECKSUM-REFUSAL"
            rec["refused"] = 1
        rec["error"] = text[:300]
        return rec
    files = manifest.get("files", [])
    rec["fetched"] = sum(1 for f in files if not f.get("resumed", False))
    rec["resumed"] = sum(1 for f in files if f.get("resumed", False))
    rec["files"] = len(files)
    rec["status"], rec["missing"], rec["pending"] = _classify(
        module, files, today)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        rec["manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()).hexdigest()
    return rec


def _overall(per_study: list) -> str:
    statuses = {p["status"] for p in per_study}
    for status in ("ERROR", "CHECKSUM-REFUSAL", "GAP", "FUNDING-PENDING"):
        if status in statuses:
            return status
    return "OK"


def fetch_all(*, today: dt.date, roots: dict[str, Path | None],
              summary_path: Path, make_client,
              tool_dir: Path = TOOL_DIR) -> dict:
    """Fetch every study in turn; write the combined summary; no raise.

    ``roots`` maps study id -> data root (None = the study's own default).
    ``make_client(study_id, module)`` builds the Vision client (the real
    one in production, a fake in tests). Precondition: ``today`` is on or
    after the clock start -- :func:`main` enforces the no-op gate.
    """
    per_study = [_fetch_study(spec, root=roots.get(spec["id"]), today=today,
                              make_client=make_client, tool_dir=tool_dir)
                 for spec in STUDIES]
    overall = _overall(per_study)
    summary = {
        "format": "cryptobot-forward-nightly-summary/1",
        "date": today.isoformat(),
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "overall": overall,
        "exit_code": _OVERALL_EXIT[overall],
        "wrapper_sha256": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "clock_start": CLOCK_START.isoformat(),
        "funding_publish_grace_days": FUNDING_PUBLISH_GRACE_DAYS,
        "studies": per_study,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def _default_client(study_id: str, module):
    return module.VisionClient()


def _short(items: list, limit: int = 8) -> str:
    if len(items) <= limit:
        return ",".join(items)
    return ",".join(items[:limit]) + f",+{len(items) - limit} more"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from cryptobot import netguard  # opt-in DNS-sinkhole fallback
        netguard.install_from_env()
    except ImportError:
        pass  # fetch works without it; studies retry on their own
    ap = argparse.ArgumentParser(
        prog="forward_nightly_fetch",
        description="Nightly forward-data catch-up: fetch only, then sort "
                    "each study into OK / FUNDING-PENDING / GAP / "
                    "CHECKSUM-REFUSAL and write one combined summary.")
    ap.add_argument("--date", default=None,
                    help="UTC date YYYY-MM-DD (default: today)")
    ap.add_argument("--out", default=None,
                    help="combined summary path (default "
                         "data/forward_nightly/summary-<date>.json)")
    ap.add_argument("--root-b4b", default=None)
    ap.add_argument("--root-fcarry", default=None)
    ap.add_argument("--root-vreg", default=None)
    args = ap.parse_args(argv)
    today = (dt.date.fromisoformat(args.date) if args.date
             else dt.datetime.now(dt.UTC).date())
    if today < CLOCK_START:
        print("nothing to fetch yet")
        return EXIT_OK
    summary_path = (Path(args.out) if args.out else
                    ROOT / "data/forward_nightly"
                    / f"summary-{today.isoformat()}.json")
    roots = {"b4b": Path(args.root_b4b) if args.root_b4b else None,
             "fcarry": Path(args.root_fcarry) if args.root_fcarry else None,
             "vreg": Path(args.root_vreg) if args.root_vreg else None}
    summary = fetch_all(today=today, roots=roots,
                        summary_path=summary_path,
                        make_client=_default_client, tool_dir=TOOL_DIR)
    for p in summary["studies"]:
        if p["status"] == "ABSENT":
            print(f"{p['study']}: status=ABSENT "
                  f"({p['file']} not present; skipped)")
            continue
        digest = (p["manifest_sha256"] or "none")[:16]
        line = (f"{p['study']}: status={p['status']} "
                f"fetched={p['fetched']} resumed={p['resumed']} "
                f"refused={p['refused']} files={p['files']} "
                f"manifest={digest}")
        if p["missing"]:
            line += f" missing={_short(p['missing'])}"
        if p["pending"]:
            line += f" pending={_short(p['pending'])}"
        if p["error"]:
            line += f" error={p['error']}"
        print(line)
    print(f"overall={summary['overall']} exit={summary['exit_code']} "
          f"summary={summary_path}")
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
