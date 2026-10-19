"""ROUND-01 allowlist enforcement + parameter fingerprints (Worker 4, CORR).

Correction for the handoff finding "ROUND-01 and the runtime selection
disagree": ROUND-01 excludes S2-V/S2-F but ``arms=all`` resolves them,
and prior reports' "18 arms" mislabels evaluation row labels as
configurations. Exact accounting: arms=all yields 11 distinct S1-S4 arm
IDs; the "18" counts row labels = 4 base arms + 7 variant arms x 2
directions (e.g. "S1-V:LONG"). Configurations are arm IDs, not rows:
ROUND-01 allows 9 strategy arms (+COMBINED/CASH portfolio roles).

Usage: verify() / enforce() compare the arms a config WOULD resolve
(mirroring Session._strategy_adapters + the arms=all variant loop,
including S5-has-no-variants) plus live parameter fingerprints against
the frozen registry, BEFORE running. enforce() raises AllowlistError on
any disagreement: unknown IDs, extra arms, missing arms, param drift.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

VARIANT_MAP: dict[str, tuple[str, ...]] = {
    "S1": ("S1", "S1-V", "S1-F"),
    "S2": ("S2", "S2-V", "S2-F"),
    "S3": ("S3", "S3-R", "S3-C"),
    "S4": ("S4", "S4-S"),
    "X1": ("X1", "X1-S", "X1-T", "X1-F"),
}
NO_VARIANT_FAMILIES = ("S5",)
FAMILIES = ("S1", "S2", "S3", "S4", "S5", "X1")

PARAM_CLASSES: dict[str, str] = {
    "S1": "cryptobot.strategies.s1:S1Params",
    "S2": "cryptobot.strategies.s2:S2Params",
    "S3": "cryptobot.strategies.s3:S3Params",
    "S4": "cryptobot.strategies.s4:S4Params",
    "X1": "cryptobot.strategies.x1:X1Params",
}
MODULE_CONSTS: dict[str, tuple[str, ...]] = {
    "S1": ("MAX_CONSECUTIVE_MISSING_HALT",),
    "S2": ("MAX_CONSECUTIVE_MISSING_HALT", "WARMUP_N"),
    "S3": ("MAX_CONSECUTIVE_MISSING_HALT", "WARMUP_N"),
    "S4": ("MAX_CONSECUTIVE_MISSING_HALT", "WARMUP_N"),
    "X1": ("MAX_CONSECUTIVE_MISSING_HALT",),
}


class AllowlistError(ValueError):
    """Resolved config disagrees with the frozen registry."""


def resolve_config_arms(strategies_enabled: list[str], arms_mode: str,
                        allowlist: list[str] | None = None) -> list[str]:
    """Mirror Session arm resolution (base adapters + arms=all variants).

    S5 has no variant path. When allowlist is set, restrict to it and
    fail closed on unknown IDs.
    """
    if arms_mode not in ("base", "all"):
        raise AllowlistError(f"arms mode must be base|all, got {arms_mode!r}")
    resolved: list[str] = []
    for name in strategies_enabled:
        if name not in FAMILIES:
            raise AllowlistError(f"unknown strategy family {name!r}")
        resolved.append(name)
        if arms_mode == "all" and name not in NO_VARIANT_FAMILIES:
            resolved.extend(a for a in VARIANT_MAP[name] if a != name)
    if allowlist is not None:
        known_all = {a for arms in VARIANT_MAP.values() for a in arms}
        known_all.update(NO_VARIANT_FAMILIES)
        bad = [a for a in allowlist
               if a not in known_all and a not in ("COMBINED", "CASH")]
        if bad:
            raise AllowlistError(f"allowlist names unknown arms: {bad}")
        resolved = [a for a in resolved if a in allowlist]
    return resolved


def runtime_param_fingerprint() -> dict[str, dict[str, Any]]:
    """Live parameter values per arm family (code truth, reviewed)."""
    import importlib

    out: dict[str, dict[str, Any]] = {}
    for family, dotted in PARAM_CLASSES.items():
        mod_name, cls_name = dotted.split(":")
        module = importlib.import_module(mod_name)
        params = dataclasses.asdict(getattr(module, cls_name)())
        consts = {key: getattr(module, key)
                  for key in MODULE_CONSTS[family]}
        out[family] = {"params": params, "module_consts": consts}
    return out


def fingerprint_sha(fingerprint: dict[str, Any]) -> str:
    blob = json.dumps(fingerprint, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _read_toml_config(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def config_arms(registry: dict[str, Any], config_id: str) -> list[str]:
    """Arm IDs for one registry config (COMBINED expands to all 9)."""
    configs = {c["config_id"]: c for c in registry["configs"]}
    if config_id not in configs:
        raise AllowlistError(f"unknown config {config_id!r} in registry")
    arm = configs[config_id]["arm"]
    if arm == "COMBINED":
        return [c["arm"] for c in registry["configs"]
                if c["arm"] not in ("COMBINED", "CASH")]
    if arm == "CASH":
        return []
    return [arm]


def verify(config_path: str | Path, registry_path: str | Path,
           params_path: str | Path,
           only_config: str | None = None) -> dict[str, Any]:
    """Mechanical registry comparison of a TOML config file."""
    config_path = Path(config_path)
    data = _read_toml_config(config_path)
    strategies = data.get("strategies", {})
    allowlist = strategies.get("arms_allowlist")
    return verify_effective(
        list(strategies.get("enabled", [])),
        strategies.get("arms", "base"),
        list(allowlist) if allowlist is not None else None,
        registry_path, params_path, only_config=only_config,
        label=str(config_path))


def verify_effective(enabled: list[str], arms_mode: str,
                     allowlist: list[str] | None,
                     registry_path: str | Path, params_path: str | Path,
                     only_config: str | None = None,
                     label: str = "") -> dict[str, Any]:
    """Mechanical registry comparison on effective cell settings."""
    registry_path, params_path = Path(registry_path), Path(params_path)
    resolved = resolve_config_arms(list(enabled), arms_mode,
                                   list(allowlist)
                                   if allowlist is not None else None)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if only_config is not None:
        strategy_arms = config_arms(registry, only_config)
    else:
        registry_arms = [c["arm"] for c in registry["configs"]]
        strategy_arms = [a for a in registry_arms
                         if a not in ("COMBINED", "CASH")]
    frozen_params = json.loads(params_path.read_text(encoding="utf-8"))
    live = runtime_param_fingerprint()
    param_diffs: dict[str, Any] = {}
    for family, frozen in frozen_params.get("families", {}).items():
        current = live.get(family)
        if current != frozen:
            param_diffs[family] = {"frozen": frozen, "live": current}
    extra = sorted(set(resolved) - set(strategy_arms))
    missing = sorted(set(strategy_arms) - set(resolved))
    report = {
        "config": label or "effective-settings",
        "registry": str(registry_path),
        "resolved_arms": resolved,
        "resolved_count": len(resolved),
        "registry_strategy_arms": sorted(strategy_arms),
        "extra_arms": extra,
        "missing_arms": missing,
        "param_diffs": param_diffs,
        "live_fingerprint_sha": fingerprint_sha(live),
        "ok": not extra and not missing and not param_diffs,
    }
    return report


def enforce(config_path: str | Path, registry_path: str | Path,
            params_path: str | Path,
            only_config: str | None = None) -> dict[str, Any]:
    """verify() that raises AllowlistError on any disagreement."""
    report = verify(config_path, registry_path, params_path,
                    only_config=only_config)
    if not report["ok"]:
        raise AllowlistError(
            f"config {report['config']} disagrees with "
            f"{report['registry']}: extra={report['extra_arms']} "
            f"missing={report['missing_arms']} "
            f"param_drift={sorted(report['param_diffs'])}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mechanical ROUND-01 allowlist check")
    parser.add_argument("--config", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--enforce", action="store_true",
                        help="exit nonzero on any disagreement")
    parser.add_argument("--only-config", default=None, metavar="CONFIG_ID",
                        help="verify against one registry config only")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    try:
        report = enforce(args.config, args.registry, args.params,
                         only_config=args.only_config) \
            if args.enforce else verify(args.config, args.registry,
                                        args.params,
                                        only_config=args.only_config)
    except AllowlistError as exc:
        print(f"ALLOWLIST FAIL: {exc}")
        return 2
    print(f"allowlist ok={report['ok']} "
          f"resolved={report['resolved_count']} "
          f"extra={report['extra_arms']} missing={report['missing_arms']} "
          f"param_drift={sorted(report['param_diffs'])} "
          f"sha={report['live_fingerprint_sha']}")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1) + "\n",
                       encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
