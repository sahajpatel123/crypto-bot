# Quick-trade probe outputs (frozen records)

Per-capture result JSONs from the 2026-10-16 runs documented in
`docs/quick-trade-probe.md` (flow-fade + continuous modes, touch and
through sensitivities, all five captures).

## Provenance warning (2026-10-17)

The input captures (`data/captures/cap-30min`, `cap-2h`,
`agreement-30s`, `cap-48h-90s`, `smoke-60s`) were **deleted in the
Oct-17 repo storage cleanup** (old development captures + stopped
campaign removed to free disk; only `data/pilot/`, `data/observed/`
residue and live campaigns remain). These JSONs are therefore
**records of computed results, not reproducible artifacts**: the
numbers, counters and exit paths stand exactly as the tool printed
them, but the `Repro` commands in the memo cannot re-run until the
same frozen rules execute against new data.

The tool itself (`tools/quick_trade_probe.py`) is unchanged and its
9 rule-level tests still pin every expectation on synthetic streams.
The powered re-run is predeclared against the fresh 1-day campaign
data under identical frozen rules — no threshold changes.
