"""Tiered maintenance margin + isolated liquidation (T1.8).

Binance USD-M leverage brackets: each tier caps notional and carries a
maintenance-margin ratio plus a cumulative amount (cum), so
``maintenance_margin = notional * ratio - cum`` for the active tier.
Isolated liquidation solves ``equity == maintenance margin`` for the
mark price with the position's isolated wallet as the only buffer.
"""
from __future__ import annotations

import math


from mutmut.mutation.trampoline import wrap_in_trampoline as _mutmut_mutated, MutantDict
mutants_x__finite__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x__finite__mutmut)
def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


def x__finite__mutmut_orig(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


def x__finite__mutmut_1(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) and not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


def x__finite__mutmut_2(value: float, name: str) -> float:
    if isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


def x__finite__mutmut_3(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


def x__finite__mutmut_4(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(None):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


def x__finite__mutmut_5(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(None)
    return float(value)


def x__finite__mutmut_6(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(None)

mutants_x__finite__mutmut['_mutmut_orig'] = x__finite__mutmut_orig # type: ignore # mutmut generated
mutants_x__finite__mutmut['x__finite__mutmut_1'] = x__finite__mutmut_1 # type: ignore # mutmut generated
mutants_x__finite__mutmut['x__finite__mutmut_2'] = x__finite__mutmut_2 # type: ignore # mutmut generated
mutants_x__finite__mutmut['x__finite__mutmut_3'] = x__finite__mutmut_3 # type: ignore # mutmut generated
mutants_x__finite__mutmut['x__finite__mutmut_4'] = x__finite__mutmut_4 # type: ignore # mutmut generated
mutants_x__finite__mutmut['x__finite__mutmut_5'] = x__finite__mutmut_5 # type: ignore # mutmut generated
mutants_x__finite__mutmut['x__finite__mutmut_6'] = x__finite__mutmut_6 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_maintenance_margin__mutmut)
def maintenance_margin(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_orig(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_1(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = None
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_2(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(None, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_3(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, None)
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_4(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite("notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_5(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, )
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_6(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "XXnotional_usdtXX")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_7(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "NOTIONAL_USDT")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_8(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional <= 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_9(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 1:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_10(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError(None)
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_11(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("XXnotional_usdt must be >= 0XX")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_12(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("NOTIONAL_USDT MUST BE >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_13(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_14(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError(None)
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_15(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("XXleverage brackets requiredXX")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_16(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("LEVERAGE BRACKETS REQUIRED")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_17(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(None, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_18(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=None):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_19(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_20(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, ):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_21(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: None):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_22(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(None)):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_23(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["XXnotionalCapXX"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_24(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalcap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_25(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["NOTIONALCAP"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_26(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional < float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_27(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(None):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_28(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["XXnotionalCapXX"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_29(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalcap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_30(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["NOTIONALCAP"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_31(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) + float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_32(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional / float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_33(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(None) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_34(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["XXmaintMarginRatioXX"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_35(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintmarginratio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_36(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["MAINTMARGINRATIO"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_37(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(None)
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_38(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get(None, 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_39(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", None))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_40(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get(0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_41(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", ))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_42(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("XXcumXX", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_43(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("CUM", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_44(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 1.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_45(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = None
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_46(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(None, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_47(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=None)
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_48(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_49(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, )
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_50(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: None)
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_51(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(None))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_52(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["XXnotionalCapXX"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_53(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalcap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_54(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["NOTIONALCAP"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_55(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) + float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_56(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional / float(top["maintMarginRatio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_57(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(None) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_58(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["XXmaintMarginRatioXX"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_59(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintmarginratio"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_60(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["MAINTMARGINRATIO"]) \
        - float(top.get("cum", 0.0))


def x_maintenance_margin__mutmut_61(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(None)


def x_maintenance_margin__mutmut_62(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get(None, 0.0))


def x_maintenance_margin__mutmut_63(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", None))


def x_maintenance_margin__mutmut_64(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get(0.0))


def x_maintenance_margin__mutmut_65(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", ))


def x_maintenance_margin__mutmut_66(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("XXcumXX", 0.0))


def x_maintenance_margin__mutmut_67(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("CUM", 0.0))


def x_maintenance_margin__mutmut_68(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return notional * float(tier["maintMarginRatio"]) \
                - float(tier.get("cum", 0.0))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return notional * float(top["maintMarginRatio"]) \
        - float(top.get("cum", 1.0))

mutants_x_maintenance_margin__mutmut['_mutmut_orig'] = x_maintenance_margin__mutmut_orig # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_1'] = x_maintenance_margin__mutmut_1 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_2'] = x_maintenance_margin__mutmut_2 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_3'] = x_maintenance_margin__mutmut_3 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_4'] = x_maintenance_margin__mutmut_4 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_5'] = x_maintenance_margin__mutmut_5 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_6'] = x_maintenance_margin__mutmut_6 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_7'] = x_maintenance_margin__mutmut_7 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_8'] = x_maintenance_margin__mutmut_8 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_9'] = x_maintenance_margin__mutmut_9 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_10'] = x_maintenance_margin__mutmut_10 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_11'] = x_maintenance_margin__mutmut_11 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_12'] = x_maintenance_margin__mutmut_12 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_13'] = x_maintenance_margin__mutmut_13 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_14'] = x_maintenance_margin__mutmut_14 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_15'] = x_maintenance_margin__mutmut_15 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_16'] = x_maintenance_margin__mutmut_16 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_17'] = x_maintenance_margin__mutmut_17 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_18'] = x_maintenance_margin__mutmut_18 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_19'] = x_maintenance_margin__mutmut_19 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_20'] = x_maintenance_margin__mutmut_20 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_21'] = x_maintenance_margin__mutmut_21 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_22'] = x_maintenance_margin__mutmut_22 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_23'] = x_maintenance_margin__mutmut_23 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_24'] = x_maintenance_margin__mutmut_24 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_25'] = x_maintenance_margin__mutmut_25 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_26'] = x_maintenance_margin__mutmut_26 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_27'] = x_maintenance_margin__mutmut_27 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_28'] = x_maintenance_margin__mutmut_28 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_29'] = x_maintenance_margin__mutmut_29 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_30'] = x_maintenance_margin__mutmut_30 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_31'] = x_maintenance_margin__mutmut_31 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_32'] = x_maintenance_margin__mutmut_32 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_33'] = x_maintenance_margin__mutmut_33 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_34'] = x_maintenance_margin__mutmut_34 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_35'] = x_maintenance_margin__mutmut_35 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_36'] = x_maintenance_margin__mutmut_36 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_37'] = x_maintenance_margin__mutmut_37 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_38'] = x_maintenance_margin__mutmut_38 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_39'] = x_maintenance_margin__mutmut_39 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_40'] = x_maintenance_margin__mutmut_40 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_41'] = x_maintenance_margin__mutmut_41 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_42'] = x_maintenance_margin__mutmut_42 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_43'] = x_maintenance_margin__mutmut_43 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_44'] = x_maintenance_margin__mutmut_44 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_45'] = x_maintenance_margin__mutmut_45 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_46'] = x_maintenance_margin__mutmut_46 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_47'] = x_maintenance_margin__mutmut_47 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_48'] = x_maintenance_margin__mutmut_48 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_49'] = x_maintenance_margin__mutmut_49 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_50'] = x_maintenance_margin__mutmut_50 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_51'] = x_maintenance_margin__mutmut_51 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_52'] = x_maintenance_margin__mutmut_52 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_53'] = x_maintenance_margin__mutmut_53 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_54'] = x_maintenance_margin__mutmut_54 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_55'] = x_maintenance_margin__mutmut_55 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_56'] = x_maintenance_margin__mutmut_56 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_57'] = x_maintenance_margin__mutmut_57 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_58'] = x_maintenance_margin__mutmut_58 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_59'] = x_maintenance_margin__mutmut_59 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_60'] = x_maintenance_margin__mutmut_60 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_61'] = x_maintenance_margin__mutmut_61 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_62'] = x_maintenance_margin__mutmut_62 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_63'] = x_maintenance_margin__mutmut_63 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_64'] = x_maintenance_margin__mutmut_64 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_65'] = x_maintenance_margin__mutmut_65 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_66'] = x_maintenance_margin__mutmut_66 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_67'] = x_maintenance_margin__mutmut_67 # type: ignore # mutmut generated
mutants_x_maintenance_margin__mutmut['x_maintenance_margin__mutmut_68'] = x_maintenance_margin__mutmut_68 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_liquidation_price_isolated__mutmut)
def liquidation_price_isolated(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_orig(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_1(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = None
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_2(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(None, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_3(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, None)
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_4(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite("entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_5(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, )
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_6(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "XXentryXX")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_7(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "ENTRY")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_8(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = None
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_9(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(None, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_10(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, None)
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_11(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite("qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_12(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, )
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_13(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "XXqtyXX")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_14(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "QTY")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_15(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty != 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_16(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 1:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_17(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError(None)
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_18(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("XXqty must be non-zeroXX")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_19(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("QTY MUST BE NON-ZERO")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_20(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = None
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_21(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") + _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_22(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(None, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_23(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, None) \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_24(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite("isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_25(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, ) \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_26(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "XXisolated_marginXX") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_27(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "ISOLATED_MARGIN") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_28(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(None, "maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_29(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, None)
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_30(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite("maint_margin")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_31(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, )
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_32(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "XXmaint_marginXX")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_33(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "MAINT_MARGIN")
    return entry - buffer / qty


def x_liquidation_price_isolated__mutmut_34(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry + buffer / qty


def x_liquidation_price_isolated__mutmut_35(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer * qty

mutants_x_liquidation_price_isolated__mutmut['_mutmut_orig'] = x_liquidation_price_isolated__mutmut_orig # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_1'] = x_liquidation_price_isolated__mutmut_1 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_2'] = x_liquidation_price_isolated__mutmut_2 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_3'] = x_liquidation_price_isolated__mutmut_3 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_4'] = x_liquidation_price_isolated__mutmut_4 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_5'] = x_liquidation_price_isolated__mutmut_5 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_6'] = x_liquidation_price_isolated__mutmut_6 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_7'] = x_liquidation_price_isolated__mutmut_7 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_8'] = x_liquidation_price_isolated__mutmut_8 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_9'] = x_liquidation_price_isolated__mutmut_9 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_10'] = x_liquidation_price_isolated__mutmut_10 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_11'] = x_liquidation_price_isolated__mutmut_11 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_12'] = x_liquidation_price_isolated__mutmut_12 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_13'] = x_liquidation_price_isolated__mutmut_13 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_14'] = x_liquidation_price_isolated__mutmut_14 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_15'] = x_liquidation_price_isolated__mutmut_15 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_16'] = x_liquidation_price_isolated__mutmut_16 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_17'] = x_liquidation_price_isolated__mutmut_17 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_18'] = x_liquidation_price_isolated__mutmut_18 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_19'] = x_liquidation_price_isolated__mutmut_19 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_20'] = x_liquidation_price_isolated__mutmut_20 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_21'] = x_liquidation_price_isolated__mutmut_21 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_22'] = x_liquidation_price_isolated__mutmut_22 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_23'] = x_liquidation_price_isolated__mutmut_23 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_24'] = x_liquidation_price_isolated__mutmut_24 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_25'] = x_liquidation_price_isolated__mutmut_25 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_26'] = x_liquidation_price_isolated__mutmut_26 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_27'] = x_liquidation_price_isolated__mutmut_27 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_28'] = x_liquidation_price_isolated__mutmut_28 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_29'] = x_liquidation_price_isolated__mutmut_29 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_30'] = x_liquidation_price_isolated__mutmut_30 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_31'] = x_liquidation_price_isolated__mutmut_31 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_32'] = x_liquidation_price_isolated__mutmut_32 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_33'] = x_liquidation_price_isolated__mutmut_33 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_34'] = x_liquidation_price_isolated__mutmut_34 # type: ignore # mutmut generated
mutants_x_liquidation_price_isolated__mutmut['x_liquidation_price_isolated__mutmut_35'] = x_liquidation_price_isolated__mutmut_35 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_liquidation_ok__mutmut)
def liquidation_ok(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_orig(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_1(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = None
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_2(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(None, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_3(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, None)
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_4(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite("entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_5(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, )
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_6(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "XXentryXX")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_7(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "ENTRY")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_8(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = None
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_9(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(None, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_10(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, None)
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_11(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite("stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_12(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, )
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_13(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "XXstopXX")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_14(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "STOP")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_15(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = None
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_16(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(None, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_17(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, None)
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_18(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite("liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_19(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, )
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_20(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "XXliqXX")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_21(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "LIQ")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_22(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = None
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_23(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(None, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_24(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, None)
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_25(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite("stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_26(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, )
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_27(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "XXstressed_slippage_bpsXX")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_28(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "STRESSED_SLIPPAGE_BPS")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_29(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = None
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_30(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(None)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_31(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry + stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_32(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist < 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_33(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 1:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_34(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return True
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_35(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = None
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_36(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(None)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_37(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry + liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_38(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist <= 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_39(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 / stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_40(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 4.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_41(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return True
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_42(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = None
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_43(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip * 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_44(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry / slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_45(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10001.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_46(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side != "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_47(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "XXLONGXX":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_48(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "long":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_49(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq <= stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_50(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop + slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_51(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side != "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_52(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "XXSHORTXX":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_53(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "short":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_54(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq >= stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_55(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop - slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def x_liquidation_ok__mutmut_56(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(None)

mutants_x_liquidation_ok__mutmut['_mutmut_orig'] = x_liquidation_ok__mutmut_orig # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_1'] = x_liquidation_ok__mutmut_1 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_2'] = x_liquidation_ok__mutmut_2 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_3'] = x_liquidation_ok__mutmut_3 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_4'] = x_liquidation_ok__mutmut_4 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_5'] = x_liquidation_ok__mutmut_5 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_6'] = x_liquidation_ok__mutmut_6 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_7'] = x_liquidation_ok__mutmut_7 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_8'] = x_liquidation_ok__mutmut_8 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_9'] = x_liquidation_ok__mutmut_9 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_10'] = x_liquidation_ok__mutmut_10 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_11'] = x_liquidation_ok__mutmut_11 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_12'] = x_liquidation_ok__mutmut_12 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_13'] = x_liquidation_ok__mutmut_13 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_14'] = x_liquidation_ok__mutmut_14 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_15'] = x_liquidation_ok__mutmut_15 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_16'] = x_liquidation_ok__mutmut_16 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_17'] = x_liquidation_ok__mutmut_17 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_18'] = x_liquidation_ok__mutmut_18 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_19'] = x_liquidation_ok__mutmut_19 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_20'] = x_liquidation_ok__mutmut_20 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_21'] = x_liquidation_ok__mutmut_21 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_22'] = x_liquidation_ok__mutmut_22 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_23'] = x_liquidation_ok__mutmut_23 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_24'] = x_liquidation_ok__mutmut_24 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_25'] = x_liquidation_ok__mutmut_25 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_26'] = x_liquidation_ok__mutmut_26 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_27'] = x_liquidation_ok__mutmut_27 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_28'] = x_liquidation_ok__mutmut_28 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_29'] = x_liquidation_ok__mutmut_29 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_30'] = x_liquidation_ok__mutmut_30 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_31'] = x_liquidation_ok__mutmut_31 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_32'] = x_liquidation_ok__mutmut_32 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_33'] = x_liquidation_ok__mutmut_33 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_34'] = x_liquidation_ok__mutmut_34 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_35'] = x_liquidation_ok__mutmut_35 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_36'] = x_liquidation_ok__mutmut_36 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_37'] = x_liquidation_ok__mutmut_37 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_38'] = x_liquidation_ok__mutmut_38 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_39'] = x_liquidation_ok__mutmut_39 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_40'] = x_liquidation_ok__mutmut_40 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_41'] = x_liquidation_ok__mutmut_41 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_42'] = x_liquidation_ok__mutmut_42 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_43'] = x_liquidation_ok__mutmut_43 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_44'] = x_liquidation_ok__mutmut_44 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_45'] = x_liquidation_ok__mutmut_45 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_46'] = x_liquidation_ok__mutmut_46 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_47'] = x_liquidation_ok__mutmut_47 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_48'] = x_liquidation_ok__mutmut_48 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_49'] = x_liquidation_ok__mutmut_49 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_50'] = x_liquidation_ok__mutmut_50 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_51'] = x_liquidation_ok__mutmut_51 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_52'] = x_liquidation_ok__mutmut_52 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_53'] = x_liquidation_ok__mutmut_53 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_54'] = x_liquidation_ok__mutmut_54 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_55'] = x_liquidation_ok__mutmut_55 # type: ignore # mutmut generated
mutants_x_liquidation_ok__mutmut['x_liquidation_ok__mutmut_56'] = x_liquidation_ok__mutmut_56 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_minimum_viable_equity__mutmut)
def minimum_viable_equity(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_orig(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_1(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 1.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_2(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 1.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_3(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = None
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_4(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(None, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_5(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, None)
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_6(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite("min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_7(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, )
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_8(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "XXmin_notional_usdtXX")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_9(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "MIN_NOTIONAL_USDT")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_10(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = None
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_11(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(None, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_12(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, None)
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_13(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite("stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_14(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, )
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_15(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "XXstop_dist_fracXX")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_16(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "STOP_DIST_FRAC")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_17(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = None
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_18(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(None, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_19(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, None)
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_20(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite("loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_21(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, )
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_22(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "XXloss_budget_pctXX")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_23(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "LOSS_BUDGET_PCT")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_24(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = None
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_25(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(None, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_26(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, None)
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_27(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite("stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_28(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, )
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_29(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "XXstressed_cost_fracXX")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_30(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "STRESSED_COST_FRAC")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_31(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 and costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_32(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 and budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_33(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 and dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_34(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional < 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_35(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 1 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_36(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist < 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_37(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 1 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_38(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget < 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_39(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 1 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_40(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs <= 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_41(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 1:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_42(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError(None)
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_43(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("XXminimum_viable_equity needs positive XX"
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_44(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("MINIMUM_VIABLE_EQUITY NEEDS POSITIVE "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_45(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "XXmin_notional/stop_dist/loss_budgetXX")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_46(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "MIN_NOTIONAL/STOP_DIST/LOSS_BUDGET")
    return min_notional * (dist + costs) / budget


def x_minimum_viable_equity__mutmut_47(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) * budget


def x_minimum_viable_equity__mutmut_48(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional / (dist + costs) / budget


def x_minimum_viable_equity__mutmut_49(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist - costs) / budget

mutants_x_minimum_viable_equity__mutmut['_mutmut_orig'] = x_minimum_viable_equity__mutmut_orig # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_1'] = x_minimum_viable_equity__mutmut_1 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_2'] = x_minimum_viable_equity__mutmut_2 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_3'] = x_minimum_viable_equity__mutmut_3 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_4'] = x_minimum_viable_equity__mutmut_4 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_5'] = x_minimum_viable_equity__mutmut_5 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_6'] = x_minimum_viable_equity__mutmut_6 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_7'] = x_minimum_viable_equity__mutmut_7 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_8'] = x_minimum_viable_equity__mutmut_8 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_9'] = x_minimum_viable_equity__mutmut_9 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_10'] = x_minimum_viable_equity__mutmut_10 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_11'] = x_minimum_viable_equity__mutmut_11 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_12'] = x_minimum_viable_equity__mutmut_12 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_13'] = x_minimum_viable_equity__mutmut_13 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_14'] = x_minimum_viable_equity__mutmut_14 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_15'] = x_minimum_viable_equity__mutmut_15 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_16'] = x_minimum_viable_equity__mutmut_16 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_17'] = x_minimum_viable_equity__mutmut_17 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_18'] = x_minimum_viable_equity__mutmut_18 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_19'] = x_minimum_viable_equity__mutmut_19 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_20'] = x_minimum_viable_equity__mutmut_20 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_21'] = x_minimum_viable_equity__mutmut_21 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_22'] = x_minimum_viable_equity__mutmut_22 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_23'] = x_minimum_viable_equity__mutmut_23 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_24'] = x_minimum_viable_equity__mutmut_24 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_25'] = x_minimum_viable_equity__mutmut_25 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_26'] = x_minimum_viable_equity__mutmut_26 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_27'] = x_minimum_viable_equity__mutmut_27 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_28'] = x_minimum_viable_equity__mutmut_28 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_29'] = x_minimum_viable_equity__mutmut_29 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_30'] = x_minimum_viable_equity__mutmut_30 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_31'] = x_minimum_viable_equity__mutmut_31 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_32'] = x_minimum_viable_equity__mutmut_32 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_33'] = x_minimum_viable_equity__mutmut_33 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_34'] = x_minimum_viable_equity__mutmut_34 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_35'] = x_minimum_viable_equity__mutmut_35 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_36'] = x_minimum_viable_equity__mutmut_36 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_37'] = x_minimum_viable_equity__mutmut_37 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_38'] = x_minimum_viable_equity__mutmut_38 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_39'] = x_minimum_viable_equity__mutmut_39 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_40'] = x_minimum_viable_equity__mutmut_40 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_41'] = x_minimum_viable_equity__mutmut_41 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_42'] = x_minimum_viable_equity__mutmut_42 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_43'] = x_minimum_viable_equity__mutmut_43 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_44'] = x_minimum_viable_equity__mutmut_44 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_45'] = x_minimum_viable_equity__mutmut_45 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_46'] = x_minimum_viable_equity__mutmut_46 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_47'] = x_minimum_viable_equity__mutmut_47 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_48'] = x_minimum_viable_equity__mutmut_48 # type: ignore # mutmut generated
mutants_x_minimum_viable_equity__mutmut['x_minimum_viable_equity__mutmut_49'] = x_minimum_viable_equity__mutmut_49 # type: ignore # mutmut generated
