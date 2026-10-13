"""Versioned round-trip cost contract (W2, 30MIN §5).

ONE contract for estimated (simulated) trade costs: schema + formula +
price reference + leg units, resolving the 26-vs-31 bps inconsistency.

Resolution (by migration analysis, not assumption): the frozen
preregistered method NET_S1_V1 (``research/experiments.py``, cited by
EXP-001..004 and ``specs/exp-returns.md``) defines round-trip as
``2*(fee+slippage) + spread + funding`` with spread the FULL observed
spread — 26 bps on the S1 preset. The spread profile
(``research/spread.py``) treats ``spread_bps`` as full spread (halved
for modeled quotes), and ``returns.py``/``runner.py`` charge 26. The
sole outlier is ``coordination/selector.py`` (``2*(fee+spread+slippage)
+ funding`` = 31), which charges the full spread per leg. Consumers
that move (proposed, owner-merged): selector formula 31→26,
``synth_benchmark`` docstring, ``returns``/``runner`` re-point, and
``ForecastCost`` funding sign (contract funding is signed).

Booked P&L is untouched: fills/commissions/settlements stay in
``accounting``. Estimates from this module are recorded SEPARATELY
(see :class:`EstimatedCost`) and must never be booked as fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "CONTRACT_VERSION",
    "METHOD_REF",
    "COST_S1",
    "CostLeg",
    "CostSpec",
    "EstimatedCost",
    "estimate_for_notional",
    "from_forecast_cost",
    "one_way_bps",
    "roundtrip_bps",
]

CONTRACT_VERSION = "cost-contract-v1"
METHOD_REF = "NET_S1_V1"


def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or value != value \
            or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class CostLeg:
    """One-way leg costs in bps of notional (fee + adverse, both >= 0)."""

    fee_bps: float
    adverse_bps: float  # slippage/adverse selection vs arrival, per leg.

    def __post_init__(self) -> None:
        _finite(self.fee_bps, "fee_bps")
        _finite(self.adverse_bps, "adverse_bps")
        if self.fee_bps < 0 or self.adverse_bps < 0:
            raise ValueError("leg costs must be >= 0")


@dataclass(frozen=True)
class CostSpec:
    """Full round-trip cost specification (estimate-side only).

    ``spread_full_bps`` is the FULL quoted spread (>= 0); each leg
    crosses half. ``funding_bps`` is SIGNED total funding for the hold
    (+ = paid, - = received). ``price_ref`` names the bps denominator:
    ``entry_notional`` (bps of qty * entry price, matching ``gross_bps``
    in ``research/returns.py``).
    """

    entry: CostLeg
    exit: CostLeg
    spread_full_bps: float
    funding_bps: float
    price_ref: str = "entry_notional"
    label: str = "conservative-simulation"

    def __post_init__(self) -> None:
        _finite(self.spread_full_bps, "spread_full_bps")
        _finite(self.funding_bps, "funding_bps")
        if self.spread_full_bps < 0:
            raise ValueError("spread_full_bps must be >= 0")
        if self.price_ref != "entry_notional":
            raise ValueError(f"unknown price_ref {self.price_ref!r}")


COST_S1 = CostSpec(
    entry=CostLeg(fee_bps=5.0, adverse_bps=5.0),
    exit=CostLeg(fee_bps=5.0, adverse_bps=5.0),
    spread_full_bps=5.0,
    funding_bps=1.0,
)


def one_way_bps(spec: CostSpec, leg: str = "entry") -> float:
    """One-way estimate: fee + half-spread + adverse for one leg."""
    active = spec.entry if leg == "entry" else spec.exit
    if leg not in ("entry", "exit"):
        raise ValueError(f"leg must be entry|exit, got {leg!r}")
    return active.fee_bps + spec.spread_full_bps / 2 + active.adverse_bps


def roundtrip_bps(spec: CostSpec) -> float:
    """Round-trip estimate: both legs (fee + half-spread + adverse) + funding.

    Funding is signed: received funding REDUCES the round-trip cost.
    """
    return (one_way_bps(spec, "entry") + one_way_bps(spec, "exit")
            + spec.funding_bps)


@dataclass(frozen=True)
class EstimatedCost:
    """Estimated cost attribution for one closed trade (never booked)."""

    contract_version: str
    label: str
    price_ref: str
    notional_usdt: float
    fee_bps: float
    spread_bps: float  # full spread crossed across both legs (2 halves).
    adverse_bps: float
    funding_bps: float  # signed.
    total_bps: float
    total_usdt: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version, "label": self.label,
            "price_ref": self.price_ref, "notional_usdt": self.notional_usdt,
            "fee_bps": self.fee_bps, "spread_bps": self.spread_bps,
            "adverse_bps": self.adverse_bps, "funding_bps": self.funding_bps,
            "total_bps": self.total_bps, "total_usdt": self.total_usdt,
        }


def estimate_for_notional(spec: CostSpec, notional_usdt: float) -> EstimatedCost:
    """Attribute a round-trip estimate to a notional (estimate-side)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional <= 0:
        raise ValueError("notional_usdt must be > 0")
    fee = spec.entry.fee_bps + spec.exit.fee_bps
    spread = spec.spread_full_bps  # two halves crossed.
    adverse = spec.entry.adverse_bps + spec.exit.adverse_bps
    total = fee + spread + adverse + spec.funding_bps
    assert abs(total - roundtrip_bps(spec)) < 1e-9  # single formula.
    return EstimatedCost(
        contract_version=CONTRACT_VERSION, label=spec.label,
        price_ref=spec.price_ref, notional_usdt=notional,
        fee_bps=fee, spread_bps=spread, adverse_bps=adverse,
        funding_bps=spec.funding_bps, total_bps=total,
        total_usdt=notional * total / 10_000.0)


def from_forecast_cost(forecast_cost: Any) -> CostSpec:
    """Map a ForecastCost (symmetric, unsigned) onto the contract.

    Both legs share fee/slippage; spread is full; funding passes
    through (ForecastCost forbids negatives — received funding needs
    the contract directly until intent.py relaxes the sign rule).
    """
    leg = CostLeg(fee_bps=float(forecast_cost.fee_bps),
                  adverse_bps=float(forecast_cost.slippage_bps))
    label = str(getattr(forecast_cost, "label", "conservative-simulation"))
    return CostSpec(entry=leg, exit=leg,
                    spread_full_bps=float(forecast_cost.spread_bps),
                    funding_bps=float(forecast_cost.funding_bps),
                    label=label)
