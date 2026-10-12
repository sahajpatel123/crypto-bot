# V-006 verification + hardening record (Bot v0.1 runtime)

Owner: Worker 3 (cool-amalthea). Base `d5bfbd0`, branch `worker3/v-006`.
Contract: v0.2.0 + `specs/app_runtime_interfaces.md` S4.

## Per-acceptance-item verdicts

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | V-005 continuation: retained capture + cap-2h + replay agreement + S5 inventory | PASS | §V-005 below; 4/4 file hashes match; replay sha exact |
| 2 | Strict metadata enforcement mandatory in run mode | PASS | `run_mode` + complete-record + fresh-asof gates; 4 tests |
| 3 | Margin-aware sizing (available/free + fee buffer + in-flight; cap not a substitute) | PASS | cap-down + recheck + `margin:insufficient`; 4 tests |
| 4 | Real commission/funding ingestion; fee=0 fault-test-only; early publish | PASS | `note_fill`/`note_funding` on ledger + policy router; published to manager pre-filing; 5 tests |
| 5 | Equity agreement after partials/reversals/funding/restart/midnight/halt | PASS | journal replay + scenario tests; agreement asserts throughout |
| 6 | Timer-driven `monitor_tick` independent of traffic | PASS | account-optional tick + persisted `last_tick_utc`; 3 tests |
| 7 | Idempotent event IDs; stale callbacks never clear newer exposure | PASS | exec-id dedupe + race-order tests (release/flat/late-delta) |
| 8 | Independent runtime regressions + early publish | PASS | `tests/ceo_review/test_runtime_risk.py` (7 scenarios); signatures published |

Frozen `tests/ceo_review/test_ceo_finding_*` record tests: unbroken (full
suite green, no edits to those files).

## V-005 continuation detail (read-only)

Retained capture (all hashes independently recomputed, match manifests):

| File | sha256 (prefix) | Match |
|---|---|---|
| cap-30min/events.jsonl (611979689 B) | 76c9137f…8792e | YES |
| cap-30min/bars.jsonl (1095832 B) | ceff7d3c…013c8 | YES |
| cap-2h/events.jsonl (1548306631 B) | 2f1b5cc6…117c4 | YES |
| cap-2h/bars.jsonl (4224040 B) | 0ef323f1…1bec | YES |

Numeric replay agreement (independent, main-line `tools/replay_stream.py`):

- cap-30min: 1129445 events, sha
  `129f0f55b095847642531dcbab30e9f704dec4015c5c7e9396b18b82dad9a581`
  (EXACT match to E-006 outbox), 3597 windows, 3283 bars + 314 missing,
  rebuild agrees, empty diffs both ways.
- cap-2h: 2838861 events, sha
  `e11655d9675840e3bf4f5670e9dece84e2fc110cb6154b122851d782cd22b116`
  (established by this check; no prior claim existed), 14398 windows =
  12420 bars + 1978 missing, rebuild agrees, empty diffs both ways.
  Method note: the stock `replay_stream.py` loads the 1.5 GB file 2–3×
  into RAM and swap-thrashes past 30 min; this check streams with
  identical definitions (validated byte-identical on cap-30min, including
  its pinned sha). Recommend a streaming replay for large runs (finding
  for the tool owner; `tools/` is outside V-006 scope).

cap-2h result: 22:17:40Z–00:17:41Z (full 2h), `duration-reached`, 2838861
events, 0 malformed/dup/ooo, 0 natural/injected gaps or disconnects, both
books synced (140846 depth applied, 0 resyncs), claim boundary present
(no exec-latency claim).

Fresh S5 inventory (vs `S5_RULING.md` UNAVAILABLE at `ea4fa9d`):

| Required | Then | Now | Evidence |
|---|---|---|---|
| Trade-level flow synced to bars | NO | YES | aggTrade channel (venue_seq, 65k+ events) + `buy_volume` per 1s bar |
| Depth synced to bars | NO | YES | depth@100ms + bookTicker, synced books, `depth.py` module |
| 1s (or finer) causal bars | NO | YES | strict 1000 ms grid (2000/2000 BTC steps), watermark + gap flags |
| Sustained capture with gap flags | PARTIAL | YES | 2h clean soak + 30min chaos soak, manifests + reports |

`specs/depth_flow_availability.md` (E-007 early publish) does not exist yet;
the S5 ruling update itself is manager/W1's call. S5.md remains a draft
hypothesis note. No profitability claim is made or implied.

## Compatibility notes (backward-compatible hardening only)

- `AccountSnapshot` margin fields optional (`available_margin_usdt=None`
  skips the margin gate; leverage cap still applies).
- `RiskConfig.run_mode` defaults False (fault-test behavior unchanged);
  `InstrumentFilter` keeps `(min_notional, qty_step)` positional order.
- `note_fill`/`note_funding` are append-only ledger additions; existing
  `record_*` behavior unchanged (journal `symbol` defaults to `""`).
- Risk-state v2 preserved (`last_tick_utc` defaults None; no migration
  bump needed).
- Tick placement for order prices stays execution-side; risk requires the
  tick field present in run-mode records but does not place orders.

## Unresolved

- Tick-level order-price alignment enforcement (execution-side, E-007).
- `depth_flow_availability.md` pending (E-007 early publish).
- S5 ruling update pending (manager/W1 decision on this inventory).
