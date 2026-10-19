# FINAL STATUS — live/edge-sprint

Worktree `/Users/sahajpatel/Code/cryto-bot-edge`, branch `live/edge-sprint`,
from `a313254`. No order was placed. No key was read. Holdout zips were
hash-sealed before returns were computed. The only holdout JSON,
`research/verdicts_b/B4.json`, is **void** under D-042 (legs were
clipped to 25% instead of the preregistered 50%). It is not a pass.

## Scores

| Score | Value | Basis |
|---|---|---|
| Infrastructure | **7/10** | Recorder, HOLDOUT vault, autopilot, verdict and human-only arm exist. Forward paper and a live drill are still owner steps. |
| Edge | **2/10** | All seven Family B hypotheses are KILLED on frozen gates after the sizing correction. B6's best Sharpe was 1.22 and still failed PBO, plateau and turnover. B4's Sharpe stayed high and failed turnover (17.05 > 12). |
| **Live = MIN** | **2/10** | No adopted screen. No arm. Gate is not GATE_READY. |

## Detectable Sharpe

SPLIT.md: one-sided 95% detectable Sharpe on the ~33-month holdout is
about **0.98**. No adopted screen cleared it.

## Both families

| Family | State | Next action |
|---|---|---|
| H1–H6 | DEV_EVAL, no dev trades | leave on the recorder timer |
| B1, B2, B3, B5, B6, B7 | KILLED | none |
| B4 | KILLED on corrected turnover | do not use `verdicts_b/B4.json` |

## Profitability at 120 / 1,000 / 10,000

Nothing is promoted, so expected deployed profit is none. A BTC hedge
sized like the voided book cannot be placed at 120 USDT because the
quantity floors through the 0.001 step.

## Next owner action

Do not arm. The ordered checklist is `OWNER_ACTIONS.md`. The next
useful step is the recorder for Family A, plus the legal and tax
confirmation in step 17 before any later arm is even considered.
