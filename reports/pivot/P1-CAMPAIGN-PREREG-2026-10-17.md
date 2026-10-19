# P1-CAMPAIGN-PREREG-2026-10-17 — maker-spread study on live 1-day set

Filed BEFORE data/captures/campaign-1day-20261017 settles (chunk-000 of 24
running at filing). Zero P1 scores exist anywhere. Target data: campaign
chunks with depth_snapshots + aggTrades + funding (full profile, BTCUSDT).

## Why campaign, not pilot archive
P1 needs a defensible queue model: join Shows position behind DISPLAYED
depth (depth snapshots), consume by taker flow through the level
(aggTrades, causal). bookTicker-only archive cannot support this without
free parameters that would drive the result (assumption theater). The
pilot correctly returned P1 = PILOT-BLOCKED.

## Config (frozen; one replay only)
- Join best bid AND best ask (two-sided quote) at each depth snapshot with
  size = $500 notional each side (~dust; queue impact negligible).
- Queue position: behind full displayed size at that level at join time.
- Queue consumption: seller-taker aggTrade volume (is_buyer_maker=true)
  depletes bid queue; buyer-taker depletes ask queue. Level changes before
  depletion = rejoin at back of new level (chase). Snapshot gaps >5s =
  cancel both sides until next snapshot (no blind quoting).
- Toxicity filter (the P1 hypothesis): cancel a side if mid moves against
  it by >5bps within 10s of joining; rejoin allowed after 30s cooldown.
- Fill = full $500 when cumulative through-volume >= queue ahead.
- Costs: 2bps/side maker fee (Binance VIP0, no rebate assumed) + adverse
  2x run (4bps/side). Spread capture measured at fill mid.
- Kill (from PIVOT-01 P1): adverse markout at fill+5s worse than
  -spread/2 on average, or realized spread capture < 0 after fees.
- Min sample: 100 fills/side pooled; fewer = P1-UNRESOLVED (not a signal).

## Verdicts
P1-SIGNAL iff spread capture net of fees > 0 BOTH costs AND markout kill
not triggered AND n>=100/side. Else P1-NONE / P1-BLOCKED (data/ops).

## Forbidden
Tuning size/cooldown/toxicity on campaign results; pool with pilot days;
claiming expectancy. Optimistic bias note: $500 size assumes no market
impact and displayed depth is fully real (spoofing favors us) — a NONE
under these assumptions is robust; a SIGNAL would still need size-scaling
proof on fresh data.
