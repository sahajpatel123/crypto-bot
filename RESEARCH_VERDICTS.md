# RESEARCH VERDICTS — does anything have a real fee-inclusive edge?

**Answer today: no strategy has a demonstrated positive net
expectancy, and no hypothesis in this repo has a machine-written
verdict JSON.** Every row below either maps to a machine artifact in
this repository or is explicitly labelled as prior-audit reporting
(F0.4d: unbacked sentences were removed).

## Machine-backed verdicts in this repo

| Hypothesis | Artifact | Verdict |
|---|---|---|
| H1 maker OFI scalp | `research/prereg/H1-maker-ofi-scalp.md` (committed before evaluation) | UNDERPOWERED — unevaluated, 0 trades |
| H2 trend/vol-regime | `research/prereg/H2-trend-vol-regime.md` | UNDERPOWERED — unevaluated, 0 trades |
| H3 funding-skew tilt | `research/prereg/H3-funding-skew-tilt.md` | UNDERPOWERED — unevaluated, 0 trades |
| H4 cross-venue lead-lag | `research/prereg/H4-cross-venue-leadlag.md` | UNDERPOWERED — unevaluated, 0 trades |
| H5 liquidation-cascade fade | `research/prereg/H5-liquidation-fade.md` | UNDERPOWERED — unevaluated, 0 trades |
| H6 vol-shock regime filter | `research/prereg/H6-volshock-filter.md` | UNDERPOWERED — unevaluated, 0 trades |

## Prior-audit reporting (NOT machine verdicts; do not cite as proof)

The previous program reported, from DEVELOPMENT data since inspected
(`research/DATA_LEDGER.md`): pilot taker scalps 0/14 cells positive
(best −25.37bps at 26bps cost), H-R2 −13.42bps, X1 0 fills (a since-
fixed latch). No trades files or verdict JSONs for those runs exist
in this repository, so under F0.4d they are recorded as prior-audit
reporting only. The autopilot (F4) must re-derive any such claim
through `cryptobot verdict` before it can be used.

## Why taker scalps fail structurally (verified F0.4b)

`cryptobot.research.cost_model_v2.breakeven_table()`, re-derived
independently in `tests/unit/test_breakeven_independent.py`
(EV = p*T − (1−p)*S − c ⇒ p = (S+c)/(T+S)): at 25/25bps stop/target,
the default taker round-trip (18bps) requires an 86% win rate; at the
pilot's 26bps round-trip it requires 102% — INFEASIBLE, flagged
`feasible: false` in the table. (An earlier revision said ">60%";
that understated the hurdle and is corrected here.)

## Protocol for any future claim

`cryptobot verdict` emits PASS/FAIL/UNDERPOWERED JSON bound to
config/data/code hashes, no manual override, and rejects SYNTHETIC
provenance. Confirmation happens exactly once per hypothesis on
sealed CONFIRM vault data via the one-shot token (F3.5/F4.5).
