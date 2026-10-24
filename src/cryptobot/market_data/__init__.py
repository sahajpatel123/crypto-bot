"""Market-data connectors, discovery, recording, replay and streaming (Worker 2, E-001/E-006)."""
from .bars import Bar1s, BarAggregator, BarMissing, to_s1_bar
from .bridge import (
    SNAPSHOT_FORMAT,
    StreamBook,
    StreamItem,
    book_features,
    flow_window,
    iter_market_stream,
    load_snapshots,
    snapshot_ms,
    snapshot_record,
    to_nautilus_ticks,
)
from .capabilities import CONNECTOR_CANDIDATES, ConnectorCapability, build_matrix, render_markdown
from .collector import (
    Collector,
    CollectorConfig,
    RunStats,
    measure_clock_offset_ms,
    select_capture_set,
)
from .datasets import DatasetHandle, open_dataset, verify_dataset
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
    load_events,
    load_recording,
    replay,
    replay_events,
    replay_hash,
    replay_with_snapshots,
)
from .views import BookView, DepthStore, FlowView2, book_flow_for
from .ws import WsClient, WsClosed, WsHandshakeError

__all__ = [
    "CONNECTOR_CANDIDATES",
    "Bar1s",
    "BarAggregator",
    "BarMissing",
    "BookView",
    "Collector",
    "CollectorConfig",
    "ConnectorCapability",
    "DepthBook",
    "DepthState",
    "DepthStore",
    "DatasetHandle",
    "DiscoveryResult",
    "FlowView2",
    "KlineRecorder",
    "RecordingStats",
    "ReplayEvent",
    "RunStats",
    "SNAPSHOT_FORMAT",
    "StreamBook",
    "StreamItem",
    "SymbolMeta",
    "WsClient",
    "WsClosed",
    "WsHandshakeError",
    "analyze_klines",
    "book_features",
    "book_flow_for",
    "build_matrix",
    "channel_of",
    "discover_usdt_perps",
    "discovery_summary",
    "eligible_symbols",
    "events_hash",
    "fetch_exchange_info",
    "flow_window",
    "iter_market_stream",
    "load_events",
    "load_recording",
    "load_snapshots",
    "measure_clock_offset_ms",
    "open_dataset",
    "parse_message",
    "raw_envelope",
    "render_markdown",
    "replay",
    "replay_events",
    "replay_hash",
    "replay_with_snapshots",
    "select_capture_set",
    "snapshot_ms",
    "snapshot_record",
    "to_nautilus_ticks",
    "to_s1_bar",
    "verify_dataset",
]
