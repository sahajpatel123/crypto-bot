"""C2-FWD forward paper recorder (prereg: research/prereg/C2-forward.md).

Public REST only: no keys, no orders. Run once a day after 00:05 UTC:

  .venv/bin/python tools/forward_c2.py record [--root data/forward_c2]
  .venv/bin/python tools/forward_c2.py health [--root data/forward_c2]
  .venv/bin/python tools/forward_c2.py score --look K   # only at 365/730/1095 days

Each run books every completed UTC day since the last one (catch-up is
safe; re-running the same day appends nothing). `health` reports only
recorder coverage — never P&L statistics. `score` runs each preregistered
look exactly once (amendment 1: O'Brien-Fleming, alpha 0.05 overall).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.research import c_family, quant  # noqa: E402

BASE = "https://fapi.binance.com"
UNIVERSE_SIZE = 30
HISTORY_DAYS = c_family.MIN_HISTORY_DAYS + 2
REPORTS = Path(__file__).resolve().parents[1] / "reports/hypotheses"
# Amendment 1: group-sequential looks (days) and one-sided O'Brien-Fleming
# z bounds for overall alpha 0.05 (quant.obf_bounds(3), frozen here).
LOOKS = (365, 730, 1095)
OBF_BOUNDS = (2.973, 2.102, 1.717)
VM_TARGET_BPS, VM_CAP, VM_WINDOW, VM_WARMUP = 150.0, 2.0, 120, 20


class Fetcher(Protocol):
    def trading_symbols(self) -> list[str]: ...
    def quote_volume_30d(self, symbol: str, end_day: str) -> float: ...
    def mark_closes(self, symbol: str, start: str, end: str) -> dict[str, float]: ...
    def funding(self, symbol: str, start: str, end: str) -> dict[str, float]: ...


def _ms(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp() * 1000)


def _day(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).strftime("%Y-%m-%d")


def _shift(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


class RestFetcher:
    """Binance USD-M public endpoints (no credentials)."""

    def _get(self, path: str, **params) -> object:
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "cryptobot-c2-fwd"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())

    def trading_symbols(self) -> list[str]:
        info = self._get("/fapi/v1/exchangeInfo")
        return sorted(s["symbol"] for s in info["symbols"]  # type: ignore[index]
                      if s.get("contractType") == "PERPETUAL"
                      and s.get("quoteAsset") == "USDT"
                      and s.get("status") == "TRADING")

    def quote_volume_30d(self, symbol: str, end_day: str) -> float:
        rows = self._get("/fapi/v1/klines", symbol=symbol, interval="1d",
                         startTime=_ms(_shift(end_day, -29)),
                         endTime=_ms(end_day) + 86_399_999, limit=30)
        return sum(float(r[7]) for r in rows)  # type: ignore[union-attr]

    def mark_closes(self, symbol: str, start: str, end: str) -> dict[str, float]:
        rows = self._get("/fapi/v1/markPriceKlines", symbol=symbol, interval="1d",
                         startTime=_ms(start), endTime=_ms(end) + 86_399_999,
                         limit=1500)
        return {_day(int(r[0])): float(r[4]) for r in rows}  # type: ignore[union-attr]

    def funding(self, symbol: str, start: str, end: str) -> dict[str, float]:
        rows = self._get("/fapi/v1/fundingRate", symbol=symbol,
                         startTime=_ms(start), endTime=_ms(end) + 86_399_999,
                         limit=1000)
        out: dict[str, float] = {}
        for r in rows:  # type: ignore[union-attr]
            day = _day(int(r["fundingTime"]))
            out[day] = out.get(day, 0.0) + float(r["fundingRate"])
        return out


def _universe(fetcher: Fetcher, day: str) -> list[str]:
    vols = []
    for sym in fetcher.trading_symbols():
        try:
            vols.append((fetcher.quote_volume_30d(sym, day), sym))
        except Exception:  # noqa: BLE001 — unreadable symbol is skipped
            continue
    return sorted(s for _, s in sorted(vols, reverse=True)[:UNIVERSE_SIZE])


def book_day(fetcher: Fetcher, state: dict, t_day: str) -> dict:
    """Decide at the close of t_day, earn t_day -> t_day+1. Returns ledger row."""
    nxt = _shift(t_day, 1)
    if c_family._is_monday(t_day) or not state.get("universe"):
        state["universe"] = _universe(fetcher, t_day)
    syms = sorted(set(state["universe"]) | set(state.get("held", {})))
    start = _shift(t_day, -HISTORY_DAYS)
    closes = {s: fetcher.mark_closes(s, start, nxt) for s in syms}
    funding = {s: fetcher.funding(s, nxt, nxt) for s in syms}
    days = [_shift(start, k) for k in range(HISTORY_DAYS + 2)]
    t = days.index(t_day)
    eligible = [s for s in c_family._eligible(closes, days, t)
                if s in state["universe"]]
    held = {s: w for s, w in state.get("held", {}).items() if s in eligible}
    target = held
    if c_family._is_monday(t_day) or not held:
        target = c_family.signal_xsmom(closes, funding, days, t, eligible)
    turnover = sum(abs(target.get(s, 0.0) - held.get(s, 0.0))
                   for s in set(target) | set(held))
    # exits forced by missing data/delisting are charged like any trade
    turnover += sum(abs(w) for s, w in state.get("held", {}).items() if s not in held)
    gross = sum(w * (closes[s][nxt] / closes[s][t_day] - 1) for s, w in target.items()) * 1e4
    fund = sum(w * funding[s].get(nxt, 0.0) for s, w in target.items()) * 1e4
    state["held"] = target
    cost = turnover * c_family.COST_BPS_PER_SIDE
    return {"day": nxt, "decided_at_close": t_day, "weights": target,
            "universe": state["universe"], "turnover": turnover,
            "gross_bps": gross - fund, "net_bps": gross - fund - cost,
            "adverse_bps": gross - fund - 2 * cost}


def record(root: Path, fetcher: Fetcher, today: str) -> int:
    """Book every completed day up to yesterday; returns rows appended."""
    root.mkdir(parents=True, exist_ok=True)
    state_path, ledger = root / "state.json", root / "ledger.jsonl"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    last_full = _shift(today, -1)  # yesterday's daily close is final
    t_day = state.get("last_booked") or _shift(last_full, -1)
    appended = 0
    while t_day < last_full:
        row = book_day(fetcher, state, t_day)
        with ledger.open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        t_day = row["day"]
        state["last_booked"] = t_day
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
        tmp.replace(state_path)
        appended += 1
    return appended


def _rows(root: Path) -> list[dict]:
    ledger = root / "ledger.jsonl"
    return [json.loads(ln) for ln in ledger.read_text().splitlines()] \
        if ledger.exists() else []


def health(root: Path) -> dict:
    days = [r["day"] for r in _rows(root)]
    gaps = [d for a, d in zip(days, days[1:], strict=False) if d != _shift(a, 1)]
    due = [k + 1 for k, n in enumerate(LOOKS) if len(days) >= n]
    return {"scored_days": len(days), "first": days[0] if days else None,
            "last": days[-1] if days else None, "gaps": gaps,
            "looks_due": due, "next_look_at_days": next(
                (n for n in LOOKS if len(days) < n), None)}


def vol_managed(net: list[float]) -> list[float]:
    """C2-VM secondary arm (descriptive): EWMA vol-targeted C2 net bps."""
    out, prev = [], 1.0
    for t, x in enumerate(net):
        lev = quant.vol_target_leverage(net[max(0, t - VM_WINDOW):t], VM_TARGET_BPS,
                                        VM_CAP) if t >= VM_WARMUP else 1.0
        out.append(x * lev - abs(lev - prev) * c_family.COST_BPS_PER_SIDE)
        prev = lev
    return out


def score_look(root: Path, out_dir: Path, look: int) -> dict:
    """Group-sequential look `look` (1-based); each look runs exactly once."""
    if not 1 <= look <= len(LOOKS):
        raise ValueError(f"look must be 1..{len(LOOKS)}")
    out = out_dir / f"C2-forward-look{look}.json"
    if out.exists():
        raise FileExistsError(f"{out.name} exists (each look runs exactly once)")
    if look > 1 and not (out_dir / f"C2-forward-look{look - 1}.json").exists():
        raise RuntimeError(f"look {look - 1} has not been scored")
    rows = _rows(root)[:LOOKS[look - 1]]
    if len(rows) < LOOKS[look - 1]:
        raise RuntimeError(f"{len(rows)} of {LOOKS[look - 1]} days recorded")
    results = [c_family.DayResult(r["day"], r["net_bps"], r["adverse_bps"],
                                  r["gross_bps"], r["turnover"]) for r in rows]
    stats = c_family.score(results)
    z = statistics.NormalDist().inv_cdf(1 - stats["p_value"])
    crossed = z >= OBF_BOUNDS[look - 1] and stats["mean_adverse_bps"] > 0
    final = look == len(LOOKS)
    verdict = "FORWARD-PASS" if crossed else ("KILLED" if final else "CONTINUE")
    vm = quant.moments(vol_managed([r.net_bps for r in results]))
    doc = {"hypothesis": "C2-XSMOM-forward", "look": look, "days": len(rows),
           "prereg": ["research/prereg/C2-forward.md",
                      "research/prereg/C2-forward-amendment-1.md"],
           "z": z, "bound": OBF_BOUNDS[look - 1], "verdict": verdict, **stats,
           "secondary_C2_VM_descriptive": {
               "mean_bps": vm.mean,
               "sharpe_annual": quant.annualize_sharpe(vm.sharpe)}}
    out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1) + "\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("record", "health", "score"))
    ap.add_argument("--root", default="data/forward_c2")
    ap.add_argument("--look", type=int, help="score: look number 1..3")
    args = ap.parse_args()
    root = Path(args.root)
    if args.cmd == "health":
        print(json.dumps(health(root), indent=1))
        return 0
    if args.cmd == "score":
        doc = score_look(root, REPORTS, args.look or 0)
        print(json.dumps(doc, indent=1))
        return 0
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    print(f"forward_c2: appended {record(root, RestFetcher(), today)} day(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
