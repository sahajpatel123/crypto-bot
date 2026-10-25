"""Watch the forward studies and record the moment a verdict becomes deliverable.

``cryptobot verdict-watch --once`` runs the B4b forward command and the D1
evaluator, keeps each study's status and the exact reason text that tool
printed, hashes the code each one ran, and writes one record per change under
``reports/verdicts/<UTC stamp>.json``.

The watcher *reports*; it never evaluates strategy results itself. It has no
threshold, no verdict of its own, and no fallback that turns missing input into
a pass:

* ``WAITING`` - the study is still short of data (B4b INSUFFICIENT FORWARD
  DATA, D1 INSUFFICIENT_FORWARD_DATA / UNDERPOWERED). This is the normal state.
* ``DECIDED`` - the tool produced a frozen verdict. The verdict text is copied
  from the tool, never synthesised here.
* ``ERROR``  - the tool could not run or printed nothing recognisable. That is
  exit 3: the watch itself is broken, not the study.

Exit codes: 0 every study still waiting (or waiting with no change), 10 any
study's status differs from the previous record (a verdict has become
deliverable), 3 the watch could not run. A rerun with no change writes no new
record, so the history stays one row per transition.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "cryptobot-verdict-watch/1"
WAITING = "WAITING"
DECIDED = "DECIDED"
ERROR = "ERROR"

EXIT_OK = 0
EXIT_CHANGED = 10
EXIT_CANNOT_RUN = 3

#: Verdicts that mean "no answer yet"; every other verdict is a decision.
WAITING_VERDICTS = frozenset({"INSUFFICIENT_FORWARD_DATA", "UNDERPOWERED"})
DEFAULT_OUT_DIR = "reports/verdicts"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def _one_line(text: str, limit: int = 200) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


@dataclass(frozen=True)
class StudyResult:
    study: str
    status: str
    verdict: str | None
    reason: str
    code_sha256: dict[str, str] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)


def _load_b4b(repo_root: Path) -> Any:
    path = repo_root / "tools" / "forward_b4b.py"
    if not path.is_file():
        raise FileNotFoundError(f"B4b tool not found at {path}")
    spec = importlib.util.spec_from_file_location("verdict_watch_b4b", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def b4b_study(*, root: Path, repo_root: Path) -> StudyResult:
    """Run the frozen B4b forward command and classify what it printed."""
    module = _load_b4b(repo_root)
    tool_path = repo_root / "tools" / "forward_b4b.py"
    code = {str(tool_path): _sha256(tool_path)}
    doc = module.forward_command(Path(root))
    if not isinstance(doc, dict) or "state" not in doc:
        raise ValueError("B4b printed no document with a state")
    state = doc["state"]
    if state == "VERDICT":
        verdict = doc.get("verdict")
        if not isinstance(verdict, dict) or "status" not in verdict:
            raise ValueError("B4b VERDICT has no status")
        reason = str(verdict.get("status") or "")
        if verdict.get("status_reason"):
            reason += f": {verdict['status_reason']}"
        detail = {
            "failed_gates": verdict.get("failed_gates"),
            "unassessable_gates": verdict.get("unassessable_gates"),
            "prereg": verdict.get("prereg"),
        }
        return StudyResult("B4b", DECIDED, str(verdict["status"]), reason,
                           code, detail)
    if state == "INSUFFICIENT FORWARD DATA":
        reason = (
            f"{doc.get('forward_days')} of {doc.get('forward_days_required')} "
            f"forward days, {doc.get('round_trips')} of "
            f"{doc.get('round_trips_required')} round trips; earliest "
            f"evaluable {doc.get('earliest_evaluable_on')}")
        detail = {key: doc.get(key) for key in (
            "forward_days", "forward_days_required", "round_trips",
            "round_trips_required", "earliest_evaluable_on",
            "pass_possible_on")}
        return StudyResult("B4b", WAITING, None, reason, code, detail)
    raise ValueError(f"B4b printed an unrecognised state {state!r}")


def d1_study(*, recorder_root: Path, repo_root: Path) -> StudyResult:
    """Run the D1 forward evaluator and classify what it printed."""
    from cryptobot.research import d1_eval

    doc = d1_eval.evaluate_forward(Path(recorder_root), repo_root=repo_root)
    if not isinstance(doc, dict) or "verdict" not in doc:
        raise ValueError("D1 printed no document with a verdict")
    verdict = str(doc["verdict"])
    status = WAITING if verdict in WAITING_VERDICTS else DECIDED
    reason = d1_eval.render(doc)
    prereg = doc.get("prereg") if isinstance(doc.get("prereg"), dict) else {}
    emitted = prereg.get("code_sha256")
    code = dict(emitted) if isinstance(emitted, dict) else {}
    detail = {
        "shortfall_stage": doc.get("shortfall_stage"),
        "stream_shortfalls": doc.get("stream_shortfalls"),
        "trial_count": doc.get("trial_count"),
        "window_days": doc.get("window_days"),
        "source": "cryptobot.research.d1_eval",
    }
    return StudyResult("D1", status, verdict, reason, code, detail)


def default_studies(*, repo_root: Path, b4b_root: Path,
                    recorder_root: Path) -> list[Callable[[], StudyResult]]:
    return [
        lambda: b4b_study(root=b4b_root, repo_root=repo_root),
        lambda: d1_study(recorder_root=recorder_root, repo_root=repo_root),
    ]


def _previous_record(out_dir: Path) -> tuple[Path, dict[str, Any]] | None:
    if not out_dir.is_dir():
        return None
    for path in sorted(out_dir.glob("*.json"), reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("studies"), dict):
            return path, doc
    return None


def _guard(result: Callable[[], StudyResult], name: str) -> StudyResult:
    """Run one study; any failure is ERROR, never a fabricated status."""
    try:
        return result()
    except Exception as exc:  # noqa: BLE001 - a broken tool must not stop the watch
        return StudyResult(name, ERROR, None,
                           f"tool did not produce output: "
                           f"{type(exc).__name__}: {exc}")


def run_watch(*, out_dir: str | Path, repo_root: str | Path,
              studies: Sequence[Callable[[], StudyResult]] | None = None,
              names: Sequence[str] | None = None,
              now: datetime | None = None,
              b4b_root: str | Path | None = None,
              recorder_root: str | Path | None = None
              ) -> tuple[dict[str, Any], int, Path | None]:
    """Run every study, compare with the last record, maybe write a new one."""
    repo = Path(repo_root)
    directory = Path(out_dir)
    default = studies is None
    if default:
        studies = default_studies(
            repo_root=repo,
            b4b_root=Path(b4b_root) if b4b_root is not None
            else repo / "data" / "forward_b4b",
            recorder_root=Path(recorder_root) if recorder_root is not None
            else repo / "data" / "recorder")
    if names is not None:
        labels = list(names)
    elif default:
        labels = ["B4b", "D1"][:len(studies)]
    else:
        labels = [f"study-{index + 1}" for index in range(len(studies))]

    results = [_guard(study, label)
               for study, label in zip(studies, labels, strict=False)]
    previous = _previous_record(directory)
    before: dict[str, Any] = {}
    if previous is not None:
        before = previous[1].get("studies") or {}

    changed: list[str] = []
    for result in results:
        old = before.get(result.study)
        if not isinstance(old, dict):
            continue
        was = str(old.get("status") or "")
        if ERROR in (was, result.status):
            continue
        if was != result.status:
            changed.append(result.study)

    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    doc: dict[str, Any] = {
        "format": SCHEMA_VERSION,
        "generated_utc": stamp.isoformat(),
        "commit": _commit(repo),
        "gate": "NO-GO",
        "previous": str(previous[0]) if previous is not None else None,
        "changed": changed,
        "studies": {
            result.study: {
                "status": result.status,
                "verdict": result.verdict,
                "reason": result.reason,
                "code_sha256": result.code_sha256,
                "detail": result.detail,
            }
            for result in results
        },
    }

    errored = any(result.status == ERROR for result in results)
    written: Path | None = None
    # One record per transition: an unchanged rerun adds nothing and rewrites
    # nothing. A failed run is recorded, because its stderr is the evidence.
    if changed or previous is None or errored:
        directory.mkdir(parents=True, exist_ok=True)
        base = stamp.strftime("%Y%m%dT%H%M%SZ")
        candidate = directory / f"{base}.json"
        suffix = 1
        while candidate.exists():
            candidate = directory / f"{base}-{suffix}.json"
            suffix += 1
        candidate.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
        written = candidate

    if errored:
        return doc, EXIT_CANNOT_RUN, written
    if changed:
        return doc, EXIT_CHANGED, written
    return doc, EXIT_OK, written


def cmd_verdict_watch(args: argparse.Namespace) -> int:
    """``cryptobot verdict-watch --once`` (cron friendly, one line per study)."""
    if not getattr(args, "once", False):
        print("verdict-watch: only --once is supported (idiomatic for cron)",
              file=sys.stderr)
        return 2
    repo = Path(args.repo_root) if args.repo_root else Path.cwd()
    doc, code, written = run_watch(
        out_dir=args.out_dir, repo_root=repo,
        b4b_root=args.b4b_root, recorder_root=args.recorder_root)
    for name, row in doc["studies"].items():
        label = row.get("verdict") or "waiting for data"
        print(f"{name}: {row['status']} - {label} - "
              f"{_one_line(str(row.get('reason') or ''))}")
    if written is not None:
        print(f"verdict-watch: recorded {written}")
    else:
        print("verdict-watch: unchanged; no new record")
    return int(code)


__all__ = [
    "DECIDED",
    "ERROR",
    "EXIT_CANNOT_RUN",
    "EXIT_CHANGED",
    "EXIT_OK",
    "SCHEMA_VERSION",
    "StudyResult",
    "WAITING",
    "b4b_study",
    "cmd_verdict_watch",
    "d1_study",
    "default_studies",
    "run_watch",
]
