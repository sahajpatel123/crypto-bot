# Zone evidence pass — 2026-10-16 (manager session)

Every zone below was verified by execution, not by re-reading claims.
Peer files (ZONES.json, sweep, runbook, F2-SPEC) were read, never edited;
worker/peer code lanes untouched. All artifacts uncommitted, left for review.

| Zone | Status | Executed evidence (this pass) |
|---|---|---|
| Z0 safety | GREEN | `Z0-PROOF-2026-10-16.md`: 43 readiness + 58 paper tests; preflight observe-only; `run --mode prod` BLOCKED on owner creds (exit 3); submission unwired in code |
| Z1 data | RED | `Z1-READINESS-2026-10-16.md`: discovery 525 symbols + dry-run PASS; disk 13GiB vs 186GB need FAIL. Enrollment auditor + 3 DEVELOPMENT-ONLY verdicts (committed `6e9aa04`/`ac44bed`); funding-settlement recorder built + proven live (`tools/pivot_funding_capture.py`, uncommitted) |
| Z2 execution | RED | Paper path 58 tests green; F2 latch fix remains in the peer lane. This session fixed dynamic-discovery book priming (never-synced 3,646→0, 8/8 synced live) + paper crash resume hints + discovery audit records + filed the ~15bps/trade paper-vs-real cost gap and the lossy-host live-feed finding (`PAPER-PROOF-2026-10-16.md`, `FEE-GAP-2026-10-16.md`). Full suite 1,409 green; sole failure proven pre-existing load flake (with/without comparison) |
| Z3 alpha | RED | Gate re-replayed today on frozen X1 economics: NONE / RESEARCH UNRESOLVED, winner null. One-day key data ranks P3 least-bad, none proven (`data/keydata/2026-10-16/`) |
| Z4 risk | YELLOW | `Z4-GAPS-2026-10-16.md`: 16 acceptance tests green; no tiered maintenance-margin model; power-loss durability explicitly unclaimed — both filed for the risk lane |
| Z5 validation | RED | `Z5-CHECK-2026-10-16.md`: reporting 34/34 green; frozen release verdict REJECTED/INSUFFICIENT, nothing qualifies for real capital |
| Z6 live-ops | RED (recorded) | `drill-z6-2026-10-16/`: fresh offline drill 6/6 PASS, SANDBOX VALIDATED; BINANCE DEMO VALIDATION PENDING (owner creds, not requested) |

## What would flip each RED

- Z1: owner provisions ~256GB capture storage (or Tardis decision) → capture → enroll.
- Z2: peer F2/F3 fixes land → re-run latch probe + lifecycle matrix.
- Z3: enrolled data + a PIVOT-01 QUALIFIED verdict on fresh splits.
- Z5/Z6: Z3 qualification + demo validation with owner credentials.

On the 2–3%/day ask: `configs/prod.toml` already carries a 2%
daily-target risk knob for the day a strategy earns it. No measured
family is above zero net of costs today; the zones above are the
machine that would prove such a strategy if one ever appears — they
cannot conjure its returns.
