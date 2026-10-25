"""The D1 program-level trial count: ONE constant, one place, no defaults.

D1's DSR gate (``research/prereg/D1-oi-flush-reversal.md``, gate 4) needs the
program-level configuration count ``N``.  The exact value is not frozen yet:
``research/prereg/D1-amendment-2.md`` retracted the earlier ``N >= 470`` floor
because a *lower* bound on trials makes ``SR0`` smaller and therefore the DSR
threshold easier (anti-conservative).  R2 is replacing it with a provable upper
bound (``N_max``) that must be frozen in an amendment before any D1 return,
event count or power estimate is computed.

So this module holds the only copy of the number, and it holds nothing until
the amendment lands:

    N_TRIALS                the frozen count; ``None`` until R2 sets it
    N_TRIALS_AMENDMENT      the amendment file that freezes it, named here so
                            the refusal can say which file is missing
    trial_count_ready()     the one gate the evaluator asks

Rules enforced by ``src/cryptobot/research/d1_eval.py`` (and tested in
``tests/unit/test_d1_eval.py``):

* ``N_TRIALS is None``            -> DSR is not computed and not reported as a
  number; gate 4 is ``not_evaluable``; the verdict can never be ``PASS_DEV``.
* ``N_TRIALS_AMENDMENT`` missing  -> same refusal, naming the missing path.
* ``N_TRIALS`` set                -> DSR is computed with that value; because it
  is an upper bound the resulting threshold is conservative (at least as strict
  as reality), which is the direction the prereg needs.

No other module may re-state a trial count.  Adding a number here without the
amendment file in the same commit is exactly what amendment 2 forbids.
"""

from __future__ import annotations

from pathlib import Path

#: Frozen program-level trial count for D1's DSR gate.  ``None`` means "not
#: frozen yet": the evaluator refuses to emit a DSR value rather than default to
#: a number.  Set only together with the amendment below.
N_TRIALS: int | None = None

#: The pre-evaluation amendment that freezes ``N_TRIALS`` (R2 owns this file).
N_TRIALS_AMENDMENT = "research/prereg/D1-amendment-3.md"


def trial_count_ready(repo_root: Path) -> tuple[int | None, str | None]:
    """Return ``(N, None)`` when the count is frozen, else ``(None, reason)``.

    ``repo_root`` is the checkout root; the amendment is looked up relative to
    it.  The reason string names the exact file that is missing, because "DSR
    unavailable" without a path is the kind of silence this gate exists to stop.
    """
    amendment = Path(repo_root) / N_TRIALS_AMENDMENT
    if N_TRIALS is None and not amendment.is_file():
        return None, (
            f"trial count not frozen: N_TRIALS is unset in "
            f"src/cryptobot/research/d1_trials.py and the amending file "
            f"{N_TRIALS_AMENDMENT} is missing"
        )
    if N_TRIALS is None:
        return None, (
            f"trial count not frozen: {N_TRIALS_AMENDMENT} exists but N_TRIALS "
            f"is unset in src/cryptobot/research/d1_trials.py"
        )
    if not amendment.is_file():
        return None, (
            f"trial count not frozen: N_TRIALS is set in "
            f"src/cryptobot/research/d1_trials.py but the amending file "
            f"{N_TRIALS_AMENDMENT} is missing"
        )
    if isinstance(N_TRIALS, bool) or not isinstance(N_TRIALS, int) or N_TRIALS < 1:
        return None, (
            f"trial count invalid: N_TRIALS must be a positive int, got "
            f"{N_TRIALS!r} in src/cryptobot/research/d1_trials.py"
        )
    return N_TRIALS, None
