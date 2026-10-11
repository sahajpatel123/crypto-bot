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

## Addendum — turn 30 (M1 report drift check; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- Committed-report drift check: fresh M1 run (/tmp/m1_fresh.json) vs
  committed reports/m1_report.json → MATCH (327 bytes, identical keys and
  values). The committed report is current, and this is the 5th determinism
  confirmation (evidence_bar 154 shape unchanged).

## Addendum — turn 31 (evidence gate re-verified; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- Evidence generator re-run on current main (6 turns + 5 commits after the
  turn-24 verification): exit 0, pytest 87 passed, M1 exit 0, task states
  consistent (V-001 review, V-001R/E-003 assigned, rest accepted), worker
  statuses honest (W1+W2 awaiting-go-ahead, W3 idle). README claims
  re-checked against reality (87 green, E-003/V-001R in flight) — current,
  no edit needed.

## Addendum — turn 32 (coord schema sweep; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- First full coord/ schema sweep (motivated by the turn-24 owner-key slip):
  14/14 JSON files parse; 12/12 inbox/outbox messages carry the README
  schema keys (incl. the turn-28/29 amended E-003/V-001R inboxes); 7/7
  tasks have valid state + owner; 3/3 workers have valid status +
  heartbeat + note. ALL PASS.

## Addendum — turn 33 (M1 report self-labels risk stub; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- Honesty gap found + fixed in the M1 artifact: the slice source labelled
  the risk gate a stub, but the committed report's `risk` field read plain
  `approved:budget=0.2500`, so a reader of the report alone could not tell.
  All three stub-emitted reasons now carry a `risk-stub:` prefix; the report
  was regenerated with the tool itself (not hand-edited) and now reads
  `risk-stub:approved:budget=0.2500`. No test asserted the old string.
  Suite 87/87, evidence gate exit 0, evidence_bar still 154. Note: this
  intentionally supersedes the turn-30 MATCH baseline — the only report
  delta is the added prefix.

## Addendum — turn 34 (M1 report self-labels fake venue; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- Same-class honesty fix as turn 33: the report recorded `fills: 1` with no
  venue label, so a reader could not tell the fill came from a fake. The
  report now carries `"venue": "slice-local-fake:ambiguous-once"` (the
  slice-local minimal fake, not E-001's order-manager venue — verified in
  source before labelling). Report regenerated with the tool; no test
  depends on report keys. Suite 87/87, evidence gate exit 0, bar 154,
  risk-stub label intact.

## Addendum — turn 35 (D-003 ownership self-audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 + V-001R still
  await worker-side go-aheads.
- Manager audited its own D-003 compliance: all non-merge commits on main
  touching worker-owned paths (strategies/features/research/market_data/
  execution/risk/accounting, capture/replay tools, specs, acceptance,
  fixtures). Five commits found, all authorised integrations, zero direct
  manager edits to worker-owned source: the E-001 trio (66dde7e, 7e2c6e7,
  77df093) is worker-authored on worker2/e-001, merged via 567dce3; 4290233
  (Q-001) carries full D-008 provenance (whisper-redshift, worker1/q-001 @
  2a33173, D-006 diff, 18/18 sha256); dbc4203 (E-002) names 7be230d from
  worker2/e-002. Nit (no action): dbc4203 implies rather than names the
  worker session. PASS.

## Addendum — turn 36 (liveness-rule + D-009 heartbeat audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~42min wait) still await worker-side
  go-aheads. W3 idle.
- Stall-rule sweep: zero tasks in `running` state (E-001/Q-001/E-002/V-002
  accepted; V-001 review; V-001R/E-003 assigned-not-started), so the D-009
  30-min stall rule trips on nothing. Correct: nothing has started-but-
  stalled; no stall marker is due. Observation (no action yet): D-009
  covers running tasks only — no aging rule exists for
  assigned-but-awaiting-go-ahead; the ~60min mark is the manager's stated
  point to raise the critical-path flag harder.
- D-009 heartbeat-integrity audit: all three `last_heartbeat_utc` values
  (W1 13:44:16Z, W2 14:11:55Z, W3 13:58:10Z) are worker-originated and
  unchanged by any manager turn. The turn-25 vocab commit (c7a8f25)
  reformatted workers.json but preserved all three values byte-identically
  (verified via diff). PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 37 (M2-readiness gap scan; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~43min wait) still await worker-side
  go-aheads. W3 idle.
- Manager scanned landed code against the M2 checklist (§9: connector
  proof, clean public live data, p50/p95/p99 data age + execution-path
  latency). Foundations present: capability matrix (E-001) + nautilus
  verdict (E-002, blocked-on-transfer); live discovery + klines capture
  emit single-shot `fetch_latency_ms` / `data_age_ms`. Gaps confirmed by
  grep over src/ + tools/: no percentile/quantile aggregation anywhere
  (no p50/p95/p99), no execution-path latency harness (fake venue only),
  and no sustained clean-capture run (single klines sample only, no
  book/trade streams). Forms the post-E-003 dispatch input; no M2 task
  dispatched yet.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 38 (coord referential-integrity sweep; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~44min wait) still await worker-side
  go-aheads. W3 idle.
- Cross-file consistency sweep over coord/: 7 tasks, 7 inbox files, 5
  outbox files. Every review/accepted task has its outbox filing; both
  assigned tasks (E-003, V-001R) correctly lack one; zero orphan
  inbox/outbox files. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 39 (worker-branch unreviewed-commit sweep; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~45min wait) still await worker-side
  go-aheads. W3 idle.
- Swept all four worker branches for commits ahead of main
  (`main..<branch>`): three at zero; only worker2/e-002 shows 7be230d,
  the already-accepted E-002 commit. Its three files (data/README.md,
  market_data/capabilities.py, test_market_data_matrix.py) are
  byte-identical on main, so no worker work is unreviewed or missing.
  Note: `git cherry` flags 7be230d as `+` (not patch-equivalent) because
  the dbc4203 integration commit bundled tracking updates (tasks,
  D-011, outbox) with the cherry-picked content — expected, not drift.
  PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 40 (decision-ledger staleness audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~46min wait) still await worker-side
  go-aheads. W3 idle.
- Re-read all of DECISIONS.md (D-001..D-011 + model-config note) against
  current state. Ten decisions hold as written; one staleness found and
  fixed: D-005's trigger wording ("deferred until the matrix lands") is
  spent — the matrix landed under E-001 — while D-011 keeps the pin
  decision re-deferred pending an import+adapter smoke pass. Annotated
  D-005 in place (manager-owned file): rationale stands, trigger wording
  superseded by D-011. No semantic change.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 41 (CONTRACTS code-alignment audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~47min wait) still await worker-side
  go-aheads. W3 idle.
- Audited every code claim in CONTRACTS.md against the reviewed sources.
  Confirmed: V-001 `Approved` already carries `reservation_id`
  (types.py:36, policy.py:106/117); `RiskOutcomeSink` on main mirrors
  the V-001 surface exactly (note_fill(id)->None, release(id)->bool,
  note_flat()->None; policy.py:124-136). One drift found and fixed in
  the manager-owned contract: the v0.1.0 risk-gate sketch read
  `evaluate(intent, account_state) -> Approved(reserved_risk, size)`
  while the reviewed implementation is `evaluate(intent, account) ->
  Approved(reserved_risk, notional_usdt, qty)`. Contract now matches
  reviewed code (V-001 still unaccepted; contract tracks it at
  acceptance if the shape moves).
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 42 (README command-verification sweep; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~48min wait) still await worker-side
  go-aheads. W3 idle.
- Ran every runnable command README documents, verbatim: m1 --help
  (exit 0); generate_evidence bare (exit 0, self-reports pytest 87 +
  M1 exit 0); capture discover live (exit 0, 924 seen/525 eligible,
  844.7ms — matches turn-26 counts); capture 5 klines to /tmp (exit 0,
  observed-public labelled, tree left clean); replay on the committed
  observed sample (exit 0, 60 events). Scope prose (accepted E-001/
  Q-001/V-002/E-002, in-flight E-003/V-001R, V-001 review-passed)
  matches tasks.json. No README fix needed. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 43 (V-002 verdict re-confirmation; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~49min wait) still await worker-side
  go-aheads. W3 idle.
- Re-confirmed the accepted V-002 CLEAN verdict on current main two
  ways: (1) S1 files (strategies, features, specs/strategies, strategy
  tests) are byte-unchanged since the V-002 base 4290233, so the
  verdict carries by construction; (2) re-ran the turn-10b probe
  (/tmp/v002_probe.py): ALL 6 functional checks PASS with identical
  values (fire_bar_t=154, sha d89576a1...). PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 44 (Q-001 hash re-verification; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~50min wait) still await worker-side
  go-aheads. W3 idle.
- Re-verified the accepted Q-001 deliverable on current main: all 18
  recorded sha256 hashes MATCH, zero missing, zero drift — the worker's
  files are byte-intact since acceptance. Record correction: the hashes
  live at top-level `file_hashes_sha256` in coord/outbox/Q-001.json,
  not under `body` (a first attempt with the wrong path raised
  KeyError; the file is authoritative). PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 45 (E-001 acceptance re-confirmation; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~51min wait) still await worker-side
  go-aheads. W3 idle.
- Re-confirmed the accepted E-001 on current main: owned test subset
  (execution + market-data) 43 passed; replay of the committed
  observed sample deterministic across two runs AND its canonical
  `replay_sha256` (772a9163...) exactly equals the turn-7c acceptance
  record. A naive stdout hash differed (3bb37050) — investigated, not
  drift: stdout wraps the digest with path/formatting bytes. Observed
  samples untouched since 77df093. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 46 (E-002/D-011 re-confirmation; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~52min wait) still await worker-side
  go-aheads. W3 idle.
- Re-confirmed the accepted E-002 on current main: capability-matrix test
  standalone 7 passed; verdict string `blocked-on-transfer` intact in
  capabilities.py with PyPI pins labelled proposal/unverified; zero
  `import`/`from nautilus` statements anywhere in src/tools/tests. D-011
  holds — engine remains stdlib-urllib + fake venue, no accidental
  adoption. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 47 (V-001 review-pass re-confirmation; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~53min wait) still await worker-side
  go-aheads. W3 idle.
- Re-confirmed the review-passed V-001 at its current location: the 34
  acceptance tests (risk gates/sizing/halts/profit, ledger, determinism)
  still pass 34/34 in the W3 worktree
  (PYTHONPATH=/tmp/cryto-bot-w3/src, pytest tests/acceptance/
  tests/fixtures/). Review-pass has not rotted; the V-001R repro base is
  stable. Note: V-001 files remain uncommitted in /tmp/cryto-bot-w3 —
  integration into main still gated on V-001R per the no-self-cert rule.
  PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 48 (M1 slice re-run; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~54min wait) still await worker-side
  go-aheads. W3 idle.
- Re-ran the M1 vertical slice on current main: exit 0 with values
  identical to acceptance — S1 ARM_BASE fires at bar 154, 1 rejected
  stale trade, 1 fill with ambiguous-once fault recovered
  (ambiguous-reconciled-no-duplicate), self-labels intact
  (`risk-stub:approved:budget=0.2500`,
  `slice-local-fake:ambiguous-once`). The runnable slice survived all
  subsequent commits unchanged. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 49 (live discovery re-probe; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~54min wait) still await worker-side
  go-aheads. W3 idle.
- Re-probed live Binance USD-M discovery (`capture_public.py discover`):
  924 symbols seen / 525 USDT-perp trading / 525 eligible, exactly
  matching the recorded 924/525 headline values; fetch latency 1115.8ms
  (same ~1s class as the recorded 844-936ms). The public-data path
  still works and the universe is unchanged. (data/README's "524" is a
  20-USDT-min-notional filtered variant, not drift.) PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 50 (pending-inbox completeness audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~55min wait) still await worker-side
  go-aheads. W3 idle.
- Audited both pending inbox files for completeness and freshness.
  E-003: objective, acceptance (reservation threading, exactly-once
  outcome callbacks), allowed paths (execution + exec tests), branch
  (worker2/e-003 from origin/main), contract v0.1.1 addendum,
  evidence list — all present; zero commits since 14:11Z dispatch
  touch its allowed paths, so no drift. V-001R: objective,
  acceptance (34-test read-only repro + halt case + R-001..R-012),
  allowed paths limited to its own outbox per D-006, read-only note,
  evidence list — all present; repro base verified 34/34 at turn 47.
  Both tasks are complete, fresh, and escalation-ready. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 51 (outbox-to-board consistency audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~56min wait) still await worker-side
  go-aheads. W3 idle.
- Compared each outbox filing's claimed state against tasks.json: E-001,
  E-002, V-002 show outbox=review with board=accepted — the expected
  pattern (worker claims review, manager accepts after inspection).
  V-001 shows review/review, correctly awaiting V-001R. E-002's
  verdict=blocked-on-transfer matches the D-011 record. Q-001's older
  outbox shape lacks body.state but carries results + hashes with
  board=accepted — cosmetic format variance, acceptance stands. All 7
  board tasks have states, zero orphans. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 52 (push-chain verification; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~57min wait) still await worker-side
  go-aheads. W3 idle.
- Independently verified the push chain: `git ls-remote origin main`
  returns b7edc7f, byte-identical to local HEAD — every evidence
  commit through turn 51 has landed on the remote, not just in the
  local clone. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 53 (klines capture freshness probe; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~58min wait) still await worker-side
  go-aheads. W3 idle.
- Fresh klines capture probe (`capture ... --limit 5` to /tmp): 5 kline
  events + header + footer, header keys byte-identical to the committed
  60-kline sample, gaps 0. stale_count 4 / max lag ~3.8min is the known
  REST-backfill-age property, not feed degradation. The klines endpoint
  path still works and the record shape is stable. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 54 (D-010 correction-input verification; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~58min wait) still await worker-side
  go-aheads. W3 idle.
- Pre-verified the D-010 correction input for the post-V-001R S2-S5
  follow-up: all four draft files present on main with titles matching
  the recorded deviations (S2 range-fade, S3 funding-tilt scalp, S4 ATR
  volatility breakout, S5 micro-imbalance scalp), and the D-010 ledger
  text accurately describes each deviation vs the directive's S2
  trend-pullback / S3 reversion / S4 failed-breakout / S5 order-flow
  hypotheses. The correction dispatch can quote this record verbatim.
  PASS. (No task dispatched — follow-up stays gated on V-001R.)
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 55 (E-003 dependency readiness; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~59min wait) still await worker-side
  go-aheads. W3 idle.
- Verified E-003's sink dependency is start-ready on main:
  `RiskOutcomeSink` imports cleanly from
  `cryptobot.coordination.risk_outcomes` and exposes exactly the three
  methods the E-003 acceptance names — `note_fill(reservation_id)`,
  `release(reservation_id) -> bool`, `note_flat()`. No missing import
  or surface gap will block W2's start. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 56 (evidence-citation integrity; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~60min wait) still await worker-side
  go-aheads. W3 idle.
- Verified evidence-report citation integrity: all 16 commit SHAs cited
  across recent addenda and tracking notes resolve to real commits via
  `git cat-file -t` (turns 45-55 tips, 4290233 replay base, 7be230d
  E-002, 2a33173, 77df093 observed-sample commit, cbb722f stale-base
  reference). No dangling or mistyped citation. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 57 (remote-ref sweep; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2, acked
  14:11Z) + V-001R (W1, acked 13:44Z, ~61min wait) still await worker-side
  go-aheads. W3 idle. FLAG: V-001R's wait has crossed ~60min; no
  manager-side unblock exists (inbox complete per turn 50, repro base
  verified per turn 47) — activation depends on the worker session.
- Swept remote refs: origin holds only main (+HEAD) — no worker
  branches, no hidden unreviewed commits. Local worker branches are
  exactly the four previously reviewed (worker1/q-001, worker2/e-001,
  worker2/e-002, worker3/v-001); no worker2/e-003 exists anywhere yet,
  consistent with E-003 not started. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 58 (V-001R coverage audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~62min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag from turn 57 stands; no manager-side unblock
  exists.
- Audited V-001R dispatch scope against V-001's 5 acceptance_mapped
  claims: adversarial fixtures, deterministic policy, repro plan, and
  risk invariants are all worker-covered (34-test repro, determinism
  re-run, hand halt case, R-001..R-012 report). The 5th item —
  Q-001/E-001 interface review — is a prose review doc covered by
  manager review only (turn-9 review-pass + turn-41 alignment audit),
  not worker reproduction; acceptable by nature, recorded here. No
  dispatch change: V-001R is already acked. PASS with noted exception.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 59 (E-003 coverage audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~63min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Audited E-003 dispatch scope against its sources: all 4 CONTRACTS
  v0.1.1 execution items (reservation_id, note_fill/release/note_flat,
  halt→exit-only, reconciliation) map to acceptance 1-3; F-E001-02 to
  acceptance 4; F-E001-03/04/05 to acceptance 5; F-E001-01 correctly
  noted closed by the addendum; RiskOutcomeSink dependency pointer
  matches the turn-55 import check; allowed_paths stay inside W2
  ownership (D-003). 6/6 acceptance items sourced. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 60 (M1 report freshness; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~64min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Audited committed reports/m1_report.json against a fresh slice run:
  JSON-identical (bar 154, notional 145.38634456685105, stub/fake
  labels, ambiguous-reconciled). The committed M1 artifact is not
  stale. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 61 (Q-001 verbatim repro; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~65min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Ran all 3 Q-001 claimed repro commands verbatim in /tmp/cryto-bot-w1:
  focused 34 passed, full 85 passed, slice green (1 reject / 1 fill /
  ambiguous-reconciled) — all match the outbox claims. (Slice shows
  the older pre-rewire risk label/notional, as expected at W1's base
  2a33173.) PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 62 (tree-hygiene sweep; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~66min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Swept tracked tree: zero __pycache__/.pyc/.venv/node_modules/
  .DS_Store entries in git ls-files. Decision ledger contiguous
  D-001..D-011, no gaps, each defined once (list format; D-005/D-011
  cross-refs are intentional prose). PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 63 (E-002 suite stability; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~67min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Re-ran E-002's claimed full-suite repro verbatim in /tmp/cryto-bot-w2
  (main venv + worktree PYTHONPATH): 52 passed, identical to the prior
  52/52 record — no drift in the accepted E-002 tree. (The nautilus
  pip-install step was not re-attempted per D-011 deferral.) PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 64 (data-manifest audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~68min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Audited data/observed against data/README: both files present,
  discovery values exactly match (924/525/524, 928ms), klines shape
  matches (header + 60 klines + footer, 59 closed, 0 gaps) with
  input_class observed-public. BUT the README blanket claim "every
  recording is labelled observed-public in its header" is false for
  the discovery JSON — it carries no label field at all. New minor
  finding F-DATA-01 (doc-vs-data label gap); data/README is W2-owned
  (D-003) so no direct edit — queued for the next W2 dispatch after
  E-003. PARTIAL PASS with finding.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 65 (F-DATA-01 scoping; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~69min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Scoped F-DATA-01 in code: discovery_summary() (market_data/
  discovery.py) emits no input_class field — the observed-public label
  machinery exists only in the recorder path (klines JSONL). Fix is
  either (a) one-line code: add input_class INPUT_OBSERVED to the
  summary + refresh the committed sample, or (b) doc-only: narrow the
  README claim to recording files. All touched files are W2-owned
  (D-003); manager recommendation is (a), W2 decides. Dispatch-ready
  input for the post-E-003 W2 task. PASS (scoping).
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 66 (V-002 check-5 re-verified; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~70min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Re-ran V-002's no-confidence-language sweep on current main
  (strategies/features/research/specs/tests): exactly 1 match —
  S1.md line 124 "No confidence percentages anywhere", a prohibition
  sentence, not a violation. Zero hand-assigned probabilities or
  win-rate claims. Check-5 substance holds. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 67 (board-vocabulary audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~71min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Audited board against coord/README vocabulary: all 7 task states
  (4 accepted, 1 review, 2 assigned) and all 3 worker statuses
  (2 awaiting-go-ahead, 1 idle) fall inside the documented sets;
  every task owner resolves to a workers.json entry with the
  expected W1/W2/W3 mapping; statuses cohere with assignments
  (W3 idle has no active task). PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 68 (live universe re-probe; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~72min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Re-probed live USDT-perp discovery: 924/525/524 at 1166ms, and the
  live 525-symbol set diffs to zero adds/removes against the committed
  sample — no listing drift, sample still representative. (First diff
  attempt used the wrong record shape; corrected to plain symbol
  strings.) PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 69 (second-symbol klines probe; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~78min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Captured ETHUSDT 1m x5 (/tmp/kl69.jsonl, new symbol beyond the
  turn-53 BTCUSDT probe): gaps 0, 4 closed + 1 forming, fetch latency
  267ms, data age ~40s, header labelled observed-public. Kept in /tmp
  (data/ is W2-owned per D-003). My first verification one-liner used
  the wrong record key; recomputed against exchange_open_ms. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 70 (fresh-capture replay determinism; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~79min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Replayed the fresh turn-69 ETHUSDT capture twice through
  replay_public: deterministic=true, replay_sha256 ee2fd38f identical
  across runs, gaps empty — the replayer is stable on a second,
  newly-captured observed file, not just the committed sample. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 71 (contract-version coherence; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~80min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Swept contract-version pins: all 12 coord inbox/outbox files pin a
  version; v0.1.0 baseline cited 30x, v0.1.1 7x. Placement is correct:
  E-003 inbox pins v0.1.1 (4x, implements the addendum), V-001 outbox
  cites it only as "addendum proposed", workers.json only in tracking
  notes, and V-001R inbox pins v0.1.0 only (verbatim repro of the V-001
  baseline). CONTRACTS.md carries both baseline + addendum. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 72 (REST latency baseline; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1, ~81min wait) still await worker-side go-aheads. W3 idle.
  The ~60min V-001R flag (turn 57) stands; no manager-side unblock.
- Measured Binance USD-M REST round-trip (/ping, n=7) from this host:
  min 223ms / med 233ms / max 332ms — consistent with earlier fetch
  latencies (267ms klines, ~1.1s full discovery) and a first data point
  for M2 execution-path latency evidence. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 73 (heartbeat-age check; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1) still await worker-side go-aheads. W3 idle.
- Heartbeat ages per D-009 (worker-originated contact only): W2
  cloud-vega 47min, W3 cool-amalthea 60min, W1 whisper-redshift 74min.
  No stall violation — the 30-min rule covers running tasks only and
  none are running. The standing flag remains: no aging rule exists
  for assigned-awaiting-go-ahead (V-001R wait longest). PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 74 (M1 report semantic audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1) still await worker-side go-aheads. W3 idle.
- Audited the committed m1_report.json against M1 milestone claims
  (beyond the turn-61 byte-freshness check): rejected_count=1,
  recovery=ambiguous-reconciled-no-duplicate, s1_source SYNTH_V1 seed
  11 bar 154, risk=risk-stub:approved:budget=0.2500,
  venue=slice-local-fake:ambiguous-once, synthetic=true. All 6
  content checks PASS — rejected trade, fault recovery, and honesty
  labels all present in the committed artifact.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 75 (D-003 ongoing compliance; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1) still await worker-side go-aheads. W3 idle.
- Re-checked D-003 file-ownership compliance for all main commits
  since the turn-34 audit (08bc082): only reports/evidence_m0_m1.md
  (39 commits), CONTRACTS.md, and DECISIONS.md were touched — all
  manager-owned. Zero worker-owned files modified. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 76 (multi-symbol data-age snapshot; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1) still await worker-side go-aheads. W3 idle.
- Captured 1m x3 klines for BTC/SOL/BNBUSDT (/tmp/age76_*.jsonl):
  data age ~10-11s each, fetch latency 226-279ms (consistent with the
  turn-72 /ping baseline), gaps 0 on all three. A second M2 data point
  showing age/latency stability across symbols. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 77 (worktree-vs-main drift check; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1) still await worker-side go-aheads. W3 idle.
- Compared worker worktrees against integrated main: W1's Q-001 files
  (strategies/features/research/specs + 4 test files) are byte-identical
  on both sides — faithful integration, no post-landing edits. W3's
  V-001 diff (risk/, accounting/, specs/acceptance*) exists only in the
  worktree with nothing on main to diverge from — correct pending
  state awaiting V-001R. Noted one empty untracked risk/ scaffold dir
  on main (no tracked files, harmless). Zero drift. PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 78 (peer-to-worker mapping audit; still awaiting go-aheads)

- No new outbox filings, commits, or worker activity; E-003 (W2) +
  V-001R (W1) still await worker-side go-aheads. W3 idle.
- Audited live peer sessions against workers.json: the 3 reachable
  cryto-bot sessions exactly match the board — whisper-redshift=W1
  Quant, cloud-vega=W2 Data/Execution, cool-amalthea=W3 Risk — with
  no missing or extra sessions. (Role field is proposed_role, not
  role; first probe used the wrong key.) PASS.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 79 (E-003 STARTED; V-001R still awaiting go-ahead)

- Worker 2 heartbeat: E-003 STARTED on new branch worker2/e-003 from
  0d90e6f (confirmed in /tmp/cryto-bot-w2 worktree, clean tree, shared
  tree untouched). Plan: reservations/callbacks -> halt->exit-only/
  reconciliation -> F-E001-02..05 -> tests/outbox. Board updated:
  E-003 assigned -> running, W2 awaiting-go-ahead -> running, heartbeat
  15:02:32Z; ack sent (transport handoff, delivery unconfirmed).
  V-001R (W1) still awaiting go-ahead; W3 idle.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 80 (E-003 in progress, scope-compliant; V-001R waiting)

- W2 actively implementing: worker2/e-003 worktree shows uncommitted
  M src/cryptobot/execution/fake_venue.py (+12/-1), inside the E-003
  allowed paths (src/cryptobot/execution/*). Read-only stat check, no
  interference. No outbox filing yet; E-003 stays running. V-001R (W1)
  still awaiting go-ahead; W3 idle. No action needed.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 81 (E-003 progressing, scope-compliant; V-001R waiting)

- W2 progressing on worker2/e-003: uncommitted edits now span
  fake_venue.py (+12/-1) and order_manager.py (+39/-6), both inside
  E-003 allowed paths. Read-only stat check, no interference. No
  outbox filing yet; E-003 stays running. V-001R (W1) still awaiting
  go-ahead; W3 idle. No action needed.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 82 (E-003 advancing; draft-hash baseline; V-001R waiting)

- W2 advancing on worker2/e-003: order_manager.py now +111/-6
  (was +39), fake_venue.py unchanged at +12/-1 — still 2 files, both
  inside E-003 allowed paths. Read-only stat check, no interference.
  No outbox filing yet; E-003 stays running. V-001R (W1) still
  awaiting go-ahead; W3 idle.
- Recorded first sha256 baseline for the S2-S5 drafts (D-010
  correction inputs): S2 09e22e7a78f2, S3 4e5618eff6cc, S4 28bcded70d29,
  S5 147e5d2583ed — stability verifiable from here.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 83 (E-003 interface alignment; V-001R waiting)

- W2 still advancing on worker2/e-003: order_manager.py now +163
  (was +111), fake_venue.py steady. Read-only WIP scan shows exact
  v0.1.1 vocabulary in the diff: reservation_id 42x, note_fill/
  note_flat, release, exit_only/exit-only, RiskOutcomeSink 4x — aligned
  with the shared Protocol, no interface drift. No interference, no
  outbox filing yet; E-003 stays running. V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 84 (E-003 test phase; V-001R waiting)

- W2 entered the test phase on worker2/e-003: new untracked
  tests/unit/test_execution_handoff.py (267 lines), matching the E-003
  allowed test glob; implementation diff steady at fake_venue +12/-1
  and order_manager +163. Read-only checks, no interference. No outbox
  filing yet; E-003 stays running. V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Suite 87/87, evidence gate exit 0.

## Addendum — turn 85 (E-003 ACCEPTED + integrated; V-001R waiting)

- W2 filed E-003 completion (commit d54a251, 4 files +432/-12, all in
  allowed paths; outbox E-003.json with 6/6 acceptance mapping).
  Manager review reproduced every claim: 104/104 green twice in the
  W2 worktree, M1 slice exit 0 with canonical output, isinstance
  assertion + halt/orphan/recover APIs present, F-E001-04 migration
  is one setup line with intent preserved, zero risk-file edits.
  One trivial note: "18 new" counts 17 collected tests (87+17=104
  reconciles). Verdict ACCEPT; merged worker2/e-003 into main.
  E-003 running -> accepted; W2 running -> idle (F-DATA-01 queued
  next). V-001R (W1) still awaiting go-ahead; W3 idle.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 86 (E-004 dispatched to W2; F-DATA-01 unblocked)
- No new outbox filings, commits, or worker activity before dispatch;
  tree clean on main at 8cb875c. W2 idle post-E-003; V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Dispatched E-004 (F-DATA-01 discovery-label fix) to W2: inbox
  coord/inbox/E-004.json (msg-E-004-01), branch worker2/e-004 from
  8cb875c, acceptance = close the gap via (a) input_class
  INPUT_OBSERVED + refreshed live sample (preferred) or (b) narrowed
  README claim, W2 decides with justification. Board: E-004 assigned,
  W2 idle -> awaiting-go-ahead (ack pending). Dispatch message sent to
  cloud-vega (transport handoff, delivery unconfirmed); durable record
  is inbox + board.
- D-009 note: manager dispatch timestamp was briefly written to W2's
  last_heartbeat_utc and immediately reverted to 15:02:32Z — manager
  contact is not worker-originated contact.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 87 (E-004 dispatch self-check PASS; still awaiting acks)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 949b01d. E-004 (W2, ack pending) + V-001R (W1, awaiting
  go-ahead) outstanding; W3 idle. Peers reachable 3/3.
- Self-verified the turn-86 dispatch before W2 reads it: all 8 inbox
  messages carry the required keys + body fields; all 8 task_ids link
  to a board entry whose owner_session resolves to a known worker;
  E-004 assigned/cloud-vega, W2 awaiting-go-ahead, heartbeat intact
  at 15:02:32Z (D-009 clean); branch base 8cb875c exists and is an
  ancestor of HEAD. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 87b (E-004 acked by W2; not started)
- Worker-originated ack (cloud-vega): E-004 received, inbox + F-DATA-01
  scoping read. Scope decision option (a) — label discovery_summary()
  output INPUT_OBSERVED, refresh the committed sample from a live run
  with drift check, pin the label in a test. Justification: discovery
  output genuinely is observed-public venue data, so labelling preserves
  the README guarantee. Branch worker2/e-004 from 8cb875c as directed.
  NOT STARTED — W2 surfacing to its user for go-ahead.
- Board: E-004 assigned (ack recorded, option a); W2 heartbeat updated
  (worker-originated, D-009), still awaiting-go-ahead. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 88 (M1 slice re-run green on post-E-003 tip)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a4dde68. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Re-ran the canonical M1 slice on the current tip (first run since
  the E-003 merge landed on main): exit 0, evidence_bar 154,
  rejected_count 1, recovery ambiguous-reconciled-no-duplicate, with
  risk-stub + slice-local-fake honesty labels intact. The merged
  v0.1.1 handoff code does not regress the runnable slice. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 89 (live discovery re-probe: 924/525, zero drift)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b171c0f. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Fresh public discover run: 924 symbols seen, 525 USDT-perp trading,
  525 eligible; membership identical to the committed
  discovery_20261011T131845Z sample (added 0, removed 0). Fetch
  latency 1192ms (single-sample point, not a percentile). PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 90 (SOL capture + replay determinism PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5bdee49. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Fresh public SOLUSDT 1m x60 capture: 62 rows (header + 60 bars +
  trailer), header labelled observed-public, 60/60 bars contiguous
  (gaps 0, span check true). stale_count 59 / max_lag ~3540s is
  expected REST-backfill age (bars up to 60min old by construction),
  not a feed-health signal.
- Replay determinism on the fresh file: two runs exit 0 with byte-
  identical stdout, replay_sha256 6c420e09.... PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 91 (REST latency re-sampled; peers 3/3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4bced29. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
  Worker peers reachable 3/3, no extras.
- Fresh fapi /ping sample n=9: min 242, med 248, max 283, mean 254ms
  (prior med 233ms n=7). Same ~250ms class; small-sample point
  comparison only, not a percentile claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 92 (V-001 review-pass re-confirmed 34/34)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 55a1eff. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Re-ran the V-001 acceptance battery read-only from the W3 worktree
  (PYTHONPATH to W3 src, no cache writes): 34/34 passed, and the W3
  tracked tree shows zero modifications afterwards. The pending V-001
  review-pass stands unchanged; still gated on the independent V-001R
  repro. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 93 (D-003 compliance re-audit PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8ad852c. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- D-003 re-audit since the turn-75 checkpoint (6430e9b): changed files
  are coord/* + reports/* (manager-owned) plus exactly 4 W2-owned
  files (execution/fake_venue.py, order_manager.py and 2 handoff
  tests), touched solely by W2's own commit d54a251, integrated via
  manager merge 28461d3. No manager-authored edit to any worker-owned
  file; no competing edits. PASS.
- Record correction: 08bc082 is the Turn-35 D-003 audit, not turn-75;
  the turn-75 checkpoint is 6430e9b ("only manager-owned files since
  08bc082"). This audit ran against the correct anchor.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 94 (liveness + stall-rule audit PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at f692a01. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Heartbeat ages: W2 5.5min (fresh E-004 ack), W3 77.9min (idle, no
  rule applies), W1 91.8min (awaiting-go-ahead). Zero running tasks,
  so the 30-min stall rule (running only, D-009) triggers nothing.
  The W1/V-001R wait remains the longest outstanding item with no
  aging rule for assigned-awaiting-go-ahead — standing escalation
  point, no manager-side unblock. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 95 (remote-ref sweep PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at c57ead8. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Remote sweep: origin carries only refs/heads/main at c57ead8,
  identical to local HEAD and origin/main. Worker branches
  (worker1/q-001, worker2/e-001/e-002/e-003, worker3/v-001) remain
  local-only as designed; no stray or unexpected remote refs. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 96 (S2-S5 draft-hash stability 4/4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2e45b25. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Re-verified the S2-S5 drafts against the turn-82 sha256 baseline
  (D-010 correction inputs): S2 09e22e7a78f2, S3 4e5618eff6cc, S4
  28bcded70d29, S5 147e5d2583ed — 4/4 MATCH, drafts unmodified. The
  pending D-010 correction still applies to exactly these texts. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 97 (M1 report freshness PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 63185a1. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Fresh M1 slice run (exit 0) byte-compares equal to the filed
  reports/m1_report.json on all 11 keys (bar 154, 1 rejected,
  risk-stub, slice-local-fake, recovery clean). The filed report is
  current with the post-E-003 code; no refresh needed. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 98 (BNBUSDT capture observation PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1a010b5. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Live BNBUSDT 1m x30 capture (observed-public): n=30 data rows,
  gaps=0 (independent recompute), closed=29, data_age 53.8s,
  fetch_latency 244.5ms. Second-symbol M2 data point; REST-backfill
  age != feed health. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 99 (BNBUSDT replay determinism PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5273323. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- BNB capture replayed twice via replay_public: outputs byte-identical
  (stdout sha c528b2826249), events 30, gaps [], replay_sha256
  fb836e50..., deterministic=true. Second-symbol replay confirms the
  tool path. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 100 (S1 evaluation determinism PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b040aaa. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- S1 baseline double-evaluation (SYNTH_V1 long, seed 11, bars 120-239,
  ARM_BASE, long+short): identical decision digests 925a7df1... both
  runs; 6 intent fires, matching the FIRE_BARS [154..159] pin. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 101 (synthetic fixture seed-determinism PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at f6f54b6. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- generate_fixture: same seed+scenario twice -> identical digest
  f916bdaa0e50 (240 bars); different seed -> 79a9881ba2b8; different
  scenario -> 24118ca70580. Seeded replay stable, variants distinct.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 102 (exchange clock-offset sample PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at fd03efa. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- USD-M /fapi/v1/time vs local mid-request time, n=7: offsets
  +36.8..+84.5ms, median +47.6ms; median RTT 239.8ms. Clocks agree
  within ~0.1s; M2 timestamp-ordering datum. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 103 (BTCUSDT depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at da6c96e. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public depth limit=20 (fetch 251ms): spread 0.01bps, top-20 bid
  $358k / ask $657k notional, all within 5bps of touch. Single
  snapshot only -- an M2 depth-at-size datum, not a liquidity claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 104 (BTCUSDT funding snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b4541e8. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public premiumIndex (fetch 239ms): mark 83100.68, index 83144.36,
  lastFundingRate 0.00154%, next funding 16:00 UTC (in ~38min).
  Single-sample cost-accounting datum, not a funding model. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 105 (BTCUSDT contract-filter snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ca9208e. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- exchangeInfo (fetch 1114ms): BTCUSDT TRADING PERPETUAL, tick 0.10,
  minQty/step 0.001, MIN_NOTIONAL 50 USDT. Illustrative check only:
  50 USDT fits under a ~Rs5000 planned notional at an assumed ~83
  INR/USD (FX assumption, not a measured rate). Single-sample datum.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 106 (BTCUSDT 24h ticker snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 71191ed. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public 24h ticker (fetch 224ms): last 83100.9, range 0.58%,
  change +0.208%, quote volume $2.81B, 733k trades. Single-sample
  activity datum, not a regime or eligibility claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 107 (BTCUSDT trade-tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d351328. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public aggTrades x100 (fetch 287ms): span 2.8s, taker-buy 96/100,
  median trade $166, max $155,578. Single-sample microstructure
  datum, not a flow signal or fill assumption. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 108 (BTCUSDT open-interest snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5186306. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterest (fetch 328ms): 93,287.991 BTC (~$7.75B at the
  ~83100 reference from turn 107's tape sample). Single-sample datum,
  not a positioning or liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 109 (ETHUSDT depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at f450e1e. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public depth limit=20 (fetch 306ms): spread 0.04bps, top-20 bid
  $827k / ask $278k notional. Second-symbol depth datum alongside
  turn-103 BTC; single snapshot, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 110 (SOLUSDT funding snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 591a75f. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public premiumIndex (fetch 257ms): last funding 0.00566%, next
  16:00 UTC. Second-symbol funding datum alongside turn-104 BTC;
  single snapshot, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 111 (ETHUSDT 24h ticker snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1342bea. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public ticker/24hr (fetch 265ms): last 2507.98, 24h range 0.89%,
  $2.49B quote vol, 1,216,557 trades. Second-symbol ticker datum
  alongside turn-106 BTC; single snapshot, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 112 (SOLUSDT trade-tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d83b8b5. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public aggTrades x100 (fetch 321ms): span 37.3s, taker-buy 58/100,
  median notional $229. Second-symbol tape datum alongside turn-107
  BTC; single snapshot, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 113 (ETHUSDT open-interest snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9317173. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterest (fetch 312ms): 2,328,479.506 ETH (~$5.84B at
  the turn-111 ticker reference ~2508, not measured this turn).
  Second-symbol OI datum alongside turn-108 BTC; single snapshot,
  not a positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 114 (BNBUSDT funding snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 07095ed. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public premiumIndex (fetch 263ms): last funding 0.00000%, next
  16:00 UTC (mark 751.26). Third-symbol funding datum alongside
  BTC/SOL turns; single snapshot, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 115 (SOLUSDT 24h ticker snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at cb1c97c. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public ticker/24hr (fetch 252ms): last 109.88, 24h range 1.60%,
  $0.65B quote vol, 774,517 trades. Third-symbol ticker datum
  alongside BTC/ETH turns; single snapshot, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 116 (SOLUSDT depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 0d9db15. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public depth limit=20 (fetch 275ms): spread 0.91bps, top-20 bid
  $4.21M / ask $5.48M notional. Third-symbol depth datum alongside
  BTC/ETH turns; single snapshot, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 117 (SOLUSDT open-interest snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e23cfce. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterest (fetch 242ms): 8,628,764.790 SOL (~$948.1M at
  the turn-115 ticker reference ~109.88, not measured this turn).
  Third-symbol OI datum alongside BTC/ETH turns; single snapshot,
  not a positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 118 (BNBUSDT 24h ticker snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b285a96. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public ticker/24hr (fetch 252ms): last 750.84, 24h range 0.95%,
  $124.2M quote vol, 368,903 trades. Fourth-symbol ticker datum
  alongside BTC/ETH/SOL turns; single snapshot, not a regime claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 119 (ETHUSDT trade-tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5dd5ed5. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public aggTrades x100 (fetch 347ms): span 26.7s, taker-buy 60/100,
  median notional $1,756. Third-symbol tape datum alongside BTC/SOL
  turns; single snapshot, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 120 (BNBUSDT depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b402ff7. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public depth limit=20 (fetch 243ms): spread 0.13bps, top-20 bid
  $111,597 / ask $213,429 notional. Fourth-symbol depth datum
  alongside BTC/ETH/SOL turns; single snapshot, not a liquidity
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 121 (BNBUSDT trade-tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7d0c29e. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public aggTrades x100 (fetch 247ms): span 60.3s, taker-buy 37/100,
  median notional $120. Fourth-symbol tape datum alongside
  BTC/SOL/ETH turns; single snapshot, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 122 (BNBUSDT open-interest snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1c65dbe. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterest (fetch 636ms with ticker): 561,856 BNB at
  $750.93 ~= $421.9M notional; completes the BNB set (funding/
  ticker/depth/tape/OI) alongside BTC/SOL/ETH. Single snapshot,
  not a positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 123 (funding-rate sweep PASS, capped sample)
- No new outbox filings, commits, or worker activity; tree clean on
  main at cec6839. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public fundingRate, no symbol param (fetch 276ms): endpoint
  returned 100 rows (default cap), 95 USDT-denominated. Distribution
  (%): min -0.1236, p50 0.00500, max 0.0214; 84 positive, 11
  negative. This is a capped 100-row sample, NOT a full-universe
  census (universe is larger; discovery must paginate or use
  exchangeInfo). Single snapshot, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 124 (USDT-perp universe census PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ad66e13. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public exchangeInfo (fetch 687ms): 924 symbols total —
  703 PERPETUAL, 217 TRADIFI_PERPETUAL, 2 quarterly each. Filtered
  USDT-margined+USDT-quoted PERPETUAL in TRADING status: 525.
  Supersedes turn-123's capped 100-row funding sample as the
  universe count; confirms TradFi/quarterly exclusion matters for
  dynamic discovery (no hardcoded whitelist). Single-sample
  metadata census, not an eligibility/liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 125 (min-notional distribution PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 6895293. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public exchangeInfo MIN_NOTIONAL across the 525-symbol universe
  (fetch 1118ms): $5.00 on 519 symbols, $20.00 on 5, $50.00 on 1;
  min=p50=$5.00, max=$50.00. Feeds M2 admissible-order-size work
  (all minima far below the illustrative ~Rs25 planned-risk scale
  at order level; sizing still needs depth/cost evidence per
  market). Metadata snapshot, not a sizing claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 126 (universe spread snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 364a9ec. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public bookTicker (fetch 418ms): 791 rows, 741 USDT-suffixed
  (raw book rows, NOT filtered to the 525-eligible TRADING census;
  includes other statuses). Spread bps: min 0.01, p10 0.71,
  p50 3.90, p90 8.44, max 34.1. Feeds M2 cost modelling at order
  level; single snapshot, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 127 (universe 24h-volume snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8cb5250. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public ticker/24hr (fetch 390ms): 789 rows, 741 USDT-suffixed
  (raw rows, unfiltered by status). Quote volume: p10 $0.1M,
  p50 $1.6M, p90 $25M, max $2.88B; counts >=$1B: 3, >=$100M: 30,
  >=$10M: 145. Informs M2 10-20-market shortlist sizing; headline
  volume is not depth at our size. Single snapshot, not an
  eligibility claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 128 (mark/index basis snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e4174a6. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public premiumIndex (fetch 763ms, 927 rows): mark/index basis —
  BTC -6.38bps (funding +0.00157%), ETH -6.07bps (+0.00064%),
  SOL -5.56bps (+0.00613%), BNB +0.47bps (+0.00000%). Feeds M2
  mark-price/liquidation-buffer understanding; single snapshot,
  not a pricing claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 129 (L/S-ratio snapshot PASS; bracket 401 noted)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1b06c62. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- leverageBracket returned HTTP 401 (signed endpoint; no
  credentials authorised) — recorded as a negative finding, not
  retried with keys. Exchange max-leverage tiers remain unverified
  from public data; the 3x pilot cap stands as the binding
  simulation-side constraint regardless.
- Fallback public datum: BTCUSDT global long/short account ratio,
  5m x12 (fetch 241ms): range 1.437-1.447, last 1.447. Single
  snapshot, not a positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 130 (taker buy/sell snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b3fbdfe. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio BTCUSDT 5m x12 (fetch 335ms):
  ratio range 0.192-2.834, last 0.351; buyVol 538 BTC,
  sellVol 678 BTC over the window. Complements turn-129 account
  positioning ratio with executed-flow data. Single snapshot,
  not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 131 (BTC 1m-kline snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 3ac4c5f. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public klines BTCUSDT 1m x60 (fetch 325ms): 0 bar gaps; 1m
  log-return stdev 2.37bps; hour high-low range 31.6bps; total
  2,540 BTC. Volatility context for S1 compression/expansion
  calibration; single hour, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 132 (BTC OI-history snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9ca2961. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterestHist BTCUSDT 5m x12 (fetch 276ms): OI
  93,361 -> 93,234 BTC, dOI -127 (-0.14%) over the hour. Adds
  change context to earlier single-point OI snapshots. Single
  snapshot, not a positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 133 (ETH 1m-kline snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e05e34c. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public klines ETHUSDT 1m x60 (fetch 232ms): 0 bar gaps; 1m
  log-return stdev 4.86bps; hour high-low range 46.1bps; total
  72,522 ETH. Second-symbol vol context beside BTC turn-131
  (2.37bps/31.6bps) for per-market S1 threshold work; single
  hour each, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 134 (BNB depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at c0d1159. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public depth BNBUSDT limit=10 (fetch 278ms): mid ~$751.53,
  spread 0.13bps; top-10 bid $77,455 / ask $50,282;
  updateId 11788763860048. Third-symbol cost context after
  earlier BTC/ETH snapshots; single sample, not a liquidity
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 135 (ETH open-interest snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7e50dbb. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterest ETHUSDT (fetch 463ms): 2,325,263 ETH at a
  ~$2,512.09 reference (~$5,841.3M notional). Second-symbol OI
  datum beside BNB turn-122; single sample, not a positioning
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 136 (SOL trade-tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at fc750c8. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public aggTrades SOLUSDT x100 (fetch 240ms): 32.3s span, 54%
  buyer-initiated; median $98, p90 $11,776 notional. Third-symbol
  tape context after BTC/BNB; single sample, not a flow claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 137 (SOL open-interest snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at eff0818. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterest SOLUSDT (fetch 627ms): 8,635,794 SOL at a
  ~$110.22 reference (~$951.8M notional). Third-symbol OI datum
  beside BNB/ETH; single sample, not a positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 138 (SOL depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ea50dec. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public depth SOLUSDT limit=10 (fetch 249ms): mid ~$110.71,
  spread 0.90bps; top-10 bid $2,161,289 / ask $1,719,184;
  updateId 11788779995733. Completes BTC/ETH/BNB/SOL depth
  coverage; single sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 139 (SOL 1m-kline snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 90e84f2. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public klines SOLUSDT 1m x60 (fetch 244ms): 0 bar gaps; 1m
  log-return stdev 7.99bps; hour range 112.9bps; quote volume
  $76.8M. Completes BTC/ETH/SOL 1m-vol coverage for per-market
  S1 threshold work; single hour each, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 140 (SOL funding-rate snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 234f785. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public funding SOLUSDT (fetch 465ms): last 0.00630%, next due
  16:00 UTC, mark ~$110.77; prior three 0.00329/0.00151/0.00588%.
  Single-symbol carry-cost context beside the turn-123 sweep;
  single sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 141 (ETH taker-flow snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 123f3f3. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio ETHUSDT 5m x6 (fetch 335ms): range
  1.088-2.026, last 1.913. Second-symbol flow datum beside BTC
  turn-130; single sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 142 (BNB L/S-ratio snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 350c34d. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public globalLongShortAccountRatio BNBUSDT 5m x6 (fetch 403ms):
  range 2.157-2.167, last 2.157. Second-symbol positioning datum
  beside BTC turn-129; single sample, not a positioning claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 143 (ETH 24h-stat snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9127e86. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public ticker/24hr ETHUSDT (fetch 344ms): last $2,527.14 (+0.76%),
  hi $2,534.32 / lo $2,496.12; quote vol $2.89B across 1,323,690
  trades; VWAP $2,507.76. Single-symbol session context; single
  sample, not a session claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 144 (SOL taker-flow snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 381f327. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio SOLUSDT 5m x6 (fetch 242ms): range
  0.819-2.691, last 0.826. Completes BTC/ETH/SOL taker-flow
  coverage; single sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 145 (ETH L/S-ratio snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e6950f4. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public globalLongShortAccountRatio ETHUSDT 5m x6 (fetch 381ms):
  range 2.940-2.963, last 2.959. Completes BTC/BNB/ETH L/S
  coverage; single sample, not a positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 146 (BNB 24h-stat snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1c46a51. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public ticker/24hr BNBUSDT (fetch 262ms): $753.42, +0.27% on day,
  $128.9M quote vol, 378,478 trades. Pairs with ETH 24h datum;
  single sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 147 (SOL 24h-stat snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 04cf676. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public ticker/24hr SOLUSDT (fetch 298ms): $110.73, +0.18% on day,
  $716.7M quote vol, 817,169 trades. Completes ETH/BNB/SOL 24h
  trio; single sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 148 (SOL OI-history snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8c91962. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterestHist SOLUSDT 5m x6 (fetch 253ms): range
  8,614,073-8,633,119 SOL, last 8,633,119 (~$956.8M @ $110.83).
  Note: endpoint rows carry no symbolPrice key (first probe failed
  KeyError, retried with ticker/price); pairs with BTC OI-history
  datum. Single sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 149 (BTC 24h-stat snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 017b954. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public ticker/24hr BTCUSDT (fetch 316ms): $83,351.40, +0.43% on
  day, $3,131.2M quote vol, 784,450 trades. Completes
  BTC/ETH/BNB/SOL 24h set; single sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 150 (ETH OI-history snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 61a03f4. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterestHist ETHUSDT 5m x6 (fetch 343ms): range
  2,302,631-2,327,355 ETH, last 2,302,631 (~$5,817.2M @ $2,526.34;
  priced via ticker/price, no symbolPrice key in rows). Completes
  BTC/SOL/ETH OI-history trio; single sample, not a leverage
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 151 (BNB OI-history snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 6d81ba9. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public openInterestHist BNBUSDT 5m x6 (fetch 256ms): range
  560,986-562,866 BNB, last 560,986 (~$422.7M @ $753.46; priced
  via ticker/price, no symbolPrice key in rows). Completes
  BTC/SOL/ETH/BNB OI-history set; single sample, not a leverage
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 152 (ETH depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 94d9898. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public depth ETHUSDT limit=20 (fetch 239ms): mid $2,525.91,
  spread 0.04bps, bid20 $1.00M / ask20 $0.88M. Joins BNB/SOL
  depth data; single sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 153 (BTC depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5afbd8f. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public depth BTCUSDT limit=20 (fetch 264ms): mid $83,400.6,
  spread 0.01bps, bid20 $0.56M / ask20 $1.01M. Completes
  BTC/ETH/BNB/SOL depth set; single sample, not a liquidity
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 154 (ETH funding snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 36ec471. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public premiumIndex ETHUSDT (fetch 257ms): last funding
  0.00083%, next 16:00 UTC, mark $2,527.05. Pairs with SOL
  funding datum; single sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 155 (BNB funding snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9b54ad1. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public premiumIndex BNBUSDT (fetch 229ms): last funding
  0.00000%, next 16:00 UTC, mark $754.13. Joins SOL/ETH funding
  data; single sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 156 (BTC funding snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at f20b38b. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public premiumIndex BTCUSDT (fetch 415ms): last funding
  0.00148%, next 16:00 UTC, mark $83,439.8. Completes
  BTC/ETH/BNB/SOL funding set; single sample, not a cost
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 157 (ETH tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at fac78ea. E-004 acked (option a, W2 not started, worker-side
  go-ahead pending); V-001R (W1) still awaiting go-ahead; W3 idle.
- Public aggTrades ETHUSDT x100 (fetch 321ms): 9.7s span, 43%
  buy-side, median $974, p90 $27,351. Joins BNB/SOL tape data;
  single sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 158 (BTC funding-history snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7735dfb. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate BTCUSDT x6 8h cadence (fetch 253ms): last 6
  settlements 10-09 16:00→10-11 08:00 UTC: +0.00129/+0.00523/
  -0.00043/+0.00046/-0.00272/-0.00099% (last -0.00099% at 08:00
  UTC). Single-sample funding datum, not a funding-cost claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 159 (bookTicker spread snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4615de7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker all symbols (fetch 442ms, N=741 USDT-named,
  non-delivery): best-bid/ask spread p10 0.75bps / p50 3.42bps /
  p90 8.06bps / max 34.10bps. Top-of-book only, no size
  weighting; single-sample cost-input datum, not an execution
  cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 160 (universe re-census PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 6bbf318. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public exchangeInfo re-census (fetch 444ms): 924 total symbols,
  523 eligible (PERPETUAL + USDT margin + TRADING + COIN
  underlying; TradFi/expiry/non-trading excluded per
  discovery contract). Single-sample census datum, not a
  membership claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 161 (ETH funding-history snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4113fa7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate ETHUSDT x6 8h cadence (fetch 305ms): last 6
  settlements 10-09 16:00→10-11 08:00 UTC: +0.00154/+0.00558/
  +0.00050/+0.00299/-0.01175/-0.01166% (last -0.01166% at 08:00
  UTC). Single-sample funding datum, not a funding-cost claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 162 (SOL funding-history snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a3eb9ca. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate SOLUSDT x6 8h cadence (fetch 255ms): last 6
  settlements 10-09 16:00→10-11 08:00 UTC: +0.00189/+0.00791/
  +0.00250/+0.00329/+0.00151/+0.00588% (last +0.00588% at 08:00
  UTC). Single-sample funding datum, not a funding-cost claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 163 (SOL depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b6d054b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth SOLUSDT x20 (fetch 465ms): mid $110.98, spread
  0.90bps, bid20 $4.28M / ask20 $5.50M, last $110.99. Joins
  ETH/BTC depth snapshots; single-sample book datum, not a
  liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 164 (BNB funding-history snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ef3aba0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate BNBUSDT x6 8h cadence (fetch 244ms): all six
  settlements 10-09 16:00→10-11 08:00 UTC +0.00000% (flat/zero
  funding across the window). Single-sample funding datum, not
  a funding-cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 165 (BNB depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 555e917. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth BNBUSDT x20 (fetch 551ms): mid $753.71, spread
  0.13bps, bid20 $107k / ask20 $257k, last $753.70. Joins
  BTC/ETH/SOL depth snapshots; single-sample book datum, not a
  liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 166 (ETH taker-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at af4c86c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio ETHUSDT 5m x6 (fetch 234ms):
  1.413/1.088/2.026/1.913/1.531/0.890, last 0.890. Joins BTC
  taker datum; single-sample taker datum, not a flow claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 167 (SOL taker-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1eebd55. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio SOLUSDT 5m x6 (fetch 271ms):
  0.849/1.552/0.826/1.259/1.368/1.158, last 1.158. Joins
  BTC/ETH taker data; single-sample taker datum, not a flow
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 168 (BNB taker-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e33a76c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio BNBUSDT 5m x6 (fetch 249ms):
  0.599/2.359/0.700/1.384/1.667/1.018, last 1.018. Joins
  BTC/ETH/SOL taker data; single-sample taker datum, not a
  flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 169 (SOL global-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 61c8960. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio SOLUSDT 5m x6 (fetch
  334ms): 2.426/2.438/2.430/2.443/2.443/2.434, last 2.434.
  Joins ETH global-L/S datum; single-sample positioning
  datum, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 170 (BNB global-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 81250e0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio BNBUSDT 5m x6 (fetch
  268ms): 2.163/2.159/2.157/2.162/2.170/2.168, last 2.168.
  Completes ETH+SOL+BNB global-L/S trio; single-sample
  positioning datum, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 171 (SOL tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 50998c8. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades SOLUSDT x100 (fetch 346ms): 7.7s span, 48%
  buy, median $1,220 / p90 $47,250. Single-sample tape
  datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 172 (BNB tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2f9b853. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades BNBUSDT x100 (fetch 241ms): 12.3s span, 68%
  buy, median $64 / p90 $6,397. Single-sample tape datum,
  not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 173 (ETH kline snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 31c12f5. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines ETHUSDT 1m x6, 15:54-15:59Z (fetch 249ms):
  closes 2526.49/2529.07/2536.24/2533.54/2535.65/2536.26,
  range $2,526.24-$2,539.87. Single-sample candle datum,
  not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 174 (SOL kline snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ef41f7b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines SOLUSDT 1m x6, 15:55-16:00Z (fetch 272ms):
  closes 111.46/111.79/111.79/111.95/111.94/111.98,
  range $110.99-$112.10. Single-sample candle datum,
  not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 175 (BNB kline snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8c6813d. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines BNBUSDT 1m x6, 15:55-16:00Z (fetch 272ms):
  closes 754.28/755.40/755.50/756.25/755.96/754.78,
  range $753.71-$756.38. Completes ETH+SOL+BNB kline trio.
  Single-sample candle datum, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 176 (BTC kline snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e5364b5. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines BTCUSDT 1m x6, 15:56-16:01Z (fetch 299ms):
  closes 83751.9/83732.5/83911.7/83868.7/83768.4/83758.5,
  range $83,511.3-$83,955.0. Single-sample candle datum,
  not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 177 (BTC tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 89afaa1. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades BTCUSDT x100 (fetch 236ms): 1.7s span, 8%
  buy, median $418 / p90 $30,717. Single-sample tape datum,
  not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 178 (BTC taker-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at fbb0440. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio BTCUSDT 5m x6 (fetch 262ms):
  2.508/2.397/1.696/1.598/0.650/2.010, last 2.010.
  Single-sample taker-flow datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 179 (BTC global-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at f4d4218. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio BTCUSDT 5m x6 (fetch
  261ms): 1.447/1.450/1.455/1.456/1.453/1.471, last 1.471.
  Extends ETH+SOL+BNB coverage to BTC; single-sample
  positioning datum, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 180 (BTC depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at dbaad0f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth BTCUSDT L20 (fetch 231ms): mid $83,786.95,
  spread 0.01bps, bid $1.35M / ask $1.46M top-20 notional.
  Single-sample depth datum, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 181 (ETH depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at df0f317. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth ETHUSDT L20 (fetch 291ms): mid $2,533.28,
  spread 0.04bps, bid $530k / ask $267k top-20 notional.
  Single-sample depth datum, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 182 (SOL depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9506f9f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth SOLUSDT L20 (fetch 340ms): mid $111.78,
  spread 0.89bps, bid $5.34M / ask $4.60M top-20 notional.
  Single-sample depth datum, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 183 (BNB depth snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9f601ba. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth BNBUSDT L20 (fetch 244ms): mid $755.20,
  spread 0.13bps, bid $178,769 / ask $181,226 top-20 notional.
  Single-sample depth datum, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 184 (funding snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ef33bde. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 515ms): BTC funding +0.0010%,
  mark $83,776.75 vs index $83,828.07; ETH funding +0.0012%,
  mark $2,533.86 vs index $2,534.75. Next funding 1791763200000.
  Single-sample datum, not a cost/regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 185 (SOL/BNB funding snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7d1f1ea. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 459ms): SOL funding +0.0067%,
  mark $111.90 vs index $111.95; BNB funding +0.0000%,
  mark $754.89 vs index $754.80. Next funding 1791763200000.
  Single-sample datum, not a cost/regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 186 (OI snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5bca947. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 487ms): BTC 92,733.643 contracts,
  ETH 2,305,101.249 contracts. Single-sample datum, not a
  leverage/flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 187 (SOL/BNB OI snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 168cc92. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 465ms): SOL 8,502,004.550 contracts,
  BNB 560,352.560 contracts. Single-sample datum, not a
  leverage/flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 188 (24h-ticker snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2b1ea7c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public ticker/24hr (fetch 479ms): BTC $83,739.40 +0.98%,
  hi $83,955.00 / lo $82,751.10, $3.93B, 893,572 trades;
  ETH $2,531.40 +0.94%, hi $2,539.87 / lo $2,496.12,
  $3.24B, 1,430,624 trades. Single-sample datum, not a
  regime/liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 189 (SOL/BNB 24h-ticker snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at fcc6d01. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public ticker/24hr (fetch 718ms): SOL $111.86 +1.52%,
  hi $112.10 / lo $108.89, $0.85B, 895,866 trades;
  BNB $755.22 +0.61%, hi $756.38 / lo $744.91,
  $0.14B, 397,495 trades. Single-sample datum, not a
  regime/liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 190 (bookTicker snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ff9456f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- First attempt: multi-symbol `symbols` param returned the full
  universe book and a quarterly contract (BTCUSDT_260925, bid 0.0)
  broke the spread math (ZeroDivisionError) — probe fixed, not a
  venue failure. Re-ran per-symbol.
- Public bookTicker (fetch 1185ms): BTC spread 0.01bps,
  ETH 0.04bps, SOL 0.89bps, BNB 0.13bps. Single-sample
  datum, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 191 (ETH taker-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d4fa98a. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- First attempt assumed `longShortRatio` key (KeyError); endpoint
  rows actually carry `buySellRatio`/`buyVol`/`sellVol` — probe
  fixed, not a venue failure. Re-ran correctly.
- Public takerlongshortRatio ETH 5m x6 (fetch 229ms):
  1.913/1.531/0.890/0.749/1.039/0.781, last 0.781.
  Single-sample datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 192 (SOL taker-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a3a7482. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio SOL 5m x6 (fetch 258ms):
  0.826/1.259/1.368/1.158/2.187/0.928, last 0.928.
  Single-sample datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 193 (BNB taker-L/S snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 0e58a17. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio BNB 5m x6 (fetch 271ms):
  1.384/1.667/1.018/1.894/0.579/0.942, last 0.942.
  Single-sample datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 194 (SOL tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 71dd8c3. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades SOL n=100 (fetch 288ms): buy-initiated
  4428.1 SOL / sell-initiated 5914.2 SOL, last $111.92.
  Single-sample datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 195 (BNB tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 045fb33. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades BNB n=100 (fetch 333ms): buy-initiated
  11.8 BNB / sell-initiated 129.1 BNB, last $755.28.
  Single-sample datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 196 (BTC tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at dc6ab64. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades BTC n=100 (fetch 319ms): buy-initiated
  0.565 BTC / sell-initiated 2.199 BTC, last $83,796.50.
  Single-sample datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 197 (ETH tape snapshot PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4632f5f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades ETH n=100 (fetch 372ms): buy-initiated
  130.5 ETH / sell-initiated 242.8 ETH, last $2,532.54.
  Single-sample datum, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 198 (universe re-check PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ad671b0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public exchangeInfo (fetch 469ms): USDT-perp TRADING=525 /
  non-trading=134 / total symbols=924. Discovery works off live
  metadata, no hardcoded whitelist. Single-sample datum, not an
  eligibility claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 199 (BTC funding-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9641584. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate BTC x3 (fetch 275ms): 00Z -0.0027%
  ($82,941.06), 08Z -0.0010% ($82,980.80), 16Z +0.0013%
  ($83,868.70). 8h cadence confirmed. Single-sample datum,
  not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 200 (ETH funding-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 277d222. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate ETH x3 (fetch 273ms): 00Z -0.0118%
  ($2,504.91), 08Z -0.0117% ($2,499.53), 16Z +0.0012%
  ($2,534.63). 8h cadence confirmed. Single-sample datum,
  not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 201 (SOL funding-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1043e09. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate SOL x3 (fetch 237ms): 00Z +0.0015%
  ($110.04), 08Z +0.0059% ($109.34), 16Z +0.0066%
  ($111.94). 8h cadence confirmed. Single-sample datum,
  not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 202 (BNB funding-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 81de45f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate BNB x3 (fetch 281ms): 00Z +0.0000%
  ($750.31), 08Z +0.0000% ($747.37), 16Z +0.0000%
  ($755.88). Four-symbol funding set complete. Single-sample
  datum, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 203 (funding-timing PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4fdae2f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 509ms): BTC nextFunding
  2026-10-12T00:00:00Z lastRate +0.0012%; ETH nextFunding
  2026-10-12T00:00:00Z lastRate +0.0015%. Single-sample
  datum, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 204 (SOL/BNB funding-timing PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8f93584. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 479ms): SOL nextFunding
  2026-10-12T00:00:00Z lastRate +0.0073%; BNB nextFunding
  2026-10-12T00:00:00Z lastRate +0.0000%. Four-symbol
  funding-timing set complete. Single-sample datum, not a
  cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 205 (OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1a46997. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 16:15Z (fetch 626ms): BTC
  92,892.018 ($7.79B); ETH 2,302,589.285 ($5.83B).
  Single-sample datum, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 206 (OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ad1c514. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 16:15Z (fetch 609ms): SOL
  8,490,789.670 ($950.3M); BNB 560,616.580 ($423.4M).
  Single-sample datum, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 207 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 04378f1. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 655ms): BTC bid 83777.0x3.987 /
  ask 83777.1x12.647 spread 0.01bp; ETH bid 2532.14x88.96 /
  ask 2532.15x166.923 spread 0.04bp. Single-sample, not a
  liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 208 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a3c4c28. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 547ms): SOL bid 111.62x481.78 /
  ask 111.63x1273.62 spread 0.90bp; BNB bid 755.57x14.03 /
  ask 755.58x115.16 spread 0.13bp. Single-sample, not a
  liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 209 (tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 3d53f17. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public XRP aggTrades n=100 (fetch 256ms): buy-initiated
  58,431.0 / sell-initiated 27,763.0 XRP, last $1.4180.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 210 (tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a84e5fd. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public DOGE aggTrades n=100 (fetch 332ms): buy-initiated
  716,290.0 / sell-initiated 1,360,288.0 DOGE, last $0.08688.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 211 (funding-timing PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a401852. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 462ms): XRP mark $1.41757
  lastFunding +0.0063%; DOGE mark $0.08691 lastFunding
  +0.0045%; both nextFunding 2026-10-12T00:00:00Z.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 212 (OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 3032bea. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 16:20Z (fetch 605ms): XRP
  296,903,067.5 ($420.7M); DOGE 2,701,386,682.0 ($234.6M).
  Single-sample datum, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 213 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a50a021. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 564ms): XRP bid 1.4169x4,138 /
  ask 1.417x54,391 spread 0.71bp; DOGE bid 0.08685x198,601 /
  ask 0.08686x755,534 spread 1.15bp. Single-sample, not a
  liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 214 (taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 161d1ff. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m (fetch 536ms): XRP 0.563
  (buy 816,974 / sell 1,450,352); DOGE 0.290 (buy 6,550,591 /
  sell 22,567,018). Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 215 (funding-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 6477d16. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x3 (fetch 480ms): XRP 00Z -0.0005% /
  08Z +0.0029% / 16Z +0.0060%; DOGE 00Z -0.0019% /
  08Z +0.0044% / 16Z +0.0034%. Single-sample, not a cost
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 216 (bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at cdb7bd9. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public per-symbol bookTicker (fetch 541ms): BTC bid
  83784.5x11.618 / ask 83784.6x2.534 spread 0.01bp; ETH bid
  2537.34x1.941 / ask 2537.35x484.509 spread 0.04bp.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 217 (bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1b62f65. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public per-symbol bookTicker (fetch 525ms): SOL bid
  111.58x246.09 / ask 111.59x1548.78 spread 0.90bp; BNB bid
  754.95x11.29 / ask 754.96x41.23 spread 0.13bp.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 218 (bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 0017d1f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public per-symbol bookTicker (fetch 550ms): XRP bid
  1.4171x63,375.6 / ask 1.4172x11,247.3 spread 0.71bp; DOGE bid
  0.08686x370,696 / ask 0.08687x656,404 spread 1.15bp.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 219 (tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9eb3846. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades n=100 (fetch 477ms): SOL buy-initiated
  4,299.5 / sell-initiated 2,523.2 last $111.72; BNB
  buy-initiated 134.8 / sell-initiated 45.6 last $755.66.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 220 (funding-timing PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at c126046. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 600ms): SOL mark $112.022
  lastRate +0.0080%; BNB mark $756.346 lastRate +0.0000%;
  both nextFunding 2026-10-12T00:00:00Z.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 221 (openInterest PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 6d20fca. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public current openInterest (fetch 1187ms): BTC
  92,950.060 ($7.80B); ETH 2,304,780.071 ($5.86B).
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 222 (openInterest PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ee6d40d. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public current openInterest (fetch 944ms): SOL
  8,481,463.150 ($949.2M); BNB 560,602.900 ($424.0M).
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 223 (openInterest PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a616d8d. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public current openInterest (fetch 957ms): XRP
  297,104,301.8 ($422.0M); DOGE 2,701,949,981.0 ($235.4M).
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 224 (taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 380c4cc. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m (fetch 613ms): BTC 0.980
  (buy 154 / sell 157); ETH 1.852 (buy 6,035 / sell 3,259).
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 225 (taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d37931e. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m (fetch 672ms): SOL 1.245
  (buy 52,414 / sell 42,084); BNB 0.545 (buy 396 /
  sell 727). Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 226 (funding-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a7dc189. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x3 (fetch 684ms): BTC 00Z -0.0027% /
  08Z -0.0010% / 16Z +0.0013%; ETH 00Z -0.0118% /
  08Z -0.0117% / 16Z +0.0012%.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 227 (funding-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e09558a. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x3 (fetch 480ms): SOL 00Z +0.0015% /
  08Z +0.0059% / 16Z +0.0066%; BNB 00Z +0.0000% /
  08Z +0.0000% / 16Z +0.0000%.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 228 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at f8dc9d1. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 461ms): BTC bid
  83788.0x1.464 / ask 83788.1x17.395 spread 0.01bp; ETH bid
  2540.96x34.891 / ask 2540.97x212.705 spread 0.04bp.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 229 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e2ae4a7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 464ms): SOL bid
  111.73x370.88 / ask 111.74x1015.38 spread 0.89bp; BNB bid
  755.84x12.86 / ask 755.85x45.21 spread 0.13bp.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 230 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at dba7db7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 644ms): XRP bid
  1.4171x31801.4 / ask 1.4172x33304.9 spread 0.71bp; DOGE bid
  0.08693x449039 / ask 0.08694x136953 spread 1.15bp.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 231 (universe PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5c0dae6. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- exchangeInfo (fetch 1126ms): 924 total symbols, 525
  USDT-margined PERPETUAL TRADING; 2 non-COIN underlying in
  scope (BTCDOMUSDT, ALLUSDT) flagged for TradFi-index
  exclusion check. Point sample, not a universe claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 232 (ticker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ed37f19. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public 24h ticker (fetch 604ms): BTC last $83,769.60
  +0.934% hi 83,957.80 lo 82,751.10 qvol $4.17B; ETH last
  $2,538.74 +1.316% hi 2,549.00 lo 2,496.12 qvol $3.57B.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 233 (ticker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 61c6ba9. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public 24h ticker (fetch 978ms): SOL last $111.69
  +1.407% hi 112.13 lo 108.89 qvol $0.89B; BNB last
  $755.60 +0.714% hi 757.27 lo 744.91 qvol $0.15B.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 234 (ticker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at be981d8. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public 24h ticker (fetch 480ms): XRP last $1.4169
  +0.804% hi 1.4260 lo 1.3865 qvol $0.38B; DOGE last
  $0.086940 +0.917% hi 0.087320 lo 0.084850 qvol $0.18B.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 235 (tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 19bacc7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades n=100 (fetch 592ms): BTC buy-init
  $216,861.7 / sell-init $81,785.0 last $83,796.70; ETH
  buy-init $1,387,708.8 / sell-init $73,268.2 last $2,541.75.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 236 (tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e6b557e. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades n=100 (fetch 511ms): XRP buy-init
  $97,151.4 / sell-init $56,200.3 last $1.41840; DOGE
  buy-init $58,691.1 / sell-init $70,715.2 last $0.08707.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 237 (tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ef48281. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades n=100 (fetch 621ms): SOL buy-init
  $457,693.1 / sell-init $352,249.5 last $111.80; BNB
  buy-init $56,599.2 / sell-init $25,442.2 last $756.51.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 238 (funding-timing PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 05567a2. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 462ms): BTC mark $83,804.16
  lastRate +0.0015%; ETH mark $2,542.46 lastRate +0.0018%;
  both nextFunding 2026-10-12T00:00:00Z.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 239 (funding-timing PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e7d45ab. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 494ms): XRP mark $1.41985
  lastRate +0.0068%; DOGE mark $0.08721 lastRate +0.0053%;
  both nextFunding 2026-10-12T00:00:00Z.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 240 (funding-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 6e042f9. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x3 (fetch 492ms): XRP 00Z -0.0005% /
  08Z +0.0029% / 16Z +0.0060%; DOGE 00Z -0.0019% / 08Z
  +0.0044% / 16Z +0.0034%.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 241 (OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4c8a263. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 (fetch 475ms): BTC 16:30Z
  92,970.5 ($7.80B) / 16:35Z 92,982.0 ($7.79B); ETH 16:30Z
  2,303,194.8 ($5.86B) / 16:35Z 2,305,173.5 ($5.85B).
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 242 (OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8d16981. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 (fetch 726ms): XRP 16:35Z
  297.26M ($421.3M) / 16:40Z 297.36M ($422.2M); DOGE 16:30Z
  2700.55M ($235.1M) / 16:35Z 2699.53M ($234.7M).
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 243 (OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 23c9bd3. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 (fetch 465ms): SOL 16:35Z
  8.48M ($946.5M) / 16:40Z 8.48M ($948.6M); BNB 16:30Z
  0.56M ($424.2M) / 16:35Z 0.56M ($423.8M).
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 244 (L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at f5a3a5b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x2 (fetch 472ms): BTC
  16:35Z 1.4301 / 16:40Z 1.4284; ETH 16:35Z 2.9651 / 16:40Z
  2.9557. Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 245 (L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ba52a0b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x2 (fetch 499ms): XRP
  16:35Z 2.3625 / 16:40Z 2.3681; DOGE 16:35Z 2.4083 / 16:40Z
  2.4060. Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 246 (L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2da778a. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x2 (fetch 629ms): SOL
  16:35Z 2.4025 / 16:40Z 2.3979; BNB 16:35Z 2.1437 / 16:40Z
  2.1456. Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 247 (taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b4e1b53. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m x2 (fetch 467ms): BTC
  16:30Z 0.7237 / 16:35Z 1.7064; ETH 16:30Z 0.9533 / 16:35Z
  1.0122. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 248 (taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 07520b0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m x2 (fetch 515ms): XRP
  16:30Z 1.0012 / 16:35Z 1.0283; DOGE 16:30Z 0.8706 / 16:35Z
  1.6604. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 249 (taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 419c1c1. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m x2 (fetch 621ms): SOL
  16:30Z 1.2803 / 16:35Z 0.8750; BNB 16:30Z 1.3572 / 16:35Z
  0.7429. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 250 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8f8452b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 465ms): BTC bid 83880.40x6.208 /
  ask 83880.50x8.201 spread 0.01bp; ETH bid 2547.05x134.627 /
  ask 2547.06x41.589 spread 0.04bp.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 251 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at cee6f8f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 609ms): SOL bid 112.1500x679.65 /
  ask 112.1600x318.33 spread 0.89bp; BNB bid 757.860x16.62 /
  ask 757.870x19.08 spread 0.13bp.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 252 (depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 240ecb5. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 628ms): XRP bid 1.4206x24184.7 /
  ask 1.4207x55624.8 spread 0.70bp; DOGE bid 0.087270x722262 /
  ask 0.087280x41631 spread 1.15bp.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 253 (universe PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9504415. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public exchangeInfo (fetch 732ms): 924 total symbols, 525
  USDT-margined PERPETUAL TRADING; 2 non-COIN in scope
  (BTCDOMUSDT, ALLUSDT) flagged.
  Single-sample, not an eligibility claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 254 (BTC/ETH spread PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7f41685. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker (fetch 624ms): BTCUSDT bid 83947.90 /
  ask 83948.00, spread 0.01bp; ETHUSDT bid 2553.30 /
  ask 2553.31, spread 0.04bp.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 255 (XRP/DOGE spread PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 875cd0b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker (fetch 461ms): XRPUSDT bid 1.42170 /
  ask 1.42180, spread 0.70bp; DOGEUSDT bid 0.08736 /
  ask 0.08737, spread 1.14bp.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 256 (SOL/BNB spread PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e615552. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker (fetch 479ms): SOLUSDT bid 112.24 /
  ask 112.25, spread 0.89bp; BNBUSDT bid 757.55 /
  ask 757.56, spread 0.13bp.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 257 (BTC/ETH kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d737d8c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 485ms): BTC 16:49Z c 83891.60 /
  16:50Z c 83869.10; ETH 16:49Z c 2551.35 / 16:50Z c 2550.27.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 258 (XRP/DOGE kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7530e03. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 474ms): XRP 16:49Z c 1.42090 /
  16:50Z c 1.42010; DOGE 16:49Z c 0.08737 / 16:50Z c 0.08726.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 259 (SOL/BNB kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 524a17c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 460ms): SOL 16:50Z c 112.15 /
  16:51Z c 112.18; BNB 16:50Z c 757.11 / 16:51Z c 757.14.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 260 (BTC/ETH tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at f6c8e67. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades n=5 (fetch 480ms): BTC last 83912.90,
  buy 0.0120 / sell 0.0210; ETH last 2551.88,
  buy 0.0860 / sell 0.8570.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 261 (XRP/DOGE tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ef39f24. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades n=5 (fetch 477ms): XRP last 1.42090,
  buy 7610.7 / sell 1228.8; DOGE last 0.08729,
  buy 7573.0 / sell 57618.0.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 262 (SOL/BNB tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 46245b4. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades n=5 (fetch 466ms): SOL last 112.24,
  buy 9.95 / sell 0.42; BNB last 757.60,
  buy 0.27 / sell 0.06.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 263 (BTC/ETH OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 79c2ee5. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 626ms): BTCUSDT OI 92,905.0;
  ETHUSDT OI 2,313,450.6.
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 264 (XRP/DOGE OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ccc077e. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 488ms): XRPUSDT OI 298,083,919.8;
  DOGEUSDT OI 2,709,205,076.0.
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 265 (SOL/BNB OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a3c7308. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 517ms): SOLUSDT OI 8,481,366.3;
  BNBUSDT OI 563,139.3.
  Single-sample, not a leverage claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 266 (BTC/ETH OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4e59c5c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 1h x2 (fetch 1303ms): BTCUSDT OI
  [93,342.5, 92,546.0] price 83,967.30; ETHUSDT OI
  [2,326,391.2, 2,301,084.5] price 2,552.15.
  OI-history rows carry no symbolPrice — prices via separate
  ticker call. Single-sample, not a leverage/flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 267 (XRP/DOGE OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 81431f0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 1h x2 (fetch 921ms): XRPUSDT OI
  [301,432,721.6, 297,734,590.2] price 1.42230; DOGEUSDT OI
  [2,690,646,445.0, 2,694,692,630.0] price 0.08743.
  Prices via separate ticker call. Single-sample, not a
  leverage/flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 268 (SOL/BNB OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5b6d96d. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 1h x2 (fetch 938ms): SOLUSDT OI
  [8,601,759.2, 8,509,202.3] price 112.27; BNBUSDT OI
  [562,863.0, 561,282.2] price 757.56.
  Prices via separate ticker call. Single-sample, not a
  leverage/flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 269 (BTC/ETH L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 318315e. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 1h x1 (fetch 544ms):
  BTCUSDT L/S 1.4710 (long 0.5953/short 0.4047); ETHUSDT
  L/S 3.0128 (long 0.7508/short 0.2492).
  Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 270 (XRP/DOGE L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4a4559e. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 1h x1 (fetch 472ms):
  XRPUSDT L/S 2.3887 (long 0.7049/short 0.2951); DOGEUSDT
  L/S 2.4270 (long 0.7082/short 0.2918).
  Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 271 (SOL/BNB L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5d8c877. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 1h x1 (fetch 613ms):
  SOLUSDT L/S 2.4471 (long 0.7099/short 0.2901); BNBUSDT
  L/S 2.1807 (long 0.6856/short 0.3144).
  Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 272 (BTC/ETH taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 56f0333. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 1h x1 (fetch 472ms): BTCUSDT
  buySellRatio 1.7838 (buy 8,140.6/sell 4,563.7); ETHUSDT
  buySellRatio 1.2957 (buy 174,110.2/sell 134,380.1).
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 273 (XRP/DOGE taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at babf3cd. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 1h x1 (fetch 509ms): XRPUSDT
  buySellRatio 1.6871 (buy 34,809,930.8/sell 20,632,958.2);
  DOGEUSDT buySellRatio 1.2070 (buy 163,450,292.0/sell
  135,424,133.0). Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 274 (SOL/BNB taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 363c90f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 1h x1 (fetch 978ms): SOLUSDT
  buySellRatio 1.4921 (buy 1,075,979.5/sell 721,123.4);
  BNBUSDT buySellRatio 1.5327 (buy 13,978.5/sell 9,120.4).
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 275 (BTC/ETH depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 715cf72. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 468ms): BTCUSDT best
  83,783.10x6.4020/83,783.20x2.0310 L5-notional
  bid $652,418/ask $171,169; ETHUSDT best
  2,542.92x131.3780/2,542.93x72.9160 L5-notional
  bid $344,718/ask $205,896.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 276 (XRP/DOGE depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at fc71720. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 480ms): XRPUSDT best
  1.41680x64,695/1.41690x14,350 L5-notional bid
  $418,378/ask $139,093; DOGEUSDT best
  0.08701x427,353/0.08702x392,097 L5-notional bid
  $266,165/ask $255,911.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 277 (SOL/BNB depth PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 84d3b4b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 (fetch 585ms): SOLUSDT best
  111.79x766.2/111.80x775.3 L5-notional bid $775,951/ask
  $580,920; BNBUSDT best 755.51x40.5/755.52x1.3
  L5-notional bid $48,201/ask $1,224 (thin top-of-book ask
  this sample — recorded as observed, not a depth claim).
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 278 (BTC/ETH bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 21ce5c9. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker per-symbol (fetch 515ms): BTCUSDT bid
  83,744.00x2.994 / ask 83,744.10x15.160 spread 0.10
  (0.01 bps); ETHUSDT bid 2,540.81x136.686 / ask
  2,540.82x71.253 spread 0.01 (0.04 bps).
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 279 (XRP/DOGE bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at bb0529f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker per-symbol (fetch 570ms): XRPUSDT bid
  1.4172x5313.3 / ask 1.4173x39229.3 spread 0.00010
  (0.71 bps); DOGEUSDT bid 0.08703x182426 / ask
  0.08704x641601 spread 0.00001 (1.15 bps).
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 280 (SOL/BNB bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e95f3b7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker per-symbol (fetch 613ms): SOLUSDT bid
  111.86x2640.71 / ask 111.87x239.25 spread 0.0100
  (0.89 bps); BNBUSDT bid 755.77x64.08 / ask
  755.78x13.98 spread 0.0100 (0.13 bps).
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 281 (BTC/ETH funding PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b3c7134. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 586ms): BTCUSDT mark 83,755.40
  lastFunding 0.1172 bps next 00:00Z; ETHUSDT mark
  2,542.90 lastFunding 0.1263 bps next 00:00Z.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 282 (XRP/DOGE funding PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e792778. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 565ms): XRPUSDT mark 1.417801
  lastFunding 0.7521 bps next 00:00Z; DOGEUSDT mark
  0.08703 lastFunding 0.6305 bps next 00:00Z.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 283 (SOL/BNB funding PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 26d3182. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex (fetch 695ms): SOLUSDT mark 111.86
  lastFunding 0.9786 bps next 00:00Z; BNBUSDT mark
  755.91 lastFunding 0.0000 bps next 00:00Z.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 284 (BTC/ETH 24hr-ticker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ad1ce4a. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public ticker/24hr (fetch 519ms): BTCUSDT last 83,758.60
  +0.88% hi 84,024.40 lo 82,751.10 quoteVol 4,443,391,041
  trades 995274; ETHUSDT last 2,542.00 +1.48% hi 2,553.76
  lo 2,496.12 quoteVol 3,941,168,032 trades 1640834.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 285 (XRP/DOGE 24hr-ticker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ddfb5be. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public ticker/24hr (fetch 476ms): XRPUSDT last 1.4177
  +0.95% hi 1.426 lo 1.3865 quoteVol 394,628,196
  trades 693427; DOGEUSDT last 0.08699 +1.02% hi
  0.08753 lo 0.08485 quoteVol 191,941,072 trades 531391.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 286 (SOL/BNB 24hr-ticker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 362a026. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public ticker/24hr (fetch 474ms): SOLUSDT last 111.89
  +1.76% hi 112.47 lo 108.89 quoteVol 943,455,956
  trades 987600; BNBUSDT last 755.51 +0.72% hi 758.77
  lo 744.91 quoteVol 157,960,963 trades 433133.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 287 (BTC/ETH kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 042f3b9. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 564ms): BTCUSDT @17:08Z
  83,763.70>83,765.00v20.8 | 83,765.10>83,765.00v2.2
  (forming); ETHUSDT @17:08Z 2,541.72>2,541.49v1,385.4 |
  2,541.49>2,541.50v49.4 (forming).
  Single-sample, not a signal claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 288 (XRP/DOGE kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ac78958. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 745ms): XRPUSDT @17:08Z
  1.4176>1.4176v259,428 | 1.4176>1.4172v93,607
  (forming); DOGEUSDT @17:08Z 0.08697>0.08693v3,103,615
  | 0.08694>0.08694v1,237,870 (forming).
  Single-sample, not a signal claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 289 (SOL/BNB kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 323be91. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 481ms): SOLUSDT @17:09Z
  111.88>111.87v9,455 | 111.87>111.84v1,886 (forming);
  BNBUSDT @17:09Z 755.54>755.21v104 | 755.20>755.20v2
  (forming). Single-sample, not a signal claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 290 (BTC/ETH tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9f48ada. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades x5 (fetch 545ms): BTCUSDT last5
  83,796.40S 83,796.50B 83,796.50B 83,796.40S 83,796.50B
  buys=3 sells=2; ETHUSDT last5 2,543.31B 2,543.31B
  2,543.31B 2,543.30S 2,543.31B buys=4 sells=1.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 291 (XRP/DOGE tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at c44cfbc. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades x5 (fetch 496ms): XRPUSDT last5
  1.4193B 1.4192S 1.4193B 1.4192S 1.4193B buys=3
  sells=2; DOGEUSDT last5 0.0871S 0.08711B 0.08711B
  0.0871S 0.0871B buys=3 sells=2. Single-sample, not
  a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 292 (SOL/BNB tape PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 65cc55a. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades x5 (fetch 478ms): SOLUSDT last5
  111.90B 111.89S 111.90B 111.90B 111.90B buys=4
  sells=1; BNBUSDT last5 755.51B 755.51B 755.50S
  755.51B 755.51B buys=4 sells=1. Single-sample, not
  a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 293 (BTC/ETH OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d36c6f7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 523ms): BTCUSDT OI=92,885.4;
  ETHUSDT OI=2,315,772.2. Single-sample, not a
  positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 294 (XRP/DOGE OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at cbfc6ed. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 467ms): XRPUSDT
  OI=297,608,503.4; DOGEUSDT OI=2,713,203,430.0.
  Single-sample, not a positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 295 (SOL/BNB OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 56af0bf. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 610ms): SOLUSDT OI=8,484,961.8;
  BNBUSDT OI=564,317.8. Single-sample, not a
  positioning claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 296 (BTC/ETH OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7b19aba. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 (fetch 476ms): BTCUSDT
  92,843 > 92,895; ETHUSDT 2,311,594 > 2,314,063.
  Single-sample, not a trend claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 297 (XRP/DOGE OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 94cb682. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 (fetch 655ms): XRPUSDT
  297,607,411 > 297,820,391; DOGEUSDT
  2,711,702,976 > 2,712,599,945. Single-sample, not a
  trend claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 298 (SOL/BNB OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 22d5429. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 (fetch 553ms): SOLUSDT
  8,472,842 > 8,481,838; BNBUSDT 564,585 > 564,710.
  Single-sample, not a trend claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 299 (BTC/ETH L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 78b11d8. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m (fetch 500ms):
  BTCUSDT L/S=1.4254 long%=58.77; ETHUSDT L/S=2.8880
  long%=74.28. Single-sample, not a sentiment claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 300 (XRP/DOGE L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a8ae12b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m (fetch 506ms):
  XRPUSDT L/S=2.3613 long%=70.25; DOGEUSDT L/S=2.4141
  long%=70.71. Single-sample, not a sentiment claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 301 (SOL/BNB L/S PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 78fa8d0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m (fetch 566ms):
  SOLUSDT L/S=2.3864 long%=70.47; BNBUSDT L/S=2.1437
  long%=68.19. Single-sample, not a sentiment claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 302 (BTC/ETH taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 68c1c98. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m (fetch 504ms):
  BTCUSDT buySellRatio=0.9936 buyVol=154.8 sellVol=155.8;
  ETHUSDT buySellRatio=0.4837 buyVol=3469.7 sellVol=7173.6.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 303 (XRP/DOGE taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 40590b3. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m (fetch 606ms):
  XRPUSDT buySellRatio=1.0399 buyVol=684266.8 sellVol=658004.0;
  DOGEUSDT buySellRatio=1.9884 buyVol=13391100.0
  sellVol=6734449.0. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 304 (SOL/BNB taker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 79243cb. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m (fetch 623ms):
  SOLUSDT buySellRatio=1.8830 buyVol=31934.2 sellVol=16959.3;
  BNBUSDT buySellRatio=1.5203 buyVol=973.5 sellVol=640.3.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 305 (BTC/ETH book PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at c4cfaed. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 top-3 (fetch 564ms):
  BTCUSDT bid 83910.60/83910.50/83910.00 ask
  83910.70/83910.80/83911.00 spread 0.10;
  ETHUSDT bid 2544.46/2544.45/2544.44 ask
  2544.47/2544.48/2544.49 spread 0.01.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 306 (XRP/DOGE book PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at bc8f10f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 top-3 (fetch 542ms):
  XRPUSDT bid 1.4213/1.4212/1.4211 ask
  1.4214/1.4215/1.4216 spread 0.0001;
  DOGEUSDT bid 0.0872/0.0871/0.0871 ask
  0.0872/0.0872/0.0872 spread 0.0000.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 307 (SOL/BNB book PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 188df33. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit=5 top-3 (fetch 469ms):
  SOLUSDT bid 112.16/112.15/112.14 ask 112.17/112.18/112.19
  spread 0.01; BNBUSDT bid 756.27/756.26/756.25 ask
  756.28/756.29/756.30 spread 0.01.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 308 (BTC/ETH funding PASS; schema fix)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8c561f2. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- First attempt KeyError 'lastPrice': premiumIndex carries no
  lastPrice — last price read via ticker/price. Re-ran (fetch
  862ms): BTCUSDT mark=83946.30 last=83929.60
  funding=0.0017%; ETHUSDT mark=2545.74 last=2544.92
  funding=0.0011%. Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 309 (XRP/DOGE funding PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e9a6ca5. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex+ticker/price (fetch 948ms):
  XRPUSDT mark=1.4236 last=1.4235 funding=0.0080%;
  DOGEUSDT mark=0.0873 last=0.0873 funding=0.0070%.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 310 (SOL/BNB funding PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 10293f8. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex+ticker/price (fetch 981ms):
  SOLUSDT mark=112.25 last=112.26 funding=0.0100%;
  BNBUSDT mark=756.69 last=756.73 funding=0.0000%.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 311 (BTC/ETH kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 072dd8c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 620ms):
  BTCUSDT 83957.30>83950.10v67 | 83950.10>83925.00v32
  forming; ETHUSDT 2545.99>2545.34v3,282 |
  2545.34>2544.57v641 forming @17:22Z.
  Single-sample, not a price claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 312 (XRP/DOGE kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at bcc7c9a. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 645ms):
  XRPUSDT 1.4232>1.4228v678,369 |
  1.4229>1.4229v319,815 forming; DOGEUSDT
  0.0873>0.0873v3,408,264 | 0.0873>0.0873v1,472,331
  forming @17:22Z. Single-sample, not a price claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 313 (SOL/BNB kline PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 75cd817. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 460ms):
  SOLUSDT 112.22>112.27v12,911 |
  112.27>112.26v3,189 forming; BNBUSDT
  756.65>756.64v159 | 756.64>756.48v56
  forming @17:23Z. Single-sample, not a price claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 314 (BTC/ETH OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 3bdf9aa. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 594ms): BTCUSDT
  92,994.0 contracts; ETHUSDT
  2,318,032.1 contracts @17:24Z. Single-sample, not a flow
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 315 (XRP/DOGE OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 86b5c36. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 619ms): XRPUSDT
  297,456,931 contracts; DOGEUSDT
  2,710,060,454 contracts @17:25Z. Single-sample, not a flow
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 316 (SOL/BNB OI PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at cddbf63. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 516ms): SOLUSDT
  8,479,237 contracts; BNBUSDT 564,537
  contracts @17:26Z. Single-sample, not a flow claim. PASS.
- Git safety: bundled:git skill re-read; objective text explicitly
  asks commit+push, authorising history writes.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 317 (BTC/ETH OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 43ad937. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 latest + ticker prices (fetch
  1211ms): BTC OIV 92,969.0 px 83,955.90; ETH
  OIV 2,315,086.7 px 2,545.11 @17:26Z.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 318 (XRP/DOGE OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d0868a0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 latest + ticker prices (fetch
  1175ms): XRP OIV 297,470,659 px 1.4214;
  DOGE OIV 2,707,213,431 px 0.08719 @17:27Z.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 319 (SOL/BNB OI-history PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7f6763d. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 5m x2 latest + ticker prices (fetch
  967ms): SOL OIV 8,479,101 px 112.29;
  BNB OIV 564,708 px 756.55 @17:27Z.
  Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 320 (BTC/ETH funding-rate PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 91d382c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x2 (fetch 483ms): BTC
  10-11 08:00Z -0.0010% | 16:00Z 0.0013%; ETH
  08:00Z -0.0117% | 16:00Z 0.0012%.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 321 (XRP/DOGE funding-rate PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4ff1560. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x2 (fetch 591ms): XRP
  10-11 08:00Z 0.0029% | 16:00Z 0.0060%; DOGE
  08:00Z 0.0044% | 16:00Z 0.0034%.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 322 (SOL/BNB funding-rate PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 357e34d. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x2 (fetch 603ms): SOL
  10-11 08:00Z 0.0059% | 16:00Z 0.0066%; BNB
  08:00Z 0.0000% | 16:00Z 0.0000%.
  Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 323 (BTC/ETH bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 582643f. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker per-symbol (fetch 509ms): BTC
  bid 83,950.40 ask 83,950.50 spread 0.10;
  ETH bid 2,545.63 ask 2,545.64 spread 0.01
  @17:29Z. Single-sample, not a spread claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 324 (XRP/DOGE bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d969840. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker per-symbol (fetch 478ms): XRP
  bid 1.4202 ask 1.4203 spread 0.0001;
  DOGE bid 0.08728 ask 0.08729 spread
  0.0000 @17:30Z. Single-sample, not a spread claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 325 (SOL/BNB bookTicker PASS)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1f7d1b7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker per-symbol (fetch 645ms): SOL
  bid 112.25 ask 112.26 spread 0.01;
  BNB bid 755.94 ask 755.95 spread 0.01
  @17:30Z. Single-sample, not a spread claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 326 (BTC/ETH long/short PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 29b79cd. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x2 (fetch 499ms):
  BTC L/S 1.4242/1.4231; ETH 2.8745/2.8625
  @17:32Z. Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 327 (XRP/DOGE long/short PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8205071. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x2 (fetch 623ms):
  XRP L/S 2.3636/2.3580; DOGE 2.4072/2.4025
  @17:33Z. Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 328 (SOL/BNB long/short PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1af6723. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x2 (fetch 509ms):
  SOL L/S 2.3795/2.3807; BNB 2.1348/2.1319
  @17:33Z. Single-sample, not a sentiment claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 329 (BTC/ETH taker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1e38a17. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle. Git skill safety re-checked this turn:
  objective text explicitly asks commit+push.
- Public takerlongshortRatio 5m x2 (fetch 495ms):
  BTC B/S 1.2897/1.4584; ETH 1.2414/0.9435
  @17:34Z. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 330 (XRP/DOGE taker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 49a2a59. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m x2 (fetch 559ms):
  XRP B/S 1.1471/1.1235; DOGE 1.4111/3.0368
  @17:34Z. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 331 (SOL/BNB taker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at c71fd94. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public takerlongshortRatio 5m x2 (fetch 516ms):
  SOL B/S 0.9677/0.9737; BNB 0.8173/1.0522
  @17:35Z. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 332 (BTC/ETH depth PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ef86968. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit-5 top-3 (fetch 470ms): BTC
  bid 83999.80x0.725 ask 83999.90x13.749;
  ETH bid 2546.55x220.099 ask 2546.56x2.681
  @17:35Z. Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 333 (XRP/DOGE depth PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8903bac. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit-5 top-3 (fetch 635ms): XRP
  bid 1.4234x61799.2 ask 1.4235x20180.2;
  DOGE bid 0.087540x390408 ask 0.087550x196922
  @17:36Z. Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 334 (SOL/BNB depth PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7508de0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth limit-5 top-3 (fetch 710ms): SOL
  bid 112.6200x156.45 ask 112.6300x1427.97;
  BNB bid 757.150x5.74 ask 757.160x20.94
  @17:36Z. Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 335 (BTC/ETH premiumIndex PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 10428ff. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex+ticker/price (fetch 971ms): BTC
  mark 84133.92 funding 0.001939% last 84145.70;
  ETH mark 2550.89 funding 0.001221% last 2551.46
  @17:37Z. Single-sample, not a funding claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 336 (XRP/DOGE premiumIndex PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2b4ee6b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex+ticker/price (fetch 1216ms): XRP
  mark 1.42280 funding 0.008221% last 1.4229;
  DOGE mark 0.087610 funding 0.007550% last 0.087590
  @17:37Z. Single-sample, not a funding claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 337 (SOL/BNB premiumIndex PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b50661c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex+ticker/price (fetch 1244ms): SOL
  mark 112.670 funding 0.010000% last 112.660;
  BNB mark 756.886 funding 0.000000% last 756.880
  @17:38Z. Single-sample, not a funding claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 338 (BTC/ETH aggTrades PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 477be02. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades x3 (fetch 504ms): BTC
  0.035 SELL @84075.50/...; ETH 0.008 BUY @2548.98/...
  @17:38Z. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 339 (XRP/DOGE aggTrades PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at fc5eb31. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades x3 (fetch 548ms): XRP
  5.9 SELL @1.4212/...; DOGE 534 SELL @0.087390/...
  @17:40Z. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 340 (SOL/BNB aggTrades PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at c33b30b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public aggTrades x3 (fetch 613ms): SOL
  0.05 SELL @112.5400/...; BNB 0.04 BUY @756.390/...
  @17:41Z. Single-sample, not a flow claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 341 (BTC/ETH openInterest PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 102e61b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 469ms): BTC 92783.308, ETH
  2320626.919 @17:41Z. Single-sample, not an exposure claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 342 (XRP/DOGE openInterest PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 84ff636. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 576ms): XRP 297086946.5, DOGE
  2716942324 @17:42Z. Single-sample, not an exposure claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 343 (SOL/BNB openInterest PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at dc7e497. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterest (fetch 595ms): SOL 8501501.25, BNB
  564756.55 @17:43Z. Single-sample, not an exposure claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 344 (BTC/ETH OI-history PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1984ec0. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 586ms): BTC 92902.538,
  ETH 2311841.344 @17:00Z bar. Single-sample, not an exposure
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 345 (XRP/DOGE OI-history PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 22d38c7. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 455ms): XRP 298107152.8,
  DOGE 2710446749.0 @17:00Z bar. Single-sample, not an exposure
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 346 (SOL/BNB OI-history PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2451feb. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 623ms): SOL 8474773.6,
  BNB 564690.48 @17:00Z bar. Single-sample, not an exposure
  claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 347 (BTC/ETH fundingRate PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at fc83065. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x1 (fetch 650ms): BTC 0.001347%, ETH
  0.001163% @16:00Z. Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 348 (XRP/DOGE fundingRate PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at edd0606. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x1 (fetch 553ms): XRP 0.006007%, DOGE
  0.003448% @16:00Z. Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 349 (SOL/BNB fundingRate PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at c995743. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public fundingRate x1 (fetch 1510ms): SOL 0.006592%, BNB
  0.000000% @16:00Z. Single-sample, not a cost claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 350 (BTC/ETH klines PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 3e2a057. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 462ms): BTC O83959.90 C83917.20 /
  O83917.20 C83930.50; ETH O2544.23 C2543.02 / O2543.01 C2543.41.
  Single-sample, not a regime claim. Replay of canonical recording
  exit 0. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 351 (XRP/DOGE klines PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 583c0a3. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 509ms): XRP O1.4182 C1.4187 /
  O1.4187 C1.4186; DOGE O0.087260 C0.087320 / O0.087310 C0.087330.
  Single-sample, not a regime claim. M1 slice recovery OK. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 352 (SOL/BNB klines PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at da1b666. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public klines 1m x2 (fetch 455ms): SOL O112.3300 C112.3800 /
  O112.3700 C112.3800; BNB O755.720 C755.820 / O755.810 C755.750.
  Single-sample, not a regime claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 353 (BTC/ETH ticker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 372e36b. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 469ms): BTC last 83931.80 +0.974%;
  ETH last 2544.45 +1.459%. Single-sample, not a momentum claim.
  Git skill re-read pre-push. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 354 (XRP/DOGE ticker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1dd70d2. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 639ms): XRP last 1.4182 +1.004%;
  DOGE last 0.087320 +1.370%. Single-sample, not a momentum claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 355 (SOL/BNB ticker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ee5628c. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 507ms): SOL last 112.3000 +2.007%;
  BNB last 755.500 +0.623%. Single-sample, not a momentum claim.
  PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 356 (BTC/ETH bookTicker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 614362e. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker x1 (fetch 459ms): BTC bid 83899.90 x5.369 /
  ask 83900.00 x7.382; ETH bid 2543.16 x74.084 / ask 2543.17
  x227.071. Single-sample, not a spread claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 357 (XRP/DOGE bookTicker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ba98374. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker x1 (fetch 668ms): XRP bid 1.4183 x35162.6 /
  ask 1.4184 x49694.2; DOGE bid 0.087310 x389936 / ask 0.087320
  x399859. Single-sample, not a spread claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 358 (SOL/BNB bookTicker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9ea3834. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public bookTicker x1 (fetch 465ms): SOL bid 112.4000 x424.00 /
  ask 112.4100 x1992.29; BNB bid 755.780 x83.75 / ask 755.790
  x3.18. Single-sample, not a spread claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 359 (BTC/ETH depth PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 3302014. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth L5 x1 (fetch 578ms): BTC top 83936.50 x4.612 /
  83936.60 x19.003; ETH top 2544.47 x16.225 / 2544.48 x334.267.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 360 (XRP/DOGE depth PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d64a981. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth L5 x1 (fetch 456ms): XRP top 1.4187 x8355.4 /
  1.4188 x46208.4; DOGE top 0.087350 x24300 / 0.087360 x905013.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 361 (SOL/BNB depth PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 175ddcd. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public depth L5 x1 (fetch 608ms): SOL top 112.3800 x942.29 /
  112.3900 x366.82; BNB top 755.580 x48.25 / 755.590 x19.09.
  Single-sample, not a liquidity claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 362 (BTC/ETH premiumIndex PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ff0a4dd. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex x1 (fetch 644ms): BTC mark 83911.40 /
  index 83949.32; ETH mark 2543.06 / index 2544.58.
  Single-sample, not a premium claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 363 (XRP/DOGE premiumIndex PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5ca2f86. E-004 acked (option a, W2 not started,
  worker-side go-ahead pending); V-001R (W1) still awaiting
  go-ahead; W3 idle.
- Public premiumIndex x1 (fetch 491ms): XRP mark 1.41900000 /
  index 1.41948309; DOGE mark 0.08736000 / index 0.08739707.
  Single-sample, not a premium claim. PASS.
- Suite 104/104, evidence gate exit 0.

## Addendum — turn 363b (E-004 STARTED, verified)
- W2 heartbeat received: E-004 started (option a). Verified on
  disk: branch worker2/e-004 from 5ca2f86 in /tmp/cryto-bot-w2,
  discovery.py edit in progress; shared tree untouched. Board
  E-004 assigned -> running.
- V-001R (W1) still awaiting go-ahead; W3 idle. Note: turn-363
  commit message predates this heartbeat.
- Suite 104/104, evidence gate exit 0 (re-verified pre-push).

## Addendum — turn 364 (E-004 ACCEPTED + integrated)
- W2 completion reviewed, not auto-accepted: diff in-scope (4
  files, label + pinning test + README + refreshed sample);
  INPUT_OBSERVED reused from recorder, no contract change; old
  sample removed via rename; stale filename refs only in
  historical records (left intact).
- Suite independently reproduced: 105/105 on worker2/e-004 AND
  on main post-merge. Drift 0 added/0 removed (924/525/524).
  Merged via f74fc3c; outbox E-004.json committed; board
  E-004 running -> accepted.
- V-001R (W1) still awaiting go-ahead; W3 idle. W2 standing by
  for next dispatch.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 365 (SOL/BNB premiumIndex PASS, cycle 2)
- E-004 accepted + merged at 4058bec; W2 standing by. No other
  new outbox filings or worker activity; tree clean on main at
  4058bec. V-001R (W1) still awaiting go-ahead; W3 idle.
- Public premiumIndex x1 (fetch 505ms): SOL mark 112.31032605 /
  index 112.35520032; BNB mark 755.16649935 / index 754.99190137.
  Single-sample, not a premium claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 366 (BTC/ETH L/S PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at cdecf9a. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x1 (fetch 595ms): BTC
  1.4131; ETH 2.8241. Single-sample, not a sentiment claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 367 (XRP/DOGE L/S PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 32e71df. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x1 (fetch 497ms): XRP
  2.2927; DOGE 2.3715. Single-sample, not a sentiment claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 368 (SOL/BNB L/S PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a4ea6ad. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x1 (fetch 479ms): SOL
  2.3322; BNB 2.1328. Single-sample, not a sentiment claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 369 (BTC/ETH taker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e1908e4. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio 5m x1 (fetch 583ms): BTC 1.2230;
  ETH 0.9648. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 370 (XRP/DOGE taker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1d03c42. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio 5m x1 (fetch 642ms): XRP 1.1318;
  DOGE 0.7767. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 371 (SOL/BNB taker PASS, cycle 2)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 78e26c3. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio 5m x1 (fetch 499ms): SOL 1.2205;
  BNB 0.3217. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 372 (BTC/ETH aggTrades PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a6318a1. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public aggTrades x3 (fetch 464ms): BTC 0.100 BUY @83813.80;
  ETH 0.040 BUY @2539.25. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 373 (XRP/DOGE aggTrades PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 74e9e91. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public aggTrades x3 (fetch 604ms): XRP 11.7 SELL @1.4148;
  DOGE 153 BUY @0.087020. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 374 (SOL/BNB aggTrades PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d9eb8d0. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public aggTrades x3 (fetch 496ms): SOL 1.33 BUY @111.9900;
  BNB 0.30 SELL @753.820. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 375 (BTC/ETH OI PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9f4cf8d. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterest x1 (fetch 611ms): BTC 92785.703; ETH
  2323483.934. Single-sample, not a positioning claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 376 (XRP/DOGE OI PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8468c3e. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterest x1 (fetch 458ms): XRP 295000374.5; DOGE
  2711960900. Single-sample, not a positioning claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 377 (SOL/BNB OI PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 8625f63. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterest x1 (fetch 616ms): SOL 8500200.84; BNB
  564663.62. Single-sample, not a positioning claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 378 (BTC/ETH OI-history PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at dcdae7a. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 480ms): BTC 92780.453;
  ETH 2321632.027 @18:00Z bar. Single-sample, not a trend claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 379 (XRP/DOGE OI-history PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5b959c0. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 568ms): XRP 295083942.8;
  DOGE 2712178624.0 @18:00Z bar. Single-sample, not a trend
  claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 380 (SOL/BNB OI-history PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b35a51a. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 637ms): SOL 8499378.86;
  BNB 564820.58 @18:00Z bar. Single-sample, not a trend claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 381 (BTC/ETH fundingRate PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 68ef78c. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public fundingRate x1 (fetch 557ms): BTC 0.001347%; ETH
  0.001163% @16:00Z. Single-sample, not a cost claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 382 (XRP/DOGE fundingRate PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a5c898b. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public fundingRate x1 (fetch 623ms): XRP 0.006007%; DOGE
  0.003448% @16:00Z. Single-sample, not a cost claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 383 (SOL/BNB fundingRate PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2ba91b1. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public fundingRate x1 (fetch 473ms): SOL 0.006592%; BNB
  0.000000% @16:00Z. Single-sample, not a cost claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 384 (BTC/ETH klines PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 3a4c1b3. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public klines 1m x2 (fetch 584ms): BTC O83836.90 C83848.50 /
  O83848.50 C83837.60; ETH O2539.66 C2540.11 / O2540.11 C2540.33.
  Single-sample, not a regime claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 385 (XRP/DOGE klines PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9c3117f. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public klines 1m x2 (fetch 628ms): XRP O1.4157 C1.4162 /
  O1.4162 C1.4162; DOGE O0.087010 C0.087010 / O0.087010 C0.087020.
  Single-sample, not a regime claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 386 (SOL/BNB klines PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 762f3d3. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public klines 1m x2 (fetch 602ms): SOL O112.2800 C112.2600 /
  O112.2600 C112.3300; BNB O754.430 C754.780 / O754.780 C755.000.
  Single-sample, not a regime claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 387 (BTC/ETH ticker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9487b25. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 468ms): BTC last 83846.30 +0.936%;
  ETH last 2539.84 +1.265%. Single-sample, not a momentum claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 388 (XRP/DOGE ticker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e2d898b. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 780ms): XRP last 1.4161 +0.876%;
  DOGE last 0.087050 +1.150%. Single-sample, not a momentum
  claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 389 (SOL/BNB ticker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 041a4f1. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 626ms): SOL last 112.2000 +2.139%;
  BNB last 754.670 +0.572%. Single-sample, not a momentum
  claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 390 (BTC/ETH bookTicker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at bdcb5a3. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public bookTicker x1 (fetch 743ms): BTC bid 83800.30x7.432 /
  ask 83800.40x4.749; ETH bid 2539.35x122.432 /
  ask 2539.36x86.851. Single-sample, not a liquidity claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 391 (XRP/DOGE bookTicker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 947f69d. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public bookTicker x1 (fetch 681ms): XRP bid 1.4150x44107.9 /
  ask 1.4151x75836.7; DOGE bid 0.086960x282689 /
  ask 0.086970x422892. Single-sample, not a liquidity claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 392 (SOL/BNB bookTicker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 12eebff. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public bookTicker x1 (fetch 644ms): SOL bid 112.1100x594.04 /
  ask 112.1200x1293.20; BNB bid 754.460x16.19 /
  ask 754.470x53.84. Single-sample, not a liquidity claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 393 (BTC/ETH depth PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 23e702a. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public depth limit=5 x1 (fetch 510ms): BTC best bid
  83797.80x7.340 / ask 83797.90x4.126; ETH best bid
  2539.37x310.398 / ask 2539.38x111.639. Single-sample, not a
  liquidity claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 394 (XRP/DOGE depth PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 9f00d00. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public depth limit=5 x1 (fetch 491ms): XRP best bid
  1.4148x49883.8 / ask 1.4149x13312.6; DOGE best bid
  0.086970x307735 / ask 0.086980x272592. Single-sample, not a
  liquidity claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 395 (SOL/BNB depth PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1f5c06a. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public depth limit=5 x1 (fetch 799ms): SOL best bid
  112.0500x303.63 / ask 112.0600x2255.63; BNB best bid
  754.430x13.89 / ask 754.440x45.64. Single-sample, not a
  liquidity claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 396 (BTC/ETH premiumIndex PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at ee8ae86. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public premiumIndex+price x1 (fetch 911ms): BTC mark
  83802.94 / index 83837.28 / last 83800.10; ETH mark
  2538.93 / index 2540.47 / last 2538.91. Single-sample, not
  a cost claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 397 (XRP/DOGE premiumIndex PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 668757a. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public premiumIndex+price x1 (fetch 965ms): XRP mark
  1.41421 / index 1.41485 / last 1.4143; DOGE mark
  0.086930 / index 0.086967 / last 0.086930. Single-sample,
  not a cost claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 398 (SOL/BNB premiumIndex PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 931dd6e. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public premiumIndex+price x1 (fetch 1292ms): SOL mark
  111.910 / index 111.964 / last 111.910; BNB mark
  754.246 / index 753.995 / last 754.280. Single-sample,
  not a cost claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 399 (BTC/ETH L/S PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at acf6fdc. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x1 (fetch 521ms):
  BTC ratio 1.4027 @18:10Z; ETH ratio 2.8344 @18:10Z.
  Single-sample, not a sentiment claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 400 (XRP/DOGE L/S PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4eee220. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x1 (fetch 653ms):
  XRP ratio 2.2949 @18:10Z; DOGE ratio 2.3693 @18:10Z.
  Single-sample, not a sentiment claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 401 (SOL/BNB L/S PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 49443bc. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public globalLongShortAccountRatio 5m x1 (fetch 601ms):
  SOL ratio 2.2227 @18:10Z; BNB ratio 2.1348 @18:10Z.
  Single-sample, not a sentiment claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 402 (BTC/ETH taker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 6edd21b. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio 5m x1 (fetch 533ms): BTC
  buySellRatio 1.7048 @18:05Z; ETH buySellRatio 2.0053
  @18:05Z. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 403 (XRP/DOGE taker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at b0d7f51. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio 5m x1 (fetch 493ms): XRP
  buySellRatio 1.1737 @18:05Z; DOGE buySellRatio 0.2789
  @18:10Z. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 404 (SOL/BNB taker PASS, cycle 3)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5ecb92e. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public takerlongshortRatio 5m x1 (fetch 545ms): SOL
  buySellRatio 0.4123 @18:10Z; BNB buySellRatio 1.0102
  @18:10Z. Single-sample, not a flow claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 405 (BTC/ETH aggTrades PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 48b3e64. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle. Cycle 3 closed (turns
  372-404, 33 snapshots); cycle 4 begins.
- Public aggTrades x3 (fetch 641ms): BTC 0.004 BUY
  @83857.30; ETH 0.011 SELL @2540.35. Single-sample, not a
  liquidity claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 406 (XRP/DOGE aggTrades PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 50f7140. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public aggTrades x3 (fetch 607ms): XRP 7.0 BUY @1.4148;
  DOGE 327 BUY @0.086950. Single-sample, not a
  liquidity claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 407 (SOL/BNB aggTrades PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 1c3621f. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public aggTrades x3 (fetch 659ms): SOL 282.09 BUY
  @111.9300; BNB 4.11 SELL @753.930. Single-sample, not a
  liquidity claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 408 (BTC/ETH OI PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at bb8bc7f. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterest x1 (fetch 475ms): BTC 92819.173;
  ETH 2323929.138. Single-sample, not a leverage claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 409 (XRP/DOGE OI PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 901a1eb. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterest x1 (fetch 462ms): XRP 294836546.6;
  DOGE 2709791708. Single-sample, not a leverage claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 410 (SOL/BNB OI PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at d9ed096. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterest x1 (fetch 604ms): SOL 8491512.76;
  BNB 565000.46. Single-sample, not a leverage claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 411 (BTC/ETH OI-history PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2880479. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 753ms): BTC
  92780.453 @18:00Z bar; ETH 2321632.027 @18:00Z bar.
  Single-sample, not a leverage claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 412 (XRP/DOGE OI-history PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 0eb9c47. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 492ms): XRP
  295083942.8 @18:00Z bar; DOGE 2712178624.0 @18:00Z
  bar. Single-sample, not a leverage claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 413 (SOL/BNB OI-history PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at a5715cc. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public openInterestHist 1h x1 (fetch 614ms): SOL
  8499378.86 @18:00Z bar; BNB 564820.58 @18:00Z bar.
  Single-sample, not a leverage claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 414 (BTC/ETH fundingRate PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at e03ab92. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public fundingRate x1 (fetch 486ms): BTC 0.001347% @16:00Z;
  ETH 0.001163% @16:00Z. Single-sample, not a cost claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 415 (XRP/DOGE fundingRate PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7c301d4. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public fundingRate x1 (fetch 602ms): XRP 0.006007% @16:00Z;
  DOGE 0.003448% @16:00Z. Single-sample, not a cost claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 416 (SOL/BNB fundingRate PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 57f18b9. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public fundingRate x1 (fetch 599ms): SOL 0.006592% @16:00Z;
  BNB 0.000000% @16:00Z. Single-sample, not a cost claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 417 (BTC/ETH klines PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 937c3d1. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public klines 1m x2 (fetch 466ms): BTC O83834.40 C83842.10
  / O83842.10 C83836.50; ETH O2539.80 C2539.95 /
  O2539.95 C2539.94. Single-sample, not a regime claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 418 (XRP/DOGE klines PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 06adb0c. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public klines 1m x2 (fetch 487ms): XRP O1.4150 C1.4151 /
  O1.4151 C1.4154; DOGE O0.086960 C0.086980 /
  O0.086980 C0.086960. Single-sample, not a regime claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 419 (SOL/BNB klines PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 5adaff7. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public klines 1m x2 (fetch 493ms): SOL O111.9400 C111.9800
  / O111.9700 C111.9900; BNB O754.360 C754.330 /
  O754.330 C754.330. Single-sample, not a regime claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 420 (BTC/ETH ticker PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 0cb3782. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 463ms): BTC last 83831.30
  +1.055%; ETH last 2539.71 +1.298%. Single-sample, not
  a momentum claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 421 (XRP/DOGE ticker PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 03f0cf4. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 596ms): XRP last 1.4141
  +0.827%; DOGE last 0.086910 +1.105%. Single-sample, not
  a momentum claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 422 (SOL/BNB ticker PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 4349f81. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public ticker/24hr x1 (fetch 483ms): SOL last 111.9200
  +1.773%; BNB last 754.170 +0.525%. Single-sample, not
  a momentum claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 423 (BTC/ETH bookTicker PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 7cd582c. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public bookTicker x1 (fetch 583ms): BTC bid 83830.90x8.109 /
  ask 83831.00x3.879; ETH bid 2539.52x130.851 /
  ask 2539.53x79.134. Single-sample, not a liquidity claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 424 (XRP/DOGE bookTicker PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2e7d1a1. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public bookTicker x1 (fetch 612ms): XRP bid 1.4142x66678.7 /
  ask 1.4143x16731.7; DOGE bid 0.086910x757944 /
  ask 0.086920x134761. Single-sample, not a liquidity claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 425 (SOL/BNB bookTicker PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 387f44c. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public bookTicker x1 (fetch 723ms): SOL bid 111.9500x525.87 /
  ask 111.9600x1367.66; BNB bid 754.160x25.74 /
  ask 754.170x75.75. Single-sample, not a liquidity claim.
  PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 426 (BTC/ETH depth PASS, cycle 4)
- No new outbox filings, commits, or worker activity; tree clean on
  main at 2d37e50. E-004 accepted; W2 standing by. V-001R (W1)
  still awaiting go-ahead; W3 idle.
- Public depth limit=5 x1 (fetch 679ms): BTC best bid
  83835.90x5.624 / ask 83836.00x15.178; ETH best bid
  2539.53x79.473 / ask 2539.54x126.516. Single-sample, not
  a liquidity claim. PASS.
- Suite 105/105, evidence gate exit 0.

## Addendum — turn 427 (XRP/DOGE depth PASS + V-001R/V-001 ACCEPT,
  cycle 4)
- Public depth limit=5 x1 (fetch 483ms): XRP best bid
  1.4136x55469.3 / ask 1.4137x64465.3; DOGE best bid
  0.086890x180581 / ask 0.086900x669158. Single-sample, not
  a liquidity claim. PASS.
- V-001R COMPLETE filed by W1 (whisper-redshift) 18:30:36Z after
  worker-side user go-ahead; standing auto-start instruction saved by
  W1 for future dispatches. Filing verified field-by-field against
  the 4 inbox acceptance conditions: suite 34 passed x2 (sizing 5,
  gates 10, halts 7, profit 5, ledger 5, determinism 2), hand
  halt-persistence case PASS (Rejected halt:daily-loss), R-001..R-012
  all pass with per-invariant mapping, read-only proof (140-file
  list + 36 V-001 sha256 identical, w3 status unchanged), zero
  unresolved, base w3 HEAD 4290233 confirmed. V-001R ACCEPTED.
- Manager independent repro (read-only, /tmp/v001r-mgr cwd,
  PYTHONDONTWRITEBYTECODE, no cacheprovider, worktree PYTHONPATH):
  34 passed; w3 tree untouched (6 untracked entries before=after).
- V-001 ACCEPTED (review-pass turn-9 + V-001R repro completes the
  no-self-certification chain) and integrated onto main via
  provenance copy of the 21 manifest files (specs/acceptance-risk.md,
  specs/acceptance-review-q001-e001.md, risk x5, accounting x3,
  acceptance tests x7, fixtures x4); all within V-001 allowed paths.
  Merged-tree verification: tests/acceptance 34/34, full suite
  139/139 (105 + 34), evidence gate exit 0. Board: V-001 +
  V-001R -> accepted; W1 + W3 idle; D-012 recorded. U-001/U-002/U-003
  carry forward. W2 still awaiting E-004 go-ahead (unchanged).
- Suite 139/139, evidence gate exit 0.

## Addendum — turn 428 (Q-002 + V-003 DISPATCHED, SOL/BNB depth
  PASS, cycle 4)
- Q-002 dispatched to W1 (whisper-redshift), inbox msg-Q-002-01:
  S2-S5 follow-up with the D-010 correction (S2/S3/S4 specs must
  match directive hypotheses or carry a substitution rationale for
  CEO/owner review), causal S2 baseline + fixtures + EXP-002, on
  new branch worker1/q-002 from eb85157. Board: assigned.
- V-003 dispatched to W3 (cool-amalthea), inbox msg-V-003-01:
  v0.1.1 risk wiring (run accepted V-001 RiskPolicy + ledger in
  the M1 slice path; risk//accounting/tests/specs only, manager
  integrates) plus U-003 disposition, on new branch worker3/v-003
  from eb85157. Board: assigned.
- Both dispatch messages transport-handed, delivery unconfirmed
  (standard pattern). W1 saved a standing auto-start instruction
  on its side (turn-427), so Q-002 may start without a fresh
  go-ahead; V-003 needs the owner to activate W3. W2 still
  awaiting E-004 go-ahead (unchanged).
- Public depth limit=5 x1 (fetch 797ms): SOL best bid
  111.9700x185.10 / ask 111.9800x2542.56; BNB best bid
  754.140x1.93 / ask 754.150x60.42. Single-sample, not
  a liquidity claim. PASS.
- Suite 139/139, evidence gate exit 0.

## Addendum — turn 429 (V-003 RUNNING, BTC/ETH premiumIndex PASS,
  cycle 4)
- W3 (cool-amalthea) acked V-003 STARTING via real message:
  fresh worktree /tmp/cryto-bot-w3-003 on branch worker3/v-003
  from eb85157 (v-001 worktree untouched); plan = wiring module
  in risk/ + RiskOutcomeSink conformance/duplicate-callback tests
  + U-003 pinned-as-simulation-defaults with boundary tests and
  measurement plan; U-001 noted only; ETA this session. Board:
  V-003 -> running. Verified: worktree exists at eb85157, clean,
  no commits yet.
- W1 created fresh worktree /tmp/cryto-bot-w1q2 on worker1/q-002
  from eb85157 (clean, no commits) but has not acked yet; Q-002
  stays assigned until an ack or first commit is observed. W2
  still awaiting E-004 go-ahead (unchanged).
- Public premiumIndex x1 + ticker/price x1 (fetch 946ms): BTC
  mark 83811.53823188 / index 83853.64434783 / last 83814.30 /
  lastFunding 0.00002076; ETH mark 2539.34608527 / index
  2540.73348837 / last 2539.50 / lastFunding 0.00001084;
  nextFunding 1791763200000 both. Single-sample, not a
  funding/liquidity claim. PASS.
- Suite 139/139, evidence gate exit 0.

## Addendum — turn 430 (Q-002 RUNNING, V-003 progressing,
  XRP/DOGE premiumIndex PASS, cycle 4)
- W1 (whisper-redshift) acked Q-002 START via real message
  (auto-start per standing instruction; inbox msg-Q-002-01
  read): worktree /tmp/cryto-bot-w1q2 on worker1/q-002 from
  eb85157 (origin/main tip verified), baseline 139/139 green,
  contract delta checked (intent.py unchanged); plan = D-010
  correction by adopting directive hypotheses for S2/S3/S4
  (no substitution rationale needed), S2 baseline mirroring S1
  (3 arms, warmup, long/short split) + SYNTH_V1 + EXP-002,
  ETA this session. Board: Q-002 -> running. Verified: branch
  at eb85157, tree clean (just started).
- V-003 progressing: w3 worktree shows M ledger.py,
  risk/__init__.py, risk/types.py + new risk/slice.py (wiring
  module), all within V-003 allowed paths; no commits yet.
  Read-only check; manager did not touch the worktree. W2
  still awaiting E-004 go-ahead (unchanged).
- Public premiumIndex x1 + ticker/price x1 (fetch 970ms): XRP
  mark 1.41188461 / index 1.41243204 / last 1.4118 /
  lastFunding 0.00009376; DOGE mark 0.08685025 / index
  0.08689805 / last 0.086840 / lastFunding 0.00007681;
  nextFunding 1791763200000 both. Single-sample, not a
  funding/liquidity claim. PASS.
- Suite 139/139, evidence gate exit 0.

## Addendum — turn 431 (Q-002/V-003 both active, SOL/BNB
  premiumIndex PASS, cycle 4)
- Q-002 active: w1 worktree now shows M specs/strategies/S2.md
  (D-010 correction underway), within allowed paths; no commits
  or outbox filing yet. V-003 active: w3 worktree unchanged
  since turn-430 (M ledger.py, risk/__init__.py, risk/types.py
  + new risk/slice.py), all within allowed paths; no commits
  yet. Both read-only checks; manager touched neither
  worktree. W2 still awaiting E-004 go-ahead (unchanged).
- Public premiumIndex x1 + ticker/price x1 (fetch 1274ms):
  SOL mark 111.94555847 / index 111.98100934 / last 111.9500
  / lastFunding 0.00010000; BNB mark 754.39342383 / index
  754.07951015 / last 754.260 / lastFunding 0.00000000;
  nextFunding 1791763200000 both. Single-sample, not a
  funding/liquidity claim. PASS.
- Suite 139/139, evidence gate exit 0.

## Addendum — turn 432 (V-003 ACCEPTED + integrated, BTC/ETH
  L/S PASS, cycle 4)
- V-003 COMPLETE filed by W3 (cool-amalthea) 18:41:16Z with a
  same-turn review handoff: SliceRisk wiring over accepted
  V-001 RiskPolicy + Ledger, sink conformance,
  duplicate-callback tolerance, U-003 pinned with boundary
  tests + measurement plan, U-001 noted only; branch
  worker3/v-003 ff to base c84499f, uncommitted diff per
  policy, 148/148 claimed. Manager verified all 4 inbox
  conditions field-by-field, read slice.py + both new test
  files + specs/acceptance-u003.md in full, and reproduced
  148/148 read-only from /tmp/cryto-bot-w3-003 (worktree
  untouched). V-003 ACCEPTED (D-013).
- Integrated onto main via provenance copy of the 7 files
  (risk/slice.py new, risk/__init__.py, risk/types.py,
  accounting/ledger.py, 2 acceptance test files,
  specs/acceptance-u003.md; all within V-003 allowed paths);
  manager wired SliceRisk into tools/m1_vertical_slice.py and
  removed risk_stub. Merged-tree verification: slice exit 0
  (risk-policy:approved:reservation=r-000001:budget=0.2500,
  notional 80.14, rejected trade + fault recovery intact),
  full suite 148/148 (139 + 9), evidence gate exit 0. Board:
  V-003 -> accepted; W3 idle. Q-002 still running (w1 tree:
  M S2/S3/S4 specs, M s1.py, new _shared.py); W2 still
  awaiting E-004 go-ahead (unchanged).
- Public globalLongShortAccountRatio 5m x1 (fetch 674ms):
  BTC ratio 1.3969 (long 0.5828 / short 0.4172); ETH ratio
  2.8285 (long 0.7388 / short 0.2612); ts 1791744000000.
  Single-sample, not a sentiment/positioning claim. PASS.
- Suite 148/148, evidence gate exit 0.

## Addendum — turn 433 (Q-002 expanding, XRP/DOGE L/S PASS,
  cycle 4)
- Q-002 progressing: w1 worktree now shows M S2/S3/S4 specs,
  M features/__init__.py, M research/__init__.py +
  experiments.py + synthetic.py, M strategies/__init__.py +
  contract.py + s1.py, and new features/pullback.py — all
  within Q-002 allowed paths. Branch still at base eb85157,
  no commits or outbox filing yet; W1 was instructed to
  rebase onto latest main before filing (main now 8696f4b).
  Read-only check; manager touched nothing. W3 idle
  (confirmed), W2 still awaiting E-004 go-ahead (unchanged).
- Public globalLongShortAccountRatio 5m x1 (fetch 510ms):
  XRP ratio 2.2916 (long 0.6962 / short 0.3038); DOGE ratio
  2.3625 (long 0.7026 / short 0.2974); ts 1791744000000.
  Single-sample, not a sentiment/positioning claim. PASS.
- Suite 148/148, evidence gate exit 0.

## Addendum — turn 434 (Q-002 S2 baseline appearing, SOL/BNB
  L/S PASS, cycle 4)
- Q-002 progressing: w1 worktree adds new
  src/cryptobot/strategies/s2.py (S2 baseline) alongside the
  S2/S3/S4 spec rewrites, features/pullback.py, _shared.py,
  and research/strategy edits — all within Q-002 allowed
  paths. Branch still at base eb85157, no commits or outbox
  filing yet. Read-only check; manager touched nothing. W3
  idle (confirmed), W2 still awaiting E-004 go-ahead
  (unchanged).
- Public globalLongShortAccountRatio 5m x1 (fetch 627ms):
  SOL ratio 2.2196 (long 0.6894 / short 0.3106); BNB ratio
  2.1377 (long 0.6813 / short 0.3187); ts 1791744000000.
  Single-sample, not a sentiment/positioning claim. PASS.
- Suite 148/148, evidence gate exit 0.

## Addendum — turn 435 (Q-002 steady, BTC/ETH taker PASS,
  cycle 4)
- Q-002 unchanged since turn-434: w1 worktree still shows
  the same 13 entries (S2/S3/S4 specs, features/research/
  strategies edits, new pullback.py/_shared.py/s2.py), all
  within allowed paths; branch at eb85157, no commits or
  outbox filing yet. Read-only check; manager touched
  nothing. W3 idle (confirmed), W2 still awaiting E-004
  go-ahead (unchanged).
- Public takerlongshortRatio 5m x1 (fetch 843ms): BTC
  buySellRatio 0.6119 (buy 29.7090 / sell 48.5530); ETH
  buySellRatio 1.0596 (buy 981.4450 / sell 926.2240); ts
  1791743700000. Single-sample, not a flow claim. PASS.
- Suite 148/148, evidence gate exit 0.

## Addendum — turn 436 (Q-002 tests + EXP-002 appearing,
  XRP/DOGE taker PASS, cycle 4)
- Q-002 progressing: w1 worktree grows to 18 entries — adds
  M tests/unit/test_strategies_{contract,features,research}.py
  plus new specs/strategies/EXP-002.md and
  tests/unit/test_strategies_s2.py, on top of the S2/S3/S4
  spec rewrites and s2.py/pullback.py/_shared.py work; all
  within Q-002 allowed paths. Branch still at eb85157, no
  commits or outbox filing yet. Read-only check; manager
  touched nothing. W3 idle (confirmed), W2 still awaiting
  E-004 go-ahead (unchanged).
- Public takerlongshortRatio 5m x1 (fetch 628ms): XRP
  buySellRatio 0.3501 (buy 299552.6000 / sell 855576.1000);
  DOGE buySellRatio 0.5542 (buy 2109226.0000 / sell
  3805675.0000); ts 1791743700000. Single-sample, not a
  flow claim. PASS.
- Suite 148/148, evidence gate exit 0.

## Addendum — turn 437 (Q-002 rebased onto main, SOL/BNB
  taker PASS, cycle 4 CLOSED)
- Q-002 nearing filing: W1 fast-forwarded worker1/q-002 to
  8176d33 (turn-435 main, per the rebase-before-filing
  instruction); same 18 file entries (S2/S3/S4 specs,
  features/research/strategies code, EXP-002, S2 + updated
  unit tests), all within allowed paths; no commits of its
  own or outbox filing yet. Read-only check; manager
  touched nothing. W3 idle (confirmed), W2 still awaiting
  E-004 go-ahead (unchanged).
- Public takerlongshortRatio 5m x1 (fetch 645ms): SOL
  buySellRatio 0.3779 (buy 11459.3400 / sell 30324.2100),
  ts 1791744000000; BNB buySellRatio 1.8796 (buy 253.2700
  / sell 134.7500), ts 1791743700000. Single-sample, not
  a flow claim. PASS.
- Cycle 4 closed: turns 405-437, 33 snapshots
  (aggTrades/OI/OI-hist/funding/klines/ticker/bookTicker/
  depth/premiumIndex/L-S/taker x 3 pairs each). Next cycle
  restarts at BTC/ETH aggTrades.
- Suite 148/148, evidence gate exit 0.
- Turn-438 (manager review): Q-002 ACCEPTED (D-014). Verified
  18/18 filing hashes, all paths allowed, repro 167/167
  read-only from /tmp/cryto-bot-w1q2 (tree untouched), read
  S2/S3/S4/EXP-002 + s2.py in full, M1 slice exit 0 from the
  w1 tree. Integration fix: s1 arm validation narrowed to
  ARM_IDS_S1 (direct probe OK). Provenance copy onto main
  (no overlap with 8176d33..29a1a10); merged tree 167/167,
  slice exit 0, gate exit 0. Board Q-002 -> accepted. No M2
  sample this turn (review turn); cycle 5 starts next turn.
- Turn-439 (cycle 5 opens): public aggTrades x1 (BTC 331ms,
  ETH 296ms): BTC a3481569477 p83556.70 q0.004 mTrue
  T1791744814451; ETH a3114466087 p2529.86 q0.700 mFalse
  T1791744814527. Single-sample, not a flow claim. PASS.
  W1 -> idle (Q-002 accepted); W3 idle, W2 still awaiting
  E-004 go-ahead. Suite 167/167, evidence gate exit 0.
- Turn-440 (cycle 5): public aggTrades x1 (XRP 270ms, DOGE
  234ms): XRP a788083331 p1.4072 q5.7 mFalse T1791744875798;
  DOGE a1039788654 p0.086580 q92 mFalse T1791744875799.
  Single-sample, not a flow claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-441 (cycle 5): public aggTrades x1 (SOL 260ms, BNB
  211ms): SOL a1104935052 p111.4900 q0.68 mFalse
  T1791744908359; BNB a874109772 p752.780 q0.07 mTrue
  T1791744907841. Single-sample, not a flow claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-442 (cycle 5): public openInterest x1 (BTC 317ms,
  ETH 284ms): BTC oi92548.305 T1791744943991; ETH
  oi2314717.717 T1791744943225. Single-sample, not a
  positioning claim. PASS. Suite 167/167, evidence
  gate exit 0.
- Turn-443 (cycle 5): public openInterest x1 (XRP 261ms,
  DOGE 226ms): XRP oi294993410.0 T1791744981522; DOGE
  oi2704630877 T1791744977275. Single-sample, not a
  positioning claim. PASS. Suite 167/167, evidence
  gate exit 0.
- Turn-444 (cycle 5): public openInterest x1 (SOL 362ms,
  BNB 287ms): SOL oi8483110.28 T1791745028874; BNB
  oi564366.16 T1791745027563. Single-sample, not a
  positioning claim. PASS. Suite 167/167, evidence
  gate exit 0.
- Turn-445 (cycle 5): public openInterestHist 5m x1 (BTC
  246ms, ETH 226ms): BTC sumOI92549.10
  value7734846561.96 T1791744900000; ETH sumOI2312776.655
  value5849209571.22 T1791744600000. Rows carry no
  symbolPrice (separate ticker call when priced).
  Single-sample, not a positioning claim. PASS. Suite
  167/167, evidence gate exit 0.
- Turn-446 (cycle 5): public openInterestHist 5m x1 (XRP
  609ms, DOGE 301ms): XRP sumOI295046796.50
  value415248861.39 T1791744900000; DOGE sumOI2703630225.0
  value234134377.49 T1791744900000. Single-sample, not
  a positioning claim. PASS. Suite 167/167, evidence
  gate exit 0.
- Turn-447 (cycle 5): public openInterestHist 5m x1 (SOL
  281ms, BNB 226ms): SOL sumOI8484803.23
  value946162017.61 T1791745200000; BNB sumOI564661.70
  value424998275.12 T1791745200000. Single-sample, not
  a positioning claim. PASS. Suite 167/167, evidence
  gate exit 0.
- Turn-448 (cycle 5): public fundingRate x1 (BTC 310ms,
  ETH 283ms): BTC rate0.00001347 T1791734400002; ETH
  rate0.00001163 T1791734400002. Single-sample, not
  a cost/positioning claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-449 (cycle 5): public fundingRate x1 (XRP 283ms,
  DOGE 216ms): XRP rate0.00006007 T1791734400002; DOGE
  rate0.00003448 T1791734400002. Single-sample, not
  a cost/positioning claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-450 (cycle 5): public fundingRate x1 (SOL 352ms,
  BNB 273ms): SOL rate0.00006592 T1791734400002; BNB
  rate0.00000000 T1791734400002. Single-sample, not
  a cost/positioning claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-451 (cycle 5): public klines 1m x1 (BTC 240ms,
  ETH 222ms), T1791745380000: BTC o83667.60 h83680.00
  l83667.60 c83679.90 v7.302 n369; ETH o2535.63
  h2536.44 l2535.62 c2536.44 v1438.725 n1071.
  Single-sample, not a trend/liquidity claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-452 (cycle 5): public klines 1m x1 (XRP 242ms,
  DOGE 216ms), T1791745440000: XRP o1.4098 h1.4098
  l1.4097 c1.4098 v28263.2 n76; DOGE o0.086850
  h0.086860 l0.086850 c0.086850 v129007 n72.
  Single-sample, not a trend/liquidity claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-453 (cycle 5): public klines 1m x1 (SOL 282ms,
  BNB 236ms), T1791745440000: SOL o111.6300 h111.6400
  l111.5900 c111.6200 v3593.23 n769; BNB o753.220
  h753.220 l753.010 c753.130 v156.38 n330.
  Single-sample, not a trend/liquidity claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-454 (cycle 5): public ticker/24hr (BTC 260ms,
  ETH 219ms): BTC last83667.80 chg%0.811 h84180.00
  l82751.10 qv4932168337.99 n1094330 T1791745528652;
  ETH last2535.72 chg%0.954 h2553.76 l2496.12
  qv4297359333.63 n1781304 T1791745527382.
  Single-sample, not a volume/liquidity claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-455 (cycle 5): public ticker/24hr (XRP 323ms,
  DOGE 280ms): XRP last1.4092 chg%0.420 h1.4260
  l1.3865 qv437718615.2966 n760681 T1791745572708;
  DOGE last0.086770 chg%0.813 h0.087620 l0.084850
  qv211006483.585960 n571788 T1791745569401.
  Single-sample, not a volume/liquidity claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-456 (cycle 5): public ticker/24hr (SOL 286ms,
  BNB 226ms): SOL last111.3900 chg%1.080 h112.7300
  l108.8900 qv1017803204.7584 n1081866
  T1791745713186; BNB last752.460 chg%0.271
  h758.770 l744.910 qv167106883.434 n459244
  T1791745710000. Single-sample, not a
  volume/liquidity claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-457 (cycle 5): public bookTicker (BTC 267ms,
  ETH 217ms): BTC bid83622.50 ask83622.60
  bq1.000 aq10.567 sprd0.1000; ETH bid2533.43
  ask2533.44 bq6.134 aq248.674 sprd0.0100.
  Single-sample, not a spread/depth claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-458 (cycle 5): public bookTicker (XRP 377ms,
  DOGE 294ms): XRP bid1.4082 ask1.4083 bq53799.2
  aq48138.2 sprd0.000100; DOGE bid0.086710
  ask0.086720 bq191941 aq513932 sprd0.000010.
  Single-sample, not a spread/depth claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-459 (cycle 5): public bookTicker (SOL 315ms,
  BNB 286ms): SOL bid111.3400 ask111.3500
  bq2322.17 aq441.08 sprd0.0100; BNB bid752.610
  ask752.620 bq1.60 aq110.25 sprd0.0100.
  Single-sample, not a spread/depth claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-460 (cycle 5): public depth limit=5 (BTC
  264ms, ETH 236ms): BTC id11790000243940
  bid83652.10x3.203 ask83652.20x7.346
  T1791745892288; ETH id11790000256441
  bid2534.36x66.465 ask2534.37x96.017
  T1791745892530. Single-sample, not a
  depth/liquidity claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-461 (cycle 5): public depth limit=5 (XRP
  338ms, DOGE 276ms): XRP id11790003306851
  bid1.4084x34444.0 ask1.4085x42486.4
  T1791745929917; DOGE id11790003324925
  bid0.086720x614059 ask0.086730x243013
  T1791745930187. Single-sample, not a
  depth/liquidity claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-462 (cycle 5): public depth limit=5 (SOL
  282ms, BNB 221ms): SOL id11790005898308
  bid111.3700x238.73 ask111.3800x3000.54
  T1791745970893; BNB id11790005907544
  bid752.760x20.50 ask752.770x14.92
  T1791745971100. Single-sample, not a
  depth/liquidity claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-463 (cycle 5): public premiumIndex (BTC
  457ms, ETH 290ms): BTC mark83664.35167391
  idx83701.06108696 fund0.00002612
  nextT1791763200000 T1791746034000; ETH
  mark2534.33000000 idx2535.48325581
  fund0.00002141 nextT1791763200000
  T1791746034000. Single-sample, not a
  funding/cost claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-464 (cycle 5): public premiumIndex (XRP
  462ms, DOGE 214ms): XRP mark1.40870000
  idx1.40926979 fund0.00010000
  nextT1791763200000 T1791746070000; DOGE
  mark0.08678062 idx0.08682366 fund0.00008030
  nextT1791763200000 T1791746071004.
  Single-sample, not a funding/cost claim.
  PASS. Suite 167/167, evidence gate exit 0.
- Turn-465 (cycle 5): public premiumIndex (SOL
  332ms, BNB 288ms): SOL mark111.40315224
  idx111.44033748 fund0.00010000
  nextT1791763200000 T1791746263000; BNB
  mark753.27000000 idx753.00754366
  fund0.00000000 nextT1791763200000
  T1791746263000. Single-sample, not a
  funding/cost claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-466 (cycle 5): public
  globalLongShortAccountRatio 5m (BTC 335ms,
  ETH 297ms): BTC L/S1.3889 longAcc0.5814
  shortAcc0.4186; ETH L/S2.8329
  longAcc0.7391 shortAcc0.2609; T1791746100000.
  Single-sample, not a sentiment claim.
  PASS. Suite 167/167, evidence gate exit 0.
- Turn-467 (cycle 5): public
  globalLongShortAccountRatio 5m (XRP 286ms,
  DOGE 213ms): XRP L/S2.2982 longAcc0.6968
  shortAcc0.3032; DOGE L/S2.3557
  longAcc0.7020 shortAcc0.2980; T1791746100000.
  Single-sample, not a sentiment claim.
  PASS. Suite 167/167, evidence gate exit 0.
- Turn-468 (cycle 5): public
  globalLongShortAccountRatio 5m (SOL 261ms,
  BNB 310ms): SOL L/S2.2041 longAcc0.6879
  shortAcc0.3121; BNB L/S2.1377
  longAcc0.6813 shortAcc0.3187; T1791746100000.
  Single-sample, not a sentiment claim.
  PASS. Suite 167/167, evidence gate exit 0.
- Turn-469 (cycle 5): public takerlongshortRatio
  5m (BTC 427ms, ETH 297ms): BTC
  buySell3.5632 buyVol281.32 sellVol78.952;
  ETH buySell1.0031 buyVol1243.517
  sellVol1239.718; T1791745800000.
  Single-sample, not a flow claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-470 (cycle 5): public takerlongshortRatio
  5m (XRP 527ms, DOGE 361ms): XRP
  buySell0.4786 buyVol316830.4
  sellVol662000.6 T1791746100000; DOGE
  buySell3.7939 buyVol7388475.0
  sellVol1947472.0 T1791745800000.
  Single-sample, not a flow claim. PASS.
  Suite 167/167, evidence gate exit 0.
- Turn-471 (cycle 5): public takerlongshortRatio
  5m (SOL 323ms, BNB 288ms): SOL
  buySell2.0850 buyVol12606.06
  sellVol6045.94 T1791745800000; BNB
  buySell1.9027 buyVol220.71 sellVol116.00
  T1791746100000. Single-sample, not a flow
  claim. PASS. Suite 167/167, evidence
  gate exit 0.
- Turn-472 (cycle 5): public ticker/price
  (BTC 324ms, ETH 342ms): BTC 83698.10;
  ETH 2535.49. Single-sample, not a
  valuation claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-473 (cycle 5): public ticker/price
  (XRP 260ms, DOGE 217ms): XRP 1.4096;
  DOGE 0.086910. Single-sample, not a
  valuation claim. PASS. Suite 167/167,
  evidence gate exit 0.
- Turn-474 (cycle 5): public ticker/price
  (SOL 262ms, BNB 214ms): SOL 111.3500;
  BNB 753.150. Single-sample, not a
  valuation claim. PASS. Suite 167/167,
  evidence gate exit 0.
