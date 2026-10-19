"""Phase B: score all 10 gated cells into economic panels (Worker 4, CORR)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.research.scoring import score_cell  # noqa: E402

ROOT = Path("/Users/sahajpatel/Code/cryto-bot")
OUT = Path("/tmp/w4-phaseb")
CAPTURE = {
    "cap30min": ROOT / "data/captures/cap-30min/events.jsonl",
    "cap2h": ROOT / "data/captures/cap-2h/events.jsonl",
}
ARMS = ["S1", "S2", "S3", "S4", "CASH"]


def main() -> int:
    (OUT / "panels").mkdir(exist_ok=True)
    index = {}
    for slice_ in ("cap30min", "cap2h"):
        for arm in ARMS:
            cell = f"R01-{arm}-{slice_}"
            run_dir = OUT / cell / "runs/mechanism" / arm
            dest = OUT / "panels" / f"{cell}.json"
            if not run_dir.exists():
                index[cell] = {"status": "MISSING", "run_dir": str(run_dir)}
                continue
            panel = score_cell(run_dir, capture_path=CAPTURE[slice_])
            panel["cell"] = cell
            panel["arm"] = arm
            panel["slice"] = slice_
            dest.write_text(json.dumps(panel, indent=2), encoding="utf-8")
            index[cell] = {
                "status": "SCORED",
                "closed": panel["closed_trades"],
                "net": panel["booked"]["net"],
                "panel": str(dest),
            }
    (OUT / "panels/index.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8")
    print(json.dumps(index, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
