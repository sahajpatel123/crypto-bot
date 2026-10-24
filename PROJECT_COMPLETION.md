# Project completion record — 2026-10-23

## What "complete" means here

The engineering is complete and the bot **can** trade real capital
through exactly one guarded route. It does not trade by default, and
no profitability claim is made: no strategy has a hash-bound PASS yet.
Owner evidence (keys, demo drill, latency, a PASS verdict) is still
required before the gate can say GO — by design, not by omission.
Start with [LIVE_RUNBOOK.md](/Users/sahajpatel/Code/cryto-bot/LIVE_RUNBOOK.md).

## Completed in this pass

| Area | Change |
|---|---|
| Prod route | `_run_prod` now runs the live Session (user stream, seeding, resume) when armed; previously it always refused after verification |
| Gate | GO requires hash-valid PASS verdict + PASS drill + measured WS latency (p99 <250ms, drops <0.1%); evidence files bound by SHA-256; 24h expiry |
| Arm | Requires valid GO gate, positive capital, daily loss ≤ capital, env ack, interactive TTY + typed phrase; armed record binds the gate digest |
| Prod guards | Refuses unless config switch + gate + armed all present; refuses when venue equity > 1.5× armed capital |
| Canary | First 10 armed trades forced to minimum legal size (`risk/ladder.canary_size`, wired in Session) |
| Liquidation gate | Prod admission checks venue leverage brackets: stop must fire ≥3× before liquidation (`risk/margin`, `BinanceLiveEngine.leverage_brackets`) |
| Stale data | Entries hold when the venue account cache is >30s old; prod also holds when not armed |
| Reports | Every run report now carries `pnl_stress` (1×/2× cost P&L) and the armed context |
| Latency probe | `--ws-seconds N` measures real public WS feed age + drop proxy; REST-only output can no longer pass the gate |
| Owner docs | `LIVE_RUNBOOK.md` (keys-last workflow), `.env.example`, `.gitignore` covers `.env`/`gate.json`/`armed.json` |

## Verified

- Targeted suites: live-launch (8), hardening, CLI readiness, risk
  sizing — green.
- `cryptobot doctor` READY; `cryptobot gate` correctly NO-GO with no
  evidence; prod correctly BLOCKED without owner keys.
- Full suite: **1501 passed, 1 failed, 1 skipped** (25m26s). The one
  failure (`test_nested_deadline_adversarial`) is a timing-sensitive
  process test that also fails on the untouched base — pre-existing
  environmental flakiness, unrelated to trading code.

## Still owner-only (cannot be done without you)

1. API keys (withdrawals disabled, IP allowlist) — runbook step 1.
2. Demo drill PASS with those keys — step 3.
3. WS latency PASS on your host — step 4.
4. A strategy PASS verdict on untouched data — step 5. This is the
   real remaining risk: the code is ready, the edge is unproven.
