# H5 — Alt-universe maker OFI scalp (preregistered, before capture)

Motivation (disclosed evidence): H1 on BTC/ETH produced 7 signals in
5,962 snapshots — majors are too balanced at the frozen 0.6 top-5
threshold. H2/H4 show opportunity concentrates in volatile names.
H5 tests maker OFI where order flow actually imbalances.

Rules (exact, frozen; H1 mechanics unchanged):
- Universe: daily causal top-3 by trailing-30d ATR% from
  BTC/ETH/SOL/ZEC/NEAR/STRK/XRP/W (same ranking as H4); capture and
  score only those names. BTC/ETH may rank in; no hand-picking.
- Signal: top-5 notional imbalance beyond +/-0.6. Entry: post-only
  at best bid/ask, 30s cancel, fill_realism.maker_fill (touches earn
  nothing). Exit: stop 25bps / target 50bps taker, max 1 position.
- Evaluation: ONLY on captures starting after this file exists.
  Verdict: verdict.evaluate_trades family_size=5. Report fills/day
  and mean net bps/day; the daily-average target is measured, never
  assumed. Implementation: research/h1_eval.py unchanged.
