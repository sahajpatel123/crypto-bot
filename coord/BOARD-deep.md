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
- W2 D3 ACCEPTED (b72865a → c0e211f): A2 PASS, 6/6 phases, SANDBOX VALIDATED.
  Caveat: drill works around two session resume defects driver-side
  (reservation-None flatten fill unbookable; _position not rebuilt across
  restart); relayed to W1 for D2 ownership. W5 must note the caveat.
- W3 part 1 verified (1be3f33, manifest 9008ba92); relayed to W4.
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

## Unresolved / risks
- Linux reviewer-side proof needs a live Linux run (this host macOS); code-inspected only.
- Sandbox fee/funding numbers must be re-recorded on testnet (fixtures hand-built).
- Untouched tick eval DATA BLOCKED until Tardis buy or fresh self-capture (owner decision).
- Workflow bodies for workstream-1/4 + critic arrived truncated; packages above carry the content.

## Next actions
- Manager: dispatch all five, integrate on branches deep/w1..w5, one acceptance command, one final report.
- Owner (later): demo creds → Binance demo check; EVAL/source decision; launch decision.
