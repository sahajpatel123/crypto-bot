# Data use audit — 2026-10-21

Every retained store is now checked by one command and consumed by a real
project path. The audit is read-only: it never edits a manifest and never
decodes holdout or reserved confirmation data.

```sh
uv run --locked cryptobot data assets \
  --json-out reports/data-use/audit.json
```

Result: **WARN — 7/9 assets fully OK, 2 partial, 0 failed, 10.5 GiB
accounted.** The two partial assets are the H1/H5 book captures whose bulk
`raw.jsonl`/`events.jsonl` (about 4 GiB) were already absent before this
audit. Their retained depth-snapshot/metadata files are intact; the scored
reports remain frozen evidence, but the captures cannot be re-scored.

The remaining ~0.8 GiB of the 11.3 GiB cleanup total is `runs/`, `reports/`,
and the scratch worktrees; that is run evidence rather than a data store and
is intentionally outside this audit.

## Asset -> consumer -> evidence

| Asset | Retained | Consumer | Evidence |
|---|---:|---|---|
| `benchmark_30d` + `datasets/cache` | 1.5 GiB | `tools/eval_h123.py`, `tools/eval_h4.py` | 506/506 sources hash-verified; H2 +56.423 bps (n=290), H3 −6.617 bps (n=121), H4 n=0 (no day ≥ 2026-10-20) |
| `data/pilot` | 572 MiB | `tools/family_a_dev.py` (external data root) | 29 days, 1.65M events/day valid gzip + `observed-public` labels |
| `data/lake/dev` | 3.2 GiB | `tools/run_family_b.py`, `tools/lake_finalize.py` | 2,452/2,452 Parquet files hash-verified; **B1 and B6 re-derived exactly** from the retained lake |
| `holdout_raw` | 2.3 GiB (242,028 files) | `cryptobot verdict --holdout-screen`, `tools/holdout_reconcile.py` | 7 manifests parsed, sampled bytes hash-verified; content **not decoded** |
| `data/recorder` | 2.1 GiB (395 chunks) | `cryptobot recorder verify`, `cryptobot compact`, `background status` | **87,727,190 records, 0 gaps**, no broken chunks; 3 corrupt unsealed partials removed |
| `data/vault` | 109 MiB (14 chunks) | `cryptobot verdict --vault-*`, `holdout_reconcile.py` | registry chain + all 14 chunk hashes verified |
| `campaign-1day-20261017` | 723 MiB (12 settled chunks) | exactly-once confirmation (owner release only) | metadata-only; 1 empty abandoned chunk removed; payloads **not decoded** |
| `h1-accrual-01` | 267 KiB present | `tools/score_h1_capture.py` | **PARTIAL**: manifest references 3.7 GiB raw/events/bars that are absent; only depth snapshots + run stats remain |
| `h5-accrual-01` | 224 KiB present | `tools/score_h1_capture.py` | **PARTIAL**: manifest references 1.1 GiB raw/events/bars that are absent; same condition |

Raw evidence files:

- `reports/data-use/audit.json` — full audit (asset hashes, samples, problems)
- `reports/data-use/lake-dq.json` — DEV lake data-quality report
- `reports/data-use/recorder-verify.json` — recorder integrity report
- `reports/data-use/family-b-reproduction.json` — B1/B6 rederive comparison
- `reports/data-use/H1-recorder-book-scan.json` — recorder book diagnostic

## The recorder now feeds a real diagnostic

`tools/recorder_book_scan.py` reads the recorder's full 30-second REST
`depth_snapshot` books (the recorder's diff stream is marked
`gap=depth-chain`, so it is deliberately not used):

- 395 chunks, **3,826 full-depth snapshots**
- **1,494 / 3,826** snapshots breach the frozen H1 top-5 notional threshold
  `|imbalance| > 0.6`
- BTCUSDT 761/1,913; ETHUSDT 733/1,913
- The retained H1/H5 REST snapshots show 2/6 and 0/5 — consistent with a very
  small sample, not with the 5,962-snapshot event book

This is a **diagnostic, not a verdict**. It does not produce fills (the
recorder has no aggTrade stream) and does not change H1. It does show that
the H1 "signal-starved on majors" result is likely an artifact of the H1
capture's shallow event book rather than full-depth market behavior. A
future H1 re-run needs a capture that maintains full depth **and** records
aggTrade prints.

## Gaps that remain (and are now visible)

1. **H1/H5 bulk events are gone.** Their manifests list ~4 GiB of
   `raw.jsonl`/`events.jsonl`/`bars.jsonl` that no longer exist. The audit
   marks both `PARTIAL`; do not describe those captures as re-runnable.
2. **H4 has no fresh day.** Cache coverage ends 2026-10-19; H4 requires
   days ≥ 2026-10-20, so it correctly stays `UNDERPOWERED (n=0)`.
3. **Recorder diff chain is broken.** Every diff is labelled
   `gap=depth-chain`; only the full REST snapshots are trustworthy.
4. **Campaign is partial and reserved.** 12 settled chunks, 723 MiB;
   metadata was checked, payloads were not read.
5. **H2/H3 are still underpowered** (290 and 121 trades vs the 300 floor),
   not changed by this audit.

## Reproduce

```sh
cd /Users/sahajpatel/Code/cryto-bot

# 1. verify + read every retained asset
uv run --locked cryptobot data assets --json-out reports/data-use/audit.json

# 2. benchmark preflight + H1/H2/H3 + H4
PYTHONPATH=src .venv/bin/python tools/eval_h123.py
PYTHONPATH=src .venv/bin/python tools/eval_h4.py

# 3. lake DQ + Family B exact rederive (edge worktree)
cd /Users/sahajpatel/Code/cryto-bot-edge
.venv/bin/python tools/lake_finalize.py dq --lake data/lake/dev \
  --out /Users/sahajpatel/Code/cryto-bot/reports/data-use/lake-dq.json
.venv/bin/python tools/run_family_b.py dev --hypothesis B1 \
  --lake data/lake/dev --root /tmp/cryto-bot-data-use/family-b
.venv/bin/python tools/run_family_b.py dev --hypothesis B6 \
  --lake data/lake/dev --root /tmp/cryto-bot-data-use/family-b

# 4. recorder + vault + book diagnostic
.venv/bin/python -m cryptobot.cli recorder verify --out data/recorder
.venv/bin/python -m cryptobot.cli vault verify --root data/vault
cd /Users/sahajpatel/Code/cryto-bot
PYTHONPATH=src .venv/bin/python tools/recorder_book_scan.py
```
