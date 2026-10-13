# Signal-to-fill funnel — 30MIN diagnosis (Worker 4)

Method: `research/funnel.py`. Unique candidate IDs + eligible time per
30-minute plan section 5 (not repeated rows). Sources: two completed
banked COMBINED cells (observed-archive, aggregates + journal) and one
short bounded synth slice (dev x COMBINED, 18,000-event causal prefix,
full row-level artifacts). All jobs ran under `tools/run_budget.py`.

## Slice (synth dev, XRPUSDT, 18,000 events, 15.9 s job)

- 44,335 evaluation rows = 44,345 unique (strategy, second)
  opportunities (strategy rows are already ~1/second; repetition lives
  in the intents table, not here).
- Eligible seconds: S1–S4 7,189 each; S5 0 (no depth in synth data).
- Healthy no-trade seconds: 28,746 total (S1 7,183; S2 7,188; S3 7,188;
  S4 7,187; S5 0).
- Intents: 23,648 rows → 253 unique real intents (1.0 rows/unique);
  23,395 rows are strategy-stage placeholders (5 ids, ~4,679:1).
- Selected: 10 (S1 6, S4 2, S2 1, S3 1, S5 0).
- Entries: 10 submitted → 2 filled + 8 venue-canceled unfilled (IOC).
- Row buckets: unavailable_data 15,589; missing_sequence 1,120;
  no_setup 27,383; below_cost 120; below_minimum 0; stale_expired 0;
  nonmarketable 0 (gap, see below); ioc_cancelled 8 (unique);
  exposure_cooldown 123. Unmapped reasons: none.

## Banked validation (COMBINED, 7 d, 16.34M events, net -0.3063%)

- 6,046,672 rows → unavailable 4,596,397 (gap 3.39M + book:never-synced
  1.21M); missing_sequence 158,661; no_setup 1,261,268; below_cost
  2,691; below_minimum 1; exposure_cooldown 27,654 (position-busy
  27,639 + cooldown 15); stale/nonmarketable 0. Unmapped: none.
- Unique IDs (journal): 13 reservations → 13 entries → 11 filled +
  2 venue-canceled unfilled; 22 fill exec_ids.

## Banked test (COMBINED, 8 d, 14.75M events, net -0.0770%)

- 6,910,699 rows → unavailable 5,501,172 (gap 4.12M + book 1.38M);
  missing_sequence 145,849; no_setup 1,242,653; below_cost 481;
  below_minimum 1; exposure_cooldown 20,543. Unmapped: none.
- Unique IDs: 1 reservation → 1 entry → 1 filled; 2 fill exec_ids.

## Diagnosis

1. Data, not setup quality, is the dominant stricture: 76–80% of
   banked rows are unavailable-data (feed gaps + never-synced books).
2. S5 never fires anywhere: 0 eligible seconds on the slice, 0 known
   admits banked, 0 snapshots installed. Excluded from ROUND-01 until
   depth-enabled captures exist.
3. Of the eligible remainder, no-setup dominates (~21%/62% banked/slice
   of rows): strategies mostly see no setup; the cost filter
   (below_cost) bites only a thin margin above it.
4. Exposure/cooldown is almost entirely position-busy (one-position
   design serializes candidates); explicit cooldown is negligible.
5. Entry fill mechanics differ slice-vs-banked (2/10 vs 11/13 filled;
   8/10 slice entries venue-canceled unfilled). Slice economics are
   synthetic — mechanics only, no profitability read (scoring follows
   corrected execution).
6. Instrumentation gaps (for W1): the journal does not distinguish
   IOC-remainder cancels from price-band protection cancels (both
   `venue-canceled`), so nonmarketable reads 0 observed; no
   intent-expiry rows were emitted anywhere, so stale_expired reads 0
   observed. Buckets are wired for both when labels land.
