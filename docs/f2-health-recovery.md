# F2 fix: level-driven Session health halt (release-on-clear)

Status: implemented on branch `fix/f2-health-recovery` (base `98616ff`,
`deep/integration`). Authored by the external contributor session; merge
and any DECISIONS/board entry remain with the manager per D-003.

## Finding (as observed, not quoted)

Round X1-R1's S1 control cell (validation) ended `run_state: halted`
while the risk state itself was healthy (`emergency_latched: false`,
`operating_stop_days: {}`) — i.e. the halt came from the health gate,
not a policy stop. Observed evidence, cell checkpoint
`outputs/x1/ckpts/realistic/X1-R1-S1_validation/bench_checkpoint.json`:

- `counts.reject_counts["execution:submit-rejected:PermissionError"] = 5`
  — the cell's only submits were refused by the engine's exit-only path;
- `counts.reject_counts["gate:stale-mark"] = 6084` — per-intent
  admission rejections while the mark was stale (correct fail-closed);
- `store_cursors.risk_transitions = 8244298` and
  `counts.journal_bytes ≈ 1.06 GB` — the same stuck latch re-wrote run
  state on market events (~8.2M duplicate transitions);
- consequence: 0 fills in all 24 round cells; the round measured the
  latch, not the strategies (see `reports/deep/FINAL-REPORT-draft.md`,
  A3).

## Root cause

`Session._ingest` evaluated `policy.check_health(snapshot)` per market
event. A not-ok verdict (`health:stale-mark` from the 1 s mark bound on
quiet-window snapshots) ran `_halt_entries(...)` + `_set_state("halted",
...)` on every event, and Session-owned exit-only reasons had no level
release: only `_release_all_exit_only` at day roll / emergency recovery
cleared them. A capped benchmark cell inside one accounting day latched
forever; every later submit raised `PermissionError` in the engine.

## Fix (semantics)

`_apply_health_gate(health)` now applies each snapshot's verdict
level-wise:

- not-ok → latch the CURRENT reason string once (idempotent: repeat
  verdicts write nothing);
- ok → release exactly the strings this gate latched, mirrored out of
  the engine's reason-keyed exit-only;
- run state flips back to `ready` only when this gate released something
  AND nothing else blocks entries (other exit-only reasons, booking
  blocks, pending flattens);
- fail-closed direction unchanged: while the condition holds entries
  stay blocked; a recovered feed re-opens them on the first fresh
  snapshot. `_release_all_exit_only` also resets the gate's tracking so
  a still-failing condition re-latches.

Call sites: `_health_tick()` (used by `_ingest`, the event path).
`_supervise` (timer path, `account=None`) is unchanged: it never sees
health reasons and never releases; absence of a snapshot never releases.

## Parallel work (disclosure)

A second, independent F2 fix exists in this repo: branch
`deep/f2-mark-health` (worktree `/private/tmp/cryto-bot-f2-mark`, author
grok-f2, filing `coord/outbox/F2-MARK-HEALTH.json`; uncommitted WIP at
the time of writing). It releases only the two mark-age reasons and
re-asserts the paper engine's one-bool halt when another reason
survives. This branch releases every reason the health gate itself
latched (mark age, day-open reconciliation, nonfinite account), fixes
the repeated run-state writes that produced ~8.2M transitions / ~1 GB
journal in X1-R1, and adopts the paper one-bool re-assert. Both fixes
are fail-closed while a stale snapshot persists and never release
without a snapshot. Consolidation/selection is the manager's call per
D-003; both are based on `98616ff` and touch `session.py`.

## Tests

`tests/unit/test_session_health_recovery.py` (6 tests): latch-once +
release-on-clear with fail-closed entry refusal, independence from other
latches (funding mismatch survives; run stays halted), release-all
re-latch (never silently open), reason-change release
(`stale-mark` → `mark-age-unknown`), paper one-bool survivor re-assert,
and the no-snapshot-never-releases supervision property.

## Not in scope (still open)

- F3 (exit-tick fills strand until resume adopts), F4 (no operator
  clear for unknowns), F5 (no finding) — untouched.
- The benchmark data characteristics (quiet-window mark sparsity on the
  frozen vehicle) are a data/vehicle question and deliberately
  untouched (round freeze).
- W5 independent verdict remains pending; this fix changes no strategy,
  cost, split, or selection semantics.

## Reproduce

```sh
WT=<this worktree>
cd "$WT"
PYTHONPATH=src /path/to/repo/.venv/bin/python -m pytest -q \
  tests/unit/test_session_health_recovery.py
```
