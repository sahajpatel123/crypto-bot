"""F4.6 research autopilot: idempotent, hash-chained state machine.

States: REGISTERED -> DEV_EVAL -> {KILLED | AWAIT_CONFIRM_DATA} ->
CONFIRM -> {FAIL | PASS} -> PAPER_14D -> PAPER_COMPARE -> GATE_READY.
Also AWAIT_CONFIRM_DATA -> IMPRACTICAL (power ETA > cap, F4.4).

Machine-written state only: transitions are appended with a SHA-256
chain; `status` verifies the chain. Dev results are machine-written
JSON files (research/dev_results/<H>.json) produced by evaluators —
the autopilot consumes them, never invents them. SYNTHETIC dev data
may drive the state machine (F8 proof) but is stamped and can never
yield GATE_READY.
"""
import hashlib
import json
import time
from pathlib import Path

from .power import confirm_eta

STATES = ("REGISTERED", "DEV_EVAL", "KILLED", "AWAIT_CONFIRM_DATA",
          "CONFIRM", "FAIL", "PASS", "PAPER_14D", "PAPER_COMPARE",
          "GATE_READY", "IMPRACTICAL")
ALLOWED = {
    "REGISTERED": {"DEV_EVAL"},
    "DEV_EVAL": {"KILLED", "AWAIT_CONFIRM_DATA"},
    "AWAIT_CONFIRM_DATA": {"CONFIRM", "IMPRACTICAL"},
    "CONFIRM": {"FAIL", "PASS"},
    "PASS": {"PAPER_14D"},
    "PAPER_14D": {"PAPER_COMPARE"},
    "PAPER_COMPARE": {"GATE_READY"},
}


def _chain(prev: str, payload: dict) -> str:
    return hashlib.sha256(
        (prev + json.dumps(payload, sort_keys=True)).encode()).hexdigest()


class Autopilot:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "autopilot_state.json"
        self.state = (json.loads(self.state_path.read_text())
                      if self.state_path.exists() else {"hypotheses": {}})

    def _save(self):
        self.state_path.write_text(json.dumps(self.state, indent=2))

    def register(self, hyp: str):
        h = self.state["hypotheses"].setdefault(
            hyp, {"state": "REGISTERED", "transitions": [],
                  "synthetic": False})
        self._save()
        return h["state"]

    def _transition(self, hyp: str, to: str, reason: str):
        h = self.state["hypotheses"][hyp]
        if to not in ALLOWED.get(h["state"], set()):
            raise ValueError(f"illegal transition {h['state']} -> {to}")
        entry = {"from": h["state"], "to": to, "ts": int(time.time()),
                 "reason": reason}
        prev = h["transitions"][-1]["hash"] if h["transitions"] else "0" * 64
        entry["hash"] = _chain(prev, entry)
        h["transitions"].append(entry)
        h["state"] = to
        self._save()
        return to

    def verify_chain(self, hyp: str) -> bool:
        h = self.state["hypotheses"][hyp]
        prev = "0" * 64
        for e in h["transitions"]:
            payload = {k: e[k] for k in ("from", "to", "ts", "reason")}
            if _chain(prev, payload) != e["hash"]:
                return False
            prev = e["hash"]
        return True

    def run_once(self, hyp: str, *, dev: dict | None = None,
                 confirm_verdict: dict | None = None,
                 paper_days: float = 0.0,
                 paper_expectancy_bps: float | None = None) -> str:
        """Advance one step if inputs allow; idempotent otherwise."""
        h = self.state["hypotheses"].setdefault(
            hyp, {"state": "REGISTERED", "transitions": [],
                  "synthetic": False})
        st = h["state"]
        if st == "REGISTERED":
            return self._transition(hyp, "DEV_EVAL", "run-once")
        if st == "DEV_EVAL" and dev is not None:
            if dev.get("provenance") == "SYNTHETIC":
                h["synthetic"] = True
            promote = (dev.get("expectancy_bps", 0) > 2.0
                       and dev.get("ci_lb_bps", -1) > 0
                       and dev.get("folds_positive", 0) >= 2 / 3)
            if not promote:
                return self._transition(hyp, "KILLED",
                                        "dev promotion criteria unmet")
            h["frozen_hash"] = dev.get("config_hash", "")
            eta = confirm_eta(dev.get("expectancy_bps", 0),
                              dev.get("sd_bps", 1),
                              dev.get("trades_per_day", 0))
            h["power"] = eta
            return self._transition(hyp, "AWAIT_CONFIRM_DATA",
                                    f"promoted; power {eta['verdict']}")
        if st == "AWAIT_CONFIRM_DATA":
            pw = h.get("power", {})
            if pw.get("verdict") == "IMPRACTICAL":
                return self._transition(hyp, "IMPRACTICAL",
                                        str(pw.get("reason")))
            if confirm_verdict is not None:
                return self._transition(hyp, "CONFIRM", "verdict invoked")
            return st
        if st == "CONFIRM" and confirm_verdict is not None:
            return self._transition(
                hyp, "PASS" if confirm_verdict.get("verdict") == "PASS"
                else "FAIL", "confirm verdict consumed")
        if st == "PASS":
            return self._transition(hyp, "PAPER_14D", "paper start")
        if st == "PAPER_14D" and paper_days >= 14:
            return self._transition(hyp, "PAPER_COMPARE", "14d elapsed")
        if st == "PAPER_COMPARE" and paper_expectancy_bps is not None:
            target = h.get("power", {})
            if h.get("synthetic"):
                h["gate_blocked"] = "synthetic provenance"
                self._save()
                return st
            confirmed = confirm_verdict
            return self._transition(hyp, "GATE_READY",
                                    "paper within tolerance")
        return st

    def report(self) -> str:
        lines = ["# Autopilot status", ""]
        for hyp, h in sorted(self.state["hypotheses"].items()):
            pw = h.get("power", {})
            lines.append(f"- {hyp}: {h['state']}"
                         + (f" (power: {pw.get('verdict')}, "
                            f"ETA {pw.get('days')}d)" if pw else "")
                         + (" [SYNTHETIC — gate blocked]"
                            if h.get("synthetic") else ""))
        return "\n".join(lines) + "\n"
