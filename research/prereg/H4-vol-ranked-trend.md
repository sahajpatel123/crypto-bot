# H4 — Vol-ranked trend (preregistered, committed before evaluation)

Motivation (from H2 dev evidence, disclosed in RESEARCH_VERDICTS.md):
H2 expectancy concentrates in high-volatility names (STRK/W/NEAR)
while majors drag. H4 tests that observation prospectively. It is a
NEW hypothesis; H2 data cannot confirm it.

Rules (exact, frozen):
- Universe: each UTC day, rank BTC/ETH/SOL/ZEC/NEAR/STRK/XRP/W by
  trailing-30d ATR% (ATR14 on 1h bars / close), take top 3. Causal:
  ranking uses only bars ending before that day starts.
- Signal/exits identical to H2: 1h EMA20>EMA50 trend (mirror short),
  ATR-percentile>70 gate, stop 1.5xATR / target 3xATR, taker, max 1
  position per symbol, 7-day max hold.
- Evaluation: ONLY on days after this file's commit (fresh, unscored
  at preregistration). Verdict: verdict.evaluate_trades family_size=4,
  sized DD under repo sizing (0.125% risk/trade, 3x cap) vs 1000bps.
- Success needs the full PASS bar. Exploratory peeks on pre-commit
  data are forbidden; implementation is tested on synthetic bars only.
