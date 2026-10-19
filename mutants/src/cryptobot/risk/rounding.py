"""One venue-rounding rule for risk, submission, fills and protection (V-008 §7).

Every stage floors quantities to the venue LOT_SIZE step with this exact
function, so a quantity admitted by risk submits, fills and protects at
the identical value. Leaf module: no package imports (adapters and
execution import it; it imports nothing).
"""
from __future__ import annotations

import math

__all__ = ["floor_to_step", "round_to_tick"]


from mutmut.mutation.trampoline import wrap_in_trampoline as _mutmut_mutated, MutantDict
mutants_x__step_eps__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x__step_eps__mutmut)
def _step_eps(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_orig(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_1(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) and quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_2(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_3(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(None) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_4(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot <= 0:
        return 0.0
    return min(2.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_5(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 1:
        return 0.0
    return min(2.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_6(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 1.0
    return min(2.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_7(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(None, 1e-6)


def x__step_eps__mutmut_8(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), None)


def x__step_eps__mutmut_9(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(1e-6)


def x__step_eps__mutmut_10(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), )


def x__step_eps__mutmut_11(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 / math.ulp(quot), 1e-6)


def x__step_eps__mutmut_12(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(3.0 * math.ulp(quot), 1e-6)


def x__step_eps__mutmut_13(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(None), 1e-6)


def x__step_eps__mutmut_14(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), 1.000001)

mutants_x__step_eps__mutmut['_mutmut_orig'] = x__step_eps__mutmut_orig # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_1'] = x__step_eps__mutmut_1 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_2'] = x__step_eps__mutmut_2 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_3'] = x__step_eps__mutmut_3 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_4'] = x__step_eps__mutmut_4 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_5'] = x__step_eps__mutmut_5 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_6'] = x__step_eps__mutmut_6 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_7'] = x__step_eps__mutmut_7 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_8'] = x__step_eps__mutmut_8 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_9'] = x__step_eps__mutmut_9 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_10'] = x__step_eps__mutmut_10 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_11'] = x__step_eps__mutmut_11 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_12'] = x__step_eps__mutmut_12 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_13'] = x__step_eps__mutmut_13 # type: ignore # mutmut generated
mutants_x__step_eps__mutmut['x__step_eps__mutmut_14'] = x__step_eps__mutmut_14 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_floor_to_step__mutmut)
def floor_to_step(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_orig(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_1(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) and step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_2(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) and not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_3(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) and not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_4(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_5(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_6(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(None) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_7(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step < 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_8(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 1:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_9(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(None)
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_10(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) and not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_11(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) and not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_12(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_13(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_14(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(None):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_15(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(None)
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_16(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty < 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_17(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 1:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_18(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 1.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_19(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = None
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_20(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty * step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_21(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(None, 12)


def x_floor_to_step__mutmut_22(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, None)


def x_floor_to_step__mutmut_23(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(12)


def x_floor_to_step__mutmut_24(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, )


def x_floor_to_step__mutmut_25(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) / step, 12)


def x_floor_to_step__mutmut_26(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(None) * step, 12)


def x_floor_to_step__mutmut_27(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot - _step_eps(quot)) * step, 12)


def x_floor_to_step__mutmut_28(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(None)) * step, 12)


def x_floor_to_step__mutmut_29(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 13)

mutants_x_floor_to_step__mutmut['_mutmut_orig'] = x_floor_to_step__mutmut_orig # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_1'] = x_floor_to_step__mutmut_1 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_2'] = x_floor_to_step__mutmut_2 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_3'] = x_floor_to_step__mutmut_3 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_4'] = x_floor_to_step__mutmut_4 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_5'] = x_floor_to_step__mutmut_5 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_6'] = x_floor_to_step__mutmut_6 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_7'] = x_floor_to_step__mutmut_7 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_8'] = x_floor_to_step__mutmut_8 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_9'] = x_floor_to_step__mutmut_9 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_10'] = x_floor_to_step__mutmut_10 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_11'] = x_floor_to_step__mutmut_11 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_12'] = x_floor_to_step__mutmut_12 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_13'] = x_floor_to_step__mutmut_13 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_14'] = x_floor_to_step__mutmut_14 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_15'] = x_floor_to_step__mutmut_15 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_16'] = x_floor_to_step__mutmut_16 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_17'] = x_floor_to_step__mutmut_17 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_18'] = x_floor_to_step__mutmut_18 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_19'] = x_floor_to_step__mutmut_19 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_20'] = x_floor_to_step__mutmut_20 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_21'] = x_floor_to_step__mutmut_21 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_22'] = x_floor_to_step__mutmut_22 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_23'] = x_floor_to_step__mutmut_23 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_24'] = x_floor_to_step__mutmut_24 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_25'] = x_floor_to_step__mutmut_25 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_26'] = x_floor_to_step__mutmut_26 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_27'] = x_floor_to_step__mutmut_27 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_28'] = x_floor_to_step__mutmut_28 # type: ignore # mutmut generated
mutants_x_floor_to_step__mutmut['x_floor_to_step__mutmut_29'] = x_floor_to_step__mutmut_29 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_round_to_tick__mutmut)
def round_to_tick(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_orig(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_1(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) and tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_2(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) and not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_3(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) and not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_4(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_5(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_6(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(None) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_7(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick < 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_8(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 1:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_9(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(None)
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_10(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) and price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_11(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) and not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_12(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) and not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_13(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_14(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_15(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(None) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_16(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price < 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_17(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 1:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_18(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(None)
    return round(round(price / tick) * tick, 12)


def x_round_to_tick__mutmut_19(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(None, 12)


def x_round_to_tick__mutmut_20(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, None)


def x_round_to_tick__mutmut_21(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(12)


def x_round_to_tick__mutmut_22(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, )


def x_round_to_tick__mutmut_23(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) / tick, 12)


def x_round_to_tick__mutmut_24(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(None) * tick, 12)


def x_round_to_tick__mutmut_25(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price * tick) * tick, 12)


def x_round_to_tick__mutmut_26(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 13)

mutants_x_round_to_tick__mutmut['_mutmut_orig'] = x_round_to_tick__mutmut_orig # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_1'] = x_round_to_tick__mutmut_1 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_2'] = x_round_to_tick__mutmut_2 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_3'] = x_round_to_tick__mutmut_3 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_4'] = x_round_to_tick__mutmut_4 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_5'] = x_round_to_tick__mutmut_5 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_6'] = x_round_to_tick__mutmut_6 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_7'] = x_round_to_tick__mutmut_7 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_8'] = x_round_to_tick__mutmut_8 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_9'] = x_round_to_tick__mutmut_9 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_10'] = x_round_to_tick__mutmut_10 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_11'] = x_round_to_tick__mutmut_11 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_12'] = x_round_to_tick__mutmut_12 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_13'] = x_round_to_tick__mutmut_13 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_14'] = x_round_to_tick__mutmut_14 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_15'] = x_round_to_tick__mutmut_15 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_16'] = x_round_to_tick__mutmut_16 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_17'] = x_round_to_tick__mutmut_17 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_18'] = x_round_to_tick__mutmut_18 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_19'] = x_round_to_tick__mutmut_19 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_20'] = x_round_to_tick__mutmut_20 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_21'] = x_round_to_tick__mutmut_21 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_22'] = x_round_to_tick__mutmut_22 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_23'] = x_round_to_tick__mutmut_23 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_24'] = x_round_to_tick__mutmut_24 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_25'] = x_round_to_tick__mutmut_25 # type: ignore # mutmut generated
mutants_x_round_to_tick__mutmut['x_round_to_tick__mutmut_26'] = x_round_to_tick__mutmut_26 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_floor_to_tick__mutmut)
def floor_to_tick(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_orig(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_1(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(None, tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_2(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, None)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_3(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_4(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, )
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_5(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = None
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_6(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price * tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_7(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(None, 12)


def x_floor_to_tick__mutmut_8(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, None)


def x_floor_to_tick__mutmut_9(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(12)


def x_floor_to_tick__mutmut_10(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, )


def x_floor_to_tick__mutmut_11(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) / tick, 12)


def x_floor_to_tick__mutmut_12(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(None) * tick, 12)


def x_floor_to_tick__mutmut_13(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(quot - _step_eps(quot)) * tick, 12)


def x_floor_to_tick__mutmut_14(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(None)) * tick, 12)


def x_floor_to_tick__mutmut_15(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 13)

mutants_x_floor_to_tick__mutmut['_mutmut_orig'] = x_floor_to_tick__mutmut_orig # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_1'] = x_floor_to_tick__mutmut_1 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_2'] = x_floor_to_tick__mutmut_2 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_3'] = x_floor_to_tick__mutmut_3 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_4'] = x_floor_to_tick__mutmut_4 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_5'] = x_floor_to_tick__mutmut_5 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_6'] = x_floor_to_tick__mutmut_6 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_7'] = x_floor_to_tick__mutmut_7 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_8'] = x_floor_to_tick__mutmut_8 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_9'] = x_floor_to_tick__mutmut_9 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_10'] = x_floor_to_tick__mutmut_10 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_11'] = x_floor_to_tick__mutmut_11 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_12'] = x_floor_to_tick__mutmut_12 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_13'] = x_floor_to_tick__mutmut_13 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_14'] = x_floor_to_tick__mutmut_14 # type: ignore # mutmut generated
mutants_x_floor_to_tick__mutmut['x_floor_to_tick__mutmut_15'] = x_floor_to_tick__mutmut_15 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_ceil_to_tick__mutmut)
def ceil_to_tick(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_orig(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_1(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(None, tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_2(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, None)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_3(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_4(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, )
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_5(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = None
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_6(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price * tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_7(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(None, 12)


def x_ceil_to_tick__mutmut_8(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, None)


def x_ceil_to_tick__mutmut_9(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(12)


def x_ceil_to_tick__mutmut_10(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, )


def x_ceil_to_tick__mutmut_11(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) / tick, 12)


def x_ceil_to_tick__mutmut_12(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(None) * tick, 12)


def x_ceil_to_tick__mutmut_13(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(quot + _step_eps(quot)) * tick, 12)


def x_ceil_to_tick__mutmut_14(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(None)) * tick, 12)


def x_ceil_to_tick__mutmut_15(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 13)

mutants_x_ceil_to_tick__mutmut['_mutmut_orig'] = x_ceil_to_tick__mutmut_orig # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_1'] = x_ceil_to_tick__mutmut_1 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_2'] = x_ceil_to_tick__mutmut_2 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_3'] = x_ceil_to_tick__mutmut_3 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_4'] = x_ceil_to_tick__mutmut_4 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_5'] = x_ceil_to_tick__mutmut_5 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_6'] = x_ceil_to_tick__mutmut_6 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_7'] = x_ceil_to_tick__mutmut_7 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_8'] = x_ceil_to_tick__mutmut_8 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_9'] = x_ceil_to_tick__mutmut_9 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_10'] = x_ceil_to_tick__mutmut_10 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_11'] = x_ceil_to_tick__mutmut_11 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_12'] = x_ceil_to_tick__mutmut_12 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_13'] = x_ceil_to_tick__mutmut_13 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_14'] = x_ceil_to_tick__mutmut_14 # type: ignore # mutmut generated
mutants_x_ceil_to_tick__mutmut['x_ceil_to_tick__mutmut_15'] = x_ceil_to_tick__mutmut_15 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x__check_tick_args__mutmut)
def _check_tick_args(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_orig(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_1(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) and tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_2(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) and not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_3(price: float, tick: float) -> None:
    if isinstance(tick, bool) and not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_4(price: float, tick: float) -> None:
    if isinstance(tick, bool) or isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_5(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_6(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(None) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_7(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick < 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_8(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 1:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_9(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(None)
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_10(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) and price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_11(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) and not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_12(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) and not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_13(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_14(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_15(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(None) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_16(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price < 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_17(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 1:
        raise ValueError(f"price must be a finite positive number, got {price!r}")


def x__check_tick_args__mutmut_18(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(None)

mutants_x__check_tick_args__mutmut['_mutmut_orig'] = x__check_tick_args__mutmut_orig # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_1'] = x__check_tick_args__mutmut_1 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_2'] = x__check_tick_args__mutmut_2 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_3'] = x__check_tick_args__mutmut_3 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_4'] = x__check_tick_args__mutmut_4 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_5'] = x__check_tick_args__mutmut_5 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_6'] = x__check_tick_args__mutmut_6 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_7'] = x__check_tick_args__mutmut_7 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_8'] = x__check_tick_args__mutmut_8 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_9'] = x__check_tick_args__mutmut_9 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_10'] = x__check_tick_args__mutmut_10 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_11'] = x__check_tick_args__mutmut_11 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_12'] = x__check_tick_args__mutmut_12 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_13'] = x__check_tick_args__mutmut_13 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_14'] = x__check_tick_args__mutmut_14 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_15'] = x__check_tick_args__mutmut_15 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_16'] = x__check_tick_args__mutmut_16 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_17'] = x__check_tick_args__mutmut_17 # type: ignore # mutmut generated
mutants_x__check_tick_args__mutmut['x__check_tick_args__mutmut_18'] = x__check_tick_args__mutmut_18 # type: ignore # mutmut generated
