"""X1 pre-round beta estimation (frozen procedure, X1.md section 9).

OLS of ETH 60s log returns on BTC 60s log returns with intercept, on
the frozen calibration slice ONLY (DEV day indices 1-5, 1s closes).
Requires >=1000 paired returns and Var(BTC)>0, else the round is
BLOCKED (exit 3) with a written reason. No trigger/outcome contact:
this tool reads closes, never evaluates any strategy.

Subcommands:
  estimate --dataset-toml <path> --out <beta.json>
  check --record <beta.json> --tomls <a.toml> [<b.toml> ...]
    (asserts every round TOML's strategies.x1_beta equals the record)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ALGO_ID = "ols-eth60-on-btc60-v1"
CALIBRATION_IDX = (1, 2, 3, 4, 5)
MIN_PAIRED = 1000
LEADER = "BTCUSDT"
LAGGARD = "ETHUSDT"


def closes_from_events(events) -> dict[int, float]:
    """Last aggTrade price per UTC second (None heartbeats skipped)."""
    closes: dict[int, float] = {}
    for event in events:
        if event is None:
            continue
        if event.get("channel") != "aggTrade":
            continue
        sec = int(event["exchange_ts_ms"]) // 1000
        closes[sec] = float(event["payload"]["price"])
    return closes


def paired_returns(btc: dict[int, float],
                   eth: dict[int, float]) -> tuple[list, list, list]:
    """60-calendar-second log returns on mutually-paired seconds."""
    secs = sorted(set(btc) & set(eth))
    have = set(secs)
    xs, ys, paired = [], [], []
    for sec in secs:
        base = sec - 60
        if base not in have:
            continue
        if btc[base] <= 0 or btc[sec] <= 0 \
                or eth[base] <= 0 or eth[sec] <= 0:
            continue
        xs.append(math.log(btc[sec] / btc[base]))
        ys.append(math.log(eth[sec] / eth[base]))
        paired.append(sec)
    return xs, ys, paired


def ols_beta(xs: list[float], ys: list[float]) -> dict:
    """OLS y on x with intercept; raises ValueError when degenerate."""
    n = len(xs)
    if n < MIN_PAIRED:
        raise ValueError(f"only {n} paired returns (< {MIN_PAIRED})")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x <= 0:
        raise ValueError("zero BTC variance")
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    beta = cov / var_x
    return {"n": n, "beta": beta, "intercept": mean_y - beta * mean_x,
            "var_btc": var_x / n}


def ist_day_events(dataset, symbol: str, ist_day: str):
    """Events for one IST day, mirroring the harness windowing exactly.

    The reader serves UTC days; the harness spans the UTC days under
    the IST window and filters to [lo, hi). Same code path, same
    slice (X1.md section 9: DEV indices are IST days).
    """
    from cryptobot.research.backtest import _ist_window_ms, _utc_range

    lo, hi = _ist_window_ms(ist_day)
    for utc_day in sorted(_utc_range(lo, hi - 1)):
        for event in dataset.events(symbol, utc_day):
            if event is None:
                continue
            ts = int(event["exchange_ts_ms"])
            if lo <= ts < hi:
                yield event


def estimate_beta(dataset, day_ids: list[str], out_path: str) -> dict:
    """Run the frozen estimation on explicit IST day ids; write record."""
    all_x, all_y = [], []
    per_day = []
    for day in day_ids:
        btc = closes_from_events(ist_day_events(dataset, LEADER, day))
        eth = closes_from_events(ist_day_events(dataset, LAGGARD, day))
        xs, ys, paired = paired_returns(btc, eth)
        all_x.extend(xs)
        all_y.extend(ys)
        per_day.append({"day": day, "btc_seconds": len(btc),
                        "eth_seconds": len(eth), "paired": len(paired)})
    fit = ols_beta(all_x, all_y)  # raises ValueError when degenerate.
    blob = json.dumps({"x": all_x, "y": all_y}, sort_keys=True)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    record = {
        "tool": "tools/x1_beta.py", "algo": ALGO_ID,
        "dataset_manifest_sha": dataset.manifest_sha(),
        "calibration_idx": list(CALIBRATION_IDX),
        "day_ids": list(day_ids),
        "beta": round(fit["beta"], 6),
        "intercept": fit["intercept"],
        "n": fit["n"],
        "var_btc": fit["var_btc"],
        "returns_sha256": digest,
        "per_day": per_day,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    return record


def cmd_estimate(args) -> int:
    from cryptobot.market_data.datasets import open_dataset
    from cryptobot.research.backtest import day_ids_for

    dataset = open_dataset(args.dataset_toml)
    day_ids = day_ids_for(dataset)
    if len(day_ids) < max(CALIBRATION_IDX):
        print(f"BLOCKED: dataset has {len(day_ids)} days; "
              f"calibration needs idx {max(CALIBRATION_IDX)}")
        return 3
    days = [day_ids[i - 1] for i in CALIBRATION_IDX]
    try:
        record = estimate_beta(dataset, days, args.out)
    except ValueError as exc:
        print(f"BLOCKED: beta estimation failed: {exc}")
        return 3
    print(f"beta={record['beta']:.6f} n={record['n']} "
          f"sha={record['dataset_manifest_sha'][:12]} -> {args.out}")
    return 0


def cmd_check(args) -> int:
    from cryptobot.app.config import load_config

    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    want = float(record["beta"])
    bad = []
    for toml in args.tomls:
        cfg = load_config(toml)
        if cfg.x1_beta != want:
            bad.append(f"{toml}: x1_beta={cfg.x1_beta} != record {want}")
    if bad:
        print("BETA MISMATCH:")
        for line in bad:
            print(f"  {line}")
        return 1
    print(f"beta check ok: {len(args.tomls)} TOMLs == record beta {want}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    est = sub.add_parser("estimate", help="run the frozen beta estimation")
    est.add_argument("--dataset-toml", required=True)
    est.add_argument("--out", required=True)
    chk = sub.add_parser("check", help="TOML beta == record beta")
    chk.add_argument("--record", required=True)
    chk.add_argument("--tomls", nargs="+", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "estimate":
        return cmd_estimate(args)
    return cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
