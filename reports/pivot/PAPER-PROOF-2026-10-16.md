# Paper execution proof (2026-10-16)

`cryptobot run --mode paper --config configs/paper-protected.toml
--duration 120s --run-id paper-proof-1` → rc 0.

- 89,935 live venue events streamed through bridge → session →
  Nautilus paper engine; 0 intents admitted, equity 120.00 → 120.00.
- Full run evidence under `runs/paper-proof-1/` (untracked):
  report.json/md, ledger, order manager journal, paper engine journal.

What this proves: the live paper path (public streams, no creds,
simulated fills) runs end to end without errors. What it does not
prove: any strategy edge — 2 minutes with zero admissions is
mechanics evidence only, and a longer paper run is needed before any
behavioral claim. No orders touched any venue.

## 10-minute session (paper-proof-10m)

452,203 live events, 0 admitted, equity flat, 0 fill bytes. Final
rejection tally (18,230 total, all 5 strategies, 8 symbols):

- 9,932 `strategy:gap:fail` — feed gap windows on quiet markets.
- 4,652 `strategy:history:fail` — insufficient warmup history.
- 3,646 `strategy:book:never-synced` — order book never synced in-run.

Every rejection is data-readiness, none is strategy merit: in a 10m
cold-start window the strategies never reach an evaluable state. Two
consequences: (1) short paper sessions cannot produce behavioral
evidence about edge — only warmup evidence; (2) the persistent
`book:never-synced` across a full 10 minutes is filed as a Z2 data
question for the execution lane (book snapshot+diff startup on live
streams), since quote-dependent logic cannot run until books sync.
Mechanics evidence only; no profitability signal either way.

## FIXED: dynamic-discovery book priming (same day)

Root cause (traced, then fixed): with `symbols = []`, the bridge
discovered 8 symbols itself while the session primed books only from
its empty config list (`_prime_live_books` → skipped
"dynamic-symbols"), with no late-prime path — books could never sync
on any dynamic-discovery live run.

Fix (manager + CLI lanes, no peer-file edits): `_run_paper` in
`src/cryptobot/cli.py` now resolves discovery BEFORE session creation
using the bridge's own rule, via new `with_resolved_symbols` in
manager-owned `src/cryptobot/app/config.py` (explicit symbols +
recomputed fingerprint; TOML untouched). Test:
`test_with_resolved_symbols_recomputes_fingerprint`.

Proof (`paper-proof-prime`, 180s live): checkpoint `depth-prime`
shows applied 8, synced 8, failed {}; `book:never-synced`
rejections went 3,646 → 0. Remaining rejects are warmup-class
(history/quality) plus 190 `book:resync-in-flight` (normal live
chain-break resyncs). Quote-dependent strategy logic can now run.

## 30-minute session (paper-proof-30m) — interrupted at ~18 min

The run died on `ConnectionError: routes-exhausted: public exceeded
10 reconnects` — the bridge refusing to trade blind (fail-closed,
correct behavior), with no final report written. Evidence to that
point: 40,310 rejections, still 100% warmup/data-readiness
(33,340 `quality:empty-window`, 4,916 history, 1,394 resync-in-flight,
660 gap), 0 fills, equity flat. `book:never-synced` stayed at 0 —
the prime fix holds across runs.

Warmup analysis: S1-class strategies need ~120 present 1s bars plus a
gap-free lookback; `empty-window` dominating after 18 minutes on
majors means views still carry no present bars that strategies can
use (quiet-window bars + lateness watermark). Short sessions cannot
produce merit evaluations — the question needs a longer run, resumed
below.

## 33-minute verdict: live evaluation blocked by connection quality

Full resumed session: 70,815 rejections, ZERO non-warmup reasons, 0
fills, equity flat. Late windows carry ~17 trade-ID jumps per 135
1s bars; `to_s1_bar` (`bars.py:106-112`) correctly fails safe to
`None` on any flagged window, so strategy-visible bar series never
form a gap-free 120-bar lookback and no strategy can evaluate.

Decisive control: `data/captures/cap-2h` shows ZERO id jumps in
~5,000 sampled aggTrades — the venue feed is sequential; this host's
live connection drops trades (reconnect-driven), and every drop
poisons the bars. The code is right to refuse; the feed from here is
lossy. Consequence for real-market trading: live evaluation needs a
stable host/network near the venue (low-loss WS with rare reconnects)
before strategy merit can even be observed. Re-running longer paper
sessions from this host will keep measuring connection quality, not
edge — the next live experiment belongs on better network.

## Replay control (replay-cap2h-1): evaluation path works

Same strategies on the clean cap-2h capture (363,296 events): 8,080
rejections, of which **1,587 are merit evaluations**
(range/breakout/pierce/trend/sequence fails — strategies evaluating
and finding no setup), 0 admitted, equity flat. The 1,616
`book:never-synced` here are by design (replay is strictly offline;
REST snapshots skipped, `runtime_feed.py:88`).

This splits the question cleanly: the evaluation machinery works on
clean data (replay: merit verdicts), the live feed from this host is
too lossy for bars to form (live: zero merit verdicts), and the
window itself is too quiet for setups either way (consistent with
STUDY-01's n=0). Three separate facts, three separate owners:
network provisioning (owner), quiet-market reality (nobody's fault),
strategy edge (unproven).

## FIXED: paper crash leaves a resume hint (same day)

The 30-minute death printed a bare traceback with no report. `_run_paper`
now mirrors `_run_replay`: any exception from `run_live` prints
`run <id> interrupted: <type>: <msg>` plus the exact resume command
and returns 3 (cleanup in `finally` still runs). Test:
`test_paper_run_interrupted_prints_resume_hint` (stubbed
`ConnectionError`, temp config + storage, no network).

## FIXED: resume reuses the recorded universe (same day)

Follow-up gap in the discovery fix: resume re-ran fresh discovery,
so the universe could rotate mid-run (observed live: TIAUSDT for
AGTUSDT between runs). `_run_paper` now loads `discovery.json` from
the run dir on `--resume` and only falls back to fresh discovery
when no usable record exists. Test:
`test_paper_resume_reuses_recorded_universe` (discovery stubbed to
raise). Live proof: resumed `paper-proof-discrec` printed `resumed
universe` with the original 8 symbols and completed clean.

## book:never-synced pointers (for the execution lane, read-only)

`market_data/views.py:270-275` returns the reason when no book or
`book.state.synced` is false; live books sync via REST snapshots in
`execution/runtime_feed.py:124-148` (`pump_live`, retry on failure).
The bridge streams `depth@100ms` (`adapters/bridge.py:51`) and REST
is reachable from this host (klines/funding/depth all fetched today),
yet no symbol synced in 10 minutes. Open questions for the lane:
whether snapshot fetches fail silently (exceptions swallowed at
`runtime_feed.py:135-137` with no evidence record), whether diffs
arrive before the first snapshot and wedge the chain, or whether
views books are fed from a different book instance than the one the
snapshots install into. Suggest: evidence-log snapshot attempts and
outcomes per symbol, then re-run this 10-minute proof.
