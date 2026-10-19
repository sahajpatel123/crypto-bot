# CAMPAIGN-SCORING-PREREG-2026-10-17 — 1-day live-set battery

Filed BEFORE data/captures/campaign-1day-20261017 settles (chunk-001 of 24
running at filing; settlement ~2026-10-18T12:15Z). This is OUT-OF-SAMPLE
confirmation: identical frozen configs, fresh live data. Zero campaign
scores exist.

## Pooled day-capture (mechanical assembly, preregistered)
Campaign = 24 hourly chunks but studies 01-03 take a single capture dir,
and study-02 needs >=9 contiguous 1h bars (impossible per-chunk). So:
concatenate SETTLED chunks' events (time-ordered by exchange_ts_ms,
fresh sequential seq, no other transformation) into
data/captures/campaign-1day-20261017/pooled-day/ with a manifest noting
assembly (chunk list + per-chunk event counts + sha). Enroll-audit the
pooled capture first (expect DEVELOPMENT-ONLY: 1d span). Excluded chunks
(unsettled/near-empty per the QC gate) are listed with counts, never for
results. Assembly is deterministic and result-blind (runs before scoring).

## Battery (each run exactly once: pooled-day for 01-03, chunks for 04)
1. SCALP = tools/pivot_study_01_momentum.py --thresholds 15,30 --rt-cost
   26 then 52 (same trade list, two charges) on pooled-day.
2. P3-SWING = tools/pivot_study_02_swing.py --rt-cost 26/52 on pooled-day.
   Thin-hour rule (<1800 trade-seconds) applies as coded.
3. P2-CARRY = tools/pivot_study_03_carry.py per chunk funding sidecar if
   present, else campaign funding.jsonl whole-day. Funding-only, same
   40bps-target comparison, same hedge-leg caveat.
4. P1-MAKER = tools/pivot_study_04_maker.py --campaign (full spec in
   P1-CAMPAIGN-PREREG-2026-10-17.md; this file incorporates it by ref).

## Verdicts
Same rules as PILOT-SCORING-PREREG per family (SIGNAL iff net>0 both
costs AND hit>0.5 realistic; P1 per its kill criteria; P2-PARTIAL max).
Campaign verdicts are DESCRIPTIVE (1 live day, DEVELOPMENT-ONLY grade);
they CANNOT qualify for capital (PIVOT-01 needs 10d). A campaign SIGNAL
would motivate a 10-day campaign + full PIVOT-01 enrollment, nothing more.

## Data QC gate (before scoring)
tools/pivot_enroll.py --campaign <dir> --attest-untouched must stream all
24 chunks; unsettled/near-empty chunks excluded from scoring WITH a
count disclosed (exclusion for corruption/emptiness only, never results).

## Forbidden
Tuning any param on campaign data or results; swapping chunk exclusion
after seeing scores; pooling pilot+campaign into one verdict (report
separately, compare honestly); presenting either as expectancy.
