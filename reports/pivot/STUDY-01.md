# STUDY-01 — 60s momentum scalp: preregistered measurement (NOT a strategy)

Status: PREREGISTERED. Hypothesis + method frozen below BEFORE running.
Results section filled after the run, unedited method. This study creates
no strategy, changes no strategy code (W1 lane untouched), and claims no
profit. It answers one question with the repo's own bytes: does trailing
60-second momentum on BTC/ETH perps continue enough to cover taker costs?

## H-01 (the claim under test)

"After a ±15bps trailing-60s impulse, the next 60s continues in the same
direction by more than round-trip taker costs (26bps, cost-contract-v1)."

Direction: LONG on trailing >= +15bps, SHORT on trailing <= -15bps.
Sensitivity arm: ±30bps thresholds, same construction.

## Data (frozen)

- `data/captures/cap-2h`, symbols BTCUSDT + ETHUSDT (whichever present;
  absent symbol = absent result, never imputed).
- 1s bars from `aggTrade` causal `exchange_ts_ms`, close = last price in
  the second. Missing seconds stay missing (no forward-fill).
- Mechanical warmup: first 130 trade-present seconds excluded.

## Method (frozen; see `tools/pivot_study_01_momentum.py`)

- Signal at bar t requires closes at t AND t-60 (else skip, no
  imputation). Forward return = close(t+60)/close(t)-1; missing t+60
  close = skip.
- One-position rule: after a signal at t, signals until t+60 ignored.
- Execution assumption (OPTIMISTIC, favors the hypothesis): fill exactly
  at bar closes, zero latency, zero spread-cross beyond the charged
  costs, no funding. Any real system does worse than this.
- Metrics per (symbol, threshold, side): n, gross mean/std (bps),
  net mean at 26bps RT, net hit rate, net winners count.

## Decision rule (frozen)

- Net mean > 0 at 26bps with n >= 30 in any cell -> W1 follow-up
  merited (new hypothesis, fresh data, full harness — NOT validation).
- Else -> H-01 REJECTED on this data; momentum-scalp does not clear
  taker costs even under optimistic execution.

## Cost context (repo + venue)

- Repo charge: 26bps RT (`COST_S1`: 2x(5 fee + 5 adverse) + 5 spread + 1
  funding). Optimistic-vs-real note: adverse 5bps/leg is a placeholder;
  live adverse selection on momentum-chasing taker fills is typically
  worse, never better.
- Venue check: web search attempted this turn, integration returned no
  results — NO fresh venue verification claimed. The 5bps/leg leg cost
  is the repo's frozen conservative-simulation preset (comparability
  with all prior rounds), not a re-verified fee schedule. Fee-schedule
  re-verification stays a data-lane task; directionally, any VIP0
  retail taker schedule keeps the hurdle at or above this level.

## RESULTS (filled after run; method above untouched)

Run: `python3 tools/pivot_study_01_momentum.py --capture
data/captures/cap-2h --symbols BTCUSDT,ETHUSDT` (exit 0).
Frozen records: `reports/pivot/study01-prereg.json` (±15, ±30),
`reports/pivot/study01-posthoc.json` (±5, ±10 diagnostic).

### Preregistered outcome: H-01 REJECTED (n = 0, all 8 cells)

No ±15bps or ±30bps trailing-60s impulse occurred once in 2 hours on
either symbol. Script-integrity probe confirmed this is the data, not a
bug: BTC trailing-60s stdev = 2.12bps (max 7.89, n=5256); ETH stdev =
2.79bps (max 10.92, n=5356). The impulses the hypothesis needs do not
exist at these thresholds.

### Volatility-vs-cost context (the decisive numbers)

- 26bps RT hurdle vs BTC 60s stdev 2.12bps: hurdle is **12x** typical
  movement, **3.3x** the single largest 60s move in 2h (7.89bps).
- Even a perfect 60s-direction predictor capturing the average |move|
  (~2bps) loses ~24bps per trade. No signal processing changes this;
  it is arithmetic.

### Post-hoc diagnostic (labeled exploration, not preregistered)

At ±5bps (where signals exist): 41 signals total, gross means -0.2 to
-1.5bps (zero continuation — slightly negative), net means -22.6 to
-27.5bps, **0/41 net winners**. At ±10bps: 2 signals, both net-negative.

### Verdict

Momentum-scalp at 60s horizons does not clear taker costs on this data
even under optimistic execution (fills at closes, zero latency). No W1
strategy follow-up is merited for this hypothesis. The scalp-thesis
question is now measured on repo bytes, not argued from priors.
