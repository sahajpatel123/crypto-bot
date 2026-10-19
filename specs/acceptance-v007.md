# V-007 verification record (backtest order, Worker 3 share)

Owner: Worker 3 (cool-amalthea). Base `fd9f83b`, branch `worker3/v-007`.
Contract: v0.2.0 + `specs/backtest_interfaces.md` B1/B8/B9 + the directive
metric table (`Muse_Crypto_Backtest_and_Performance_Plan.md`).

## Per-acceptance-item verdicts

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | B8 ack verification: risk publishes required position quantity for protection/stop verification | PASS | `Approved.required_stop_qty` + `Reservation.qty` (persisted) + `RiskPolicy.required_stop_qty()` live/unresolved/unknown/legacy; 5 tests |
| 2 | Protection/margin/funding invariants hold in the backtest path | PASS | margin-from-sim determinism (3 tests) + funding→floor arm/halt pair (2 tests) + delta idempotence |
| 3 | Independent reconciliation: rebuilt totals agree with the persisted ledger or the build fails | PASS | 7-check `reconcile()` (fees, funding, realised, episode-fees, cash, equity-cash, equity-position); raises `ReconciliationError`; corrupt/dropped-episode tests |
| 4 | `reporting/` package: summary.json + trades/equity/daily-returns/rejections CSVs + standalone report.html from run files | PASS | `cryptobot.reporting.build_report()`; strict B9 loaders; 40 new tests; sample build below |
| 5 | report.html covers the directive metric table with labeled gaps, no estimates | PASS | first-page answers, 4 inline-SVG charts (no CDN/JS), expectancy CI, splits, reliability, methods; unobservables labeled (strategy/exit reason, execution effects, speed) |

Frozen `tests/ceo_review/test_ceo_finding_*` record tests: unbroken (full
suite green, no edits to those files).

## Reconciliation proof (sample build)

Synthetic run `tests/fixtures/v007_run` (1 episode: LONG 1.0 BTCUSDT
@100 → 0.4@110 + 0.6@108, fees 3.0, funding −0.5, deposit +100):

- Episode net 5.3 == ledger realised 5.3; net return 0.00053; status
  `agree` on all 7 checks (fees, funding, realised, episode-fees,
  cash, equity-cash, equity-position).
- Profit factor labeled `undefined: no losing episodes`; expectancy
  labeled `insufficient: n<30`; splits `unassigned: no splits declared`.
- report.html: 4 inline `<svg>` charts, zero `http`/`<script>`/`src=`/
  `href=` references; byte-identical across rebuilds.

## Run-file schemas consumed (frozen, main `fd9f83b`)

`Session._append_run_file` docstring: fills {execution_id,
client_order_id, instrument, side, qty, price, fee, liquidity, ts_utc};
rejections {ts_utc, stage, reason, strategy, instrument, side}; risk
{ts_utc, kind, from_state, to_state, reason}; equity {ts_utc,
marked_equity, cash, position_qty, position_symbol, open_pnl, source};
plus ledger.json / config.toml / dataset_manifest.json. Identity resolves
config-first, manifest-second. B3 (live-loop heartbeats) touched no run
schemas — verified by diff.

## Flagged gaps (labeled in every report, not estimated)

- Fills carry no strategy tag → episodes attribute the run-level config
  strategy (else "unknown", labeled).
- Fills carry no exit reason → non-terminal closes report "unknown"
  except labeled end-of-data closes; MFE/MAE need bar data (null).
- Execution effects (slippage vs arrival) unobservable from run files;
  speed/resource timings reported only when recorded (currently not).
- Close costs excluded from returns; ending open exposure is shown
  marked, not liquidated.

## Manager-verifies-at-integration items

- `required_stop_qty` / `Reservation.qty` persistence compatibility
  ruling (state v2 carries `qty`, legacy files load as None).
- Same-drawdown contrast note: the funding→floor pair uses +150/−100
  (funded, halts on profit-protection) vs −50 (control, no arm, ok);
  the control move is smaller so it stays above the daily-loss halt and
  isolates the floor arm as the halting cause.
