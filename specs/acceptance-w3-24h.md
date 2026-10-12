# W3-24H verification record (24h activation, Worker 3)

Owner: Worker 3 (cool-amalthea). Base `3cadfca`, branch `worker3/w3-24h`.
Dispatch: 24h activation W3 (risk profile + Binance contract + restart
identities). No app/session.py edits (method proposals sent to manager);
risk changes await manager/W5 review before integration.

## Per-acceptance-item verdicts

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Versioned risk profile §4 (0.125% / 0.5% ACTION / 1% emergency / 70% floor, flow-adjusted net of costs) | PASS (policy side) | `profile_version="24h-1"`, stops on netliq, latches + `pending_stop_actions` + `recover_from_emergency`; 16 profile + 2 race tests; Session ACTION loop proposed |
| 2 | Exchange contract (algoOrder, hosts, account fields, listen-key, demo, error contract, unknown preservation, bot-only) | PASS | algo rail + triggered ids + ALGO_UPDATE, documented account fields, keyed listenKey, demo mode, `caller_action`, CANCEL_UNKNOWN, bot-only filter; 12 new recorded tests |
| 3 | Restart identities (venue/account/symbol/trade keys, rebuild, exposure block, idempotent replay) | PASS | Qualified exec ids end-to-end incl ledger; journal rebuild at construction; 4 restart tests |

Frozen `tests/ceo_review/test_ceo_finding_*` record tests: unbroken.

## Before/after probes (defects reproduced, then fixed)

BEFORE (`/tmp/w3_before.py` on base): -0.6% day Approved + healthy;
0.25% budget; no stop-action API; stops on `/fapi/v1/order`; invented
marginType/dualSidePosition; listenKey without API header; ID-777 —
cross-symbol same-trade second fill SILENTLY DROPPED (worse than a key
collision); fresh engine loses UNKNOWN/roles/reservations.
AFTER (`/tmp/w3_after.py`): -0.6% → halt:operating-stop; 0.125% budget
(12.5); actions tuple; emergency latches + persists; algo rail, no
invented fields; distinct `binance-usdm/<tag>/<sym>/<trade>` fills both
booked; demo hosts selected; rebuild restores trades/unknowns/roles.

## Contract changes for manager/W5 review

- `max_loss_budget_pct` 0.0025 → 0.00125; stops key on net_liquidation
  (net of costs), not marked; `halt:daily-loss` → `halt:emergency`
  (persistent, reconciled recovery) + `halt:operating-stop` (per-day).
- `RiskState.halt_days` → `operating_stop_days` (+ legacy mapping) +
  `emergency_latched/since` (defaults keep old files loadable).
- `RiskConfig.daily_loss_halt_pct` → deprecated alias of
  `emergency_stop_pct` (keeps app/config + old callers working until
  manager migrates; warns, conflicts raise).
- Expectation updates (same rigor, new numbers): halts (5+2 new),
  sizing/u003/v006 goldens, v004 reasons/budget, determinism,
  runtime_risk, v007 control move (-40 stays above operating stop).

## Manager-owned follow-ups (proposed, not in this diff)

- Session stop-ACTION loop + emergency recovery call (proposal 1).
- Risk config plumbing (operating/emergency/profile/mark-age) +
  paper/r2/r3.toml (proposal 2); snapshot mark_age_ms (proposal 3).
- Live `caller_action` wiring + per-tick unknown lookup +
  `stream_reconnected` (proposal 4); live config + socket host (5).
- Testnet re-record of algo shapes (triggeredOrderId field,
  ALGO_UPDATE `ti`, algoStatus vocabulary) — recorded-shape fixtures.

## Notes

- A6 (unknown block lost on restart, 24h-board) fixed by the journal
  rebuild + covered by restart tests.
- Suite warnings (67) are the intentional alias DeprecationWarnings.
