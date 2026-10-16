# SC micro-breakout scalp — exact rules v0.1.0

Status: BASELINE (simulation only; not a validated trading system).
Written before any SC measurement was opened. Parameters are not
fitted to a tape. Production order submission stays refused.

## 1. Why this shape

A scalp is a round trip that is over in at most a few minutes. On
this stack the selector drops any intent whose target does not clear
the frozen round-trip forecast. That forecast is NET_S1_V1:

`2 · (fee_bps + spread_bps / 2 + slippage_bps) + funding_bps`
`= 2 · (5 + 2.5 + 5) + 1 = 26` bps.

A target inside 26 bps is rejected before it can trade. The scalp
therefore asks for a 40 bps target, which clears 26 bps after the
2 bps entry band, and it refuses a stop that is either inside the
spread noise or wide enough to be a swing. Holding is 90 seconds.
That is the whole economic rule. It is not a claim that a day of
these trades returns 1.5–2%.

## 2. Bar schema and causality

Same 1-second bars as S1. Evaluate at index `t`. Windows end at
`t-1` except the trigger bar's own close, spread, and the momentum
endpoint `close[t]`. No later bar is read. `t < 60` does not fire
(`insufficient-history`).

## 3. Frozen parameters v0.1.0

| Name | Value | Meaning |
|---|---|---|
| `WARMUP_N` | 60 | minimum bar index |
| `RANGE_N` | 20 | micro-range, bars `t-20..t-1` |
| `MOM_M` | 20 | momentum lookback |
| `EXTENSION_MIN_BPS` | 8.0 | min break beyond the micro-range |
| `MOM_MIN_BPS` | 8.0 | min 20-bar return, same sign |
| `SPREAD_MAX_BPS` | 4.0 | reject a wider trigger-bar spread |
| `STOP_MIN_BPS` | 8.0 | stop closer than this is noise |
| `STOP_MAX_BPS` | 20.0 | stop wider than this is not a scalp |
| `TARGET_BPS` | 40.0 | target distance from the trigger close |
| `ENTRY_TOL_BPS` | 2.0 | entry band around the trigger close |
| `ENTRY_EXPIRY_S` | 5 | do not chase a stale scalp |
| `HOLDING_LIMIT_S` | 90 | time exit; under a few minutes |
| `MAX_CONSECUTIVE_MISSING_HALT` | 5 | same gap halt as S1 |

One arm: `SC`. Forecast cost is the shared conservative preset
(`fee 5, spread 5, slippage 5, funding 1`, label
`conservative-simulation`).

Exit wire: `stop` = the far side of the micro-range, `target` =
`close[t] · (1 ± TARGET_BPS/1e4)`, `time_exit` = evidence + 90s,
policy id `SC:stop+target+time`.

Research config cooldown is 60 seconds (`configs/sc-dev.toml`).
That number is part of this freeze.

## 4. Per-side trigger

LONG, all must hold:

1. `close[t] > max(high[t-20..t-1])`.
2. Extension `(close[t] − ref_high) / close[t] · 1e4 >= 8`.
3. Momentum `(close[t] / close[t-20] − 1) · 1e4 >= 8`.
4. `spread_bps[t] <= 4`.
5. Stop distance `(close[t] − range_low) / close[t] · 1e4` is inside
   `[8, 20]`.
6. Planned reward from the entry bound to the target is at least 26 bps.
   With these constants it is about 38 bps. If a later edit breaks
   that, the side rejects `reward-below-cost` and does not emit.

SHORT mirrors every sign. Opposing fires are left to the selector,
which stands the instrument aside.

## 5. Measurement window (declared before the run)

Development only. Deep split idx 1, IST date 2026-09-12, which is
role `dev` in `datasets/splits_deep.toml`. The burned test split
(idx 23–30) is not used.

The scored slice is the first 15 minutes of that IST date, one
accounting date, so the average daily net is the window's own ledger
net return. It is not multiplied by 1440/15.

- Start: 2026-09-12 00:00 IST = 2026-09-11 18:30:00Z = `1789151400000`
- End (exclusive): 2026-09-12 00:15 IST = 2026-09-11 18:45:00Z = `1789152300000`
- Symbol: BTCUSDT
- UTC day file: `2026-09-11`
- Dataset: `datasets/benchmark_30d.toml`
- Spread: the bench's frozen profile (`--spread-bps` with no number).
  The archive has no BBO. The profile is not fitted to this run.
- Filters: `filters/x1_bench_filters.json` (no network).

Funding that is absent on the capture is reported and is not added
into the return. A booked funding of zero is not treated as a profit.

## 6. Verdict rule

`avg_daily_net_pct = net_return_pct / max(1, accounting_dates)`.

Inside the closed band means `1.5 <= avg_daily_net_pct <= 2.0`.

Qualified for real capital only when that average is inside the band,
the ledger net is strictly positive, and a separate validation net
is strictly positive. This measurement does not score validation, so
the recorded verdict is not qualified. Missing the band is recorded
as measured. Costs, the window, and the holdout are not edited
afterwards.
