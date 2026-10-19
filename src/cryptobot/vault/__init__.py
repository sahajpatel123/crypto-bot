"""Sealed data vault (F3.5): hash-chained registry, one-shot tokens, gated loader."""

from cryptobot.vault._common import (
    VaultError,
    VaultRefused,
    VaultSynthetic,
    VaultUnknownChunk,
)
from cryptobot.vault.loader import (
    check_provenance,
    get_record,
    load_chunk,
    verify_access_log,
)
from cryptobot.vault.registry import Registry, seal_chunk
from cryptobot.vault.tokens import (
    TokenStore,
    mint_verdict_token,
    redeem_verdict_token,
)

__all__ = [
    "Registry",
    "TokenStore",
    "VaultError",
    "VaultRefused",
    "VaultSynthetic",
    "VaultUnknownChunk",
    "check_provenance",
    "get_record",
    "load_chunk",
    "mint_verdict_token",
    "redeem_verdict_token",
    "seal_chunk",
    "verify_access_log",
]
