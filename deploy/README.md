# cryptobot deployment kit (F2.4)

Everything here is a template: no secrets. Keys are read from the
environment or a 0600 file at run time. The recorder uses only public
data and can run before any key exists.

## Services

| Unit | Purpose |
|---|---|
| `cryptobot-bot.service` | paper/live session (submission gated) |
| `cryptobot-recorder.service` | standalone public-data recorder |
| `cryptobot-watchdog.service` | external stale-heartbeat flattener |
| `cryptobot-autopilot.service` / `.timer` | daily research state machine |
| `cryptobot-dashboard.timer` | static dashboard refresh |

## First run

```sh
sudo bash deploy/bootstrap-ubuntu.sh
cp deploy/.env.example /etc/cryptobot.env && sudo chmod 600 /etc/cryptobot.env
sudo systemctl daemon-reload
sudo systemctl enable --now cryptobot-recorder
uv run --locked cryptobot recorder status --out data/recorder
```

Do not start `cryptobot-bot` in prod until `gate` is GO and `arm` has
been run interactively by the owner. `cryptobot-bot.service` passes
`--mode paper` by default.
