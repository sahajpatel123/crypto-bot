# Family B verdicts

Dev numbers are the machine artifacts `research/autopilot_b/dev/B*.json`
after the D-042 leg-size correction. A miss on any frozen bullet kills
the hypothesis. No holdout decision is adopted.

The file `research/verdicts_b/B4.json` is a **void** screen. It was
produced while B4's preregistered 50% legs were clipped to 25%
(D-042). That screen is not a pass. The corrected dev run fails the
unchanged turnover budget, so B4 never reaches a new screen.

| ID | Trials | Best OOS Sharpe | DSR | PBO | 2× Sharpe | Max DD | Turnover | State | Failed gates |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| B1 | 12 | 0.586 | 0.508 | 0.571 | 0.547 | 0.121 | 4.52 | KILLED | oos Sharpe, DSR, PBO, plateau |
| B2 | 6 | −0.325 | 0.111 | 0.414 | −0.493 | 0.150 | 13.34 | KILLED | oos Sharpe, 2×, DSR, PBO, plateau, turnover, years |
| B3 | 8 | 0.018 | 0.210 | 0.143 | −0.028 | 0.302 | 5.30 | KILLED | oos Sharpe, 2×, DSR, plateau |
| B4 | 9 | 4.396 | 1.000 | 0.000 | 1.723 | 0.005 | 17.05 | KILLED | turnover (budget 12) |
| B5 | 8 | 0.641 | 0.392 | 0.457 | 0.513 | 0.270 | 48.33 | KILLED | oos Sharpe, DSR, PBO, plateau, turnover |
| B6 | 8 | 1.224 | 0.828 | 0.371 | 1.146 | 0.127 | 7.34 | KILLED | PBO 0.37, plateau 0.67, turnover 7.34 > 6 |
| B7 | 8 | 0.147 | 0.402 | 0.600 | 0.167 | 0.295 | 6.55 | KILLED | oos Sharpe, 2×, DSR, PBO, plateau, turnover, years |

B4's Sharpe stays high because the book is a hedged funding residual
with almost no price volatility. At the preregistered 50% leg size the
one-way turnover is 17.05, above the frozen budget of 12, so the
hypothesis is killed. The void screen's point Sharpe was 2.945 and its
ending equity was 10,192.29 on 10,000. Those figures are not used.

## Detectable Sharpe

`research/prereg/SPLIT.md`: one-sided 95% detectable Sharpe on this
holdout is about **0.98**. No hypothesis reached an adopted screen, so
that bar was not cleared by a result we keep.

## Capital

No strategy is promoted, so none of 120 / 1,000 / 10,000 is allocated.
Separately, a BTC hedge at the size seen in the voided book (0.067 BTC
on 10,000 USDT) scales to about 0.0008 BTC at 120 USDT, which floors
through the 0.001 quantity step. 120 USDT cannot express that hedge
even if a future rerun passed.

## Statistics repair after the B4 kill (D-052)

B4's DSR of 1.000 was measured with n = 915 daily observations on a series
that is 75.2% exact zeros with ACF(1) = 0.46: consecutive days re-measure
the same open position. The same series has an iid t of 6.96 but a
Newey-West t(30) of 2.20. `slow_stats.deflated_sharpe` now substitutes an
autocorrelation-adjusted effective sample size for n (and caps it at
n / holding period), so the recorded numbers above are restated:

| Basis | n_eff | DSR |
|---|---:|---:|
| naive n = 915 (old code) | 915 | 1.000 |
| Newey-West, 30d lag window | 91.5 | 0.946 |
| capped by 30-day max hold | 30.5 | 0.821 |
| the ~23-bet estimate the audit argues for | 22.5 | 0.784 |

The B4 verdict does not change (it was killed on turnover, which D-051
argues is the wrong bullet), but the DSR bullet was not the clean pass it
appeared to be: at the bet count this strategy actually has, B4 fails
DSR 0.8 as well. `deflated_sharpe(..., adjust_n=False)` still reproduces
the old 0.9999998 exactly, so nothing is hidden.

The engine's own warning was also being dropped: `slow_backtest` appends
`leak-investigate` above Sharpe 3.0, and `run_family_b` discarded the
flags before writing the gate document. Flags now travel into the gate
document (`flags`, `cell_flags`, `best_cell_flags`) and a blocking flag
fails promotion, so a suspiciously good result cannot be adopted silently.

## B4b forward study (the only surviving test of this mechanism)

`research/prereg/B4b-forward-basis.md` — one cell (C1's k = 1.5,
drift_band = 0.05), one look, forward data only, committed before any
forward read. It replaces the turnover budget with per-fill square-root
impact and a 1% ADV participation cap and keeps no turnover gate at all.

**Status as of 2026-10-24: UNDERPOWERED — 0 of 90 forward days, 0 of 20
round trips.** There is no forward result to report. Vision publishes
funding monthly, the 2026-11 monthly file is the first admissible one,
and the 2026-10 file is a holdout-dated artifact that this study refuses
to decode, so the forward clock starts 2026-11-01 and the 90-day mark is
2027-01-29 at the earliest. The first tradeable decision is later still
(20 forward days of bars are needed for ADV20 and sigma). The binding
constraint is expected to be the 20 round trips, because entry needs a
trailing funding APR above 41.45% (median 8h rate above 37.9 bps) — a
rich regime, not the ordinary one. Running
`python tools/forward_b4b.py status` prints the live counters.
