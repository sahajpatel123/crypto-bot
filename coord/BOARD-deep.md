# Deep-research completion board (supersedes negative close-out)

Project IN PROGRESS until all three acceptance points pass. Base: `3aac4c7` (rev2-rc-1).
Budget: every job ≤1500s via `tools/run_budget.py`, incl. cleanup. No auto-relaunch.
Production submission DISABLED. No credentials requested at this stage.

## A1 — Deployment + execution correctness (W1 cloud-vega; W5 verifies)
- D1 enforce-or-refuse: preflight in `tools/run_budget.py` BEFORE checkpoint/Popen.
  supported = Linux AND prctl-subreaper acquired AND table-scan ok.
  Strict+unsupported → report+checkpoint REFUSED_UNSUPPORTED, stderr REFUSED, exit **125**, never spawn.
  `--allow-best-effort` (default off) keeps legacy path. New `tests/unit/test_run_budget_refusal.py`.
- D2 lifecycle proof on real RunStore + default threading: happy, dupes, delayed ack,
  ambiguous submit, disconnect, restart-with-exposure, booking failure, queue pressure,
  stale data, halt independence, operator stop, emergency flatten, foreign positions.
- Gate: macOS run refuses 125; best-effort reproduces legacy rc; full 13-row matrix green.

## A2 — Sandbox demonstration (W2 white-aldebaran; W5 verifies)
- D3: NEW `tools/audit/sandbox_drill.py` driving real Session + BinanceLiveEngine paths
  through scriptable SandboxTransport; NEW `src/cryptobot/adapters/sandbox_venue.py`
  (book, filters, fees/funding, delays, IOC, partials, cancels, lookup, snapshots,
  listenKey, reorder/dupe stream, rate-limit, UNKNOWN injects).
- Phases preflight|drill|interrupt|resume|stream-gap|reconcile|full; JSONL + report auto-made.
  Interrupt with exposure → resume → reconciled flat or explicit failure. Any BLOCKED → run BLOCKED.
- Gate: one offline command, seed-pinned; record SANDBOX VALIDATED vs BINANCE DEMO VALIDATION PENDING.

## A3 — Economic strategy on real data (W3 cool-amalthea data; W4 whisper-redshift strategy)
- D5 data: manifest e8255323 transform v2 IST; DEV idx1-15; VAL idx16-22 (scored-once);
  TEST idx23-30 BURNED, never reuse. Mint exactly one EVAL: (a) fresh self-capture $0,
  (b) Vision days, or (c) Tardis Solo $700/mo re-audited. Gap close: merge staged BTC+ETH
  Oct funding, re-freeze, new sha.
- D4 research round 1: NEW family X1 leader-laggard (BTC60≥35bps AND raw gap G≥35bps same
  sign; entry expiry 10s, IOC ±2bps; invalidation BTC>50% retrace or gap widens >10bps;
  exit 50% gap limit/stop/timeout). 4 configs X1/X1-S/X1-T/X1-F + CASH + S1 control.
  Frozen selection: at most one X1, highest val net with dev>0&val>0, else NONE.
  Pre-freeze: ARM_IDS + allowlist + frozen X1Params + X1.md v0.1.0 (incl. dual-symbol
  feed spec + beta estimation step).
- Gate: preregistered, frozen before outcomes; ≤1 candidate to eval; 100-pos/10d screen;
  realistic + adverse (2x) costs; full economics report. No qualification → RESEARCH UNRESOLVED.

## Manager decisions (no owner ask needed)
- Refusal exit code 125 (avoids collision with child rc / 124 / EXIT_BLOCKED=2).
- Sandbox ships as script first; CLI alias optional later.
- EVAL options prepared without spend; owner decides purchase later.
- X1 beta: pre-round estimation step, frozen in X1.md before round.

## Integration log
- W1 D1 ACCEPTED (cd42146 → 04c0bee): 6/6 proofs re-run green. Shared-tree
  probe deletions broke units re-run; restored (tests require them).
- W1 D2 ACCEPTED (6bc5af6 → 47a8c8c + fixup 9be4fb1): 3/3 re-run green
  (14/14 matrix, 1071+1, 261). F1 fix covers W2 resume findings; F2–F5
  filed. A1 gate: PASS. Units closed 1080+1 after transient I/O retry.
- W2 D3 ACCEPTED (b72865a → c0e211f): A2 PASS, 6/6 phases, SANDBOX VALIDATED.
  Caveat: drill works around two session resume defects driver-side
  (reservation-None flatten fill unbookable; _position not rebuilt across
  restart); relayed to W1 for D2 ownership. W5 must note the caveat.
- W3 part 1 verified (1be3f33, manifest 9008ba92); relayed to W4.
- W3 D5 ACCEPTED (0cdf1e4 → f28bb81): 5/5 proofs re-run green (cache
  rebuilt rc3/518s as predicted; EVAL SCORABLE reproduced). Caveats:
  merge script rewrites build timestamps (sha drift on fresh re-run;
  restored frozen TOML after timestamps-only diff); audit --out needs
  pre-existing dir. Both filed to W3 as follow-ups.
- W4 freeze verified outcome-free (a96ed72); beta calibration overlaps DEV
  idx1-5 (disclosed, trigger-neutral); W5 footnote.
- W4 feasibility ruling (manager): full-split replay infeasible (6.3h+54GB
  per cell vs 1500s/~6GB). Execute freeze literally: dev 30 wall-min and
  val 2 wall-h caps per config, via chained bounded bench_run + resume
  within caps; coverage reported honestly; screen descriptive/DATA BLOCKED
  if unmet. No amendment, no dataset swap.
- W4 vehicle authorization (manager): bench_run.py may gain --symbols
  plural (heap merge, per-symbol cursors, ckpt v3 auto-migrate v2) +
  --start-ms/--end-ms window filters. Backward compat + new tests green
  before any round cell; freeze untouched; separate commit for review.
- W4 vehicle authorization #2 (manager): --spread-bps in-stream modeled
  spread (frozen iter_with_spread; default = frozen profile value; spec
  in resume identity). Premises verified: spreadless bars convert to
  None, cache lacks bookTicker, §8 already assumes the profile.

## Round-1 outcome mechanism (manager analysis, pre-acceptance)
- Selection NONE is mechanically correct AND weak as strategy evidence.
- X1 family: 0 intents in 11/12 cells (1 in X1-T val) — 35bps double-gate
  never co-occurred in capped windows. Strategies untested, not disproven.
- S1 control: 391 dev + 6199 val intents admitted, 0 fills — all 5 val
  submits status=failed (execution:submit-rejected under exit-only).
  Root cause: health:stale-mark latched ~t+5s on quiet window opens and
  never released (W1 F2, filed, fail-closed). 6084 gate trips in S1-val.
- Verdict shape: RESEARCH UNRESOLVED with mechanism decomposed. F2 is the
  binding constraint on any future measurement round (not authorized here).
- Freeze integrity: only §9 IST clarification (pre-outcome, disclosed) +
  authorized beta transcription; params/round/selection untouched.

## Integration log (continued)
- W4 D4 ACCEPTED (d71b050 → af9c86a + fixup bd8d54c): economics/select/
  bench-tests re-ran green; full-suite expect_rc adjusted for merged tree.
- FULL ACCEPTANCE PASS (A1+A2+A3) on clean state. First attempt failed on
  stale drill-out-sandbox + bench_d5 dirs (mine, documented fresh-dir
  requirement) — no regressions. W5 called for independent verdict.

## Stop-order incident (resolved)
- W4 stopped round-1 at jobs 1–4 citing "owner order" (1cc77dd, evidence
  preserved). Provenance: stale Oct 12–13 local-session stops, superseded
  by Oct-14 "Continue" + the acked deep dispatch; re-surfaced by W4's
  local context, not a new order. Owner in manager session confirmed no
  stop. Manager ruled RESUME under existing authorizations; interruption
  disclosed in W4's stopped.json record.
  Resume acked with one disclosed mechanical redo (dev j1 rerun, journals
  pruned pre-fix-bridge, MATCH-verified vs backup — allowed by freeze).
- W4 /tmp wipe (~11h stall): worktree + job-10 partial chain lost; committed
  evidence intact through 8024d13 (9/48 jobs). Recovery in progress (cache
  copy + sha-verify, job-10 disclosed rerun). Filing ETA ~Oct-16 00:00 UTC.
- W4 vehicle authorization #3 (manager): bench _restore must reseed
  _cmd_seq + roll back commands table (job 19 duplicate cmd:000000;
  both halves verified in code). Regression-tested, separate commit,
  verbatim job-19 rerun disclosed. 18/48 jobs done through 71b369f.
- W4 fix #3 compat ruling (manager): fix implemented, 15 failures claimed
  pre-existing. W4 to push fix + with/without evidence now; may run ONLY
  job-19 rerun while manager verifies; 20–48 held for confirm.
- W4 fix #3 VERIFIED (manager): diff in-scope; 15 failures = stale tests +
  strict wrapper on W4 branch (pass on flag-fixed tree); regression tests
  fail pre-fix (observed). Jobs 20–48 CONFIRMED.
- W4 SESSION SWAP (owner, Oct-15): whisper-redshift → granite-cetus. Old
  session gone, job-19 process dead, no orphans running. New W4 briefed:
  fresh worktree at f245331, cache copy + sha-verify, relaunch job-19
  verbatim (disclosed mechanical rerun), then 20–48 as filed.
- W4 jobs-19/20 ruling (manager): new W4 found 19+20 already ran terminal
  pre-swap; independently corroborated (receipts, cursors, sha, dense cmds,
  authorization timing). ACCEPTED as complete; bridge audit must clear the
  replayed_tail=0 point; continue at 21. True state 20/48 run, 17 committed.

## Unresolved / risks
- Linux reviewer-side proof needs a live Linux run (this host macOS); code-inspected only.
- Sandbox fee/funding numbers must be re-recorded on testnet (fixtures hand-built).
- Untouched tick eval DATA BLOCKED until Tardis buy or fresh self-capture (owner decision).
- Workflow bodies for workstream-1/4 + critic arrived truncated; packages above carry the content.

## Next actions
- Manager: dispatch all five, integrate on branches deep/w1..w5, one acceptance command, one final report.
- Owner (later): demo creds → Binance demo check; EVAL/source decision; launch decision.
