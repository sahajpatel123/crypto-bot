# Observed return evaluation — method + record (Worker 1, Q-006)

Status: METHOD FROZEN (sections 1–5 written before any return was scored);
results in section 6. Promotion: NONE — descriptive only, like EXP-001..004.
Layer separation: (1) signal mechanics = existing runner metrics (cost
exposure only); (2) observed replay economics = this document (closed
trades on replayed bar paths); (3) forward paper = NOT RUN (pending
E-007/V-006 integration; no paper claims are made here).

## 1. Why new splits

SPLIT_AUDIT.md finding 3: the preregistered 70/5/25 splits carry a 12-bar
embargo, far short of the 135-bar outcome horizon (`holding_limit_s` 120 +
`entry_expiry_s` 15). Return scoring on those splits would leak outcomes
across the train/validation boundary. The frozen EXP-003/004 manifests are
executed unchanged for signal mechanics; return evaluation uses separate
purged geometry defined below. Fixture inputs stay `SYNTH_V1` labelled
synthetic; nothing here is market data.

## 2. Geometry (all in bars = seconds, 1 s grid)

- `N_BARS = 600`, `WARMUP = 120`, `MAX_HORIZON = 135` (120 + 15).
- Train scored: `[120, 240)`. Purge: `[240, 375)` (135 bars, unscored).
  Validation scored: `[375, 465]`. Tail `(465, 600)` is outcome room only.
- Every scored signal satisfies `t + 135 <= 600`, so every entry/exit
  decision lands inside the fixture; no open-at-boundary interpolation.
- Train outcomes may extend into the purge (that is its purpose) but can
  never reach validation (`240 + 135 = 375`). Validation outcomes extend
  into the unscored tail. History reads across boundaries are causal
  (past bars only) and permitted.
- Holdout: separate pinned seeds (never train/val seeds), scored exactly
  once over `[120, 465]` as one region (outcomes to 600), no tuning.

## 3. Seeds and scenarios

- Same scenarios as the parent EXP (S3/S4 long/short + flat/choppy
  controls); same `SYNTH_V1` generator with `n_bars=600` (event placement
  unchanged: S3/S4 events at bars 150–220 fall in train; validation is a
  quiet-hold control measuring false-positive economics).
- Train/val seeds: the preregistered sets (S3: 51–53 / 61–62; S4: 71–73 /
  81–82). No seed-picking: identical seeds, longer bars.
- Holdout seeds (pinned here, scored once, reported as-is): S3 {91, 92},
  S4 {93, 94}.

## 4. Closed-trade model (labelled `conservative-simulation`)

Paper-policy surface mirrored from `app_runtime_interfaces.md` S3/S4:
nonzero fill delay (entry strictly after the signal bar), limit-touch
entrybox, reduce-only stop/target/time exits, modelled commission via the
frozen `NET_S1_V1` haircut. Approximations are labelled, not hidden.

- Stops/targets per signal: `stop = intent.invalidation_price`;
  S4 arms `target = close[t] ± 1.5R`, `R = |close[t] − inval|` (matches
  the S4 exit policy); S3 arms `target` = range mid recomputed over
  `bars[t-63..t]` (matches S3.md §5 mid target); time exit at `t + 120`.
- Entry: first present bar `j` in `(t, t+15]` whose `[low, high]` touches
  `[entry_low, entry_high]`; fill `entry_px = close[j]`. No touch within
  15 s → `expired` (counted, no trade, no imputed fill).
- Exits scanned from `j` to `t+120` on bar `high/low/close`: long stops
  when `low <= stop`, targets when `high >= target`; short mirrored.
  Same-bar stop+target → stop wins (conservative). Time exit fills at the
  `t+120` close when neither level traded first.
- `gross_bps = side · (exit − entry) / entry · 1e4` (fills at close = mid
  proxy). `cost_bps = 26.0` (`NET_S1_V1` round-trip `2·(5+5)+5+1`,
  covering fee + slippage + spread + funding). `net_bps = gross − cost`.
- Missing (`None`) bars are skipped in scans (no touch, no fill); the
  S3/S4 scenario sets contain no gaps, so this path is defensive only.

## 5. Metrics and reporting

Per arm × split: `n_signals`, `n_entered`, `n_expired`,
`n_stop/n_target/n_time`, `gross_total/mean_bps`, `net_total/mean_bps`.
Zero-trade cells are reported as zero, never dropped. Negative findings
are kept verbatim; no arm, seed, or parameter may be promoted from these
numbers. Repro: `python -m cryptobot.research.returns --exp EXP-003
--out <dir>` (then `EXP-004`); outputs `trades.jsonl` + `summary.json`
per experiment, with fixture hashes and split ranges per trade.

## 6. Results (appended after the frozen method ran unmodified)

Run: `python -m cryptobot.research.returns --exp EXP-003 --out
/tmp/exp006/returns` then `--exp EXP-004` (single run each; holdout scored
once alongside, no tuning). Method sections 1–5 unchanged since freezing.
Per-trade records with fixture hashes: `trades.jsonl` beside each
`summary.json`. Costs in bps; `net = gross − 26.0` (`NET_S1_V1`).

### EXP-003 (S3 arms × 4 scenarios × 8 seeds; 810 signals, 810 entered)

| Arm × split | n_sig | stop/tgt/time | gross tot | net tot | gross mean | net mean |
|---|---|---|---|---|---|---|
| S3 × train | 162 | 0/0/162 | +2046.0 | −2166.0 | +12.63 | −13.37 |
| S3 × validation | 0 | 0/0/0 | 0.0 | 0.0 | — | — |
| S3 × holdout | 108 | 0/0/108 | +1364.0 | −1444.0 | +12.63 | −13.37 |
| S3-R × train | 162 | 0/0/162 | +2046.0 | −2166.0 | +12.63 | −13.37 |
| S3-R × validation | 0 | 0/0/0 | 0.0 | 0.0 | — | — |
| S3-R × holdout | 108 | 0/0/108 | +1364.0 | −1444.0 | +12.63 | −13.37 |
| S3-C × train | 162 | 0/0/162 | +2046.0 | −2166.0 | +12.63 | −13.37 |
| S3-C × validation | 0 | 0/0/0 | 0.0 | 0.0 | — | — |
| S3-C × holdout | 108 | 0/0/108 | +1364.0 | −1444.0 | +12.63 | −13.37 |

Reading (descriptive, promotion NONE): all three S3 arms fire identically
on these fixtures (filters bind nothing — same as the signal-mechanics
leg: 32/32 per arm). Every trade exits on time: the +30 bps mid target is
never reached by the +13 bps constructed drift, and the stop never
trades. Gross positive, net negative after the 26 bps haircut on every
cell. Validation (quiet hold) fires zero — a clean no-false-positive
control, not a scored return cell.

### EXP-004 (S4 arms × 4 scenarios × 8 seeds; 445 signals, 445 entered)

| Arm × split | n_sig | stop/tgt/time | gross tot | net tot | gross mean | net mean |
|---|---|---|---|---|---|---|
| S4 × train | 30 | 0/12/18 | +142.4 | −637.6 | +4.75 | −21.25 |
| S4 × validation | 0 | 0/0/0 | 0.0 | 0.0 | — | — |
| S4 × holdout | 20 | 0/8/12 | +94.9 | −425.1 | +4.75 | −21.25 |
| S4-S × train | 237 | 75/144/18 | +944.7 | −5217.3 | +3.99 | −22.01 |
| S4-S × validation | 0 | 0/0/0 | 0.0 | 0.0 | — | — |
| S4-S × holdout | 158 | 50/96/12 | +629.8 | −3478.2 | +3.99 | −22.01 |

Reading (descriptive, promotion NONE): the pierce requirement cuts S4
volume ~8× vs S4-S with a slightly better per-trade gross (+4.75 vs
+3.99). Both arms are net negative in every scored cell after costs;
S4-S pays more total cost via volume. Zero expiries in both EXPs (the
2 bps entry box always touches within 15 s on 1 s bars). Validation
fires zero for both arms (quiet-hold control).

### Signal-mechanics leg (frozen manifests, for the joint record)

`python -m cryptobot.research.runner --exp EXP-003 --out /tmp/exp006`:
60/60 ok, 0 failed. `--exp EXP-004`: 40/40 ok, 0 failed. Totals:
EXP-003 S3/S3-R/S3-C = 32 long + 32 short each; EXP-004 S4 = 12 + 12,
S4-S = 67 + 69. Logs: `/tmp/exp006/EXP-003|004/trials.jsonl` with
manifests, fixture hashes, split ranges; reconciliation `missing: []`.
Forward paper: NOT RUN (no claim).
