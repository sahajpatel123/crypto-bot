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

**2026-10-17 redirect (owner decision): 1 day, 10 GB budget, richest
capture.** The 10-day BTC-only campaign ran 11 chunks cleanly (10
complete + 1 honest partial, 72 MB, 0 gaps) and was stopped per the
owner's new direction. It is preserved untouched at
`data/captures/campaign-20261016/` (status `stopped`).

**Live now**: `data/captures/campaign-1day-20261017/` — BTCUSDT+ETHUSDT,
profile `full` (aggTrade + markPrice@1s + bookTicker + depth@100ms),
1 day, 1-hour chunks, `--min-free-gb 2`, started 2026-10-17T12:13Z.
A 1-day window inside a 10 GB budget affords the full channel set the
10-day window could not: live preflight (120 s, measured) projected
**1.2 GB settled / 2.4 GB peak against 14.5 GB free → verdict OK**
(depth synced in probe; gzip 0.090 on full-profile bytes).

```sh
cd /Users/sahajpatel/Code/cryto-bot
nohup caffeinate -is .venv/bin/python <this-branch>/tools/capture_campaign.py start \
  --dest /Users/sahajpatel/Code/cryto-bot/data/captures/campaign-1day-20261017 \
  --days 1 --chunk-hours 1 --symbols BTCUSDT,ETHUSDT --profile full \
  --probe-s 120 --min-free-gb 2 \
  >> data/captures/campaign-1day-20261017.nohup.log 2>&1 &
```

Monitor / stop:

```sh
.venv/bin/python <this-branch>/tools/capture_campaign.py status \
  --dest data/captures/campaign-1day-20261017
.venv/bin/python <this-branch>/tools/capture_campaign.py stop \
  --dest data/captures/campaign-1day-20261017
```

Notes: `status` shows the full chunk ledger once the first hourly chunk
settles; before that, `chunk-*/heartbeat.json` is the live pulse.
Restart after any reboot = re-run the same `start` command (resumes at
the next unsettled chunk, no re-probe). The stopped 10-day campaign was
BTC-only because at then-current activity BTC+ETH needed ~16–21 GB
settled against ~13 GB free; it used `lean500` because bookTicker
(83 % of bytes) and depth@100ms did not fit — depth@500ms still
reconstructs the full book at ≤1 s resolution (soak: 2,236/2,381 diffs
applied, 24/24 snapshots synced).

## Storage budget (10 GB owner cap)

`--max-settled-gb N` is a hard cap on settled bytes (sum of settled
`*.jsonl.gz` across chunks), checked before every chunk: when reached,
the campaign stops cleanly with status `budget-reached`. The cap stops
intake — it never deletes or filters captured data. `status` reports
`settled_bytes_now` so usage is always visible. The live 1-day campaign
projects ~1.2 GB settled against the 10 GB cap (no restart needed: the
guard only binds future runs that approach the cap, and the disk guard
already protects the host).

## What this does NOT do

No trading, no orders, no credentials. Completing the campaign unlocks
the **powered** version of the predeclared probes and the qualification
screen under the same kill criteria — it does not promise a positive
result; it buys the honest right to look.
