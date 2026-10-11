"""Pinned connector capability matrix (Worker 2, CONTRACTS v0.1.0).

Every row separates VERIFIED behaviour (exercised in this environment, with
evidence) from ASSUMED behaviour (documented upstream, not exercised here).
A row with an empty ``verified`` tuple has proven nothing; its blockers say why.

``build_matrix()`` is offline-safe: installed versions are probed live via
importlib.metadata, proposed pins are point-in-time PyPI observations recorded
below (see ``PYPI_OBSERVED_UTC``). Live behaviour evidence is attached by the
capture tool after a real run via ``extra_verified``.
"""
from __future__ import annotations

import importlib.metadata as _md
import sys
from dataclasses import dataclass, field
from typing import Mapping

# Point-in-time `pip index versions` observations (PyPI, no install performed).
PYPI_OBSERVED_UTC = "2026-10-11T12:55:00Z"
PROPOSED_PINS = {
    # dist-name: PyPI latest observed at PYPI_OBSERVED_UTC (UNVERIFIED proposal).
    "nautilus_trader": "1.231.0",
    "ccxt": "4.5.85",
    "binance-connector": "3.13.0",
}

CONTRACT_VERSION = "v0.1.0"


@dataclass(frozen=True)
class ConnectorCapability:
    """One capability-matrix row."""

    name: str
    role: str
    dist_name: str | None  # PyPI distribution; None for stdlib/interpreter.
    installed_version: str | None  # Live probe; None means NOT installed.
    proposed_pin: str | None  # Point-in-time proposal; verified only if installed and exercised.
    pinned: bool  # Installed version equals the proposed pin.
    verified: tuple[str, ...] = field(default_factory=tuple)
    assumed: tuple[str, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _Candidate:
    name: str
    role: str
    dist_name: str | None
    assumed: tuple[str, ...]
    install_blocker: str  # Used when the distribution is not installed.


CONNECTOR_CANDIDATES: tuple[_Candidate, ...] = (
    _Candidate(
        name="stdlib-urllib",
        role="REST public data (discovery + capture for E-001)",
        dist_name=None,
        assumed=(
            "HTTPS GET against Binance USD-M futures REST (fapi)",
            "Sufficient for metadata discovery and kline capture; no streaming",
        ),
        install_blocker="",
    ),
    _Candidate(
        name="nautilus_trader",
        role="CEO-default production engine (DECISIONS D-005, pin deferred to this matrix)",
        dist_name="nautilus_trader",
        assumed=(
            "Backtest + live execution engine with Binance adapter (upstream docs)",
            "Rust-backed core; install is heavy (native build/wheel)",
        ),
        install_blocker="not installed in .venv; bounded E-001 check did metadata-only PyPI probe, no install",
    ),
    _Candidate(
        name="binance-connector",
        role="Thin official Binance SDK fallback (only on demonstrated Nautilus incompatibility)",
        dist_name="binance-connector",
        assumed=("Official Binance REST + websocket clients (upstream docs)",),
        install_blocker="not installed in .venv; no blocking incompatibility demonstrated yet",
    ),
    _Candidate(
        name="ccxt",
        role="Reference only (not selected; multi-exchange REST abstraction)",
        dist_name="ccxt",
        assumed=("Unified REST API across exchanges (upstream docs)",),
        install_blocker="not installed in .venv; not in the CEO decision path",
    ),
)


def _installed_version(dist_name: str | None) -> str | None:
    if dist_name is None:
        return f"stdlib (python {sys.version.split()[0]})"
    try:
        return _md.version(dist_name)
    except _md.PackageNotFoundError:
        return None


def build_matrix(extra_verified: Mapping[str, list[str]] | None = None) -> list[ConnectorCapability]:
    """Build the matrix. ``extra_verified`` maps row name to evidence strings."""
    extra = extra_verified or {}
    rows: list[ConnectorCapability] = []
    for cand in CONNECTOR_CANDIDATES:
        installed = _installed_version(cand.dist_name)
        proposed = PROPOSED_PINS.get(cand.dist_name or "")
        verified = tuple(extra.get(cand.name, ()))
        blockers: list[str] = []
        if installed is None:
            blockers.append(cand.install_blocker)
        if not verified:
            blockers.append("no behaviour verified in this environment for E-001")
        rows.append(
            ConnectorCapability(
                name=cand.name,
                role=cand.role,
                dist_name=cand.dist_name,
                installed_version=installed,
                proposed_pin=proposed,
                pinned=bool(installed and proposed and installed == proposed),
                verified=verified,
                assumed=cand.assumed,
                blockers=tuple(blockers),
            )
        )
    return rows


def to_dict(matrix: list[ConnectorCapability]) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "pypi_observed_utc": PYPI_OBSERVED_UTC,
        "rows": [
            {
                "name": r.name,
                "role": r.role,
                "dist": r.dist_name,
                "installed": r.installed_version,
                "proposed_pin": r.proposed_pin,
                "pinned": r.pinned,
                "verified": list(r.verified),
                "assumed": list(r.assumed),
                "blockers": list(r.blockers),
            }
            for r in matrix
        ],
    }


def render_markdown(matrix: list[ConnectorCapability]) -> str:
    lines = [
        f"contract {CONTRACT_VERSION}; PyPI pins observed {PYPI_OBSERVED_UTC} (proposals, unverified).",
        "",
        "| Connector | Installed | Proposed pin | Verified | Assumed | Blockers |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in matrix:
        ver = "<br>".join(r.verified) if r.verified else "—"
        asm = "<br>".join(r.assumed) if r.assumed else "—"
        blk = "<br>".join(r.blockers) if r.blockers else "—"
        lines.append(
            f"| {r.name} | {r.installed_version or 'NOT-INSTALLED'} "
            f"| {r.proposed_pin or 'n/a (stdlib)'} | {ver} | {asm} | {blk} |"
        )
    return "\n".join(lines) + "\n"
