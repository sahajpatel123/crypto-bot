"""One-shot verdict tokens for CONFIRM chunk access (F3.5).

A token is minted for one hypothesis and one exact set of chunk_ids. Each
``(token, chunk_id)`` pair redeems at most once: the first redeem marks it
used, every later redeem fails. Tokens live in ``<root>/tokens.json``.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from cryptobot.vault._common import (
    DEFAULT_VAULT_ROOT,
    atomic_write_json,
    utc_now_iso,
)

TOKENS_VERSION = 1
TOKENS_FILENAME = "tokens.json"


class TokenStore:
    """Mint/redeem store for one-shot verdict tokens."""

    def __init__(
        self,
        root: str | Path | None = None,
        now_utc: Callable[[], str | datetime] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else DEFAULT_VAULT_ROOT
        self._now_utc = now_utc

    @property
    def tokens_path(self) -> Path:
        return self.root / TOKENS_FILENAME

    def _load(self) -> dict:
        if not self.tokens_path.is_file():
            return {}
        with open(self.tokens_path, encoding="utf-8") as fh:
            data = json.load(fh)
        tokens = data.get("tokens", {})
        if not isinstance(tokens, dict):
            raise ValueError("tokens.json corrupt: 'tokens' is not an object")
        return tokens

    def _save(self, tokens: dict) -> None:
        atomic_write_json(
            self.tokens_path, {"version": TOKENS_VERSION, "tokens": tokens}
        )

    def mint(self, hypothesis: str, chunk_ids: list[str] | tuple[str, ...]) -> str:
        """Mint a token bound to one hypothesis and one exact chunk set."""
        chunk_list = sorted(set(chunk_ids))
        if not hypothesis:
            raise ValueError("hypothesis must be a non-empty string")
        if not chunk_list:
            raise ValueError("chunk_ids must be non-empty")
        tokens = self._load()
        token = secrets.token_hex(16)  # 128-bit
        while token in tokens:
            token = secrets.token_hex(16)
        tokens[token] = {
            "hypothesis": hypothesis,
            "chunk_ids": chunk_list,
            "redeemed": [],
            "minted_utc": utc_now_iso(self._now_utc),
        }
        self._save(tokens)
        return token

    def redeem(self, token: str, hypothesis: str, chunk_id: str) -> bool:
        """Redeem one (token, chunk) pair. Single-use: repeats fail."""
        tokens = self._load()
        entry = tokens.get(token)
        if not isinstance(entry, dict):
            return False
        if entry.get("hypothesis") != hypothesis:
            return False
        if chunk_id not in set(entry.get("chunk_ids", [])):
            return False
        redeemed = entry.get("redeemed", [])
        if chunk_id in redeemed:
            return False
        redeemed.append(chunk_id)
        entry["redeemed"] = sorted(redeemed)
        self._save(tokens)
        return True


def mint_verdict_token(
    hypothesis: str,
    chunk_ids: list[str] | tuple[str, ...],
    *,
    root: str | Path | None = None,
    now_utc: Callable[[], str | datetime] | None = None,
) -> str:
    """Mint a one-shot verdict token (module-level convenience wrapper)."""
    return TokenStore(root=root, now_utc=now_utc).mint(hypothesis, chunk_ids)


def redeem_verdict_token(
    token: str,
    hypothesis: str,
    chunk_id: str,
    *,
    root: str | Path | None = None,
) -> bool:
    """Redeem one (token, chunk) pair (module-level convenience wrapper)."""
    return TokenStore(root=root).redeem(token, hypothesis, chunk_id)
