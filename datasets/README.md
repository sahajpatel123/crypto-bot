# Frozen datasets (B5)

Two manifests, both opened with
`cryptobot.market_data.datasets.open_dataset`:

- `benchmark_30d.toml` — 30 IST-complete accounting days
  (2026-09-12..2026-10-11), 8 symbols, aggTrade + markPrice (+ Sep
  funding monthlies). 500 sources, 88 gaps, 12 upstream-absent files
  recorded. Parquet bulk lives in `cache/` (untracked, ~1.6 GB);
  `local` paths resolve against this directory. Manifest sha
  `b423a7be...` is the run-fingerprint input.
- `captured.toml` — retained live run-dirs (cap-2h, cap-30min,
  agreement-30s, smoke-60s), 16 sources, 0 gaps. Bulk lives in
  `data/captures/` (untracked, 2.0 GB) with absolute `local` paths.

Raw provenance zips for the 30-day freeze stay in
`data/bench30d/raw/` (untracked, 2.1 GB, re-downloadable).

Re-run (resume-safe, e.g. October funding top-up after month-end):

```sh
uv run --locked python datasets/prepare_benchmark_30d.py --out /tmp/bench30d-topup --jobs 32
```

then merge new parquets into `datasets/cache/`, regenerate the
manifest into `datasets/benchmark_30d.toml`, and record the new sha
before scoring. Never edit a manifest by hand.
