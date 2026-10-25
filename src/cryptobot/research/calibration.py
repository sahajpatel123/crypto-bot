"""F2.2: calibrate slippage/latency from recorded fills.

Input rows may come from demo drills, paper runs or (later) live fills:

    {"side": "BUY", "expected_price": 100.0, "fill_price": 100.05,
     "qty": 1.0, "latency_ms": 120, "fee_bps": 5.0,
     "funding_bps": 0.1, "spread_bps": 2.0, "day": "2026-10-18"}

The fit is deliberately pessimistic: slippage is the mean adverse
absolute move, latency uses p95, and fees are the maximum observed
taker fee. Automatic updates may only make the model MORE expensive.
A relaxation requires a PASS verdict document bound to the same config
hash (``--verdict-json``); otherwise the update is refused.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MODEL_FORMAT = "cryptobot-cost-model/2"


def _finite(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric, got {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return out


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(math.ceil(0.95 * len(ordered))) - 1)
    return ordered[idx]


@dataclass(frozen=True)
class FillSample:
    side: str
    expected_price: float
    fill_price: float
    qty: float
    latency_ms: float
    fee_bps: float
    funding_bps: float
    spread_bps: float
    day: str = ""

    @property
    def slippage_bps(self) -> float:
        if self.expected_price <= 0 or self.qty <= 0:
            raise ValueError("prices/qty must be positive")
        signed = (self.fill_price - self.expected_price) / self.expected_price
        if self.side == "SELL":
            signed = -signed
        # Adverse only: a favourable fill is recorded as zero cost, never
        # as a credit that could relax the model.
        return max(0.0, signed * 10_000.0)


def parse_fills(rows: Iterable[dict[str, Any]]) -> list[FillSample]:
    out: list[FillSample] = []
    for row in rows:
        side = str(row.get("side", "")).upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"fill side must be BUY/SELL, got {side!r}")
        out.append(FillSample(
            side=side,
            expected_price=_finite(row.get("expected_price",
                                           row.get("price")), "expected_price"),
            fill_price=_finite(row.get("fill_price", row.get("price")),
                               "fill_price"),
            qty=_finite(row.get("qty", 1.0), "qty"),
            latency_ms=_finite(row.get("latency_ms", 0.0), "latency_ms"),
            fee_bps=_finite(row.get("fee_bps", 0.0), "fee_bps"),
            funding_bps=_finite(row.get("funding_bps", 0.0), "funding_bps"),
            spread_bps=_finite(row.get("spread_bps", 0.0), "spread_bps"),
            day=str(row.get("day", "")),
        ))
    return out


def fit_cost_model(samples: list[FillSample], *,
                   source: str = "fills") -> dict:
    if not samples:
        raise ValueError("calibration needs at least one fill")
    slippage = [s.slippage_bps for s in samples]
    latency = [s.latency_ms for s in samples]
    fees = [s.fee_bps for s in samples]
    spread = [s.spread_bps for s in samples]
    model = {
        "format": MODEL_FORMAT,
        "version": 0,
        "created_utc": datetime.now(UTC).isoformat(),
        "source": source,
        "samples": len(samples),
        "days": len({s.day for s in samples if s.day}) or 1,
        "slippage_bps": round(max(0.0, statistics.fmean(slippage)), 4),
        "slippage_p95_bps": round(_p95(slippage), 4),
        "latency_ms": round(_p95(latency), 4),
        "taker_bps": round(max(fees) if fees else 0.0, 4),
        "funding_bps": round(max((s.funding_bps for s in samples),
                                 default=0.0), 4),
        "spread_bps": round(max(spread) if spread else 0.0, 4),
        "config_sha256": hashlib.sha256(json.dumps(
            [s.__dict__ for s in samples], sort_keys=True,
            default=str).encode()).hexdigest(),
    }
    return model


def _cost_fields(model: dict) -> tuple[str, ...]:
    return ("slippage_bps", "slippage_p95_bps", "latency_ms", "taker_bps",
            "funding_bps", "spread_bps")


def relaxations(previous: dict | None, new: dict) -> list[str]:
    """Cost fields that became cheaper (any such change needs a verdict)."""
    if not previous:
        return []
    out = []
    for field in _cost_fields(new):
        old = float(previous.get(field, 0.0) or 0.0)
        cur = float(new.get(field, 0.0) or 0.0)
        if cur < old:
            out.append(f"{field}: {old} -> {cur}")
    return out


def _verdict_allows_relaxation(verdict_path: str | Path | None,
                               *, new_model: dict) -> bool:
    if not verdict_path:
        return False
    path = Path(verdict_path)
    if not path.exists():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return (doc.get("verdict") == "PASS"
            and doc.get("hashes", {}).get("config_sha256_16")
            == new_model["config_sha256"][:16])


def update_cost_model(previous: dict | None, new: dict, *,
                      verdict_path: str | Path | None = None) -> dict:
    relaxed = relaxations(previous, new)
    if relaxed and not _verdict_allows_relaxation(
            verdict_path, new_model=new):
        raise ValueError(
            "cost relaxation refused without a matching PASS verdict: "
            + ", ".join(relaxed))
    version = int((previous or {}).get("version", 0)) + 1
    out = dict(new)
    out["version"] = version
    out["previous_version"] = int((previous or {}).get("version", 0))
    out["relaxations"] = relaxed
    out["approved_by_verdict"] = bool(relaxed)
    return out


def load_model(path: str | Path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def write_model(path: str | Path, model: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(model, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(p)


__all__ = ["FillSample", "parse_fills", "fit_cost_model", "update_cost_model",
           "load_model", "write_model", "relaxations", "MODEL_FORMAT"]
