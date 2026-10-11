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

## Addendum — turn 2 (E-001 running; shared-tree race disclosed)

- Worker 2 heartbeat: owner go-ahead received, E-001 assigned→running, branch
  worker2/e-001 created from clean main. No worker files yet; completion will
  arrive via coord/outbox/E-001.json.
- Shared-tree race (my defect, disclosed): all four sessions share one working
  tree, so Worker 2's checkout switched my tree mid-turn and my turn-2 commit
  e5ed85b landed on worker2/e-001 instead of main. e5ed85b was never pushed;
  identical manager content is re-committed on main here. I will not rewrite
  the worker's branch; identical content merges cleanly at integration.
  Mitigation requested: workers use separate `git worktree` checkouts per
  directive Section 5 instead of switching branches in the shared tree.
- Manager change: added `tests/unit/test_coordinator.py` (dedup, opposing
  stand-aside, stale/halt rejection). First run caught a bad test construction
  (expiry before evidence); fixed the test, product invariant unchanged.
- Checks: `pytest -q` 6 passed; M1 slice exit 0, synthetic report unchanged.
- Worker 3: re-nudged once, still no reply; flagged stalled-pending-ack.
  Worker 1: still awaiting owner authorization. Accepted worker changes: none.

## Addendum — turn 3 (E-001 progressing uncommitted; decision records added)

- Worker 2: `market_data/capabilities.py` + `__init__.py` present uncommitted;
  matrix separates verified vs assumed with no invented verification (early
  read-only review; full review at E-001 completion). Referenced
  discovery/recorder/replayer modules not yet written. No commits, no outbox.
- Manager change: added `coordination/decision_record.py` (frozen
  DecisionRecord + FeatureEvidence for Intent evidence_ref) with unit tests.
- Checks: `pytest -q` 9 passed; M1 slice exit 0.
- Worker 1: turn-3 check, session reachable, no new messages, still awaiting
  owner authorization. Worker 3: turn-3 check, reachable, still no reply;
  no further nudge this turn — owner attention needed on that session.

## Addendum — turn 4 (E-001 expanding; M1 wires decision records)

- Worker 2: worktree holds untracked market_data/ + execution/ (order-manager
  skeleton started). Still no commits, no outbox completion. Shared tree clean.
- Manager change: M1 slice now builds a real DecisionRecord and asserts the
  accepted Intent's evidence_ref points at it (synthetic content, labelled).
- Checks: `pytest -q` 9 passed; M1 slice exit 0.
- Worker 1: turn-4 check, reachable, no new messages, still awaiting owner
  authorization. Worker 3: turn-4 check, reachable, still silent since kickoff.

## Addendum — turn 5 (E-001 tools emerging; evidence generator added)

- Worker 2: worktree adds capture/replay tools (public-REST-only,
  observed/synthetic separation, determinism hash — early read, full review
  at completion). Still uncommitted; heartbeat + incremental-commit request
  sent. No outbox completion.
- Manager change: added `tools/generate_evidence.py`, a reproducible
  status-evidence collector (pytest + M1 + task board + worker status + git
  log). Smoke-tested: exits 0, output verified.
- Checks: `pytest -q` 9 passed; M1 slice exit 0.
- Worker 1: turn-5 check, reachable, no new messages, still awaiting owner
  authorization. Worker 3: turn-5 check, reachable, still silent since kickoff.

## Addendum — turn 6 (E-001 tests green uncommitted; README touched)

- Worker 2: worktree adds 5 unit-test files. Manager verification (read-only,
  worktree PYTHONPATH): 41 passed, 0 failed. First attempt without PYTHONPATH
  errored on collection — invocation artifact of the cross-tree run, not a
  product defect; corrected run is the evidence. Late-turn heartbeat then
  reported incremental commits 66dde7e + 7e2c6e7; manager verified both on
  worker2/e-001 (15 files, all inside E-001 allowed paths, +1875 lines).
  47-green claim corroborated by manager's independent 41-pass run plus the
  6 bootstrap tests on that base. Next: live public-data sample + outbox.
- Manager change: README entry-point list now documents generate_evidence.py.
- Checks: `pytest -q` 9 passed (main tree); M1 slice exit 0.
- Worker 1: turn-6 check, reachable, no new messages, still awaiting owner
  authorization. Worker 3: turn-6 check, reachable, still silent since kickoff.

## Addendum — turn 7 (V-001 running; D-006 outbox exception)

- Worker 3: first ack — user go-ahead received, V-001 assigned→running,
  starting on worker3/v-001. Flagged two real issues: commit policy
  (cites diffs unless user authorizes — accepted) and coord/outbox write
  ambiguity (resolved by D-006: each worker may write only its own
  completion file). Worktree recommended. D-006 also notified to Workers 1–2.
- Worker 2: worktree modifies recorder/tools + new data/observed/ — live
  public-data sample in progress. Still on 7e2c6e7, no outbox yet.
- Manager changes: D-006 in DECISIONS.md; tasks.json V-001→running.
- Checks: `pytest -q` 9 passed; M1 slice exit 0.
- Worker 1: turn-7 check, reachable, no new messages, still awaiting owner
  authorization. Only remaining unauthorised worker.

## Addendum — turn 7b (all workers running; E-001 review passed)

- Worker 1: go-ahead received, Q-001 assigned→running in isolated worktree
  /tmp/cryto-bot-w1 (branch worker1/q-001). All three workers now active.
- Worker 3: moved to worktree /tmp/cryto-bot-w3; shared tree returned to
  main with only manager files + outbox. V-001 progressing (acceptance
  spec written; fixtures/tests before policy).
- Worker 2: E-001 completion claim INSPECTED, review PASSED (merge below):
  3 commits verified ownership-clean; 48/48 tests reproduced; replay sha
  772a9163… reproduced exactly with 0 gaps; discovery counts 924/525/524
  reproduced from committed JSON; no-whitelist test present; order-manager
  code read (unique IDs, reconcile-before-retry with new IDs, no atomic
  bracket, expiry, restart recovery). data/observed placement + matrix
  location accepted as faithful readings of the task text.
  Unresolved carried forward: nautilus trial install, streaming, live adapter.
- Tree race #2 (Worker 3 checkout) caused zero damage: branch guard held,
  no commit on wrong branch, resolved by worktree move within the turn.

## Addendum — turn 7c (E-001 ACCEPTED and merged)

- Merge 567dce3 (no-ff) brought worker2/e-001 into main: 22 worker files
  (market_data ×5, execution ×3, tools ×2, data ×3, tests ×5, README).
  Conflicts confined to coord/workers.json + evidence report (stale turn-2
  duplicates on the branch); resolved to main versions.
- Merged-tree verification (all observed): pytest 51/51 green, M1 exit 0,
  replay of committed observed sample deterministic with sha 772a9163…
  E-001 state → accepted. First worker acceptance of the project.
- Worker 2's carried-forward items stand: nautilus trial install (needs
  follow-up task), streaming connector, live-venue adapter — all future work,
  none blocking Q-001/V-001.
