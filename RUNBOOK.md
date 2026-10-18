# RUNBOOK

All commands assume `/opt/cryptobot` and the project venv. Never place an
order while debugging; replay/sandbox first.

## Unknown order outcome

Symptom: journal/engine reports `UNKNOWN`, `unknown-entry-submit`, or a
submit timed out.
1. `cryptobot reconcile --config <cfg>` — read-only venue truth.
2. Do not retry the same client id. `lookup` resolves it.
3. If exposure exists and no stop is live, flatten reduce-only:
   `cryptobot stop --run-id <id> --flatten` (or the watchdog command).
4. Record the client id and checkpoint in the incident log. Entries stay
   halted until the unknown set is empty.

## Naked position

Symptom: ledger/venue has exposure, no verified stop.
1. Flatten reduce-only immediately (`cryptobot stop --flatten`).
2. If flatten is rejected, use the venue UI/owner flatten command; do not
   open a hedge.
3. After flat, `cryptobot reconcile --expect-flat`.
4. Check `protection-*` checkpoints and attach failures.

## Stale data / WS gap

Symptom: `stream-stall`, `feed-drop-breaker`, `gap` markers.
1. Entries are already halted by the breaker.
2. `cryptobot recorder verify` for the interval; note gap rate.
3. Wait for resync (`re-prime`) or restart the recorder.
4. Do not clear the halt manually; it releases on a clean window.

## 418 / 429 ban

Symptom: `RateLimitedError`, HTTP 418/429.
1. Stop submitting; the engine refuses fast for the backoff window.
2. Check weight usage and API-key IP allowlist.
3. Wait for the ban to expire; do not rotate keys to evade it.
4. After expiry, `readiness` + `reconcile`, then resume.

## Clock skew

Symptom: `clock:skew-*`, signature errors, `recvWindow` rejection.
1. `chronyc tracking` / `timedatectl`.
2. `cryptobot host-check` (must PASS).
3. Do not arm or resume until skew is inside the safety margin.

## Exchange outage

Symptom: repeated 5xx/timeouts, venue status not TRADING.
1. Entries halt/safe-mode; flatten attempts are bounded.
2. Keep the watchdog running with a working flatten command.
3. Poll `cryptobot readiness`; resume only after full reconcile.

## Crash loop

Symptom: systemd restart loop, `StartLimitBurst` hit.
1. `journalctl -u cryptobot-bot -n 200`.
2. Inspect `runs/<id>/watchdog.json`, `risk.jsonl`, `report.json`.
3. Fix the cause; clear only the specific stale lock/unknown state after
   reconciliation. Never delete risk-state history.

## Disk full

Symptom: recorder `disk-budget-exceeded`, write errors.
1. Stop the recorder cleanly (`cryptobot recorder stop`).
2. Move sealed chunks to cold storage; never delete a chunk referenced by
   the manifest without updating the vault registry through tooling.
3. Free space, restart, `cryptobot recorder verify`.

## Recorder gap

Symptom: `verify` gap rate > 0 or `gaps` in the manifest.
1. Note the interval and stream.
2. Do not use the gapped interval as CONFIRM data.
3. Restart the recorder; confirm sequence continuity resumes.

## Watchdog fired

Symptom: `watchdog: TRIGGERED`, exit 3.
1. Assume exposure; run the configured flatten command.
2. `cryptobot reconcile --expect-flat`.
3. Inspect why the heartbeat was stale (process hang, disk, OOM).
4. Do not restart the bot until flat and reconciled.

## Gate NO-GO

Normal today. Read `gate.json` `checks`; fix the first false check. Never
edit gate.json by hand; re-run `cryptobot gate` with fresh evidence.
