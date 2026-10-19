# Z6 first drill record (2026-10-16)

Independent re-run of the accepted W2 D3 offline drill (tool untouched,
read-only use) to a fresh directory, per the board's fresh-dir rule:

`python tools/audit/sandbox_drill.py --dir /tmp/drill-z6 --seed 7 full`
→ rc 0, all 6 phases PASS, **SANDBOX VALIDATED**.

What this proves for Z6 live-ops: interrupt-with-exposure → resume →
reconciled-flat works end to end on the scripted sandbox (crash with
+0.002 ETH venue exposure unadopted, resume adopts fills and flattens,
ledger_net=0.0, no duplicates). Re-run command is in the W2 D3 filing
(`coord/outbox/DEEP-W2-D3.done.json`).

What it does NOT prove: **BINANCE DEMO VALIDATION PENDING** — the demo
leg needs owner credentials under policy and was not run. Z6 cannot go
GREEN on a sandbox record alone; this record moves it from "no record
exists" to "offline drill record exists, demo pending".
