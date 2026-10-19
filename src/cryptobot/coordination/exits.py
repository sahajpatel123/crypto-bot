"""Typed executable exit policies (manager-owned, app runtime S2).

``Intent.exit_rule`` remains the wire format (CONTRACTS v0.2.0 compat); the
runtime decodes it into an :class:`ExitPolicy` to drive exits. Strategies MUST
emit ``encode_exit_rule`` output; an undecodable rule blocks the intent at
selection with reason ``exit:undecodable-rule``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

__all__ = ["ExitPolicy", "encode_exit_rule", "decode_exit_rule"]

_VERSION = "v1"


def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class ExitPolicy:
    stop_price: float
    target_price: float | None
    time_exit_utc: datetime
    reduce_only: bool = True
    policy_id: str = ""

    def __post_init__(self) -> None:
        _finite(self.stop_price, "stop_price")
        if self.stop_price <= 0:
            raise ValueError("stop_price must be > 0")
        if self.target_price is not None:
            _finite(self.target_price, "target_price")
            if self.target_price <= 0:
                raise ValueError("target_price must be > 0")
        if self.time_exit_utc.tzinfo is None:
            raise ValueError("time_exit_utc must be tz-aware")
        if "|" in self.policy_id or "=" in self.policy_id:
            raise ValueError("policy_id must not contain '|' or '=")


def encode_exit_rule(policy: ExitPolicy) -> str:
    """Encode a policy into the ``Intent.exit_rule`` wire string."""
    target = "" if policy.target_price is None else repr(policy.target_price)
    return (
        f"{_VERSION}|stop={policy.stop_price!r}"
        f"|target={target}"
        f"|time_exit={policy.time_exit_utc.isoformat()}"
        f"|reduce_only={int(policy.reduce_only)}"
        f"|id={policy.policy_id}"
    )


def decode_exit_rule(rule: str) -> ExitPolicy:
    """Decode an ``Intent.exit_rule`` string; raises ValueError if undecodable."""
    parts = rule.split("|")
    if len(parts) != 6 or parts[0] != _VERSION:
        raise ValueError(f"undecodable exit rule: {rule!r}")
    kv: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            raise ValueError(f"undecodable exit rule: {rule!r}")
        key, _, value = part.partition("=")
        kv[key] = value
    try:
        stop = float(kv["stop"])
        target_raw = kv["target"]
        target = float(target_raw) if target_raw else None
        time_exit = datetime.fromisoformat(kv["time_exit"])
        reduce_only = {"0": False, "1": True}[kv["reduce_only"]]
        policy_id = kv["id"]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"undecodable exit rule: {rule!r}") from exc
    return ExitPolicy(
        stop_price=stop,
        target_price=target,
        time_exit_utc=time_exit,
        reduce_only=reduce_only,
        policy_id=policy_id,
    )
