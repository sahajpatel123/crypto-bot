# W5 CORR-VERIFY — interim evidence (base tag + nested deadline)

Worker 5 (`crystal-parallax`), branch `worker5/corr-verify`.
Base: tag `review-cdcd10c-baseline` = `cdcd10cbb40c3983b78b73b3d924a00aeb62a8c5`.
Battery commit: `b517f49` (pushed to `origin/worker5/corr-verify`).
Machine: Darwin arm64 (MacBook Air), project venv python 3.14.6.
Raw base-probe JSON: `reports/w5corr-base-probes.json` (3.0s runtime).

## 1. Review probes on base tag — all four findings REPRODUCED

| # | Finding | Observed on base |
|---|---|---|
| 1 | Marketable IOC uses future liquidity | No fill at 200 ms; quote 10 s later fills BUY at 90. `defect_observed: true` |
| 2 | Checkpoint omits trading context | Before: 135 bar slots, warmed, ready at 131 s. After restore: 0 feeds, `warmed=False`. Orphan ledger 0.5 qty called flat (`true`); changed-cooldown resume allowed (`true`) |
| 3 | Flat detection wrong | After round-trip, `open_orders()` returns `["filled","filled"]`, `_is_flat` false; orphan 0.5 qty called flat |
| 4 | Freshness not scoped to candidate | Fresh-BTC/stale-ETH gate passes (`None`); stale-BTC/fresh-ETH fails (`gate:stale-quote`) |
| 5 | Nested deadline unreliable | Plain case did NOT reproduce here (1.219 s, rc 124, no orphans). Two escape mechanisms proven below reproduce the exact 8.07 s signature |

Also confirmed: runtime arm list is 11 distinct IDs including S2-V/S2-F
(`arms=all` vs ROUND-01 exclusion disagrees, as the handoff notes);
clean synthetic warmup reads ready at 131 s, not 65 minutes.

Repro: `cd <base> && PYTHONPATH=src <venv>/bin/python
/Users/sahajpatel/Code/cryto-bot/Crypto_Bot_cdcd10c_Review_Probes.py`
(Note: system `python`/`python3` lack nautilus; the project `.venv` is required.
Assignment scripts live untracked in the main workspace, not in the tag.)

## 2. Nested deadline — battery 4 pass / 3 fail (all failures are holes)

New gate: `tests/runtime/test_nested_deadline_adversarial.py` (seconds-scale,
unique markers, teardown reaps only cmdline-verified own PIDs; every run ends
with zero strays confirmed via `pgrep`).

PASS (deadline enforced, Mac):
- Handoff's exact nested case (outer 1 s / inner 30 s / 8 s sleeper), 2
  iterations: caller returns ~1.2 s, sleeper never completes, report matches
  wall. The plain-case 8.068 s event did NOT reproduce on this Mac (12+
  consecutive clean runs incl. the repo's own nested test).
- SIGTERM-ignoring child: SIGKILL escalation kills it inside budget+grace.
- Rapid fork during grace (~40 grandchildren): zero survivors.
- Shutdown race (child exits exactly at deadline), 6 iterations: clean
  CHILD_EXIT or INCOMPLETE_BUDGET every time, valid report, no hang.

FAIL (demonstrated enforcement holes, Mac):
1. `test_daemon_reparent_escape` — a double-fork + setsid grandchild reparents
   to init (observed live: pid 85708, **ppid 1**, own pgid) BEFORE the deadline
   and is invisible to both the ppid walk and killpg. It survives; the wrapper
   exits 124 reporting INCOMPLETE with no hint of the escape.
2. `test_inherited_pipe_blocks_caller_on_escape` — the escaped daemon holds the
   capturing caller's stdout pipe: **caller wall 8.073 s vs report 2.166 s**.
   This reproduces the handoff's 8.068 s / 1.116 s signature to milliseconds and
   is the mechanism "wrapper exit/report does not prove descendants stopped".
3. `test_enumeration_failure_must_not_fail_open` — with `ps` unavailable,
   `_descendants()` returns the empty set and the kill degrades to
   group-kill-only; but every wrapper child starts in its OWN session, so
   grandchildren always escape that path. Measured: **caller wall 8.104 s vs
   report 1.124 s** (handoff: 8.068 s / 1.116 s). Any transient `ps`
   failure (fork pressure under parallel-agent load is the leading candidate
   for the handoff's plain-case event) fails OPEN and silently.

## 3. Deployment-OS analysis (static; Linux runtime BLOCKED)

No deployment OS is documented in-repo (no Dockerfile/CI/host docs) — the
presumed target is Linux. A Linux runtime check was attempted (colima VM) but
the image download ran ~5%/100 s (~30 min) and was killed; no VM/container
runtime is available on this machine. By construction, both holes transfer to
Linux unchanged: orphan reparenting (to subreaper/init), setsid semantics,
killpg scope, and the fail-open `except → return set()` are identical; only
the init pid (1 vs launchd) differs cosmetically.

Repair direction (for the owner of `tools/run_budget.py`): on Linux,
`PR_SET_CHILD_SUBREAPER` makes orphans reparent to the wrapper so the existing
walk kills them — the only airtight fix. macOS has no subreaper API: best
effort is a birth registry (frequent scans during life) plus fail-closed
reporting (`enforcement: UNVERIFIED` when enumeration fails or known survivors
remain) instead of silent INCOMPLETE. W5 can implement this on request; the
battery above is the acceptance gate either way.

## 4. Research allowlist + cost reconciliation — VALIDATED on base

- `tests/net_guard.py` (deny-by-default, loopback-only): existing
  `test_net_guard.py` 6 passed / 1 skipped (skip is the public-data opt-in
  profile). Adversarial spot-checks: external connect/urlopen raise
  `ExternalNetworkBlocked`; loopback bind works; hex/int/bracketed/empty
  host spellings all fail closed. One observation (low, test-only): names
  matching `*.localhost` pass the guard and hit the REAL resolver
  (confirmed: nonexistent `*.localhost` attempted resolution, resolved to
  loopback here) — a hostile resolver could turn that into a bypass. The
  guard cannot prove loopback for names; literals only would close it.
- `tools/audit/reconcile.py`: synthetic RECONCILED / tampered-MISMATCH /
  zero-fill-VACUOUS fixtures all verdict correctly (exit 1 iff MISMATCH);
  it also caught a deliberately inconsistent fixture I wrote (nonzero net
  with zero fills). `tests/audit/test_cost_contract.py`: 3 passed.

## 5. Repair (manager-authorized, commit `0b14c32`)

`tools/run_budget.py` repaired on this branch; battery updated to the new
contract and extended to 10 tests. Changes:

- Linux child subreaper (best-effort ctypes, no hard dependency): orphans
  reparent to the wrapper, closing the daemon hole where the OS allows.
- Birth registry: descendants scanned every 0.25 s during life; the kill
  set is registry ∪ fresh snapshot ∪ {child} — birth-registry identity
  only, unrelated PIDs never signaled.
- Wrapper-owned stdout/stderr relay (portable threads): the child tree
  never inherits the caller's pipes, so no descendant can block a
  capturing caller past wrapper exit (bounded 2 s drain). Child stdio is
  now always pipes, never a tty (documented behavior change).
- Fail-closed reporting: `ps` nonzero/empty output counts as enumeration
  failure (this hole was caught by the new flaky-ps test during repair
  development); post-kill verification sweep; report carries
  `enforcement: verified|UNVERIFIED` + detail + `subreaper` + a
  no-subreaper honesty note on macOS. Exit stays 124.

Results: battery 10/10, repo `test_run_budget.py` 5/5, full
`tests/unit+tests/audit+tests/runtime` 858 passed / 1 skipped (4m25s, all
under the frozen base outer wrapper). The 4 key regression tests fail on
the pre-fix wrapper (verified via stash) and pass post-fix. Review probes
re-run with the repaired wrapper: identical 4 findings, nested plain case
1.166 s with `enforcement: verified`. Every run ends with zero strays.

Platform truth table after repair: Linux closes all three holes (daemon
kill via subreaper — code path present, runtime proof needs a Linux host);
macOS closes pipe-block + ps-failure and degrades honestly on daemon kill
(report says so; caller never blocks).

## 6. Pending (blocked on others)

- W2 CORR diff: no `worker2/*corr*` branch on origin yet → review OWED.
- Adversarial end-to-end on the integrated revision: blocked until the
  final integrated SHA (W1+W2 still unmerged at this writing).
- `coord/outbox/W5-CORR.json`: filed; covers base probes, nested repair,
  allowlist/reconciler. W1+W3 reviews banked below; W2+e2e ride a second
  addendum.

## 7. Addendum — substantive W1 + W3 reviews (APPROVE both)

Reviewed in scratch worktrees at branch tips (read-only; no commits
there). All pytest runs use `PYTHONPATH=src` pinned to the review
worktree: the shared venv carries an editable install of the main
checkout, and a bare `pytest` silently imports the WRONG `cryptobot`
(this initially produced 13 false failures on W1's branch; re-run with
the pin: 103/103). Every job ran under the repaired `run_budget`.

### W1 `origin/worker1/corr-exec` (fix `5987619`) — APPROVE

- Official probe IOC leg: `defect_observed=false`, fill @101.0 (arrival
  ask, stamped 10s−1ns via pre-flush), nothing at 200ms. Round-trip
  `open_orders`/`_is_flat` unchanged (correctly W2 territory).
- Full suite: 1030 passed, 1 skipped in 163.8s — claim verified exactly.
  Targeted (IOC + 3 touched files + IOC adversarial): 103 passed.
- No test removed: 12→19 in `test_ioc_arrival.py`; the two superseded
  tests were replaced by strictly stronger ones (first-opportunity-only,
  same-ts-cancel-rejected); the genuine-race test is byte-identical;
  the 6 legacy price pins moved to due-time prices with rationale
  comments, assertion shapes intact (approx, fee>0, exec-id,
  exactly-once). Margin/fee deltas rechecked for direction.
- W5 adversarial extras: never-quoted-symbol edge (their disclosed gap)
  probed benign — LIMIT arrival-cancels, MARKET venue-rejects
  (`no market`), zero fills, no cross-symbol leakage; recommend a
  committed test. Exec-vs-ack separation holds under 5s delivery delay
  (fill still @101). Sweep-send path appears unreachable on pinned
  nautilus (venue always terminalizes evaluated IOCs; stat stays 0) —
  harmless defense-in-depth, but untested backstop is recorded.
- Scope clean: only `paper_engine.py` in `src/`; sparse-data model
  declared + tested; accept+1-tick removed.

### W3 `origin/worker3/corr-data` (`b3b2161`, merged as `8f5710c`) — APPROVE

- Full suite: 1043 passed, 1 skipped in 160.3s. Targeted (freshness +
  audit + runtime): 41 passed.
- Candidate scoping verified by matrix: all four fresh/stale BTC×ETH
  combinations gate each symbol on its own observations only (base
  first-feed-wins defect gone); at-bound passes, bound+1ms fails;
  unknown symbol fails closed; a stale event through real ingestion
  keeps exchange-time age → stale (no forward-fill relabeling).
- Exchange-mark leg: in-suite tests cover both orderings
  (fresh-mark+stale-quote and fresh-quote+stale-mark both reject) plus
  mark-without-ts, mark-not-required, unconfigured bound, malformed
  timestamps. Signature migration complete (1 production caller passes
  the candidate instrument; health/books keep valuation age);
  `test_runtime_30min.py` diff is signature-only with identical verdicts.
- `tools/audit_dataset.py`: suite-tested and proven on the observed
  cap-30min capture (verdict SCORABLE with honest warmup/depth
  warnings). `tools/export_warmup.py`: FUNCTIONAL on the observed
  capture (rc 0, timestamped milestones, honestly empty unreached
  milestones) but has ZERO in-suite tests — observation, recommend one.
  No W3 outbox was filed (reviewed from the diff directly).
- Scope clean: only `session.py` in `src/`.

## Repro commands (all ≤25 min jobs; battery ~65 s)

- Base probes: `PYTHONPATH=src .venv/bin/python
  /Users/sahajpatel/Code/cryto-bot/Crypto_Bot_cdcd10c_Review_Probes.py`
- Battery: `.venv/bin/python -m pytest
  tests/runtime/test_nested_deadline_adversarial.py -q`
- Repo budget tests: `.venv/bin/python -m pytest tests/unit/test_run_budget.py -q`
- Stray check after any run: `pgrep -fl w5corr-deadline-battery` (expect none)
