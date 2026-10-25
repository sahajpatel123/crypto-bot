"""F6.1: static daily dashboard (no server, no credentials)."""
from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path


def _load(path: Path, default: dict | None = None) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default or {}


def collect_status(*, recorder_root: str | Path = "data/recorder",
                   autopilot_root: str | Path = "research/autopilot",
                   risk_state: str | Path | None = None) -> dict:
    rec = Path(recorder_root)
    status = _load(rec / "status.json", {})
    manifest = _load(rec / "manifest.json", {})
    entries = manifest.get("entries", []) if isinstance(manifest, dict) else []
    total_records = sum(int(e.get("records", 0)) for e in entries)
    total_gaps = sum(int(e.get("gaps", 0)) for e in entries)
    bot = _load(Path(autopilot_root) / "registry.json", {})
    hyp_rows = []
    for hyp in sorted(bot.get("hypotheses", {})):
        state = _load(Path(autopilot_root) / "state" / f"{hyp}.json",
                      {"state": "REGISTERED"})
        hyp_rows.append({"hypothesis": hyp,
                         "state": state.get("state", "?"),
                         "power": state.get("power"),
                         "provenance": state.get("provenance", "OBSERVED")})
    risk = _load(Path(risk_state), {}) if risk_state else {}
    return {"generated_utc": datetime.now(UTC).isoformat(),
            "recorder": {"state": status.get("state", "UNKNOWN"),
                         "dropped": status.get("dropped", 0),
                         "chunks": len(entries),
                         "records": total_records,
                         "gaps": total_gaps,
                         "gap_rate": (total_gaps / total_records)
                         if total_records else 0.0},
            "hypotheses": hyp_rows,
            "risk": {"emergency_latched": risk.get("emergency_latched"),
                     "needs_reconciliation":
                     risk.get("needs_reconciliation"),
                     "profit_floor": risk.get("profit_floor")}}


def render_html(status: dict) -> str:
    rec = status["recorder"]
    rows = []
    for h in status["hypotheses"]:
        power = h.get("power") or {}
        eta = power.get("days_required")
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(h["hypothesis"])),
                html.escape(str(h["state"])),
                html.escape(f"{eta:.1f}" if isinstance(eta, (int, float))
                            else "n/a"),
                html.escape(str(h.get("provenance", "")))))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>cryptobot status</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;max-width:900px}}
td,th{{border:1px solid #ccc;padding:.35rem .6rem;text-align:left}}
.bad{{color:#a00}}.ok{{color:#060}}</style></head><body>
<h1>cryptobot status</h1>
<p>generated {html.escape(status["generated_utc"])}</p>
<h2>Recorder</h2>
<ul>
<li>state: <b>{html.escape(str(rec["state"]))}</b></li>
<li>chunks: {rec["chunks"]}, records: {rec["records"]},
    gaps: {rec["gaps"]} (rate {rec["gap_rate"]:.4%})</li>
<li>dropped: <span class="{'bad' if rec["dropped"] else 'ok'}">
    {rec["dropped"]}</span></li>
</ul>
<h2>Autopilot hypotheses</h2>
<table><tr><th>Hypothesis</th><th>State</th><th>Power ETA (days)</th>
<th>Provenance</th></tr>{''.join(rows)}</table>
<h2>Risk state</h2>
<pre>{html.escape(json.dumps(status["risk"], indent=1))}</pre>
</body></html>
"""


def write_dashboard(out: str | Path, **kwargs) -> dict:
    status = collect_status(**kwargs)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(status), encoding="utf-8")
    return status


__all__ = ["collect_status", "render_html", "write_dashboard"]
