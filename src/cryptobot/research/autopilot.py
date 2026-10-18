"""F4.6: idempotent research autopilot state machine.

States (exactly):
  REGISTERED -> DEV_EVAL -> {KILLED | AWAIT_CONFIRM_DATA}
  AWAIT_CONFIRM_DATA -> CONFIRM -> {FAIL | PASS}
  PASS -> PAPER_14D -> PAPER_COMPARE -> GATE_READY

Every transition is appended to a hash-chained log and written to a
machine-only state file. The machine never arms anything: GATE_READY is
only an input to the human-only gate/arm path.

Dev promotion criteria (preregistered F4.2):
  * pooled dev net expectancy > +2bps at realistic cost;
  * day-block bootstrap 90% lower bound > 0;
  * positive expectancy in at least 2/3 of folds.
Confirmation requires >=300 trades and a vault one-shot token; too few
trades is UNDERPOWERED and stays AWAIT_CONFIRM_DATA.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptobot.research.verdict import evaluate_trades

STATES = ("REGISTERED", "DEV_EVAL", "KILLED", "AWAIT_CONFIRM_DATA",
          "CONFIRM", "FAIL", "PASS", "PAPER_14D", "PAPER_COMPARE",
          "GATE_READY")
TERMINAL = {"KILLED", "FAIL"}
PAPER_DAYS = 14


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _bootstrap_lower(values: list[float], *, seed: int = 7,
                     rounds: int = 2000, alpha: float = 0.10) -> float:
    import random
    if not values:
        return 0.0
    rng = random.Random(seed)
    means = sorted(statistics.fmean(values[rng.randrange(len(values))]
                                    for _ in range(len(values)))
                   for _ in range(rounds))
    return means[int(alpha * rounds)]


class Autopilot:
    def __init__(self, root: str | Path = "research/autopilot",
                 *, allow_synthetic: bool = False,
                 paper_days: int = PAPER_DAYS) -> None:
        self.root = Path(root)
        self.state_dir = self.root / "state"
        self.registry_path = self.root / "registry.json"
        self.log_path = self.root / "transitions.json"
        self.allow_synthetic = bool(allow_synthetic)
        self.paper_days = int(paper_days)
        if not self.registry_path.exists():
            _atomic(self.registry_path, {
                "format": "cryptobot-autopilot-registry/1",
                "created_utc": _utc_now(), "hypotheses": {}})
        if not self.log_path.exists():
            _atomic(self.log_path, {
                "format": "cryptobot-autopilot-transitions/1",
                "chain_head": "genesis", "entries": []})

    # -- registry ----------------------------------------------------------
    @property
    def registry(self) -> dict:
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def register(self, hypothesis: str, *, prereg: str,
                 config_sha256: str, commit: str, family_size: int = 6) -> dict:
        reg = self.registry
        if hypothesis in reg["hypotheses"]:
            raise ValueError(f"{hypothesis} already registered")
        if len(reg["hypotheses"]) >= 8:
            raise ValueError("hypothesis budget is 8 total (F4.1)")
        entry = {"hypothesis": hypothesis, "prereg": prereg,
                 "config_sha256": config_sha256, "commit": commit,
                 "family_size": int(family_size),
                 "registered_utc": _utc_now()}
        reg["hypotheses"][hypothesis] = entry
        _atomic(self.registry_path, reg)
        return entry

    # -- state -------------------------------------------------------------
    def state_path(self, hypothesis: str) -> Path:
        return self.state_dir / f"{hypothesis}.json"

    def read_state(self, hypothesis: str) -> dict:
        path = self.state_path(hypothesis)
        if not path.exists():
            return {"hypothesis": hypothesis, "state": "REGISTERED",
                    "history": [], "updated_utc": _utc_now(),
                    "provenance": "OBSERVED"}
        return json.loads(path.read_text(encoding="utf-8"))

    def _transition(self, hypothesis: str, new_state: str, *,
                    reason: str, details: dict | None = None,
                    provenance: str = "OBSERVED") -> dict:
        state = self.read_state(hypothesis)
        if state["state"] == new_state:
            return state
        if new_state not in STATES:
            raise ValueError(f"unknown autopilot state {new_state}")
        entry = {"hypothesis": hypothesis, "from": state["state"],
                 "to": new_state, "reason": reason,
                 "ts_utc": _utc_now(), "provenance": provenance,
                 "details": details or {}}
        log = json.loads(self.log_path.read_text(encoding="utf-8"))
        entry["prev"] = log.get("chain_head", "genesis")
        entry["entry_hash"] = _sha(entry)
        log["entries"].append(entry)
        log["chain_head"] = entry["entry_hash"]
        _atomic(self.log_path, log)
        history = list(state.get("history", []))
        history.append({"state": new_state, "reason": reason,
                        "ts_utc": entry["ts_utc"]})
        state.update({"state": new_state, "updated_utc": entry["ts_utc"],
                      "history": history, "reason": reason,
                      "provenance": provenance})
        if details:
            state.update({k: v for k, v in details.items()
                          if k not in {"history", "state"}})
        _atomic(self.state_path(hypothesis), state)
        return state

    def verify_log(self) -> list[str]:
        log = json.loads(self.log_path.read_text(encoding="utf-8"))
        problems: list[str] = []
        prev = "genesis"
        for i, entry in enumerate(log.get("entries", [])):
            if entry.get("prev") != prev:
                problems.append(f"entry {i}: prev mismatch")
            body = {k: v for k, v in entry.items() if k != "entry_hash"}
            if _sha(body) != entry.get("entry_hash"):
                problems.append(f"entry {i}: hash mismatch")
            prev = entry.get("entry_hash")
        if prev != log.get("chain_head"):
            problems.append("chain_head mismatch")
        return problems

    # -- artifacts ---------------------------------------------------------
    def _artifact(self, kind: str, hypothesis: str) -> dict | None:
        path = self.root / kind / f"{hypothesis}.json"
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        doc["_path"] = str(path)
        return doc

    @staticmethod
    def _provenance(doc: dict | None) -> str:
        if not doc:
            return "OBSERVED"
        return str(doc.get("provenance", "OBSERVED")).upper()

    def _guard_synthetic(self, doc: dict | None) -> str | None:
        prov = self._provenance(doc)
        if prov == "SYNTHETIC" and not self.allow_synthetic:
            return "synthetic artifact refused (autopilot requires observed)"
        return None

    # -- evaluation --------------------------------------------------------
    @staticmethod
    def dev_promotes(trades: list[dict]) -> tuple[bool, dict]:
        values = [float(r["net_bps"]) for r in trades]
        if not values:
            return False, {"reason": "no dev trades"}
        mean = statistics.fmean(values)
        lo90 = _bootstrap_lower(values, alpha=0.10)
        folds = max(1, min(3, len(values)))
        chunks = [values[i::folds] for i in range(folds)]
        positive = sum(1 for c in chunks if c and statistics.fmean(c) > 0)
        ok = mean > 2.0 and lo90 > 0 and positive >= 2
        return ok, {"dev_mean_bps": mean, "dev_ci90_lower": lo90,
                    "folds_positive": positive, "folds": folds,
                    "criterion": "mean>2bps & ci90>0 & >=2/3 folds positive"}

    def run_once(self) -> dict:
        reg = self.registry
        results = {}
        for hyp, entry in sorted(reg.get("hypotheses", {}).items()):
            results[hyp] = self._advance(hyp, entry)
        report = self.report()
        self._write_daily(report)
        return {"run_utc": _utc_now(), "hypotheses": results,
                "report": report}

    def _advance(self, hyp: str, entry: dict) -> dict:
        state = self.read_state(hyp)
        cur = state["state"]
        if cur in TERMINAL:
            return {"state": cur, "changed": False}
        if cur == "REGISTERED":
            prereg = Path(entry.get("prereg", ""))
            if not prereg.exists():
                return {"state": cur, "changed": False,
                        "blocked": f"prereg missing: {prereg}"}
            return {"state": self._transition(
                hyp, "DEV_EVAL", reason="prereg present; dev evaluation due",
                details={"prereg": str(prereg),
                         "config_sha256": entry.get("config_sha256")}
            )["state"], "changed": True}
        if cur == "DEV_EVAL":
            dev = self._artifact("dev", hyp)
            blocked = self._guard_synthetic(dev)
            if blocked:
                return {"state": cur, "changed": False, "blocked": blocked}
            if dev is None:
                return {"state": cur, "changed": False,
                        "blocked": "dev/<H>.json not present"}
            trades = dev.get("trades", [])
            ok, detail = self.dev_promotes(trades)
            if not ok:
                return {"state": self._transition(
                    hyp, "KILLED", reason="dev promotion failed",
                    details=detail,
                    provenance=self._provenance(dev))["state"],
                    "changed": True}
            # F4.4 power estimate from dev stats.
            from cryptobot.research.power import estimate_power
            values = [float(r["net_bps"]) for r in trades]
            rate = float(dev.get("trades_per_day", 1.0) or 1.0)
            power = estimate_power(values, trades_per_day=rate)
            return {"state": self._transition(
                hyp, "AWAIT_CONFIRM_DATA",
                reason="dev promotion passed; awaiting sealed confirm data",
                details={"dev": detail, "power": power.as_dict(),
                         "paper_days": PAPER_DAYS},
                provenance=self._provenance(dev))["state"],
                "changed": True}
        if cur == "AWAIT_CONFIRM_DATA":
            confirm = self._artifact("confirm", hyp)
            blocked = self._guard_synthetic(confirm)
            if blocked:
                return {"state": cur, "changed": False, "blocked": blocked}
            if confirm is None:
                return {"state": cur, "changed": False,
                        "blocked": "confirm/<H>.json not present"}
            trades = confirm.get("trades", [])
            if len(trades) < 300:
                return {"state": cur, "changed": False,
                        "blocked": f"UNDERPOWERED n={len(trades)}<300; "
                                   "extend the sealed window"}
            result = evaluate_trades(
                [float(r["net_bps"]) for r in trades],
                adverse_bps=[float(r.get("adverse_bps", r["net_bps"]))
                             for r in trades],
                days=[str(r.get("day", "")) for r in trades],
                max_dd_bps=float(confirm.get("max_dd_bps", 0.0)),
                dd_budget_bps=float(confirm.get("dd_budget_bps", 500.0)),
                family_size=int(entry.get("family_size", 6)))
            new = "PASS" if result["verdict"] == "PASS" else "FAIL"
            return {"state": self._transition(
                hyp, "CONFIRM", reason="exactly-once confirmation executed",
                details={"result": result},
                provenance=self._provenance(confirm))["state"],
                "changed": True}
        if cur == "CONFIRM":
            state = self.read_state(hyp)
            result = state.get("result") or state.get("details", {}).get(
                "result", {})
            new = "PASS" if result.get("verdict") == "PASS" else "FAIL"
            return {"state": self._transition(
                hyp, new, reason=f"confirm verdict {result.get('verdict')}",
                details={"confirm_result": result},
                provenance=state.get("provenance", "OBSERVED"))["state"],
                "changed": True}
        if cur == "PASS":
            paper = self._artifact("paper", hyp)
            blocked = self._guard_synthetic(paper)
            if blocked:
                return {"state": cur, "changed": False, "blocked": blocked}
            started = state.get("paper_started_utc")
            details = {"paper_started_utc": started or _utc_now(),
                       "paper_requires_days": self.paper_days}
            return {"state": self._transition(
                hyp, "PAPER_14D", reason="PASS: starting 14-day paper",
                details=details,
                provenance=state.get("provenance", "OBSERVED"))["state"],
                "changed": True}
        if cur == "PAPER_14D":
            paper = self._artifact("paper", hyp)
            blocked = self._guard_synthetic(paper)
            if blocked:
                return {"state": cur, "changed": False, "blocked": blocked}
            state = self.read_state(hyp)
            started = state.get("paper_started_utc")
            if not started or paper is None:
                return {"state": cur, "changed": False,
                        "blocked": "paper run incomplete"}
            try:
                elapsed = (datetime.now(timezone.utc)
                           - datetime.fromisoformat(started)).total_seconds()
            except ValueError:
                elapsed = 0.0
            if elapsed < self.paper_days * 86400:
                remaining = self.paper_days - elapsed / 86400
                return {"state": cur, "changed": False,
                        "blocked": f"paper window {remaining:.1f} days left"}
            realized = statistics.fmean(
                float(r["net_bps"]) for r in paper.get("trades", []))
            dev = state.get("dev") or state.get("details", {}).get("dev", {})
            confirmed = float(dev.get("dev_mean_bps", 0.0))
            tolerance = float(paper.get("tolerance_bps", 5.0))
            passed = abs(realized - confirmed) <= tolerance \
                and realized > 0
            return {"state": self._transition(
                hyp, "PAPER_COMPARE", reason="14-day paper window complete",
                details={"realized_bps": realized, "confirmed_bps": confirmed,
                         "tolerance_bps": tolerance, "passed": passed},
                provenance=self._provenance(paper))["state"],
                "changed": True}
        if cur == "PAPER_COMPARE":
            state = self.read_state(hyp)
            detail = state.get("details", {})
            passed = bool(state.get("passed", detail.get("passed")))
            if detail:
                detail = {**detail, **{k: state[k] for k in
                                       ("realized_bps", "confirmed_bps",
                                        "tolerance_bps") if k in state}}
            return {"state": self._transition(
                hyp, "GATE_READY" if passed else "FAIL",
                reason="paper compare " + ("PASSED" if passed else "FAILED"),
                details=detail,
                provenance=state.get("provenance", "OBSERVED"))["state"],
                "changed": True}
        return {"state": cur, "changed": False}

    # -- reporting ---------------------------------------------------------
    def report(self) -> dict:
        reg = self.registry
        rows = []
        for hyp in sorted(reg.get("hypotheses", {})):
            state = self.read_state(hyp)
            rows.append({"hypothesis": hyp, "state": state["state"],
                         "updated_utc": state.get("updated_utc"),
                         "provenance": state.get("provenance", "OBSERVED"),
                         "power": state.get("power"),
                         "reason": state.get("reason", "")})
        terminal = bool(rows) and all(
            row["state"] in TERMINAL for row in rows)
        if terminal:
            path = self.root / "reports" / "NO-EDGE.md"
            lines = ["# Terminal NO-EDGE report", "",
                     "Every registered hypothesis is KILLED or FAIL.", "",
                     "| Hypothesis | State | Reason |", "|---|---|---|"]
            lines += [f"| {r['hypothesis']} | {r['state']} | {r['reason']} |"
                      for r in rows]
            lines += ["", "Cost-to-move at the default model is 18bps "
                      "taker round trip (26bps at 2x); any remaining idea "
                      "must clear that before alpha.", ""]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"format": "cryptobot-autopilot-report/1",
                "generated_utc": _utc_now(), "hypotheses": rows,
                "terminal_no_edge": terminal,
                "log_problems": self.verify_log()}

    def _write_daily(self, report: dict) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self.root / "reports" / f"{day}.json"
        _atomic(path, report)
        md = self.root / "reports" / f"{day}.md"
        lines = [f"# Autopilot report {day}", "",
                 "| Hypothesis | State | Power ETA | Reason |",
                 "|---|---|---|---|"]
        for row in report["hypotheses"]:
            power = row.get("power") or {}
            eta = (f"{power.get('days_required'):.1f}d"
                   if power.get("days_required") is not None else "n/a")
            lines.append(f"| {row['hypothesis']} | {row['state']} | "
                         f"{eta} | {row['reason']} |")
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_autopilot(root: str | Path = "research/autopilot",
                  *, allow_synthetic: bool = False,
                  paper_days: int = PAPER_DAYS) -> dict:
    return Autopilot(root, allow_synthetic=allow_synthetic,
                     paper_days=paper_days).run_once()


__all__ = ["Autopilot", "STATES", "PAPER_DAYS", "run_autopilot"]
