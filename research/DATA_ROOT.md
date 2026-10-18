# Data root

`cryptobot.research.data_root.resolve_data_roots` finds three stores:

| Store | Relative path | What it is |
|---|---|---|
| lake | `data/lake` | Vision parquet and raw zips. DEV is before 2024-01-01. HOLDOUT stays sealed. FORWARD is after 2026-10-17. |
| pilot | `data/pilot` | Read-only Family A development days. |
| benchmark | `datasets/benchmark_30d.toml` | Frozen 30-day manifest. Paths inside it resolve next to the file. |

Resolution order for each store:

1. `CRYPTOBOT_LAKE`, `CRYPTOBOT_PILOT`, or `CRYPTOBOT_BENCHMARK`
2. `CRYPTOBOT_DATA_ROOT`, or `root` in `research/data_root.toml` (or the file named by `CRYPTOBOT_DATA_CONFIG`)
3. The same relative path in the repo, if it exists
4. The same relative path under `CRYPTOBOT_EXTERNAL_ROOT` or `external_root` in the config, if it exists

The read-only external checkout for this machine is
`/Users/sahajpatel/Code/cryto-bot` (`data/pilot` and
`datasets/benchmark_30d.toml`). Do not write there. Do not read
`coord/pivot` or campaign captures.
