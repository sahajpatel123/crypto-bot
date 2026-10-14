# Economic report — integrated release (Checkpoint C)

Code: release main (contract v1, Checkpoint-A integration). Runtime:
Python 3.14.6, NautilusTrader 1.231.0 (locked). This report answers:
what the bot evaluated, why it traded or declined, net results after
each cost, fill modeling, sample size and qualification.

## 1. H-R2 rejected-candidate counterfactuals — REJECTED

Full detail: `outputs/hr2/report.md` (+ `diagnostics.json`,
`portfolio.json`, `extract_manifest.json`). 61 exported candidates
(16 S1, 45 S3): 60 filled/partial, 1 unmarketable, 0 unscorable.
Exits 50 stop / 4 target / 6 time; exit-net mean **−13.04 bps, 0/60
wins**; markouts negative at 30/60/120/300 s; portfolio overlay
(1-position + 300 s cooldown) 5 admitted, −63.49 bps. Costs: 5 bps/leg
labeled fees; spread/slippage zero-added (in touch fills/arrival);
funding excluded (≤0.01 bp bound). Verdict: no executable edge; the
cost floor correctly rejects. These are counterfactual diagnostics,
never P&L.

## 2. Bounded round REL-R1 — design (frozen 2026-10-14T06:10:46Z)

Spec: `trials/rel-round-01.json` + `rel-round-01.params.json`, configs
`configs/rel-r1/REL-*.toml`. Six predeclared S1/S2 configs (frozen
ROUND-01 params, 120 s horizon) + CASH, selected before viewing any
arm backtest outcome:

| Config | Arm | Mechanism |
|---|---|---|
| REL-S1 | S1 | Unchanged control: breakout continuation |
| REL-S1-V | S1-V | Volatility-conditioned (vol_z ≥ 1.0, 60-bar) |
| REL-S1-F | S1-F | Flow-regime (10-bar buy_frac ≥ 0.58) |
| REL-S2 | S2 | Unchanged control: trend pullback/resumption |
| REL-S2-V | S2-V | Volume-confirmed resumption |
| REL-S2-F | S2-F | Flow-regime resumption |

A 300 s-horizon arm was considered and rejected at design time (new arm
IDs would break frozen ROUND-01/contract pins) — predeclared, not
post-hoc. Stops/targets are setup invalidation and measured
opportunity, never moved to satisfy the cost floor.

Chronological dev (cap-30min) / validation (cap-2h), fresh Session per
cell (full purge), causal warmup. Selection rule (mechanical): advance
at most one config with dev_net > 0 AND validation_net > 0 (full
costs); highest validation net wins; ties by dev net, then config_id.
Otherwise advance NONE and end REJECTED. Prior-use disclosure: these
arms were defined/selected in prior rounds on overlapping captures —
any positive dev/validation result carries a disclosed selection
effect; only the untouched evaluation would be selectable evidence.

## 3. REL-R1 cell results (dev + validation)

Evidence: `reports/rel/rel-r1/*.comparison.json` (8 mechanism cells).
Dev = cap-30min (1,129,445 events/cell); validation = cap-2h
(2,838,861 events/cell). All cells rc=0 under the round gate
(`sha=f08fa9c507a5ef17`).

| Config | Split | Admitted | Fills | Net | Rejection attribution |
|---|---|---|---|---|---|
| REL-S1 | dev | 0 | 0 | 0.00% | floor rejected 12; gates rejected the rest |
| REL-S1-V | dev | 0 | 0 | 0.00% | floor 7; confirm-gate 5; gates rest |
| REL-S1-F | dev | 0 | 0 | 0.00% | floor 9; confirm-gate 3; gates rest |
| REL-S2 | dev | 0 | 0 | 0.00% | no setups fired (trend/sequence gates) |
| REL-S2-V | dev | 0 | 0 | 0.00% | no setups fired |
| REL-S2-F | dev | 0 | 0 | 0.00% | no setups fired |
| REL-S1 | validation | 0 | 0 | 0.00% | floor rejected 4; gates rest |
| REL-S2 | validation | 0 | 0 | 0.00% | no setups fired |
| REL-CASH | — | 0 | 0 | 0.00% | reference zero (by construction) |

Variant validation cells (S1-V/S1-F/S2-V/S2-F on cap-2h) were not run:
each variant's gates are a strict superset of its family control's, so
its admitted set is provably ⊆ the control's admitted set = ∅ on the
same data (dev confirms the subset: 7,9 ≤ 12 floor-rejects). Stated
before validation ran; if either control had admitted > 0, its
family's variants would have been run.

Selection-rule outcome: no config has dev_net > 0 → **advance NONE,
round REJECTED**. No adverse-sensitivity rerun applies (sensitivity is
for selected candidates; none selected). Win rate / expectancy /
profit factor / drawdown are undefined on zero trades and are reported
as such, not imputed. Turnover 0, fees paid 0, funding 0.

## 4. Costs, fills, attribution

Fills: Nautilus paper engine, IOC at touch inside the protected band;
arrival = first bookTicker at/after evidence; $20-notional unit sizing
(H-R2 diagnostic) / risk-sized quantities (REL-R1 cells, ≤0.125%
planned risk, ≤3x, one position). Fees 5 bps/leg labeled schedule
(account-specific rates unavailable); spread implicit in touch fills,
never double-charged; funding excluded with stated bound (no funding
channel in captures). Fill rate, turnover, holding periods, drawdown
and concentration reported per cell in §3 (all zero-trade cells report
rejection attribution instead — floor vs gate).

## 5. Qualification screen — DATA BLOCKED (untouched leg)

The screen (≥100 closed out-of-sample positions / ≥10 days + positive
net under realistic/adverse costs) is preserved, not lowered. No
suitable untouched tick data exists: cap-30min/cap-2h are development
knowledge; cap-48h-90s/smoke-60s/agreement-30s are 30–90 s long
(shorter than warmup+hold); bench30d has prior use and is quote-less
(spread assumption, unsuitable for 1 s IOC validation); no funding
channel anywhere. Required to unblock: ≥10 days of tick data nobody
has used — bookTicker (or depth deltas) + aggTrades + markPrice at ≥1 s
resolution, funding rates, exchange event time + receipt time +
sequence IDs. Verified available source for part of this: Binance
public vision archive (aggTrades + 1m klines only — no historical
book). Full 1 s book history is not publicly available post-hoc; a new
forward capture of ≥10 days (continuous capture job) is the exact
remaining dependency.

## 6. Strategy verdicts (per family)

| Family | Verdict | Basis |
|---|---|---|
| S1 breakout momentum | **REJECTED** (this round) | 0 admits on dev + validation; 16 setups reached the cost floor across windows and were correctly rejected (targets below costs); confirmation variants admit ∅. Consistent with H-R2 (0/60 counterfactual wins). |
| S2 trend pullback | **REJECTED** (this round; economics unmeasured) | Zero setups fired on either window (trend/sequence gates) — not measured-negative but unevaluable here; fails the positive-net selection rule either way. |
| S3 range/VWAP reversion | **UNQUALIFIED** (diagnostic complete) | H-R2: all 45 S3 targets below the fee assumption; 0 counterfactual wins. No redesign attempted this round (out of scope per §6 table). |
| S4 failed-breakout reclaim | **INSUFFICIENT** | Implementation retained; no qualifying evidence gathered this round (not in the bounded 6). |
| S5 order-flow continuation | **INSUFFICIENT** | Eligible only with synchronized book/flow history + own evaluation; not in the bounded 6. |

Overall economic result: **no strategy qualifies for real capital**.
The round is complete (hypothesis rejected with measured reasons),
the untouched-evaluation leg is DATA BLOCKED (§5), and no further
cycling is permitted to conceal the result. The release ships as a
functioning application with a rejected/insufficient economic result.
