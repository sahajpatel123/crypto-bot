"""Zone evidence checker (read-only, manager-owned).

Verifies that every zone in coord/pivot/ZONES.json cites evidence that
exists and parses. It NEVER grants readiness: statuses in ZONES.json are
manager-signed records, and overall readiness additionally requires a
human sign-off the tool cannot produce.

Check kinds:
  exists  — path exists under the repo root.
  verdict — path is JSON whose dotted key contains the expected substring.
  (A zone with no evidence checks reports EVIDENCE-EMPTY, never OK.)

Exit codes: 0 check completed (any outcome); 2 bad manifest/IO error.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXIT_BLOCKED = 2


def _load_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})")
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return doc


def _dotted(doc: dict, key: str):
    cur: object = doc
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise ValueError(f"key {key!r} not found")
        cur = cur[part]
    return cur


def check_zones(manifest: dict, repo: Path) -> dict:
    zones = manifest.get("zones")
    if not isinstance(zones, dict) or not zones:
        raise ValueError("manifest: expected non-empty 'zones' object")
    per_zone: dict[str, dict] = {}
    for zid in sorted(zones):
        zone = zones[zid]
        if not isinstance(zone, dict):
            raise ValueError(f"manifest: zone {zid!r} is not an object")
        status = zone.get("status", "?")
        evidence = zone.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError(f"manifest: zone {zid!r} evidence not a list")
        problems: list[str] = []
        checked = 0
        for i, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise ValueError(
                    f"manifest: zone {zid!r} evidence {i} not an object")
            kind = item.get("kind")
            rel = item.get("path", "")
            target = repo / rel
            if kind == "exists":
                checked += 1
                if not target.exists():
                    problems.append(f"missing: {rel}")
            elif kind == "verdict":
                checked += 1
                try:
                    doc = _load_json(target)
                    value = str(_dotted(doc, str(item.get("key", ""))))
                except ValueError as exc:
                    problems.append(f"{rel}: {exc}")
                    continue
                want = str(item.get("contains", ""))
                if want not in value:
                    problems.append(
                        f"{rel}: key {item.get('key')!r} lacks {want!r}")
            else:
                raise ValueError(
                    f"manifest: zone {zid!r} evidence {i} unknown kind "
                    f"{kind!r}")
        state = ("EVIDENCE-EMPTY" if checked == 0
                 else ("EVIDENCE-OK" if not problems
                       else "EVIDENCE-STALE"))
        per_zone[zid] = {"status": status, "evidence_state": state,
                         "checked": checked, "problems": problems}
    n_ok = sum(1 for z in per_zone.values()
               if z["evidence_state"] == "EVIDENCE-OK")
    return {"zones": per_zone,
            "summary": (f"EVIDENCE {n_ok}/{len(per_zone)} zones OK; "
                        "readiness is manager-signed, never auto-passed")}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Zone evidence checker (read-only)")
    parser.add_argument("--zones", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        manifest = _load_json(Path(args.zones))
        result = check_zones(manifest, Path(args.repo))
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"{result['summary']} [{args.out}]")
    for zid, z in result["zones"].items():
        print(f"  {zid}: {z['status']} / {z['evidence_state']}"
              + (f" :: {'; '.join(z['problems'])}" if z["problems"]
                 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
