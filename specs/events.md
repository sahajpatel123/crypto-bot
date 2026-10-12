# Events and market monitoring (Worker 4, EV-001)

Owner: Worker 4 (white-aldebaran). Contract: six-agent-48h (directive
sections 6, 8). Owned paths: `src/cryptobot/events/**`,
`tests/unit/test_events_*.py`, this file. Manager owns Session/CLI
integration; this spec proposes the exact Session seam.

## 1. Purpose

A small deterministic module that keeps macro-event calendars, blocks new
entries around designated events, and exposes an unscheduled-shock policy
interface. It never places, cancels, or exits orders and never reads the
market: Session supplies time and measurements, the module returns
decisions.

## 2. Event record

Every event persists (JSON-serializable, `Event.to_dict`):

| Field | Meaning |
|---|---|
| `event_id` | Stable ID, e.g. `FOMC-2026-09-16-decision`, `CPI-2026-10-14` |
| `source` | `fomc`, `cpi`, `employment`, `bea-pce`, `bea-gdp`, `exchange-notices` |
| `title`, `kind`, `note` | Human label; one of decision/press-conference/release/maintenance/delisting; free note |
| `source_url` | Official calendar URL the schedule came from |
| `scheduled_local_iso` | Naive `YYYY-MM-DDTHH:MM:SS` wall time + `tz_name` (official convention) |
| `scheduled_utc` | Authoritative instant; load FAILS if it disagrees with wall+zone |
| `first_seen_utc` | First observation; immutable once stored |
| `fetch_utc` | Last (re)fetch; moves on revision |
| `revision`, `revisions[]` | Counter + append-only change log (rev, fetched, note, changed fields) |
| `horizon_end_utc` | Last scheduled instant this source record covers (None = unknown) |
| `expires_utc` | Record retention end (scheduled + 7 days); pruned only by explicit `prune()` |
| `press_end_utc` | Press-conference end: verified value or explicit conservative assumption |
| `status` | scheduled / released / revised / cancelled (cancelled events never block) |

Revisions use `Event.with_revision(...)`: scheduled time, fetch time,
revision+1, status `revised`, and a `Revision` entry. `upsert` rejects
backward revisions and first-seen rewrites.

## 3. Sources and fixture provenance (EV-001)

| Source | Schedule | Provenance |
|---|---|---|
| FOMC decisions + press (8+8 events, 2026) | Statement 2:00 PM ET, press 2:30 PM ET, second meeting day | `fomc_2026.json`, meeting dates read from the official Fed calendar page on 2026-10-12 (Jan-Sep released, Oct/Dec scheduled). Every-meeting press policy (post-2019). |
| CPI releases (12 events, 2026) | 8:30 AM ET monthly | `cpi_2026.json`. Direct BLS fetch returned HTTP 403 on 2026-10-12, so all twelve dates were cross-checked against four agreeing mirrors (WSJ live coverage, CPI schedule trackers, BLS-derived datasets). Re-verify Oct 14+ at runtime (lapse/rescheduling chatter observed). |
| Employment, BEA PCE/GDP, exchange notices | — | `StubAdapter`: explicit `not-implemented`, no events, no horizon. Required stubs block; EV-001 leaves them optional. |

Coverage record per source: horizon end, fetch time, expiry (fetch + 24h
TTL), status. Effective state (`coverage_status`): `fresh`, `stale`
(fetch expired), `expired-horizon` (now past last known schedule),
`outage` (explicit error), `unknown` (no record), `not-implemented`.
Anything but `fresh` on a REQUIRED source fails the gate closed (section 5).

## 4. Timezones

Author in `America/New_York` wall time, store/compare in UTC, display in
IST (`YYYY-MM-DD HH:MM IST`). US DST 2026: EDT (UTC-4) Mar 8–Nov 1, EST
(UTC-5) otherwise. Spot table (all pinned by `test_events_tz.py`):

| Event | ET | UTC | IST |
|---|---|---|---|
| FOMC Jan 28 decision | 14:00 EST | 19:00 | 00:30 Jan 29 |
| FOMC Sep 16 decision | 14:00 EDT | 18:00 | 23:30 |
| FOMC Dec 9 decision | 14:00 EST | 19:00 | 00:30 Dec 10 |
| CPI Mar 11 | 08:30 EDT | 12:30 | 18:00 |
| CPI Nov 10 | 08:30 EST | 13:30 | 19:00 |

Eastern has no fixed fallback: a host without tzdata raises instead of
guessing the offset. IST falls back to fixed UTC+5:30 (identical by
construction). Nonexistent spring-forward wall times raise.

## 5. Entry gate

`EventGate(store, GateConfig)` answers: may Session admit a new entry now?

Frozen paper hypothesis: block from 15 min before a designated event
until 15 min after (`pre_buffer_s`/`post_buffer_s` = 900). Press
conferences are separate events: window runs from scheduled−pre through
press-end+post, where press-end is the verified fixture value or the
configured 60-minute conservative assumption (`press_duration_s`).
`resume_cooldown_s` (default 0) extends the block for a defined healthy
period; spread/liquidity/feed health itself is Session's measurement.

`check(now_utc) -> GateDecision(blocked, reason, event_ids, window_end_utc,
coverage)`. Reason vocabulary (stage `event` in `rejections.jsonl`):

- `event:clear`
- `event:pre-window:<id>`, `event:in-window:<id>`, `event:press-window:<id>`, `event:post-window:<id>`
- `event:stale-source:<source>:<unknown|outage|stale|expired-horizon|not-implemented>`

Coverage is checked FIRST: a stale/outage/unknown required source blocks
even with no event near. `active()` lists events in-window;
`upcoming(now, horizon_s)` lists windows opening soon with action
`prepare-flat` (Session cancels unfilled entries and aims flat by window
start; protection stays on until closure is confirmed).

Protective-exits invariant: the gate exposes NO exit/flatten/cancel API
(pinned by test). Session must call it only in the entry path.

### Proposed Session seam (manager to wire)

In `Session._maybe_admit`, after selector admission and before
`policy.evaluate`:

```python
gate_decision = self.event_gate.check(self.now_utc())
if gate_decision.blocked:
    self._note_reject(gate_decision.reason, intent.strategy,
                      intent.instrument, intent.side.value)
    self.store.record_intent(..., "rejected", gate_decision.reason, ...)
    return
```

Plus a pre-window sweep (per ingested second or per evaluation): query
`upcoming(now, horizon_s)` and, for each hit, cancel unfilled entry
orders for that instrument and steer to flat before `window_start_utc`
without touching protective stops. Exact sweep placement is the
manager's call; this module only supplies the query.

## 6. Anomaly (unscheduled-shock) interface

`evaluate(config, reading, baseline, state, now) -> AnomalyDecision`.
Session measures; the policy folds one reading into `AnomalyState` and
returns an entry action. No market I/O, no orders, no liquidation.

Starting thresholds (explicit ASSUMPTIONS, require dev/val tuning):

| Signal | Trip | Recovery (hysteresis) | Action |
|---|---|---|---|
| spread_bps ≥ 25 | widen | ≤ 12.5 for `clear_streak` | reject-entries |
| book_depth_ratio ≤ 0.30 | thin book | ≥ 0.65 for `clear_streak` | reject-entries |
| abs_return_bps ≥ 50 / 60s | shock | ≤ 25 for `clear_streak` | cancel-entries |
| latency_ms ≥ 2000 | stale feed | ≤ 1000 for `clear_streak` | halt-entries |
| exchange errors ≥ 3 / 60s | venue faults | 0 for `clear_streak` | halt-entries |

Hysteresis: `clear_streak` (default 3) consecutive clean readings to drop
a trip; `None` readings neither trip nor clear. Cooldown: after trips
empty, `reject-entries` persists until `cooldown_until_utc` (trip time +
`cooldown_s`, default 300s), then `allow`. Worst action wins; reasons
look like `anomaly:halt-entries:latency`. `halt-entries` means exit-only
for NEW risk; protection and exposure reduction proceed.

## 7. Historical use

Backtests may only consult events with `first_seen_utc` ≤ simulated now
(the store records it; the harness must enforce the cutoff). Fixture
schedules are 2026 annual caches: using a December event's time in a
September replay without a contemporaneous first-seen is leakage. Future
work: per-replay cutoff filter in the harness.

## 8. Test map

- `test_events_tz.py`: EST/EDT conversion, DST boundaries (Mar 8 / Nov 1
  2026), IST display incl. date rollover, wall/UTC mismatch rejection.
- `test_events_store.py`: CRUD/ordering, revision monotonicity,
  first-seen immutability, coverage states, JSON round-trip, prune.
- `test_events_sources.py`: fixture counts/IDs/dates/URLs/horizons,
  full DST audit of every fixture instant, outage/stub explicitness.
- `test_events_gate.py`: pre/in/press/post windows incl. FOMC
  decision→press continuity, stale-source fail-closed (all five states),
  upcoming prepare-flat, cancelled skip, no-exit-API pin.
- `test_events_anomaly.py`: per-signal trip/action, worst-wins,
  hysteresis streak, None neutrality, cooldown, config validation.
