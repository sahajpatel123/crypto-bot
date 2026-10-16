# Ten-day untouched capture campaign (G1 unlock)

Status: tool committed on branch `data/ten-day-campaign`; the campaign
itself is launched by the owner/manager from this branch (or after
manager integration) — see "Launch". Authored by the external
contributor session, 2026-10-16.

## Why this exists

The release report (Checkpoint-C §3d) blocks the untouched evaluation
leg and the qualification screen on one missing input: **≥10 days of
fresh tick data nobody has used** (trades + book/depth + marks + seq/
timestamps; funding is backfilled separately from Binance Vision
monthly files — existing `datasets/backfill_funding.py`). This campaign
captures exactly that, unattended, at $0, with a fail-closed preflight
and an honest disk policy.

## Disk reality (measured on this host, 2026-10-16)

Free space: ~12 GB of 228 GB. Measured channel bytes on `cap-2h`
(full capture, 2 h, BTC+ETH):

| channel | bytes / 2 h | share |
|---|---|---|
| bookTicker | 1,285 MB | 83 % |
| depth@100ms | 223 MB | 14 % |
| aggTrade | 34 MB | 2 % |
| markPrice@1s | 7 MB | <1 % |

A full-rate 10-day capture needs ~186 GB → impossible here, and even
the 100 ms-depth minimum projects ~13 GB settled for BTC+ETH — right at
the free-space edge with the peak and guard. The tool's **live
preflight probe** measures the real rates on the day of launch, projects
settled + peak bytes, and REFUSES to start when they do not fit
(`--allow-tight` overrides loudly). Profiles:

| profile | public | measured behavior |
|---|---|---|
| `lean500` (default) | depth@500ms | ~2 depth events/s/symbol; largely chains (soak decides final acceptance); halves-thin bytes |
| `minimal` | depth@100ms | deepest cadence; ~9.5 depth events/s/symbol; cleanest sync measured (542/571 applied, 1 resync in 60 s) |
| `full` | bookTicker+depth@100ms | needs tens of GB free — not runnable here |

Either thin profile drops the bookTicker channel: bars then carry no
direct spread and replay uses the **modeled spread profile**, exactly
as every frozen round already does. Depth alone reconstructs the full
book from snapshot + chained diffs, which is what "book/depth" in the
screen's data list requires.

## What the supervisor does

- Chunked capture (default `--chunk-hours 2`, configurable) using the
  real E-006 `Collector` (routes, REST depth snapshots, heartbeat,
  reconnect, STOP semantics inherited).
- Settle per chunk: gzip `events.jsonl` / `bars.jsonl` /
  `depth_snapshots.jsonl` with sha256 + sizes recorded; **delete
  `raw.jsonl`** (the canonical record is events.jsonl; raw exists only
  during capture). `SETTLED.json` carries an honest `complete` flag
  (only `duration-reached` is complete; anything else is partial and
  says so).
- Resume: settled chunks are skipped on restart; a crash-partial chunk
  is settled as partial, never fabricated, never re-run.
- Failed chunks retry the same index (bounded attempts, gap records in
  `campaign_state.json` and `campaign_log.jsonl`).
- Disk guard: below `--min-free-gb` the campaign **pauses** and
  re-checks every 15 minutes (status `disk-paused`) instead of dying or
  filling the disk.
- `status` / `stop` subcommands; SIGTERM stops the live chunk cleanly
  and finalizes state.

## Launched (2026-10-16, this host)

**Live now**: `data/captures/campaign-20261016/` — BTCUSDT, profile
`lean500`, 10 days, 1-hour chunks, `--min-free-gb 2`, started
2026-10-16T15:13Z. Launched detached as:

```sh
cd /Users/sahajpatel/Code/cryto-bot
nohup caffeinate -is .venv/bin/python <this-branch>/tools/capture_campaign.py start \
  --dest /Users/sahajpatel/Code/cryto-bot/data/captures/campaign-20261016 \
  --days 10 --chunk-hours 1 --symbols BTCUSDT --probe-s 180 --min-free-gb 2 \
  >> data/captures/campaign-20261016.nohup.log 2>&1 &
```

Live preflight (180 s, measured): events 36.2 kB/s, raw 42.4 kB/s,
gzip ratio **0.183**, projected settled **5.9 GB** / peak 6.2 GB against
13.9 GB free → **verdict OK** (depth synced in probe; 94 % of depth
diffs chain after the first minute, ~2 resyncs/min, books heal in
~2.5 s; the eligibility layer records any spans honestly).

Monitor / stop:

```sh
.venv/bin/python <this-branch>/tools/capture_campaign.py status \
  --dest data/captures/campaign-20261016
.venv/bin/python <this-branch>/tools/capture_campaign.py stop \
  --dest data/captures/campaign-20261016
```

Notes: `status` shows the full chunk ledger once the first hourly chunk
settles; before that, `chunk-*/heartbeat.json` is the live pulse.
Restart after any reboot = re-run the same `start` command (resumes at
the next unsettled chunk, no re-probe). Why BTC-only: at current market
activity BTC+ETH needs ~16–21 GB settled and the disk has ~13 GB free;
ETH (and X1's BTC/ETH pairing) waits for space or a second campaign.
Why `lean500`: bookTicker (83 % of bytes) and depth@100ms were the
alternatives that did not fit; depth@500ms still reconstructs the full
book at ≤1 s resolution (soak: 2,236/2,381 diffs applied, 24/24
snapshots synced).

## What this does NOT do

No trading, no orders, no credentials. Completing the campaign unlocks
the **powered** version of the predeclared probes and the qualification
screen under the same kill criteria — it does not promise a positive
result; it buys the honest right to look.
