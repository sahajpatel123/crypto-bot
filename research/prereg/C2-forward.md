# C2-FWD — forward paper study of daily cross-sectional momentum (prereg)

Committed before the first forward record. This opens a NEW study on
data that does not exist yet; it does not revise the historical C2
KILLED verdicts (DEV p=0.0195, holdout p=0.154, 2020-21 p=0.080). It is
the only remaining honest test of C2's consistent-but-unproven sign.

Universe (point-in-time, fixes the survivor bias of universe B): each
Monday, all TRADING USDT-margined perpetuals on Binance USD-M, ranked
by trailing 30-day quote volume; the top 30 form the week's universe.
Delisted symbols simply stop appearing; their final day is marked at
the last available close.

Rules: identical to `research.c_family.signal_xsmom` — 28-day return
on UTC daily mark closes, long top quintile / short bottom quintile,
0.5 gross per side, rebalanced on Mondays, held close-to-close; cost
9 bps per side on notional traded (2x adverse = 18); funding booked.

Recorder: `tools/forward_c2.py` (public REST only, no keys, no orders),
run once per day after 00:05 UTC; append-only `data/forward_c2/ledger.jsonl`.

Scoring (SUPERSEDED by C2-forward-amendment-1.md before any record):
exactly once, after >= 180 scored days, using
`c_family.score` (week-block bootstrap). FORWARD-PASS needs mean net >
0 at 1x with one-sided p <= 0.05, mean > 0 at 2x adverse, and max
drawdown < 2,500 bps. A PASS earns runtime work (multi-position
Session) + demo drill + gate; a FAIL closes C2 permanently. No interim
peeking at significance; the ledger may be checked only for recorder
health (days recorded, gaps).
