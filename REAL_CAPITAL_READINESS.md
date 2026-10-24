# Real-capital readiness — 2026-10-21 (updated 2026-10-24)

## Verdict: **NO-GO. Do not arm. Do not deploy real capital.**

### Update 2026-10-24

- **H2 KILLED** on 2022-01..2026-08 archive data it had never seen:
  −17.09 bps/trade over 6,441 trades (gross +0.91), CI95 [−29.9, −4.1]
  (`reports/hypotheses/H2-history.json`). It is no longer a candidate.
- **Family C** (daily TSMOM / XSMOM / carry / reversal) preregistered
  and scored: all FAIL DEV; the best (C2 XSMOM) was KILLED on the
  one-shot 2025–26 holdout (p=0.154) and on the one-shot 2020–21
  replication (p=0.080). See RESEARCH_VERDICTS.md.
- Safety fixes: armed `max_daily_loss` is now enforced in the risk
  policy; the gate records the strategies + code commit its verdict
  scored and prod refuses anything else (so S1–S5 can never trade
  live); verdict Holm p-value and day-block bootstrap corrected.
- The prod route DOES run live when fully armed (since 095cbd7); item 3
  below describes the earlier always-refuse state.

The project's own gate says NO-GO. This is not a code-completion problem;
there is no validated edge to trade.

### Evidence (read-only commands, no orders, no keys)

| Check | Result | Source |
|---|---|---|
| `cryptobot final-status` | H1–H6 `AWAIT_DATA`; B1–B7 `KILLED`; C1 `AWAIT_FORWARD`; adjudication `WAITING` | edge worktree |
| `cryptobot monitor` | **NO-GO — no demonstrated edge**; hurdle `HURDLE_UNMET` | edge worktree |
| Gate file | none — no `gate.json` GO exists | both worktrees |
| Arm file | none — no `armed.json` exists | both worktrees |
| H1 | UNDERPOWERED, n=1 (capture bulk events now missing) | `reports/hypotheses/H1*.json` |
| H2 | dev UNDERPOWERED n=290 (+56.42bps) → **KILLED** on 2022–26 history (−17.09bps, n=6,441) | `reports/hypotheses/H2.json`, `H2-history.json` |
| H3 | UNDERPOWERED, n=121; net −6.62 bps/trade | `reports/hypotheses/H3.json` |
| H4 | UNDERPOWERED, n=0; cache ends 2026-10-19, fresh window starts 2026-10-20 | `reports/hypotheses/H4.json` |
| H5 | UNDERPOWERED, n=0 | `reports/hypotheses/H5-accrual-01.json` |
| Family B B1–B7 | all **KILLED** on frozen gates | `FINAL_STATUS.md`, edge verdicts |
| 14-day pessimistic paper | **not run** — requires a PASS first | `STATE.md` T5.6 |
| Demo drill | **BLOCKED** — no credentials, not run | `OWNER_ACTIONS.md` |
| Live latency (WS p99 / drops) | **not measured** — REST only | `latency.json` absent |
| Cost model / host check / watchdog evidence | not fresh / not owner-supplied | `OWNER_ACTIONS.md` steps 1–7 |
| Prod submission | hard-disabled; `_run_prod` always refuses at the end | `src/cryptobot/cli.py` |
| Active-branch readiness | **4/10**; edge release | `FINAL_STATUS.md` |
| Edge release readiness | **2/10** live | `cryto-bot-edge/FINAL_STATUS.md` |

### Why real capital is unsafe today

1. **No strategy passes the project's own bar.** H2 is the closest at
   `n=290`, ten trades short, and its edge is concentrated in three symbols.
   B1–B7 are KILLED. H4 has no fresh data. Nothing has a PASS.
2. **A real-capital launch requires evidence this repo does not have:** a
   hash-bound PASS, 14-day pessimistic paper, demo drill, measured WS
   latency/drops, fresh cost model/host check, and a GO gate.
3. **The prod route is intentionally a refusal.** `_run_prod` constructs
   and verifies the driver, then returns `REFUSED — submission disabled`.
   Flipping that switch is an owner-authorized launch, not a normal code
   change.
4. **The active branch still has PARTIAL hardening tasks** (T1.2–T1.4,
   T1.8–T1.9, T2.1–T2.4, T3.1–T3.4, T6.2–T6.3). These are engineering
   gaps, not an edge.
5. **The H1 capture lost its bulk events.** The retained depth-only files
   cannot reproduce the original 5,962-snapshot score. The new recorder
   diagnostic suggests the original H1 “signal-starved” result was limited
   by capture depth, not the market — but it has no trade prints, so it
   cannot become a verdict.

### What would change this verdict

Only this sequence, in order, with owner-provided evidence:

1. A hypothesis reaches a **hash-bound PASS**: ≥300 trades, CI95 lower >0,
   positive at 2× cost, ≥60% non-negative days, drawdown in budget, Holm.
2. **14-day pessimistic paper** matches the confirmed expectancy.
3. **Demo drill PASS** with credentials only in the owner's environment,
   withdrawals disabled, IP allowlisted.
4. **WS latency p99 < 250 ms, drops < 0.1%**, fresh cost model, host check,
   watchdog heartbeat.
5. `cryptobot gate` writes **GO** from machine evidence.
6. Owner runs `cryptobot arm` on a real TTY, with the typed acknowledgement,
   small capital, daily loss cap, and 10-trade minimum-size canary.
7. Legal/tax jurisdiction and venue-access confirmation.

Until then, the correct action is **do not fund, do not arm, do not place
orders**. This is a negative research result plus a hardened simulator,
not a live trading system.

### What I will not do

- I will not fabricate a PASS verdict, GO gate, drill, latency report, or
  armed record.
- I will not flip `allow_live_submission` or remove the prod refusal to
  make the bot “trade.”
- I will not place real orders or handle live API keys.
- I will not describe an underpowered result as an edge.

### Next safe work available

- Extend fresh benchmark days and re-run H2/H4 honestly; H2 needs 10 more
  trades and H4 needs days ≥2026-10-20. This may still end underpowered.
- Finish the PARTIAL hardening tasks (stale-cache halt/refresher,
  leverage-bracket admission, fault-injection matrix, book-walk accounting).
- Port the stronger edge-repo arm checks (TTY/CI/positive capital/gate hash)
  into the active branch and enforce gate+armed before any future prod
  submission.
- Keep the recorder running and re-capture H1/H5 with full depth **and**
  aggTrade prints if those hypotheses are ever revisited.
