# 24-Hour Execution Directive — Completion Summary (partial by owner stop order)

Tip at writing: `a890b19` (suite 949 passed + 1 skipped, 0 xfail).
Handoff commit: see log (this file).

## 1. Status

All six reproduced snapshot/exchange-recovery defects fixed and proven.
Streaming Session replay, supervision/watchdog, bounded protected entries,
revised daily-loss/profit-floor actions, and the F-W5R1 four-budget sizing
rule are implemented, tested, and integrated on main. Protected paper ran
2h clean on live public data. The 30-day benchmark completed 4/21 cells
(COMBINED + CASH on validation and test) before the owner/CEO stop order;
dev cells and 15 singles are missing with a preserved resume path (~10h).
No real-capital activation; live trading remains disabled (demo-only guard).

## 2. Software decisions

- **Snapshot causality (P1) + live sync honesty (P2) + ingest resync (P3).**
  In-loop causal snapshot install with clock+tolerance defense; honest
  live prime via sync_report; chain-break resync reaction. D1/D2 probes green.
- **Streaming Session replay first**, serialized shared-file queue (W1, then
  W2/W3/W4). FIFO==file parity proven (metrics + stream hash + fills + curve).
- **Watchdog supervision (manager).** Engine clock advances on every live wake
  (idle heartbeats included — queued submissions stalled without this);
  60s stream-stall detector with P3-style book resync; bounded live drain;
  serialized evidence log. Rejects/refreshes stay timeout-bounded.
- **Price-protected IOC entries (directive L76).** Session routes economic
  entries through submit_protected capped at the intent band, side-aware
  tick rounding (new floor/ceil_to_tick), window-bound expiry; reference
  engine keeps MARKET via explicit fallback. Consequence: on fast rips the
  2bps band is dead on arrival and the IOC honestly cancels (proven
  cap-vs-book); no tuning was done to recover fill rates.
- **Four-budget sizing (F-W5R1, valid W5 finding).** Policy computes
  remaining-daily + fee-netted floor cushion; sizing takes the min and skips
  on exhaustion. Margin/minimums stay gates. W5 probes pass unmarked.
- **F-W1B1 (benchmark crash).** Nautilus flags every limit fill MAKER;
  an IOC resting across 1/s modeled-quote iterates filled late and crashed
  the taker-only guard. Ruling: IOC-only relabel to taker (taker costs,
  journaled, counted, S3-listed); non-IOC still fail-closed; no staleness
  guard (pending-fill blindness; revisit if relabels exceed 1% of fills).
  Proven on the 10-min crash window (fill 08:39:44.476, relabel=1; pre-fix
  crashes identically). Original crash artifacts lost to relaunch cleanup
  (declared gap); window repro + fix commit stand as evidence.
- **§12 gap-bar crash.** Live paper exposed unguarded None bars in
  anomaly inputs; fixed + regression-tested.
- **Mixed-SHA attestation (4 standing cells bdb2f61, new work 5fc611e+).**
  Verified both sides: relabel branch never executed in standing cells
  (would have crashed them); gap-bar code never runs with
  events_enabled=false (benchmark configs); repro change comment-only.

## 3. Economics decisions

| Cell | Equity | Net | Intents | Fills | Events | Costs |
|---|---|---|---|---|---|---|
| COMBINED validation | 119.63 | -0.306% | 13 | 22 | 16.34M | 0.318 |
| COMBINED test (once) | 119.91 | -0.077% | 1 | 2 | 14.75M | 0.027 |
| CASH validation/test | 120.00 | 0.000% | 0 | 0 | same streams | 0 |

- CASH baseline first, no tuning: all strategy params frozen (2bps bands,
  300s cooldown). Test split scored exactly once per armset.
- Funding 0.0 everywhere is honest: positions hold minutes (600s time exits),
  never spanning 8h funding boundaries.
- Protected entries structurally reduce fill rates vs MARKET-chasing;
  reported as measured, not tuned away.
- Cross-armset stream hashes identical per split (val 54a66272.., test
  c398a752..); engine=ledger=report reconciled to 1e-6 (W5 20/20 + manager
  independent run, exit 0).
- No profitability claim: n=1 test intent cannot support one. Owner's
  2–3%/day objective vs measured −0.08% test / −0.31% val: NOT MET on this
  evidence; further research (dev + singles + new edges) required.

## 4. Operational decisions

- Protected paper 2h (paper-protected.toml): 8.59M events, 4 admitted,
  6 fills, −0.086%, flat, exit 0, zero stalls/halts. Run dir: runs/paper-24h-long.
- Keep live trading disabled; demo-only guard stands. AlgoOrder rail,
  demo hosts, and API-key transport verified present but NOT drill-certified
  (owner credentials required; drill still blocked).
- Evidence archived: reports/benchmark-24h-final/ (4 cells + matrix.json +
  manager reconciliation). Coordinator filings: coord/outbox/W*.json.
- Resume path: W1 runner resumable (cell.json skip); remaining 2 dev cells +
  15 singles ~10h at 3-way on 5fc611e+. Dev cells must precede any test
  reinterpretation; test cells already banked must NOT be re-scored.

## 5. Remaining blockers (honest)

1. Benchmark partial 4/21 by owner stop order (dev + singles missing).
2. Demo drill blocked on owner credentials (unchanged).
3. Oct funding re-freeze deferred (raw re-download infeasible); Sep–Oct
   backfill complete (125 settlements/symbol, provenance SHAs).
4. Old-vs-new risk-profile comparison: versioned 24h-1 shipped; head-to-head
   cells deferred to the resume (dev-only comparison proposed).
5. N3 (W5 note): paper run dirs should record source config path+sha
   (report carries only the fingerprint).
