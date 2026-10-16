# Deep-research final report (NEAR-FINAL — W5 verdict pending)

Integrated SHA: `7d48e5e` (`deep/integration`, all five worker branches merged).
Base: `3aac4c7` (rev2-rc-1). Board + rulings: `coord/BOARD-deep.md`.

Single acceptance command (manager-owned; re-runs every worker proof):
`rm -rf drill-out-sandbox bench_d5 && PYTHONPATH=src .venv/bin/python
tools/deep_accept.py --suite full --report-out R.json`
(exits 0 PASS / 2 BLOCKED / 1 FAIL; observed output only; fresh dirs required.)
Observed result: OVERALL PASS — A1 PASS (D1 6/6, D2 3/3), A2 PASS (2/2),
A3 PASS (D5 5/5, D4 5/5).

Budget: every job ≤1500s via tools/run_budget.py (strict preflight refuses
unsupported hosts with exit 125; macOS/dev runs pass --allow-best-effort
explicitly). Production submission DISABLED throughout. No credentials used.

## A1 — Deployment + execution correctness: PASS
- D1 enforce-or-refuse (W1 cloud-vega, cd42146 → 04c0bee): strict preflight
  before checkpoint/spawn; exit 125 + REFUSED_UNSUPPORTED + stderr REFUSED,
  child never spawns (marker-proven); best-effort reproduces legacy
  rc/report shape bit-for-bit. 6/6 re-ran green (2× refuse, passthrough,
  14 file tests, 1080+1 units, 261 rest).
- D2 lifecycle matrix (W1, 6bc5af6 → 47a8c8c + flag fixup 9be4fb1): 14/14
  rows green on the real run_live loop. 3/3 re-ran green.
- Session fixes owned: F1 ambiguous-submit attribution (journal seam +
  durable fallback); position-shell persist/restore; orphan-close fallback —
  covering both W2 resume findings. Filed, not fixed: F2 stale-mark
  one-way latch (fail-closed — see round mechanism below); F3 exit-tick
  fills strand until resume adopts; F4 no operator clear for unknowns;
  F5 halts gate entries only (no finding).

## A2 — Sandbox demonstration: PASS
- D3 (W2 white-aldebaran, b72865a → c0e211f): one offline seed-pinned
  command, 6/6 phases PASS; report records SANDBOX VALIDATED vs BINANCE
  DEMO VALIDATION PENDING. 11/11 audit tests green. Verified offline with
  no secrets; the credentialed demo command is prepared only, never run.
- Wart (noted, out of scope): re-running into an occupied --dir crashes
  instead of refusing loudly; fresh dirs are the contract.

## A3 — Economic strategy on real data
- D5 data (W3 cool-amalthea, 0cdf1e4 → f28bb81): 5/5 re-ran green.
  Manifest 9008ba92 (Oct funding merged, 22 gaps resolved); splits frozen
  + verified (480 cells; DEV idx1-15, VAL idx16-22 scored-once, TEST
  idx23-30 BURNED); one EVAL minted (eval-deep1, $0 self-capture,
  SCORABLE reproduced); bench bounded (124) + resume (COMPLETE) proven.
  Caveats filed to W3: merge rewrites build timestamps (sha drift on
  fresh re-run); audit --out needs a pre-existing dir.
- D4 X1 round-1 (W4 whisper-redshift → granite-cetus, d71b050 → af9c86a +
  expect_rc fixup bd8d54c): 48/48 filed jobs ran to cap, 24/24 cells
  bridged rc=0, realistic + adverse (2x spread) costs. Freeze verified:
  only the pre-outcome §9 IST clarification + authorized beta (1.254028)
  transcription; params/round/selection untouched. Three vehicle
  extensions + bridge reviewed (narrow, tested, backward compatible).
  Two session-swap/evidence incidents resolved with records (stopped.json
  false alarm; jobs-19/20 accepted complete after corroboration).
- OUTCOME: selection NONE — RESEARCH UNRESOLVED. Fills 0 in all 24 cells.
  Mechanism (manager pre-acceptance analysis, W5 to confirm): X1 admitted
  0 intents in 11/12 cells (1 in X1-T val) — the 35bps double-gate never
  co-occurred in capped windows, so X1 is UNTESTED, not disproven. S1
  admitted 391 dev + 6199 val intents but all submits failed under the
  exit-only latch: health:stale-mark trips ~5s in on quiet window opens
  and never releases (F2; 6084 gate trips in S1-val; 5/5 submits
  submit-rejected). The round measured the latch, not the strategies.
  F2 is the binding constraint on any future measurement round.

## Independent verification (W5): [PENDING — verdict filing]

## Production eligibility: [PENDING — decided after W5 verdict]
Standing facts: mechanics gates (A1/A2) never establish profitability;
no strategy qualified (NONE); F2 blocks any live submission path from
measuring fills at all. The decision will be explicit: NOT ELIGIBLE
unless the verdict changes the facts above.

## Evidence index
- Filings: coord/outbox/DEEP-*.done.json (+ DEEP-W5-VERDICT.json on arrival)
- Worker evidence: coord/evidence/deep-w1-d1/, deep-w1-d2/,
  drill-out-sandbox/, bench_d5/, outputs/x1/, datasets/splits_deep.toml
- Integration SHAs: D1 04c0bee, D3 c0e211f, D5 f28bb81, D2 47a8c8c+9be4fb1,
  D4 af9c86a+bd8d54c; acceptance PASS at 7d48e5e
