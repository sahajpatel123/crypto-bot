# PILOT-01 scoring preregistration (frozen before ANY pilot strategy scoring)

Date: 2026-10-17. Status at filing: zero strategy scores computed on pilot
data (only enrollment QC audits). Dataset: data/pilot/<date>/ rank-ordered
volatile days per coord/pivot/PILOT-01.json.

Regime caveat (binding on all results): volatile-regime behavior ONLY.
Nothing here qualifies any config for capital (PIVOT-01 10-day rule stands).

## Cost contract
- realistic: 26bps round-trip (cost-contract-v1).
- adverse: 52bps round-trip (2x).
- Verdict rule per family: PILOT-SIGNAL iff pooled net_mean_bps > 0 at BOTH
  costs AND pooled net_winners/n > 0.5 at realistic; else PILOT-NONE;
  PILOT-BLOCKED only for data/ops failure or unevaluable channel.

## Cells (one replay per family config, run exactly once)
1. SCALP (STUDY-01 as-preregistered): tools/pivot_study_01_momentum.py,
   thresholds 15/30, trail 60s, hold 60s, warmup 130 bars; run at
   --rt-cost 26 and --rt-cost 52 (cost flag changes the charge only,
   identical trade list). Pool cells across days per (thr, side).
2. P3-SWING (tools/pivot_study_02_swing.py, spec below): 1h-bar
   continuation on causal 1s aggTrade closes. Signal at each 1h close
   (warmup: first 4h of day skipped): LONG if close > prior 4h high + 10bps;
   SHORT if close < prior 4h low - 10bps; else flat. One position max per
   day-side; 4h time exit (fill at exit-bar close; positions opened after
   20:00 UTC skipped — no room for 4h exit in-day, no overnight holds in
   pilot). Stop: none beyond time exit (matches P3 low-turnover hypothesis;
   gross must clear 2x hurdle per PIVOT-01 invalidation). Costs 26/52bps.
3. P2-CARRY (tools/pivot_study_03_carry.py, accounting only): sum observed
   funding settlements per day (funding.jsonl, provenance-checked) in bps
   of notional for a 1x perp-long-through-settlement position; report
   mean/day vs 40bps min_target. No hedge leg exists in pilot channels, so
   full delta-neutral carry is NOT scored — reported as funding-only
   descriptive with that caveat. Verdict: PILOT-SIGNAL impossible by
   construction (incomplete strategy); record PILOT-NONE or P2-PARTIAL.
4. P1-MAKER: PILOT-BLOCKED — no quote channel in futures archive; queue
   fill rate and adverse markout unevaluable. No replay attempted.

## Forbidden
- Tuning any threshold/horizon on pilot results; re-running with changed
  params; dropping days for their results; pooling extra data post-hoc.
- Presenting pooled means as expectancy or profit rates.

Filed by: manager (this session), 2026-10-17, pre-scoring.
