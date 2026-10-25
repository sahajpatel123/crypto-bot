# E1 loopback rehearsal evidence

This evidence is from the in-repository MockEx emulator bound to `127.0.0.1`, using process-only generated FAKE credentials. It is not a Binance demo-host rehearsal and is not a live-edge or production-readiness claim.

- `drill.json`: owner drill reached auth/modes, tiny entry acknowledgement and fill, server-acknowledged protection attach, flatten, and PASS.
- `readiness.txt`: signed checks reached MockEx, but the CLI correctly exited 2 because the loopback URL fails the exact demo-host pin. Treat this as loopback transport evidence only, not a readiness PASS.
- `reconcile.txt`: read-only `--expect-flat` succeeded after the drill.
- MockEx reports `canWithdraw=false` to exercise the readiness PASS branch; that does not establish a real API key's withdrawal permission. If a real demo response omits `canWithdraw`, readiness now reports UNVERIFIED and exits 3; a reported `true` fails readiness. The owner must confirm the real demo key in the demo UI.

No real credential, live venue, private Binance endpoint, or holdout dataset was used.
