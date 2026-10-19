#!/bin/sh
# Z1.4 clean-room proof of tag v1.0-closeout. Logs stay under release/.
set -u
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
CLONE="${CLEANROOM_DIR:-/tmp/cryptobot-v1-cleanroom}"
LOG="$ROOT/release/cleanroom.log"
exec >"$LOG" 2>&1
set -x
rm -rf "$CLONE"
git clone --branch release/v1 "$ROOT/release/v1.0-closeout.bundle" "$CLONE"
cd "$CLONE"
git rev-parse HEAD
git describe --tags --exact-match HEAD || git describe --tags
ln -s "$ROOT/data/lake" data/lake
uv sync --locked
uv sync --locked --extra dev
uv run --locked --extra dev python -m pytest -q --tb=line
echo "PYTEST_RC:$?"
uv run --locked --extra dev cryptobot acceptance --full --root /tmp/cryptobot-v1-acceptance
echo "ACCEPT_RC:$?"
uv run --locked --extra dev cryptobot gate --out /tmp/cryptobot-v1-gate.json
echo "GATE_RC:$?"
python3 -c 'import json; print("GATE", json.load(open("/tmp/cryptobot-v1-gate.json"))["gate"])'
rm -f /tmp/cryptobot-v1-gate.json
uv run --locked --extra dev cryptobot arm --capital-usdt 120 --max-daily-loss 1 --out /tmp/cryptobot-v1-armed.json
echo "ARM_RC:$?"
rm -f /tmp/cryptobot-v1-armed.json
uv run --locked --extra dev python - << 'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, "tools")
from run_family_b import evaluate_hypothesis

def cmp(hyp):
    committed = json.loads(Path(f"research/autopilot_b/dev/{hyp}.json").read_text())
    fresh = evaluate_hypothesis(hyp, Path("data/lake/dev"), equity=1000.0)
    keys = ("best_oos_sharpe", "turnover", "dsr", "pbo", "sharpe_2x", "drawdown", "pass")
    diffs = {}
    for k in keys:
        a = committed["gates"].get(k)
        b = fresh["gates"].get(k)
        if a != b:
            diffs[k] = [a, b]
    cell = committed.get("cell_sharpes") != fresh.get("cell_sharpes")
    print(hyp, "MATCH" if not diffs and not cell else "DIFF", json.dumps({"diffs": diffs, "cells_differ": cell, "best": fresh.get("best_cell")}))

cmp("B1")
cmp("B6")
PY
echo "REDERIVE_RC:$?"
echo CLEANROOM_DONE
