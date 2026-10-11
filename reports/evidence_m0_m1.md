# Evidence report — M0 dispatch + M1 manager scaffold (11 Oct 2026)

Manager: young-polaris. Contract: v0.1.0. Mode: replay/simulation only. No live orders.

## Milestone and runnable capability

- M0: environment inspected (empty workspace, no git); repo initialised on main;
  shared contracts, decisions, task board and inbox/outbox protocol live; all
  three first tasks dispatched via verified native messaging + durable inbox files.
- M1 (manager scaffold, synthetic only): `tools/m1_vertical_slice.py` runs
  metadata → replay → S1 stub intent → coordinator → risk stub → fake venue →
  ledger → report, with one rejected stale intent and one ambiguous-order
  reconcile-before-retry recovery (single fill, no duplicate exposure).
  This is mechanics scaffolding, not a validated trading system.

## Worker status and accepted changes

- Worker 1 whisper-redshift (Q-001): probe ack + full-task receipt confirmed;
  contracts re-read, task understood, NOT started; awaiting owner go-ahead in
  that session. No branches/files from this worker. Nothing to accept yet.
- Worker 2 cloud-vega (E-001): probe ack + full-task receipt confirmed;
  contracts re-read, task understood, NOT started; awaiting owner go-ahead in
  that session. No branches/files from this worker. Nothing to accept yet.
- Worker 3 cool-amalthea (V-001): probe + full task sent; no ack yet.
  Inbox file on disk. No delegation claimed.
- Accepted changes: none from workers. Manager-owned scaffold only.

## Actual commands and outcomes (all observed this session)

- `git init; git branch -M main` — ok, empty repo created.
- `python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"` — ok
  (pip notices a newer release; install succeeded).
- `.venv/bin/python tools/m1_vertical_slice.py` — exit 0; report
  `reports/m1_report.json`: synthetic true, coordinator single-owner-selected,
  rejected_count 1, risk approved budget 0.2500 (synthetic USDT), fills 1,
  recovery ambiguous-reconciled-no-duplicate.
- `.venv/bin/python -m pytest -q` — 3 passed.
- Native messaging: 3 probes + 3 full tasks sent (transport accepted,
  custody unconfirmed per receipts); 4 peer replies received and quoted in
  coord/workers.json notes (2 probe acks, 2 full-task receipts).

## Measured vs unresolved

- Measured: M1 scaffold mechanics + intent unit tests green; messaging round
  trips complete for 2 of 3 workers (task receipt confirmed).
- Unresolved: all profitability/edge claims; connector capabilities (awaiting
  E-001); real risk policy (awaiting V-001); S1 baseline (awaiting Q-001);
  model-config 1.3 Max-effort unverified (no inspectable setting; recorded in
  DECISIONS.md, no substitution claimed); Worker 3 ack.

## Blockers and next action

- Blocker: Q-001/E-001 execution needs owner go-ahead inside the
  whisper-redshift and cloud-vega sessions (their harness requires local
  authorization; peer tasking alone cannot start work). V-001 also needs
  cool-amalthea to wake/ack.
- Next: owner authorizes workers (or pastes nothing — tasks are already in
  their sessions + inbox files); manager integrates worker branches on
  completion, reproduces M2 data/latency evidence, and extends the slice.
