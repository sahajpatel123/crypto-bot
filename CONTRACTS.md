# Shared contracts v0.1.0 (manager-owned; only manager edits)

## Intent schema (immutable, all strategies → coordinator → risk → execution)

Required fields:
- strategy: string, e.g. "S1"; version: string, e.g. "0.1.0"
- instrument: string, Binance USDT-perp symbol, e.g. "BTCUSDT"
- side: "LONG" | "SHORT"
- evidence_ts_utc: ISO-8601 UTC timestamp of the last causal observation used
- entry_low, entry_high: float price bounds; entry_expiry_utc: ISO-8601 UTC
- invalidation_price: float; exit_rule: string identifier + params
- holding_limit_s: int (usual 30-300; emergency exits may be sooner)
- forecast_cost: {fee_bps, spread_bps, slippage_bps, funding_bps} all >= 0, labelled
  conservative-simulation until account fee lookup exists
- evidence_ref: string pointer to decision record (no hand-assigned confidence %
  as win probability)
- data_quality: "clean" | "degraded" | "halt" with reason

Invariants: evidence_ts_utc <= entry_expiry_utc; entry_low <= entry_high;
invalidation on the loss side of entry bounds; holding_limit_s > 0.
Intents are immutable once created (frozen dataclass / mapping).

## Decision record

Each intent carries a causal explanatory record: regime label, features with
windows/thresholds, trigger clause, reject checks evaluated, and data-quality
state. Long/short evidence separate.

## Coordinator rules (initial)

- One execution service owns orders. All intents flow strategy → coordinator →
  risk gate → order manager.
- Duplicate same-symbol/same-direction: single owner, deduplicate, no size multiply.
- Opposing qualified signals: stand aside initially.
- Open position keeps owning exit policy; only global risk/health overrides exit.
- Stale/expired/invalid-cost intents rejected with reason.

## Risk gate interface (Worker 3 implements; manager reviews)

`evaluate(intent, account) -> Approved(reserved_risk, notional_usdt, qty) | Rejected(reason)`
(matches the reviewed V-001 surface; turn-41 audit fix).
Must enforce: planned-loss sizing incl. stressed costs, leverage/margin/exposure,
minimum-size skip, one-position incl. reservations, daily halt/target pause,
profit-protection upward-only persistence, health blocks. Reservation atomic.

## Execution interface (Worker 2 implements)

Order manager owns client IDs (unique), entry expiry, partial fills, stop/target
sibling handling (no assumed atomic bracket; verify conditional endpoints), exit-only
behaviour, reconciliation before retry of ambiguous orders, restart recovery.
Fake venue for M1 must support fault injection (timeout, partial fill, reject).

## Ledger/reporting

Primary USDT; UTC raw, Asia/Kolkata day. Marked equity (incl. open P&L, paid
costs) and net-liquidation estimate (projected close costs) kept distinct.
Deposits/transfers partitioned, never profit. Daily target fractions computed on
ALL calendar days, with trading-active split shown separately.

## Versions

Contract v0.1.0. Task messages cite this version. Breaking changes require a new
version + manager-approved migration of worker code.

## Addendum v0.1.1 — risk→execution handoff (D-007; closes F-E001-01/U-002)

Status: interface defined by manager; implementation follows in E/V follow-up
tasks. v0.1.0 remains the implemented baseline until those land.

- `Approved` carries `reservation_id: string`, unique per approval (the V-001
  policy already returns this shape).
- `submit_entry(..., reservation_id)` threads the reservation key into the
  order manager; the manager records the key on the entry order and its
  protective siblings.
- Outcome callbacks into risk, exactly-once per reservation: `note_fill`
  (entry filled → reservation converts to open-position state), `release`
  (cancelled/expired/rejected → reservation freed), `note_flat` (position
  flat → open-position cleared). No callback path may strand a live
  reservation past entry expiry.
- Halt → exit-only signal: when risk engages a daily halt, profit-protection
  breach, or health block that forbids new entries, execution enters exit-only
  mode (no new entries; protective exits and exposure reduction proceed). The
  signal is level-triggered and persists across restarts until risk clears it
  via reconciliation.
- Restart reconciliation covers reservations: any reservation without a
  matching live entry/order after recovery is released with a logged reason.
- Code: `cryptobot.coordination.RiskOutcomeSink` (manager-owned Protocol).
  E-003 stubs and the future V-001 wiring both conform to it; signatures
  mirror the V-001 policy surface (release → bool, note_fill(id),
  note_flat()).

## Addendum v0.2.0 — fill-delta propagation (MG-001; F-CEO-02/03 seam)

Status: PUBLISHED by manager. V-004 implements the risk/ledger side, E-005
the execution side. Supersedes v0.1.x callback semantics only where stated.
Protocol code update lands at integration with both sides.

- New sink method (risk implements, execution calls):
  `note_fill_delta(reservation_id: str, exec_id: str, symbol: str,
  venue_side: str, qty: float, price: float, fee: float, ts_utc: str) -> None`
  - Execution calls it for EVERY new fill increment (partial or full),
    at-least-once per exec_id. `venue_side` is "BUY"|"SELL"; `ts_utc` is an
    ISO-8601 UTC timestamp; `fee` is the venue-reported fee for this
    increment (0.0 on venues that model no fee, labelled as such).
  - Risk/ledger books idempotently keyed by exec_id: duplicate delivery is
    ignored, never double-charged. First booked nonzero delta for a
    reservation marks exposure.
  - Rejects (before booking): nonfinite/negative qty/price/fee, unknown
    venue_side, naive/non-UTC ts (extends F-CEO-07 validation).
- `note_fill(reservation_id)` redefined: fires exactly-once on the FIRST
  nonzero fill (partial or full), converting reservation → open-position
  state. The first increment is ALSO delivered via note_fill_delta (delta
  first for booking, then the transition). Never call note_fill for a
  zero-fill reservation.
- `release(reservation_id) -> bool` tightened: execution may call it only
  when lifetime fills == 0 AND no live/ambiguous/settling orders remain for
  the reservation (reconciliation-proven). Risk returns False — retaining
  the block — when booked deltas show nonzero open exposure or the id is
  unknown; True only when a live reservation was actually freed. An expired
  reservation with booked exposure is NEVER silently purged; flat booking +
  reconciliation lifts the block.
- `note_flat()` retained: risk clears open-position state only when booked
  exposure reconciles flat (net-zero).
- Exec identity: OrderManager mints one exec_id per fill increment, unique,
  persisted in the order log (fsync) BEFORE the sink call, stable across
  recovery, and traceable to its client_id. Format at execution discretion.
- Execution-local (no contract change, W2 tests): expiry settle window —
  expired entries are re-reconciled until the window passes fill-free; late
  fills are booked and protected. Overfill residual: exit fills beyond entry
  fills are booked truthfully, logged, and freeze further exits for that
  reservation; full prevention needs venue-side OCO (documented residual).
