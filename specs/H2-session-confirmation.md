# H2 Session-confirmation design (next stage after dev PASS)

Question: does the bar-level H2 dev edge survive the real Session
path (selector → risk → Nautilus fills → protection → ledger)?

Design (no code yet; build only after H2 dev verdict is PASS):
- Implement H2 as a runtime strategy on the existing contract
  (strategies/contract.py, MarketView 1h bars): EMA20/50 trend,
  ATR-percentile>70 gate, stop 1.5xATR / target 3xATR, taker.
  Universe and sizing identical to the dev evaluation (8 symbols,
  0.125% risk/trade, 3x leverage cap). One position per symbol.
- Run via research/backtest.py harness on the frozen benchmark
  (fresh Session per split; test split scored once). Compare
  Session expectancy vs bar-level +55.9bps: slippage, protection
  sequencing, and risk halts explain any decay.
- PASS bar unchanged (verdict.evaluate_trades, family_size=4 with
  H4 in family). Any Session FAIL overrides the bar-level result:
  the bot trades through Session, not through bars.
- Only after Session PASS: 14-day pessimistic paper (T5.6), then
  owner gates (demo drill, latency, armed.json review). No arm on
  bar-level evidence alone.
