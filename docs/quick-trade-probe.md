# Quick-trade capture probe — predeclared method and first results

Status: diagnostics, not a strategy trial and not P&L. Authored by the
external contributor session (2026-10-16). Companion tool:
`tools/quick_trade_probe.py`; rule-level tests:
`tests/unit/test_quick_trade_probe.py`.

## 0. The question this answers

"Can quick/scalp trades make money here?" reduces to one measurable
question at our size: **can a liquidity-providing (maker) fade of
aggressive-flow dislocations capture enough short-horizon reversion to
clear our frozen cost schedules?** The mechanism is the exact one the
published literature identifies as the strongest short-horizon
crypto effect: flow-driven reversal read as compensation for supplying
immediacy (arXiv 2608.21888, 183 pairs, five years, artifact-tested,
frozen holdout). That paper's own headline number, measured over 15-min
spot horizons: **gross edge ≈ 1.3 bp per trade against ≥ 5 bp cheapest
round-trip cost — "large enough to detect, too small to capture."**

This probe is the local, decisive version of that test on OUR captures
(futures venue, BTC/ETH, 1-second tape, October 2026), under cost
schedules that cannot be argued with.

## 1. Predeclared method (frozen in the tool docstring before any run)

Signal (per symbol, causal, file order): at an aggTrade, signed
aggressive notional over 5 s (`flow_W`); **spike** = `|flow_W|` ≥
5× the median of prior `|flow_W|` samples in 60 s (≥20 samples);
**displacement** = last trade vs price 5 s earlier, in bps. Candidate =
spike AND |disp| ≥ 3 bps; primary band |disp| ≥ 5 bps; dose-response
buckets reported in full.

Execution: fade the displacement with a **passive limit at the touch**
(SELL at best ask after an up-spike; BUY at best bid after a down-spike;
stale book >1 s excludes the candidate; resting cap 3 s → unfilled).
Stop 10 bps adverse crosses as taker (+100 ms arrival); target exit is a
passive limit at the opposite quote (10 s cap → taker); horizon 120 s →
taker. **Both fill sensitivities reported: `touch` (print at the limit)
and `through` (print strictly beyond).** No imputation anywhere:
unfilled, unresolved and stale paths are counted and excluded.

Costs: maker 2.0 bps / taker 5.0 bps per leg (USDT-M VIP0), BNB-discount
column 1.8/4.5, ADVERSE column 2× actual path, all-maker and all-taker
bounds. Funding settled only on a real 8h boundary inside a hold
(placeholder 1.0 bp/boundary; captures carry no funding channel).

Outputs: counters (candidates, stale, filled, unfilled, unresolved,
exit paths) and bps distributions (gross, net per schedule, win rate,
holds, 5 s/30 s markouts). **Counterfactual diagnostics, never P&L.**

## 2. Results (all five captures; BTC+ETH; run 2026-10-16)

| capture | candidates | filled (touch/through) | gross bps (touch) | net actual (touch) | net all-maker | net all-taker |
|---|---|---|---|---|---|---|
| agreement-30s | 33 | 0 / 0 | — | — | — | — |
| smoke-60s | 59 | 1 / 1 | +0.04 | −3.96 | −3.96 | −9.96 |
| cap-48h-90s | 12 | 0 / 0 | — | — | — | — |
| cap-30min | 2,293 | 25 / 14 | **−0.35** | −4.71 | −4.35 | −10.35 |
| cap-2h | 7,902 | 30 / 19 | **−0.44** | −5.44 | −4.44 | −10.44 |
| **combined (filled)** | — | **55 / 33** | **−0.400 / −0.967** | **−5.109 / −6.513** | **−4.400 / −4.967** | **−10.400 / −10.967** |

(The combined row reports touch / through. All figures computed from the
saved per-capture JSONs; win rate 0 % on every schedule.)

Note on counts: "candidates" are flow spikes passing the 5× median gate;
the subset with |disp| ≥ 3 bps arms an episode. Episodes armed =
filled + unfilled + unresolved — cap-30min 29 (touch) / 22 (through),
cap-2h 31 / 27; the remainder of the spikes had < 3 bps displacement
inside the window (micro-noise) and were recorded, not traded.

Additional observed facts:

- **Win rate 0 %** on every fee schedule (gross ≈ 0 or negative).
- **Stops never fired**: positions exited by passive target or resting
  expiry within seconds — the tape gives nothing to harvest.
- **Markouts confirm adverse selection, not edge**: mean 5 s/30 s
  markouts ≈ −0.7/−1.3 bps (cap-30min) and −0.1/+0.8 bps (cap-2h) after
  fills — no post-fill drift in our favour to capture later.
- Per-symbol: BTC fades fared worst in cap-30min (−4.3 bps gross mean on
  5 fills); ETH ≈ 0 — small samples throughout.
- Conservative fills starve the sample (55 fills / 3.5 h): this is
  indicative, not powered. A powered version is the 10-day capture and
  is predeclared here: same rules, no threshold changes.

## 2b. Continuous two-sided quoting (the "pile small spreads" test)

The strongest version of the frequency thesis: rest on BOTH sides at
the touch while idle, re-arm every cycle (3 s rest / 1 s cooldown),
capture the spread on whichever side the aggressor hits, exit at the
opposite touch. Same conservative fill rules, same accounting; second
predeclared mode of the same tool.

| capture | sensitivity | fills | gross bps | net all-maker | net actual | win % | markout 5 s |
|---|---|---|---|---|---|---|---|
| cap-30min | touch | 939 | −0.20 | −4.20 | −4.53 | 0 | −0.10 |
| cap-30min | through | 222 | −1.31 | −5.31 | −7.16 | 0 | −1.28 |
| cap-2h | touch | 3,611 | −0.11 | −4.11 | −4.41 | 0 | −0.06 |
| cap-2h | through | 563 | −1.12 | −5.12 | −7.64 | 0 | −0.99 |

Observed mechanism: the spread capture works mechanically — most fills
exit at the opposite touch (3,244 of 3,611 on cap-2h touch) — but the
minority that run away (`exit-expiry` taker exits) hand the spread
back: ≈ 90 % × +1 bp against ≈ 10 % × −10 bps ≈ zero gross. **At zero
fees (USDC-M base tier charges 0.00 % maker), net ≈ gross: still
−0.1 bps (touch) to −1.1 bps (through) per fill.** The total scales
linearly with frequency at a fixed negative sign — more fills lose
more, proportionally; the "pile up small profits" arithmetic is
correct, but on these captures the pile-up sign is negative in every
scaling (even at one tenth of the observed fill rate).

## 3. Verdict (frozen reading, no reinterpretation)

**Neither the flow-fade nor the continuous spread-pile can clear ANY
frozen cost schedule on our captures — and both are ≈ zero gross even
before fees.** Combined with the published maximum for this mechanism
family (≈1.3 bps gross vs ≥5 bps costs), the honest conclusion is:

- A retail-cost "scalp" built on flow-driven reversal is **structurally
  negative** at our size; no amount of tuning or frequency changes a
  negative per-trade sign — frequency multiplies it.
- Faster taker scalping is strictly worse (costs double; the project's
  own H-R2 counterfactual already measured −13.4 bps net per candidate).
- The only route to a positive per-trade sign for this activity found
  anywhere in the evidence is **fee rebates / VIP-tier pricing /
  sub-bp infrastructure we cannot reach** — a venue-and-capital
  problem, not a strategy choice.

## 4. What this does to the goal

The "pile small profits" arithmetic: 2–3 %/day of capital — 200–300 bps
— over 100–200 trades/day needs **+1 to +3 bps NET per trade** of
full-capital notional (more with partial notional; less only with
leverage, which multiplies losses identically). What we measured, on
our tape, with both predeclared structures:

- best gross = ≈ 0 bps (flow-fade) to ≈ −0.1 bps (continuous, touch);
- net at zero fees ≈ still −0.1 to −1.1 bps;
- net at the real schedules = **−4 to −8 bps per trade**;
- win rate 0 % everywhere; markouts confirm adverse selection, not
  edge.

So the requirement is a **sign flip of roughly 5–9 bps per trade**, not
more trades. No measured mechanism, in this repo or in the published
literature, supplies it at retail costs. The honest alternatives
(funding/basis carry, longer-horizon mechanisms, or manufacturing a
genuine fee/infrastructure edge) remain separate hypotheses with their
own preregistered rounds.

## 5. Repro

```sh
python3 tools/quick_trade_probe.py \
  --capture data/captures/cap-2h --out /tmp/qp-cap-2h.json
python3 tools/quick_trade_probe.py \
  --capture data/captures/cap-2h --mode continuous --out /tmp/qp-cont.json
python3 -m pytest -q tests/unit/test_quick_trade_probe.py
```

Determinism: both passes are pure functions of the capture bytes; no
wall clock, no randomness.

## 6. Addendum 2026-10-17: inputs deleted, outputs preserved

The five input captures were deleted in the Oct-17 storage cleanup
(see `outputs/quick-probe/README.md`). The per-capture result JSONs are
preserved frozen in `outputs/quick-probe/`; the §2/§2b tables reproduce
them exactly. The powered re-run against the fresh 1-day campaign data
(`data/captures/campaign-1day-20261017`) uses the identical frozen
rules — rerun, not reinterpretation.
