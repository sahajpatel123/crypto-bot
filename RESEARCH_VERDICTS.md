# RESEARCH VERDICTS — does anything have a real fee-inclusive edge?

**Answer today: no strategy has demonstrated a positive net
expectancy — 0 PASS across the 6 machine verdicts in
research/verdicts/.** A rigorous negative result plus a hardened
system is a successful outcome here; nothing below is dressed up.

## Evidence (development data only — see research/DATA_LEDGER.md)

| Family | Ledger-cited audit input | Machine verdict |
|---|---|---|
| Taker scalps (prior pilot, S-family) | 0/14 cells positive; best −25.37bps at 26bps cost (14 cells; raw vectors absent in-tree) | UNDERPOWERED — research/verdicts/pilot-S.json (n=0 in-tree trades) |
| H-R2 (prior benchmark) | −13.42bps expectancy cited (raw vectors absent in-tree) | UNDERPOWERED — research/verdicts/H-R2.json (n=0 in-tree trades) |
| X1 (prior benchmark) | 0 fills in 24 cells cited, F2 latch since fixed (raw vectors absent in-tree) | UNDERPOWERED — research/verdicts/X1.json (n=0 in-tree trades) |
| H1 maker OFI scalp | research/prereg/H1-maker-ofi-scalp.md — preregistered, 0 trials | UNDERPOWERED — research/verdicts/H1.json (unevaluated) |
| H2 trend/vol-regime | research/prereg/H2-trend-vol-regime.md — preregistered, 0 trials | UNDERPOWERED — research/verdicts/H2.json (unevaluated) |
| H3 funding-skew tilt | research/prereg/H3-funding-skew-tilt.md — preregistered, 0 trials | UNDERPOWERED — research/verdicts/H3.json (unevaluated) |

## Structural cost arithmetic (research/verdicts/cost-model.json)

Machine output of `tools/verify_breakeven.py --out
research/verdicts/cost-model.json` (30 rows checked, 3 infeasible):
EV = p*T − (1−p)*S − c gives p* = (S+c)/(T+S) per
research/verdicts/cost-model.json. At 25/25bps stop/target with a
taker entry, round-trip is 18bps at 1x requiring 86% wins; at
1.5x/2x stress (27/36bps) it needs 104%/122%, recorded
infeasible in research/verdicts/cost-model.json. At 26bps a 25/25
needs 102%, also infeasible per research/verdicts/cost-model.json,
which is what the pilot's ledger-cited best cell (−25.37bps) shows
without a real signal. Maker entry (15bps at 1x, 80% at 25/25)
priced with the conservative queue model in
`execution/fill_realism.maker_fill` (no credit for touches).

## Protocol (machine process, rerun in research/verdicts/README.md)

The verdict CLI emits hash-bound JSON documents with config, data
and code bindings and no manual override path; rerun commands are
in research/verdicts/README.md. A positive outcome needs bootstrap
CI95 lower bound above zero at realistic cost, expectancy above zero
at 2x adverse cost, at least 300 trades, at least 60% non-negative
days, drawdown inside budget, and Holm correction across the family
(see research/verdicts/README.md). Confirmation runs exactly once
per hypothesis on untouched data as released by the owner (see
research/verdicts/README.md).
