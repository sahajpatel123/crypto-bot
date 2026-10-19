# Recorder costs

Measured on this Mac after `deploy/macos/install.sh`, 2026-10-18.
Symbols BTCUSDT and ETHUSDT. Chunks rotate every 300 seconds.
Public data only. The vault access log head stayed
`1ccf32fffad9ae95` (21 entries). The recorder manifest verified
with an empty problem list and 3 sealed entries. First seal
`2026-10-18T21:42:56.700228Z`.

Process pid 72130, elapsed 18:36, CPU time 1:50.90.
That is 110.9 seconds of CPU over 1116 seconds, **9.9% of one core**.

Chunk bytes grew from 2,285,093 to 17,621,934 in 948.6 seconds
(`/tmp/recorder-sample-1.json` to the later `du` of `data/recorder/chunks`).
Rate: **58.21 MB/hour**, about **1.40 GB/day** if that rate holds.

Watchdog free space at the end of the window: 16,868 MB.
At 1.40 GB/day that is about **12 days** until the 8,192 MB stop
threshold (the host had ~13 GB free at install; the code default of
50,000 MB would have stopped the recorder immediately, so the agent
uses `--disk-budget-mb 8192`).

The daily refresh listed Binance Vision through filename date
2026-10-17 and found **zero** objects dated after that day, so it
downloaded nothing and did not open holdout. See
`~/Library/Logs/cryptobot/refresh.log`.
