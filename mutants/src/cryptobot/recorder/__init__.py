"""F3 data-engine recorder: durable long-running capture for BTC/ETH USD-M.

Wraps the E-006 supervised-collector primitives (WsClient, DepthBook,
events.parse_message, discovery) with durability (hourly gzipped chunks,
fsync batching, hash-chained manifest), missing streams (forceOrder
liquidations, REST polls), venue plugin stubs, and offline integrity
reporting.
"""
from cryptobot.market_data.events import channel_of, parse_message

from .integrity import build_report, render_markdown
from .plugins import BybitPlugin, OKXPlugin, PluginDisabled, VenuePlugin
from .service import RecorderConfig, RecorderService
from .streams import (
    backoff_with_jitter,
    build_binance_streams,
    build_binance_urls,
    check_usdc_perps,
    parse_force_order_message,
    parse_rest_record,
    resync_depth,
)
from .writer import GENESIS_HASH, DurableWriter, verify_manifest_chain

__all__ = [
    "DurableWriter",
    "verify_manifest_chain",
    "GENESIS_HASH",
    "RecorderService",
    "RecorderConfig",
    "VenuePlugin",
    "PluginDisabled",
    "BybitPlugin",
    "OKXPlugin",
    "build_binance_streams",
    "build_binance_urls",
    "check_usdc_perps",
    "backoff_with_jitter",
    "resync_depth",
    "parse_force_order_message",
    "parse_rest_record",
    "parse_message",
    "channel_of",
    "build_report",
    "render_markdown",
]
