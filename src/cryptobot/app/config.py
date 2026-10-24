"""TOML configuration loading + validation + fingerprint (manager-owned)."""
from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = ["AppConfig", "ConfigError", "load_config",
           "with_resolved_symbols"]

PACKAGE_VERSION = "0.1.0"


class ConfigError(ValueError):
    pass


def _finite(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{name} must be finite, got {value!r}")
    return float(value)


def _positive(value: object, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise ConfigError(f"{name} must be > 0, got {value!r}")
    return number


def _unit_interval(value: object, name: str) -> float:
    number = _finite(value, name)
    if not 0.0 < number < 1.0:
        raise ConfigError(f"{name} must lie in (0, 1), got {value!r}")
    return number


def _x1_beta(value: object) -> float | None:
    if value is None:
        return None
    return _positive(value, "strategies.x1_beta")


@dataclass(frozen=True)
class AppConfig:
    mode: str
    paper_capital_usdt: float
    accounting_tz: str
    duration_s: int
    # risk (mirrors RiskConfig fields 1:1; W3-24H profile 24h-1)
    max_loss_budget_pct: float
    leverage_cap: float
    min_notional_usdt: float
    stress_multiplier: float
    operating_stop_pct: float
    emergency_stop_pct: float
    profile_version: str
    max_mark_age_ms: float | None
    daily_loss_halt_pct: float | None
    daily_target_pct: float
    profit_arm_pct: float
    profit_retain_pct: float
    max_evidence_age_s: float
    max_clock_skew_s: float
    filters_max_age_s: float
    max_notional_cap_usdt: float
    # fees / engine / data / storage / strategies
    fee_label: str
    taker_bps: float
    funding_bps_per_8h: float
    engine_kind: str
    engine_demo: bool
    engine_base_url: str | None
    submit_delay_ms: int
    fill_delay_ms: int
    # W3-30MIN §4/§9: live submission is DISABLED by default at every
    # layer (config default False + adapter default-off). api_key_ref is
    # a reference label only — keys never live in config files.
    allow_live_submission: bool = False
    api_key_ref: str | None = None
    # W3-30MIN §4 runtime controls: control-tick target, bounded feed
    # queue, quote-age gate for new entries.
    control_tick_s: float = 0.25
    feed_queue_max: int = 1000
    quote_max_age_s: float = 1.0
    symbols: tuple[str, ...] = ()
    max_symbols: int = 8
    warmup_bars: int = 130
    max_hf_subscriptions: int = 2  # REL-W3: at most two HF subs to start.
    storage_dir: str = "runs"
    storage_budget_mb: int = 2048
    equity_sample_s: int = 60
    strategies_enabled: tuple[str, ...] = ("S1", "S2", "S3", "S4")
    strategies_arms: str = "base"
    # W4-CORR: exact arm allowlist (e.g. ROUND-01's 9 strategy arms).
    # None preserves legacy base/all behavior; when set, Session
    # evaluates only allowlisted arms and fails closed on unknown IDs.
    strategies_arms_allowlist: tuple[str, ...] | None = None
    # X1 leader-laggard frozen beta (X1.md §9): None until the
    # pre-round beta step transcribes the recorded value; X1
    # no-fires while unset.
    x1_beta: float | None = None
    cooldown_s: int = 300
    min_reward_multiple: float = 1.0
    allow_legacy_exit_rules: bool = True
    events_enabled: bool = False
    fingerprint: str = ""
    source_path: str = ""

    def to_risk_kwargs(self) -> dict:
        out = {
            "profile_version": self.profile_version,
            "max_loss_budget_pct": self.max_loss_budget_pct,
            "leverage_cap": self.leverage_cap,
            "min_notional_usdt": self.min_notional_usdt,
            "stress_multiplier": self.stress_multiplier,
            "operating_stop_pct": self.operating_stop_pct,
            "emergency_stop_pct": self.emergency_stop_pct,
            "daily_target_pct": self.daily_target_pct,
            "profit_arm_pct": self.profit_arm_pct,
            "profit_retain_pct": self.profit_retain_pct,
            "max_evidence_age_s": self.max_evidence_age_s,
            "max_clock_skew_s": self.max_clock_skew_s,
            "filters_max_age_s": self.filters_max_age_s,
        }
        if self.max_mark_age_ms is not None:
            out["max_mark_age_ms"] = self.max_mark_age_ms
        if self.daily_loss_halt_pct is not None:
            out["daily_loss_halt_pct"] = self.daily_loss_halt_pct
        return out

    @property
    def risk(self) -> RiskConfig:
        """Risk profile view: the exact RiskConfig the Session builds."""
        from cryptobot.risk.types import RiskConfig
        return RiskConfig(**self.to_risk_kwargs())


def _parse_duration(raw: object) -> int:
    if not isinstance(raw, str) or not raw:
        raise ConfigError(f"run.duration must be a string like '24h', got {raw!r}")
    unit = raw[-1]
    try:
        magnitude = float(raw[:-1])
    except ValueError:
        raise ConfigError(f"run.duration must look like '24h', got {raw!r}") from None
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit)
    if scale is None or magnitude <= 0:
        raise ConfigError(f"run.duration must look like '24h', got {raw!r}")
    return int(magnitude * scale)


def load_config(path: str | Path) -> AppConfig:
    """Load + validate a TOML config. Raises ConfigError on any problem."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config {path} is not valid TOML: {exc}") from None
    run = raw.get("run", {})
    risk = raw.get("risk", {})
    fees = raw.get("fees", {})
    engine = raw.get("engine", {})
    data = raw.get("data", {})
    storage = raw.get("storage", {})
    strategies = raw.get("strategies", {})
    runtime = raw.get("runtime", {})

    mode = run.get("mode")
    if mode not in ("replay", "paper", "prod"):
        raise ConfigError(f"run.mode must be 'replay', 'paper' or 'prod', got {mode!r}")
    tz = run.get("accounting_tz")
    if tz != "Asia/Kolkata":
        raise ConfigError(f"run.accounting_tz must be 'Asia/Kolkata', got {tz!r}")
    engine_kind = engine.get("kind")
    if engine_kind not in ("reference", "nautilus", "live"):
        raise ConfigError("engine.kind must be 'reference', 'nautilus' or "
                          f"'live', got {engine_kind!r}")
    if (engine_kind == "live" and mode != "prod"
            and not bool(engine.get("demo", False))):
        raise ConfigError("non-prod engine.kind = 'live' requires demo = true "
                          "(production orders are disabled)")
    if mode == "paper" and engine_kind not in ("nautilus", "live"):
        raise ConfigError("paper mode requires engine.kind = 'nautilus' or "
                          "'live' (reference engine is replay/tests only)")
    # W3-30MIN §9: explicit production path, separate from demo. Prod is
    # observe-only unless allow_live_submission is explicitly enabled;
    # the preflight tool (tools/preflight.py) gates real runs.
    if mode == "prod" and engine_kind != "live":
        raise ConfigError("prod mode requires engine.kind = 'live'")
    if mode == "prod" and bool(engine.get("demo", False)):
        raise ConfigError("prod mode forbids demo = true (demo is paper-live)")
    if mode == "prod" and engine.get("base_url"):
        host = str(engine["base_url"])
        if "demo-fapi" in host or "testnet" in host:
            raise ConfigError("prod mode forbids demo/testnet hosts")
    for secret_key in ("api_key", "api_secret", "secret"):
        if secret_key in engine:
            raise ConfigError(f"engine.{secret_key} is forbidden in config "
                              f"files (use api_key_ref + env, never keys)")
    arms = strategies.get("arms", "base")
    if arms not in ("base", "all"):
        raise ConfigError(f"strategies.arms must be 'base' or 'all', got {arms!r}")
    enabled = tuple(strategies.get("enabled", ["S1", "S2", "S3", "S4"]))
    for name in enabled:
        if name not in ("S1", "S2", "S3", "S4", "S5", "X1"):
            raise ConfigError(f"unknown strategy {name!r} in strategies.enabled")
    allowlist = strategies.get("arms_allowlist")
    if allowlist is not None:
        from cryptobot.strategies.contract import ARM_IDS
        if not isinstance(allowlist, list) or not all(
                isinstance(a, str) and a for a in allowlist):
            raise ConfigError("strategies.arms_allowlist must be a "
                              "non-empty-string list")
        for arm in allowlist:
            if arm not in ARM_IDS:
                raise ConfigError(f"unknown arm {arm!r} in "
                                  f"strategies.arms_allowlist")
        allowlist = tuple(allowlist)
    symbols = tuple(data.get("symbols", []))
    for symbol in symbols:
        if not symbol or not isinstance(symbol, str):
            raise ConfigError("data.symbols entries must be non-empty strings")

    cfg = AppConfig(
        mode=mode,
        paper_capital_usdt=_positive(run.get("paper_capital_usdt"), "run.paper_capital_usdt"),
        accounting_tz=tz,
        duration_s=_parse_duration(run.get("duration", "24h")),
        max_loss_budget_pct=_unit_interval(risk.get("max_loss_budget_pct"), "risk.max_loss_budget_pct"),
        leverage_cap=_positive(risk.get("leverage_cap"), "risk.leverage_cap"),
        min_notional_usdt=_finite(risk.get("min_notional_usdt"), "risk.min_notional_usdt"),
        stress_multiplier=_positive(risk.get("stress_multiplier"), "risk.stress_multiplier"),
        operating_stop_pct=_unit_interval(
            risk.get("operating_stop_pct", 0.005), "risk.operating_stop_pct"),
        emergency_stop_pct=_unit_interval(
            risk.get("emergency_stop_pct", 0.01), "risk.emergency_stop_pct"),
        profile_version=str(risk.get("profile_version", "24h-1")),
        max_mark_age_ms=(_positive(risk.get("max_mark_age_ms"), "risk.max_mark_age_ms")
                         if risk.get("max_mark_age_ms") is not None else None),
        daily_loss_halt_pct=(_unit_interval(risk.get("daily_loss_halt_pct"), "risk.daily_loss_halt_pct")
                             if risk.get("daily_loss_halt_pct") is not None else None),
        daily_target_pct=_positive(risk.get("daily_target_pct"), "risk.daily_target_pct"),
        profit_arm_pct=_unit_interval(risk.get("profit_arm_pct"), "risk.profit_arm_pct"),
        profit_retain_pct=_unit_interval(risk.get("profit_retain_pct"), "risk.profit_retain_pct"),
        max_evidence_age_s=_positive(risk.get("max_evidence_age_s"), "risk.max_evidence_age_s"),
        max_clock_skew_s=_finite(risk.get("max_clock_skew_s"), "risk.max_clock_skew_s"),
        filters_max_age_s=_positive(risk.get("filters_max_age_s"), "risk.filters_max_age_s"),
        max_notional_cap_usdt=_positive(
            risk.get("max_notional_cap_usdt"), "risk.max_notional_cap_usdt"),
        fee_label=str(fees.get("label", "simulation-labeled")),
        taker_bps=_finite(fees.get("taker_bps"), "fees.taker_bps"),
        funding_bps_per_8h=_finite(fees.get("funding_bps_per_8h"), "fees.funding_bps_per_8h"),
        engine_kind=engine_kind,
        engine_demo=bool(engine.get("demo", False)),
        engine_base_url=(str(engine.get("base_url"))
                         if engine.get("base_url") else None),
        submit_delay_ms=int(_finite(engine.get("submit_delay_ms", 0), "engine.submit_delay_ms")),
        fill_delay_ms=int(_finite(engine.get("fill_delay_ms", 0), "engine.fill_delay_ms")),
        allow_live_submission=bool(engine.get("allow_live_submission", False)),
        api_key_ref=(str(engine.get("api_key_ref"))
                     if engine.get("api_key_ref") else None),
        control_tick_s=_positive(runtime.get("control_tick_s", 0.25),
                                 "runtime.control_tick_s"),
        feed_queue_max=int(_positive(runtime.get("feed_queue_max", 1000),
                                     "runtime.feed_queue_max")),
        quote_max_age_s=_positive(runtime.get("quote_max_age_s", 1.0),
                                  "runtime.quote_max_age_s"),
        symbols=symbols,
        max_symbols=int(_positive(data.get("max_symbols", 8), "data.max_symbols")),
        warmup_bars=int(_positive(data.get("warmup_bars", 130), "data.warmup_bars")),
        max_hf_subscriptions=int(_positive(data.get("max_hf_subscriptions", 2),
                                           "data.max_hf_subscriptions")),
        storage_dir=str(storage.get("dir", "runs")),
        storage_budget_mb=int(_positive(storage.get("budget_mb", 2048), "storage.budget_mb")),
        equity_sample_s=int(_positive(storage.get("equity_sample_s", 60),
                                      "storage.equity_sample_s")),
        strategies_enabled=enabled,
        strategies_arms=arms,
        strategies_arms_allowlist=allowlist,
        x1_beta=_x1_beta(strategies.get("x1_beta")),
        cooldown_s=int(_finite(strategies.get("cooldown_s", 300), "strategies.cooldown_s")),
        min_reward_multiple=_positive(
            strategies.get("min_reward_multiple", 1.0), "strategies.min_reward_multiple"),
        allow_legacy_exit_rules=bool(strategies.get("allow_legacy_exit_rules", True)),
        events_enabled=bool(run.get("events_enabled", False)),
        source_path=str(path),
    )
    return AppConfig(**{**cfg.__dict__,
                       "fingerprint": _fingerprint_config(cfg)})


def _fingerprint_config(cfg: AppConfig) -> str:
    canonical_obj: dict = {
        "mode": cfg.mode, "capital": cfg.paper_capital_usdt, "risk": cfg.to_risk_kwargs(),
        "fees": {"label": cfg.fee_label, "taker_bps": cfg.taker_bps,
                 "funding_bps": cfg.funding_bps_per_8h},
        "engine": cfg.engine_kind, "submit_delay_ms": cfg.submit_delay_ms,
        "allow_live_submission": cfg.allow_live_submission,
        "demo": cfg.engine_demo,
        "runtime": {"tick_s": cfg.control_tick_s, "queue": cfg.feed_queue_max,
                  "quote_age_s": cfg.quote_max_age_s},
        "fill_delay_ms": cfg.fill_delay_ms, "symbols": list(cfg.symbols),
        "strategies": list(cfg.strategies_enabled), "arms": cfg.strategies_arms,
        "cooldown_s": cfg.cooldown_s, "min_reward_multiple": cfg.min_reward_multiple,
        "legacy_exits": cfg.allow_legacy_exit_rules,
        "events_enabled": cfg.events_enabled,
    }
    # Only fingerprinted when set, so legacy configs keep their hashes.
    if cfg.strategies_arms_allowlist is not None:
        canonical_obj["arms_allowlist"] = list(cfg.strategies_arms_allowlist)
    if cfg.x1_beta is not None:
        canonical_obj["x1_beta"] = cfg.x1_beta
    canonical = json.dumps(canonical_obj, sort_keys=True)
    return hashlib.sha256(
        f"{PACKAGE_VERSION}|{canonical}".encode()).hexdigest()[:16]


def with_resolved_symbols(cfg: AppConfig, symbols: list[str]) -> AppConfig:
    """Copy with explicit symbols and a recomputed fingerprint.

    Used when live discovery resolves an empty symbol list before the
    session exists, so book priming and the run fingerprint both see
    the actual universe. Symbols are upper-cased; the source TOML is
    untouched.
    """
    import dataclasses

    resolved = tuple(str(s).upper() for s in symbols if str(s).strip())
    if not resolved:
        raise ConfigError("resolved symbols must be non-empty")
    new = dataclasses.replace(cfg, symbols=resolved)
    return AppConfig(**{**new.__dict__,
                       "fingerprint": _fingerprint_config(new)})
