# V-008 verification record (48h directive §7, Worker 3 share)

Owner: Worker 3 (cool-amalthea). Base `60acd66`, branch `worker3/v-008`.
Contract: v0.2.0 + 48h directive (`Muse_Crypto_Six_Agent_48_Hour_Directive.md`)
§2/§7/§8. Scope per dispatch + manager scope correction (app/* is
manager-owned; Session-side wiring sent as NEEDS proposals 1/2 and 2/2 —
this diff holds risk/accounting/venues + tests only, no app/* edits).

## Per-acceptance-item verdicts

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1a | Admission inputs (available/free margin, fee buffers, in-flight) actually supplied | PARTIAL (my side done) | Engine accessor exists (`account_margin`); Session wiring proposed (exact shapes: margin[0]/None, 2·rate·available buffer, one-budget inflight); manager implements |
| 1b | Identical venue rounding across risk/submission/fills/protection | PASS | `risk/rounding.py` single rule; sizing + sim submit + protection + FakeVenue converted; risk→submit→fill→protect identity test (exact equality) |
| 2 | Funding reconciliation ledger/engine incl. mark-age; exchange-mark vs feed.mark shared with reports | PARTIAL (my side done) | Engine `valuation_mark_ts` + `settled_funding_total`; reporting mark-provenance block + CSV columns; Session preference/reconcile proposed |
| 3 | One budget across pending/open/unresolved exposure | PARTIAL (my side done) | `RiskPolicy.booked_total_qty()` (excess-over-ledger semantics); Session computation proposed; timeout-never-flat retained |
| 4 | Disabled real-venue Binance adapter contract, recorded tests only, no prod funds/keys | PASS | `adapters/binance_live.py` (default-off, testnet default, journaled, unknown-outcome lookup rule); 21 recorded contract tests; zero network/key material |

Frozen `tests/ceo_review/test_ceo_finding_*` record tests: unbroken (full
suite green, no edits to those files).

## Detail

Rounding (1b): `floor_to_step` (floor + epsilon + round-12, idempotent)
and `round_to_tick` in leaf `risk/rounding.py` (zero package imports —
adapters/execution import it, no cycle). Converted: `sizing.floored`,
`paper_engine._quantize_qty` + `_round_tick`, `attach_protection`
(floors BEFORE submit so recorded == executed), `FakeVenue` (optional
per-symbol `lot_steps`; unconfigured symbols keep legacy raw behavior so
fault tests are untouched). Nautilus fills at the submitted quantized
qty by construction — proven, not assumed, by the identity test.

One budget (3): the live-path case is the partial fill (open position +
unfilled entry remainder both draw margin). Pending (entry-role unfilled)
+ open (ledger) + unresolved excess (booked beyond ledger — booked and
ledger move together on the happy path, so only the excess prices
ledger-invisible exposure). `booked_total_qty()` tested (sum, eps→0).

Marks/funding (2): every engine mark carries observation time (markPrice
stamps exchange time); settled totals cover exactly the emitted
`EngineFunding` events (same-boundary-never-twice tested); ledger books
the emitted event and agrees. Reporting: additive `mark_source` /
`mark_age_ms` equity fields (strict when present, `unrecorded` default),
`mark_provenance` summary block (by-source counts, max age, open rows
without mark — counted loudly), new CSV columns, HTML reliability rows.

Live adapter (4): HMAC signing, time-sync with skew fail-closed,
exchangeInfo filters (LOT∩MARKET_LOT min), fee tier, one-way-mode +
margin-type + leverage verify, stable journaled client ids, conditional
stops (workingType param, venue default), enforced reduce-only exits,
cancel, openOrders TTL cache, lookup/void, user-stream parsing
(ORDER_TRADE_UPDATE fills with exact USDT commissions; ACCOUNT_UPDATE
journaled; unknown kinds loud), listenKey lifecycle, recover-via-lookup,
per-trade userTrades adoption with cumulative cross-check journaled
(fees never estimated), income-based funding total. Retry rule: UNKNOWN
blocks same-reservation submits until lookup; deterministic rejections
allow retry. `submit_protected` = LIMIT IOC at rounded cap.

## Manager-owned follow-ups (proposed, not in this diff)

- NEEDS 1/2: `PaperEngine.account_margin` on Protocol + reference None;
  Session snapshot three fields; one-budget computation; order_manager
  `_submit` flooring (or confirm it is mine).
- NEEDS 2/2: `valuation_mark_ts` on Protocol; Session mark preference
  (exchange → feed → none) + equity-row provenance; funding reconcile
  checkpoint + exit-only on mismatch. Note: markPrice replays move
  valuation to the exchange mark — flag for golden-test review.
- Live CLI/mode wiring + user-stream socket + testnet re-record of the
  `recorded-shape` fixtures (hand-built, labeled, NOT actual captures).
