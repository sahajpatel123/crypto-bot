# Key data — one day only (2026-10-16, owner-bounded)

Fetched under the owner's "no bulk collection; one day or key data"
instruction. NOT a PIVOT-01 qualifying dataset (floor: >=10d tick);
status DEVELOPMENT-ONLY by construction. No credentials, public
endpoints only. Total <1MB.

| File | Content | Source |
|---|---|---|
| `klines_BTCUSDT_1m_1d.jsonl` | 1440 x 1m bars (24h) | `tools/capture_public.py capture` (Binance USD-M public) |
| `klines_ETHUSDT_1m_1d.jsonl` | 1440 x 1m bars (24h) | same |
| `funding_1d.jsonl` | 6 funding settlements (3/symbol, 8h) | `GET /fapi/v1/fundingRate`, provenance per record |

Integrity (verified 2026-10-16): 1440/1440 minutes per symbol,
0 missing minutes, 0 duplicate timestamps, OHLC internally
consistent, 23.98h span; all 6 funding records carry complete
provenance (source, timestamp, symbol). Enrollment status:
DEVELOPMENT-ONLY by construction — 1 day of 1m bars is not >=10d
of tick with observed quotes, and converting bars to tick events
would be imputation, so no enrollment audit is claimed on it.

Descriptive facts (no strategy scoring, no profit claim):

- Day move: BTC +203bps, ETH +475bps; 1m return stdev 5.0 / 6.9bps;
  largest 1m move 36 / 64bps — vs the 26bps taker round-trip hurdle,
  ordinary 1m noise is far below cost; only rare minutes exceed it.
- Funding: BTC 1.41bps/day, ETH 1.75bps/day summed over settlements —
  far below P2's preregistered 40bps min target on this day. One day
  proves nothing about P2 persistence; it calibrates scale only.
- P1 maker scale (`spread_snapshot.json`, 6 bookTicker samples @5s):
  quoted spread is one tick — 0.012bps (BTC) / 0.041bps (ETH) —
  against P1's 15bps min target. Spread capture alone is ~400x
  too small; any P1 edge would have to come from rebates and
  adverse-selection avoidance, not the quoted spread. Snapshot
  only (30s window); tick-bound spreads on these symbols are
  structural, but intraday variation is unmeasured here.
- P2 basis scale (`basis_1d.json`, 24 x 1h spot-vs-perp closes):
  perp traded ~4.7bps (BTC) / ~4.4bps (ETH) BELOW spot all day
  (ranges -6.1..-3.3 / -5.6..-3.2bps). Combined with funding above,
  the whole carry complex (funding ~1.5bps/day + |basis| ~5bps)
  sits an order of magnitude under P2's 40bps min target today.
- P3 swing scale (24 x 1h bars, n small): 1h ATR 60bps (BTC) / 85bps
  (ETH), so the 26bps round trip is 43% / 31% of 1h ATR. Against 4h
  ranges (mean 125 / 203bps, median 88 / 150bps) costs are ~21% /
  ~13% — still above P3's preregistered "costs <10% of ATR" bar on
  this day, though within ~2x of it at the 4h horizon, unlike the
  60s scalp's 12x shortfall. Descriptive only; 24h cannot validate
  or reject P3.
