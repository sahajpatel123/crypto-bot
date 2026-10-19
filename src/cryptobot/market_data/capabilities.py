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

# E-002 bounded trial-install record (D-005 follow-up). A trial documents what
# was ATTEMPTED and observed; it never counts as verified behaviour — the
# nautilus row's `verified` tuple stays empty until an import + adapter smoke
# actually passes in this environment.
# E-002 bounded trial-install record (D-005 follow-up). Historical: the wheel
# transfer stalled and the trial closed as blocked-on-transfer.
E002_TRIAL_UTC = "2026-10-11T13:36:00Z/2026-10-11T14:06:45Z"  # bound window (start/end).
E002_TRIAL_VERDICT = "blocked-on-transfer"
E002_TRIAL_EVIDENCE = (
    "trial venv .venv-trial (project-checkout-local, untracked, never committed)",
    "attempt 1 (py3.11): pin 1.231.0 rejected — requires-python >=3.12,<3.15 (PyPI file list: cp312/cp313/cp314 wheels + sdist)",
    "attempt 2 (py3.14, pip wheels-only): deps resolved; 156MB cp314 macosx_arm64 wheel at ~96KB/s, ~55MB in ~15min, stopped for faster installer",
    "attempt 3 (py3.14, uv 0.11.11): 15 pkgs resolved in 61s; parallel transfer reached 110MB+ cache but wheel never completed by the ~30min bound",
    "env: macOS 27.2 arm64, python 3.14.6, pip 26.1.2 — trial venv 13M, nautilus absent",
    "never completed: wheel transfer/install; no import, adapter, or conditional-order evidence obtained",
)

# E-006 bounded resumable trial (D-005 follow-up). The install SUCCEEDED on
# resume, so the import + adapter smoke E-002 defined as its bar ran here.
# Verified rule: `verified` entries name the venv they were exercised in;
# project-.venv adoption (pin install) is still a manager decision, so the
# row keeps a not-installed blocker alongside the trial-venv verification.
E006_TRIAL_UTC = "2026-10-11T21:46:00Z/2026-10-11T21:49:00Z"  # bound window (start/end).
E006_TRIAL_VERDICT = "import-adapter-smoke-passed"
E006_TRIAL_EVIDENCE = (
    "resume of E-002 blocked install: uv reused the 113M cache; cp314 macosx_arm64 wheel (149MB) + deps installed in 33s",
    "trial venv .venv-trial (project-checkout-local, untracked, never committed), 662M with deps",
    "import nautilus_trader -> 1.231.0 (matches pin)",
    "adapter: nautilus_trader.adapters.binance imports; BinanceLiveDataClientFactory + BinanceLiveExecClientFactory present; BinanceAccountType includes USDT_FUTURES",
    "orders: OrderType has STOP_MARKET/STOP_LIMIT/TRAILING_STOP_MARKET/TRAILING_STOP_LIMIT; ContingencyType OCO/OTO/OUO; OrderList.is_bracket present",
    "env: macOS 27.2 arm64, python 3.14.6, uv 0.11.11",
    "NOT covered: live order submission (no creds by policy), backtest run, project-.venv install",
)
E006_VERIFIED = (
    "pin 1.231.0 imports in .venv-trial (cp314 macosx_arm64 wheel, 2026-10-11)",
    "Binance adapter live data+exec factories and USDT_FUTURES account type present (.venv-trial smoke)",
    "stop/trailing order types, OCO/OTO/OUO contingency, OrderList.is_bracket present (.venv-trial smoke)",
)


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
    trial: tuple[str, ...] = field(default_factory=tuple)  # E-002 attempt evidence; never verification.
    trial: tuple[str, ...] = field(default_factory=tuple)  # trial-attempt evidence (E-002 + E-006).


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
        install_blocker="not installed in .venv; E-002 trial blocked-on-transfer (see trial notes)",
        install_blocker=("not installed in project .venv (import+adapter smoke verified in untracked "
                         ".venv-trial only; see trial notes); adoption needs pin + .venv install"),
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
        if cand.name == "nautilus_trader":
            verified += E006_VERIFIED
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
                trial=E002_TRIAL_EVIDENCE if cand.name == "nautilus_trader" else (),
                trial=(E002_TRIAL_EVIDENCE + E006_TRIAL_EVIDENCE
                       if cand.name == "nautilus_trader" else ()),
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
                "trial": list(r.trial),
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
    trial_rows = [r for r in matrix if r.trial]
    if trial_rows:
        lines += ["", f"Trial notes (E-002, {E002_TRIAL_UTC}; verdict: {E002_TRIAL_VERDICT}):", ""]
        lines += ["",
                  f"Trial notes (E-002, {E002_TRIAL_UTC}; verdict: {E002_TRIAL_VERDICT}; "
                  f"E-006, {E006_TRIAL_UTC}; verdict: {E006_TRIAL_VERDICT}):", ""]
        for r in trial_rows:
            lines.append(f"- {r.name} (pin {r.proposed_pin}):")
            lines.extend(f"  - {note}" for note in r.trial)
    return "\n".join(lines) + "\n"
