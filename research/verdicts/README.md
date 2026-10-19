# research/verdicts — machine-written verdict JSONs (F0.4d, F4)

Every `*.json` here is MACHINE-WRITTEN ONLY (rule 6): produced by
`cryptobot verdict` or `tools/verify_breakeven.py --out`, never
hand-edited. RESEARCH_VERDICTS.md cites these files for every verdict
sentence; tests/unit/test_verdicts_mapping.py enforces the mapping.

## What these verdicts mean (2026-10-18)

All six strategy verdicts are UNDERPOWERED with n=0 machine-readable
trades in the committed tree:

- `pilot-S.json` (S-family taker scalps): pre-takeover audit input
  cites 0/14 cells positive, best −25.37bps at 26bps cost
  (research/DATA_LEDGER.md). Raw cell/trade vectors are NOT in the
  committed tree (data/pilot is uncommitted in the main checkout and
  off-limits), so no machine FAIL can be recomputed in-tree. The
  ledger citation stands as audit input; the machine verdict on
  in-tree evidence is UNDERPOWERED.
- `H-R2.json` (−13.42bps cited), `X1.json` (0 fills cited): same —
  datasets/benchmark_30d raw vectors absent from the committed tree.
- `H1/H2/H3.json`: preregistered, not yet evaluated (0 trials).

`cost-model.json`: machine output of verify_breakeven (30 rows,
3 INFEASIBLE). Structural arithmetic, not a strategy verdict.

## Rerun (exact commands)

```sh
export PYTHONPATH=<worktree>/src
export CRYPTOBOT_CODE_COMMIT=$(git rev-parse HEAD)
PYBIN=/Users/sahajpatel/Code/cryto-bot/.venv/bin/python  # or worktree .venv
for spec in "pilot-S:S-family-pilot:research/DATA_LEDGER.md" \
  "H-R2:H-R2-benchmark:research/DATA_LEDGER.md" \
  "X1:X1-benchmark:research/DATA_LEDGER.md" \
  "H1:H1-maker-ofi-scalp:research/prereg/H1-maker-ofi-scalp.md" \
  "H2:H2-trend-vol-regime:research/prereg/H2-trend-vol-regime.md" \
  "H3:H3-funding-skew-tilt:research/prereg/H3-funding-skew-tilt.md"; do
  f="${spec%%:*}"; rest="${spec#*:}"; hyp="${rest%%:*}"; cfg="${rest#*:}"
  $PYBIN -m cryptobot.cli verdict --trades research/verdicts/trades/$f.jsonl \
    --hypothesis $hyp --config $cfg --family-size 6 \
    --out research/verdicts/$f.json
done
$PYBIN tools/verify_breakeven.py --out research/verdicts/cost-model.json
```

Expected: all six RC=1 (non-PASS), verdict UNDERPOWERED; cost script
RC=0, 30 rows OK. Trades inputs are empty (`trades/*.jsonl`, 0 bytes)
because no machine-readable trade vectors exist in-tree — that
emptiness IS the evidence of UNDERPOWERED, not a gap to fill by hand.
F4 autopilot appends dev/confirm verdicts here as data accrues.
