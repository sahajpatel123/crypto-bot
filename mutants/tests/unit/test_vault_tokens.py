"""One-shot verdict tokens: mint once, redeem once, tight binding."""

from pathlib import Path

import pytest

from cryptobot.vault.tokens import (
    TokenStore,
    mint_verdict_token,
    redeem_verdict_token,
)


def test_mint_redeem_once_ok(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    token = mint_verdict_token("H1", ["a.bin", "b.bin"], root=root)
    assert isinstance(token, str) and len(token) == 32
    assert redeem_verdict_token(token, "H1", "a.bin", root=root) is True
    # Same token still works for the other bound chunk (per-(token, chunk) use).
    assert redeem_verdict_token(token, "H1", "b.bin", root=root) is True


def test_double_redeem_fails(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    token = TokenStore(root=root).mint("H1", ["a.bin"])
    assert TokenStore(root=root).redeem(token, "H1", "a.bin") is True
    assert TokenStore(root=root).redeem(token, "H1", "a.bin") is False
    assert redeem_verdict_token(token, "H1", "a.bin", root=root) is False


def test_wrong_hypothesis_fails(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    token = mint_verdict_token("H1", ["a.bin"], root=root)
    assert redeem_verdict_token(token, "H2", "a.bin", root=root) is False
    # Failed redeem must not consume the token.
    assert redeem_verdict_token(token, "H1", "a.bin", root=root) is True


def test_wrong_chunk_fails(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    token = mint_verdict_token("H1", ["a.bin"], root=root)
    assert redeem_verdict_token(token, "H1", "evil.bin", root=root) is False
    assert redeem_verdict_token(token, "H1", "a.bin", root=root) is True


def test_unknown_token_fails(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    mint_verdict_token("H1", ["a.bin"], root=root)
    assert redeem_verdict_token("0" * 32, "H1", "a.bin", root=root) is False


def test_mint_validates_inputs(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    with pytest.raises(ValueError, match="non-empty"):
        TokenStore(root=root).mint("", ["a.bin"])
    with pytest.raises(ValueError, match="non-empty"):
        TokenStore(root=root).mint("H1", [])


def test_tokens_unique(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    seen = {mint_verdict_token("H1", ["a.bin"], root=root) for _ in range(25)}
    assert len(seen) == 25
