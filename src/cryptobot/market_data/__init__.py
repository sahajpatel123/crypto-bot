"""Market-data connectors, discovery, recording, replay and streaming (Worker 2, E-001/E-006)."""
from .bars import Bar1s, BarAggregator, BarMissing, to_s1_bar
from .capabilities import CONNECTOR_CANDIDATES, ConnectorCapability, build_matrix, render_markdown
from .collector import Collector, CollectorConfig, RunStats, measure_clock_offset_ms, select_capture_set
from .depth import DepthBook, DepthState
from .discovery import (
    DiscoveryResult,
    SymbolMeta,
    discover_usdt_perps,
    discovery_summary,
    eligible_symbols,
    fetch_exchange_info,
)
from .events import EVENT_FORMAT, channel_of, parse_message, raw_envelope
from .recorder import KlineRecorder, RecordingStats, analyze_klines
from .replayer import (
    ReplayEvent,
    events_hash,
    iter_events,
    load_events,
    load_recording,
    replay,
    replay_events,
    replay_hash,
    streaming_events_hash,
)
from .ws import WsClient, WsClosed, WsHandshakeError

__all__ = [
    "CONNECTOR_CANDIDATES",
    "Bar1s",
    "BarAggregator",
    "BarMissing",
    "Collector",
    "CollectorConfig",
    "ConnectorCapability",
    "DepthBook",
    "DepthState",
    "DiscoveryResult",
    "KlineRecorder",
    "RecordingStats",
    "ReplayEvent",
    "RunStats",
    "SymbolMeta",
    "WsClient",
    "WsClosed",
    "WsHandshakeError",
    "analyze_klines",
    "build_matrix",
    "channel_of",
    "discover_usdt_perps",
    "discovery_summary",
    "eligible_symbols",
    "events_hash",
    "fetch_exchange_info",
    "iter_events",
    "load_events",
    "load_recording",
    "measure_clock_offset_ms",
    "parse_message",
    "raw_envelope",
    "render_markdown",
    "replay",
    "replay_events",
    "replay_hash",
    "select_capture_set",
    "streaming_events_hash",
    "to_s1_bar",
]
