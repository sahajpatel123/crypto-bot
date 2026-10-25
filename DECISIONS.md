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
  determinism-checked. Lesson reinforced: reproduce, never adopt, foreign results.
- D-041 (official screens; CODE FREEZE): (a) B4 vault freeze ADOPTED
  (hash matches E3-frozen B4.toml, verified untouched since b0b4ac4).
  (b) Parallel B4 screen (2.945) NOT adopted (unknown code state);
  official screens run once each by this session on the audited tree.
  (c) Fresh minimal per-screen HOLDOUT manifests (prereg-determined file
  lists only) preserve exactly-once per chunk. (d) CODE FREEZE on the
  evaluation path (family_b/slow_backtest/slow_stats/driver/runner/
  verdict-screen/lake readers) until all screens complete; exceptions
  only for proven bugs (failing test + new decision entry). (e) B5's
  premature KILL (foreign artifact, metrics missing) is remediated by
  proper rerun: corroborated FAIL stands; a PROMOTE forks to B5R (8th
  budget slot) to preserve append-only terminal semantics.
- D-042 (B4 sizing bug; screen voided + rerun): the shared 25%/leg clip
  silently halved B4's preregistered 50%/leg delta-neutral size (signal
  code said 0.5, _cap_weights clipped to 0.25; tests only pinned signs).
  Sharpe is near scale-free so gates were likely unaffected, but dust/
  step-quantization differ, so: fixed via per-hypothesis cap param +
  exact-size test, VOIDED the in-flight 0.25-code screen (its decode of
  chunk-74e0 stands logged but unused), and reran DEV B4 + a fresh-chunk
  single screen on the fixed tree. No results from the voided run were
  adopted. Lesson: pin economic magnitudes in tests, not just signs.
- D-043 (autopilot_b state reset; foreign transitions voided): the
  parallel session drove autopilot_b on void artifacts: B4 to
  SCREEN_PASS (foreign 0.25-code screen), B6 to KILLED (no-metrics
  premature dev), and my own run consumed their premature B5 dev
  (KILLED on incomplete data). B1/B2/B3/B7 KILLED transitions are VALID
  (my artifacts, corroborated). Remediation: (1) quarantined foreign
  verdict/cell/dev files to /tmp/void-foreign (moved, never deleted);
  (2) B4 rerun officially on fixed code -> KILLED on turnover 15.48>12
  (sole failing bullet; OOS 4.28 retained); (3) B5/B6 rerun properly
  once metrics land; (4) autopilot_b state/ + transitions.json RESET
  (old chain preserved as transitions.json.VOIDED) and re-driven SOLELY
  from verified artifacts. Terminal states are never edited in place.
- D-044 (Z1.1 provenance, 2026-10-19): uncommitted worktree diffs at
  tip 00474c1 were not the code that produced any adopted verdict.
  `research/autopilot_b/dev/B4.json` on disk (evaluated
  2026-10-18T17:20:33Z, best cell k=3, turnover 15.4809) disagreed
  with the committed artifact (evaluated 2026-10-18T15:50:09Z, best
  cell k=2, turnover 17.0506). B2 differed only in the last float
  digit. The whole diff, including doc files that restated the
  uncommitted numbers, is `archive/z1.1-uncommitted.patch` (10275
  lines) and the worktree was restored to 00474c1. D-043's sentence
  "turnover 15.48" describes that uncommitted rerun; the release
  artifact remains the committed file. Artifacts were not edited.
  Recorded code commits versus 00474c1: `research/verdicts_b/B4.json`
  hashes.code_commit `fdb8967` is an ancestor. Exceptions:
  `research/verdicts/H1.json`–`H6.json` record `code_commit: unknown`;
  `research/autopilot_b/dev/B1.json`–`B7.json` and
  `research/autopilot/dev/H1.json`–`H6.json` have no `code_commit`
  field. Those files stay as written.
- INC-1 / D-045 (Z1.3, 2026-10-19): B4 holdout was decoded three times,
  breaking the exactly-once rule. Consumer `verdict`, hypothesis B4
  only. Times and tokens are in `release/holdout-reconcile.json`.
  The decodes are void (D-042). `tools/holdout_reconcile.py` compared
  those chunk manifests to the pre-analysis seal
  `chunk-2a22e52c3c8f50db` (118548 files). Of the 198-file chunk,
  132 files (66 klines + 66 funding) are in that seal and 66 spot
  files are not. Of the 202-file chunk, the same 132 are in the seal;
  66 spot files and 4 rest_tail files are not. `subset_ok` is false.
  No zip was opened.
- D-046 (operational completion, 2026-10-19): `release/v1` was moved
  to tag `v1.0-final` (`166690c`) because that tag is the complete
  tree and the branch pointer was still the earlier closeout.
  `EXTERNAL_DATA_ROOT` was empty, so the recorder and lake were not
  moved. H4 Bybit/OKX streams stay off: disk covers about 12 days at
  the measured rate and adjudication is 90 days away
  (IMPRACTICAL-BY-RESOURCE). C1's decision date is
  `c1_final_utc`: the first day with 90 forward days, then
  max(T, that day), never later than T+14. Emulator output is
  provenance EMULATED and cannot satisfy `demo_drill_pass_fresh`.
  Loopback base URLs are accepted only for `127.0.0.1` and
  `localhost`. Prod ops refuse without an arm record. No prereg was
  edited. No arm or GO gate file was written.
- D-047 (2026-10-19, owner hurdle of 2–3%/day): the wish is recorded
  and checked by `cryptobot monitor`. It is not written into a frozen
  prereg and it is not a new gate. B4's best OOS Sharpe is 4.396 with
  max drawdown 0.47%. Turning that Sharpe into a 2%/day mean would
  require about 8.7% daily volatility, which contradicts the
  drawdown. Verdict HURDLE_UNMET, gate NO-GO. No cell was retuned.
  2%/day compounded is about 1,377× in a year; 3%/day is about
  48,483×. Those multiples are not in the measured results.
- D-048 (operational hardening, 2026-10-20, commits 3c17b65–e7babf2):
  verified the A–E DONE claims by execution, then closed the gaps
  found. C: `ops order` routes STOP_MARKET/TAKE_PROFIT_MARKET via
  `place_algo` (needs `--stop-price`); `--post-only` LIMIT refuses
  when marketable; new `cancel --client-id` and `cancel-all` that
  cancels regular + algo orders (previously cancel-all wrongly
  flattened); `kill` = cancel-all + flatten + halt; `--client-id`
  gives safe retry (duplicate refused, no double fill). Reduce-only
  closes skip the entry reservation (they cannot add exposure; the
  venue validates they close) so protection can attach after an
  entry; entries still go through RiskPolicy one-position. B:
  MockEx stamps EMULATED on list rows (was header-only); drill
  gains an http-503 unknown-outcome cell on a fresh engine (the
  429 cell leaves a 60s refuse-fast window); soak callers now run
  24 steps, not 4. A: selftest asserts exact exits (doctor 1,
  refusals 2, readiness-missing-creds 3), bare parents, invalid
  mode, ops-prod refusal per action, monitor idempotency, SIGINT
  rc 0; 57 commands, 132 checks. D5: install.sh defaults to
  `$ROOT/.venv` (was a hardcoded main-checkout path). E1: owner
  prints PASS/TODO + counts + send-back, validates --step.
  Adjudication force-close stays at T per the frozen prereg;
  `c1_final_utc` (T+14 display) integration waits for forward data.
  Full WS market streams, tick/step server validation, 418/502/504
  injects, and SIGKILL-resume remain future work, recorded in
  STATE.md. No prereg edited. No arm or GO artifact written.
- D-049 (B/D completion, 2026-10-20, commits after a791864): MockEx
  now serves combined market streams (aggTrade, bookTicker,
  depthUpdate, markPriceUpdate, forceOrder) over a real WebSocket,
  plus the private user-data stream with listenKey TTL enforcement
  and clean close on scripted death. SandboxVenue validates tick,
  step and min-notional server-side (-4014) instead of trusting the
  client, and injects 418, 502, 504, timeout (connection drop) and
  deterministic reject. The drill is 19 cells: auth/filters/entry,
  partial/IOC, protection, 429/418/502/504/timeout/reject, clock
  skew, market streams, user stream, listenKey expiry, watchdog
  freshness, SIGTERM flatten and SIGKILL resume in separate OS
  processes, flatten-under-failure, resume. The 24-step soak uses a
  fresh engine per hour, all eight fault actions, and proves no
  duplicate fill, no lost fill (venue tape vs adopted journal) and
  zero open positions. A recorder smoke test feeds EMULATED streams
  through the real recorder into a SYNTHETIC sealed chunk.
  Selftest --all now also runs risk acceptance, a chaos subset,
  determinism, vault/verdict/gate/arm refusals, adjudicator
  branches, recorder smoke, host-check and background status
  (140 checks). D4: the daily autopilot report carries recorder gap
  %, and `background status` projects disk days against the
  adjudication date and notifies on shortfall. EXTERNAL_DATA_ROOT
  is still unset, so the recorder/lake were not moved (D-046
  stands); measured projection is ~16 days of disk against ~103
  days to adjudication, which is recorded as an owner resource
  item, not silently ignored. Retention compaction was not run on
  the real recorder (no external root, ample local headroom); the
  code path is not claimed.
- D-050 (D1 retention tool, 2026-10-20): `cryptobot compact --root
  <recorder>` writes zstd Parquet next to each sealed `.jsonl.gz`
  and appends a hash-chained proof entry (raw sha, parquet sha, row
  count, canonical row hash, recorder chain head). Equivalence is
  fail-closed: rows and canonical hash must match before an entry
  is written. Raw deletion is deliberately NOT automatic: the
  recorder manifest is append-only and hashes each raw chunk, so
  deleting a referenced chunk would break `recorder verify` and the
  vault import. Pruning needs a reviewed manifest v2; until then it
  is an owner action on a copy. Tested on fixtures
  (`tests/unit/test_compaction.py`), not run on the real recorder.
  `background status` projects ~16 days of disk against ~103 days to
  adjudication (`disk_alert: true`); that is recorded as
  BLOCKED-OWNER resource work.
- D-051 (B4 turnover-kill audit; only a FORWARD test of the carry can
  answer it, 2026-10-24): the sole failing B4 bullet (one-way annualized
  turnover 17.05 > frozen budget 12) is not a valid capacity test. Every
  fill in the B4 P&L already pays the full 53 bps round trip, so a
  turnover cap charges the same cost twice; turnover is dimensionless
  (x equity/yr, no ADV term) so it cannot say whether the book could be
  traded; and "one-way" was never defined in the prereg (under the
  half-round-trip convention B4 = 8.53 and passes the same budget). The
  budget is NOT retro-softened: B4 stays KILLED, its holdout stays BURNED
  (release/holdout-reconcile.json, three decodes), and no B4 result is
  reused or rescored. The replacement is a forward study under
  research/prereg/B4b-forward-basis.md, committed before any forward
  read: per-fill square-root impact (0.5*sigma*sqrt(Q/ADV20), the 1 bp
  floor removed), legs capped at 1% of ADV20, participation gates instead
  of a turnover gate, and all ten B4/B4b cells counted in DSR (N=10).
  Two consequences are stated in the prereg rather than discovered later:
  the 14 days 2026-10-18..2026-10-31 cannot be scored without decoding
  the 2026-10 monthly funding file (a holdout-dated artifact), so the
  forward clock starts 2026-11-01; and the >=2-positive-years gate is
  first assessable at 121 forward days, i.e. 2027-03-01, which means a
  90-day look can only KILL (D-056 corrects an earlier 2028-12-31 claim
  that was simply wrong arithmetic). Runner: tools/forward_b4b.py (Vision
  CDN only, fapi.binance.com is HTTP 451 here). As of 2026-10-24 the
  study is UNDERPOWERED at 0 of 90 forward days: no forward-dated funding
  file exists yet (Vision publishes funding monthly), and the first
  tradeable decision also needs 20 forward days of bars for ADV20/sigma.
- D-052 (two statistics repairs; both overstated confidence, 2026-10-24):
  (a) deflated_sharpe used n = daily observations on a series that is 75%
  exact zeros with ACF(1)=0.46, which is why B4 recorded DSR 0.9999998
  while a Newey-West t(30) on the same series is 2.20 (iid t 6.96).
  slow_stats.autocorr_adjusted_n now estimates an effective sample size
  (Bartlett/Newey-West variance inflation, 30-day lag window, floored so
  a mean-reverting series is never credited with extra observations, and
  capped at n/hold_days when the holding period is known) and DSR uses it
  in place of n. B4's dev series under the fix, recomputed and corrected
  in D-056: n_eff 91.5 -> DSR 0.9464; with the 30-day maximum-hold cap
  n_eff 30.5 -> DSR 0.8211; with N = 10 trials and that cap -- the way
  tools/forward_b4b.py calls it -- DSR 0.8055. B4 therefore still clears
  the 0.80 DSR gate, by 0.0055 at N=10 and 0.0211 at N=9: a thin pass,
  not the clean 0.9999998 it appeared to be, and not the failure an
  earlier version of this entry claimed. adjust_n=False reproduces the
  old number exactly, which is how the fix is pinned in tests. A
  "22.5-bet / DSR 0.7838" row previously quoted here was withdrawn: it
  requires hold_days=40.7, longer than B4's own 30-day maximum hold, and
  no code path produces it. (b)
  slow_backtest already appends "leak-investigate" when Sharpe > 3.0 but
  run_family_b threw the flags away, so a suspiciously good artifact read
  clean. promotion_gates now records flags, per-cell flags and a
  flags_clean bullet, and a blocking flag fails promotion. No frozen
  artifact was edited.
- D-053 (base-tree defects found while validating this change,
  2026-10-24): `main` (and origin/live/hardening) could not be imported:
  src/cryptobot/app/session.py held a duplicated merge fragment
  (lines 3512-3516, a stray `and "reduce_exposure" ...`) that is a
  SyntaxError, so 31 test modules failed at collection. Repaired by
  deleting the duplicated fragment only; the surviving block (3504-3511)
  is the more careful variant that also guards on `_exit_only_reasons`,
  and no logic was added or reinterpreted. Separately, the committed
  uv.lock is corrupted (two ruff package entries merged at line 779), so
  `uv sync --locked` fails; CI survives on its `|| pip install -e
  ".[dev]"` fallback and the local venv was built the same way. The lock
  was NOT regenerated here (a lock rewrite is a separate, reviewable
  change).
- D-054 (validation of D-051..D-053 on this tree, 2026-10-24): the two
  repairs in D-053 were required before anything could run, and only those
  two were made. `cli.py` carried the same autofix damage (8 leftover
  `timezone.utc` uses with `UTC` imported); those are NameErrors on
  `cryptobot gate/arm` paths and were fixed the same way. With those, the
  suite collects and runs: 1745 passed, and the failures that remain are
  PRE-EXISTING, not caused by this change -- proven by checking out the
  base commit 3ccbd14 in a clean worktree, applying only those same two
  import repairs, and reproducing the identical failures there
  (test_live_launch, test_autopilot_gate, test_invalidation,
  test_hardening_batch, test_lifecycle_matrix, test_emulator_hardening,
  test_operational). Their signature is schema drift in the GO/NO-GO gate
  (`verdict_names_strategies`/`verdict_pass` false on fixtures the gate
  used to accept) plus emulator timing, i.e. someone else's in-flight
  ledger/gate work, not research code; repairing it means choosing between
  two competing gate semantics and was left alone. Also observed and left
  alone: `src/cryptobot/cli.py` defines `cmd_gate` twice (line 1539 is a
  docstring-only stub from the same bad merge, shadowed by the real
  definition at 1552 -- harmless at runtime, still an artifact), the
  committed uv.lock is corrupt (two ruff entries merged at line 779), and
  `ruff check src tests` reports 140 pre-existing findings, so the
  blocking lint job is red on the base tree independently of this branch.
  Files touched by this change are lint-clean.
- D-055 (base repairs landed via PR #21, 2026-10-25): D-053/D-054
  describe the base defects this branch first ran into (the duplicated
  `session.py` merge fragment, the `cli.py` `timezone.utc`/`UTC`
  NameErrors, the spliced `uv.lock`). Those were repaired on this branch
  only so the suite could run at all. After PR #21 merged the real
  repair into base (live/hardening 0c2ccc4), this branch was merged onto
  it (64d5989 is a merge commit, not a rebase) and its own three repair
  commits were DROPPED rather than re-landed:
  the lock, session and CLI repairs in this history are #21's, not this
  branch's. Confirm with
  `git diff origin/live/hardening..HEAD -- src/cryptobot/cli.py
  src/cryptobot/app/session.py uv.lock`, which is empty. D-053/D-054 are
  left as written because they record what was true on the pre-#21 tree.
- D-056 (independent-review fixes to the B4b forward study, 2026-10-25):
  the review found the runner's book was not delta-neutral and that four
  of its guards were unpinned. Fixed, all before any forward read:
  (a) CRITICAL -- `tools/forward_b4b.py` accrued spot mark-to-market into
  cash while equity already marked the spot position, so the "delta-
  neutral" book was long 1x spot for the whole hold (equity = E0 +
  q*(s_t - s_entry) + funding - costs). Measured on the trend fixture:
  +169% of equity for a +1%/day trend against +28% carry. The spot
  accrual is deleted; only the perp (a derivative) moves cash, and at
  every fill it settles to that fill's own price so the gap between the
  last daily mark and the trade is booked. Equity is now exactly
  E0 + funding - costs when spot and perp marks are equal, asserted for
  trend +1%/day, 0 and -1%/day. (b) The prereg claimed the turnover
  budget was "the only gate change" while silently dropping B4's plateau
  >=70%; plateau is now a declared structural null with its reason (no
  parameter grid to walk), and the years restatement is stated explicitly
  instead of inherited by implication. (c) The claim that the years gate
  was unassessable before 2028-12-31 was wrong arithmetic: 2026 supplies
  61 forward days and 2027 reaches 60 on 2027-03-01, i.e. forward day 121.
  Corrected, and the consequence is now stated in the prereg, the verdict
  document and the CLI: a 90-day look can only KILL, a PASS first becomes
  possible at 121 forward days, and the recorder reports
  `years_assessable_from_forward_day`/`years_assessable_from`/
  `forward_days_to_first_possible_pass`. (d) The research record's DSR
  numbers were wrong in the estimator's own terms; corrected to 0.9464
  (n_eff 91.5), 0.8211 (30-day cap) and 0.8055 (N=10 + cap, the runner's
  convention), and the unreproducible "22.5 bets / 0.7838" row deleted.
  B4 still clears the 0.80 DSR gate by 0.0055 -- thinly, which is the
  honest reading. (e) Data integrity: every file is checksum-verified
  against its published .CHECKSUM on every run including resumed files
  (the CLI printed "checksums verified" while never comparing), every row
  must fall inside its own file's date window (a 2026-10 file renamed
  2026-11 would otherwise import the 14 permanently-excluded holdout
  days), and a forward day now needs bars as well as funding, so dropping
  10 days of bars lowers the day count by 10 instead of scoring stale
  marks. (f) Rebalances now execute at the next bar open like entry and
  exit, not at the prior close. Each fix has a test that fails when the
  guard is deleted (nine guard-deletions verified). No frozen threshold
  changed: Sharpe 0.70, 2x 0.30, DSR 0.80, PBO 0.30, DD 35%, 2 years,
  1%/5% participation, bootstrap > 0, NW t 2.0 all stand.

- D-057 (recorder stream coverage, 2026-10-25): the recorder subscribed to
  five Binance streams and recorded two. Measured on the owner's Mac
  (DoH shim on, raw sockets, both `/ws/<name>` and `/stream?streams=`):
  `trade`, `bookTicker` and `depth@100ms` deliver frames; `aggTrade`,
  `markPrice@1s` and `forceOrder` complete the handshake and then send
  zero bytes for the whole window, with no close and no error. The chunk
  for 07:18Z held 96,273 `book_ticker`, 5,874 `depth`, 10 `open_interest`,
  10 `premium_index`, 10 `depth_snapshot` and **zero** trade, mark-price
  or liquidation records; every chunk back to 18 October is the same. So
  it was neither a disk-budget cut nor a writer allowlist (there is none:
  drops happen only on queue overflow, and the manifest's `streams` list
  is derived from records actually written) -- the three names are simply
  not served on this path, and the loss was silent.
  Consequences and the fix: (a) `BINANCE_STREAMS` is now the delivered
  set (`trade`, `bookTicker`, `depth@100ms`), with the silent names kept
  in `BINANCE_SILENT_STREAMS` and still requestable through the new
  `RecorderConfig.streams`; (b) `classify_message` accepts `e == "trade"`
  (id in `t`, not `a`), so raw prints are no longer unclassified;
  (c) trades are folded into per-second order-flow buckets (`trade_agg`:
  buy/sell qty, count, VWAP) because raw prints do not fit the 4 GB
  budget -- measured 689 B / 3 s for ETHUSDT and 554 B / 2.5 s for
  BTCUSDT on `@trade`, i.e. roughly 20 MB/day per symbol raw, 40 MB/day
  for both, versus ~1.2 GB/day today, so aggregates add well under 5%;
  (d) a sealed chunk now raises a `stream-silent` alert naming every
  subscribed stream that produced no record, so this cannot repeat
  quietly; (e) mark price keeps coming from the 60 s REST `premiumIndex`
  poll, which already carries `markPrice` and `indexPrice`; index/mark
  over websocket and liquidation events remain unavailable on this path
  and are recorded as foreclosed rather than assumed.
  Scope note: this changes the recorder's future output, not any scored
  dataset. The change must land on a chunk boundary when the owner
  restarts the recorder; the 18-25 Oct chunks stay as they are, and no
  preregistered threshold, holdout file or verdict is touched.

- D-058 (the stream-silent guard is per stream, not per symbol,
  2026-10-25): the first cut of D-057 guard exempted every SYMBOL@* name
  as soon as any of that symbol trade records was seen, because the
  trade/aggTrade equivalence was tested on the symbol rather than on the
  stream name. With trade flowing by default that made the alert
  unreachable in the one case it exists to catch -- one stream dying
  while the symbol others keep flowing -- and the test that shipped with
  it fed a seen set holding only bookTicker records, so it could not fail. The equivalence now
  applies only to its own stream name; a single-stream (/ws/<name>)
  connection, whose records carry no stream field, is recognised by bare
  event name instead of alerting on every chunk; and trade_agg keeps the
  first/last trade id so a replayed or duplicated print can be
  de-duplicated downstream. The bare-name tolerance is scoped to a
  one-symbol, one-stream configuration, the only shape in which such
  a connection exists, so on a full run one symbol's bare records
  cannot silence another. A trade-id gap or out-of-order print that
  lands on a second whose bucket already exists is now carried on
  the bucket instead of being dropped. Two known limits are recorded rather than
  papered over: a print arriving for a second whose bucket was already
  flushed re-opens that second, so one (symbol, second) can carry two
  partial trade_agg records that must be summed; and the second still
  open when a chunk seals is written into the next chunk, so a chunk
  manifest streams list is not exhaustive for its sealing second
  (records are keyed by event_ms). No preregistered threshold, scored
  dataset, verdict or holdout file is touched.

- D-059 (C2-FWD point-in-time membership and listing policy, 2026-10-25):
  without a historical public exchangeInfo source, freeze membership from the
  latest exchangeInfo snapshot observed on the decision UTC date and no more
  than 8 hours before its close; require the documented complete response and
  serverTime within 15 minutes of the local UTC clock. Store the exchange
  serverTime as the observation time and use it to reject unfinished candles;
  a server time before 00:05 UTC or outside the requested day refuses booking.
  A post-close snapshot may confirm a missing next candle as a retirement but
  never changes signal membership. Require 36 consecutive daily mark closes
  spanning 35 completed calendar-day intervals, and at least 35 calendar days
  since listing, matching C2's minimum-history requirement and exceeding the
  30-day liquidity window; rank Monday candidates only from 30
  complete quote-volume candles finalized after close. Refuse missing/stale snapshots,
  incomplete volume, unresolved halts, or backfills with no contemporaneous
  snapshot; never infer aliases or reconstruct old membership from current
  exchangeInfo. The frozen preregistration remains unchanged and the gate stays
  NO-GO pending owner review of the policy interpretation.

- D-060 (C2-FWD bootstrap precision, 2026-10-25): use the preregistered
  week-block estimator with fixed seed 7 and 50,000 rounds at each exact look.
  This gives Monte Carlo resolution 1/50,001 before the first OBF bound; record
  the count and seed in every look report. The round count changes precision
  only, not the estimator, data, boundary, or stop rule.

- D-061 (C2-FWD independent-review hardening, 2026-10-25): when a complete
  post-close exchangeInfo snapshot confirms retirement but the next candle is
  absent, use the last available decision close as the terminal mark, charge a
  separate forced-exit leg, and record its mark day/turnover. Before a later
  look, bind every prior report to its look index, exact day count, ledger-prefix
  hash, frozen scoring parameters, and deterministic recomputation of its
  primary verdict. This adds no hypothesis or threshold; frozen preregistration
  remains unchanged and the gate stays NO-GO.
