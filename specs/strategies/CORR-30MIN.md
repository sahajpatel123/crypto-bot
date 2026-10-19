# CORR-30MIN correction report (Worker 4, phase A)

Correction assignment from `Muse_Crypto_Handoff_Review_and_Corrections.md`
(Worker 4 section). Phase A only: allowlist enforcement, opportunity/fill
reporting repair, dev-comparison prep. No economic scoring (phase B awaits
Workers 1–3 + manager go).

## 1. ROUND-01 vs runtime selection (FIXED)

- Mechanical finding: `arms=all` over S1–S4 resolves **11 distinct arm
  IDs** including S2-V/S2-F, which ROUND-01 excludes (deferred).
  Proven by `research/allowlist.py`: `extra=['S2-F', 'S2-V']`.
- Prior reports' "18 arms" counts **evaluation row labels** (4 base arms
  + 7 variant arms x 2 directions, e.g. `S1-V:LONG`), not independent
  configurations. Configurations are arm IDs: 11 under arms=all, 9 in
  ROUND-01. (Old handoff files are frozen history and were left
  untouched; the correction lives here and in code comments.)
- Fix: `strategies.arms_allowlist` config key (default None = legacy
  behavior) + Session filter (base adapters + variant loop) +
  `backtest.py --require-round/--require-config` gates that abort on
  any arm/param disagreement before running.
- Executable configs: `configs/round01.toml` (full 9-arm allowlist) +
  `configs/round01/R01-*.toml` (11 per-config derivations, each passing
  its own `--only-config` gate). Verified end-to-end: the gated slice
  evaluated zero S2-V/S2-F/S5 rows.
- Parameter fingerprints (`trials/round-01.params.json`, sha
  `f08fa9c507a5ef17`): live S1–S4 dataclass values match the frozen
  file (no drift). Review notes (for W1, non-blocking): code carries
  `take_r=1.5` for S2/S4 where cards omit TAKE_R; `HALT_GAP=5` (cards)
  is `MAX_CONSECUTIVE_MISSING_HALT=5` (code) — same value.
- Shared-file touches for deliberate integration: `config.py`
  (+allowlist key, fingerprint-preserving), `session.py`
  (+6-line filter in `_strategy_adapters`, +3-line variant skip),
  `backtest.py` (+gating flags, default off). All default-off.

## 2. Opportunity/fill reporting (REPAIRED, funnel v2)

`research/funnel.py` now reports unique decisions + eligible time:

- 8 stages: usable data → strategy eligible → setup → cost pass →
  portfolio/risk pass → submitted → filled → closed (journal-linked;
  banked closes reproduce exactly: validation 11, test 1).
- Separations: no setup, startup (pre-first-eligible seconds; never
  counted as strategy observation), stale input (`gate:*` quote/mark
  holds), missing depth (`book:*`, split from generic unavailable),
  below costs, minimum-size, IOC cancellation (unique unfilled
  venue-cancelled entries), exposure/cooldown, plus informational
  other_hold (event/anomaly/reconcile/config gates).
- Original-decision preservation: every unique intent carries
  `strategy_verdict: admitted` plus its terminal gate
  (`intent_stage_paths`), so a later gate block never overwrites the
  strategy's decision; terminal-gate counts summarize the loss points.
- Symbol-time: `analyze_symbol_time` measures usable (symbol, second)
  pairs from capture events, independent of evaluation.
- Corrected-stack slice (synth dev, 18k events, allowlisted): 124,165
  rows = 124,166 unique opportunities; 9,000 usable XRPUSDT-seconds;
  761 unique intents → 1 selected (S4-S) → 1 submitted → 0 filled,
  1 IOC-cancelled. Zero unmapped reasons across slice + banked cells.
- Failed/discarded trials retained via registry v0.4.0 (`TrialLog`
  append-only; `failed()`/`discarded()`).

## 3. Diagnosis notes (carried forward)

- Data remains the dominant stricture (banked: 3.4–4.1M gap rows +
  1.2–1.4M never-synced depth rows); S5 stays excluded (0 eligible
  seconds anywhere, 0 snapshots installed).
- Journal still cannot split IOC-remainder vs price-band cancels
  (both `venue-canceled`); no expiry rows observed anywhere.
- Synth slices measure mechanics only; economics await corrected
  execution on compatible real-data slices (see ROUND-01-DEV-SLICES).
