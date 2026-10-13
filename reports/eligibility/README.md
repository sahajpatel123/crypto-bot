# Per-symbol eligible intervals for research input (W3 READY-DATA Track A)

Exact market-eligibility intervals per symbol with a fully classified gap
ledger — one class per excluded span, never a generic gap reason. Generated
offline from capture bytes (no replay) by `tools/eligible_intervals.py`
(`src/cryptobot/market_data/eligibility.py`), all jobs under
`tools/run_budget.py`.

## Files

- `cap-30min.json` — cap-30min (30 min, BTCUSDT+ETHUSDT).
- `cap-2h.json` — cap-2h (2 h, BTCUSDT+ETHUSDT).

Each file records the rule profile (paper.toml 24h-1 fingerprint
443da19b4e4e2a55: quote 1.0s, mark 1000ms, warmup 130), the capture span,
per-symbol trade seconds, mechanical-ready clock, market intervals,
research-ready intersection, the gap ledger, and depth evidence.

## Headline numbers (live rules)

| Capture | Symbol | Market eligible | Research (post-ready) | Empty-trade-s |
|---|---|---|---|---|
| cap-30min | BTCUSDT | 1627.4 s / 1799 s | 1505.8 s | 171 |
| cap-30min | ETHUSDT | 1654.7 s / 1799 s | 1539.8 s | 144 |
| cap-2h | BTCUSDT | 6181.0 s / 7199 s | 6076.1 s | 1014 |
| cap-2h | ETHUSDT | 6230.6 s / 7199 s | 6101.1 s | 964 |

## Empty-second verdict (evidence, not assumption)

- Aggregate message sequence (`venue_seq`/`agg_id`): ZERO breaks on both
  captures (31,428 + 65,540 trades) — transport delivered every message.
  `missing-trade-ids` count is 0 everywhere.
- All empty trade-seconds are `quiet-no-trade`: aggregate sequence
  continuous, quotes/marks flowing, venue had no fills. Healthy
  inactivity — but the bars are still missing under current strategy
  rules (no forward-fill applied anywhere).
- Raw single-ID skips with continuous aggregate sequence (210/316 on
  cap-30min, 664/689 on cap-2h) are venue-side ID consumption by fills
  not published to this stream. Counted per symbol as a volume caveat
  (`venue_raw_id_skips`); they exclude no time and the second's bar stands.
- The one injected-disconnect marker (cap-30min t+900s) has no
  surrounding silence and no ID break: ledger-noted, excludes nothing.
- No depth snapshots in either capture: replay books unsynced
  (S5-ineligible; S1–S4 unaffected).

## Freshness finding

`markPrice@1s` cadence jitters past the 1000 ms bound (~1000
micro-slivers on cap-30min, ~4000 on cap-2h, each a few ms): a 1 Hz feed
can only satisfy a strict 1 s age rule with luck. The intervals above
exclude those slivers exactly (millisecond boundaries). Executable
(BBO/trade) cadence never breaks 1 s on either capture.

## Clocks (separate by design)

- Mechanical warmup: first-trade window + 130 s (≈131 s measured).
- Market eligibility: the intervals in these files (bar present + data
  fresh + no transport/ID gaps).
- Research-ready: market intervals after mechanical ready.
- Strategy-firable (120-clean-bar lookback) is strategy state, not data
  state — see W3-CORR (BTC cap-2h first clean window ends t+3925 s).

## Regeneration

```sh
python tools/run_budget.py --budget-s 1500 --checkpoint-dir CKPT \
  --report-out REP.json -- \
  python tools/eligible_intervals.py --capture <cap-dir> \
  --out reports/eligibility/<name>.json
```
