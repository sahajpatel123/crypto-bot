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

## Addendum — turn 8 (E-002 dispatched; Q-001/V-001 implementing)

- E-002 (bounded Nautilus trial install + capability verdict, D-005 follow-up)
  dispatched to Worker 2 on new branch worker2/e-002; documented blocker is a
  valid finding. Receipt acked; not started, awaiting worker-side go-ahead.
- Worker 1: Q-001 worktree shows S1–S5 specs, EXP-001, contract, s1.py,
  features, research harness. Rebase-onto-new-main plan accepted; observed
  sample reserved for post-EXP-001 validation (EXP-001 stays synthetic).
- Worker 3: V-001 worktree shows acceptance spec, ledger/day accounting, risk
  policy/sizing/state, acceptance tests + fixtures. __pycache__ noted for
  exclusion from any commit.
- Checks: pytest 51/51 green; M1 exit 0. Pushed cbb722f + 2a33173.

## Addendum — turn 9 (Q-001 ACCEPTED + merged; V-001 review-passed)

- Q-001 accepted and integrated as 4290233 (provenance commit per new D-008):
  18 files, 18/18 sha256 verified vs outbox, 34/34 focused + 85/85 full
  reproduced, M1 output byte-identical post-merge. Causality + invalidation
  side verified by construction; EXP-001 clean (0 trials, promotion NONE).
- V-001 manager review PASSED, state review: 34/34 acceptance + 85/85 full
  reproduced in w3 worktree; policy/ledger reviewed gate-for-gate vs
  R-001..R-012. Acceptance awaits independent reproduction (no self-cert).
- Dispatched V-001R (Worker 1, independent V-001 repro, evidence-only) and
  V-002 (Worker 3, landed-S1 6-point verification).
- D-007: F-E001-01 handoff gap accepted as real; v0.1.1 addendum scheduled.
  E-002 STARTED (branch worker2/e-002 from 2a33173).

## Addendum — turn 10 (M1 uses real S1; V-002 ACCEPTED clean)

- Manager wiring (tools/m1_*): S1 stub replaced with real S1 ARM_BASE intent
  from SYNTH_V1 long-breakout seed 11 (fires bar 154); coordinator select,
  1 stale rejection, risk-stub approval, ambiguous-reconcile recovery (1
  fill, no duplicate) all preserved. Risk stub stays labelled to V-001.
  Committed 8a9b735; suite 85 green.
- V-002 accepted (75e20cb): landed-S1 CLEAN verdict fully verified — 34/34
  strategies + 34/34 acceptance reproduced, worker probe re-run ALL 6 PASS
  with fire_bar_t=154 sha d89576a1…, matching filed evidence.
- V-001R receipt acked by Worker 1; not started, awaiting go-ahead. E-002
  trial venv .venv-trial observed in w2 worktree.

## Addendum — turn 11 (v0.1.1 addendum; E-002 healthy heartbeat)

- Manager drafted CONTRACTS v0.1.1 addendum (f58f225): reservation_id
  threading, exactly-once outcome callbacks, halt→exit-only signal,
  reservation-aware restart reconciliation. v0.1.0 stays implemented
  baseline; implementation follows in E/V follow-ups. Names verified
  against landed code (submit_entry, note_fill/release/note_flat).
- E-002 heartbeat: install in progress, no blocker, inside ~30min bound;
  pin needs Python ≥3.12 (3.11 venv fast-rejected, logged); cp312–314
  wheels incl. macosx_arm64 confirmed; 156MB cp314 wheel downloading.
  Recorded ea2acae. worker3/v-001 moved to 4290233 base (diff intact).
- Checks: pytest 85 green; M1 stable (bar 154, third confirmation).

## Addendum — turns 12–14 (hygiene; E-002 approaching bound)

- Turn 12: evidence report refreshed (this file, turns 8–11 addenda);
  .gitignore now covers .venv-trial/ (verified via git check-ignore) so the
  E-002 trial venv can never be committed; heads-up sent to Worker 2.
  Pushed 8c6d6ce. Worker acks recorded (e75730f): E-001 confirm (Worker 2,
  reminded E-002 is active, worktree kept), V-002 confirm (Worker 3,
  corrected: manager-only integration).
- Turn 13: README updated to real, verified entry points (capture discover/
  capture, replay --in) + accepted scope (E-001, Q-001, V-002); every
  documented command executed live before commit. Pushed 5245107. Worker 3
  confirmed the integration correction (4a17566).
- Turn 14: D-009 tightened heartbeat semantics (worker-originated contact
  only; manager turns do not refresh). E-002 bound notice sent to Worker 2
  (~23min elapsed, lapses ~14:06Z): land install or file the
  documented-blocker finding. Pushed 84f03ef. Suite 85 green throughout.
- Standing waits: V-001R (Worker 1 go-ahead, 5th turn, no escalation yet —
  worker-side approvals have historically landed); E-002 verdict/blocker.

## Addendum — turn 17 (Q-001 draft review finding)

- Manager review of the accepted Q-001 S2–S5 drafts found F-Q001-01: S2–S4
  drafts do not match the directive's five candidates (S2 range-fade,
  S3 funding-tilt, S4 ATR breakout vs directive S2 trend-pullback, S3 range
  reversion, S4 failed-breakout reversal; S5 aligned). Recorded as D-010;
  Q-001 acceptance stands, correction rides with the S2–S5 follow-up task.
  FYI sent to Worker 1, no action required. E-002 bound lapses ~14:06Z.

## Addendum — turn 19 (E-002 bound lapsed)

- At ~14:06Z the E-002 ~30min bound lapsed with no install landed (trial
  venv pip-only 13M at last probe ~14:05Z, no outbox filing, no commits).
  Manager sent the lapse directive to Worker 2: stop install attempts, file
  E-002 completion now as either verdict-with-evidence or documented-blocker
  (commands+timestamps, output tail, environment). Either outcome closes
  E-002; next E-task dispatches after the filing.

## Addendum — turn 20 (E-002 finding emerging)

- Worker 2 heartbeat via fresh worktree evidence (~14:08Z): E-002 trial
  record taking shape in worker2/e-002 (uncommitted) — verdict
  "blocked-on-transfer": attempt 1 py3.11 rejected by requires-python
  >=3.12; attempt 2 pip wheels-only ~55MB of 156MB at ~96KB/s, stopped for
  uv; attempt 3 uv resolved 15 pkgs in 61s, 110MB+ cached, wheel never
  completed by the bound. Matrix + data README + new test updated; trial
  explicitly not counted as verification. No outbox filing yet — manager
  integration waits for the completion claim.

## Addendum — turn 21 (E-002 accepted + integrated)

- Worker 2 filed E-002 completion (outbox E-002.json + message, commit
  7be230d on worker2/e-002): verdict blocked-on-transfer, honest
  acceptance map (install/import/adapter items marked NOT OBTAINED),
  3 timestamped attempts, environment, repro commands, DEFER
  recommendation. Manager reproduced 52/52 in the w2 worktree,
  confirmed 0 tracked trial files and a clean main .venv, and
  cherry-picked 7be230d onto main: suite now 86/86 green.
- D-011: pin 1.231.0 stays PROPOSAL; no thin-SDK trigger (no upstream
  incompatibility demonstrated); retry deferred to better throughput or a
  pre-seeded cache. Next E-task (v0.1.1 execution + crash fix) dispatches
  after this integration.

## Addendum — turn 22 (E-003 dispatched; M1 reconfirmed)

- E-003 dispatched to Worker 2 (inbox msg-E-003-01, branch worker2/e-003):
  v0.1.1 execution side (reservation_id threading, exactly-once outcome
  callbacks via recording stub, halt→exit-only persistence, reservation
  reconciliation) + F-E001-02 fsync/orphan-sweep fix + F-E001-03/04 nits +
  F-E001-05 live note. Awaiting ack. E-002 acceptance message sent.
- M1 slice re-run post-E-002-integration (4th determinism confirmation):
  evidence_bar 154, 1 rejected, 1 fill, ambiguous-reconciled-no-duplicate
  — identical shape to prior runs. Suite 86/86.

## Addendum — turn 23 (shared v0.1.1 callback interface)

- Manager defined the shared execution→risk callback interface before E-003
  starts (interface-before-implementation duty): new manager-owned
  cryptobot.coordination.RiskOutcomeSink Protocol + conformance test.
  Signatures mirror the V-001 policy surface exactly (read from the w3
  worktree, not invented): note_fill(id), release(id)->bool,
  note_flat(). CONTRACTS addendum points to the module. FYI sent to
  Worker 2: build the E-003 recording stub against it. Suite 87/87.

## Addendum — turn 24 (evidence pipeline verified; README refreshed)

- Evidence generator tools/generate_evidence.py verified live: pytest 87
  green, M1 exit 0 in the same run.
- README refreshed to real entry points + accepted scope (E-002 accepted,
  E-003/V-001R in flight, 87 green). E-003 tracking schema key fixed
  (owner → owner_session, caught by the evidence generator). Pushed af6615b.

## Addendum — turn 25 (status vocabulary; W1 nudge)

- Worker status vocabulary formalised in coord/README (running /
  awaiting-go-ahead / idle / stalled); honest values applied: W1+W2
  awaiting-go-ahead, W3 idle. Previously all read running with no active work.
- V-001R nudge sent to Worker 1 (acked turn-10, ~31min without go-ahead;
  gates V-001 acceptance). Transport-accepted, receipt unconfirmed; no
  heartbeat refresh per D-009 (manager-originated). Suite 87/87, M1 exit 0.
  Pushed c7a8f25.

## Addendum — turn 26 (live tooling smoke; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads. tasks.json states consistent (V-001 review,
  V-001R/E-003 assigned, rest accepted).
- Live smoke of accepted E-001 tooling on current main, public API only:
  capture_public discover → 924 symbols seen, 525 USDT-perp trading,
  525 eligible, fetch_latency_ms 936.3; replay_public on the observed
  BTCUSDT sample exits clean. Tooling remains live-green.

## Addendum — turn 27 (contract conformance audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- Manager-run conformance audit on current main (all PASS):
  (1) no `import nautilus` / `from nautilus` in src/ or tools/ — only
  capability-matrix string labels + E-002 trial evidence, as designed
  (D-011: engine is stdlib-urllib + fake venue);
  (2) no BTCUSDT/ETHUSDT literals or symbol-list defaults in src/ or
  tools/ — no hardcoded whitelist, discovery stays dynamic (observed
  samples live only under data/observed/);
  (3) no api_key/secret/private-key/password patterns in src/ or tools/ —
  no credentials in code.

## Addendum — turn 28 (E-003 dependency-pointer check; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- Pre-start dependency check (E-003 has not started, so fixes are clean):
  CONTRACTS-cited import `from cryptobot.coordination import
  RiskOutcomeSink` verified resolvable from a fresh interpreter (re-exported
  in coordination/__init__.py, impl src/cryptobot/coordination/
  risk_outcomes.py). Gap found: inbox E-003.json named only "the addendum
  interface" without the concrete path (Protocol landed post-dispatch).
  Fixed: concrete pointer appended to the inbox dependencies (import path +
  file + conformance test tests/unit/test_coordination_risk_outcomes.py,
  filename verified present); one-line FYI sent to Worker 2, no re-ack needed.

## Addendum — turn 29 (V-001R pre-start pointer check; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- Symmetric pre-start check on V-001R (not started, fixes clean). Gap found:
  inbox cited w3 base cbb722f, but worker3/v-001 moved to 4290233 at turn-11;
  corrected the inbox to 4290233. Verified: w3 HEAD is 4290233 with the V-001
  diff intact; repro plan section exists (acceptance-review-q001-e001.md:79);
  the cited 34-test repro runs read-only (PYTHONDONTWRITEBYTECODE +
  no:cacheprovider, worktree PYTHONPATH) → 34 passed, and the worktree shows
  no new files after the probe. This run proves runnability only — V-001
  acceptance still requires Worker 1's independent V-001R filing. FYI + start
  request sent to Worker 1.
