"""Run-file schemas and strict loaders (V-007, B9).

Row schemas are FROZEN by the manager (`Session._append_run_file` docstring,
main c2bd955); this module enforces them exactly and fails LOUDLY on any
missing file, missing field, or mistyped value:

fills.jsonl:      {execution_id, client_order_id, instrument, side, qty,
                   price, fee, liquidity, ts_utc}
rejections.jsonl: {ts_utc, stage, reason, strategy, instrument, side}
risk.jsonl:       {ts_utc, kind, from_state, to_state, reason}
equity.jsonl:     {ts_utc, marked_equity, cash, position_qty,
                   position_symbol, open_pnl, source}
ledger.json:      accounting.Ledger.to_dict format (validated on load)
config.toml:      run identity + starting_equity ([run] preferred;
                  dataset/window/strategy also accepted from the manifest)
dataset_manifest.json: {dataset, window, manifest_sha?, splits?}

Gaps vs the metric table (flagged, not papered over): fills carry no
strategy tag, so episodes attribute the run-level config strategy when the
config names exactly one, else "unknown" (labeled); fills carry no exit
reason, so non-terminal closes report "unknown" except labeled
end-of-data closes.
"""
from __future__ import annotations

import csv
import json
import math
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class RunFileError(ValueError):
    """A run file is missing, malformed, or violates its schema."""


@dataclass(frozen=True)
class Fill:
    execution_id: str
    client_order_id: str
    instrument: str
    side: str
    qty: float
    price: float
    fee: float
    liquidity: str
    ts_utc: datetime


@dataclass(frozen=True)
class EquityRow:
    ts_utc: datetime
    marked_equity: float
    cash: float
    position_qty: float
    position_symbol: str
    open_pnl: float
    source: str
    # V-008 §7: mark provenance (additive; older runs lack these keys).
    mark_source: str = "unrecorded"  # exchange | feed | none | unrecorded
    mark_age_ms: float | None = None


@dataclass(frozen=True)
class Rejection:
    ts_utc: datetime
    stage: str
    reason: str
    strategy: str
    instrument: str
    side: str


@dataclass(frozen=True)
class RiskEvent:
    ts_utc: datetime
    kind: str
    from_state: str
    to_state: str
    reason: str


@dataclass(frozen=True)
class RunFiles:
    run_dir: Path
    fills: tuple[Fill, ...]
    equity: tuple[EquityRow, ...]
    rejections: tuple[Rejection, ...]
    risk_events: tuple[RiskEvent, ...]
    ledger: object  # accounting.Ledger (imported lazily to keep deps light)
    config: dict
    manifest: dict
    splits: dict  # optional splits.json ({} when undeclared)


def _cross_check_fills(fills: tuple[Fill, ...], ledger) -> None:
    """Every fill must agree with the persisted ledger (fail loudly).

    Ledgers that carry exec ids join on execution_id; legacy ledgers
    without them fall back to consuming identical (side, qty, price,
    fee) entries. Fill symbols must be ledger-known when the ledger
    records symbols.
    """
    journal = [e for e in ledger.to_dict()["journal"] if e["kind"] == "fill"]
    if fills and not journal:
        raise RunFileError("fills present without ledger fills")
    by_exec = {e.get("exec_id"): e for e in journal if e.get("exec_id")}
    symbols = {e.get("symbol") for e in journal if e.get("symbol")}

    def _agree(entry: dict, f: Fill) -> bool:
        return (entry.get("side") == f.side
                and float(entry.get("qty", -1)) == f.qty
                and float(entry.get("price", -1)) == f.price
                and float(entry.get("fee", -1)) == f.fee)

    pool = list(journal)
    for f in fills:
        if symbols and f.instrument not in symbols:
            raise RunFileError(
                f"fills.jsonl:{f.execution_id}: unknown instrument {f.instrument}")
        if by_exec:
            entry = by_exec.get(f.execution_id)
            if entry is None or not _agree(entry, f):
                raise RunFileError(
                    f"fills.jsonl:{f.execution_id}: no ledger fill agrees")
        else:
            for i, entry in enumerate(pool):
                if _agree(entry, f):
                    pool.pop(i)
                    break
            else:
                raise RunFileError(
                    f"fills.jsonl:{f.execution_id}: no ledger fill agrees")


def _parse_ts(value: object, where: str) -> datetime:
    if not isinstance(value, str):
        raise RunFileError(f"{where}: ts_utc must be an ISO-8601 string")
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        raise RunFileError(f"{where}: bad ts_utc {value!r}") from None
    if ts.tzinfo is None:
        raise RunFileError(f"{where}: ts_utc must be tz-aware")
    return ts


def _parse_float(value: object, name: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RunFileError(f"{where}: {name} must be a finite number")
    return float(value)


def _parse_str(value: object, name: str, where: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise RunFileError(f"{where}: {name} must be a non-empty string")
    return value


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise RunFileError(f"missing run file: {path.name}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunFileError(f"cannot read {path.name}: {exc}") from exc
    rows = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunFileError(f"{path.name}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise RunFileError(f"{path.name}:{lineno}: row must be an object")
        rows.append(row)
    return rows


def load_fills(path: Path) -> tuple[Fill, ...]:
    fills = []
    for row in _read_jsonl(path):
        where = f"fills.jsonl:{row.get('execution_id', '?')}"
        side = _parse_str(row.get("side"), "side", where)
        if side not in ("BUY", "SELL"):
            raise RunFileError(f"{where}: side must be BUY or SELL")
        fills.append(Fill(
            execution_id=_parse_str(row.get("execution_id"), "execution_id", where),
            client_order_id=_parse_str(row.get("client_order_id"), "client_order_id", where),
            instrument=_parse_str(row.get("instrument"), "instrument", where),
            side=side,
            qty=_parse_float(row.get("qty"), "qty", where),
            price=_parse_float(row.get("price"), "price", where),
            fee=_parse_float(row.get("fee"), "fee", where),
            liquidity=_parse_str(row.get("liquidity"), "liquidity", where),
            ts_utc=_parse_ts(row.get("ts_utc"), where),
        ))
    seen = set()
    for fill in fills:
        if fill.execution_id in seen:
            raise RunFileError(f"fills.jsonl: duplicate execution_id {fill.execution_id}")
        seen.add(fill.execution_id)
        if fill.qty <= 0 or fill.price <= 0 or fill.fee < 0:
            raise RunFileError(f"fills.jsonl:{fill.execution_id}: qty/price/fee out of range")
    return tuple(sorted(fills, key=lambda f: (f.ts_utc, f.execution_id)))


def load_equity(path: Path) -> tuple[EquityRow, ...]:
    rows = []
    for row in _read_jsonl(path):
        where = f"equity.jsonl:{row.get('ts_utc', '?')}"
        msrc = row.get("mark_source", "unrecorded")
        if not isinstance(msrc, str) or not msrc:
            raise RunFileError(f"{where}: mark_source must be a non-empty string")
        mage = row.get("mark_age_ms")
        if mage is not None:
            mage = _parse_float(mage, "mark_age_ms", where)
            if mage < 0:
                raise RunFileError(f"{where}: mark_age_ms must be >= 0")
        rows.append(EquityRow(
            ts_utc=_parse_ts(row.get("ts_utc"), where),
            marked_equity=_parse_float(row.get("marked_equity"), "marked_equity", where),
            cash=_parse_float(row.get("cash"), "cash", where),
            position_qty=_parse_float(row.get("position_qty"), "position_qty", where),
            position_symbol=_parse_str(row.get("position_symbol"), "position_symbol",
                                       where, allow_empty=True),
            open_pnl=_parse_float(row.get("open_pnl"), "open_pnl", where),
            source=_parse_str(row.get("source"), "source", where),
            mark_source=msrc,
            mark_age_ms=mage,
        ))
    return tuple(sorted(rows, key=lambda r: r.ts_utc))


def load_rejections(path: Path) -> tuple[Rejection, ...]:
    rows = []
    for row in _read_jsonl(path):
        where = f"rejections.jsonl:{row.get('ts_utc', '?')}"
        rows.append(Rejection(
            ts_utc=_parse_ts(row.get("ts_utc"), where),
            stage=_parse_str(row.get("stage"), "stage", where),
            reason=_parse_str(row.get("reason"), "reason", where),
            strategy=_parse_str(row.get("strategy"), "strategy", where),
            instrument=_parse_str(row.get("instrument"), "instrument", where),
            side=_parse_str(row.get("side"), "side", where),
        ))
    return tuple(sorted(rows, key=lambda r: r.ts_utc))


def load_risk_events(path: Path) -> tuple[RiskEvent, ...]:
    rows = []
    for row in _read_jsonl(path):
        where = f"risk.jsonl:{row.get('ts_utc', '?')}"
        rows.append(RiskEvent(
            ts_utc=_parse_ts(row.get("ts_utc"), where),
            kind=_parse_str(row.get("kind"), "kind", where),
            from_state=_parse_str(row.get("from_state"), "from_state", where,
                                  allow_empty=True),
            to_state=_parse_str(row.get("to_state"), "to_state", where),
            reason=_parse_str(row.get("reason"), "reason", where, allow_empty=True),
        ))
    return tuple(sorted(rows, key=lambda r: r.ts_utc))


def load_ledger(path: Path):
    from cryptobot.accounting import Ledger
    if not path.exists():
        raise RunFileError("missing run file: ledger.json")
    try:
        return Ledger.load(path)
    except (ValueError, OSError) as exc:
        raise RunFileError(f"ledger.json: {exc}") from exc


def load_toml(path: Path, name: str) -> dict:
    if not path.exists():
        raise RunFileError(f"missing run file: {name}")
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RunFileError(f"{name}: {exc}") from exc
    if not isinstance(data, dict):
        raise RunFileError(f"{name}: top level must be a table")
    return data


def load_json(path: Path, name: str) -> dict:
    if not path.exists():
        raise RunFileError(f"missing run file: {name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunFileError(f"{name}: {exc}") from exc
    if not isinstance(data, dict):
        raise RunFileError(f"{name}: top level must be an object")
    return data


def _first_present(*candidates):
    for value in candidates:
        if value is not None:
            return value
    return None


def _window_bounds(value: object, where: str) -> tuple[str, str]:
    if isinstance(value, str) and ".." in value:
        start, end = value.split("..", 1)
        return start.strip(), end.strip()
    raise RunFileError(f"{where}: window must be 'start..end'")


def load_run(run_dir: str | Path) -> RunFiles:
    """Load and strictly validate every run file (fails loudly).

    Identity fields resolve config-first, manifest-second; a missing value
    anywhere fails loudly.
    """
    run_dir = Path(run_dir)
    config = load_toml(run_dir / "config.toml", "config.toml")
    manifest = load_json(run_dir / "dataset_manifest.json", "dataset_manifest.json")
    run = config.get("run", {})
    if not isinstance(run, dict):
        raise RunFileError("config.toml: [run] must be a table")
    dataset = _first_present(run.get("dataset"), manifest.get("dataset"))
    if dataset is None:
        raise RunFileError("run identity: dataset missing (config [run] + manifest)")
    start = _first_present(run.get("window_start_utc"))
    end = _first_present(run.get("window_end_utc"))
    if start is None or end is None:
        for holder, where in ((run, "config.toml:[run]"), (manifest, "dataset_manifest.json")):
            window = holder.get("window")
            if window is not None and start is None:
                start, end = _window_bounds(window, where)
                break
    if start is None or end is None:
        raise RunFileError("run identity: window missing (config [run] + manifest)")
    equity0 = _first_present(run.get("starting_equity"),
                             config.get("account", {}).get("starting_equity")
                             if isinstance(config.get("account"), dict) else None,
                             config.get("starting_equity"))
    if equity0 is None:
        raise RunFileError("run identity: starting_equity missing (config)")
    _parse_ts(start, "run window")
    _parse_ts(end, "run window")
    _parse_float(equity0, "starting_equity", "config")
    run = dict(run)
    run.update(dataset=dataset, window_start_utc=start, window_end_utc=end,
               starting_equity=float(equity0),
               mode=run.get("mode", manifest.get("mode", "unknown")),
               strategy=run.get("strategy", manifest.get("strategy")))
    config = dict(config)
    config["run"] = run
    fills = load_fills(run_dir / "fills.jsonl")
    ledger = load_ledger(run_dir / "ledger.json")
    _cross_check_fills(fills, ledger)
    splits_path = run_dir / "splits.json"
    splits = load_json(splits_path, "splits.json") if splits_path.exists() else {}
    return RunFiles(
        run_dir=run_dir,
        fills=fills,
        equity=load_equity(run_dir / "equity.jsonl"),
        rejections=load_rejections(run_dir / "rejections.jsonl"),
        risk_events=load_risk_events(run_dir / "risk.jsonl"),
        ledger=ledger,
        config=config,
        manifest=manifest,
        splits=splits,
    )


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
