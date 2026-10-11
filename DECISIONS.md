# Decisions and evidence log

Manager: young-polaris. Workers: exactly three peer sessions (see coord/workers.json).
Model configuration: owner requested Muse Spark 1.3 Max-effort. Available session
tools do not expose model version/effort settings for inspection (env shows no
SPARK/1.3/EFFORT variables; no Muse model-config command verified). Recorded as
unverified; no substitution claimed. Identity per session: Muse Code powered by
Meta Muse Spark.

## CEO initial decisions (simulation defaults, not proven settings)

- M0 run mode: replay/offline simulation; live-feed paper next.
- Python + pinned NautilusTrader after bounded connector-capability check; thin
  official Binance SDK connector only on demonstrated blocking incompatibility.
  One production engine, not two.
- Modular single-process application; no distributed microservices/heavy frontend
  without measured need.
- Position mode one-way; future pilot proposal isolated margin, auto-add off.
  Never alter unrelated account positions/configuration.
- One open position globally in initial pilot design, including in-flight reservations.
- Planned per-trade loss budget: at most 0.25% of reconciled trading equity
  incl. stressed loss-side execution costs (approx Rs 25 at Rs 10,000).
- Leverage cap 3x initial; higher leverage separately validated later.
- Operational daily loss circuit breaker: 1% decline from starting-day marked
  equity (flow-adjusted) blocks new entries rest of accounting day + exposure
  reduction. Persistent across restart; next day needs reconciliation + healthy
  system. Trigger, not guaranteed limit.
- Profit-protection simulation candidate: retain 70% of global net realised
  gains after gains reach 1% of original pilot equity; threshold upward-only,
  preserved across days/restarts; flows separate. Test alternatives offline.
- New-entry pause at 2% daily net-liquidation-equity target in initial simulation
  policy; manage open exposure normally. Evaluate continued trading under profit
  protection separately. No late-day size inflation.
- Accounting day Asia/Kolkata 00:00-24:00; raw events UTC. Ledger USDT primary,
  INR display separate.
- No withdrawal credentials, transfers, paid subs, publication or live orders.

## Manager decisions (M0)

- D-001: Repo initialised at workspace root (was empty, no git). Branch main.
  Remote to be added only for the owner-named private repo at commit time.
- D-002: Shared coordination directory `coord/` outside any worker worktree/branch.
  Task states: assigned, running, blocked, review, accepted. See coord/README.md.
- D-003: File ownership to prevent competing edits (contract v0.1.0):
  - Manager: CONTRACTS.md, DECISIONS.md, coord/, tools/m1_*, src/cryptobot/coordination/,
    src/cryptobot/__init__.py, pyproject/README/test bootstrap, reports/.
  - Worker 1 (Quant): specs/strategies/, src/cryptobot/strategies/,
    src/cryptobot/features/, src/cryptobot/research/, tests/unit/test_strategies_*.
  - Worker 2 (Data/Execution): src/cryptobot/market_data/,
    src/cryptobot/execution/, tools/capture_*, tools/replay_*, data/README,
    tests/unit/test_execution_*, tests/unit/test_market_data_*.
  - Worker 3 (Risk/Verification): src/cryptobot/risk/, src/cryptobot/accounting/
    (ledger review), tests/acceptance/, tests/fixtures/, specs/acceptance*.
    Risk code requires manager review + another worker reproducing critical
    invariants; strategy profitability never self-certified.
- D-004: M1 scaffold lives in manager-owned tools/m1_vertical_slice.py with inline
  stubs labelled synthetic; worker modules replace stubs via contracts. No manager
  edits inside worker-owned implementation files.
- D-005: NautilusTrader version pin deferred until Worker 2 capability matrix
  lands (bounded check). No framework code in M1 scaffold.
  [Turn-40 annotation: the matrix landed under E-001, satisfying the
  original trigger; the pin decision itself is re-deferred by D-011
  pending a future import+adapter smoke pass. D-005's deferral rationale
  stands, its trigger wording is superseded by D-011.]
- D-006: Workers may write exactly their own completion file
  (coord/outbox/Q-001.json, E-001.json, V-001.json); the rest of coord/
  stays manager-owned. Uncommitted-branch-diff evidence is acceptable for
  review when a worker's git policy requires user authorization to commit;
  the manager reviews the diff and the worker commits if/when authorized.
- D-007: V-001 finding F-E001-01/U-002 accepted as a real contract gap
  (risk->execution handoff: reservation_id threading, fill/cancel/expire
  outcome callbacks, halt->exit-only signal). Manager will draft a CONTRACTS
  v0.1.1 addendum with E/V implementation follow-ups after Q-001/V-001 land.
  F-E001-02 (venue-submit/log crash window) is must-fix before any real venue
  (E-003 candidate); F-E001-03/04 nits + F-E001-05 note bundle into it.
- D-008: Uncommitted worker diffs integrate via manager provenance commits:
  verified files are copied to main with the authoring worker, source branch,
  and hash/diff evidence named in the commit; worker branches stay the source
  of truth until the worker commits if/when authorized.
- D-009: Heartbeat semantics tightened: last_heartbeat_utc advances only on
  worker-originated contact (message, outbox file, ack) or newly observed
  worker-produced evidence (commits, diffs, files). The manager's own turns
  do not refresh it. The 30-minute stall rule in coord/README applies to
  running tasks without such contact.
- D-010: Finding F-Q001-01 (manager review of accepted Q-001 drafts):
  specs/strategies/S2.md-S4.md do not match the directive's five candidates
  (S2 filed as range-fade ~ directive S3; S3 as funding-tilt scalp, not in
  the directive; S4 as ATR breakout, not failed-breakout reversal; S5
  micro-imbalance ~ directive S5 order-flow, aligned). Q-001 acceptance
  stands (S1 + contract met the bar; drafts are labelled DRAFT/no-code), but
  the S2-S5 follow-up task will require the directive's S2/S3/S4 hypotheses
  or a written substitution rationale for CEO/owner review. Substitutions are
  a goal-content change, not routine engineering.
- D-011: E-002 verdict blocked-on-transfer accepted: nautilus_trader==1.231.0
  stays a PROPOSAL (D-005 still open); no adoption without a future
  import+adapter smoke pass. The bottleneck is host/network-specific
  (~100KB/s class), not a demonstrated upstream incompatibility, so it does
  not trigger the thin-official-SDK path either (CEO Sec.3.2 requires a
  specific blocking incompatibility). Engine work continues on stdlib-urllib
  capture + fake venue; retry deferred to a better-connected host or a
  pre-seeded wheel cache.
