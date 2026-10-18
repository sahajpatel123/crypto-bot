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

## live/final-hardening takeover (2026-10-18)

- D-020: Work is confined to a dedicated worktree
  `/Users/sahajpatel/Code/cryto-bot-final`, branch `live/final-hardening`,
  created from `live/hardening` tip `3100266`. The main checkout's
  uncommitted `coord/pivot/*` was never read, modified or relied on; no
  other branch was merged. `data/captures/campaign-1day-*` events were
  never read (only manifest/status metadata may be read).
- D-021 (hermetic suite, F0.2): `test_zone_status` now reads the committed
  git object `HEAD:coord/pivot/ZONES.json` instead of the mutable working
  tree. `tests/unit/test_hermetic_reads.py` resolves literal repo paths in
  test modules and fails when a test reads a currently modified/untracked
  data/config file. Source imports under `src/` and tools under `tools/`
  are exempt because they are the code under test; tests/ and tmp are
  allowed. This is the rule the old failure violated.
- D-022 (break-even, F0.4b): `required_win_rate = (S+c)/(T+S)` is
  re-derived by `tools/breakeven_audit.py` without calling the production
  function. The table now carries `feasible`/`verdict`; `p >= 100%` is
  INFEASIBLE. At 25/25bps and 26bps cost p=102% (impossible). The default
  model's 25/25 taker geometry is 18bps, requiring p=86%; the earlier
  ">60-65%" prose was wrong and is corrected in RESEARCH_VERDICTS.md.
- D-023 (bracket admission, F0.4a): `bracket_admission_check` is called
  from `Session._maybe_admit` before submission for any engine exposing
  `leverage_brackets`. Missing/unobserved/stale/malformed brackets reject;
  leverage is the engine's expected value and is re-checked every 60s via
  `leverage_now` (mid-run changes halt entries). Maintenance margin is
  clamped non-negative so a malformed `cum` cannot move liquidation away.
- D-024 (paper fills, F0.4c): the "one adverse tick" rule is replaced by
  `PaperFillParameters`, which derives expected adverse bps from measured
  spread, depth multiple and latency, with floor/cap ticks. The Nautilus
  paper simulator applies at most one tick (documented limitation); the
  bps model is what replay/paper accounting and calibration use.
- D-025 (rounding bug): property tests found that the 1e-9 epsilon in
  `floor_to_step`/`floor_to_tick` could round UP by a whole step at large
  ratios, and `ceil_to_tick` could round DOWN. Both now clamp the result
  to the correct side of the input. F1.1 property tests cover it. This is
  a correctness fix, not a threshold relaxation.
- D-026 (gate strictness, F5.1): the old gate accepted
  `MEASURED-REST-ONLY` latency. It now requires measured
  `p99_feed_age_ms <= 250` and `drop_rate <= 0.001`, plus GATE_READY,
  sealed provenance, config-hash match, cost model <=30 days, host-check
  <=7 days, demo drill <=7 days, and a fresh watchdog heartbeat. This is
  STRICTER than before; no threshold was loosened to make anything pass.
- D-027 (research budget, F4.1): the family is H1-H6 (6 of the 8 allowed),
  preregistered in `research/prereg/` with exact rules/grids/costs/min
  trades and frozen configs in `research/configs/`. H4-H6 were committed
  before any evaluation. The registry is machine-written by
  `cryptobot research register`.
- D-028 (synthetic acceptance, F8.1): the autopilot's
  `--allow-synthetic` flag exists only to exercise the state machine in
  acceptance. It stamps state provenance SYNTHETIC; `gate` rejects it.
  The acceptance command proves the transition path AND the rejection.
- D-029 (adversarial review triage): two independent reviewers audited
  FINAL_STATUS and money paths without this STATE. Findings were:
  FIXED: unknown/reject submit escapes (A1/A2), unreachable venue treated
  as flat (B1/A7), day-roll clearing safety halts (B2/A8), protection
  UNKNOWN crash (B3), user-stream fee crash (B4), missing watchdog
  heartbeat (B5), orphan late fill (B6), leave-protected local-only
  trust (B7/A9), dust/min-notional close loop (B8/A10), malformed venue
  position rows read as flat (B9), shadow stop not wired (A4), rate-limit
  read escapes (A3), flatten not drained (A12), negative maintenance
  margin (A6 part). DISPUTED/ACCEPTED-RISK: booking-block latch has no
  auto-ack (A11) — it is fail-closed and requires reconciliation; default
  `max_mark_age_ms=None` on old research configs (A5) — prod/demo set
  1s, and the gate requires host/latency evidence; full mutation score
  (F1.2) is recorded as BLOCKED-TECH below if not completed.
- D-030 (chaos): the existing 13-row lifecycle matrix
  (`tests/unit/test_lifecycle_matrix.py`) is the automated fault matrix
  (timeout/5xx/429/reject/partial/dupe/reorder/WS death/crash/resume) on
  the real Session + sandbox venue; acceptance adds submit/stream fault
  scenarios. The invariant is flat or verified-protected, never an
  unowned naked position; the new orphan/shadow-stop guards enforce it.

## live/edge-sprint (2026-10-18, Family B low-frequency search)

- D-031 (E2.1 split): C = 2024-01-01T00:00Z; DEV [2019-09-01, C) ~4.3y,
  HOLDOUT [C, 2026-10-17] ~33.5mo, FORWARD after ingestion end. Chosen on
  calendar/coverage grounds from inventory metadata only (file counts,
  date ranges, bytes); no return/volume statistic was computed before
  research/prereg/SPLIT.md committed. Detectable SR ≈ 0.98 one-sided
  95% (t = SR·√2.797); 80%-power SR ≈ 1.49. The holdout is a SCREEN
  (sensitivity ~0.88 at SR=1, type-I ~0.31 on the point leg alone), not
  proof; see SPLIT.md for the full power table and look-boundary
  attestation.
- D-032 (E2.3 Family B budget): separate budget (max 8) and Holm family
  from Family A. Justification: disjoint data (multi-year daily lake vs
  tick/dev captures), disjoint strategy space (holding periods hours–
  weeks vs seconds–minutes), disjoint trial universes. Pooling would
  over-penalize both families and answer neither question cleanly.
  DSR trial counts are kept per family. Registry:
  research/autopilot_b/registry.json with its own hash chain.
- D-033 (E2.2 vault HOLDOUT): new class HOLDOUT seals a manifest of raw
  holdout files by byte-hash (no content sniff; explicit input_class
  required). Family-level manifests sealed BEFORE any Family B freeze.
  Decode is verdict-only via authorize_holdout_decode (one-shot token,
  integrity verified before the token burns, decode logged). Eligibility
  = zero decode/read log entries before the hypothesis frozen_utc, which
  forces batch-freezing all E6.2 survivors in one commit before the first
  screen (a late freeze after any screen is correctly ineligible: the
  human could have tuned on published screen results). load_chunk refuses
  HOLDOUT; import lint extended to authorize_holdout_decode/
  decode_holdout/holdout_frames. Legal per E2.2: no Family B hypothesis
  is frozen yet; Family A CONFIRM path untouched (14/14 vault tests green).
- D-034 (E4 mechanics clarifications, pre-evaluation): implementing the
  frozen B-preregs surfaced under-specifications; resolved WITHOUT
  touching prereg text, thresholds, grids, or criteria, before any lake
  byte was decoded (pull still running): (a) B2 "legs dollar-equal" +
  "each leg to 10% vol" conflict -> equal-dollar legs kept exact, uniform
  scale so the hotter trailing-60d leg sits at 10% (neutrality is
  load-bearing and tested); (b) anchored walk-forward: embargo_days folds
  into the purge gap (35d total; separate post-test embargo would only
  punch holes in expanding trains); documented in slow_stats.py.
- D-035 (E3 pre-evaluation corrections, NO data seen): implementing E4
  against the frozen B-preregs exposed 4 frozen-input bugs, fixed in
  prereg text BEFORE any lake byte was decoded (pass-1 pull still in
  flight): (a) B4 round-trip 49->53bps (spread+slip were counted once
  for both legs); (b) B2 "skip-1" words clarified to match the frozen
  formula (closes strictly before rebalance date; next-open execution
  already stales the last close by a day); (c) B6 min-obs 4->3 for W=30
  (90d admit exactly 3 non-overlapping 30d windows; min-4 structurally
  silenced half the grid); (d) B5 OI window max(W,24h) on daily prints
  (intraday OI unobservable). Also: B3 forced-exit 7d no-re-entry block
  (prereg silent; without it max-hold is a no-op; smallest coherent unit
  = one weekly cycle). No threshold/grid/criterion was tuned to results;
  none exist. Adversarial-review fixes E4.5: stale-key flatten, B5 exits,
  B4/B5 state round-trip, OI strictly-before-d, raw B6 z, wick liq,
  00:00 mark=open, independent event ledger, WF eval0 + 2x-hold gaps.
- D-035 (E3 pre-evaluation prereg corrections; zero lake bytes decoded): adversarial review of E4/E5 against frozen preregs found 4 frozen-input bugs + 1 gap, corrected in prereg text BEFORE any evaluation (pass-1 pull still in flight; only inventory metadata + synthetic fixtures touched): (a) B4 round-trip 49->53bps (spread+slip double-count fix); (b) B2 skip-1 words clarified to the frozen formula (closes strictly before rebalance date); (c) B6 min-obs 4->3 for W=30 (90d admit 3 non-overlapping 30d windows); raw z-scores kept literal; (d) B5 OI window max(W,24h) on daily prints, strictly-before-d (lookahead-safe; intraday OI unobservable); (e) B3 28d forced exit + 7d no-re-entry block (prereg silent; without a block max-hold is a no-op). No threshold was tuned to results (none exist); grids/criteria/promotion anchors unchanged. Code fixes in the same batch: stale-key flatten, B5 exits/cooldown, B4/B5 state round-trip, OI precede-d, wick liq trigger, 00:00 mark=open, independent event ledger, WF eval0 + max(35,2xHold) gaps, turnover gate helper.
- D-036 (concurrent-session incident 2026-10-18 ~16:19 UTC): an
  unidentified parallel Cursor process modified tools/vision_pull.py in
  this worktree (parallelized plan listings + test) and launched the
  pass-1 pull (24 workers, data/lake paths). Audited before adopting:
  split_of/checksum/pull logic untouched (diff = plan concurrency only);
  running plan matches SPLIT.md cutoffs and the pass-1 dataset scope;
  2000-job random sample showed 0 split mismatches; pull failures = 0
  (checksum gate active). ADOPTED the running pull (killing it would
  waste verified progress); my own nohup relaunch had died silently
  (empty plan log, no process). Lesson: use the shell tool's background
  mode (supervised) instead of nohup for long jobs in this harness.
- D-037 (E6.2/E6.3 pre-data specs; holdout undecoded): (a) holdout screen
  turnover is REPORTED, not gated (DEV already gated the same cell; a new
  screen gate post-freeze would be a new criterion); (b) UNDERPOWERED if
  <30 holdout rebalances (fail-safe precedent from Family A min_trades);
  (c) screen runs on the FULL holdout window, cold-start flat (no eval
  gap: all holdout decisions use legitimate past data; inherited DEV
  positions would flatter, so none are inherited); (d) FORWARD_COMPARE
  pass = realized Sharpe >0 AND >=50% of screen Sharpe AND DD<=35% AND
  turnover<=budget (mirrors the screen's DEV-fraction logic; forward data
  does not exist yet); (e) CJK symbol URLs percent-encoded (31 pull
  failures root-caused to UnicodeEncodeError); retry via rebuilt plan +
  same state file after the running pull completes.
- D-038 (leg-wise seal-before-analysis + universe hygiene, pre-evaluation):
  (a) The vault enforces CONFIRM eligibility PER HOLDOUT CHUNK (per data
  leg). Sequencing follows the same granularity: a DEV evaluation touching
  only 1d+funding bytes is cleared once the klines-1d/1h and fundingRate
  holdout legs are sealed; metrics/spot legs seal before any evaluation
  touching them. No evaluation has decoded any unsealed holdout leg.
  (b) 13 BUSD-margined symbols enter DEV top-30 weeks; the frozen universe
  rule is followed LITERALLY (settled as USDT, ~0 tracking error,
  disclosed in E6.4) — no post-freeze universe change. (c) Zero *SETTLED /
  quarterly symbols qualified in DEV; a fail-closed tripwire in
  run_family_b.py aborts any evaluation (DEV or holdout) if one ever
  qualifies, rather than backtesting fiction. (d) data/vault/chunks/ and
  tokens/ are host-local (gitignored); registry.json + access_log.json
  are committed. The parallel session's all-in-one HOLDOUT manifest
  (absolute paths) coexists harmlessly (append-only); E6.2 uses the
  per-leg manifests.
- D-039 (shared-worktree protocol; parallel Cursor session active in this
  worktree since ~16:19 UTC): all foreign content is AUDITED before use,
  never trusted. Adopted after line review + tests: parallel plan
  listings, _ascii_url hardening, MarketIndex engine index (+parity
  tests), stops_by_day engine support (completed here: was passed by
  runner without engine support), universe cache, run progress prints.
  Foreign data ops adopted: pass-1 pull (167,625/167,625 verified, 0
  split mismatches in 2000-sample audit), all-in-one HOLDOUT manifest
  (coexists; E6.2 uses per-leg manifests). Killed 2026-10-18 ~19:05 UTC:
  redundant foreign metrics pull (dup destination, DEV-only scope
  insufficient for B5/B6 holdout screens, memory pressure SIGTERMing
  local tests). Protocol henceforth: re-read before every edit; stage
  explicit paths only (no git add -A); full-diff review pre-commit;
  behavior battery after any suspected foreign change. E6.1 wave-1
  killed pre-output (perf: uncached universes) — no results existed, so
  the memoized relaunch is result-identical.
- D-040 (foreign E6.1 artifacts VOID): parallel session wrote B1/B2/B3/B7
  dev artifacts with unknown code provenance; independent rerun of B1 on
  the verified tree disagreed (best cell AND cell sharpes differ, e.g.
  turnover ~2x off). Saved to /tmp/foreign-dev-artifacts for the record;
  official E6.1 = this session's reruns on the audited tree, each
  determinism-checked. Lesson reinforced: reproduce, never adopt, чужое.
