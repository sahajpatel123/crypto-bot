# Family C — amendment 2: C2 replication on untouched 2020-2021 (prereg)

Committed BEFORE any 2019-2021 data is downloaded or read.

C2 XSMOM was KILLED on the 2025-26 holdout (+5.95 bps/day, p=0.154)
after +9.19 bps/day on DEV (p=0.0195). Both point estimates are
positive; neither is significant at its bar. 2020-01..2021-12 is the
only remaining Binance USD-M history this project has never read.

Test (exactly once): C2 rules byte-identical to `research/c_family.py`
at this commit, universe B, same cost model and funding, scored days
2020-01-01..2021-12-31 (2019-09+ downloaded for warm-up only).

Because this revisits a killed hypothesis, the bar is stricter than the
original holdout: C2 becomes a FORWARD-PAPER CANDIDATE only if ALL of
1. mean net > 0 at 1x with one-sided week-block p <= 0.01;
2. mean > 0 at 2x adverse cost;
3. positive mean in both 2020 and 2021.
Otherwise C2 stays KILLED and Family C is closed. Regime caveat stated
up front: 2020-21 was a strong bull market that historically favours
momentum, so even a pass is regime-specific and needs >=90 days of
forward paper (scored once) before any runtime or arming work.
