# Real-capital readiness — zones, gates, and targets that are honest

Status: working note by the external contributor session. Not
manager-owned; the owner/manager decide and may re-file it. Written
2026-10-16 against `deep/integration` `98616ff` plus branches
`fix/f2-health-recovery` (`1778915`) and `fix/f3-shutdown-drain`
(`ff7b65b`).

## 0. Definition: what "real-capital ready" means here

A system may touch real money only when ALL of these hold; none is
optional:

- **G0 — Measurement is trustworthy.** Data in, booking, shutdown
  accounting, and verdicts are correct and independently checked.
- **G1 — Untouched evaluation data exists.** ≥10 fresh days nobody
  has seen (the current captures are all development knowledge).
- **G2 — A strategy qualifies out-of-sample.** Positive net on
  dev + validation under realistic AND 2x-adverse costs, ≥100 closed
  positions over ≥10 days, on untouched data, independently reproduced.
- **G3 — Mechanics validated on the venue demo.** Owner credentials →
  the prepared demo drill.
- **G4 — Operations and safety verified.** Runbook, kill switches,
  reconciliation, alerts, risk limits (mostly built; drill pending).
- **G5 — Owner authorizes a tiny pilot** with money they can afford to
  lose entirely, under hard caps.

Today: G0 partial (F2/F3 fixed this week; F4 open; W5 verdict
pending); G1 not yet; G2 never achieved (all rounds REJECTED / NONE);
G3 blocked on owner demo keys; G4 largely built; G5 far.

## 1. The honest math on "2–3% per day"

- 2.5%/day compounded over 250 trading days ≈ **1.025^250 ≈ 480×** a
  year. No verifiable retail system does this. Professional market
  makers earn basis points per day on large capital, with fee rebates,
  colocation, and balance-sheet advantages this project does not have.
- The fee floor is structural: Binance USD-M VIP0 taker ≈ 0.05%/side
  (≈10 bps round trip before spread, slippage, funding). The project's
  own causal counterfactual measured **−13.4 bps mean net** per
  candidate (H-R2: 61/61 accounted, 0/60 wins); X1-R1 closed with 0
  qualifying cells, and the cost gate rejected 92 candidates on
  reward-below-cost in one cell alone.
- Indian tax context (verify with a professional): 30% + 1% TDS per
  transfer, no loss set-off — a structural drag on high-frequency
  approaches.
- Capital scale: at ₹10,000, +1%/day ≈ ₹100/day **before** data, VPS,
  slippage, and taxes. The realistic ceiling for an excellent small
  systematic system is low single-digit % **per month**, with negative
  months. A 2–3%/day promise can only come from (a) selling something,
  (b) gambling (leverage martingale / no stops), or (c) cherry-picked
  backtests — the three failure modes this repo's discipline exists to
  prevent.
- What is achievable and worth building: prove or disprove edges
  honestly, keep losses bounded by construction, and compound a
  validated edge — treating each round's result, positive or negative,
  as the product.

## 2. Zones (the terrain, split)

| Zone | What must work | Current state | Next concrete step |
|---|---|---|---|
| Z1 Measurement & verification | replay/bench booking, halts, shutdown accounting | F2 ✓ (level-release), F3 ✓ (shutdown booking); F4 open (operator clear for unknown commands); W5 verdict pending | merge F2/F3 after review; dispatch F4 |
| Z2 Data adequacy | ≥10 untouched days (trades + BBO + marks + funding + depth), audited | bench30d quote-less; depth unsynced (S5 ineligible); funding backfill partial; captures ≤2h | self-capture campaign ($0, own license); Tardis only if pre-Oct history is needed |
| Z3 Cost & execution realism | fee tiers (BNB/VIP), maker-first variants, latency, slippage honesty | taker-only preset; order latency explicitly unclaimed | fee-tier config + a bounded maker-first arm spec (5 bps → ~2.25 bps/side changes economics materially) |
| Z4 Strategy portfolio | mechanisms with a chance | S1–S5 rejected/insufficient; X1 untested (gate never co-occurred); funding carry/basis not implemented; longer horizons absent | one preregistered round on fresh data; add a funding-carry hypothesis with explicit carry math |
| Z5 Risk & safety | budgets/halts/protection/margin | strong and verified; margin/liquidation stress partial | worst-case gap / liquidation-distance stress test |
| Z6 Operations | runbook, monitoring, alerts, demo drill | CLI tools exist; demo blocked on owner keys | demo credentials → run the drill; write the first-response runbook |
| Z7 Capital & governance | expectancy planner, kill criteria, tax | not started | ratify kill criteria (below); net-of-cost expectancy planner; tax consult |

## 3. Kill criteria (proposed, to ratify BEFORE the next round)

- Next clean measurement round (post-F2/F3, on ≥10 untouched days):
  if no config shows positive net on dev + validation under realistic
  AND 2x-adverse costs → **close the scalping branch**. No new configs.
  Keep the platform.
- If a config passes dev + validation but fails the untouched screen
  (≥100 positions / ≥10 days, positive adverse net) → close with the
  same discipline.
- If demo mechanics contradict simulation → stop and fix mechanics
  before any capital.
- Never enable submission on mechanics-only evidence; only G2 + G3 +
  G4 gate it. Existing caps stand if a pilot ever happens (0.25%
  per-trade budget, daily stops); no leverage increase without a new
  validated round.

## 4. What changed this week (external contributor)

- `fix/f2-health-recovery` (`1778915`): **F2** — level-driven health
  halt. Unblocks measurement (round X1-R1 measured the latch, not the
  strategies) and removes the ~8.2M-transition / ~1 GB journal bloat.
- `fix/f3-shutdown-drain` (`ff7b65b`): **F3** — shutdown owner-sweep
  books exit-tick fills; the final report is flat without requiring a
  resume.
- Parallel work disclosed: grok-f2's `deep/f2-mark-health` (narrower
  mark-only release + paper-bool re-assert). Consolidation is the
  manager's decision; both branches share base `98616ff`.

## 5. What this does NOT do

No strategy is qualified; no profit claim is made; submission stays
disabled; the gates above are engineering conditions, not promises.
