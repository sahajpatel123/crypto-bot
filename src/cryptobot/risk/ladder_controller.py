"""F5.3: persisted capital-ladder controller (automatic demotion, gated promotion).

The controller consumes per-trade attribution and supervision facts and
persists the demoted state. Demotion stays automatic and unchanged.

Promotion is **evidence gated**: :meth:`LadderController.promote` accepts a
promotion only when it cites a JSON evidence document whose live statistics
were derived from the journals by ``cryptobot.ops.daily_pnl`` (the document
carries that generator's own source hash, and every source file it cites is
re-hashed here). A promotion records the rung history, the evidence document's
sha256, the git commit and the UTC timestamp, refuses to skip a rung, and
refuses to spend the same evidence twice.

Every threshold lives in :mod:`cryptobot.risk.ladder` and is an operational
sizing rule, not a research gate (DECISIONS.md, "Operational ladder
promotion").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ladder import (
    EVIDENCE_GENERATOR_MODULE,
    PROMOTION_EVIDENCE_FORMAT,
    BacktestReference,
    LiveStatistics,
    Promotion,
    demotion_reasons,
    next_rung,
    promotion_decision,
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")


class LadderError(RuntimeError):
    """The promotion evidence or the requested transition is not admissible."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _generator_sha256() -> str | None:
    """SHA-256 of the installed evidence generator, or ``None`` if absent."""
    path = Path(__file__).resolve().parent.parent / "ops" / "daily_pnl.py"
    return sha256_file(path) if path.is_file() else None


def _number(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def _live_from_evidence(doc: dict[str, Any]) -> LiveStatistics:
    live = doc.get("live")
    if not isinstance(live, dict):
        raise LadderError("evidence has no 'live' statistics block")
    trips = live.get("round_trips")
    if isinstance(trips, bool) or not isinstance(trips, int):
        raise LadderError("evidence live.round_trips must be an integer")
    return LiveStatistics(
        round_trips=trips,
        days=_number(live.get("days")) or 0.0,
        sharpe=_number(live.get("sharpe")),
        cost_bps=_number(live.get("cost_bps")),
        max_drawdown_frac=_number(live.get("max_drawdown_frac")),
        halted=bool(live.get("halted", False)),
    )


def _backtest_from_evidence(doc: dict[str, Any]) -> BacktestReference:
    backtest = doc.get("backtest")
    if not isinstance(backtest, dict):
        raise LadderError("evidence has no 'backtest' reference block")
    return BacktestReference(
        sharpe=_number(backtest.get("sharpe")),
        cost_bps=_number(backtest.get("cost_bps")),
        max_drawdown_frac=_number(backtest.get("max_drawdown_frac")),
    )


def _resolve_source(raw: str, base: Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    candidate = (base / path).resolve()
    if candidate.is_file():
        return candidate
    return (Path.cwd() / path).resolve()


def _verify_evidence(doc: dict[str, Any], *, evidence_path: Path) -> list[str]:
    """Refuse evidence that was not derived from hashed journals.

    Returns the cited-but-missing paths so the caller can name them.
    """
    if doc.get("format") != PROMOTION_EVIDENCE_FORMAT:
        raise LadderError(
            f"evidence format {doc.get('format')!r} is not "
            f"{PROMOTION_EVIDENCE_FORMAT}")
    generated = doc.get("generated_by")
    if not isinstance(generated, dict):
        raise LadderError("evidence has no 'generated_by' block; a hand-typed "
                          "number is not evidence")
    if generated.get("module") != EVIDENCE_GENERATOR_MODULE:
        raise LadderError(
            f"evidence was not derived by {EVIDENCE_GENERATOR_MODULE} "
            f"(generated_by.module={generated.get('module')!r})")
    installed = _generator_sha256()
    if installed is None:
        raise LadderError(
            f"cannot re-hash {EVIDENCE_GENERATOR_MODULE}; refusing to trust "
            "unverifiable evidence")
    if generated.get("code_sha256") != installed:
        raise LadderError(
            "evidence was produced by a different build of "
            f"{EVIDENCE_GENERATOR_MODULE}; re-derive it from the journals")
    sources = doc.get("sources")
    if not isinstance(sources, list) or not sources:
        raise LadderError("evidence cites no source files")
    base = evidence_path.parent
    for item in sources:
        if not isinstance(item, dict):
            raise LadderError("evidence source entries must be objects")
        raw_path = item.get("path")
        expected = item.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            raise LadderError("evidence source entries need path and sha256")
        path = _resolve_source(raw_path, base)
        if not path.is_file():
            raise LadderError(f"evidence source {raw_path} is missing")
        actual = sha256_file(path)
        if actual != expected:
            raise LadderError(
                f"evidence source {raw_path} no longer matches its recorded "
                f"sha256 ({actual[:12]} != {expected[:12]})")
    return [str(item["path"]) for item in sources if isinstance(item, dict)]


class LadderController:
    def __init__(self, state_path: str | Path,
                 *, assumed_slippage_bps: float,
                 unknown_budget_s: float = 60.0,
                 expectancy_min_n: int = 30) -> None:
        self.path = Path(state_path)
        self.assumed_slippage_bps = float(assumed_slippage_bps)
        if not math.isfinite(self.assumed_slippage_bps) \
                or self.assumed_slippage_bps <= 0:
            raise ValueError("assumed_slippage_bps must be positive")
        self.unknown_budget_s = float(unknown_budget_s)
        self.expectancy_min_n = int(expectancy_min_n)
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            state: dict[str, Any] = json.loads(
                self.path.read_text(encoding="utf-8"))
            # State written before promotion existed carries only ``demoted``.
            state.setdefault(
                "rung", "halted" if state.get("demoted") else "canary")
            state.setdefault("promotions", [])
            return state
        return {"format": "cryptobot-ladder/1", "demoted": False,
                "reasons": [], "trades": [], "history": [], "rung": "canary",
                "promotions": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
        tmp.replace(self.path)

    def record_trade(self, *, realized_slippage_bps: float,
                     net_bps: float, predicted_slippage_bps: float | None = None,
                     ts_utc: str | None = None) -> dict[str, Any]:
        predicted = (float(predicted_slippage_bps)
                     if predicted_slippage_bps is not None
                     else self.assumed_slippage_bps)
        if predicted <= 0 or not math.isfinite(predicted):
            raise ValueError("predicted slippage must be positive")
        if not math.isfinite(float(realized_slippage_bps)) \
                or not math.isfinite(float(net_bps)):
            raise ValueError("trade attribution must be finite")
        self.state["trades"].append({
            "ts_utc": ts_utc or datetime.now(UTC).isoformat(),
            "predicted_slippage_bps": predicted,
            "realized_slippage_bps": float(realized_slippage_bps),
            "slippage_ratio": float(realized_slippage_bps) / predicted,
            "net_bps": float(net_bps)})
        self.state["trades"] = self.state["trades"][-500:]
        self._evaluate()
        return self.state

    @staticmethod
    def _ci_upper(values: list[float]) -> float | None:
        import statistics
        if len(values) < 2:
            return None
        mean = statistics.fmean(values)
        sd = statistics.pstdev(values)
        se = sd / math.sqrt(len(values))
        return mean + 1.96 * se

    def _halt(self, reasons: tuple[str, ...]) -> None:
        """Automatic demotion: unchanged, and it outranks any promotion."""
        from_rung = str(self.state.get("rung") or "canary")
        self.state["demoted"] = True
        self.state["rung"] = "halted"
        for reason in reasons:
            if reason not in self.state["reasons"]:
                self.state["reasons"].append(reason)
        self.state["history"].append({
            "ts_utc": datetime.now(UTC).isoformat(),
            "kind": "demote",
            "from_rung": from_rung,
            "to_rung": "halted",
            "reasons": list(reasons)})

    def _evaluate(self) -> None:
        trades = self.state["trades"]
        recent = trades[-30:]
        ratio = None
        if recent:
            ratio = sum(t["slippage_ratio"] for t in recent) / len(recent)
        ci_upper = self._ci_upper([t["net_bps"] for t in trades])
        reasons = demotion_reasons(
            slippage_ratio=ratio, expectancy_ci_upper_bps=ci_upper,
            expectancy_n=len(trades), expectancy_min_n=self.expectancy_min_n,
            unknown_age_s=None, unknown_budget_s=self.unknown_budget_s)
        if reasons:
            self._halt(reasons)
        self._save()

    def observe_unknown(self, age_s: float) -> tuple[str, ...]:
        reasons = demotion_reasons(
            unknown_age_s=float(age_s),
            unknown_budget_s=self.unknown_budget_s)
        if reasons:
            self.state["demoted"] = True
            self.state["rung"] = "halted"
            self.state["reasons"] = sorted(
                set(self.state["reasons"]) | set(reasons))
            self._save()
        return reasons

    def daily_stop(self) -> tuple[str, ...]:
        reasons = demotion_reasons(daily_stop_hit=True)
        self.state["demoted"] = True
        self.state["rung"] = "halted"
        self.state["reasons"] = sorted(
            set(self.state["reasons"]) | set(reasons))
        self._save()
        return reasons

    def demote(self, reason: str) -> dict[str, Any]:
        """Operator-initiated demotion; recorded, never inferred."""
        if not reason or not reason.strip():
            raise LadderError("an operator demotion needs a reason")
        self._halt((reason.strip(),))
        self._save()
        return {"rung": "halted", "reasons": [reason.strip()]}

    @property
    def demoted(self) -> bool:
        return bool(self.state["demoted"])

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(self.state["reasons"])

    @property
    def rung(self) -> str:
        return str(self.state["rung"])

    def manual_promote(self) -> None:
        """Operator clears a halt or a demotion; it lands on ``canary``.

        It cannot reach ``armed``: only :meth:`promote` with evidence does
        that, so an operator cannot skip a rung either.
        """
        from_rung = str(self.state["rung"])
        self.state["rung"] = "canary"
        self.state["demoted"] = False
        self.state["reasons"] = []
        self.state["history"].append({
            "ts_utc": datetime.now(UTC).isoformat(),
            "kind": "manual_promote",
            "manual_promote": True,
            "from_rung": from_rung,
            "to_rung": "canary"})
        self._save()

    def decide(self, evidence_path: str | Path) -> tuple[Promotion, str]:
        """Evaluate the promotion rule against an evidence document."""
        path = Path(evidence_path)
        if not path.is_file():
            raise LadderError(f"evidence {path} is missing")
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            raise LadderError(f"evidence {path} is not JSON: {exc}") from None
        if not isinstance(doc, dict):
            raise LadderError(f"evidence {path} must be a JSON object")
        _verify_evidence(doc, evidence_path=path)
        live = _live_from_evidence(doc)
        backtest = _backtest_from_evidence(doc)
        decision = promotion_decision(
            current_rung=self.rung, live=live, backtest=backtest)
        return decision, sha

    def promote(self, *, evidence_path: str | Path, commit: str,
                now: datetime | None = None) -> dict[str, Any]:
        """Promote exactly one rung, if and only if the evidence allows it."""
        path = Path(evidence_path)
        if not _COMMIT_RE.match(commit):
            raise LadderError(
                f"commit {commit!r} is not a git SHA; a promotion must name "
                "the commit its evidence was read at")
        decision, sha = self.decide(path)
        for entry in self.state["history"]:
            if entry.get("kind") == "promote" \
                    and entry.get("evidence_sha256") == sha:
                raise LadderError(
                    "this evidence document already supported a promotion at "
                    f"{entry.get('ts_utc')}; one document, one rung")
        ts = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        if not decision.allowed:
            return {"allowed": False, "rung": decision.rung,
                    "reasons": list(decision.reasons),
                    "evidence_sha256": sha, "commit": commit,
                    "ts_utc": ts, "persisted": False}
        from_rung = self.rung
        target = next_rung(from_rung)
        if target is None or decision.rung != target:
            raise LadderError(
                f"refusing a promotion that skips a rung: {from_rung} -> "
                f"{decision.rung}")
        self.state["rung"] = target
        self.state["demoted"] = False
        self.state["reasons"] = []
        entry = {
            "ts_utc": ts,
            "kind": "promote",
            "from_rung": from_rung,
            "to_rung": target,
            "evidence_path": str(path),
            "evidence_sha256": sha,
            "commit": commit,
            "reasons": [],
        }
        self.state["history"].append(entry)
        self.state["promotions"].append(
            {"ts_utc": ts, "rung": target, "evidence_sha256": sha,
             "commit": commit})
        self._save()
        return {"allowed": True, "rung": target, "reasons": [],
                "evidence_sha256": sha, "commit": commit, "ts_utc": ts,
                "persisted": True, "from_rung": from_rung}


def _derive_evidence(args: argparse.Namespace) -> str:
    """Derive the promotion evidence from journals; never accept a number typed in."""
    root = getattr(args, "root", None)
    backtest = getattr(args, "backtest", None)
    if not root or not backtest:
        raise LadderError(
            "promote needs --evidence, or --root and --backtest so the "
            "evidence can be derived from the journals")
    from cryptobot.ops.daily_pnl import build_ladder_evidence

    out = getattr(args, "evidence_out", None) or str(
        Path("runs/ladder") /
        f"evidence-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
    build_ladder_evidence(
        root, backtest_reference=backtest, out=out,
        study=str(getattr(args, "study", "unlabelled")),
        risk_state=getattr(args, "risk_state", None),
        strategy_state=str(Path(args.state)))
    print(f"ladder: derived evidence {out}")
    return out


def _git_head(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LadderError(
            f"cannot resolve the git commit under {repo_root}: {exc}") from None
    return out.stdout.strip()


def _controller(args: argparse.Namespace) -> LadderController:
    return LadderController(
        Path(args.state), assumed_slippage_bps=float(args.assumed_slippage_bps))


def cmd_ladder(args: argparse.Namespace) -> int:
    """``cryptobot ladder status|promote|demote`` (thin command wrapper)."""
    command = getattr(args, "ladder_cmd", None)
    try:
        controller = _controller(args)
        if command == "status":
            result = {
                "state": str(controller.path),
                "rung": controller.rung,
                "demoted": controller.demoted,
                "reasons": list(controller.reasons),
                "history_tail": controller.state["history"][-5:],
            }
            evidence = getattr(args, "evidence", None)
            if evidence:
                decision, sha = controller.decide(evidence)
                result["evidence_sha256"] = sha
                result["next"] = {"allowed": decision.allowed,
                                  "rung": decision.rung,
                                  "reasons": list(decision.reasons)}
            print(json.dumps(result, indent=1, sort_keys=True))
            if evidence:
                return 0 if result["next"]["allowed"] else 1
            return 0
        if command == "promote":
            evidence = getattr(args, "evidence", None)
            if not evidence:
                raise LadderError(
                    "promote needs --evidence: a promotion must cite the "
                    "document it was derived from")
            commit = getattr(args, "commit", None) or _git_head(
                Path(getattr(args, "repo_root", None) or "."))
            outcome = controller.promote(evidence_path=evidence, commit=commit)
            print(json.dumps(outcome, indent=1, sort_keys=True))
            return 0 if outcome["persisted"] else 1
        if command == "demote":
            outcome = controller.demote(str(getattr(args, "reason", "")))
            print(json.dumps(outcome, indent=1, sort_keys=True))
            return 0
    except LadderError as exc:
        print(f"ladder: REFUSED {exc}")
        return 2
    print(f"ladder: unknown command {command!r}")
    return 2


__all__ = ["LadderController", "LadderError", "cmd_ladder", "sha256_file"]
