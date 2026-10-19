"""Acceptance-test helpers (Worker 3, V-001). Data-only fixtures + builders."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_clock(fixed_now: datetime = NOW) -> Callable[[], datetime]:
    return lambda: fixed_now


def build_intent(spec: dict[str, Any]):  # -> cryptobot.coordination.Intent
    from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side

    fc = spec["forecast_cost"]
    return Intent(
        strategy=spec["strategy"],
        version=spec["version"],
        instrument=spec["instrument"],
        side=Side(spec["side"]),
        evidence_ts_utc=datetime.fromisoformat(spec["evidence_ts_utc"]),
        entry_low=spec["entry_low"],
        entry_high=spec["entry_high"],
        entry_expiry_utc=datetime.fromisoformat(spec["entry_expiry_utc"]),
        invalidation_price=spec["invalidation_price"],
        exit_rule=spec["exit_rule"],
        holding_limit_s=spec["holding_limit_s"],
        forecast_cost=ForecastCost(
            fee_bps=fc["fee_bps"],
            spread_bps=fc["spread_bps"],
            slippage_bps=fc["slippage_bps"],
            funding_bps=fc["funding_bps"],
        ),
        evidence_ref=spec["evidence_ref"],
        data_quality=DataQuality(spec["data_quality"]),
    )


def build_account(spec: dict[str, Any]):  # -> cryptobot.risk.AccountSnapshot
    from cryptobot.risk import AccountSnapshot

    return AccountSnapshot(
        reconciled_equity=spec["reconciled_equity"],
        marked_equity=spec["marked_equity"],
        net_liquidation=spec["net_liquidation"],
        net_realised_global=spec["net_realised_global"],
        open_position=spec["open_position"],
    )


def make_policy(tmp_path: Path, now: datetime = NOW, **cfg):  # -> RiskPolicy
    from cryptobot.risk import RiskConfig, RiskPolicy

    return RiskPolicy(
        config=RiskConfig(**cfg),
        state_path=tmp_path / "risk_state.json",
        now_utc=make_clock(now),
    )
