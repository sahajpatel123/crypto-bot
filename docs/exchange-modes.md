# Exchange modes: paper vs demo vs prod

CORRECTION (Oct 2026 review): credential-free public-data paper trading
needs NO API keys. Only the credentialed demo path needs demo keys, and
only signed readiness checks need prod keys. The earlier handoff line
claiming a "live-feed paper session require[s] owner-supplied demo keys"
was wrong for the Nautilus paper path and is superseded by this document.

## 1. Credential-free paper (public data, simulated fills)

- Command (bounded, no keys in the environment):
  `python3 tools/run_budget.py --budget-s 1500 --checkpoint-dir <ckpt> --report-out <report> -- cryptobot run --mode paper --config configs/r2.toml --duration 20m`
- Engine: `nautilus` (local simulation on live public websocket feeds).
  The Nautilus branch of `cli._run_paper` reads no credential variables.
- Stops: entries stop early enough to close permitted exposure and
  reconcile before the deadline; `--duration` is the session budget.

## 2. Credentialed demo (demo venue, real mechanics, fake money)

- Command (bounded, keys from the OWNER'S environment only):
  `BINANCE_DEMO_KEY=... BINANCE_DEMO_SECRET=... python3 tools/run_budget.py --budget-s 1500 --checkpoint-dir <ckpt> --report-out <report> -- cryptobot run --mode paper --config configs/demo.toml --duration 20m`
- Engine: `live` + `demo = true` → `https://demo-fapi.binance.com` only.
  The adapter refuses `demo=true` with the production host.
- Missing keys → the CLI refuses with exit 2 (demo guard intact).
- Demo verifies exchange mechanics; demo profits do not validate an edge.

## 3. Read-only readiness (signed venue checks, never submits)

- `cryptobot readiness --config configs/demo.toml` (demo keys) or
  `cryptobot readiness --config configs/prod.toml` (prod keys).
- Unsigned checks (config, host pinning, no inline secrets, default-off
  submission) always run. Signed checks (clock skew, permissions,
  position mode, fees, filters, positions, orders, balances) use GET
  requests only and report BLOCKED when credentials are absent.
- Exit codes: 0 READY, 2 FAIL, 3 BLOCKED-on-credentials.
- Credential values are never printed (only set/MISSING + key fingerprint).

## 4. Production (implemented routing, submission DISABLED)

- `cryptobot run --mode prod --config configs/prod.toml` verifies guards
  (prod host pinned exactly to `https://fapi.binance.com`, no demo/testnet,
  default-off submission) and then REFUSES with exit 2: production order
  submission is disabled for this assignment. Enablement requires an
  explicit future code + owner-authorization step — never a config flip.
- `tools/preflight.py` is CONFIGURATION-ONLY: it validates files, never
  signs a request, and its CONFIG-READY verdict is not account readiness
  and not a production GO.

## Host separation summary

| Path | Host | Default? |
|---|---|---|
| demo paper | `https://demo-fapi.binance.com` | yes for demo=true |
| testnet (adapter fallback) | `https://testnet.binancefuture.com` | yes for live non-demo without base_url |
| production | `https://fapi.binance.com` | NEVER; explicit base_url only |
