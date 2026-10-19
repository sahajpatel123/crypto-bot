# Interface review: Q-001 / E-001 vs CONTRACTS v0.1.0 (V-001)

Reviewer: Worker 3 (cool-amalthea). Scope is read-only review; no reviewed
file was modified. E-001 reviewed at merged main `9ab5a01`
(`src/cryptobot/execution/*`, identical to `worker2/e-001` tip — verified
zero diff). Q-001 reviewed at `worker1/q-001` (tip `c66aca1`).

## E-001 execution interface — conformances

- C-E001-01 Client-ID ownership: `new_client_id()` unique incl. across
  restarts (uuid suffix); fake venue treats duplicate IDs idempotently (no
  duplicate order). Contract: satisfied.
- C-E001-02 Entry expiry: `poll()` cancels/expires `role == "entry"` orders
  past `expire_at_utc`. Satisfied.
- C-E001-03 Partial fills: PARTIAL state with `filled_qty`/`avg_price`;
  venue `settle()` advances programmed fractions. Satisfied.
- C-E001-04 Siblings: stop/target submitted and reconciled independently, no
  atomic-bracket assumption; first-fill cancels the other leg with
  verification. Satisfied.
- C-E001-05 Ambiguity: `submit_with_retry` reconciles before every retry and
  retries only under a NEW id when the venue never saw the order; venue-owned
  orders are adopted, never duplicated. Satisfied.
- C-E001-06 Restart recovery: `recover()` rebuilds from the append-only log
  and reconciles every non-terminal order. Satisfied (see F-E001-02 window).
- C-E001-07 Exit-only mode and injectable clock; fault injection covers
  timeout (received True/False), reject, partial — all deterministic, no
  randomness. Satisfied.

## E-001 findings (ordered by severity)

- F-E001-01 Contract gap — risk→execution handoff unspecified (needs manager
  call, recorded as U-002 in `specs/acceptance-risk.md`). The v0.1.0 contract
  defines `Approved(reserved_risk, size)` but no reservation key travels into
  `submit_entry(symbol, strategy_side, qty, price, ...)`, and no
  fill/cancel/expire outcome flows back into risk to release the reservation;
  likewise there is no defined risk-halt → execution exit-only signal (the
  `exit_only` flag exists but nothing sets it). The V-001 policy returns
  `reservation_id` as a compatible superset. Recommend a v0.1.1 addendum:
  thread `reservation_id` through submission, define outcome callbacks
  (fill/cancel/expire/release), and define the halt → exit-only signal.
- F-E001-02 Crash window between venue submit and log append (low for M1,
  must-fix before any real venue). `_submit` calls `venue.submit`, then
  `_log` (append, no fsync). A crash in between leaves a live venue-side
  order that `recover()` can never see (it only knows logged IDs), so the
  orphan is never reconciled. Suggest fsync on append (as the V-001 risk
  state does) plus a startup sweep for venue-side unknowns.
- F-E001-03 Dead line in `recover()`: `manager._seq = max(manager._seq, 0)`
  is a no-op; cross-restart ID uniqueness actually comes from the uuid
  suffix, so behaviour is correct — remove or restore-from-log for clarity.
  Nit.
- F-E001-04 Fake-venue zero-price fill (nit): `_ref_price` returns `0.0`
  when no price/last-price exists, so a direct `MARKET` submit with no
  `set_last_price` fills at 0.0. Unreachable via `OrderManager` today
  (entries are LIMIT with price); suggest a guard raising instead. Nit.
- F-E001-05 Expiry covers `role == "entry"` only; stop/target legs never
  expire. Fine for M1; note for live.

## Q-001 strategy interface — nothing to review yet

`worker1/q-001` contains no worker files (branch tip == base `c66aca1`;
`specs/strategies/` empty on main). No interface exists to check. When Q-001
lands, Worker 3 will verify, in this order: (1) every emitted intent
validates against `cryptobot.coordination.Intent` (bounds, invalidation side,
`evidence_ts <= expiry`, `holding_limit_s > 0`); (2) intents immutable after
creation; (3) each intent's `evidence_ref` resolves to a `DecisionRecord`
with matching side and non-empty regime/features/trigger; (4) long/short
evidence separated; (5) no hand-assigned confidence percentages; (6) replay
fixtures reproduce byte-identical intents (determinism). Repro:
`pytest -q tests/unit/test_strategies_*` plus the V-001 acceptance suite for
the risk-side intake.

## Coordinator (manager-owned, informational — not edited)

`Coordinator.select` matches its contract: halt-quality and expired intents
filtered, same-symbol/same-direction deduplicated to a single owner,
opposing signals stand aside. Selection is deterministic for a fixed input
order (picks the first valid intent's key group).

## Independent reproduction plan (for another worker)

1. Check out `worker3/v-001` (or a tree containing it merged over main
   `9ab5a01`), activate `.venv`, run `pytest -q tests/acceptance` — expect
   34 passed. 2. Re-run to confirm byte-identical state files are not
   required across runs (tmp-state) but each run is internally deterministic
   (`test_determinism.py`). 3. Reproduce one halt-persistence case by hand:
   copy `tests/fixtures/risk_state_crash.json` to a scratch path, construct
   `RiskPolicy` on it, evaluate any healthy intent — expect
   `halt:daily-loss`. No network, credentials, or randomness involved.
