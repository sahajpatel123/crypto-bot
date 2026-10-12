"""Shared portfolio backtest harness (Worker 1, Q-007, B6).

Runs each BASE strategy separately + the combined bot + a cash reference
through the manager ``Session`` path (strategies → selector → risk →
Nautilus engine → ledger → store). One account policy per comparison; all
cooldowns, one-position, expiry, sizing, margin, exits, daily pauses and
protection are enforced BY Session — this module never scores in parallel.

Frozen splits (30-day benchmark day indices): dev 1–15, validation 16–22,
test 23–30. Each (arm-set, split) cell is a FRESH Session run, so no
position, cooldown, or holding window crosses a split boundary (full
purge); every run warms causally on its own split prefix. Test is scored
ONCE: rerunning a completed test split is refused (archive first).

Dataset consumption codes against B5 (``events(symbol, day)``,
``coverage()``, ``manifest_sha()``); E-008 swaps in without harness
changes. Until then the frozen ``synth_benchmark`` datasets run here,
labeled ``synthetic-benchmark``. Quote-less days use the
``research-spread-profile`` (see ``research/spread.py``) with sensitivity
reruns; S5 stays ineligible there with precise reasons.

Command: ``python -m cryptobot.research.backtest --dataset synth_quotes
--out <dir> --config configs/paper.toml``.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any, Protocol

DEV_DAYS = tuple(range(1, 16))
VAL_DAYS = tuple(range(16, 23))
TEST_DAYS = tuple(range(23, 31))
SPLITS = {"dev": DEV_DAYS, "validation": VAL_DAYS, "test": TEST_DAYS}
ARM_SETS = {
    "S1": ("S1",), "S2": ("S2",), "S3": ("S3",), "S4": ("S4",),
    "S5": ("S5",), "COMBINED": ("S1", "S2", "S3", "S4", "S5"), "CASH": (),
}
FILTER_LABEL = "frozen-assumed"
FROZEN_FILTERS = {
    # symbol -> tick/step/min-notional/precisions (labeled assumption, NOT
    # venue facts; E-008 supplies historical filters for real datasets).
    "BTCUSDT": {"tick_size": 0.01, "step_size": 0.001, "min_notional": 0.0,
                "price_precision": 2, "size_precision": 3},
    "XRPUSDT": {"tick_size": 0.0001, "step_size": 0.1, "min_notional": 0.0,
                "price_precision": 4, "size_precision": 1},
}
TEST_MARKER = "test-COMPLETED.json"

__all__ = [
    "ARM_SETS",
    "DEV_DAYS",
    "FROZEN_FILTERS",
    "MECHANISM_SPLIT",
    "SPLITS",
    "TEST_DAYS",
    "VAL_DAYS",
    "DatasetHandle",
    "compare_runs",
    "curve_signature",
    "day_events_for",
    "day_has_quotes",
    "day_ids_for",
    "fills_signature",
    "filters_for",
    "main",
    "preflight",
    "prepare_split_capture",
    "run_cell",
    "run_comparison",
]


class DatasetHandle(Protocol):
    """B5 reader surface (E-008 implements; synth doubles it for trial)."""

    def events(self, symbol: str, day): ...
    def coverage(self) -> dict: ...
    def manifest_sha(self) -> str: ...


MECHANISM_SPLIT = "mechanism"  # all available days, one run, labeled proof


def day_ids_for(dataset: DatasetHandle) -> tuple:
    """Ordered day ids: synth ints, vision IST dates, captured UTC dates."""
    if hasattr(dataset, "days"):
        return tuple(dataset.days())  # type: ignore[no-any-return]
    manifest = dataset.manifest  # type: ignore[attr-defined]
    info = manifest.get("dataset", {})
    if dataset.kind == "vision-archive":  # type: ignore[attr-defined]
        start, end = info["window_ist"]
        return _ist_range(start, end)
    days: set[str] = set()
    for entry in manifest.get("source", []):
        lo, hi = entry.get("ts_min_ms"), entry.get("ts_max_ms")
        if lo is None or hi is None:
            continue
        days.update(_utc_range(lo, hi))
    if not days:
        raise ValueError("no day coverage derivable from manifest")
    return tuple(sorted(days))


def _ist_range(start: str, end: str) -> tuple[str, ...]:
    """Inclusive IST date list (YYYY-MM-DD)."""
    import datetime as _dt

    lo = _dt.date.fromisoformat(start)
    hi = _dt.date.fromisoformat(end)
    out = []
    day = lo
    while day <= hi:
        out.append(day.isoformat())
        day += _dt.timedelta(days=1)
    return tuple(out)


def _utc_range(lo_ms: int, hi_ms: int) -> set[str]:
    import datetime as _dt

    out = set()
    day = _dt.datetime.fromtimestamp(lo_ms / 1000, tz=_dt.timezone.utc).date()
    end = _dt.datetime.fromtimestamp(hi_ms / 1000, tz=_dt.timezone.utc).date()
    while day <= end:
        out.add(day.isoformat())
        day += _dt.timedelta(days=1)
    return out


def _ist_window_ms(ist_day: str) -> tuple[int, int]:
    """IST calendar day as a UTC half-open [lo, hi) ms window."""
    import datetime as _dt

    lo = (_dt.datetime.fromisoformat(f"{ist_day}T00:00:00+05:30").timestamp()
          * 1000)
    return int(lo), int(lo + 86_400_000)


def day_events_for(dataset: DatasetHandle, symbol: str,
                   day_id) -> tuple[list[dict], dict]:
    """Day's normalized events (heartbeats dropped; gaps kept by ts).

    Returns (events, day_info). Raises when the day has no usable source.
    """
    if hasattr(dataset, "days"):
        events = [e for e in dataset.events(symbol, day_id) if e is not None]
        return events, {"day": day_id, "calendar": "synthetic-compressed"}
    manifest = dataset.manifest  # type: ignore[attr-defined]
    kind = dataset.kind  # type: ignore[attr-defined]
    if kind == "vision-archive":
        import datetime as _dt

        lo, hi = _ist_window_ms(day_id)
        utc_days = sorted(_utc_range(lo, hi - 1))
        events = []
        for utc_day in utc_days:
            for e in dataset.events(symbol, utc_day):
                if e is None:
                    continue
                ts = int(e["exchange_ts_ms"])
                if lo <= ts < hi:
                    events.append(e)
        return events, {"day": day_id, "calendar": "IST",
                        "utc_days": utc_days,
                        "window_utc_ms": [lo, hi]}
    events = [e for e in dataset.events(symbol, day_id) if e is not None]
    return events, {"day": day_id, "calendar": "UTC"}


def day_has_quotes(dataset: DatasetHandle, symbol: str, day_id) -> bool:
    """Whether (symbol, day) carries observed bookTicker coverage."""
    if hasattr(dataset, "days"):
        for d in dataset.coverage()["days"]:
            if d["day"] == day_id:
                return bool(d.get("quotes_observed", False))
        return False
    manifest = dataset.manifest  # type: ignore[attr-defined]
    for entry in manifest.get("source", []):
        symbols = entry.get("symbols") or ([entry.get("symbol")]
                                           if entry.get("symbol") else [])
        if symbol not in symbols:
            continue
        channels = entry.get("channels", [])
        if not channels and entry.get("channel"):
            channels = [entry["channel"]]
        if "bookTicker" in channels:
            return True
    return False


def filters_for(dataset: DatasetHandle, symbol: str) -> tuple[dict, str]:
    """Instrument filters: manifest-first, frozen-assumed fallback.

    Returns (filter dict, origin label). Manifest filters carry venue
    tick/step/min facts; the fallback is labeled, never venue truth.
    """
    cov = dataset.coverage()
    manifest_syms = (cov.get("filters") or {}).get("symbols", {})
    if symbol in manifest_syms:
        m = manifest_syms[symbol]
        return {
            "tick_size": float(m["tick"]), "step_size": float(m["step"]),
            "min_qty": float(m.get("min_qty", 0.0)),
            "min_notional": float(m.get("min_notional", 0.0)),
            "price_precision": _decimals(m["tick"]),
            "size_precision": _decimals(m["step"]),
        }, "manifest-frozen"
    if symbol in FROZEN_FILTERS:
        return dict(FROZEN_FILTERS[symbol]), FILTER_LABEL
    raise ValueError(f"no filters for {symbol!r} (manifest nor fallback)")


def _decimals(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return max(0, -int(text.split("e")[-1].replace("E", "")))
    return len(text.split(".")[1]) if "." in text else 0


def preflight(dataset: DatasetHandle, symbols: tuple[str, ...],
              day_ids: tuple) -> None:
    """Fail fast with a precise error when event data is absent locally."""
    if hasattr(dataset, "days"):
        return  # synthetic: always generatable
    cov = dataset.coverage()
    missing = [s for s in cov["sources"]
               if not s.get("local_exists", False)]
    if not missing:
        return
    have = len(cov["sources"]) - len(missing)
    raise FileNotFoundError(
        f"dataset {cov.get('dataset')}: {len(missing)}/{len(cov['sources'])} "
        f"sources missing locally ({have} present); fetch/preparation is "
        f"W2-owned. Availability fallback: frozen synthetic 30d benchmark "
        f"(labeled) for the split procedure; captured runs for mechanism.")


def _dataset_id(dataset: DatasetHandle) -> str:
    return str(getattr(dataset, "dataset_id", "external"))


def prepare_split_capture(dataset: DatasetHandle, split: str, out_dir,
                          symbols: tuple[str, ...],
                          spread_profile=None,
                          max_events: int | None = None) -> dict:
    """Concatenate split days into one capture dir (gaps preserved)."""
    from .spread import PROFILE_ID, apply_profile, profile_spread_bps

    day_ids = day_ids_for(dataset)
    if split == MECHANISM_SPLIT:
        days = day_ids
    elif split in SPLITS:
        positions = SPLITS[split]
        if len(day_ids) < max(positions):
            raise ValueError(
                f"dataset has {len(day_ids)} days; split {split!r} needs "
                f"{max(positions)} (use {MECHANISM_SPLIT} for short data)")
        days = tuple(day_ids[i - 1] for i in positions)
    else:
        raise ValueError(f"unknown split {split!r}")
    preflight(dataset, symbols, days)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    day_manifest = []
    for day in days:
        for symbol in symbols:
            day_events, day_info = day_events_for(dataset, symbol, day)
            quotes = day_has_quotes(dataset, symbol, day)
            applied = None
            if not quotes and spread_profile is not None:
                applied = profile_spread_bps(spread_profile, symbol)
                day_events, _ = apply_profile(day_events, symbol, applied)
            events.extend(day_events)
            day_manifest.append({
                **day_info, "symbol": symbol,
                "quotes_observed": quotes,
                "spread_profile": PROFILE_ID if applied else None,
                "spread_bps_assumed": applied,
                "n_events": len(day_events),
            })
    events.sort(key=lambda e: (int(e["exchange_ts_ms"]), e.get("channel", "")))
    # Capture-overlap dedup: overlapping runs carry the same venue feed;
    # collapse byte-identical (channel, ts, payload) repeats, labeled.
    n_before_dedup = len(events)
    seen: set[str] = set()
    deduped: list[dict] = []
    for e in events:
        key = (str(e.get("channel")), str(e.get("exchange_ts_ms")),
               json.dumps(e.get("payload", {}), sort_keys=True))
        fingerprint = "|".join(key)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(e)
    events = deduped
    truncated = False
    if max_events is not None and len(events) > max_events:
        events = events[:max_events]  # causal prefix only, labeled below
        truncated = True
    last_agg: dict[str, int] = {}
    for seq, e in enumerate(events, start=1):
        e["seq"] = seq
        e["local_mono_ns"] = seq
        if e.get("channel") == "aggTrade":
            agg = int(e["payload"]["agg_id"])
            sym = str(e.get("symbol", ""))
            if sym in last_agg and agg <= last_agg[sym]:
                raise ValueError(f"non-monotonic agg_id on {sym} at seq {seq}")
            last_agg[sym] = agg
    (out / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    manifest = {
        "split": split, "days": list(days),
        "dataset_id": _dataset_id(dataset),
        "dataset_manifest_sha": dataset.manifest_sha(),
        "symbols": list(symbols),
        "n_events": len(events),
        "deduped_repeats": n_before_dedup - len(seen),
        "truncated_prefix": truncated,
        "max_events": max_events,
        "purge": "fresh Session per cell; no cross-split state",
        "warmup": "causal, on split prefix (config warmup_bars)",
        "day_manifest": day_manifest,
    }
    (out / "day_manifest.json").write_text(json.dumps(manifest, indent=2),
                                           encoding="utf-8")
    return manifest


def run_cell(base_config_path, capture_dir, strategies: tuple[str, ...],
             run_dir, run_id: str, symbols: tuple[str, ...],
             instrument_filters: dict[str, dict] | None = None,
             filter_origin: str = FILTER_LABEL,
             filters_asof_utc=None) -> dict:
    """One (arm-set, split) cell: fresh Session + Nautilus engine, replay."""
    from cryptobot.adapters import NautilusPaperEngine
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    run_path = Path(run_dir)
    if run_path.exists():
        for child in sorted(run_path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
    run_path.mkdir(parents=True, exist_ok=True)
    cfg = load_config(base_config_path)
    cfg = dataclasses.replace(cfg, strategies_enabled=tuple(strategies),
                              storage_dir=str(run_path))
    store = RunStore(run_path / "store.db")
    from datetime import datetime, timezone
    _EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
    now_cell: dict[str, Any] = {"now": lambda: _EPOCH}
    # Engine delays follow the base config (production parity). E-008's
    # rework (GTC trade-cross, valuation-only marks) resolved the Q-007
    # mark-quote partial-fill pathology, verified by this harness.
    engine = NautilusPaperEngine(
        outcome_sink=None, taker_bps=cfg.taker_bps,
        now_utc=lambda: now_cell["now"](),
        submit_delay_ms=cfg.submit_delay_ms,
        fill_delay_ms=max(1, cfg.fill_delay_ms),
        journal_path=run_path / "engine_journal.jsonl",
        starting_balance_usdt=cfg.paper_capital_usdt)
    filters = instrument_filters or {}
    for symbol in symbols:
        filt = filters.get(symbol) or FROZEN_FILTERS.get(symbol.upper())
        if filt is None:
            raise ValueError(f"no filters for {symbol!r}")
        engine.add_instrument(symbol, price_precision=filt["price_precision"],
                              size_precision=filt["size_precision"],
                              tick_size=filt["tick_size"],
                              step_size=filt["step_size"],
                              min_qty=filt.get("min_qty", 0.0),
                              min_notional=filt["min_notional"])
    session = Session(cfg, store, run_path, run_id, engine=engine)
    # Risk sizes on the same filters the engine enforces (F3: no dust).
    known = instrument_filters or {}
    session.arm_replay_filters(
        {s: (known.get(s) or FROZEN_FILTERS.get(s.upper(), {}))
         for s in symbols}, filter_origin, asof_utc=filters_asof_utc)
    now_cell["now"] = session.now_utc
    # Fills must reach risk/ledger or positions never exist economically
    # (E-007 runtime binds the same sink on the live path).
    engine.bind_sink(session.policy)
    capture = Path(capture_dir)
    input_class = json.loads(
        (capture / "events.jsonl").read_text(
            encoding="utf-8").splitlines()[0])["input_class"]
    report = session.run_replay(capture, expect_class=input_class)
    report["filter_profile"] = {"label": filter_origin,
                                "filters": {s: filters.get(s) or
                                            FROZEN_FILTERS.get(s.upper())
                                            for s in symbols}}
    (run_path / "report.json").write_text(json.dumps(report, indent=2),
                                          encoding="utf-8")
    return {"report": report, "run_dir": str(run_path),
            "journal": str(run_path / "engine_journal.jsonl")}


def _normalize_id(value: Any) -> Any:
    # Nautilus client ids embed a uuid8 suffix (B1 allows varying display
    # ids); the seq prefix is the stable part. Reservation ids are stable.
    if isinstance(value, str) and value.rsplit("-", 1)[-1].strip():
        head, _, tail = value.rpartition("-")
        if head and len(tail) == 8 and all(
                c in "0123456789abcdef" for c in tail):
            return head
    return value


def _journal_records(journal_path) -> list[dict]:
    path = Path(journal_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fills_signature(journal_path) -> list[tuple]:
    """Normalized fills in journal order: (ts, side, qty, price, fee)."""
    sig = []
    for rec in _journal_records(journal_path):
        if rec.get("event") != "fill":
            continue
        d = rec["detail"]
        sig.append((rec["ts_utc"], _normalize_id(d.get("client_id")),
                    d.get("venue_side"), d.get("qty"), d.get("price"),
                    d.get("fee")))
    return sig


def curve_signature(journal_path) -> list[tuple]:
    """Per-fill cumulative (fee, signed notional): the realized curve."""
    cum_fee = 0.0
    cum_not = 0.0
    curve = []
    for rec in _journal_records(journal_path):
        if rec.get("event") != "fill":
            continue
        d = rec["detail"]
        sgn = 1.0 if str(d.get("venue_side", "")).upper().startswith("B") \
            else -1.0
        cum_fee += float(d.get("fee", 0.0))
        cum_not += sgn * float(d.get("qty", 0.0)) * float(d.get("price", 0.0))
        curve.append((rec["ts_utc"], round(cum_fee, 8), round(cum_not, 8)))
    return curve


def _metrics_signature(report: dict) -> dict:
    return {
        "closing_equity": report["closing_equity"],
        "net_return_pct": report["net_return_pct"],
        "paid_costs": report["paid_costs"],
        "funding_net": report["funding_net"],
        "realised": report["realised"],
        "intents_admitted": report["intents_admitted"],
        "events_seen": report["events_seen"],
        "reject_counts": report["reject_counts"],
    }


def compare_runs(report_a: dict, journal_a, report_b: dict, journal_b) -> dict:
    """Determinism diff: fills + curve + metrics identical?"""
    fills_a, fills_b = fills_signature(journal_a), fills_signature(journal_b)
    curve_a, curve_b = curve_signature(journal_a), curve_signature(journal_b)
    met_a, met_b = _metrics_signature(report_a), _metrics_signature(report_b)
    return {
        "fills_equal": fills_a == fills_b,
        "n_fills": len(fills_a),
        "curve_equal": curve_a == curve_b,
        "metrics_equal": met_a == met_b,
        "metric_diff": {k: [met_a[k], met_b[k]] for k in met_a
                        if met_a[k] != met_b[k]},
        "deterministic": fills_a == fills_b and curve_a == curve_b
                         and met_a == met_b,
    }


def run_comparison(dataset: DatasetHandle, out_dir, base_config_path,
                   symbols: tuple[str, ...], *,
                   splits: tuple[str, ...] = ("dev", "validation", "test"),
                   armsets: tuple[str, ...] = ("S1", "S2", "S3", "S4", "S5",
                                               "COMBINED", "CASH"),
                   spread_profile=None, sensitivity: bool = False,
                   max_events: int | None = None) -> dict:
    """Frozen per-strategy + combined + cash comparison across splits."""
    from .spread import PROFILE_ID, sensitivity_spreads

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if "test" in splits and (out / TEST_MARKER).exists():
        raise RuntimeError(
            "test split already scored once; archive results before rerunning")
    unknown = [a for a in armsets if a not in ARM_SETS]
    if unknown:
        raise ValueError(f"unknown arm-sets: {unknown}")
    bad_splits = [s for s in splits if s not in (*SPLITS, MECHANISM_SPLIT)]
    if bad_splits:
        raise ValueError(f"unknown splits: {bad_splits}")
    resolved = {s: filters_for(dataset, s) for s in symbols}
    instrument_filters = {s: f for s, (f, _) in resolved.items()}
    origins = sorted({origin for _, origin in resolved.values()})
    filters_asof = None
    manifest = getattr(dataset, "manifest", None)
    if isinstance(manifest, dict):
        created = manifest.get("dataset", {}).get("created_utc")
        if created:
            from datetime import datetime
            filters_asof = datetime.fromisoformat(created)
    comparison: dict[str, Any] = {
        "dataset_id": _dataset_id(dataset),
        "dataset_manifest_sha": dataset.manifest_sha(),
        "symbols": list(symbols),
        "splits": list(splits),
        "armsets": list(armsets),
        "filter_profile": "+".join(origins),
        "engine_delays_ms": {"note": "base config values (production "
                                     "parity); E-008 GTC/valuation-only marks "
                                     "verified healthy by this harness"},
        "promotion_rule": "NONE - descriptive baseline; no tuning on any split",
        "cells": {},
        "s5_ineligibility": {},
        "sensitivity": {},
    }
    for split in splits:
        cap_dir = out / "captures" / split
        manifest = prepare_split_capture(dataset, split, cap_dir, symbols,
                                         spread_profile, max_events)
        spread_used = any(d["spread_bps_assumed"]
                          for d in manifest["day_manifest"])
        for armset in armsets:
            run_id = f"{comparison['dataset_id']}-{split}-{armset}"
            run_dir = out / "runs" / split / armset
            cell = run_cell(base_config_path, cap_dir, ARM_SETS[armset],
                            run_dir, run_id, symbols, instrument_filters,
                            "+".join(origins), filters_asof)
            report = cell["report"]
            key = f"{armset}|{split}"
            comparison["cells"][key] = {
                **_metrics_signature(report),
                "n_fills": len(fills_signature(cell["journal"])),
                "run_dir": cell["run_dir"],
            }
            s5_reasons = {k: v for k, v in report["reject_counts"].items()
                          if "depth:" in k or "flow:" in k or "book:" in k}
            if s5_reasons:
                comparison["s5_ineligibility"][key] = {
                    "windows": sum(s5_reasons.values()),
                    "reasons": s5_reasons,
                }
            if sensitivity and spread_used and armset != "CASH":
                assert spread_profile is not None  # spread_used implies it
                for mult in sensitivity_spreads_for(
                        spread_profile, symbols):
                    if mult == 1.0:
                        continue
                    sens_cap = out / "captures" / f"{split}@spread{mult}x"
                    prepare_split_capture(
                        dataset, split, sens_cap, symbols,
                        _scaled_profile(spread_profile, mult), max_events)
                    run_dir_s = out / "runs" / f"{split}@spread{mult}x" / armset
                    run_id_s = f"{run_id}@spread{mult}x"
                    cell_s = run_cell(base_config_path, sens_cap,
                                      ARM_SETS[armset], run_dir_s, run_id_s,
                                      symbols, instrument_filters,
                                      "+".join(origins), filters_asof)
                    rep_s = cell_s["report"]
                    comparison["sensitivity"][f"{key}@spread{mult}x"] = {
                        "multiplier": mult,
                        "closing_equity": rep_s["closing_equity"],
                        "net_return_pct": rep_s["net_return_pct"],
                        "paid_costs": rep_s["paid_costs"],
                        "intents_admitted": rep_s["intents_admitted"],
                        "n_fills": len(fills_signature(cell_s["journal"])),
                        "run_dir": cell_s["run_dir"],
                    }
    if "test" in splits:
        (out / TEST_MARKER).write_text(json.dumps(
            {"test": "scored-once", "cells": sorted(
                k for k in comparison["cells"] if k.endswith("|test"))},
            indent=2), encoding="utf-8")
    (out / "comparison.json").write_text(json.dumps(comparison, indent=2),
                                         encoding="utf-8")
    return comparison


def sensitivity_spreads_for(spread_profile, symbols: tuple[str, ...]) -> dict:
    from .spread import sensitivity_spreads
    out: dict[float, dict] = {}
    for symbol in symbols:
        for mult, bps in sensitivity_spreads(spread_profile, symbol).items():
            out.setdefault(mult, {})[symbol] = bps
    return out


def _scaled_profile(spread_profile, mult: float):
    import dataclasses

    scaled = tuple((s, b * mult)
                   for s, b in spread_profile.per_symbol_bps)
    return dataclasses.replace(spread_profile,
                               default_bps=spread_profile.default_bps * mult,
                               per_symbol_bps=scaled)


def _default_symbols(dataset) -> list[str]:
    info = dataset.manifest.get("dataset", {})
    if isinstance(info, dict) and info.get("symbols"):
        return [info["symbols"][0]]
    return ["BTCUSDT"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Portfolio backtest harness")
    parser.add_argument("--dataset", required=True,
                        choices=["synth_quotes", "synth_noquotes",
                                 "captured", "benchmark-30d"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--splits", default="dev,validation,test")
    parser.add_argument("--armsets", default=",".join(ARM_SETS))
    parser.add_argument("--symbols", default=None,
                        help="comma-separated (default: dataset symbol)")
    parser.add_argument("--sensitivity", action="store_true",
                        help="spread sensitivity reruns (quote-less data)")
    parser.add_argument("--no-profile", action="store_true",
                        help="skip spread profile even on quote-less data")
    parser.add_argument("--max-events", type=int, default=None,
                        help="causal-prefix cap per split capture (labeled)")
    args = parser.parse_args(argv)
    from .spread import SpreadProfile
    from .synth_benchmark import SYMBOL, SynthBenchmark

    if args.dataset in ("synth_quotes", "synth_noquotes"):
        dataset = SynthBenchmark(dataset_id=args.dataset)
        symbols = (SYMBOL,)
        want_profile = args.dataset == "synth_noquotes"
    else:
        from cryptobot.market_data.datasets import open_dataset
        dataset = open_dataset(f"datasets/{args.dataset}.toml")
        symbols = tuple(s for s in (args.symbols or "").split(",") if s) \
            or tuple(_default_symbols(dataset))
        want_profile = True  # applied per-day only where quotes are absent
    profile = SpreadProfile() if (want_profile and not args.no_profile) \
        else None
    comparison = run_comparison(
        dataset, args.out, args.config, symbols,
        splits=tuple(s for s in args.splits.split(",") if s),
        armsets=tuple(a for a in args.armsets.split(",") if a),
        spread_profile=profile, sensitivity=args.sensitivity,
        max_events=args.max_events)
    n = len(comparison["cells"])
    print(f"{args.dataset}: {n} cells "
          f"({args.splits} x {args.armsets}) -> {args.out}/comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
