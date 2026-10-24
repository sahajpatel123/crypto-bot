# H1 book-capture preregistration (prospective, committed before capture)

Purpose: give H1 (maker OFI scalp, research/prereg/H1-maker-ofi-scalp.md)
the only input it can honestly be scored on: synced top-of-book depth.
Dev archives have no book channel, so H1 is UNEVALUABLE retrospectively.

Capture (owner or scheduled job, public data only, no keys, no orders):
- Symbols: BTCUSDT, ETHUSDT. Stream: <sym>@depth@100ms + REST snapshot
  sync via market_data/depth.py DepthBook; persist bridge depth
  snapshots (cryptobot-depth-snapshots/1) + aggTrade prints.
- Start: first run after this file is committed. Duration: until at
  least 300 conservative maker fills are scorable or 14 days elapse,
  whichever comes first. Log the run in research/DATA_LEDGER.md.
- The capture is DEVELOPMENT once scored exploratorily; a PASS still
  needs the exactly-once untouched confirmation before any arm talk.

Scoring (no changes after capture starts): src/cryptobot/research/
h1_eval.py — imbalance > +/-0.6 (top-5 notional), post-only at best
bid/ask, 30s cancel, maker_fill queue model (touches earn nothing),
stop 25 / target 50 taker exit, max 1 position, verdict family_size=3.
Target check: report fills/day and mean net bps/day; 200-300bps/day
average is claimed only if measured with CI95 lower bound > 0.
