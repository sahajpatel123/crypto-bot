# Grouped upgrade plan

Written after reading the machine artifacts on `release/v1`. The owner
asked for a demonstrated edge and an average of 2–3% a day. The
measured results do not support that. This plan does not retune a
frozen gate to manufacture it.

## Group 1 — What is already true

| Family | State | Evidence |
|---|---|---|
| H1–H6 | AWAIT_DATA | No L2 book, no second venue, no liquidation prints in the pilot or the 30-day benchmark |
| B1–B7 | KILLED | 59 DEV cells. Best OOS Sharpe is B4 at 4.396, drawdown 0.47%, turnover 17.05 > budget 12 |
| C1 | AWAIT_FORWARD | Prereg committed. Holdout burned. No file dated after 2026-10-17 yet |

`cryptobot monitor` on 2026-10-19 printed `NO-GO`, `HURDLE_UNMET`, and
`no demonstrated edge`.

## Group 2 — What 2–3%/day would mean

Constant 2% a day compounds to about 1,377× in a year. Constant 3% a
day compounds to about 48,483×. B4's Sharpe of 4.396 would produce a
2% daily mean only if the book also moved about 8.7% a day. The same
artifact's max drawdown is 0.47%. Those two facts cannot both be a
2%/day strategy. The high Sharpe is a quiet carry book that the
turnover rule killed. D-047 records the decision not to retune.

## Group 3 — What gets built

1. `cryptobot monitor` reads hypothesis state, the best Family B
   artifact, and the recorder heartbeat. It reports the hurdle and
   stays NO-GO. It does not write a gate or an arm file.
2. The 2–3% figure stays an owner wish outside the frozen preregs.
   C1's confirmation hurdle remains the 5% APR already in
   `research/configs/C1.toml`.
3. Forward data, when it exists, is the only place a new pass can
   appear. The adjudication date stays 2027-01-16, with the C1 grace
   cap at T+14.

## Group 4 — What stays off

No new parameter search on DEV or holdout. No orders. No keys. No GO
gate. Emulator output stays EMULATED and cannot count. H4's extra
venues stay off while disk covers about 12 days.

## Group 5 — Next honest step

Keep the recorder and the daily adjudicator. When 90 forward days
exist, score the already-frozen C1 cell once. If it misses, the
project archives as a negative result. A different idea needs a new
preregistration and a new information source.
