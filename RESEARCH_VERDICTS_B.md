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
