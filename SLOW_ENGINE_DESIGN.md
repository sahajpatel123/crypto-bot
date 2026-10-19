# Slow-engine design (not built as a live path)

No Family B hypothesis survived the corrected dev gates, so this is a
design note and not an order path. `research/slow_path.py` can plan a
paper book and always records `orders_sent: 0`. It is not wired to a
venue.

If a future hypothesis is frozen and then screen-passes on a fresh
holdout chunk:

1. Portfolio risk: gross cap 2, per-symbol cap from that prereg, net cap
   tight for basis books, daily and weekly loss stops, kill on
   non-positive equity. Do not change the one-position scalp rules.
2. Rebalance: no-trade band, TWAP slices, reconcile to venue positions
   before any live send. Spot legs only for a basis hypothesis that
   actually passed.
3. Forward paper: pessimistic costs, predicted versus realized
   attribution each rebalance, clock of 60 days and 30 rebalances,
   whichever finishes later.
4. Size from the bootstrap lower bound of expected return, then a
   hard cap. First tranche minimal. Demotion automatic. Promotion manual.
5. Gate: SCREEN_PASS must be `SEALED-HOLDOUT` with matching hashes,
   forward compare pass, fresh costs, host check, drill, heartbeat.
   Prod still refuses without a human arm.

Until that happens the live gate stays NO-GO.
