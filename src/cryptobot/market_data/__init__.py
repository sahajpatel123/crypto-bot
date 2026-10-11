"""Market-data connectors, discovery, recording and replay (Worker 2, E-001)."""
from .capabilities import CONNECTOR_CANDIDATES, ConnectorCapability, build_matrix, render_markdown
from .discovery import (
    DiscoveryResult,
    SymbolMeta,
    discover_usdt_perps,
    discovery_summary,
    eligible_symbols,
    fetch_exchange_info,
)
from .recorder import KlineRecorder, RecordingStats, analyze_klines
from .replayer import ReplayEvent, load_recording, replay, replay_hash

__all__ = [
    "CONNECTOR_CANDIDATES",
    "ConnectorCapability",
    "DiscoveryResult",
    "KlineRecorder",
    "RecordingStats",
    "ReplayEvent",
    "SymbolMeta",
    "analyze_klines",
    "build_matrix",
    "discover_usdt_perps",
    "discovery_summary",
    "eligible_symbols",
    "fetch_exchange_info",
    "load_recording",
    "render_markdown",
    "replay",
    "replay_hash",
]
