# Family C — amendment 1 (committed after DEV, before any HOLDOUT read)

DEV result (reports/hypotheses/C-dev.json): all four FAIL the DEV bar.
C4 REVERSAL and C3 CARRY are KILLED (negative/zero means).
C1 TSMOM (+9.3 bps/day, p=0.106) and C2 XSMOM (+9.2 bps/day, CI95 lower
+0.43, p=0.0195, 2024 −1.08) are near-misses.

Decision, disclosed as post-DEV: the HOLDOUT is spent on exactly ONE
hypothesis, selected by the best DEV annualised Sharpe: **C2 XSMOM**
(1.06 vs C1 0.63). Rules frozen as in C-family-daily.md at this commit.
C1 is NOT tested on the holdout, now or later (it stays unconfirmed).

HOLDOUT criteria unchanged: mean daily net > 0 at 1x, one-sided
week-block bootstrap p <= 0.05, mean at 2x adverse > 0. Because C2 was
selected from 4 on DEV and failed the DEV bar, a holdout CONFIRMED is
weaker evidence than a clean DEV PASS: it earns only a forward paper
run (>=90 days, scored once), never direct arming.
