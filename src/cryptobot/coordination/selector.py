"""Strategy selector: regime/cost/quality/dedup/opposition/cooldown (manager-owned, S6).

Admits at most ONE intent per cycle (global one-position rule, including
in-flight). Output is deterministic given the same inputs. Scoring is a
frozen transparent heuristic labeled as such — no calibrated win
probabilities or expected-value estimates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .exits import decode_exit_rule
from .intent import DataQuality, Intent

__all__ = ["Candidate", "SelectorConfig", "SelectorDecision", "Selector",
           "SCORING_LABEL"]

SCORING_LABEL = "heuristic-v1"


@dataclass(frozen=True)
class Candidate:
    strategy_id: str
    intent: Intent | None
    reject_reason: str = ""


@dataclass(frozen=True)
class SelectorConfig:
    min_reward_multiple: float = 1.0
    cooldown_s: int = 300
    allow_legacy_exit_rules: bool = False


@dataclass(frozen=True)
class SelectorDecision:
    admitted: Intent | None
    rejections: tuple[tuple[str, str], ...]  # (evidence_ref or strategy, reason)
    scoring_label: str = SCORING_LABEL
    legacy_exit: bool = False


class Selector:
    def __init__(self, config: SelectorConfig | None = None) -> None:
        self.config = config or SelectorConfig()
        self._cooldowns: dict[tuple[str, str], datetime] = {}

    def _round_trip_bps(self, intent: Intent) -> float:
        fc = intent.forecast_cost
        one_way = fc.fee_bps + fc.spread_bps + fc.slippage_bps
        return 2.0 * one_way + fc.funding_bps

    def _reward_bps(self, intent: Intent) -> float | None:
        """Planned gross reward from the decoded exit target (None if unknown)."""
        try:
            policy = decode_exit_rule(intent.exit_rule)
        except ValueError:
            return None
        if policy.target_price is None:
            return None
        ref = intent.entry_high if intent.side.value == "LONG" else intent.entry_low
        if ref <= 0:
            return None
        return abs(policy.target_price - ref) / ref * 10_000.0

    def select(self, candidates: list[Candidate], *,
               now_utc: datetime, position_busy: bool) -> SelectorDecision:
        cfg = self.config
        rejections: list[tuple[str, str]] = []
        live: list[Candidate] = []
        for cand in candidates:
            intent = cand.intent
            if intent is None:
                rejections.append((cand.strategy_id,
                                  cand.reject_reason or "strategy:no-intent"))
                continue
            ref = intent.evidence_ref
            if intent.entry_expiry_utc < now_utc:
                rejections.append((ref, "selection:expired"))
                continue
            if intent.data_quality == DataQuality.HALT:
                rejections.append((ref, "selection:halt-quality"))
                continue
            legacy = False
            try:
                decode_exit_rule(intent.exit_rule)
            except ValueError:
                if not cfg.allow_legacy_exit_rules:
                    rejections.append((ref, "selection:exit-undecodable"))
                    continue
                legacy = True
            reward = self._reward_bps(intent)
            if reward is None:
                rejections.append((ref, "selection:reward-unknown"))
                continue
            if reward < self._round_trip_bps(intent) * cfg.min_reward_multiple:
                rejections.append((ref, "selection:reward-below-cost"))
                continue
            key = (intent.strategy, intent.instrument)
            if key in self._cooldowns:
                age = (now_utc - self._cooldowns[key]).total_seconds()
                if age < cfg.cooldown_s:
                    rejections.append((ref, "selection:cooldown"))
                    continue
            live.append(cand)
            # stash legacy flag alongside via parallel list
            if legacy:
                rejections.append((ref, "selection:legacy-exit-accepted"))
        legacy_marks = {ref for ref, reason in rejections
                        if reason == "selection:legacy-exit-accepted"}
        rejections = [(ref, reason) for ref, reason in rejections
                      if reason != "selection:legacy-exit-accepted"]

        # Opposing signals on one instrument stand the whole instrument aside.
        by_symbol: dict[str, set[str]] = {}
        for cand in live:
            assert cand.intent is not None
            by_symbol.setdefault(cand.intent.instrument, set()).add(cand.intent.side.value)
        opposed = {s for s, sides in by_symbol.items() if len(sides) > 1}
        if opposed:
            kept = []
            for cand in live:
                assert cand.intent is not None
                if cand.intent.instrument in opposed:
                    rejections.append((cand.intent.evidence_ref,
                                      f"selection:opposing-stand-aside:{cand.intent.instrument}"))
                else:
                    kept.append(cand)
            live = kept

        # Dedup same (instrument, side): earliest evidence wins, deterministically.
        by_key: dict[tuple[str, str], Candidate] = {}
        for cand in sorted(live, key=lambda c: (
                c.intent.evidence_ts_utc if c.intent else now_utc,
                c.strategy_id,
                c.intent.instrument if c.intent else "")):
            assert cand.intent is not None
            key = (cand.intent.instrument, cand.intent.side.value)
            if key in by_key:
                rejections.append((cand.intent.evidence_ref, "selection:dedup"))
            else:
                by_key[key] = cand
        live = sorted(by_key.values(), key=lambda c: (
            c.intent.evidence_ts_utc, c.strategy_id, c.intent.instrument))

        if position_busy:
            for cand in live:
                assert cand.intent is not None
                rejections.append((cand.intent.evidence_ref, "selection:position-busy"))
            return SelectorDecision(None, tuple(rejections))
        if not live:
            return SelectorDecision(None, tuple(rejections))
        winner = live[0]
        assert winner.intent is not None
        for cand in live[1:]:
            assert cand.intent is not None
            rejections.append((cand.intent.evidence_ref, "selection:single-owner"))
        self._cooldowns[(winner.intent.strategy, winner.intent.instrument)] = now_utc
        return SelectorDecision(winner.intent, tuple(rejections),
                                legacy_exit=winner.intent.evidence_ref in legacy_marks)
