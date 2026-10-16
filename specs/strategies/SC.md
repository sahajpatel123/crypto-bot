# SC micro-breakout scalp — exact rules v0.1.9

Status: BASELINE (simulation only; not a validated trading system).
v0.1.0 was frozen before the first measurement. That run rejected
quiet seconds as gaps. v0.1.1 fixed only that. Its rerun, on the
same window, rejected 838 of 839 evaluations as `breakout:fail`:
an 8 bps close through the prior 20-second high does not occur on
these 1-second bars. v0.1.2 shortened that to a 5-second impulse and
a 1.5 bps break. That rerun still booked nothing: 812 of 839
evaluations were `breakout:fail`. A 1.5 bps hurdle is still larger
than the new highs this tape prints. v0.1.3 is frozen before the
next measurement. The trigger is a strict break of the prior
5-second range plus at least 1 bp of 5-second momentum. v0.1.3
did fire: three intents reached risk and were refused
`skip:min-notional`, because the 0.125% budget cannot buy the
venue's minimum BTC lot on a 120 USDT book. v0.1.4 is frozen
before the next measurement. Only the size of an SC order changes.
When the budget quantity is below the venue minimum quantity or
minimum notional, SC submits the smallest lot that clears both,
rounded up to the lot step. That lot is allowed only when its stop
loss plus stressed costs fits inside the configured operating stop
(0.5% of reconciled equity) and inside the room still left before
that stop. If it does not, the reason is
`sizing:min-lot-exceeds-operating-stop`. Every other strategy still
rounds down and never lifts to the minimum. The fee preset, the
spread profile, the 40 bps target, the 26 bps cost floor, the
15-minute development window, and the burned test split are
unchanged. Production order submission stays refused.

v0.1.7 placed that stop at 8 bps. The same short was sold at
77180.9 and covered at 77243.9, 78 seconds later. The adverse move
was 8.2 bps, the 8 bp stop. After that print the window's extreme
against the short was 9.9 bps, and the best move in favor was 15.1
bps, which does not clear the 26 bp cost floor. The 15 bp print
arrived after the 180 second clock. v0.1.8 placed a tighter range
stop at 12 bps and held 300 seconds. That short was sold at 77180.9
and covered at 77178.0 on the clock, about 0.4 bp in favor.

Before v0.1.9 was written, the same window's trades were measured.
High 77257.3, low 77064.3, range 25.0 bps. No leg clears 26 bps, so
the 40 bp target cannot fill. On 1-second closes, a lookahead book
that pays the engine's 5 bp taker and the 1 bp research spread, and
that flattens before a 0.5% loss, nets at most 0.168 USDT (0.14%)
at 0.001 BTC and 0.335 USDT (0.28%) at 0.002 BTC. 0.002 BTC is the
largest step whose 12 bp stop plus stressed costs fit in the 0.5%
room on this book. Swings of 8 bp have a median length of 80
seconds. v0.1.9 is frozen before the next measurement. The entry,
the 12 bp stop floor, and the 40 bp target stay. The hold is 90
seconds, so a finished scalp frees the book and the next impulse
can trade inside the window. Size is the largest step inside the
operating-stop room, not the venue minimum alone. Costs, the spread
profile, the window, and the burned test split are not changed.

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
After the book is flat the same arm may fire again. That is the
whole economic rule. It is not a claim that a day of these trades
returns 1.5–2%. The measured ceiling on this window is 0.28% at
the largest legal lot.

## 2. Bar schema and causality

Same 1-second bars as S1. Evaluate at index `t`. Windows end at
`t-1` except the trigger bar's own close, spread, and the momentum
endpoint `close[t]`. No later bar is read. `t < 60`, or a missing
trigger bar, does not fire (`insufficient-history`).

A `None` bar is a quiet second: no trade printed. It is not a veto.
The micro-range and the momentum base use the present prints only.
The range window must contain at least 3 present bars
(`MIN_RANGE_PRINTS`), or the side rejects `insufficient-prints`.
Momentum uses `close[t]` against the latest present close at index
`<= t-5` inside the warmup. Timestamp
disorder still halts. More than 5 consecutive missing seconds still
halts (`outage`). One quiet second does not.

## 3. Frozen parameters v0.1.9

| Name | Value | Meaning |
|---|---|---|
| `WARMUP_N` | 60 | minimum bar index |
| `RANGE_N` | 5 | micro-range, bars `t-5..t-1` |
| `MOM_M` | 5 | momentum lookback |
| `EXTENSION_MIN_BPS` | 0.0 | strict break only: extension must be > 0 |
| `MOM_MIN_BPS` | 2.0 | min 5-second return, same sign |
| `SPREAD_MAX_BPS` | 4.0 | reject a wider trigger-bar spread |
| `STOP_MIN_BPS` | 12.0 | a tighter range stop is placed out to this |
| `STOP_MAX_BPS` | 20.0 | stop wider than this is not a scalp |
| `TARGET_BPS` | 40.0 | target distance from the trigger close |
| `ENTRY_TOL_BPS` | 2.0 | entry band around the trigger close |
| `ENTRY_EXPIRY_S` | 5 | do not chase a stale scalp |
| `HOLDING_LIMIT_S` | 90 | time exit; the next impulse can still trade |
| `MAX_CONSECUTIVE_MISSING_HALT` | 5 | consecutive missing seconds that halt |
| `MIN_RANGE_PRINTS` | 3 | present bars required inside the 5-bar range |

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

1. `close[t] > max(high)` of the present bars in `t-5..t-1`.
2. Extension `(close[t] − ref_high) / close[t] · 1e4 > 0`.
3. Momentum over 5 seconds is at least 2 bps.
4. `spread_bps[t] <= 4`.
5. A range stop tighter than 12 bps is placed at 12 bps. A stop wider
   than 20 bps rejects.
6. Planned reward from the entry bound to the target is at least 26 bps.
   With these constants it is about 38 bps. If a later edit breaks
   that, the side rejects `reward-below-cost` and does not emit.

SHORT mirrors every sign. Opposing fires are left to the selector,
which stands the instrument aside. A later bar may fire again once
the book is flat and the 60 second cooldown has elapsed. Size is the
largest lot step inside the operating-stop room.

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
