# Deep-research final report (DRAFT — round-1 outcome + verdict pending)

Single acceptance command (manager-owned, re-runs worker proofs):
`PYTHONPATH=src .venv/bin/python tools/deep_accept.py --suite full --report-out R.json`
(exits 0 PASS / 2 BLOCKED / 1 FAIL; every cited command re-executed, observed output only.)

Budget: every job ≤1500s via tools/run_budget.py (strict preflight; macOS/dev
hosts pass --allow-best-effort explicitly). Production submission DISABLED throughout.

## A1 — Deployment + execution correctness: PASS (integrated, re-run green)
- D1 enforce-or-refuse (W1 cloud-vega, cd42146 → 04c0bee): strict preflight
  before checkpoint/spawn; unsupported host → REFUSED_UNSUPPORTED + stderr
  REFUSED + exit 125, child never spawns (marker-proven). --allow-best-effort
  reproduces legacy rc/report shape bit-for-bit. 6/6 filing commands re-ran
  green (refuse ×2, passthrough, 14 file tests, 1080+1 units, 261 rest).
- D2 lifecycle matrix (W1, 6bc5af6 → 47a8c8c + fixup 9be4fb1): 14/14 rows
  green on the real run_live loop (happy, dupe, delayed-ack, ambiguous,
  disconnect, restart-with-exposure, 06b, booking-fail, queue, stale, halt,
  stop, flatten, foreign). 3/3 filing commands re-ran green.
- Session fixes owned: F1 ambiguous-submit attribution (journal seam +
  durable fallback, pinned by row 4); position-shell persist/restore;
  orphan-close nonzero-booked fallback — covers both W2 resume findings.
- Filed, not fixed: F2 stale-mark one-way latch (fail-closed); F3 exit-tick
  fills strand until resume adopts (venue safe, ledger lags); F4 no operator
  clear for unknown commands; F5 halts gate entries only (no finding).
  Docs examples updated for the strict flag (641609a).

## A2 — Sandbox demonstration: PASS (integrated, re-run green)
- D3 (W2 white-aldebaran, b72865a → c0e211f): tools/audit/sandbox_drill.py +
  src/cryptobot/adapters/sandbox_venue.py. One offline seed-pinned command,
  6/6 phases PASS, report records SANDBOX VALIDATED vs BINANCE DEMO
  VALIDATION PENDING. 11/11 audit tests green. Verified offline (no network,
  no creds); demo command + credential config prepared only, never executed.
- Caveat: drill works around the two session resume defects driver-side
  (now fixed session-side by W1 D2 — drill predates the fix; re-run still
  green after the merge).

## A3 — Economic strategy on real data (PENDING round-1)
- D5 data (W3 cool-amalthea, 0cdf1e4 → f28bb81): 5/5 proofs re-run green.
  Manifest 9008ba92 (Oct funding merged, 22 gaps resolved); splits frozen +
  verified (480 cells; DEV idx1-15, VAL idx16-22 scored-once, TEST idx23-30
  BURNED); exactly one EVAL minted (eval-deep1, $0 self-capture, SCORABLE
  reproduced); bench bounded (124 TRUNCATED) + resume (COMPLETE) proven.
  Caveats: merge script rewrites build timestamps (sha drift on fresh
  re-run; frozen TOML restored after timestamps-only diff); audit --out
  needs a pre-existing dir. Both filed to W3 as follow-ups.
- D4 X1 round-1 (W4 whisper-redshift): freeze verified outcome-free
  (a96ed72; params match dispatch; honest minimum-trigger economics
  pre-registered; beta 1.254028 via frozen §9 on DEV idx1–5 — overlaps DEV
  scoring slice, disclosed, trigger-neutral). Feasibility ruling: frozen
  30min/2h per-config wall caps executed via chained bounded resume (no
  amendment, no dataset swap). Vehicle authorizations #1 (multi-symbol +
  window filters) and #2 (--spread-bps modeled spread) — premises verified
  in code, backward compat + tests-gated, freeze untouched. Stop-order
  incident resolved as stale-context false alarm (record in stopped.json);
  round resumed with one disclosed mechanical redo (dev j1, MATCH-verified).
- OUTCOME: [pending — selection by frozen tools/x1_select.py; ≤1 advance
  on dev>0 & val>0 else NONE; economics reconciled to ledger]

## Production eligibility: [pending W5 verdict + round outcome]
Mechanics gates (A1/A2) do not establish profitability. Awaiting: X1-R1
filing, full acceptance re-run, W5 independent verdict.

## Evidence index
- Board + rulings: coord/BOARD-deep.md (this branch)
- Filings: coord/outbox/DEEP-*.done.json (+ W5 verdict on arrival)
- Worker evidence: coord/evidence/deep-w1-d1/, deep-w1-d2/, drill-out-sandbox/,
  outputs/x1/ (on W4 branch until integrated)
- Integration SHAs: D1 04c0bee, D3 c0e211f, D5 f28bb81, D2 47a8c8c+9be4fb1
