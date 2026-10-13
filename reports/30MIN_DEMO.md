# Bounded 30-minute credentialed demo drill (W5, 30min §9)

One command, hard-bounded, honest verdicts. Owner credentials stay local;
missing pieces BLOCK (declared) instead of failing or faking.

## The one command

```bash
python tools/run_budget.py --budget-s 1500 \
    --checkpoint-dir /tmp/demo30/ckpt --report-out /tmp/demo30/report.json \
    --heartbeat-s 30 -- \
    python tools/audit/demo_drill.py --dir /tmp/demo30 --symbol BTCUSDT full
```

Budget: 1500s wall. Entry cutoff minute 20 (no new entries after).
Closure by minute 25. Overrun exits INCOMPLETE (124), never PASS.

## Minute plan

| Min | Step | Command / action | Pass criteria |
|-----|------|------------------|---------------|
| 0–3 | Preflight | `demo_drill.py preflight` | server skew <5s, readiness cached, balance >0, fees + filters read, live mark |
| 3–8 | Entry + IOC outcomes | `demo_drill.py drill` (phase 1) | tiny IOC entry reaches exactly one terminal state; cancel-or-fill observed, no rest-and-revive |
| 8–12 | Protection + reduce-only exit | drill (phase 2) | stop leg attached after fill; reduce-only exit closes flat; no flip |
| 12–16 | Ambiguous submit | drill (phase 3) | dropped order response raises UNKNOWN; lookup resolves; exactly one venue order (no duplicate) |
| 16–19 | Restart adoption | drill (phase 4, fresh PID) | new process recovers journal; unknowns/open adopt; no new entries during reconcile |
| 19–20 | Stream gap | `demo_drill.py stream-gap` | BLOCKED until CLI user-stream reader exists; then rotate + adopt check |
| 20–25 | Closure + agreement | `demo_drill.py reconcile` | venue open orders empty, unknowns empty, every journaled order terminal on venue, journal flat |

No new entries after minute 20 for any reason. If closure cannot finish
by minute 25, the run is INCOMPLETE (flatten via venue UI if needed and
record the incident handoff below).

## Preconditions / declared blockers (not failures)

- `BINANCE_DEMO_KEY` / `BINANCE_DEMO_SECRET` absent → BLOCKED. Owner
  configures locally; keys never touch chat, files, or commits.
- Demo hosts unreachable → BLOCKED with the transport error.
- `stream-gap` → BLOCKED until the CLI user-stream reader integration
  lands (manager/CLI scope); the drill detects this itself.
- Any base_url other than `https://demo-fapi.binance.com` is REFUSED.

## Abort criteria (stop the drill, keep evidence)

- Any FAIL verdict (non-demo host, duplicate order, non-flat end,
  venue/journal disagreement).
- Entry cutoff reached with an open position that cannot close by min 25.
- Venue outage: cancel via venue UI, record incident handoff, file evidence.

## Evidence produced

- `/tmp/demo30/drill_evidence.jsonl` — per-phase PASS/FAIL/BLOCKED + detail.
- `/tmp/demo30/drill_journal.jsonl` — engine journal (submits, fills,
  cancels, unknowns, recovery).
- `/tmp/demo30/report.json` — run_budget record (elapsed, budget, status).

Reconcile step replays venue state (open orders, per-order lookup,
unknowns) against the journal; journal net must be flat and every
order terminal. Exchange/ledger agreement is a venue-vs-journal
comparison, not self-comparison.

## Safety notes

- Single symbol, min-notional × 1.2 sizes, demo hosts only (hard-coded
  refusal otherwise).
- Fault injection is local and bounded: one dropped order response,
  one process restart. No firewall surgery, no venue-side chaos.
- This drill does not certify unattended operation or production
  readiness; see §9 gates. Owner present for first activation.
