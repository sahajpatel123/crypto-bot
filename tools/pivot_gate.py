"""PIVOT-01 qualification gate (read-only, manager-owned).

Scores preregistered pivot economics against the frozen PIVOT-01 screen.
Never imputes: missing fields, missing coverage, or zero-trade cells yield
explicit NONE / DATA BLOCKED / UNRESOLVED verdicts with reasons — never a
pass, never a profit claim.

Inputs (all JSON):
  --realistic  economics file {"cells": [...]} under realistic costs
               (same shape as outputs/x1/economics_realistic.json)
  --adverse    economics file {"cells": [...]} under adverse (2x) costs
  --manifest   PIVOT-01.json preregistration (selection rule + screens)
  --coverage   optional {"<config_id>|<split>": {"days": float}} mapping.
               Absent a config|split entry, covered days are UNKNOWN and
               the config cannot qualify (DATA BLOCKED, not failed).

Output: verdict JSON {"verdict": ..., "configs": {...}} to --out,
plus a one-line human summary on stdout.

Exit codes: 0 verdict written (any verdict, incl. NONE/BLOCKED);
2 input/contract error (missing file, bad shape, manifest mismatch).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXIT_BLOCKED = 2

REQUIRED_CELL_FIELDS = (
    "config_id", "split", "ledger_net", "closed_positions",
    "n_fills", "intents_admitted",
)


def _load_json(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})")


def _cells_by_config(doc: dict, path: str) -> dict[str, dict[str, dict]]:
    if not isinstance(doc, dict) or not isinstance(doc.get("cells"), list):
        raise ValueError(f"{path}: expected {{\"cells\": [...]}}")
    out: dict[str, dict[str, dict]] = {}
    for i, cell in enumerate(doc["cells"]):
        if not isinstance(cell, dict):
            raise ValueError(f"{path}: cell {i} is not an object")
        missing = [f for f in REQUIRED_CELL_FIELDS if f not in cell]
        if missing:
            raise ValueError(
                f"{path}: cell {i} missing fields {missing}")
        cfg = str(cell["config_id"])
        split = str(cell["split"])
        for num_field in ("ledger_net", "closed_positions", "n_fills",
                          "intents_admitted"):
            val = cell[num_field]
            if not isinstance(val, (int, float)) or val != val:
                raise ValueError(
                    f"{path}: cell {i} field {num_field!r} not numeric")
        out.setdefault(cfg, {})[split] = cell
    return out


def _mechanism(dev: dict, val: dict) -> str:
    intents = (dev.get("intents_admitted", 0) or 0) + \
        (val.get("intents_admitted", 0) or 0)
    fills = (dev.get("n_fills", 0) or 0) + (val.get("n_fills", 0) or 0)
    if intents == 0:
        return "UNTESTED (zero intents admitted)"
    if fills == 0:
        return "BLOCKED (intents admitted, zero fills)"
    return "SCORED"


def _family_of(config_id: str, families: dict) -> str | None:
    """Map a config_id to its preregistered family (exact or prefix)."""
    if config_id in families:
        return config_id
    for fam in sorted(families, key=len, reverse=True):
        if config_id.startswith(fam + "-"):
            return fam
    if config_id == "CASH" or config_id.endswith("-CASH"):
        return "CASH"
    return None


def evaluate(realistic: dict[str, dict[str, dict]],
             adverse: dict[str, dict[str, dict]],
             manifest: dict,
             coverage: dict) -> dict:
    min_positions = 100
    min_days = 10.0
    eligible_roles = {"candidate"}
    families: dict[str, dict] = {}
    for c in manifest.get("families", []):
        key = c.get("config_id", c.get("family"))
        if key:
            families[str(key)] = c
    role_of = {k: c.get("role", "candidate") for k, c in families.items()}
    for c in manifest.get("configs", []):
        if c.get("config_id"):
            role_of[c["config_id"]] = c.get("role", "candidate")
    manifest_configs = {c.get("config_id") for c in
                        manifest.get("configs", [])}
    # A preregistration that names families enrolls ONLY configs of
    # candidate families (P1-R1 -> P1). Controls (CASH) never advance
    # and unenrolled configs (e.g. re-entered X1/S1) cannot qualify,
    # per the frozen selection rule. An empty manifest keeps legacy
    # descriptive scoring (existing unit fixtures).

    per_config: dict[str, dict] = {}
    for cfg, splits in sorted(realistic.items()):
        dev = splits.get("dev") or splits.get("development") or {}
        val = splits.get("validation") or splits.get("val") or {}
        adv_val = (adverse.get(cfg, {}).get("validation")
                   or adverse.get(cfg, {}).get("val") or {})
        reasons: list[str] = []
        dev_net = float(dev.get("ledger_net", 0.0)) if dev else 0.0
        val_net = float(val.get("ledger_net", 0.0)) if val else 0.0
        adv_net = float(adv_val.get("ledger_net", 0.0)) if adv_val else 0.0
        val_closed = int(val.get("closed_positions", 0)) if val else 0
        mechanism = _mechanism(dev, val) if (dev or val) else \
            "UNTESTED (no dev/val cells)"
        if not dev or not val:
            reasons.append("missing dev or val cell")
        if not adv_val:
            reasons.append("missing adverse val cell")
        cov_key = f"{cfg}|validation"
        cov = coverage.get(cov_key, coverage.get(f"{cfg}|val"))
        days = None
        if isinstance(cov, dict) and isinstance(cov.get("days"),
                                                (int, float)):
            days = float(cov["days"])
        else:
            reasons.append("covered days UNKNOWN (no coverage entry)")
        if mechanism.startswith("UNTESTED"):
            reasons.append("zero intents: strategy untested, not disproven")
        elif mechanism.startswith("BLOCKED"):
            reasons.append("zero fills: admission without fills "
                           "(gate/latch, not strategy evidence)")
        if val_closed < min_positions:
            reasons.append(f"screen: {val_closed} < {min_positions} "
                           f"VAL closed positions")
        if days is not None and days < min_days:
            reasons.append(f"screen: {days} < {min_days} covered days")
        if not (dev_net > 0 and val_net > 0):
            reasons.append(f"nets fail dev>0&val>0 "
                           f"(dev={dev_net}, val={val_net})")
        if adv_val and not (adv_net > 0):
            reasons.append(f"adverse val net <= 0 ({adv_net})")
        family = _family_of(cfg, families)
        if families:
            enrolled = cfg in manifest_configs or (
                family is not None
                and role_of.get(family) in eligible_roles)
            role_ok = enrolled
            if family is not None and \
                    role_of.get(family) not in eligible_roles:
                reasons.append(
                    f"control ({family} reference): never advances")
            elif not enrolled:
                reasons.append(
                    f"not enrolled: config {cfg} maps to no candidate "
                    f"family in preregistration (re-entry excluded)")
            elif family is not None:
                target = families[family].get("min_target_bps")
                if not isinstance(target, (int, float)) or target <= 0:
                    reasons.append(
                        f"family {family}: min_target_bps not declared "
                        f"at preregistration")
        else:
            enrolled = (not manifest_configs) or (cfg in manifest_configs)
            role_ok = role_of.get(cfg, "candidate") in eligible_roles \
                if role_of else True
        data_blocked = days is None or days < min_days \
            or val_closed < min_positions
        qualifies = (not reasons) and enrolled and role_ok \
            and not data_blocked
        status = "QUALIFIED" if qualifies else (
            "REJECTED" if (families and not role_ok) else (
                "DATA BLOCKED" if data_blocked else "REJECTED"))
        per_config[cfg] = {
            "dev_net": dev_net, "val_net": val_net,
            "adverse_val_net": adv_net if adv_val else None,
            "val_closed": val_closed,
            "covered_days": days,
            "mechanism": mechanism,
            "status": status,
            "reasons": reasons,
        }
    qualified = [c for c, r in per_config.items()
                 if r["status"] == "QUALIFIED"]
    winner = None
    if qualified:
        winner = sorted(
            qualified,
            key=lambda c: (-per_config[c]["val_net"],
                           -per_config[c]["dev_net"], c))[0]
        verdict = f"QUALIFIED: {winner} (advances to TEST, scored once)"
    elif any(r["status"] == "DATA BLOCKED"
             for r in per_config.values()):
        verdict = "NONE (DATA BLOCKED — screen unmet, RESEARCH UNRESOLVED)"
    else:
        verdict = "NONE (no candidate qualifies — RESEARCH UNRESOLVED)"
    return {"verdict": verdict, "winner": winner,
            "screens": {"min_val_closed": min_positions,
                        "min_covered_days": min_days,
                        "rule": "dev>0 & val>0 realistic & val>0 adverse"},
            "configs": per_config}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PIVOT-01 qualification gate (read-only)")
    parser.add_argument("--realistic", required=True)
    parser.add_argument("--adverse", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--coverage", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        realistic = _cells_by_config(_load_json(args.realistic),
                                     args.realistic)
        adverse = _cells_by_config(_load_json(args.adverse), args.adverse)
        manifest = _load_json(args.manifest)
        coverage = _load_json(args.coverage) if args.coverage else {}
        if not isinstance(coverage, dict):
            raise ValueError(f"{args.coverage}: expected object mapping")
        result = evaluate(realistic, adverse, manifest, coverage)
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True)
                        + "\n", encoding="utf-8")
    n = len(result["configs"])
    print(f"{result['verdict']} [{n} configs -> {args.out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
