"""Locate the lake, the pilot store, and the benchmark manifest.

Any worktree can find the same files. An explicit environment variable
wins, then a TOML config, then a file that exists in the repo, then the
same relative path under ``external_root`` (read-only checkout).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataRoots:
    lake: Path
    pilot: Path
    benchmark: Path
    lake_source: str
    pilot_source: str
    benchmark_source: str


def _config(repo: Path) -> dict:
    explicit = os.environ.get("CRYPTOBOT_DATA_CONFIG")
    path = Path(explicit) if explicit else repo / "research" / "data_root.toml"
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _pick(name: str, rel: str, *, repo: Path, base: Path,
          external: Path | None, env_key: str) -> tuple[Path, str]:
    override = os.environ.get(env_key)
    if override:
        return Path(override), f"env:{env_key}"
    local = base / rel
    if local.exists():
        return local, "local"
    if external is not None:
        alt = external / rel
        if alt.exists():
            return alt, "external"
    return local, "missing"


def resolve_data_roots(repo: Path | None = None) -> DataRoots:
    repo = (repo or Path.cwd()).resolve()
    cfg = _config(repo)
    if os.environ.get("CRYPTOBOT_DATA_ROOT"):
        base = Path(os.environ["CRYPTOBOT_DATA_ROOT"])
    elif cfg.get("root"):
        base = Path(str(cfg["root"]))
    else:
        base = repo
    external_txt = os.environ.get("CRYPTOBOT_EXTERNAL_ROOT") or str(
        cfg.get("external_root") or "")
    external = Path(external_txt) if external_txt else None
    lake_rel = str(cfg.get("lake") or "data/lake")
    pilot_rel = str(cfg.get("pilot") or "data/pilot")
    bench_rel = str(cfg.get("benchmark") or "datasets/benchmark_30d.toml")
    lake, lake_src = _pick("lake", lake_rel, repo=repo, base=base,
                           external=external, env_key="CRYPTOBOT_LAKE")
    pilot, pilot_src = _pick("pilot", pilot_rel, repo=repo, base=base,
                             external=external, env_key="CRYPTOBOT_PILOT")
    bench, bench_src = _pick("benchmark", bench_rel, repo=repo, base=base,
                             external=external, env_key="CRYPTOBOT_BENCHMARK")
    return DataRoots(lake, pilot, bench, lake_src, pilot_src, bench_src)


__all__ = ["DataRoots", "resolve_data_roots"]
