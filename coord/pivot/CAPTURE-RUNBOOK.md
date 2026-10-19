# Z1 self-capture runbook — 10 days of qualifying tick (owner-executed, $0)

Goal: produce the PIVOT-01 qualifying dataset input: >=10 days of untouched
tick for the capture set, with L2/book quotes + aggTrades + marks >=1s +
funding + monotonic seq. Public streams only — **no credentials, no orders.**

This runbook stops at **audited raw captures + hashes**. Manifest build /
dataset freeze is a data-lane task on top of these bytes (same pattern as
`datasets/README.md`: prepare script regenerates, never hand-edit).

All commands run from the repo root on a machine with network access to
`fstream.binance.com`. Tool: `tools/capture_stream.py` (Worker 2, E-006).

## 0. Preflight (do not skip)

```sh
# 1. Universe + clock sanity (read-only, ~seconds)
python tools/capture_public.py discover --max-min-notional 20

# 2. Dry run: discovery + selection + clock offset, no capture
python tools/capture_stream.py --top-n 2 --duration-s 60 --dry-run

# 3. Disk: check free space NOW (a prior board noted ~5GB free on one
#    host — that host cannot hold 10 days; use external storage)
df -h . ; df -h /Volumes 2>/dev/null || true
```

Proceed only if: discovery returns a symbol list, dry-run prints
`clock_offset_ms`, and free space exceeds your measured need (step 1).

## 1. One-hour pilot (measure, don't guess)

```sh
python tools/capture_stream.py --top-n 2 --duration-s 3600 \
  --run-base /path/with/space/captures --run-id cap-pilot-1h
```

While it runs, supervision (from the tool header):

- `heartbeat.json` in the run dir advances; `STOP` file or SIGTERM/SIGINT
  stops cleanly; PID file tracks the process.
- Watch for `gap_kind` rows and reconnect lines in stdout.

After it exits:

```sh
du -sh /path/with/space/captures/cap-pilot-1h
# bytes_per_hour = that number. Required ≈ bytes_per_hour * 24 * 10 * 1.3
# (30% headroom). If free space < required: STOP, attach bigger storage.
```

Record `bytes_per_hour`, host, and date in your handoff note. No
extrapolation without this measurement.

## 2. Symbol continuity decision (record it)

Default (`--top-n 2`) re-selects by 24h quoteVolume every run — correct
for a live universe, wrong for a 10-day panel (membership churn breaks
day-to-day comparability).

- For the qualifying panel, pin the pilot's symbols explicitly:
  `--symbols BTCUSDT,ETHUSDT` (whatever the pilot selected).
- This is recorded by the tool as `operator override: ... (NOT dynamic
  selection)`. That label is honest and expected here: continuity is a
  stated property of this dataset, and the rule string travels with the
  run manifest.
- Do NOT mix pinned and dynamic runs inside one 10-day panel.

## 3. Ten daily captures (one per day, resumable)

```sh
# Day N (run once per calendar day; run-id carries the date):
python tools/capture_stream.py --symbols BTCUSDT,ETHUSDT \
  --duration-s 86400 --run-base /path/with/space/captures \
  --run-id cap-10d-day01
# ... day02 ... day10
```

Rules:

- One run = one day. If a run dies mid-day, start a **new run-id**
  (`cap-10d-day04b`); never splice bytes into a finished run dir.
  Gaps are ledgered by the audit step, not hidden.
- Keep every run dir, including short/failed ones. Deleting bad runs
  is survivorship bias with extra steps.
- Leave `--chaos-disconnect-after-s` OFF for qualifying captures
  (chaos runs are for resilience drills, not data).
- Funding: settlements arrive on stream; month-boundary backfill via
  REST is a data-lane step (availability previously verified) —
  note any month boundary crossed in the handoff.

## 4. Per-run audit (mechanical, same function the readiness track uses)

```sh
python3 -c "
import sys; sys.path.insert(0, 'src')
from pathlib import Path
from cryptobot.market_data.eligibility import classify_capture
import json
rep = classify_capture(Path('/path/with/space/captures/cap-10d-day01'),
                       ['BTCUSDT', 'ETHUSDT'])
print(json.dumps({s: {'market_eligible_s': v['market_eligible_s'],
                      'research_eligible_s': v['research_eligible_s'],
                      'trade_seconds': v['trade_seconds']}
                  for s, v in rep['symbols'].items()}, indent=1))
print('bad_rows:', rep.get('bad_rows'),
      '| gap_markers:', len(rep.get('gap_markers', [])))
print('depth:', rep.get('depth', {}).get('class'),
      rep.get('depth', {}).get('count'))
"
```

Keep the full report JSON per run (`--out` equivalent: redirect to
`<run-dir>/eligibility.json`). A run enrolls toward the 10-day panel
only if: `bad_rows` is small and explained, research-eligible seconds
cover the day modulo ledgered gaps, and depth snapshots are present
(`count > 0`; absence = S5-class views ineligible, recorded not assumed).

## 5. Hashes + handoff (what the data lane receives)

```sh
cd /path/with/space/captures
sha256sum cap-10d-day*/events.jsonl > SHA256SUMS 2>/dev/null \
  || shasum -a 256 cap-10d-day*/events.jsonl > SHA256SUMS
```

Handoff note must state: host, dates, `--symbols` rule string, pilot
`bytes_per_hour`, per-run eligibility summary, SHA256SUMS, and anything
unusual (restarts, network drops, month boundary). Failed runs listed,
not omitted.

## 6. Explicit non-goals

- No trading, no keys, no orders — capture tools cannot submit.
- No editing manifests by hand; no scoring against this data until the
  data lane freezes splits and the TEST portion is sealed.
- This data does not validate any strategy. It only unblocks Z1 so
  that measurement can begin.
