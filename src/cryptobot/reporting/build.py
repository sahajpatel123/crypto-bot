"""Report builder (V-007, B9): run files → CSVs + summary + standalone HTML.

`build_report(run_dir, out_dir)` is the single entry point (the manager's
`cryptobot report --run-dir` calls it). All artifacts rebuild
deterministically from persisted files; reconciliation failures raise
before anything is written.
"""
from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptobot.reporting import charts
from cryptobot.reporting.episodes import build_episodes
from cryptobot.reporting.metrics import compute_metrics
from cryptobot.reporting.schemas import load_run, write_csv

IST = ZoneInfo("Asia/Kolkata")


def build_report(run_dir: str | Path, out_dir: str | Path) -> dict[str, str]:
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    run = load_run(run_dir)
    journal = run.ledger.to_dict()["journal"]
    funding = [(e["ts_utc"], e["amount"]) for e in journal if e["kind"] == "funding"]
    from datetime import datetime
    funding = [(datetime.fromisoformat(ts), amount) for ts, amount in funding]
    end_ts = datetime.fromisoformat(str(run.config["run"]["window_end_utc"]))
    strategy = run.config["run"].get("strategy") or "unknown"
    episodes = build_episodes(run.fills, funding, end_ts, strategy=strategy)
    metrics = compute_metrics(run, episodes)
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_trades(out_dir / "trades.csv", episodes)
    _write_equity(out_dir / "equity.csv", run)
    write_csv(out_dir / "daily_returns.csv",
              ["date", "ret", "label", "full_day", "n_episodes"],
              metrics.daily["days"])
    write_csv(out_dir / "rejections.csv",
              ["ts_utc", "stage", "reason", "strategy", "instrument", "side"],
              [{"ts_utc": r.ts_utc.isoformat(), "stage": r.stage, "reason": r.reason,
                "strategy": r.strategy, "instrument": r.instrument, "side": r.side}
               for r in run.rejections])
    summary = metrics.to_dict()
    summary["provenance"] = {
        "dataset_manifest": run.manifest,
        "run_strategy": strategy,
        "builder": "cryptobot.reporting.build",
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True),
                                          encoding="utf-8")
    (out_dir / "report.html").write_text(_render_html(metrics, episodes, run),
                                         encoding="utf-8")
    return {name: str(out_dir / name) for name in
            ("summary.json", "trades.csv", "equity.csv", "daily_returns.csv",
             "rejections.csv", "report.html")}


def _write_trades(path: Path, episodes) -> None:
    rows = [{
        "episode_id": e.episode_id, "symbol": e.symbol, "side": e.side,
        "strategy": e.strategy, "open_ts_utc": e.open_ts_utc.isoformat(),
        "close_ts_utc": e.close_ts_utc.isoformat(), "holding_s": round(e.holding_s, 3),
        "qty": e.qty, "entry_px": e.entry_px, "exit_px": e.exit_px,
        "gross": round(e.gross, 8), "fees": round(e.fees, 8),
        "funding": round(e.funding, 8), "net": round(e.net, 8),
        "exit_reason": e.exit_reason, "legs": len(e.legs),
        "end_of_data": str(e.end_of_data),
        "mfe_usdt": "" if e.mfe_usdt is None else e.mfe_usdt,
        "mae_usdt": "" if e.mae_usdt is None else e.mae_usdt,
    } for e in episodes]
    write_csv(path, ["episode_id", "symbol", "side", "strategy", "open_ts_utc",
                     "close_ts_utc", "holding_s", "qty", "entry_px", "exit_px",
                     "gross", "fees", "funding", "net", "exit_reason", "legs",
                     "end_of_data", "mfe_usdt", "mae_usdt"], rows)


def _write_equity(path: Path, run) -> None:
    rows, peak = [], 0.0
    for r in run.equity:
        peak = max(peak, r.marked_equity)
        dd = peak - r.marked_equity
        rows.append({
            "ts_utc": r.ts_utc.isoformat(), "marked_equity": r.marked_equity,
            "cash": r.cash, "position_qty": r.position_qty,
            "position_symbol": r.position_symbol, "open_pnl": r.open_pnl,
            "source": r.source, "drawdown_usdt": round(dd, 8),
            "drawdown_pct": round(dd / peak, 8) if peak else 0.0,
            "date_ist": r.ts_utc.astimezone(IST).date().isoformat(),
            "mark_source": r.mark_source,
            "mark_age_ms": "" if r.mark_age_ms is None else r.mark_age_ms,
        })
    write_csv(path, ["ts_utc", "marked_equity", "cash", "position_qty",
                     "position_symbol", "open_pnl", "source", "drawdown_usdt",
                     "drawdown_pct", "date_ist", "mark_source",
                     "mark_age_ms"], rows)


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:+.2%}"


def _num(v, nd: int = 2) -> str:
    return "n/a" if v is None else f"{v:+,.{nd}f}"


def _render_html(metrics, episodes, run) -> str:
    caption = (f"Dataset {metrics.dataset}; window {metrics.window_start_utc} .. "
               f"{metrics.window_end_utc} ({metrics.mode}).")
    eq = [r.marked_equity for r in run.equity]
    peak, dd_curve = 0.0, []
    for v in eq:
        peak = max(peak, v)
        dd_curve.append(peak - v)
    days = metrics.daily["days"]
    day_labels = [d["date"][5:] for d in days if d["ret"] is not None]
    day_vals = [d["ret"] for d in days if d["ret"] is not None]
    strat = metrics.behavior["per_strategy"]
    names = sorted(strat)
    first = _first_page(metrics)
    tables = _tables(metrics)
    charts_html = "\n".join([
        charts.line_chart("Equity (marked, USDT)", caption, eq),
        charts.drawdown_chart("Drawdown (USDT)", caption, dd_curve),
        charts.bar_chart("Daily returns", caption, day_labels, day_vals),
        charts.strategy_chart("Net by strategy (USDT)", caption, names,
                              [strat[s]["net"] for s in names]),
    ])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest report — {metrics.dataset}</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#1a1a1a;
max-width:960px;margin:2rem auto;padding:0 1.2rem;line-height:1.5}}
h1{{font-size:1.5rem;border-bottom:2px solid #1a1a1a;padding-bottom:.4rem}}
h2{{font-size:1.15rem;margin-top:2rem;border-bottom:1px solid #d8d8d8;
padding-bottom:.25rem}}
table{{border-collapse:collapse;margin:.8rem 0;width:100%;font-size:.9rem}}
th,td{{text-align:left;padding:.35rem .6rem;border-bottom:1px solid #e2e2e2}}
th{{font-weight:600}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.label{{color:#6b6b6b;font-size:.85rem}}
figure{{margin:1.2rem 0}}
figcaption{{color:#6b6b6b;font-size:.85rem;margin-top:.3rem}}
ol.answers li{{margin:.4rem 0}}
</style></head><body>
<h1>Backtest report — {metrics.dataset}</h1>
<p class="label">{caption} Reconciliation: {metrics.reconciliation["status"]}
({", ".join(metrics.reconciliation["checks"])}).</p>
<h2>First page</h2>
<ol class="answers">{first}</ol>
{charts_html}
<h2>Metrics</h2>
{tables}
<h2>Methods and assumptions</h2>
<p class="label">Episodes rebuild from fills (partials are legs); funding
shares attribute by window overlap; end-of-data closes are marked at the last
fill price and labeled. Close costs are excluded from returns; ending open
exposure is shown, not liquidated. MFE/MAE need bar data and are null here.
Speed timings are reported only when the run files record them. Short samples
(n&lt;30) are labeled insufficient; undefined denominators are labeled, never
faked. No annualization; no blended splits.</p>
</body></html>"""


def _first_page(m) -> str:
    ret = m.net_return["net_return"]
    dd = m.drawdown
    made = "made" if ret > 0 else ("lost" if ret < 0 else "held flat")
    strat = m.behavior["per_strategy"]
    helped = ", ".join(f"{s} ({v['net']:+,.0f})"
                       for s, v in sorted(strat.items()) if v["net"] > 0) or "none"
    hurt = ", ".join(f"{s} ({v['net']:+,.0f})"
                     for s, v in sorted(strat.items()) if v["net"] < 0) or "none"
    nodata = ", ".join(s for s, v in sorted(strat.items()) if v["n"] == 0) or "none"
    return (
        f"<li>After costs this version <b>{made} {_pct(ret)}</b> net.</li>"
        f"<li>Worst account decline: <b>{dd['max_drawdown_usdt']:,.0f} USDT "
        f"({_pct(dd['max_drawdown_pct'])})</b>.</li>"
        f"<li><b>{m.n_episodes}</b> completed positions "
        f"({m.expectancy.get('label', '')}).</li>"
        f"<li>Helped: {helped}. Hurt: {hurt}. No data: {nodata}.</li>"
        "<li>Worse costs/delays: see cost burden vs expectancy; sensitivity "
        "analysis is strategy-side work.</li>"
        "<li>Next: see reliability gaps and no-coverage days below.</li>")


def _kv(rows: list[tuple[str, str]]) -> str:
    return ("<table><tbody>" + "".join(
        f"<tr><th>{k}</th><td class=\"num\">{v}</td></tr>" for k, v in rows)
        + "</tbody></table>")


def _tables(m) -> str:
    e, w, c, d = m.expectancy, m.win_loss, m.costs, m.daily
    pf = "undefined (no losing episodes)" if w["profit_factor"] is None \
        else f"{w['profit_factor']:.2f}"
    b = m.behavior
    return "\n".join([
        "<h3>Account</h3>" + _kv([
            ("Net return", _pct(m.net_return["net_return"])),
            ("Ending marked equity", f"{m.net_return['end_marked_equity']:,.2f}"),
            ("Flows total", f"{m.net_return['flows_total']:+,.2f}"),
            ("Open exposure (end)", f"{m.net_return['open_exposure_end_usdt']:,.2f}"),
        ]),
        "<h3>Expectancy</h3>" + _kv([
            ("Mean net / episode", _num(e.get("mean_net")) if e.get("n") else "n/a"),
            ("Episodes", str(e.get("n"))),
            ("95% CI half-width",
             _num(e.get("ci95_half_width")) if e.get("ci95_half_width") else "n/a"),
            ("Sample", e.get("label", "")),
        ]),
        "<h3>Wins / losses</h3>" + _kv([
            ("Win rate", "n/a" if w["win_rate"] is None else f"{w['win_rate']:.1%}"),
            ("Profit factor", pf),
            ("W/L/flat", f"{w['wins']}/{w['losses']}/{w['flats']}"),
        ]),
        "<h3>Behavior</h3>" + _kv([
            ("Fills / legs / partial episodes",
             f"{b['fills']} / {b['episode_legs']} / {b['episodes_with_partials']}"),
            ("Exposure time", f"{b['exposure_time_s']:,.0f} s"),
            ("Holding p50/p95",
             f"{b['holding_p50_s'] or 0:,.0f} / {b['holding_p95_s'] or 0:,.0f} s"),
            ("Long / short", f"{b['long_episodes']} / {b['short_episodes']}"),
            ("Exits", ", ".join(f"{k}={v}" for k, v in b["exit_reasons"].items()) or "—"),
        ]),
        "<h3>Costs</h3>" + _kv([
            ("Entry fees", f"{c['entry_fees']:,.2f}"),
            ("Exit fees", f"{c['exit_fees']:,.2f}"),
            ("Funding (signed)", f"{c['funding_total']:+,.2f}"),
            ("Execution effects", c["execution_effects"]),
        ]),
        "<h3>Daily evidence</h3>" + _kv([
            ("Full covered days", str(d["full_covered_days"])),
            ("Mean / median", f"{_pct(d['mean'])} / {_pct(d['median'])}"),
            ("Best / worst", f"{_pct(d['best'])} / {_pct(d['worst'])}"),
            ("Days ≥ +2% / ≥ +3%",
             f"{d['fraction_ge_2pct'] or 0:.0%} / {d['fraction_ge_3pct'] or 0:.0%}"),
        ]),
        "<h3>Reliability</h3>" + _kv([
            ("Equity gaps",
             f"{m.reliability['equity_gaps']['count']} "
             f"({m.reliability['equity_gaps']['total_s']:,.0f} s)"),
            ("Restarts", str(m.reliability["restarts"])),
            ("Lost events", str(m.reliability["lost_events"])),
            ("Mark sources",
             ", ".join(f"{k}={v}"
                       for k, v in m.reliability["mark_provenance"]["by_source"].items())),
            ("Open rows without mark",
             str(m.reliability["mark_provenance"]["open_rows_without_mark"])),
        ]),
        "<h3>Speed / resources</h3>" + _kv([
            ("Status", str(m.speed_resources["status"])),
        ]),
    ])
