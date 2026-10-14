# Crypto bot — integrated release report (the single complete record)

Status: RELEASE CANDIDATE (review f8f6a76 follow-through integrated).
Starting SHA `48029fb` (`release-start-48029fb`); reviewed `f8f6a76`;
this report written against the rev2 integration tip (tag on acceptance).
Runtime: Python 3.14.6, NautilusTrader 1.231.0 (locked `uv.lock`).
Full suite **1318 passed + 1 skipped** (rc=0, 278 s, budgeted).
Production submission: DISABLED. No live orders were placed at any point.

This is the only release report. It records the checkpoints, the exact
operator commands, the economic evidence with per-family verdicts, the
§11 release verdicts, the evidence index and the remaining external
dependencies. Superseded phase handoffs were deleted (all preserved in
git history); raw evidence files stay where they are cited.

## 1. Checkpoint A — one complete offline trading lifecycle: DONE

Contract v1 (`specs/session-adapter-contract.md`, `src/cryptobot/app/engine.py`):
open-only `open_orders()`, versioned `order_status()` incl. terminal/unknown,
bound-sink push, namespaced execution IDs, timestamped `AccountSnapshot`.

- Normal Session + actual adapters (paper + Binance live) against injected
  venue responses. Joint proof 4/4 (`tests/unit/test_release_checkpoint_a.py`):
  fill→ledger→protection→restart with exact REST dialogue asserted, plus live
  exit legs — partial entry, pair replace/resize, partial target exit without
  churn/over-close, final exit + sibling termination, 7-leg reconciled flatness.
- Integrated challenge 15/15
  (`tests/acceptance/test_rel_integrated_challenge.py`), incl. protected-posture
  end-to-end (posture fail-open fixed via `advisory_only`; employment wiring
  via `adapters_for`; latent `log_refresh` crash fixed; push-reentrancy guards
  `_in_ensure`/`_in_flatten`; membership-guarded terminal prune).
- Restart at exposure, crash boundaries, stream-gap halt, foreign-exposure
  untouched, unresolved-restart non-success — all proven.
- Review-f8f6a76 threading repair: socket-only pump + bounded owner
  handoff (`drain_owner` ticked by `run_live`); fills recoverable until
  durable-booking ack; no premature dedup; reason-keyed halts with
  independent heals. Adversarial acceptance 13/13 (default thread +
  real store + owner loop), incl. duplicates, booking failure,
  disconnect/recovery, restart-with-exposure. Linux deadline case:
  unreproduced across 3 envs — fix REFUSED, tripwire test committed.

## 2. Checkpoint B — complete application commands: DONE

All commands proven from the clean locked env (`uv run --locked --no-sync
python -m cryptobot.cli`, repo root). Observed exit codes:

| Command | Result |
|---|---|
| `doctor --config configs/r2.toml` | 0 READY |
| `readiness --config configs/demo.toml` | 3 BLOCKED, no creds (unsigned stand) |
| `preflight --config configs/prod.toml` | 3 BLOCKED, no creds / 0 READY-EXCEPT-SUBMISSION when green (offline-proven) |
| `reconcile --config configs/demo.toml [--expect-flat]` | 3 BLOCKED, no creds / 0 FLAT or EXPOSED |
| `run --mode replay --config <replay> --capture <dir> --run-id <id>` | 0 (b-proof-1: 1.13M events, 601 s, report.json) |
| `run --mode paper --config configs/paper.toml` | live paper (Nautilus sim) |
| `run --mode paper --config configs/demo.toml` | 2 without demo creds; live demo with them (private stream attached) |
| `run --mode prod --config configs/prod.toml` | 3 BLOCKED, no creds / 2 REFUSED at submission switch (full driver verified) |
| `demo_drill.py --dir <d> full` (no keys) | 2 BLOCKED all phases, zero network (was dishonest exit-0 PASS — fixed) |
| `status --storage runs --run-id <id>` | 0 state/counts/heartbeat |
| `stop --storage runs --run-id <id> [--flatten]` | 0 graceful/flatten requested |
| `report --run-dir runs/<id> --out <dir>` | 0 CSVs + report.html |
| `backtest --dataset … --require-round/--round-params/--require-config` | 0 comparison.json (round-gated) |

Private user stream: supervised reader + gap→halt via `set_exit_only`
(halt-until-first-heal), wired into live runs with try/finally close;
stdlib `WsClient` socket factory; 28/28 wiring tests green. Prod route
(§4): same driver (live engine + normal Session, resume-capable), host
pinning, env-only secrets, live equity/positions/fees, §7 risk bounds,
venue-state reconcile — refuses ONLY at the submission switch (code +
owner authorization to enable, never config).

## 3. Checkpoint C — economic report: DONE (no strategy qualifies)

### 3a. H-R2 rejected-candidate counterfactuals — REJECTED (v2, causal)

v1 (60/60 fills before decision) is archived byte-exact under
`outputs/hr2/superseded/` and never citable. v2 rules: arrival = first
book ≥ decision+100 ms; quote ≤1000 ms else unscorable; exits at
executable exit-side touch (trigger ≠ fill); markouts need ≤5 s marks +
book/trade coverage else unscorable; funding settles iff a sourced
boundary falls in the hold, else 0 with provenance.

61/61 accounted. 60 filled, 1 unmarketable. Exits 50 stop / 4 target /
6 time. Exit-net mean **−13.42 bps, 0/60 wins**. Markouts: 30 s −11.95
(0/60 positive), 60 s −14.12 (3/60), 120 s −8.33 (4/60), 300 s −12.76
(0/58); 2/244 legs unscorable on coverage. Funding zero
(no-settlement-boundary-in-hold) on all 60. Portfolio overlay: 6
admitted on decision-ts ordering, mean −15.02 bps. Machine audit
(`hr2_diagnostic.py audit`): CAUSAL, 0 violations. Raw rows:
`outputs/hr2/diagnostics.json` (+ `portfolio.json`,
`extract_manifest.json`). Verdict: no executable edge; the cost floor
correctly rejects. Counterfactual diagnostics, never P&L.

### 3b. Bounded round REL-R1 — REJECTED (advance NONE)

Frozen 2026-10-14T06:10:46Z (`trials/rel-round-01.json`, params,
`configs/rel-r1/`), before any arm outcome was viewed. Six S1/S2 configs
(frozen ROUND-01 params, 120 s horizon) + CASH. 300 s arm rejected at
design time (would break frozen ROUND-01/contract pins) — predeclared.
Chronological dev (cap-30min) / validation (cap-2h), fresh Session per
cell. Mechanical rule: advance at most one config with dev_net > 0 AND
validation_net > 0; else NONE.

| Config | Split | Admitted | Fills | Net | Why |
|---|---|---|---|---|---|
| REL-S1 | dev / val | 0 / 0 | 0 / 0 | 0 / 0 | floor rejected 12 / 4; gates rest |
| REL-S1-V | dev | 0 | 0 | 0 | floor 7; confirm-gate 5 |
| REL-S1-F | dev | 0 | 0 | 0 | floor 9; confirm-gate 3 |
| REL-S2 | dev / val | 0 / 0 | 0 / 0 | 0 / 0 | no setups fired (trend/sequence gates) |
| REL-S2-V | dev | 0 | 0 | 0 | no setups fired |
| REL-S2-F | dev | 0 | 0 | 0 | no setups fired |

Dev 1,129,445 events/cell; validation 2,838,861 events/cell; all rc=0
under gate `sha=f08fa9c507a5ef17`. Variant validation cells not run:
variant gates ⊇ control gates ⇒ admitted ⊆ control's ∅ (stated before
validation; controls would have triggered them). Evidence:
`reports/rel/rel-r1/*.comparison.json` (8 files).

### 3c. Per-family verdicts

S1 **REJECTED** (0 admits; 16 floor rejects; consistent with H-R2).
S2 **REJECTED** (zero setups fired — unevaluable here, fails the rule
either way). S3 **UNQUALIFIED** (H-R2 complete, 0 wins). S4/S5
**INSUFFICIENT** (retained, no evidence this round). Win rate /
expectancy / profit factor / drawdown undefined on zero trades —
reported as such, never imputed. Turnover 0, fees 0, funding 0.

### 3c-ii. Finite investigation R6 — NO QUALIFYING STRATEGY (0 cells)

Signed H-R6 (manager + W4, before any round cells): "No available S1/S3
mechanism variant is economically motivated on development data under
corrected causal execution." Rejection rule: reject only on ≥5 closed
episodes with mean net > 0 on dev AND replicated positive on
validation. Measured reasons: −13.42 bps counterfactual mean, markouts
negative at all horizons, all 4 target exits net-negative, 50/60 stop
exits, median cost gap −21.13 bps. H-R6 STANDS: round closed with no
candidate per §6 — no new configs, no loosened costs, no consumed
holdout. Old registry identities untouched.

### 3d. Qualification screen — DATA BLOCKED (untouched leg)

Screen preserved (≥100 OOS positions / ≥10 days + positive net adverse).
No suitable untouched tick data exists: cap-30min/cap-2h are development
knowledge; 30–90 s captures are shorter than warmup+hold; bench30d has
prior use and is quote-less; no funding channel. Suitability:
`reports/suitability/table.md` (5 captures, 5/5 SCORABLE with warnings).
Unblock needs: ≥10 days tick data nobody used (book/depth + trades +
marks ≥1 s, funding, event/receipt time, seq IDs). Feasibility audit
(`reports/suitability/rev2_feasibility.md`): Binance Vision free data
covers trades/funding/mark-1m/klines (audited, CC BY-NC-SA research
only); only book/depth needs a vendor (Tardis samples audited, $0
spent) or fresh self-capture ($0, recommended). One concrete purchase
choice for the owner if self-capture is declined: Tardis Solo
perpetuals 1-month slice ≈ $700 (exact coverage/TOS to confirm at
purchase; license excludes redistribution/sublicensing).

## 4. Checkpoint D — venue demonstration: BLOCKED (external)

No owner demo credentials. Provided instead: the complete offline-tested
command + secure env instructions. Proven offline (exit 2 BLOCKED, zero
network — credential check precedes any contact):

```
export BINANCE_DEMO_KEY="<owner key>" BINANCE_DEMO_SECRET="<owner secret>"
uv run --locked --no-sync python tools/audit/demo_drill.py --dir /tmp/demo30 --symbol BTCUSDT preflight
uv run --locked --no-sync python tools/audit/demo_drill.py --dir /tmp/demo30 --symbol BTCUSDT full
```

Drill: demo-host pinned, tiny qty under the notional cap, entries stop by
minute 20, IOC entry → protection → reduce-only exit → reconcile, plus
stream-gap and resume-adopt legs. Keys live in env only, never in files.
Demo P&L (when run) is mechanics evidence, not profitability evidence.

## 5. Release verdicts (§11)

| Verdict | Result |
|---|---|
| Software complete | **YES** — lifecycle, CLI, durability, failure behavior verified |
| Demo validated / blocked | **BLOCKED** — needs owner `BINANCE_DEMO_KEY/SECRET` |
| Strategy qualified / rejected / insufficient | **REJECTED / INSUFFICIENT** — nothing qualifies for real capital |
| Production activation eligible / ineligible | **INELIGIBLE** — submission disabled + no qualified strategy + no credentials |

## 6. Evidence index (raw files kept)

- Lifecycle/challenge/joint: `tests/acceptance/test_rel_integrated_challenge.py`,
  `tests/unit/test_release_checkpoint_a.py`, `tests/venue_fixtures.py`
- H-R2: `outputs/hr2/{diagnostics,portfolio,extract_manifest}.json`,
  `tools/hr2_diagnostic.py`
- REL-R1: `trials/rel-round-01.*`, `configs/rel-r1/`,
  `reports/rel/rel-r1/*.comparison.json`
- Suitability: `reports/suitability/{table.md,table.json,audits/,README.md}`
- Worker evidence: `reports/rel/w1/`, `reports/rel/w1-exit/`
- Filings: `coord/outbox/W{1,2,3,5}-REL*.json` (W4 reassigned-unresponsive §8)
- Prior research data (kept, superseded narratives deleted):
  `reports/{corr-evidence,ready-evidence,benchmark-24h-final,eligibility}/`,
  `m1_report.json`, `review-*.json`, `w5*.json`, `runs_index.md`

## 7. Remaining external dependencies (no executable work waiting)

1. Owner demo credentials → run the §4 drill.
2. Fresh untouched ≥10-day tick capture → unlocks REL-R1 untouched
   evaluation + the qualification screen.
3. Owner launch authorization + a qualified strategy → only then the
   explicit submission-switch step (code + authorization, never config).
