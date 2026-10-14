# Session/adapter contract v1 (manager decision, release assignment §3-§4)

Status: BINDING on W1/W2 from dispatch. Changes require manager approval.
Runtime: Python 3.14.6 (locked env). Nautilus 1.231.0.

## 1. Responsibility split

- Session owns the trading lifecycle and is the ONLY booking path into
  the application ledger/risk. Adapters own transport + simulated venue
  behavior, emit normalized execution events, and never mutate app state.
- One accounting owner: fill identity → ledger effect → reservation
  transition → protection/exit follows ONE idempotent handler:
  `Session._apply_engine_event` (name fixed by this contract).

## 2. Adapter surface (`app/engine.py`)

- `open_orders()` returns CURRENTLY-OPEN/PARTIAL bot orders ONLY, on
  every adapter. Paper changes to filter terminal states. A missing
  order here proves nothing about cancellation, fills, or flatness.
- `order_status(client_id)` (NEW): tracked truth including terminal
  and `unknown` states; `None` only when never seen. Both adapters.
- `unknown_ids()` (NEW on protocol; live already has it): ids needing
  lookup/reconciliation. Paper returns `()` (documented: no unknowns).
- `EngineOrderStatus` gains `version: int` (default 0): adapters bump
  it on every per-order transition; Session applies only versions
  strictly newer than last applied. Never deduplicate updates by bare
  client ID; cumulative filled quantity never rolls back.
- `poll()` drains events emitted before a sink was bound (bounded).
  Steady-state delivery is push (see §3).
- `AccountSnapshot` (NEW) + `account_snapshot()` (NEW): named wallet
  equity, available margin, margin balance, timestamped positions with
  a `complete` flag. New code uses this; the `account_margin()` tuple
  stays for compatibility and must not gain new callers.
- `bind_sink(handler)` (NEW on protocol): registers the Session
  handler. Adapters invoke it on EVERY emission: user-stream fills,
  lookup-adopted fills, recovery-adopted fills, simulated callbacks.
  No second booking path anywhere.

## 3. Event flow (both adapters, identical)

Adapter emission → bound Session handler → idempotent ledger/risk
application keyed by namespaced `execution_id`:
- live: `binanceusdm/{account_tag}/{SYMBOL}/{venue_trade_id}`
- paper: `paper/{run_id}/{SYMBOL}/{seq}`
- reference: `reference/{run_id}/{SYMBOL}/{seq}`

Session keeps max-applied cumulative qty per order; stale/duplicate
events are no-ops (logged at debug, counted). Fees/funding reconcile
from venue truth; never estimated.

## 4. Recovery and durability (`app/store.py`, W1)

- One SQLite writer; persist command intentions + normalized execution
  events BEFORE acknowledging application processing; one transaction
  where applicable; never hold a transaction across network I/O.
- Single-instance/account lock; crash-consistent cursors; versioned
  reader + backup; refuse unsafe state (no guessing).
- SQLite: WAL + `synchronous=NORMAL` documented as process-crash safe;
  power-loss guarantee called out as NOT claimed without FULL + tested
  media. Record the chosen mode in the release config.
- Possibly-executed commands reconcile by durable client ID before any
  resubmission; rate-limit backoff protects cancel/reduce capacity.

## 5. Forbidden

- A second ledger or a second booking path; paper/live behavior splits.
- Deleting safety checks to "complete" the prod route (prod wiring is
  manager-owned, default-off submission stays).
- Weakening tests, cost gates, risk controls, or deadline assertions
  to obtain passes/trades.
