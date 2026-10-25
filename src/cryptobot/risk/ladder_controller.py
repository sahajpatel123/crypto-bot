"""F5.3: persisted capital-ladder controller (automatic demotion only).

The controller consumes per-trade attribution and supervision facts,
persists the demoted state, and never promotes. Promotion is a manual
operator action outside this class.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from .ladder import demotion_reasons


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

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"format": "cryptobot-ladder/1", "demoted": False,
                "reasons": [], "trades": [], "history": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
        tmp.replace(self.path)

    def record_trade(self, *, realized_slippage_bps: float,
                     net_bps: float, predicted_slippage_bps: float | None = None,
                     ts_utc: str | None = None) -> dict:
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
            self.state["demoted"] = True
            for reason in reasons:
                if reason not in self.state["reasons"]:
                    self.state["reasons"].append(reason)
            self.state["history"].append({
                "ts_utc": datetime.now(UTC).isoformat(),
                "reasons": list(reasons)})
        self._save()

    def observe_unknown(self, age_s: float) -> tuple[str, ...]:
        reasons = demotion_reasons(
            unknown_age_s=float(age_s),
            unknown_budget_s=self.unknown_budget_s)
        if reasons:
            self.state["demoted"] = True
            self.state["reasons"] = sorted(
                set(self.state["reasons"]) | set(reasons))
            self._save()
        return reasons

    def daily_stop(self) -> tuple[str, ...]:
        reasons = demotion_reasons(daily_stop_hit=True)
        self.state["demoted"] = True
        self.state["reasons"] = sorted(
            set(self.state["reasons"]) | set(reasons))
        self._save()
        return reasons

    @property
    def demoted(self) -> bool:
        return bool(self.state["demoted"])

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(self.state["reasons"])

    def manual_promote(self) -> None:
        """Promotion is explicitly an operator action, never automatic."""
        self.state["demoted"] = False
        self.state["reasons"] = []
        self.state["history"].append({
            "ts_utc": datetime.now(UTC).isoformat(),
            "manual_promote": True})
        self._save()


__all__ = ["LadderController"]
