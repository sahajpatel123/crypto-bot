# B1 — Vol-scaled time-series trend, multi-horizon, liquid-perps basket

Status: FROZEN-BEFORE-EVALUATION (committed pre-evaluation, Family B 7/8).
Data: DEV lake only. No holdout touch. No lake statistic seen at prereg.

## Economic mechanism

Prices underreact to news and flows diffuse slowly across venues and
participants; hedging/rebalancing flows and liquidation cascades extend
moves beyond fundamentals. A trailing-return sign rule rides the
persistent component. Vol scaling keeps risk stationary across regimes
so no single episode dominates the P&L.

## Counterparty test

Who loses: (a) hedgers and forced sellers (miners, treasuries,
liquidated longs/shorts) trading for non-informational reasons;
(b) late retail chasers buying tops/selling bottoms; (c) stop-loss
cascades that push price through technical levels. Why it persists:
hedging/liquidation demand is structural and price-insensitive;
information diffuses slowly across hundreds of venues/pairs; behavioral
anchoring delays reaction. Crowding risk is real (failure mode F3).

## Exact rules

- Universe: `eligible_universe` top_n=30, min_listing_age_days=90,
  min_quote_volume_30d=$10M, computed at each weekly rebalance date.
- Signal date: each Monday 00:00 UTC (start of week W). For symbol s and
  lookback L in {20, 60, 120} days: `ret = close[d-1]/close[d-1-L] - 1`
  where d = Monday date (uses closes ≤ Sunday close; most recent day
  skipped by construction of d-1 indexing... precisely: last close
  used is Sunday's, first is L days before it).
- Direction: +1 if ret > 0, -1 if ret < 0, 0 if exactly 0.
- Position: sleeve per symbol = direction × (target_vol / σ_20/60) ×
  (equity / N), where σ = trailing vol-window std of daily log returns
  (annualized), N = number of nonzero-signal symbols that week.
  Portfolio rescaled to gross ≤ 2× equity; per-symbol ≤ 25% gross.
- Execution: market (taker) at Monday 00:00 UTC open (the daily bar
  open). All figures use next-open execution.
- No-trade band: keep the previous week's sign unless the new sign
  persists 2 consecutive weeks (anti-whipsaw hysteresis).
- Delisting: exit at last available close (taker costs), no replacement
  until next rebalance.

## Parameter grid (12 cells, ALL trials counted)

| lookback L (days) | vol window (days) | target vol (ann.) |
|---|---|---|
| 20, 60, 120 | 20, 60 | 15%, 25% |

Literature-convention values (1/3/6-month trend; 1/3-month vol);
symmetric spans, not fitted.

## Cost model (realistic all-in)

- Perp taker 7.5bps/side (5bps VIP0 + 50% history buffer).
- Spread 1bp/side. Slippage per side:
  max(1bp, 0.5 × σ_1d_trailing × √(order_notional / ADV_30d)).
- Funding paid/received at every 8h settlement on actual positions
  (observed fundingRate; DEV lake / verdict-time holdout).
- 2× adverse: fee+spread+slippage legs doubled; funding unchanged
  (transfer, not cost).
- Taker-only assumption (maker upside not counted).

## Rebalance / turnover

- Weekly, Monday 00:00 UTC signals→execution as above.
- Turnover budget: ≤ 6× one-way annualized (reported; promotion
  requires ≤ budget).

## Universe / leverage / risk

- Universe rule above; vol target per cell; gross ≤ 2×; per-symbol
  ≤ 25% gross; isolated-liq distance checked per position in backtest
  (3× headroom assumption); account leverage cap 3× respected.

## Dev promotion (numeric; E5 anchors + one justified adjustment)

Walk-forward OOS: train [2020]→test 2021, [2020-21]→2022,
[2020-22]→2023; purge/embargo = max(30d, 2× holding). Pooled OOS =
2021–2023 daily net returns.
- Pooled OOS net Sharpe ≥ 0.7 at realistic cost.
- Net Sharpe > 0.3 at 2× cost (same OOS series).
- DSR ≥ 0.8 with trials = 12.
- PBO ≤ 0.3 (CSCV on DEV).
- Positive net in ≥2 of 3 OOS calendar years (2021–2023).
  ADJUSTMENT with justification: the E5 anchor says "≥3 of last 4 dev
  years", but 2020 is train-only by construction (no OOS exists for
  it); requiring it would force in-sample evaluation. 2-of-3 OOS
  years is the coherent equivalent.
- Plateau: ≥70% of Hamming-distance-1 neighbor cells have OOS Sharpe > 0.
- Max drawdown ≤ 35% at intended risk.
- Turnover ≤ 6× one-way annualized.
Failure on ANY bullet KILLS B1 permanently (best cell judged; all
cells reported).

## Confirmation (holdout screen, exactly once, via verdict)

- Point net Sharpe > 0.3 AND ≥ 50% of dev OOS Sharpe.
- 80% stationary-bootstrap lower bound > −0.3.
- Positive at 2× cost. Drawdown inside 35% budget. Turnover reported.
Verdict text states the screen-not-proof caveat (SPLIT.md power table).

## Failure modes

F1: range-bound regime — whipsaw despite hysteresis. F2: crowded exit
(all trend-followers deleverage together). F3: costs exceed drift on
20d cells (turnover). F4: single-symbol blowups dominate equal-risk
sleeves (mitigated by 25% cap).

## Knowledge-contamination note

What I know about 2019–2026 crypto: BTC ≈$7k Jan-2020; COVID crash
Mar-2020; bull run to ≈$69k Nov-2021; bear market 2022 (≈$16k low,
LUNA collapse May-2022, FTX Nov-2022); recovery 2023; 2024 halving +
US ETFs; new highs 2024–25; many alt boom/bust cycles.
How this rule avoids contamination: (1) lookbacks/vol windows are
textbook trend conventions (1/3/6mo, 1/3mo vol), not values recalled
as "working"; (2) the grid is a small symmetric span, no event-
conditioned filters (no halving/crash dummies); (3) universe/costs
from venue mechanics; (4) vol targeting is risk hygiene, not alpha;
(5) written before ANY lake statistic was computed (inventory metadata
only: counts/dates/bytes).
