"""F2.2 calibration: fit fill-model params from fills; never relax.

Reads fills JSONL (slippage_bps, latency_ms, spread_bps per fill) and
writes a versioned cost-model JSON. The fitted adverse component is
the max(previous, fitted p75) — automatic updates only ever make the
model MORE conservative; relaxing needs a fresh verdict (human step).
"""
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path


def _p75(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(0.75 * len(s)))]


def calibrate(fills_path, out_path, *, previous: dict | None = None,
              version: int = 1) -> dict:
    rows = [json.loads(ln) for ln in
            Path(fills_path).read_text().splitlines() if ln.strip()]
    prev = (previous or {}).get("fill_params", {})
    fitted = {
        "spread_bps": round(_p75([float(r.get("spread_bps", 3.0))
                                  for r in rows]), 3),
        "depth_bps": float(prev.get("depth_bps", 5.0)),
        "latency_bps": round(_p75([float(r.get("latency_ms", 0.0))
                                   for r in rows]) / 10.0, 3),
        "adverse_bps": round(_p75([abs(float(r.get("slippage_bps", 0.0)))
                                   for r in rows]), 3),
    }
    # Monotonic conservatism (F2.2): never auto-relax any component.
    for k, v in list(fitted.items()):
        if k in prev:
            fitted[k] = max(float(prev[k]), v)
    doc = {"calibration": "fill-params", "version": version,
           "n_fills": len(rows), "fill_params": fitted,
           "created_utc": datetime.now(timezone.utc).isoformat()}
    Path(out_path).write_text(json.dumps(doc, indent=1) + "\n")
    return doc
