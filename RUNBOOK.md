# RUNBOOK

All commands assume the project venv. Never place an order while
debugging. Replay and the localhost emulator come first. The gate is
NO-GO. There is no demonstrated edge.

Hermetic check: `cryptobot selftest --all`.
Operator actions on the emulator: `cryptobot ops status --mode emulator`.
Full ops list: `status`, `positions`, `orders`, `pause`, `resume`,
`cancel-all`, `cancel --client-id <id>`, `flatten [--symbol <s>]`,
`kill` (cancel-all + flatten + halt), `order --kind MARKET|LIMIT|
STOP_MARKET|TAKE_PROFIT_MARKET [--price <p>] [--stop-price <p>]
[--post-only] [--reduce-only] [--client-id <id>]`.
Background jobs: `cryptobot background status` (free disk, projected
disk days, recorder gap %, next adjudication date; notifies when the
projection is shorter than the wait). `install`/`uninstall` wrap
`deploy/macos/*.sh`; jobs run after completion and never block it.
Daily gaps: `cryptobot autopilot report` includes the recorder gap %
(`--recorder-root`, `--no-notify`); above 5% it posts a notification.
Owner steps: `cryptobot owner` (resumable via `--step <name>`).
Certificate: `cryptobot certify --out COMPLETION_CERTIFICATE.md
--matrix-out COMMAND_MATRIX.md` (fails unless selftest is 100% PASS).
Adjudication clock: T0 = first sealed recorder chunk, T = T0+90d,
C1 final = min(T+14, max(T, first day with 90 forward days)).
Prod ops refuse without a human arm. A real demo drill is an owner step
(`cryptobot owner`), not something the emulator can satisfy.

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
1. The watchdog (`deploy/macos/watchdog.py`, every 60s) stops the
   recorder at the 8192 MB guard; the recorder plist runs under
   `caffeinate -is` so sleep does not silently gap the capture.
2. Stop the recorder cleanly (`cryptobot recorder stop`) if still running.
3. Move sealed chunks to cold storage; never delete a chunk referenced by
   the manifest without updating the vault registry through tooling.
4. Free space, restart, `cryptobot recorder verify`.

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

## Lake pull stalls or fails files

Symptom: `vision_pull.py pull` exits non-zero or `report` shows gaps.
1. Read the state failures (`pull-*.json`): checksum mismatches vs 404s
   vs timeouts have different causes (re-try, delisted key, backoff).
2. Re-run the same `pull` command: completed files resume from state;
   only pending/failed keys are retried.
3. CJK symbol names need percent-encoded URLs (fixed in the tool; older
   plans must be rebuilt).
4. Never hand-edit a zip into place: `verify` re-hashes everything.

## Lake build breaks on a file

Symptom: `build_lake` raises on a zip (shape/units/columns).
1. The failure names the file: inspect its first rows (DEV files only —
   holdout bytes must never be decoded outside `verdict`).
2. Vision drifts formats (kline header rows appear on newer listings);
   extend the reader + add a fixture test, never a silent skip.
3. Re-run the build; `verify_lake_manifest` must be clean after.

## Holdout seal/eligibility problems

Symptom: `vault holdout-eligible` false, or `verdict` REFUSED.
1. `holdout-eligible` false + "not frozen": freeze first
   (`vault freeze` with the committed config hash).
2. "pre-freeze decode": the chunk was decoded before the freeze — it can
   never confirm that hypothesis. Seal a fresh window, do not override.
3. `verify-holdout` lists bad/missing files: re-pull the exact keys,
   re-seal as a NEW chunk (never rewrite a sealed manifest).

## Monthly lake refresh (owner/operator)

1. Run the pull with a new plan (same datasets); new months land in
   `holdout_raw/` or FORWARD per filename date (DEV never grows).
2. FORWARD files (dated after ingestion end) feed forward-paper only.
3. Re-run `report` + `verify`; append the monthly summary to the lake
   report. Never re-cut DEV/HOLDOUT: the split is frozen in
   `research/prereg/SPLIT.md`.
