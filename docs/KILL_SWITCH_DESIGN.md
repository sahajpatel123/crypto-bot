# Kill-switch design (GAP-1 proposal — no live wiring)

Status: **DESIGN ONLY**. This document proposes the missing live venue-wide
kill switch. It adds no live order path, no credential handling change, and
no background job. Nothing here is wired to a real venue. Implementation
requires explicit owner approval **and** a passing demo drill first.

Audited base: `live/trade-ready` from `v1.1.1` (`dcd82da`).

## 1. Problem

Every halt path that exists today either needs the session loop alive or
refuses the real venue:

| Path | Code | Limitation |
|---|---|---|
| `cryptobot stop --flatten` | `cli.py::cmd_stop` → `RunStore` stop request → `session.py::_run_stop_actions` | cooperative: the session loop must be alive to honour it |
| `enter_safe_mode` | `session.py:529` (halt entries + flatten + alert, never raises) | in-process only; a hung loop never gets there |
| `ops kill` | `cli_extra.py:134-140` | sandbox/emulator `Book` only; prod is explicitly REFUSED (`cli_extra.py:94-96`) |
| Risk halts + exit-only latching | `risk/policy.py`, `session.py` | in-process; correct, but same liveness dependency |
| Trading watchdog | `tools/watchdog.py` (stale heartbeat + exposure → owner `--flatten-cmd`) | no flatten command exists for it to call; nothing installed on this Mac |

If the session loop hangs with live exposure, the only outs are the Binance
UI by hand, or an unconfigured watchdog with no command to run. That gap is
GAP-1. This design closes it with one owner command plus the watchdog
wiring that invokes the exposure-reducing half of it.

## 2. Non-goals (hard)

- No new order entry path of any kind. The kill command can only reduce
  exposure (cancel, reduce-only flatten). This must hold by construction,
  not by flag discipline: the code path it calls accepts no side/qty that
  could open or add to a position.
- No gate loosening, no arm bypass, no auto-arm. The kill command never
  arms anything and never clears a latch by itself.
- No credential storage change. Credentials flow through the existing
  `security.py` paths only (Keychain or git-ignored 0600 file, trade-only
  keys, withdrawals disabled, IP allow-list). The command never prints key
  material and refuses keys that can withdraw, exactly like `run --mode
  prod` does today.
- No `countdownCancelAll` reliance: per the `tools/watchdog.py` header, it
  is unproven whether conditional stops survive it, so the design cancels
  explicitly (spot + algo/conditional) and then verifies.

## 3. Proposed UX: `cryptobot ops kill-live`

Name is a proposal; `kill-live` keeps it visually distinct from the
sandbox-only `ops kill`. Semantics:

```
cryptobot ops kill-live --config configs/demo.toml   # demo or prod config
```

Steps, in order, each journaled before and after:

1. **Human ceremony (interactive only).** Requires a TTY, the
   `CRYPTOBOT_ARM_ACK` environment acknowledgement, and a typed phrase
   (`KILL BTCUSDT` style: the venue + account alias, never a bare `yes`),
   mirroring the existing `arm` ceremony (`cli.py:1699-1747`). Refuses
   under CI/non-TTY exactly like `arm` does.
2. **Read-only snapshot.** `venue_status`: open orders (spot + conditional/
   algo), positions, balances. Printed for the owner; also the pre-image
   for the verify loop.
3. **Cancel-all.** Cancel every open order including conditional/algo
   orders, each cancel verified by re-query (a `-2013 unknown order` on a
   re-query after a cancel counts as cancelled, consistent with the
   existing `reconcile()` void-after-grace semantics in
   `execution/order_manager.py`).
4. **Flatten-all.** For each remaining position, a reduce-only order sized
   from the venue-reported position (never from local state), then re-query
   until the venue reports flat or a bounded retry budget (time + attempts)
   is exhausted.
5. **Verify loop.** Re-query `venue_status` until flat-and-no-open-orders,
   or escalate: exit non-zero, emit the `operator-kill` alert through the
   `_alert` sink seam with the residual exposure attached, and print the
   exact manual cleanup (symbol, side, qty per venue read).
6. **Halt latch.** On success (and on escalated failure), write a durable
   halt latch the session honours: extend the existing `RunStore`
   stop-request mechanism with a `kill-live` reason that (a) blocks entries
   on every path that checks `stop_requested`, (b) survives restart —
   a restarted session comes up halted, never trading — and (c) clears only
   via a second TTY ceremony (`cryptobot ops resume --clear-kill` or
   equivalent), never automatically and never from the watchdog.
7. **Idempotency.** Re-running with nothing to do prints the flat snapshot
   and exits 0. Repeated runs never re-alert for the same latch (same
   per-latch dedup the alert seam already does).

Exit codes: `0` flat-and-halted, `2` refused (no TTY / bad ceremony /
credentials missing or withdraw-capable / config not demo-or-prod),
`3` partial (residual exposure; alert emitted; manual cleanup printed).
No traceback on any refusal path, per the command-matrix standard.

Rate-limit behaviour: cancels and flattens run through the existing
`ExceptionPolicy` (429/418 Retry-After honoured, cancel capacity
reserved). A 418 ban mid-kill escalates to exit 3 with the alert — it must
never spin into an order storm.

## 4. Watchdog half: what the watchdog may and may not do

`tools/watchdog.py` already implements the trigger (heartbeat file stale
past `--max-age-s` **and** `has_exposure` true → run `--flatten-cmd` once,
exit 3). What is missing is (a) the heartbeat writer, (b) the command it
calls, (c) the install. This design fixes the interface:

- **Heartbeat writer (session side).** The session rewrites
  `runs/watchdog.json` every tick (`{"ts_utc", "has_exposure", "run_id"}`).
  `has_exposure` is true when local open orders/positions are non-empty OR
  the last venue read disagrees (fail-closed: unknown counts as exposed).
  Gate criterion stays as specified: heartbeat fresh (<90 s) when exposure
  exists (`watchdog_heartbeat_fresh`).
- **`--flatten-cmd` target.** A non-interactive entry point of the same
  kill implementation, e.g. `cryptobot ops kill-live --from-watchdog
  --auth <path>`, which:
  - runs steps 2–6 only (no ceremony), exposure-reducing only;
  - requires a pre-authorisation file the owner created via TTY (0600,
    binds config + run_id, expires ≤ 24 h like the gate);
  - refuses if the auth file is missing, expired, or names a different
    run/config — a stale watchdog must never flatten a new session's
    positions on a misunderstood heartbeat.
- **Install (macOS, proposal for Helix's runbook).** A dedicated
  `com.cryptobot.trade-watchdog` launchd job (name must not collide with
  the recorder's `com.cryptobot.watchdog`, which guards disk/stall — two
  different tools), running `tools/watchdog.py --heartbeat
  <runs/watchdog.json> --max-age-s 90 --flatten-cmd '<kill-live
  --from-watchdog ...>'` in a loop, plus log rotation and a
  launchd `ThrottleInterval`. Rollback is uninstall + delete the pre-auth
  file; the session is unaffected.
- **What the watchdog must never do:** clear the halt latch, place or
  re-place entry orders, touch credentials (they stay in the kill
  command's own environment per the `tools/watchdog.py` header), or run
  against a config the pre-auth does not name.

## 5. Proof plan (before any live use)

1. **Emulator now.** Drive the kill command against `MockEx`:
   kill-with-flat (exit 0, idempotent re-run), kill-with-open-orders (all
   cancelled), kill-with-position (flattened, venue re-queried flat),
   kill-during-hung-session (session thread wedged; kill runs in a
   separate process and still reaches flat), watchdog trigger
   (stale heartbeat + exposure → flatten-cmd runs once → exit 3),
   watchdog quiet (fresh heartbeat → exit 0, no command run),
   pre-auth expiry (refused, exit 2). Each a named test, offline.
2. **Demo venue later (owner steps, after keys + drill).** One real
   `kill-live` against `demo.toml` with a small demo position: cancel-all
   + flatten + latch verified by re-query; watchdog `--once` against a
   live heartbeat; the full loop only after (1) is green in CI.
3. **Gate evidence.** `watchdog_heartbeat_fresh` (<90 s + has_exposure)
   becomes passable only after install; the gate must keep failing on it
   until then — no placeholder passes.

## 6. Open questions for the owner (approval blockers)

1. Command name and typed-phrase wording (`kill-live` vs alternatives).
2. Pre-auth lifetime for `--from-watchdog` (proposal: ≤ 24 h, bound to
   run_id + config).
3. Whether the watchdog may flatten at all, or should be alert-only until
   the demo drill proves the kill path (proposal: alert-only first,
   flatten enabled only after demo proof).
4. Conditional-order inventory on the demo account (the owner finding
   procedure in `OWNER_ACTIONS.md`) so step 3's cancel set is complete.

## 7. Acceptance of this document

This design is done when it is reviewed (Verity), the interface in §4 is
agreed with Helix's install runbook, and the owner approves §6. Code comes
after, on a branch off this one, with the §5 emulator tests landing before
any demo-venue execution.
