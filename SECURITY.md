# SECURITY

## Secrets

- API keys come from the environment (`BINANCE_API_KEY`,
  `BINANCE_API_SECRET`) or a **0600** file. `cryptobot.security` refuses
  files with group/other permission bits and never returns key material
  in logs or readiness output.
- Demo/testnet keys are separate from production keys.
- No key, signature, listenKey or authorization header is ever written to
  fixtures, reports, journals or this repository.
- `deploy/.env.example` contains empty placeholders only. `.env` is
  git-ignored and must be `chmod 600`.

## Venue permissions (manual, unavoidable)

The API cannot prove withdrawal permissions without a signed endpoint.
`cryptobot readiness` emits this manual checklist:

1. Withdrawals disabled.
2. Trade-only key; no universal transfer.
3. IP allowlist set to the bot host.
4. Demo and production keys separated.

Do not arm until all four are confirmed in the Binance UI.

## Human-only arming

`cryptobot arm` refuses:
- non-interactive stdin (no TTY),
- CI environments (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `JENKINS_URL`,
  `BUILDKITE`, `TF_BUILD`),
- a missing/expired/NO-GO gate,
- a missing `CRYPTOBOT_ARM_ACK` phrase,
- a typed phrase mismatch,
- non-positive capital or daily loss.

The gate itself is NO-GO without machine evidence: GATE_READY autopilot
state, sealed (never synthetic) provenance, fresh calibrated cost model,
fresh host-check, fresh demo drill, measured WS latency/drops, and a fresh
watchdog heartbeat. There is no manual override flag.

## Network and host

- Recorder uses public endpoints only; no credentials in that process.
- Host firewall: deny inbound, allow outbound. No bot port is exposed.
- NTP/chrony is mandatory; `cryptobot host-check` fails closed when clock
  skew or venue RTT cannot be measured.
- The watchdog flatten command is owner-supplied via environment; it is
  never hardcoded and never uses `countdownCancelAll` (unproven stop
  preservation).

## Data integrity

- Recorder chunks are SHA-256 hash-chained; tampering is detected by
  `cryptobot recorder verify` and `cryptobot vault verify`.
- Vault CONFIRM access is logged in a hash-chained access log; denial,
  issue and read events are all recorded.
- Synthetic artifacts are stamped and rejected by gate/verdict.

## Reporting a vulnerability

Open a private issue with the owner; do not attach keys. Include the
commit, command, and the smallest reproduction with synthetic data.
