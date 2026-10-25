# netshim — DNS-sinkhole fallback for exchange hostnames (opt-in)

**Problem.** Some ISP resolvers (observed: Reliance Jio, India) answer `*.binance.com`
and `*.okx.com` with a sinkhole address (`49.44.79.236`), a dead host, so every TCP connect
times out. It is **not** a VPN or geo-block: with the real addresses (from `1.1.1.1` /
`8.8.8.8`) REST returns 200 and the websocket upgrade returns 101. `data.binance.vision`,
`testnet.binancefuture.com` and `api.bybit.com` are not sinkholed.

**What this does.** With `CRYPTOBOT_DOH=1`, `socket.getaddrinfo` re-resolves only the
suffixes `binance.com,okx.com` through DNS-over-HTTPS endpoints addressed by IP
(`1.1.1.1`, `8.8.8.8`, `1.0.0.1`, `8.8.4.4`), caches by TTL (30-300 s), serves a stale
answer if DoH fails, and otherwise falls back to the system resolver. The connection is
still made to the original hostname, so SNI and certificate checks are unchanged. It
discards loopback/private/link-local answers. **Default is OFF**; turn it on only where
`cryptobot host-check` reports `dns-sinkhole FAIL`.

Two ways in, one implementation (the core block is byte-identical; a test enforces it):

| Use | How |
|---|---|
| Any `cryptobot` command or `tools/*.py` network tool | `export CRYPTOBOT_DOH=1` (they call `netguard.install_from_env()`) |
| A process that does not import cryptobot (recorder from an old tree, other scripts) | put **this directory** on `PYTHONPATH`, plus `CRYPTOBOT_DOH=1` (`sitecustomize.py` self-installs, stdlib only, chains to the interpreter's own sitecustomize) |

Optional: `CRYPTOBOT_DOH_SUFFIXES=binance.com,okx.com` (comma list).

## Exact lines

Copy the directory somewhere stable first (the recorder's tree may be older than the repo):

```sh
mkdir -p ~/.cryptobot/netshim && cp tools/netshim/sitecustomize.py ~/.cryptobot/netshim/
```

**Shell**

```sh
export CRYPTOBOT_DOH=1
export PYTHONPATH="$HOME/.cryptobot/netshim${PYTHONPATH:+:$PYTHONPATH}"   # only if cryptobot itself is not new enough
cryptobot host-check            # dns-sinkhole should now read PASS (mitigated) or PASS
```

**launchd** (`~/Library/LaunchAgents/com.cryptobot.recorder.plist`, inside the top `<dict>`)

```xml
<key>EnvironmentVariables</key>
<dict>
  <key>CRYPTOBOT_DOH</key><string>1</string>
  <key>PYTHONPATH</key><string>/Users/YOU/.cryptobot/netshim:/Users/YOU/Code/cryto-bot-edge/src</string>
</dict>
```

then `launchctl bootout gui/$(id -u)/com.cryptobot.recorder; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cryptobot.recorder.plist`.
Never start a second recorder: check `ps -axo pid,command | grep 'cryptobot.cli recorder'` first.

**systemd** (`cryptobot-recorder.service`, `[Service]`)

```ini
Environment=CRYPTOBOT_DOH=1
Environment=PYTHONPATH=/opt/cryptobot/netshim
```

then `systemctl daemon-reload && systemctl restart cryptobot-recorder`.

## Alternatives and limits

- Setting a public DNS (1.1.1.1 / 8.8.8.8) in the OS network settings fixes it for every
  program and needs no shim. Use this if you can.
- IPv4 only (A records). A caller that explicitly requests `AF_INET6` gets the system answer.
- With an HTTPS proxy the proxy resolves the exchange name, so the shim is not involved.
- Editing `core` here by hand is wrong: edit `src/cryptobot/netguard.py`, then
  `python tools/netshim/sync_core.py`.
