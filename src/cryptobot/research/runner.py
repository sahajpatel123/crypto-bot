"""Resumable EXP-001..004 descriptive runner (Worker 1, Q-003 Phase 2, Q-004).

Command: ``python -m cryptobot.research.runner --exp EXP-001 --out <dir>``.

Derives the trial manifest from each experiment's FROZEN arms, scenarios,
seeds and split definition; executes every trial; persists successes AND
failures with fixture hashes, config, versions, seeds and split boundaries;
reconciles planned-vs-completed. Re-running with the same ``--out`` resumes
(completed trial ids are skipped). Zero signals is a valid executed result;
an empty log is not an execution.

Synthetic signal mechanics only. Promotion stays NONE; nothing here can
promote a strategy or establish profitability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime

from cryptobot.costs import COST_S1, roundtrip_bps
from cryptobot.strategies.contract import (
    ARM_IDS_S1,
    ARM_IDS_S2,
    ARM_IDS_S3,
    ARM_IDS_S4,
    STRATEGY_VERSION,
)
from cryptobot.strategies.s1 import evaluate_bar as evaluate_s1
from cryptobot.strategies.s2 import evaluate_bar as evaluate_s2
from cryptobot.strategies.s3 import evaluate_bar as evaluate_s3
from cryptobot.strategies.s4 import evaluate_bar as evaluate_s4

from .experiments import (
    EXP_001,
    EXP_002,
    EXP_003,
    EXP_004,
    REGISTRY_VERSION,
    TrialLog,
    TrialRecord,
    split_indices,
)
from .synthetic import generate_fixture

EXPERIMENTS = {"EXP-001": EXP_001, "EXP-002": EXP_002, "EXP-003": EXP_003, "EXP-004": EXP_004}
EVALUATORS = {}
for _arm in ARM_IDS_S1:
    EVALUATORS[_arm] = evaluate_s1
for _arm in ARM_IDS_S2:
    EVALUATORS[_arm] = evaluate_s2
for _arm in ARM_IDS_S3:
    EVALUATORS[_arm] = evaluate_s3
for _arm in ARM_IDS_S4:
    EVALUATORS[_arm] = evaluate_s4

WARMUP_BARS = 120
ROUNDTRIP_BPS_PER_SIGNAL = roundtrip_bps(COST_S1)  # cost-contract-v1, cost exposure only

__all__ = [
    "EXPERIMENTS",
    "build_manifest",
    "execute_trial",
    "load_completed",
    "main",
    "reconcile",
    "run_manifest",
]


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=10, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _fixture_hash(fixture) -> str:
    canonical = json.dumps(fixture.to_dict(), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_manifest(exp_id: str) -> dict:
    """Planned trial list derived from the frozen experiment definition."""
    if exp_id not in EXPERIMENTS:
        raise ValueError(f"unknown experiment {exp_id!r}")
    exp = EXPERIMENTS[exp_id]
    trials = []
    for arm in exp["arms"]:
        for scenario in exp["scenarios"]:
            for split, seeds in (("train", exp["train_seeds"]),
                                 ("validation", exp["validation_seeds"])):
                for seed in seeds:
                    fixture = generate_fixture(seed=seed, scenario=scenario)
                    n = len(fixture.bars)
                    part = split_indices(n)
                    lo, hi = (0, part.train_end) if split == "train" else (part.val_start, n)
                    trials.append({
                        "trial_id": f"{exp_id}:{arm}:{scenario}:{seed}:{split}",
                        "exp_id": exp_id,
                        "arm": arm,
                        "scenario": scenario,
                        "seed": seed,
                        "split": split,
                        "split_range": [lo, hi],
                        "n_bars": n,
                        "fixture_hash": _fixture_hash(fixture),
                    })
    return {
        "exp_id": exp_id,
        "created_utc": _utcnow(),
        "code": {
            "registry_version": REGISTRY_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "git_sha": _git_sha(),
        },
        "split_def": exp["split"],
        "promotion_rule": exp["promotion_rule"],
        "planned": len(trials),
        "trials": trials,
    }


def execute_trial(trial: dict) -> TrialRecord:
    """Run one trial; returns an ok record (zero signals valid)."""
    fixture = generate_fixture(seed=trial["seed"], scenario=trial["scenario"])
    bars = list(fixture.bars)
    lo, hi = trial["split_range"]
    evaluate = EVALUATORS[trial["arm"]]
    n_long = n_short = 0
    rejects: dict[str, int] = {}
    evaluated = 0
    for t in range(max(lo, WARMUP_BARS), hi):
        long_d, short_d = evaluate(bars, t, trial["arm"], fixture.instrument)
        evaluated += 2
        for decision, key in ((long_d, "long"), (short_d, "short")):
            if decision.intent is not None:
                if key == "long":
                    n_long += 1
                else:
                    n_short += 1
            else:
                reason = decision.evaluation.reason
                rejects[reason] = rejects.get(reason, 0) + 1
    cost_exposure = (n_long + n_short) * ROUNDTRIP_BPS_PER_SIGNAL
    metrics = (
        ("n_signals_long", str(n_long)),
        ("n_signals_short", str(n_short)),
        ("evaluations", str(evaluated)),
        ("est_roundtrip_cost_bps_total", f"{cost_exposure:.1f}"),
        ("fixture_hash", _fixture_hash(fixture)),
        ("split_range", f"{lo}:{hi}"),
    ) + tuple(sorted((f"reject:{k}", str(v)) for k, v in rejects.items()))
    return TrialRecord(
        trial_id=trial["trial_id"], exp_id=trial["exp_id"], arm=trial["arm"],
        seed=trial["seed"], split=trial["split"], status="ok",
        reason="executed", utc=TrialRecord.utcnow(), metrics=metrics,
    )


def load_completed(log_path) -> TrialLog:
    """Load persisted trials; skips a corrupt trailing line (crash resume)."""
    from pathlib import Path

    log = TrialLog()
    path = Path(log_path)
    if not path.exists():
        return log
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            log.log_trial(TrialRecord(
                trial_id=d["trial_id"], exp_id=d["exp_id"], arm=d["arm"],
                seed=d["seed"], split=d["split"], status=d["status"],
                reason=d["reason"], utc=d["utc"],
                metrics=tuple((k, v) for k, v in d.get("metrics", [])),
            ))
        except (KeyError, ValueError):
            continue
    return log


def run_manifest(manifest: dict, out_dir, limit: int | None = None) -> TrialLog:
    """Execute planned trials (resuming past completed ids); returns the log."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log_path = out / "trials.jsonl"
    log = load_completed(log_path)
    done = {t.trial_id for t in log.trials}
    planned = manifest["trials"][:limit] if limit else manifest["trials"]
    with log_path.open("a", encoding="utf-8") as fh:
        for trial in planned:
            if trial["trial_id"] in done:
                continue
            try:
                record = execute_trial(trial)
            except Exception as exc:  # noqa: BLE001 - failures are data
                record = TrialRecord(
                    trial_id=trial["trial_id"], exp_id=trial["exp_id"],
                    arm=trial["arm"], seed=trial["seed"], split=trial["split"],
                    status="failed",
                    reason=f"{type(exc).__name__}:{str(exc)[:200]}",
                    utc=TrialRecord.utcnow(),
                )
            log.log_trial(record)
            fh.write(json.dumps(record.to_dict()) + "\n")
            fh.flush()
    return log


def reconcile(manifest: dict, log: TrialLog) -> dict:
    """Planned-vs-completed counts; missing ids listed for resume."""
    planned = [t["trial_id"] for t in manifest["trials"]]
    completed = {t.trial_id for t in log.trials}
    missing = [tid for tid in planned if tid not in completed]
    failed = [t.trial_id for t in log.trials if t.status == "failed"]
    return {
        "planned": len(planned),
        "completed": len(completed),
        "ok": len(completed) - len(failed),
        "failed": len(failed),
        "failed_ids": failed,
        "missing": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resumable EXP-001/EXP-002 runner")
    parser.add_argument("--exp", default="all",
                        choices=["all", "EXP-001", "EXP-002", "EXP-003", "EXP-004"])
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--limit", type=int, default=None,
                        help="smoke: run only the first N trials per experiment")
    parser.add_argument("--dry-run", action="store_true",
                        help="write manifests only, execute nothing")
    args = parser.parse_args(argv)
    from pathlib import Path

    out = Path(args.out)
    exp_ids = ["EXP-001", "EXP-002", "EXP-003", "EXP-004"] if args.exp == "all" else [args.exp]
    overall = {"planned": 0, "completed": 0, "failed": 0}
    for exp_id in exp_ids:
        manifest = build_manifest(exp_id)
        exp_out = out / exp_id
        if args.dry_run:
            exp_out.mkdir(parents=True, exist_ok=True)
            (exp_out / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"{exp_id}: planned={manifest['planned']} (dry run)")
            overall["planned"] += manifest["planned"]
            continue
        log = run_manifest(manifest, exp_out, limit=args.limit)
        rec = reconcile(manifest if args.limit is None else
                        {**manifest, "trials": manifest["trials"][:args.limit]}, log)
        print(f"{exp_id}: planned={rec['planned']} completed={rec['completed']} "
              f"ok={rec['ok']} failed={rec['failed']}")
        overall["planned"] += rec["planned"]
        overall["completed"] += rec["completed"]
        overall["failed"] += rec["failed"]
    print(f"TOTAL: planned={overall['planned']} completed={overall['completed']} "
          f"failed={overall['failed']}")
    if args.dry_run:
        return 0
    return 0 if overall["completed"] == overall["planned"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
