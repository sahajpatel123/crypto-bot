"""Capital ladder, automatic demotion, canary sizing and evidence-gated promotion (T6.2/T6.3).

Demotion is automatic: stressed slippage, a rolling expectancy CI whose UPPER
bound is negative, an unknown outcome aged past its budget, or the operating
daily stop each force the bot back to minimum size / halted.

Promotion is *evidence gated* and never automatic in the sense of trusting a
number typed by a human: :func:`promotion_decision` is a pure rule over
:class:`LiveStatistics` and :class:`BacktestReference`. It refuses whenever a
required statistic is absent, and it only ever moves one rung up
(``halted -> canary -> armed``), so no path skips a rung.

Every threshold below is an OPERATIONAL sizing rule, not a research gate. It
cannot make a strategy pass, it cannot revive a killed family, and it does not
touch the program gate (NO-GO). See DECISIONS.md, "Operational ladder
promotion".
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

#: Rungs, lowest first. ``armed`` is the only rung that sizes real capital.
RUNG_ORDER: tuple[str, ...] = ("halted", "canary", "armed")

#: Closed live round trips required before a promotion may be considered.
#: 100 is more than three times the 30-trade window the demoter uses for its
#: expectancy CI, so a promotion can never fire on a sample the demoter would
#: still call noise, and one regime cannot dominate the evidence.
PROMOTION_MIN_LIVE_ROUND_TRIPS = 100

#: Distinct live trading days required. One calendar month spans every weekly
#: pattern and a full set of funding cycles; it is the same 30-day horizon the
#: demoter's expectancy window assumes.
PROMOTION_MIN_LIVE_DAYS = 30.0

#: Live Sharpe must reach this fraction of the backtest Sharpe. Half the
#: backtest allows for the optimism a backtest carries (no queue position,
#: ideal fills) while still refusing a live result that is not the same order
#: of magnitude as the reference the capital was justified with.
PROMOTION_SHARPE_FRACTION = 0.5

#: Realised cost may be at most this multiple of the modelled cost. The same
#: 1.5x multiple the demoter uses for "slippage>1.5x-assumed", so promotion and
#: demotion agree on what "costs are out of line" means.
PROMOTION_COST_MULTIPLE = 1.5

#: Live max drawdown may be at most this multiple of the backtest drawdown.
#: Matches the 1.5x stress multiple the research code charges its own books.
PROMOTION_DRAWDOWN_MULTIPLE = 1.5

#: Format of the evidence document a promotion must cite.
PROMOTION_EVIDENCE_FORMAT = "cryptobot-ladder-evidence/1"

#: The module that derives live statistics from journals. Only a document whose
#: ``generated_by.code_sha256`` matches this file is accepted as evidence, so a
#: hand-written number is refused (see DECISIONS.md for the residual limit).
EVIDENCE_GENERATOR_MODULE = "cryptobot.ops.daily_pnl"


def demotion_reasons(*, slippage_ratio: float | None = None,
                     expectancy_ci_upper_bps: float | None = None,
                     expectancy_n: int = 0, expectancy_min_n: int = 30,
                     unknown_age_s: float | None = None,
                     unknown_budget_s: float = 60.0,
                     daily_stop_hit: bool = False) -> tuple[str, ...]:
    """All currently-triggered demotion reasons (empty = none)."""
    out: list[str] = []
    if slippage_ratio is not None and slippage_ratio > 1.5:
        out.append("slippage>1.5x-assumed")
    if expectancy_ci_upper_bps is not None \
            and expectancy_n >= expectancy_min_n \
            and expectancy_ci_upper_bps < 0:
        out.append("expectancy-ci-upper<0")
    if unknown_age_s is not None and unknown_age_s > unknown_budget_s:
        out.append("unknown-outcome-aged")
    if daily_stop_hit:
        out.append("operating-daily-stop")
    return tuple(out)


def canary_size(*, trade_index: int, canary_trades: int,
                min_qty: float, planned_qty: float) -> float:
    """First ``canary_trades`` after arming trade at minimum size."""
    if trade_index < max(0, int(canary_trades)):
        return float(min_qty)
    return float(planned_qty)


def ladder_level(*, armed_capital_usdt: float, demoted: bool,
                 canary_done: bool) -> str:
    """Current ladder rung: halted < canary < armed (promotion evidence gated)."""
    if demoted:
        return "halted"
    if not canary_done:
        return "canary"
    return "armed" if armed_capital_usdt > 0 else "halted"


@dataclass(frozen=True)
class LiveStatistics:
    """Measured live performance, derived from journals (never typed in)."""

    round_trips: int
    days: float
    sharpe: float | None = None
    cost_bps: float | None = None
    max_drawdown_frac: float | None = None
    halted: bool = False


@dataclass(frozen=True)
class BacktestReference:
    """The strategy's own backtest numbers a promotion is measured against."""

    sharpe: float | None = None
    cost_bps: float | None = None
    max_drawdown_frac: float | None = None


class Promotion(NamedTuple):
    """``(allowed, rung, reasons)`` — the rung is the target when allowed."""

    allowed: bool
    rung: str
    reasons: tuple[str, ...]


def next_rung(rung: str) -> str | None:
    """The one rung above ``rung``; ``None`` at the top or for an unknown rung."""
    try:
        index = RUNG_ORDER.index(rung)
    except ValueError:
        return None
    if index + 1 >= len(RUNG_ORDER):
        return None
    return RUNG_ORDER[index + 1]


def _usable(value: float | None) -> bool:
    """``True`` when the statistic was actually measured, not just present."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def promotion_decision(*, current_rung: str, live: LiveStatistics,
                       backtest: BacktestReference) -> Promotion:
    """Decide whether live evidence may promote one rung.

    The rule fails closed: a missing or non-finite statistic is a refusal with
    its own reason, never a default to "allowed". Reasons are returned in a
    fixed order so a decision document is reproducible.
    """
    reasons: list[str] = []
    target = next_rung(current_rung)
    if current_rung not in RUNG_ORDER:
        reasons.append(f"unknown-rung:{current_rung}")
    elif current_rung == "halted":
        # Clearing a halt is an operator action, and it lands on canary —
        # evidence alone never lifts a halt.
        reasons.append("rung-halted")
    elif target is None:
        reasons.append("rung-already-armed")

    if live.halted:
        reasons.append("risk-halted")

    if live.round_trips < PROMOTION_MIN_LIVE_ROUND_TRIPS:
        reasons.append(
            f"live-round-trips<{PROMOTION_MIN_LIVE_ROUND_TRIPS}")
    if not _usable(live.days) or live.days < PROMOTION_MIN_LIVE_DAYS:
        reasons.append(f"live-days<{PROMOTION_MIN_LIVE_DAYS:g}")

    if not _usable(live.sharpe):
        reasons.append("live-sharpe-missing")
    if not _usable(backtest.sharpe):
        reasons.append("backtest-sharpe-missing")
    elif backtest.sharpe is not None and backtest.sharpe <= 0:
        reasons.append("backtest-sharpe<=0")
    elif _usable(live.sharpe) and live.sharpe is not None \
            and backtest.sharpe is not None \
            and live.sharpe < PROMOTION_SHARPE_FRACTION * backtest.sharpe:
        reasons.append("live-sharpe<0.5x-backtest")

    if not _usable(live.cost_bps):
        reasons.append("live-cost-missing")
    if not _usable(backtest.cost_bps):
        reasons.append("backtest-cost-missing")
    elif backtest.cost_bps is not None and backtest.cost_bps <= 0:
        reasons.append("backtest-cost<=0")
    elif _usable(live.cost_bps) and live.cost_bps is not None:
        assert backtest.cost_bps is not None
        if live.cost_bps < 0:
            reasons.append("live-cost<0")
        elif live.cost_bps > PROMOTION_COST_MULTIPLE * backtest.cost_bps:
            reasons.append("live-cost>1.5x-backtest")

    if not _usable(live.max_drawdown_frac):
        reasons.append("live-drawdown-missing")
    if not _usable(backtest.max_drawdown_frac):
        reasons.append("backtest-drawdown-missing")
    elif backtest.max_drawdown_frac is not None \
            and backtest.max_drawdown_frac <= 0:
        reasons.append("backtest-drawdown<=0")
    elif _usable(live.max_drawdown_frac) \
            and live.max_drawdown_frac is not None:
        assert backtest.max_drawdown_frac is not None
        if live.max_drawdown_frac < 0 or live.max_drawdown_frac > 1:
            reasons.append("live-drawdown-out-of-range")
        elif live.max_drawdown_frac > \
                PROMOTION_DRAWDOWN_MULTIPLE * backtest.max_drawdown_frac:
            reasons.append("live-drawdown>1.5x-backtest")

    if reasons or target is None:
        # ``target is None`` cannot happen without a reason above; keeping the
        # branch means the rule fails closed even if that ever changes.
        return Promotion(False, current_rung, tuple(reasons))
    return Promotion(True, target, ())


def _check_finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


__all__ = [
    "BacktestReference",
    "EVIDENCE_GENERATOR_MODULE",
    "LiveStatistics",
    "PROMOTION_COST_MULTIPLE",
    "PROMOTION_DRAWDOWN_MULTIPLE",
    "PROMOTION_EVIDENCE_FORMAT",
    "PROMOTION_MIN_LIVE_DAYS",
    "PROMOTION_MIN_LIVE_ROUND_TRIPS",
    "PROMOTION_SHARPE_FRACTION",
    "Promotion",
    "RUNG_ORDER",
    "canary_size",
    "demotion_reasons",
    "ladder_level",
    "next_rung",
    "promotion_decision",
]
