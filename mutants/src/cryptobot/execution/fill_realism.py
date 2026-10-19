"""Pessimistic fill realism for paper/replay (T1.9, parameterized F0.4c).

Zero-slippage paper fills fabricate edge. This model walks the visible
book (worst covered level when depth is insufficient, plus an
empty-book penalty) and adds a latency penalty calibrated to measured
feed age. It never improves a price: buys pay >= book VWAP, sells
receive <= book VWAP.

F0.4c replaces the "always one tick adverse"
(FillModel(prob_slippage=1.0)) rule with PaperFillParams: an explicit,
versioned, provenance-stamped parameter set. Defaults are
ASSUMED-pessimistic (documented below, not measured). The calibration
path (F2.2 `cryptobot calibrate`) fits spread/slippage/latency from
demo-drill, paper and live fills and writes a versioned cost model;
the paper engine loads it via PaperFillParams.from_dict. Automatic
updates may only make costs MORE conservative; relaxing requires a
fresh verdict run.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


from mutmut.mutation.trampoline import wrap_in_trampoline as _mutmut_mutated, MutantDict
mutants_xǁPaperFillParamsǁto_dict__mutmut: MutantDict = {}  # type: ignore
mutants_xǁPaperFillParamsǁfrom_dict__mutmut: MutantDict = {}  # type: ignore


@dataclass(frozen=True)
class PaperFillParams:
    """Versioned paper-fill parameters (F0.4c).

    Fields:
      version: schema version (1). Unknown versions refuse to load.
      spread_bps: round-trip spread cost proxy (half-spread x2).
      slippage_bps: adverse slippage per round trip (queue + impact).
      latency_ms_p95: p95 decision-to-ack latency driving the fill
        delay model and the latency_bps penalty term.
      latency_bps: adverse price drift applied per fill for latency.
      empty_book_bps: penalty per unit of uncovered quantity when
        visible depth cannot cover the order (thin-book conservatism).
      provenance: ASSUMED (defaults, pessimistic) or MEASURED
        (F2.2 calibration output with source/asof).
      source: calibration origin ("assumed-pessimistic", "demo-drill",
        "paper", "live") for audit.
      asof_utc: ISO timestamp of the calibration (None for defaults).
      fill_model_note: documents the nautilus FillModel mapping so the
        1-tick rule is never silently reintroduced.
    """

    version: int = 1
    spread_bps: float = 2.0
    slippage_bps: float = 6.0
    latency_ms_p95: int = 50
    latency_bps: float = 2.0
    empty_book_bps: float = 25.0
    provenance: str = "ASSUMED"
    source: str = "assumed-pessimistic"
    asof_utc: str | None = None
    fill_model_note: str = (
        "nautilus FillModel(prob_slippage=1.0) replaced: matching timing "
        "kept, fill economics set by these params (book-walk + latency "
        "penalty + audit top-up); see NautilusPaperEngine.slippage_audit")

    @classmethod
    def default_pessimistic(cls) -> PaperFillParams:
        """Conservative ASSUMED defaults (pre-calibration).

        Values mirror cost_model_v2 taker assumptions (2 spread + 6
        slip) plus a 2bps latency drift and 25bps thin-book penalty.
        Pessimistic by construction; F2.2 replaces with MEASURED.
        """
        return cls()

    @_mutmut_mutated(mutants_xǁPaperFillParamsǁto_dict__mutmut)
    def to_dict(self) -> dict:
        return asdict(self)

    def xǁPaperFillParamsǁto_dict__mutmut_orig(self) -> dict:
        return asdict(self)

    def xǁPaperFillParamsǁto_dict__mutmut_1(self) -> dict:
        return asdict(None)

    @classmethod
    @_mutmut_mutated(mutants_xǁPaperFillParamsǁfrom_dict__mutmut, is_classmethod = True)
    def from_dict(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_orig(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_1(cls, data: dict) -> PaperFillParams:
        if isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_2(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError(None)
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_3(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("XXfill params must be a dictXX")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_4(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("FILL PARAMS MUST BE A DICT")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_5(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get(None) != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_6(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("XXversionXX") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_7(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("VERSION") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_8(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") == 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_9(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 2:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_10(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                None)
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_11(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get(None)!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_12(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('XXversionXX')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_13(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('VERSION')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_14(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = None
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_15(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = None
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_16(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) + known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_17(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(None) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_18(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(None)
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_19(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(None)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_20(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = None
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_21(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k not in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_22(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("XXspread_bpsXX", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_23(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("SPREAD_BPS", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_24(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "XXslippage_bpsXX", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_25(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "SLIPPAGE_BPS", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_26(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "XXlatency_bpsXX",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_27(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "LATENCY_BPS",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_28(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "XXempty_book_bpsXX"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_29(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "EMPTY_BOOK_BPS"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_30(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = None
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_31(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(None, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_32(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, None)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_33(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_34(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, )
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_35(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) and value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_36(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) and not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_37(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_38(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_39(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(None) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_40(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_41(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 1:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_42(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(None)
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_43(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) and params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_44(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_45(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 < 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_46(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 1:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_47(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError(None)
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_48(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("XXlatency_ms_p95 must be a positive intXX")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_49(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("LATENCY_MS_P95 MUST BE A POSITIVE INT")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_50(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_51(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("XXASSUMEDXX", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_52(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("assumed", "MEASURED"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_53(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "XXMEASUREDXX"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_54(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "measured"):
            raise ValueError("provenance must be ASSUMED or MEASURED")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_55(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError(None)
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_56(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("XXprovenance must be ASSUMED or MEASUREDXX")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_57(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("provenance must be assumed or measured")
        return params

    @classmethod
    def xǁPaperFillParamsǁfrom_dict__mutmut_58(cls, data: dict) -> PaperFillParams:
        if not isinstance(data, dict):
            raise ValueError("fill params must be a dict")
        if data.get("version") != 1:
            raise ValueError(
                f"unknown PaperFillParams version: {data.get('version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown fill param fields: {sorted(unknown)}")
        params = cls(**{k: v for k, v in data.items() if k in known})
        for name in ("spread_bps", "slippage_bps", "latency_bps",
                     "empty_book_bps"):
            value = getattr(params, name)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite >= 0")
        if not isinstance(params.latency_ms_p95, int) \
                or params.latency_ms_p95 <= 0:
            raise ValueError("latency_ms_p95 must be a positive int")
        if params.provenance not in ("ASSUMED", "MEASURED"):
            raise ValueError("PROVENANCE MUST BE ASSUMED OR MEASURED")
        return params

mutants_xǁPaperFillParamsǁto_dict__mutmut['_mutmut_orig'] = PaperFillParams.xǁPaperFillParamsǁto_dict__mutmut_orig # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁto_dict__mutmut['xǁPaperFillParamsǁto_dict__mutmut_1'] = PaperFillParams.xǁPaperFillParamsǁto_dict__mutmut_1 # type: ignore # mutmut generated

mutants_xǁPaperFillParamsǁfrom_dict__mutmut['_mutmut_orig'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_orig # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_1'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_1 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_2'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_2 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_3'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_3 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_4'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_4 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_5'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_5 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_6'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_6 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_7'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_7 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_8'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_8 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_9'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_9 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_10'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_10 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_11'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_11 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_12'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_12 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_13'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_13 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_14'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_14 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_15'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_15 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_16'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_16 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_17'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_17 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_18'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_18 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_19'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_19 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_20'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_20 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_21'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_21 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_22'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_22 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_23'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_23 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_24'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_24 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_25'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_25 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_26'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_26 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_27'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_27 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_28'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_28 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_29'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_29 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_30'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_30 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_31'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_31 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_32'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_32 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_33'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_33 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_34'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_34 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_35'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_35 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_36'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_36 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_37'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_37 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_38'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_38 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_39'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_39 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_40'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_40 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_41'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_41 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_42'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_42 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_43'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_43 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_44'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_44 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_45'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_45 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_46'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_46 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_47'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_47 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_48'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_48 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_49'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_49 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_50'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_50 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_51'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_51 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_52'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_52 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_53'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_53 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_54'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_54 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_55'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_55 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_56'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_56 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_57'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_57 # type: ignore # mutmut generated
mutants_xǁPaperFillParamsǁfrom_dict__mutmut['xǁPaperFillParamsǁfrom_dict__mutmut_58'] = PaperFillParams.xǁPaperFillParamsǁfrom_dict__mutmut_58 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_pessimistic_fill_price__mutmut)
def pessimistic_fill_price(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_orig(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_1(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 1.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_2(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 26.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_3(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_4(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("XXBUYXX", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_5(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("buy", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_6(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "XXSELLXX"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_7(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "sell"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_8(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(None)
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_9(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 and not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_10(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty < 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_11(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 1 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_12(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_13(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(None):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_14(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError(None)
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_15(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("XXqty must be positive finiteXX")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_16(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("QTY MUST BE POSITIVE FINITE")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_17(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_18(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError(None)
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_19(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("XXlevels must be non-empty (no book, no fill)XX")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_20(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("LEVELS MUST BE NON-EMPTY (NO BOOK, NO FILL)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_21(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = None
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_22(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(None)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_23(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = None
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_24(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 1.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_25(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = None
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_26(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(None)
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_27(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[1][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_28(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][1])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_29(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining < 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_30(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 1:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_31(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            return
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_32(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = None
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_33(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(None, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_34(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, None)
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_35(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_36(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, )
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_37(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(None))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_38(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take < 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_39(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 1:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_40(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            break
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_41(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost = take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_42(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost -= take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_43(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take / float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_44(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(None)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_45(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining = take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_46(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining += take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_47(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = None
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_48(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(None)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_49(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining >= 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_50(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 1:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_51(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = None
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_52(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if (side == "BUY") and False \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_53(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if (side == "BUY") or True \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_54(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 - empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_55(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 2.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_56(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps * 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_57(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10001.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_58(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side != "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_59(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "XXBUYXX" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_60(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "buy" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_61(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 + empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_62(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 2.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_63(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps * 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_64(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10001.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_65(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost = remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_66(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost -= remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_67(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst / penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_68(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining / worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_69(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = None
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_70(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost * float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_71(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(None)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_72(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = None
    return vwap * latency


def x_pessimistic_fill_price__mutmut_73(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if (side == "BUY") and False \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_74(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if (side == "BUY") or True \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_75(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 - latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_76(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 2.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_77(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps * 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_78(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10001.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_79(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side != "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_80(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "XXBUYXX" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_81(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "buy" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_82(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 + latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_83(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 2.0 - latency_bps / 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_84(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps * 10000.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_85(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10001.0
    return vwap * latency


def x_pessimistic_fill_price__mutmut_86(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap / latency

mutants_x_pessimistic_fill_price__mutmut['_mutmut_orig'] = x_pessimistic_fill_price__mutmut_orig # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_1'] = x_pessimistic_fill_price__mutmut_1 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_2'] = x_pessimistic_fill_price__mutmut_2 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_3'] = x_pessimistic_fill_price__mutmut_3 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_4'] = x_pessimistic_fill_price__mutmut_4 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_5'] = x_pessimistic_fill_price__mutmut_5 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_6'] = x_pessimistic_fill_price__mutmut_6 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_7'] = x_pessimistic_fill_price__mutmut_7 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_8'] = x_pessimistic_fill_price__mutmut_8 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_9'] = x_pessimistic_fill_price__mutmut_9 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_10'] = x_pessimistic_fill_price__mutmut_10 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_11'] = x_pessimistic_fill_price__mutmut_11 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_12'] = x_pessimistic_fill_price__mutmut_12 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_13'] = x_pessimistic_fill_price__mutmut_13 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_14'] = x_pessimistic_fill_price__mutmut_14 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_15'] = x_pessimistic_fill_price__mutmut_15 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_16'] = x_pessimistic_fill_price__mutmut_16 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_17'] = x_pessimistic_fill_price__mutmut_17 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_18'] = x_pessimistic_fill_price__mutmut_18 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_19'] = x_pessimistic_fill_price__mutmut_19 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_20'] = x_pessimistic_fill_price__mutmut_20 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_21'] = x_pessimistic_fill_price__mutmut_21 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_22'] = x_pessimistic_fill_price__mutmut_22 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_23'] = x_pessimistic_fill_price__mutmut_23 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_24'] = x_pessimistic_fill_price__mutmut_24 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_25'] = x_pessimistic_fill_price__mutmut_25 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_26'] = x_pessimistic_fill_price__mutmut_26 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_27'] = x_pessimistic_fill_price__mutmut_27 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_28'] = x_pessimistic_fill_price__mutmut_28 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_29'] = x_pessimistic_fill_price__mutmut_29 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_30'] = x_pessimistic_fill_price__mutmut_30 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_31'] = x_pessimistic_fill_price__mutmut_31 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_32'] = x_pessimistic_fill_price__mutmut_32 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_33'] = x_pessimistic_fill_price__mutmut_33 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_34'] = x_pessimistic_fill_price__mutmut_34 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_35'] = x_pessimistic_fill_price__mutmut_35 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_36'] = x_pessimistic_fill_price__mutmut_36 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_37'] = x_pessimistic_fill_price__mutmut_37 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_38'] = x_pessimistic_fill_price__mutmut_38 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_39'] = x_pessimistic_fill_price__mutmut_39 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_40'] = x_pessimistic_fill_price__mutmut_40 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_41'] = x_pessimistic_fill_price__mutmut_41 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_42'] = x_pessimistic_fill_price__mutmut_42 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_43'] = x_pessimistic_fill_price__mutmut_43 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_44'] = x_pessimistic_fill_price__mutmut_44 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_45'] = x_pessimistic_fill_price__mutmut_45 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_46'] = x_pessimistic_fill_price__mutmut_46 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_47'] = x_pessimistic_fill_price__mutmut_47 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_48'] = x_pessimistic_fill_price__mutmut_48 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_49'] = x_pessimistic_fill_price__mutmut_49 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_50'] = x_pessimistic_fill_price__mutmut_50 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_51'] = x_pessimistic_fill_price__mutmut_51 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_52'] = x_pessimistic_fill_price__mutmut_52 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_53'] = x_pessimistic_fill_price__mutmut_53 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_54'] = x_pessimistic_fill_price__mutmut_54 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_55'] = x_pessimistic_fill_price__mutmut_55 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_56'] = x_pessimistic_fill_price__mutmut_56 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_57'] = x_pessimistic_fill_price__mutmut_57 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_58'] = x_pessimistic_fill_price__mutmut_58 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_59'] = x_pessimistic_fill_price__mutmut_59 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_60'] = x_pessimistic_fill_price__mutmut_60 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_61'] = x_pessimistic_fill_price__mutmut_61 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_62'] = x_pessimistic_fill_price__mutmut_62 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_63'] = x_pessimistic_fill_price__mutmut_63 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_64'] = x_pessimistic_fill_price__mutmut_64 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_65'] = x_pessimistic_fill_price__mutmut_65 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_66'] = x_pessimistic_fill_price__mutmut_66 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_67'] = x_pessimistic_fill_price__mutmut_67 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_68'] = x_pessimistic_fill_price__mutmut_68 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_69'] = x_pessimistic_fill_price__mutmut_69 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_70'] = x_pessimistic_fill_price__mutmut_70 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_71'] = x_pessimistic_fill_price__mutmut_71 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_72'] = x_pessimistic_fill_price__mutmut_72 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_73'] = x_pessimistic_fill_price__mutmut_73 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_74'] = x_pessimistic_fill_price__mutmut_74 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_75'] = x_pessimistic_fill_price__mutmut_75 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_76'] = x_pessimistic_fill_price__mutmut_76 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_77'] = x_pessimistic_fill_price__mutmut_77 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_78'] = x_pessimistic_fill_price__mutmut_78 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_79'] = x_pessimistic_fill_price__mutmut_79 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_80'] = x_pessimistic_fill_price__mutmut_80 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_81'] = x_pessimistic_fill_price__mutmut_81 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_82'] = x_pessimistic_fill_price__mutmut_82 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_83'] = x_pessimistic_fill_price__mutmut_83 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_84'] = x_pessimistic_fill_price__mutmut_84 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_85'] = x_pessimistic_fill_price__mutmut_85 # type: ignore # mutmut generated
mutants_x_pessimistic_fill_price__mutmut['x_pessimistic_fill_price__mutmut_86'] = x_pessimistic_fill_price__mutmut_86 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_maker_fill__mutmut)
def maker_fill(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_orig(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_1(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_2(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("XXBUYXX", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_3(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("buy", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_4(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "XXSELLXX"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_5(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "sell"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_6(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(None)
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_7(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = None
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_8(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(None)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_9(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = None
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_10(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 1.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_11(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled > qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_12(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            return
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_13(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = None
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_14(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if (side == "BUY") and False \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_15(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if (side == "BUY") or True \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_16(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price <= limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_17(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side != "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_18(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "XXBUYXX" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_19(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "buy" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_20(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price >= limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_21(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = None
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_22(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price != limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_23(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = None
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_24(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(None, qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_25(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), None)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_26(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_27(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), )
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_28(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(None), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_29(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty + filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_30(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled = take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_31(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled -= take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_32(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = None
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_33(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(None, ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_34(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), None)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_35(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_36(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), )
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_37(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(None), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_38(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead = consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_39(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead += consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_40(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = None
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_41(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) + consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_42(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(None) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_43(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess >= 0:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_44(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 1:
                filled += min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_45(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled = min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_46(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled -= min(excess, qty - filled)
    return filled


def x_maker_fill__mutmut_47(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(None, qty - filled)
    return filled


def x_maker_fill__mutmut_48(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, None)
    return filled


def x_maker_fill__mutmut_49(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(qty - filled)
    return filled


def x_maker_fill__mutmut_50(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, )
    return filled


def x_maker_fill__mutmut_51(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty + filled)
    return filled

mutants_x_maker_fill__mutmut['_mutmut_orig'] = x_maker_fill__mutmut_orig # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_1'] = x_maker_fill__mutmut_1 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_2'] = x_maker_fill__mutmut_2 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_3'] = x_maker_fill__mutmut_3 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_4'] = x_maker_fill__mutmut_4 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_5'] = x_maker_fill__mutmut_5 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_6'] = x_maker_fill__mutmut_6 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_7'] = x_maker_fill__mutmut_7 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_8'] = x_maker_fill__mutmut_8 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_9'] = x_maker_fill__mutmut_9 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_10'] = x_maker_fill__mutmut_10 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_11'] = x_maker_fill__mutmut_11 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_12'] = x_maker_fill__mutmut_12 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_13'] = x_maker_fill__mutmut_13 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_14'] = x_maker_fill__mutmut_14 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_15'] = x_maker_fill__mutmut_15 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_16'] = x_maker_fill__mutmut_16 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_17'] = x_maker_fill__mutmut_17 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_18'] = x_maker_fill__mutmut_18 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_19'] = x_maker_fill__mutmut_19 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_20'] = x_maker_fill__mutmut_20 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_21'] = x_maker_fill__mutmut_21 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_22'] = x_maker_fill__mutmut_22 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_23'] = x_maker_fill__mutmut_23 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_24'] = x_maker_fill__mutmut_24 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_25'] = x_maker_fill__mutmut_25 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_26'] = x_maker_fill__mutmut_26 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_27'] = x_maker_fill__mutmut_27 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_28'] = x_maker_fill__mutmut_28 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_29'] = x_maker_fill__mutmut_29 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_30'] = x_maker_fill__mutmut_30 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_31'] = x_maker_fill__mutmut_31 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_32'] = x_maker_fill__mutmut_32 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_33'] = x_maker_fill__mutmut_33 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_34'] = x_maker_fill__mutmut_34 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_35'] = x_maker_fill__mutmut_35 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_36'] = x_maker_fill__mutmut_36 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_37'] = x_maker_fill__mutmut_37 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_38'] = x_maker_fill__mutmut_38 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_39'] = x_maker_fill__mutmut_39 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_40'] = x_maker_fill__mutmut_40 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_41'] = x_maker_fill__mutmut_41 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_42'] = x_maker_fill__mutmut_42 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_43'] = x_maker_fill__mutmut_43 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_44'] = x_maker_fill__mutmut_44 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_45'] = x_maker_fill__mutmut_45 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_46'] = x_maker_fill__mutmut_46 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_47'] = x_maker_fill__mutmut_47 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_48'] = x_maker_fill__mutmut_48 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_49'] = x_maker_fill__mutmut_49 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_50'] = x_maker_fill__mutmut_50 # type: ignore # mutmut generated
mutants_x_maker_fill__mutmut['x_maker_fill__mutmut_51'] = x_maker_fill__mutmut_51 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_stressed_pnl__mutmut)
def stressed_pnl(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_orig(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_1(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"XXgrossXX": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_2(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"GROSS": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_3(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(None), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_4(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "XXcosts_1xXX": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_5(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "COSTS_1X": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_6(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(None),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_7(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "XXpnl_1xXX": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_8(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "PNL_1X": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_9(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) + float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_10(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(None) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_11(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(None),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_12(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "XXpnl_2xXX": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_13(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "PNL_2X": float(gross_pnl) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_14(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) + 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_15(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(None) - 2.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_16(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 / float(costs_1x)}


def x_stressed_pnl__mutmut_17(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 3.0 * float(costs_1x)}


def x_stressed_pnl__mutmut_18(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(None)}

mutants_x_stressed_pnl__mutmut['_mutmut_orig'] = x_stressed_pnl__mutmut_orig # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_1'] = x_stressed_pnl__mutmut_1 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_2'] = x_stressed_pnl__mutmut_2 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_3'] = x_stressed_pnl__mutmut_3 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_4'] = x_stressed_pnl__mutmut_4 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_5'] = x_stressed_pnl__mutmut_5 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_6'] = x_stressed_pnl__mutmut_6 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_7'] = x_stressed_pnl__mutmut_7 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_8'] = x_stressed_pnl__mutmut_8 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_9'] = x_stressed_pnl__mutmut_9 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_10'] = x_stressed_pnl__mutmut_10 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_11'] = x_stressed_pnl__mutmut_11 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_12'] = x_stressed_pnl__mutmut_12 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_13'] = x_stressed_pnl__mutmut_13 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_14'] = x_stressed_pnl__mutmut_14 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_15'] = x_stressed_pnl__mutmut_15 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_16'] = x_stressed_pnl__mutmut_16 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_17'] = x_stressed_pnl__mutmut_17 # type: ignore # mutmut generated
mutants_x_stressed_pnl__mutmut['x_stressed_pnl__mutmut_18'] = x_stressed_pnl__mutmut_18 # type: ignore # mutmut generated
