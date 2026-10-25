# E1 loopback rehearsal evidence

This evidence is from the in-repository MockEx emulator bound to `127.0.0.1`, using process-only generated FAKE credentials. It is not a Binance demo-host rehearsal and is not a live-edge or production-readiness claim.

- `drill.json`: owner drill reached auth/modes, tiny entry acknowledgement and fill, server-acknowledged protection attach, flatten, and PASS.
- `readiness.txt`: signed checks reached MockEx, but the CLI correctly exited 2 because the loopback URL fails the exact demo-host pin. Treat this as loopback transport evidence only, not a readiness PASS.
- `reconcile.txt`: read-only `--expect-flat` succeeded against a separately started MockEx instance. Its port and account tag differ from `readiness.txt`, so it proves only that second emulator account was flat; it does not prove the drill account was flat.
- MockEx reports the account field `canWithdraw=false`; that does not establish the API key's withdrawal restriction. Readiness therefore reports withdrawals UNVERIFIED (rather than PASS) for this API surface; an account `canWithdraw=true` fails closed. The owner must confirm the real demo key in the demo UI.

No real credential, live venue, private Binance endpoint, or holdout dataset was used.
