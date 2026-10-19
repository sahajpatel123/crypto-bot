# Project final report

This repo is a research system for a cost-adjusted crypto edge. It
downloads public Binance data, scores preregistered hypotheses, and
refuses live capital unless a machine gate is GO and a person arms it
at a terminal. No order path was used in this closeout.

## What was learned

Family B tested 59 cells on DEV data (before 2024-01-01). All seven
hypotheses were killed. The nearest statistical results still missed
a frozen gate: B4's best out-of-sample Sharpe was about 4.4 with
turnover 17.05 against a budget of 12; B6's Sharpe was about 1.23
with PBO, plateau, and turnover all short of the anchors. A holdout
screen that looked like a pass for B4 was void. It came from a book
clipped to 25% per leg (D-042). Its document hash
`2974cc1a24cdc1ef99238380919a9070e271427798482a5ded351e03bda028e8`
is on the invalidation chain. Re-running B1 and B6 from
`data/lake/dev` matched the committed DEV statistics exactly
(`release/rederive.log`).

Family A (H1–H6) was scored on the read-only pilot (29 days) and
`datasets/benchmark_30d.toml` (aggTrades, funding, 1-minute marks).
The pilot manifest says there is no quote channel. The benchmark
says book views are never synced. There is no Bybit, OKX, or
liquidation history. `estimate_power` on an empty trade list returns
IMPOSSIBLE, "fewer than 2 dev trades", with no day count. They stay
UNDERPOWERED / AWAIT_DATA.

Family C is one pre-authorized carry hypothesis, C1 (B4b). The
prereg was committed before any forward read. The holdout is burned.
Confirmation is allowed only on data dated after 2026-10-17, and
only after 90 such days. That window has not started in the bucket:
the newest listed filename date is 2026-10-17.

## Decision clock

T0 is the first sealed recorder chunk,
`2026-10-18T21:42:56.700228Z`. T is T0 plus 90 days
(2027-01-16). `cryptobot adjudicate` is WAITING. At T, anything
still AWAIT_DATA or otherwise unfinished becomes NOT_ESTABLISHED
and counts as no edge. If every hypothesis is already terminal, it
stops early.

| Final state | What happens |
|---|---|
| ARCHIVE_NEGATIVE | Every hypothesis is KILLED, FAIL, IMPRACTICAL, or NOT_ESTABLISHED. Launchd jobs unload, the recorder stops, `FINAL_VERDICT.md` is written, a macOS notification is posted. |
| PAPER_ONLY | At least one PASS, and the gate is not GO. Those hypotheses stay in paper for 30 more days. No live orders. |
| READY_FOR_HUMAN_DECISION | The existing gate returns GO. A notification is posted. The program does not arm. |

A SYNTHETIC artifact cannot produce any of those three outcomes.

## Hypothesis state

| Id | State |
|---|---|
| H1–H6 | AWAIT_DATA (UNDERPOWERED) |
| B1–B7 | KILLED |
| C1 | AWAIT_FORWARD |

## Costs and risks

The recorder, on this Mac, used about 9.9% of one core and 58 MB/hour
(`RECORDER_COSTS.md`). At that rate the free disk covers about 12
days before the 8 GB guard stops it. The scientific risk that
remains is treating a void or a short sample as an edge. The
invalidation chain, the burned holdout, and the 90-day forward
floor are what prevent that. B4's high Sharpe was funding on a
hedged book, and the frozen turnover rule killed it.

## Owner only

The software does not decide whether you may use the venue from
your jurisdiction, or how gains and losses are taxed. Those two
questions are yours, with your own counsel, before any arm.

## How to extend

A new idea needs a new preregistration and a new information source.
It does not get to reuse the burned B4 holdout. Capital stays off
until `cryptobot gate` is GO and you arm it yourself on a TTY.
