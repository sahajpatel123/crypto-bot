# PILOT-EXPLORATORY-2026-10-17 — 60s return-surface description

BANNER: hypothesis-GENERATING exploration only. No rules tested, no
thresholds chosen, no verdicts produced. The pilot days are now EXPLORED
data: they can never confirm a hypothesis born here (confirmation needs
fresh days + fresh prereg). Scratch script kept out of the repo (/tmp).

## Method (read-only over 29 pilot gz days, 2.07M grid seconds)
For each second with full 60s trail + 60s forward bars: trailing-60s
momentum (bps) vs forward-60s move (bps), bucketed by trail decile x UTC
hour. Gross moves, no costs.

## Result: the surface is flat
- Trail-decile -> mean forward: all 10 deciles within +/-0.11bps
  (hardest-down decile +0.07, hardest-up decile +0.00). No continuation,
  no reversal. ~200x smaller than the 26bps round-trip cost.
- UTC-hour unconditional means: all within +/-0.25bps. No session effect.
- Deepest sub-cell extremes (+0.78bps, decile 9 at 04h/08h, n~8k) are
  noise-consistent: consecutive grid seconds share 59/60 of their window,
  so effective n is ~1/60 of nominal and +/-0.8bps is ~1 effective SE.

## Implication
This KILLS the "session filter / momentum conditioning at 60s" idea
cheaply: there is no structure here worth a fresh prereg at this horizon.
Do not preregister 60s-momentum variants (hour filters, decile gates) for
fresh-data confirmation — the pilot surface gives them nothing to stand on.

Open (unexplored, still preregistrable for fresh data): nothing in this
memo promotes or demotes other horizons/families; P1 on campaign depth
data remains the live lead (battery filed, cron scheduled).
