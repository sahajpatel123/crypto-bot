# Program close-out — the crypto-bot research program on frozen data

Status: **CLOSED — negative result.** Written 2026-10-25 against
`origin/live/hardening` at `8754fc4`. Docs-only: no gate, threshold, prereg,
verdict or number in this repository is changed by this file, no result, P&L or
return is computed here, no holdout byte is opened, and no line below claims a
PASS.

This document settles one question per strategy line: **is the gate decidable on
the frozen data, or is it permanently undecidable because it needs future
observations that will never arrive?** Every figure is either quoted from a
committed file with its line, explicitly marked as the operator's statement
(section 1), or shown as arithmetic derived from quoted figures (option B); none
is a new measurement.

## 1. What is frozen

**Operator statement (not in-repo evidence; do not cite these figures as
committed numbers).** Market-data collection stopped permanently at
2026-10-25T12:41Z: `com.cryptobot.recorder` is unloaded and disabled, a STOP
file sits in the recorder directory, and the daily forward jobs (`refresh`,
`c2fwd`) are disabled. The surviving archive is 473 sealed chunks, all class
DEV — there is **no HOLDOUT chunk** — 98,371,791 records, ~2.4 GiB, covering
2026-10-18T21:37:56Z to 2026-10-25T12:35:13Z, with three inter-chunk holes (the
largest 4.9 days, 2026-10-20T07:10Z → 2026-10-25T05:05Z; plus 20 min and
30 min). Trade-flow records exist only in the last 17 chunks, after the
2026-10-25 stream fix.

What the repository itself commits about that data, and what limits it:

- The recorder writes **~1.5 GB per UTC day** and stops on a free-space floor of
  **4,096 MB** (`RESUME.md:397`, `RESUME.md:270`; the floor is a free-space
  check, not a cap on its own archive — `src/cryptobot/market_data/live_recorder.py:427`).
- Trade prints were **silently absent** for the whole 18–25 Oct run until the
  fix; chunk `rec-000417-20261025T071824Z` holds zero `trade` records
  (`RESUME.md:276`–`RESUME.md:288`). Trade flow exists only after the restart
  (`RESUME.md:296`–`RESUME.md:298`).
- The recorder carries **neither a settled `fundingRate` nor `kline_1d`**
  records, so a carry study cannot charge funding and a cross-sectional universe
  cannot be ranked from it (`RESUME.md:259`).
- Liquidation history **does not exist and never did**: `forceOrder` handshakes
  and sends zero bytes (`RESUME.md:303`–`RESUME.md:306`).

The repository already carries a root `PROJECT_CLOSEOUT.md` from the
edge-sprint review; this file is the program-level close-out, it cites that
file's rules, and it does not modify it.

## 2. How to read the rulings

- **Settled negative** — the gate already failed on data that has been read.
  More observations cannot change it, and re-running it is data-snooping.
- **Decidable on the frozen archive** — could be evaluated using only the
  2026-10-18..25 DEV archive (seven days, operator-dated; section 1). **No line
  below is in this class.**
- **Permanently undecidable (in-program)** — the gate needs forward
  observations, and the program will never collect them. Where the *data source*
  is public and external (Binance Vision, section 6 option B), the study is
  resumable by re-opening work, but it remains undecidable for this closed
  program and cannot be answered from the archive.

## 3. Gate-by-gate rulings

| Line | Gate (as frozen) | Status | Decidable on frozen archive? | Decisive evidence |
|---|---|---|---|---|
| **B4** delta-neutral basis | Annualised turnover ≤ 12×; "Any miss KILLS B4" (`research/prereg/B4-delta-neutral-basis.md:68`) | **KILLED** (settled) | N/A — settled before the archive | turnover `17.05060731836767` (`research/autopilot_b/state/B4.json:949`), gate `false` (`:939`) |
| **B4b** forward basis | Verdict only at ≥90 forward days **and** ≥20 round trips; PASS only at day 121 (`research/prereg/B4b-forward-basis.md:320`–`:331`) | **UNDERPOWERED**, 0/90 days, 0/20 round trips (`RESUME.md:257`) | **No** — its own date rule excludes the whole archive (`:125`) | clock starts 2026-11-01 (`:123`); 18–31 Oct permanently outside (`:125`) |
| **C1** TSMOM (Family C) | DEV: CI95 lower > 0, 2× mean > 0, p ≤ 0.0125, positive 2022/23/24, ≥300 days; then one holdout (`research/prereg/C-family-daily.md:45`–`:53`) | **FAIL** (`reports/hypotheses/C-dev.json:14`) | N/A — settled before the archive | +9.33 bps/day, p `0.1059` (`C-dev.json:20`, `:28`) |
| **C2** XSMOM (Family C) | DEV p ≤ 0.0125; holdout p ≤ 0.05 once; replication bar p ≤ 0.01 (`C-family-daily.md:48`, `:53`; `C-family-amendment-2.md:16`) | **KILLED** (settled) | N/A — settled before the archive | DEV p `0.0195`, 2024 negative (`C-dev.json:54`, `:58`); holdout p `0.154` (`C2-holdout.json:21`); replication p `0.0805` (`C2-replication.json:23`) |
| **C2-FWD** forward XSMOM | Exactly 365/730/1,095 recorded days, each once; terminal at look 3 (`research/prereg/C2-forward-amendment-1.md:26`–`:30`) | **1 row booked**, 0/365 (`RESUME.md:404`–`:405`) | **No** | rows must accrue; membership cannot be reconstructed (`research/C2-FWD-AUDIT.md:34`) |
| **D1** OI-flush reversal | 8 gates incl. ≥300 events **and** ≥100 event days, DSR ≥ 0.80 with frozen `N` (`research/prereg/D1-oi-flush-reversal.md:285`–`:345`) | **UNEVALUATED / BLOCKED**; DSR not evaluable | **No**, and PASS is structurally impossible | `N_TRIALS = None` (`src/cryptobot/research/d1_trials.py:42`); "PASS is impossible" (`D1-amendment-3.md:45`); inputs missing (`RESUME.md:259`) |
| **R2-Family-D** | The R2 round owning D1's frozen `N_TRIALS` (`d1_trials.py:16`, `:44`) | **CLOSED without a number** | No | `D1-amendment-3.md:7`: no finite `N_TRIALS` is established |
| **R3/carry** (C1-b4b carry) | ≥90 forward days after 2026-10-17; 80% LB APR > 0, 2× APR > 0, DD ≤ 2% (`research/prereg/C1-b4b-carry.md:73`–`:82`, `:104`–`:106`) | **UNCONFIRMED**, 0 forward days | **No** — 7 days vs 90, and no settled funding in the archive | confirmation cell frozen (`C1-b4b-carry.md:51`); funding absent (`RESUME.md:259`) |

### B4 — killed, and its passing verdict is void

The frozen promotion rule is explicit: turnover ≤ 12× and "Any miss KILLS B4"
(`research/prereg/B4-delta-neutral-basis.md:68`). The corrected measurement is
`17.05060731836767` with the turnover gate `false`
(`research/autopilot_b/state/B4.json:949`, `:939`). The `SCREEN_PASS` document
`research/verdicts_b/B4.json` is **void**, not evidence: its
`document_sha256` `2974cc1a24cdc1ef99238380919a9070e271427798482a5ded351e03bda028e8`
is invalidated under D-042 and the holdout is marked **BURNED**
(`research/verdicts_b/invalidations.json:9`, `:11`, `:47`). Nothing may be
rescored: the holdout for B4 and any B4 variant is spent
(`PROJECT_CLOSEOUT.md:26`). **Ruling: settled negative. Do not reopen.**

### B4b — out of reach by its own calendar, not merely short of data

B4b needs both ≥90 forward days and ≥20 completed round trips before it will
write any verdict (`research/prereg/B4b-forward-basis.md:320`–`:323`), and a
second look needs a new prereg (`:324`–`:325`). The forward clock starts
2026-11-01 (`:123`), and the 14 days 2026-10-18..2026-10-31 are **permanently
outside this study** (`:125`) — which is the entire frozen archive. Even a
90-day look can only KILL: gate 6 needs 121 forward days, so the earliest a PASS
condition is even assessable is 2027-03-01 (`:328`–`:331`), and the committed
status is 0 of 90 days and 0 of 20 round trips (`RESUME.md:257`). B4b reads
public Binance Vision daily archives, not the recorder
(`research/forward_b4b_data_manifest.json:3`–`:8`), so this is *resumable*
(section 6B) but **not answerable from the archive**. **Ruling: permanently
undecidable in-program.**

### C1 TSMOM and C2 — the historical C family is settled

C1 TSMOM failed DEV on its own frozen bar: +9.33 bps/day with p `0.1059`
against p ≤ 0.0125, and a CI95 lower bound below zero
(`reports/hypotheses/C-dev.json:20`, `:28`; bars
`research/prereg/C-family-daily.md:45`–`:50`). C2 XSMOM failed DEV on p
`0.0195` and a negative 2024 (`C-dev.json:54`, `:58`), then failed the one-shot
holdout at p `0.154` (`C2-holdout.json:21`), then failed the stricter
replication bar p ≤ 0.01 at p `0.0805` (`C2-replication.json:23`;
`C-family-amendment-2.md:16`). The ledger records Family C **closed**
(`research/DATA_LEDGER.md:15`). **Ruling: settled negative for C1 TSMOM, C2 and
the C family.**

### C2-FWD — needs 365 days it will never get

Scoring is exactly once at 365, 730 or 1,095 recorded days, in order, with a
terminal verdict at the third look (`research/prereg/C2-forward-amendment-1.md:26`–`:30`).
The committed ledger state is **1 row**, booked 2026-10-25T05:43Z for day
2026-10-24, with the first scoring look around 2027-10-24 (`RESUME.md:404`–`:405`).
The ledger cannot be backfilled: weekly point-in-time membership comes from a
contemporaneous snapshot, and "historical membership that was never recorded
cannot be reconstructed from today's exchange metadata"
(`research/C2-FWD-AUDIT.md:10`, `:34`). Seven archived days cannot become 365
recorded days. **Ruling: permanently undecidable in-program.**

### D1 — not "waiting for data": the DSR gate cannot open

D1's gates require ≥300 events and ≥100 distinct event days
(`research/prereg/D1-oi-flush-reversal.md:299`–`:300`) and a DSR ≥ 0.80 computed
against the exact program-level configuration count (`:304`–`:317`). Amendment 3
freezes that count as **no number**: `N_TRIALS` remains `None`, DSR must not be
computed, and "PASS is impossible" (`research/prereg/D1-amendment-3.md:7`,
`:45`). The evaluator enforces this at the only place the constant lives,
`N_TRIALS: int | None = None` (`src/cryptobot/research/d1_trials.py:42`), and
renders "trial count: NOT FROZEN" (`src/cryptobot/research/d1_eval.py:2149`–`:2154`).
Independently, the recorder supplies neither settled funding nor daily klines
(`RESUME.md:259`), and the archive's 7 days cannot satisfy ≥100 event days, or
the 2020-10..2023-12 DEV window the prereg names
(`D1-oi-flush-reversal.md:444`–`:447`). Amendment 3 also refuses to adopt the
1,406 design-opportunity subtotal as a count (`D1-amendment-3.md:11`–`:41`).
**Ruling: permanently undecidable as a verdict, and no data acquisition can make
it PASS while the frozen rule stands.** This is not a data gap; it is the gate.

### The remaining historical lines, for completeness

| Line | Status | Decisive evidence |
|---|---|---|
| C3 CARRY (Family C) | **FAIL/KILLED** — −0.703 bps/day, p `0.5762`, fails gates 1–4 | `reports/hypotheses/C-dev.json:64`–`:84` |
| C4 REVERSAL | **FAIL/KILLED** — −14.95 bps/day, p `1.0` | `C-dev.json:92`–`:110` |
| H2 multi-year (H2-HIST) | **KILLED** — −17.09 bps/trade, n=6,441 | `RESEARCH_VERDICTS.md:81` |
| S pilot (prior) | **FAIL** — 0/14 cells positive | `RESEARCH_VERDICTS.md:76` |
| H-R2 (prior) | **FAIL** — −13.42 bps expectancy | `RESEARCH_VERDICTS.md:77` |
| X1 (prior) | **UNDERPOWERED** — 0 fills in 24 cells (latch) | `RESEARCH_VERDICTS.md:78` |
| H1, H3, H5 | **UNDERPOWERED** — signal-starved or negative | `RESEARCH_VERDICTS.md:79`, `:85`, `:86` |
| H2 (bar-level) | **UNDERPOWERED** — 290 trades vs 300 | `RESEARCH_VERDICTS.md:80` |
| H4, H6 | **UNDERPOWERED** — 0 trades, no evaluation artifact | `research/verdicts/H4.json`, `research/verdicts/H6.json` |

H5's liquidation-fade line is permanently undecidable in-program for a
structural reason: the venue never delivers `forceOrder`, so no liquidation
history exists to test it (`RESUME.md:303`–`RESUME.md:306`).

## 4. Label resolution — R2-Family-D and R3/carry

The literal strings `R2-Family-D` and `R3/carry` do **not** appear in the
committed prereg, verdict or resume material. The two nearest committed objects
are named below so the brief's labels are not silently redefined:

- **R2-Family-D** is the round that owns D1's trial count, not a separate
  strategy gate. The frozen module says `N_TRIALS` is "`None` until R2 sets it"
  and "the amendment that freezes `N_TRIALS` (R2 owns this file)"
  (`src/cryptobot/research/d1_trials.py:16`, `:44`). The round closed without a
  number (`research/prereg/D1-amendment-3.md:7`), so its content is exactly the
  D1 DSR row above.
- **R3/carry** is the post-closeout carry line, committed as
  `research/prereg/C1-b4b-carry.md` ("the only new hypothesis authorized after
  closeout", `:3`–`:6`). Its gate and ruling are the R3 row above. The
  *historical* carry line, C3 CARRY, is separately KILLED
  (`reports/hypotheses/C-dev.json:64`–`:84`); both are covered, so neither
  reading of the label is left unanswered.

## 5. Program-level conclusion

**The program is complete and its answer is negative.** No preregistered
strategy line in this repository reached its own frozen promotion or
confirmation bar on any data that was read, and none can be advanced on the
frozen archive:

1. **Every line that could be decided was decided against it** — B4 killed on
   turnover (`17.05` vs `12`), C2 killed on replication (`p=0.0805` vs `0.01`),
   C3/C4 killed on DEV, C1 TSMOM failed DEV, S/X1/H-R2 negative or empty, H2
   killed on 4.7 years of unseen history.
2. **Every line that was still open needs forward time, not more analysis** —
   B4b (90/121 forward days), C1-b4b carry (90 forward days), C2-FWD (365
   recorded days), D1 (a measurable event sample *and* a frozen `N_TRIALS`).
   The archive is seven days long, with a 4.9-day hole and only 17 chunks of
   trade flow (operator inventory, section 1); it cannot substitute for any of
   them.
3. **D1 is the one line where the gate itself is shut.** Even with unlimited
   future data, the frozen DSR gate cannot emit a number while `N_TRIALS` is
   `None`, and the evaluator must fail closed
   (`src/cryptobot/research/d1_trials.py:42`; `D1-amendment-3.md:45`).
4. **No PASS exists in this repository, and none is claimed here.** The gate
   remains NO-GO (`RESUME.md:252`); nothing validated is available to arm, and
   no orders, keys or live money are involved.

The honest summary is the one the repo already states: a rigorous negative
result plus a hardened system is the outcome. The program should be **closed as
a negative result**, not left "waiting for data" that will not arrive.

## 6. What remains legitimate

Only these three options are consistent with the frozen material. Anything else
— rescoring B4, reopening the holdout, re-running a read window for a better
number, or reading C2-FWD's ledger before its looks — is a gate violation, not
an option.

### A. Accept the negative result and stop (recommended, zero cost)

Close the program. Keep every prereg, verdict and threshold as committed. Keep
the holdout sealed; do not decode a holdout chunk for B4 or any B4 variant
(`PROJECT_CLOSEOUT.md:26`). Leave the recorder stopped and the forward jobs
disabled. Cost: nothing, and nothing in this repository changes except this
document and one RESUME line.

### B. Re-open collection later — exact cost

This is the only path that could ever produce a verdict for B4b, C1-b4b carry
or C2-FWD. The cost, from committed figures and stated assumptions:

- **Disk:** ~1.5 GB per UTC day (`RESUME.md:397`). A 90-day window (B4b first
  look; C1 carry) is ≈ **135 GB**; a 365-day window (C2-FWD first look) is
  ≈ **548 GB**. On top of that the host must keep the recorder's free-space
  floor of **4,096 MB** (`RESUME.md:270`), and the owner's Mac currently has
  about **12 GiB free (94% full — operator statement, not committed)**. The
  archive therefore has to live on another volume or host, not on that disk.
- **Time:** 90 days wall clock for the first B4b/C1 look; **121 days** before a
  B4b PASS condition is even assessable (`research/prereg/B4b-forward-basis.md:328`–`:331`);
  **365 days** for C2-FWD's first look (`RESUME.md:405`). From a restart today
  those dates move out by the restart delay.
- **Additional inputs that must exist first:** settled funding settlements and
  daily klines are *not* recorded today (`RESUME.md:259`), so a re-opened
  recorder needs those streams (or a daily Vision pull) before a carry study can
  charge funding or rank the universe. C2-FWD additionally needs its
  point-in-time membership snapshots from day one, because they cannot be
  reconstructed later (`research/C2-FWD-AUDIT.md:34`).
- **What it still cannot buy:** D1. No amount of new data opens a DSR gate that
  is frozen to `None` (`D1-amendment-3.md:45`). Liquidation history is also
  unavailable on this venue feed (`RESUME.md:303`–`:306`).

### C. Re-scope to questions answerable from seven days of DEV data

Legitimate, but only as **descriptive** work with a new, explicitly descriptive
preregistration — never as a promotion path. Within the frozen gates, seven
days on two symbols cannot meet any economic bar here: the shortest is 90
forward days (`C1-b4b-carry.md:73`–`:76`), the Family C DEV floor is ≥300 scored
days (`C-family-daily.md:50`), and D1 needs ≥300 events and ≥100 event days
(`D1-oi-flush-reversal.md:299`–`:300`). What the archive can honestly support:

- **Data-quality and plumbing audits** on the 473 chunks (operator inventory,
  section 1): per-chunk stream
  coverage, the three holes, and the pre/post-fix trade-flow boundary — the same
  kind of count-only evidence `RESUME.md:276`–`:300` already records.
- **Recorder-health bookkeeping** for C2-FWD, which its own prereg allows
  ("the ledger may be checked only for recorder health (days recorded, gaps)",
  `research/prereg/C2-forward.md:28`–`:29`) — never significance.
- **Descriptive capital-feasibility tables**, e.g. C1's 120/1,000/10,000 USDT
  table at observed prices (`C1-b4b-carry.md:93`–`:99`), which is not a return
  claim.
- **Event-count feasibility (stage-0 style)** for D1 or C1 on two symbols over
  seven days, reported as counts only, with the explicit statement that it
  cannot be scaled into a verdict.

Any question about profitability, edge or promotion is **not** answerable from
this archive, and a re-scoped study that proposed one would be a new
information source with a new preregistration — not a continuation of this
program (`PROJECT_CLOSEOUT.md:34`).

## 7. Boundary of this document

- No holdout byte was opened, listed or decoded; this file is built from
  committed text and JSON only.
- No gate, threshold, prereg, verdict, manifest or number was edited. The only
  changes in this PR are this file and one appended milestone line in
  `RESUME.md`.
- No return, P&L, expectancy, Sharpe or new statistic is computed here; every
  figure is quoted from the named committed file, marked operator-provided
  (section 1), or shown as arithmetic derived from quoted figures (section 6B).
- Not verified, and not claimed: the operator's post-12:41Z machine state
  (launchd unload, STOP file, disabled jobs), the byte-level archive inventory
  (473 chunks / 98,371,791 records / ~2.4 GiB / the three holes), and the
  untracked `data/forward_c2/ledger.jsonl` row itself. The committed evidence
  for the C2-FWD row count is `RESUME.md:404`–`:405`; the archive figures above
  are the operator's statement, marked as such.
