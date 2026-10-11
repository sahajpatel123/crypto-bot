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
- D-012: V-001R accepted (turn-427): W1 reproduced the V-001 acceptance
  suite read-only 34/34 twice + hand halt-persistence case
  (Rejected halt:daily-loss) + R-001..R-012 all pass, with read-only
  proof and zero unresolved; manager independently re-ran 34/34
  read-only from /tmp/cryto-bot-w3 with the w3 tree untouched. V-001
  therefore accepted (no-self-certification chain complete: W3 authored,
  manager reviewed turn-9, W1 reproduced) and integrated onto main via
  provenance copy of the 21 manifest files (all within V-001 allowed
  paths); merged-tree verification 139/139 + evidence
  gate exit 0. U-001/U-002/U-003 carry forward as follow-ups (U-002
  partly addressed by E-003 v0.1.1 handoff + RiskOutcomeSink).
- D-013: V-003 accepted (turn-432): W3 delivered SliceRisk wiring
  (accepted V-001 RiskPolicy + Ledger, (ok,reason,notional) shape,
  risk-policy:* labelling) + sink conformance + duplicate-callback
  tolerance + U-003 pinned-as-simulation-defaults with boundary
  tests and a written measurement plan; U-001 noted only. Manager
  verified all 4 inbox conditions field-by-field, read slice.py
  (106 lines), both new test files, and specs/acceptance-u003.md
  in full, and reproduced 148/148 read-only from
  /tmp/cryto-bot-w3-003 with the w3 tree untouched. Integrated
  onto main via provenance copy of the 7 files (all within V-003
  allowed paths); manager wired SliceRisk into the M1 slice
  (risk_stub removed, no risk-stub labelling remains). Merged-tree
  verification: slice exit 0 with
  risk-policy:approved:reservation=r-000001:budget=0.2500,
  rejected trade + fault recovery intact, full suite 148/148,
  evidence gate exit 0. U-003 stays pinned until Worker 2
  delivers the cost/latency datasets per the plan; U-001 remains
  out of scope by design.
- D-014: Q-002 accepted (turn-438): W1 delivered the D-010 correction
  (S2 trend-pullback exact spec + causal baseline, S3 range-reversion
  SPEC, S4 failed-breakout SPEC, all matching directive hypotheses;
  S5 kept as aligned) + pullback features + 2 SYNTH_V1 S2 scenarios
  + preregistered EXP-002 (S2/S2-V/S2-F, seeds 31-33/41-42, 0 trials,
  promotion NONE) + 19 new tests. Manager verified 18/18 sha256
  hashes, all paths within Q-002 allowed prefixes, and reproduced
  167/167 read-only from /tmp/cryto-bot-w1q2 with the w1 tree
  untouched; read S2/S3/S4/EXP-002 specs and s2.py (298 lines) in
  full; ran the M1 slice from the w1 tree (exit 0,
  risk-policy:approved, recovery OK). One manager-side integration
  fix: s1.evaluate_side now validates against ARM_IDS_S1 (the
  extended ARM_IDS would have let S2 arm labels into S1 logic);
  verified by direct probe. Integrated onto main via provenance
  copy (no path overlap with 8176d33..29a1a10); merged-tree
  verification: 167/167, slice exit 0, evidence gate exit 0.
- D-015: CEO review directive accepted (baseline 871d104):
  F-CEO-01..10 independently reproduced by manager probe
  (realized 76.0 vs 16; adverse loss 4.568 vs budget 2.5;
  partial-protection refusal + expiry release + re-approval
  with open fill; TTL re-approval; deposit-triggered target
  pause; NaN approved; gate exit 0 on injected failures;
  inline M1 venue; stale E-004/coord state + README; stalled
  data/research). Snapshot/test/commit loop STOPPED; logical
  commits only. V-004 (W3), E-005 (W2), Q-003 (W1) dispatched;
  manager owns MG-001. Live trading stays disabled.
- D-016: V-004 + E-005 accepted and integrated (turn review):
  V-004 ledger/risk corrections (221/221 incl. fixup) via
  provenance copy (15 files, sha-verified); E-005 execution
  (187/187) merged as 6640bc9. Manager integration changes:
  RiskOutcomeSink Protocol gains note_fill_delta (v0.2.0 code)
  + 2 stub conformance updates + 3 handoff assertions to the
  delta-before-transition sequence. Merged-tree: 238/238,
  M1 exit 0, CEO probe 8/8 fixed. Rulings: unresolved-bucket
  stands (observable, block-retaining); filled reservations
  are consumed by first-fill transition (never expire live);
  W1 retention assertion corrected to release-False +
  booked_net-nonzero. Q-003 fix-after 19/20, one correction
  outstanding. E-002-style residuals recorded, not promoted.
- D-017: Q-003 accepted and integrated: 20 black-box CEO
  regressions (15F/5P baseline record identical on 871d104 +
  branch, 20/20 fix-after on integrated main) + resumable
  EXP runner + 150/150 executed trials (EXP-001 90, EXP-002 60,
  promotion NONE) + split audit (embargo insufficient for
  future return scoring: 12 vs 135-bar horizon). Manager
  integration fix: tests/ceo_review/conftest.py renamed to
  helpers.py — the duplicate top-level conftest module broke
  4 V-004 tests in full runs (proven: 264/264 after rename).
  Merged-tree 264/264, M1 exit 0, gate PASS. Packet 1
  (V-004/E-005/Q-003) fully accepted.
- D-018: M1 rewired to the integrated lifecycle (F-CEO-08
  closed): labelled synthetic recording through the real
  replay boundary (asserted input class, lossless transport,
  clean gap/stale stats) -> S1 -> coordinator (1 rejection)
  -> V-004 risk -> shared OrderManager + fault venue on one
  virtual clock: partial entry, sibling protection,
  crash/restart with exposure open (orders/risk/ledger
  rebuilt, fills/booked/cash agree), remainder expiry
  without release, stop exit, verified sibling cancel, flat
  reconciliation, closed-trade report (realized -0.0285 on
  100 USDT synthetic, within 0.25 budget). Numerics
  deterministic across runs. 264/264, gate PASS. Q-003 rider
  (EXP-001 90/90, EXP-002 60/60 statuses) integrated.
  E-006 started (W2).
- D-019: E-006 accepted on manager review, merged as 7dc90ea
  (22 files, +3039/-33): routed-WS collector, depth sync,
  normalized events, causal 1s bars, supervised 30-min
  capture (1,129,445 events, chaos recovered), deterministic
  replay (SHA 129f0f55, exact bar agreement), latency/DQ
  report (event-age p50 74ms, decision p50 0.02ms, order
  latency explicitly unclaimed). Manager independently
  reproduced suite/replay/hashes/methodology/Nautilus smoke.
  V-005 independent verification DISPATCHED but unacknowl-
  edged: session-message route containment-limited (5 sends);
  inbox V-005.json on main is the durable record; V-005 stays
  open with fixup authority. D-005 adoption ruling: pin
  nautilus_trader==1.231.0 recorded as import+adapter
  verified (trial venv); NO project-.venv install now (keep
  env light, no second engine); backtest-trial follow-up
  scoped; live submission unverified (no creds by policy).
  Merged-tree 340/340, gate PASS. cap-2h follow-up pending.
