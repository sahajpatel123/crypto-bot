# Sandbox drill report

verdict: **PASS**
seed: 7
symbol: ETHUSDT
sandbox: SANDBOX VALIDATED
demo: BINANCE DEMO VALIDATION PENDING

## Phases

- preflight: 0
- drill: 0
- interrupt: 0
- resume: 0
- stream-gap: 0
- reconcile: 0

## Evidence (latest per phase)

- [PASS] drill/ambiguous-submit: UNKNOWN sandbox-000001-ea26 resolved; 1 submit intent, 0 open leg(s); no duplicate
- [PASS] drill/entry-ioc: sandbox-000001-4590 -> filled filled=0.002
- [PASS] drill/protection: stop leg sandbox-000002-b06d state=open in 0.0s
- [PASS] drill/quote-fresh: quote age 0.0s
- [PASS] drill/reduce-only-exit: flat in 0.3s (net=0.0)
- [PASS] drill/stream-heal: sandbox stream healed in 0.0s
- [PASS] interrupt/crash: state persisted; process 'died' with venue exposure unadopted
- [PASS] interrupt/exposure: venue exposure +0.00200000 ETHUSDT unadopted (ledger flat, queue holds the TRADE)
- [PASS] interrupt/restored: ledger_net=0.0
- [PASS] preflight/account: virtual available=10000.0 free=10000.0
- [PASS] preflight/clock: sandbox server skew 0ms (seed 7)
- [PASS] preflight/fees: taker=5.0bps (sandbox fixture)
- [PASS] preflight/mark: ETHUSDT mark 2499.875
- [PASS] preflight/quote-fresh: quote age 0.0s
- [PASS] preflight/readiness: filters+fees cached for ETHUSDT
- [PASS] reconcile/ledger: ledger_net=0.0
- [PASS] reconcile/order-sandbox-000001-4590: venue state=filled
- [PASS] reconcile/order-sandbox-000001-6fe6: venue state=filled
- [PASS] reconcile/order-sandbox-000001-8738: void(zero-fill, venue-rejected-at-submit)
- [PASS] reconcile/order-sandbox-000001-ea26: venue state=cancelled
- [PASS] reconcile/order-sandbox-000001-edc0: venue state=filled
- [PASS] reconcile/order-sandbox-000002-b06d: venue state=cancelled
- [PASS] reconcile/order-sandbox-000003-71b6: venue state=cancelled
- [PASS] reconcile/order-sandbox-000004-d339: venue state=cancelled
- [PASS] reconcile/order-sandbox-000005-5dc8: venue state=cancelled
- [PASS] reconcile/order-sandbox-000006-1d30: venue state=filled
- [PASS] reconcile/unknowns: unknown=[]
- [PASS] reconcile/venue-open-orders: open=0
- [PASS] reconcile/venue-positions: nonzero=[]
- [PASS] resume/adopt: fresh objects resumed run sandbox-drill: ledger_net=0.002 store_events 7->8
- [PASS] resume/adopt-sweep: looked up journaled orders (7 live)
- [PASS] resume/close: net=0.0
- [PASS] resume/durability: 0 journaled fills missing from store
- [PASS] resume/fill-adopted: ledger_net=0.002 store_events 7->8
- [PASS] resume/heal: sandbox stream healed in 0.1s
- [PASS] resume/legs-unexpected: no legs journaled-live or resting (pre-protection crash, as designed)
- [PASS] resume/restored: ledger_net=0.0
- [PASS] resume/shell-rebuilt: shell recovered for sandbox-000001-edc0 (venue filled 0.002; drill-side recovery, W1 D2 owns session-level)
- [PASS] resume/unknowns: unknown=[]
- [PASS] stream-gap/entry-refused: exit-only: entries refused
- [PASS] stream-gap/exit-works: exit reached venue (venue verdict: VenueRejectedError('venue http 400 code=-2022: sandbox: ReduceOnly Order is rejected'))
- [PASS] stream-gap/halt: entries halted 0.0s after socket drop
- [PASS] stream-gap/heal: healed in 0.0s
- [PASS] stream-gap/reheal: halt released after heal in 0.1s
