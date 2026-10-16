# PIVOT-01 — honest status (manager-owned)

Status: **PREREGISTERED — DATA BLOCKED.** No qualifying dataset enrolled.
No pivot backtest has run. Nothing here is profitability evidence.

## Why this exists

Three independent rounds rejected or failed to resolve the 120s taker-scalp
thesis on cost physics alone:

- CORR Phase B: 10/10 cells 0 fills, 62/62 cost-killed.
- REL-R1: advance NONE (S1/S2 REJECTED).
- X1-R1: 24/24 cells 0 fills, selection NONE — X1 untested (0 intents),
  S1 control blocked by the F2 stale-mark latch (0 fills on 6590 intents).
- H-R2 counterfactuals: 0/60 wins, mean −13.42bps.

Continuing to tune taker-scalp thresholds would be data-snooping, not
research. PIVOT-01 preregisters **new mechanisms with different cost
physics** before any outcomes exist.

## What changes (families)

| Family | Mechanism | Min target vs 26bps hurdle |
|---|---|---|
| P1 maker/post-only | Earn spread/rebate, toxicity filter | 15bps (maker math, not taker) |
| P2 funding/carry | 8h funding + basis, ~1/day turnover | 40bps |
| P3 swing 4h+ | Costs <10% of ATR, wide stops | 80bps |

Full preregistration: `coord/pivot/PIVOT-01.json` (frozen 2026-10-16).
S1–S5/X1 configs are **not re-entered**.

## What does NOT change

- Cost contract `cost-contract-v1` (26bps taker reference), realistic +
  adverse (2x) economics, Nautilus paper path.
- Screens: ≥100 VAL closed positions spanning ≥10d, dev>0 & val>0
  realistic AND val>0 adverse, at most one advances, else NONE.
- Live submission DISABLED. No credentials. TEST scored once, only on
  qualification.

## Track A artifacts (this slice)

- Preregistration: `coord/pivot/PIVOT-01.json`
- Z1 capture runbook (owner-executed): `coord/pivot/CAPTURE-RUNBOOK.md`
- Z2 F2 latch fix spec (W1 lane, spec only): `coord/pivot/F2-SPEC.md`
- Zone scoreboard: `coord/pivot/ZONES.json`, checked read-only by
  `python tools/zone_status.py --zones coord/pivot/ZONES.json --repo . --out <report>`
  (verifies cited evidence exists/parses; never grants readiness)

## Gate tool

`python tools/pivot_gate.py --realistic <econ> --adverse <econ>
--manifest coord/pivot/PIVOT-01.json [--coverage <json>] --out <verdict>`

Read-only. Missing fields/coverage → explicit DATA BLOCKED, never a pass.
Reproduces the X1 NONE shape on all-zero economics (see
`tests/unit/test_pivot_gate.py`).

Gate fix (2026-10-16): CASH controls never advance and configs mapping
to no candidate family in the preregistration (e.g. re-entered X1/S1)
cannot qualify — both previously returned QUALIFIED on strong synthetic
nets. Regression tests: `test_cash_control_never_advances`,
`test_unenrolled_config_cannot_qualify`,
`test_enrolled_candidate_still_qualifies`. Replay on the frozen X1
economics (`outputs/x1/economics_{realistic,adverse}.json`) yields
NONE / RESEARCH UNRESOLVED in `reports/pivot/verdict-x1-replay.json`:
X1 cells UNTESTED (0 intents), S1 control BLOCKED (intents, 0 fills),
all excluded from PIVOT-01 enrollment regardless.

## Enrollment auditor (2026-10-16)

`python tools/pivot_enroll.py --capture <dir> --out <verdict.json>
[--attest-untouched]` streams a capture against the floor below and
writes ENROLLED / DEVELOPMENT-ONLY with per-symbol reasons. It never
imputes: funding *rates* on markPrice are explicitly not settlements,
modelled-spread quotes fail, untouched is UNKNOWN without attestation.

Audited 2026-10-16 (all DEVELOPMENT-ONLY, as preregistered):

| Capture | Span/symbol | Binding failures |
|---|---|---|
| cap-30min | 0.02d | span, no funding settlements |
| cap-2h | 0.08d | span, no funding settlements |
| eval-deep1 | 0.01d | span, 64s mark gap, no funding settlements |

Verdicts: `reports/pivot/enroll-{cap-30min,cap-2h,eval-deep1}.json`;
tests: `tests/unit/test_pivot_enroll.py` (incl. an ENROLLED synthetic
at full floor cadence, so the gate is passable, not vacuous).

Actionable finding for the data lane (W2-owned `tools/capture_*`, not
edited here): current captures record no funding-settlement channel,
so even a future 10d self-capture cannot enroll until settlement
capture with provenance is added there.

Update (same day): the auditor now also accepts
`--funding-file settlements.jsonl` — records of
`{symbol, funding_ts_ms, funding_rate, source}` matching the repo's
`datasets/backfill_funding.py` provenance pattern. Settlements count
only inside the capture span; records without provenance are rejected
loudly. This gives the data lane a target format without editing its
tools. Tests: `test_funding_sidecar_*` (3, incl. outside-span and
missing-provenance rejection).

## Capture sizing (measured 2026-10-16, this host)

From `data/captures/cap-2h` (BTC+ETH, 2h): events.jsonl 1.55GB,
3.06GB written incl. raw duplication. Per-channel byte share
(300k-line sample): bookTicker 83.6%, depth 13.8%, aggTrade 2.2%,
markPrice 0.4%. Extrapolated 10d qualifying capture (top-2):
~186GB events-only (~155GB of it bookTicker, the required quote
stream), ~370GB with raw duplication. This host has 13GiB free —
infeasible here by >10x. BTC-only halves it (~95GB) but still
needs external storage (~256GB) or a capture host with room.
Dropping depth saves only ~14%; thinning bookTicker would break
the tick floor. Storage is an owner provisioning decision.

## Data blocker (owner decision)

Qualification needs ≥10d untouched tick: L2/book quotes (no modelled
spread), aggTrades, marks ≥1s, funding with provenance, monotonic seq.
Current captures (cap-30min/cap-2h, bench30d) are development-only.
Options: fresh self-capture ($0, owner-run supervised) or Tardis Solo
re-audit. No pivot scoring until a dataset enrolls.

## Coordination (3 peer agents active)

This slice touches **only** manager-owned, previously nonexistent paths:

- NEW `coord/pivot/PIVOT-01.json`
- NEW `tools/pivot_gate.py`
- NEW `tests/unit/test_pivot_gate.py`
- NEW `reports/pivot/README.md` (this file)

No edits to `src/`, worker-owned `tools/capture_*` / `tools/replay_*`,
`specs/strategies/`, `specs/acceptance*`, `coord/evidence/*` (W5 verifying),
or any live/execution path. Safe to integrate alongside deep/w1..w5 work.
