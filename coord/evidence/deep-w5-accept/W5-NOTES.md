# DEEP-W5 independent verification notes (crystal-parallax)

Method: every worker `.done.json` command re-run on the integrated tree via the
harness's own `_check_filing` (exact verdict code), one filing per
`run_budget` job (≤1500s; `--allow-best-effort` on macOS since strict
refuses to spawn by design). Observed output only; no worker command
modified. Env: `PYTHONPATH=src`, locked main-checkout venv via `.venv`
symlink (untracked, uncommitted), machine-local 506-file bulk via
`datasets/cache` symlink (untracked; integrity proven by freeze
recompute, not by trust).

Tested SHAs: A1 (D1+D2) on 7d48e5e-content (merge 96755cf);
A2+A3 on 98616ff-content (merge 8faa31d, adds W2 occupied-dir guard +
PIVOT-01 scope, which is out of verdict scope — no filing, post-call).

## Per-filing observed (see *.json in this dir)

- D1 PASS 6/6: refuse×2 rc125, passthrough rc0, files 14 passed (15.76s),
  units 1111 passed +1 skipped (802.58s), rest 272 passed (97.10s).
- D2 TIMEOUT-FAIL (harness rules): matrix 14/14 (184.06s) rc0, rest 272
  (104.63s) rc0, units TIMEOUT at 900s. Isolation: same suite green
  standalone, 1111 passed +1 skipped in 1082.54s (d2u-iso-report.json).
  Same suite also green inside D1 (802s). Environmental, not product.
- D3 PASS 2/2 on new tip: drill 6/6 phases PASS, SANDBOX VALIDATED vs
  BINANCE DEMO VALIDATION PENDING (a2-drill-report.json); 11/11 audit
  tests (1.85s).
- D5 PASS 5/5: merge no-op rc0, freeze 480-cell recompute rc0, EVAL
  SCORABLE rc0 (4 filed warns), benchA rc124 TRUNCATED, benchB rc0
  COMPLETE (repA/repB.json). Manifest byte-identical before/after.
- D4 (harness run crashed, see bug): economics×2 rc0 with values
  byte-identical to committed (input-order-only diff from CLI arg
  order; restored after compare), select rc0 byte-identical NONE,
  bench tests 14/14 (128.05s, d4s-wrapper.json), full suite TIMEOUT
  at 900s under harness. Isolation: full suite green standalone,
  1399 passed +1 skipped in 1102.63s, ZERO failures (d4f-wrapper.json)
  — confirms the 15 stale failures exist only on the W4 branch.

## Harness bug (filed to manager)

`tools/deep_accept.py` @832382a cannot report a timeout: the
`TimeoutExpired` path yields bytes tails (partial output never
decoded), crashing with `TypeError` — twice at record serialization,
once inside `_rerun` itself (`can't concat str to bytes`), killing the
gate run. Reproduced 3× (D2 twice, D4 once). Any timeout anywhere
breaks the whole report. Fix class: decode tails (errors=replace) at
tail build. W5 did not modify the harness; the driver coerces only at
persistence, verdict math untouched.

## Negative probes (all /tmp/deep-w5-neg + /tmp/deep-w5-blocked)

1. Refusal without spawn: distinct sentinel child, strict run → rc125,
   REFUSED on stderr with full reason (linux=False subreaper=False
   table_scan_ok=True), sentinel absent, both records
   REFUSED_UNSUPPORTED with command recorded. PASS.
2. Verdict logic unit probe: all-pass→PASS, one-blocked→BLOCKED,
   one-omitted→BLOCKED (phase named), fail+blocked→FAIL, stamp only
   on PASS. PASS.
3. End-to-end BLOCKED drill (30s deadline budget): drill/entry-cutoff
   BLOCKED, overall rc2, report BLOCKED, NOT VALIDATED stamp, no
   PASS anywhere (neg-blocked-drill-report.json). PASS.
4. Occupied-dir guard (new tip): rc2 + loud BLOCKED + evidence
   record, no crash. PASS.
5. Registry-role invariance: selection NONE holds with frozen
   registry AND with all six configs forced candidate (nets all
   0.0). Post-outcome registry creation immaterial HERE; hygiene
   deviation stands (must pre-freeze in round 2; "first outcome
   contact" claim overprecise — jobs 1-4 outcomes seen Oct 14).
6. TEST burn: zero burned IST dates (10-04..10-11) in any round-1
   cell window; all windows within idx1-22; 09-11 label is UTC-day
   file span, scored window exactly DEV. Property HOLDS. No
   mechanical tripwire exists (`scoring_allowed` written, never
   consumed) — recommend bench_run refuse burned slices.
7. Synthetic-profit exclusion: S1-val economics cell traces field-
   for-field to its rundir report; 0 fills ↔ 0.0 nets; mechanism
   counts confirmed from committed checkpoint (6084 stale-mark
   trips, 5 submit-rejected, halted). No synthetic profit anywhere;
   only numbers are 0.0 nets → NONE.

## Report-accuracy deltas (near-final @7ae44f4)

- Counts stale: units observed 1111+1 (report 1080+1, filing 1066);
  rest observed 272 (filing 261); full observed 1399+1 (filing 1343).
  Gates pass on rc either way; prose must carry observed numbers.
- D4 freeze claim omits the post-outcome registry creation (tool
  frozen ✓, registry input post-hoc; immaterial here, must disclose).
- "~5s latch" timing is analysis gloss; trip counts confirmed.
- One acceptance command needs the fresh-dir prefix (already in
  report) AND a quiet host or raised per-command timeout (see D2/D4).
