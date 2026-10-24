# C2-FWD — amendment 1: group-sequential design (prereg)

Committed before the first forward record (`data/forward_c2/` does not
exist on any host yet), so this changes the design, not a result.

## Why

`tools/quant_report.py` (reports/quant/C2-quant.json) measured C2's
historical daily series: annual Sharpe ~0.98 pooled, kurtosis 15,
worst day −1,619 bps, historical max drawdowns 2,658–3,785 bps. At
that Sharpe the original design was a coin flip weighted towards
failure even if the edge is real:

- 180-day fixed test at p <= 0.05: power 17%.
- Its pass rule "max drawdown < 2,500 bps" fails on every one of the
  three historical periods, i.e. it would reject the edge as measured.
- 80% power needs ~2,356 days (6.5 years) in a single fixed test.
- An anytime-valid betting e-process with a loss bound covering the
  worst historical day reaches only ~19% power in 3 years.

## Design (replaces "Scoring" in C2-forward.md)

Universe, rules, costs, funding, recorder: unchanged.

Primary hypothesis H0: mean daily net (1x cost) <= 0 for C2.
Looks at exactly 365, 730 and 1,095 recorded days
(`tools/forward_c2.py score --look K`, each look once, in order). At
look k compute the week-block bootstrap one-sided p of the first
N_k days, z = Phi^-1(1 − p), and stop with FORWARD-PASS if
z >= b_k AND mean at 2x adverse cost > 0, where the one-sided
O'Brien-Fleming bounds for overall alpha 0.05 are
b = (2.973, 2.102, 1.717) (`quant.obf_bounds(3)`). Not crossing at
look 3 = KILLED, permanently. Power at the measured Sharpe ~51%;
at half the measured Sharpe ~21%. That is the honest price of a
Sharpe ~1 edge; no design shortens it without a higher-Sharpe signal.

Drawdown is reported, not a pass criterion (paper trading risks no
capital). It governs sizing instead (below).

Secondary (fixed-sequence gatekeeping, no alpha split): only if C2
passes at some look, C2-VM — the same ledger vol-targeted to 150 bps/day
(EWMA half-life 20 over the trailing 120 days, 20-day warm-up at 1x,
leverage cap 2, leverage changes charged 9 bps per unit) — is tested
with the same bound at that look. Its historical Sharpe gain
(1.02/0.83/1.08 → 1.05/1.05/1.25) was found on read data and is a
hypothesis only.

## Sizing if (and only if) it passes

Leverage = `quant.drawdown_capped_leverage` on the forward data's
1-sd lower-bound mean, with P(drawdown >= 20%) <= 5%. On history this
gives ~0.2x gross — expected ~4% a year. Any live step still requires
the multi-position runtime, demo drill, latency check, gate and arm.

`health` reports coverage and which looks are due — never statistics.
