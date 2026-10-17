# STATE — live/hardening (principal-engineer takeover)

Branch: `live/hardening` from `deep/integration` @ `e766383`.
Mission: research harness (2/10 for live capital) → hardened, validated,
gated, ready for a *supervised small-capital live trial*; find out honestly
whether any strategy has a real fee-inclusive edge. A rigorous negative
result plus a hardened system is success. Priority: money-handling
correctness > validation integrity > features.

## Task list

| ID | Task | Status |
|---|---|---|
| T0.1 | Baseline targeted tests + this file | DONE |
| T0.2 | Consolidate F2 health recovery + F-SIZING-01 (+ client-ID if present); restore F2 tests; prove `_release_exit_only` callers | DONE |
| T0.3 | ruff + mypy configs (strict on risk/execution/adapters/app) + CI | TODO |
| T0.4 | Truth-in-docs (doctor, run_live docstring, README E-007, prod.toml) | TODO |
| T1.1 | Venue-seeded accounting + account-mode verification (fail closed) | TODO |
| T1.2 | Hot path: cached account snapshot, debounced risk writer, weight governor, benchmark | TODO |
| T1.3 | Table-driven exception policy + safe mode; one order-lifecycle path | TODO |
| T1.4 | Protection window: parallel stop/target, shadow stop, fault injection | TODO |
| T1.5 | SIGTERM/SIGINT flatten by default; `--leave-protected` opt-out | TODO |
| T1.6 | Client IDs: UUID run prefix + persisted monotonic seq, ≤36 chars | TODO |
| T1.7 | Settled funding booked in ledger, reconciled vs venue | TODO |
| T1.8 | Tiered maintenance margin / liquidation gate + min-viable-equity calc | TODO |
| T1.9 | Pessimistic paper fills (book-walk + latency penalty); 1x/2x cost P&L | TODO |
| T2.1 | Ingestion/strategy decoupling, drop accounting + breaker | TODO |
| T2.2 | Honor `max_hf_subscriptions` (BTCUSDT, ETHUSDT default) | TODO |
| T2.3 | `cryptobot latency-probe` (gate: p99 feed age <250ms, drops <0.1%) | TODO |
| T2.4 | 5x-burst soak test (bounded memory, drop budget) | TODO |
| T3.1 | systemd unit + Dockerfile, crash-loop breaker, resume-on-restart | TODO |
| T3.2 | External watchdog (flatten on stale heartbeat + exposure) | TODO |
| T3.3 | Pluggable alerts (rate-limited, fake-sink tested) | TODO |
| T3.4 | JSON logging + rotation, metrics export, FULL-sync cost report | TODO |
| T3.5 | `cryptobot data verify`; gz replay docs | TODO |
| T4.1 | Fixture recorder (redacted) + recorded-fixture contract tests | TODO |
| T4.2 | `cryptobot demo-drill` (hashed JSON report) | TODO |
| T4.3 | OWNER_ACTIONS.md (exact commands + expected outputs) | TODO |
| T5.1 | Cost model v2 + break-even / required-win-rate tables | TODO |
| T5.2 | Maker-capable replay/paper execution (conservative queue model) | TODO |
| T5.3 | Hypothesis registry ≤6, preregistered + committed pre-evaluation | TODO |
| T5.4 | Evaluation protocol (walk-forward, purge/embargo, bootstrap, Holm) | TODO |
| T5.5 | `cryptobot verdict` PASS/FAIL/UNDERPOWERED JSON (hash-bound) | TODO |
| T5.6 | ≥14d pessimistic paper if any PASS | TODO |
| T6.1 | `cryptobot gate` + `cryptobot arm` two-step prod enablement (built OFF) | TODO |
| T6.2 | Capital ladder + automatic demotion/halt | TODO |
| T6.3 | Live canary: first N trades at minimum size | TODO |

Status values: TODO / IN_PROGRESS / DONE / BLOCKED / PARTIAL.

## T0.1 baseline (verified 2026-10-17, this session)

Command:
`nice .venv/bin/python -m pytest tests/unit/test_binance_live_contract.py
tests/unit/test_binance_live_v008.py tests/unit/test_execution_orders.py
tests/unit/test_execution_e2e.py tests/acceptance/test_ledger.py
tests/acceptance/test_risk_sizing.py tests/acceptance/test_risk_v008.py -q`
→ **81 passed in 2.91s**. `tests/unit/test_session_health_recovery.py` does
NOT exist on `deep/integration` (confirmed: `file or directory not found`) —
it is the missing F2 test to restore in T0.2.

## Audit-claim verification (code-checked before fixing)

1. Ledger seeded from config even live — **CONFIRMED**:
   `src/cryptobot/app/session.py:188` `Ledger(config.paper_capital_usdt)`;
   `configs/prod.toml:16` `paper_capital_usdt = 120.0` ("NOT live equity").
   Venue seeding: only via periodic `_snapshot_account()` (session.py:2757);
   no startup wallet/position/order seeding found.
2. Signed REST on hot path — **CONFIRMED**: `binance_live.py:625,1307,1315,
   1388,1416` call `_signed("GET","/fapi/v2/account")`; account view at
   :1307 explicitly "no cache". Fsync-per-tick claim: risk-state writer to
   verify in T1.2.
3. Venue exceptions kill process — **PLAUSIBLE, to pin in T1.3**: Session has
   `_exchange_errors` counter (session.py:215) but no safe-mode flatten path
   found on the live driver; classification table absent.
4. No atomic bracket / protection window — **TO VERIFY in T1.4** (entry →
   `attach_protection` sequencing in `app/engine.py`, `app/reference.py`).
5. SIGTERM does not flatten — **CONFIRMED**: `cli.py:121-126` handler only
   sets `session._stop_flag = "graceful"`; no flatten/confirm path.
6. No maintenance-margin/liquidation model — **CONFIRMED** (no
   `leverageBracket`/liquidation-price code in risk/; verify in T1.8).
7. Feed drops / `max_hf_subscriptions` unused — **TO MEASURE in T2.1/T2.2**
   (config declares `max_hf_subscriptions = 2` in paper/prod/demo tomls;
   subscription path to trace).
8. Client-ID collision — **CONFIRMED for live engine**:
   `binance_live.py:249` default `run_tag="bl"`, `:650-653`
   `f"{run_tag}-{seq:06d}-{rand16}"` with per-process `seq` and only 16 bits
   of randomness → collisions across restarts are likely. (`OrderManager`
   at `execution/order_manager.py:132-135` uses 8 hex chars — better, still
   per-process seq.) No run-unique UUID prefix, no persisted seq.
9. F2 + F-SIZING-01 unmerged — **CONFIRMED**: `fix/f2-health-recovery`
   (`eb0cfe1`) and `integration/owner-exec` (`21e21a4` merge, `a576e73`
   sizing clamp) are not ancestors of HEAD. On HEAD,
   `session.py:2757-2759` still latches health once (`_halt_entries` with no
   release); `risk/sizing.py:93` still `stressed = sum(legs)/10000*...`
   unclamped (negative funding credit enlarges size).
   `_release_exit_only` (session.py:1494) has **zero production callers** on
   HEAD — only `tests/unit/test_rev2_stream_ownership.py:644`.
10. Live funding never booked — **PARTIAL**: `ledger.py:169-180`
    `record_funding`/`note_funding` exist and `binance_live.py:1399-1404`
    sums `FUNDING_FEE` income, but no live-path caller books settled funding
    into the ledger (to pin in T1.7).
11. Zero-slippage paper fills — **CONFIRMED**: `paper_engine.py:223`
    `FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, ...)`.
    `OrderManager.submit_with_retry` (`order_manager.py:159`) is the tested
    retry path; live path uses `BinanceLiveEngine.submit` directly — retry
    logic not wired into live (T1.3).

Also: no `.github/` CI on HEAD; no ruff/mypy config in `pyproject.toml`
(dev extra is pytest only). Working tree carries uncommitted pivot work
(`tools/pivot_*`, `tests/unit/test_pivot_*`, `data/pilot/`, `reports/pivot/`)
that predates this branch — left untouched, never committed as own work.

## Decisions

- D-H1: Branch `live/hardening` created from `deep/integration` @ e766383;
  commit per task with task ID (explicitly directed by the takeover
  protocol). No push without explicit ask. `deep/sc-scalp` never merged
  (negative evidence).
- D-H2: `data/captures/campaign-1day-20261017` is never read/touched
  (untouched confirmation data, live campaign running). Dev data:
  `data/pilot`, `datasets/benchmark_30d`; log every use in
  `research/DATA_LEDGER.md`.
- D-H3: Prod submission stays OFF by default; P6 builds the arming path
  only. Gate thresholds are never lowered to pass; any change needs a
  written justification in DECISIONS.md.

## T0.2 consolidation (DONE)

Reproduced on HEAD before fixing (branch tests run against e766383):
F2 file → 6 failed/1 passed (stale latch never releases; entries never flow
after mark recovery); sizing file → 2 failed/2 passed (−25bps funding credit
sized qty×stop = 33.6 USDT vs 12.5 budget). Cherry-picked `eb0cfe1`
(F2, → b686d0b) and `a576e73` (F-SIZING-01, → b87ee9a); after: both files
11 passed; targeted regression (session×4 + sizing×3 + execution) 84 passed.
`_release_exit_only` production callers now: `_apply_health_gate`
(session.py:1569) ← `_health_tick` (:1585) ← event path (:2832). No
client-ID work exists on `integration/owner-exec` (diff of
binance_live.py/order_manager.py vs e766383 is empty) → client IDs are
T1.6. `docs/f2-health-recovery.md` came with the F2 cherry-pick.

## Commands run

- `git switch -c live/hardening` (from deep/integration @ e766383)
- targeted baseline above → 81 passed
- T0.2: `pytest /tmp/test_session_health_recovery.py` → 6F/1P on HEAD;
  `pytest tests/acceptance/test_sizing_funding_clamp.py` → 2F/2P on HEAD;
  after cherry-picks → 11 passed; regression set → 84 passed

## Open risks

- R-1: Full suite (~16 min, ~1420 tests) not yet run on this branch;
  schedule at end of P0.
- R-2: Pivot working-tree changes may interact with suite runs (pivot
  tests present); keep them out of hardening commits.
- R-3: No credentials available (by design) — all venue-behaviour claims
  must be proven on the sandbox venue / recorded fixtures; live claims
  become OWNER_ACTIONS.md entries.
