"""F0.5 triage batch 8: identity, seeding, brackets, watchdog (A#10,B#13,B#14,B#18).

A#10 (LOW): OrderManager.recover restores _seq past journaled ids and
new_client_id never re-mints; paper recovery advances the RNG stream
identically (32-bit, deterministic post-restart ids).
B#13 (MEDIUM): seed refuses when unjournaled (foreign) orders sit on
the venue (stray ids surfaced, not pre-filtered away).
B#14 (MEDIUM): paper run_mode works without venue brackets
(brackets_required_in_run_mode=False on the paper path); the flag
defaults True (live/demo fail closed).
B#18 (MEDIUM): supervision writes the watchdog heartbeat file;
resume-unknown refuses cleanly (live) or fresh-starts loudly
(paper); safe-mode alerts persist to alerts.jsonl.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)


def test_order_manager_recover_restores_seq(tmp_path):
    from datetime import timedelta

    from cryptobot.execution import FakeVenue, OrderManager

    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = OrderManager(venue, log_path=tmp_path / "orders.jsonl",
                           now_utc=lambda: NOW)
    minted = [manager.submit_entry(
        "BTCUSDT", "LONG", 0.01, 67005.0,
        expire_at_utc=NOW + timedelta(seconds=60)).client_id
        for _ in range(3)]
    seqs = [int(cid.split("-")[1]) for cid in minted]
    assert seqs == [1, 2, 3]
    recovered = OrderManager.recover(
        venue, tmp_path / "orders.jsonl", now_utc=lambda: NOW)
    assert recovered._seq == 3  # noqa: SLF001
    nxt = recovered.new_client_id()
    assert int(nxt.split("-")[1]) == 4
    assert nxt not in minted
    more = [recovered.new_client_id() for _ in range(100)]
    assert len(set(more)) == 100
    assert not (set(more) & set(minted))


def test_paper_recovery_ids_match_uninterrupted(tmp_path):
    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    from cryptobot.app.engine import EngineOrder

    def _mk(tag):
        engine = NautilusPaperEngine(
            submit_delay_ms=0, fill_delay_ms=1,
            journal_path=str(tmp_path / f"{tag}.jsonl"),
            run_tag="det", random_seed=42)
        engine.add_instrument("BTCUSDT", price_precision=2,
                              size_precision=3, tick_size=0.01,
                              step_size=0.001, ts_utc=NOW)
        return engine

    uninterrupted = _mk("u")
    ids_full = [uninterrupted.submit(EngineOrder(
        "BTCUSDT", "BUY", 0.001, "MARKET")) for _ in range(4)]

    restarted = _mk("r")
    ids_pre = [restarted.submit(EngineOrder(
        "BTCUSDT", "BUY", 0.001, "MARKET")) for _ in range(3)]
    assert ids_pre == ids_full[:3]
    restarted2 = _mk("r")
    restarted2.recover(lambda event: None)
    assert restarted2.submit(EngineOrder(
        "BTCUSDT", "BUY", 0.001, "MARKET")) == ids_full[3]


def test_seed_refuses_foreign_orders(tmp_path):
    import venue_fixtures as venues
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore
    from cryptobot.cli import _seed_live_session

    account = {"totalWalletBalance": "100.0", "availableBalance": "90.0",
               "totalMarginBalance": "100.0", "totalInitialMargin": "0",
               "positions": []}
    script = [
        ("GET", "/fapi/v2/account", None, ("ok", account)),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [
            {"symbol": "BTCUSDT", "clientOrderId": "manual-1",
             "status": "NEW", "origQty": "0.1", "executedQty": "0"}])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
    ]
    engine, _ = venues.make_engine(tmp_path, script)
    # Modes verification is orthogonal (covered in v008); the unit
    # under test is the foreign-order refusal at seed time.
    engine.verify_account_modes = lambda symbols, leverage_cap: {}
    text = Path("configs/demo.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "demo.toml"
    cfg_path.write_text(text)
    config = load_config(cfg_path)
    session = Session(config, RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "run", "seed-foreign", engine=engine)
    import pytest

    with pytest.raises(ValueError, match="[Ff]oreign"):
        _seed_live_session(session, engine, config)


def test_paper_run_mode_skips_bracket_gate(tmp_path):
    from cryptobot.coordination import (DataQuality, ForecastCost, Intent,
                                        Side)
    from cryptobot.risk import Approved, RiskConfig
    from cryptobot.risk.policy import RiskPolicy
    from cryptobot.risk.types import AccountSnapshot, InstrumentFilter

    filt = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                            max_notional_usdt=1e9, min_qty=0.01,
                            max_qty=1000.0, tick_size=0.1)
    cfg = RiskConfig(run_mode=True,
                     instrument_filters={"BTCUSDT": filt},
                     filters_asof_utc=NOW,
                     brackets_required_in_run_mode=False)
    policy = RiskPolicy(config=cfg, state_path=tmp_path / "risk.json",
                        now_utc=lambda: NOW)
    policy.reconcile_day(10000.0)
    intent = Intent(
        strategy="S1", version="1", instrument="BTCUSDT", side=Side.LONG,
        evidence_ts_utc=NOW, entry_low=100.0, entry_high=101.0,
        entry_expiry_utc=NOW + timedelta(seconds=60),
        invalidation_price=99.0, exit_rule="inv", holding_limit_s=60,
        forecast_cost=ForecastCost(5, 5, 5, 0), evidence_ref="r",
        data_quality=DataQuality.CLEAN)
    acct = AccountSnapshot(reconciled_equity=10000.0,
                           marked_equity=10000.0,
                           net_liquidation=10000.0,
                           net_realised_global=0.0, open_position=False)
    out = policy.evaluate(intent, acct)
    assert isinstance(out, Approved), out
    # Default stays fail-closed for live/demo.
    assert RiskConfig().brackets_required_in_run_mode is True


def test_supervision_writes_watchdog_heartbeat(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    class _Eng:
        model_label = "b8"
        assumptions = ()

        def poll(self):
            return []

        def open_orders(self):
            return []

    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    session = Session(load_config(cfg_path),
                      RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "run", "b8-run", engine=_Eng())
    session.policy.reconcile_day(120.0, 0.0)
    session.store.create_run("b8-run", "paper", "fp",
                             str(session.workdir), None)
    session.control_tick()
    beat = Path(f"{tmp_path / 'runs'}") / "heartbeat.json"
    assert beat.exists(), "no watchdog heartbeat file"
    doc = json.loads(beat.read_text())
    assert set(doc) >= {"ts_utc", "has_exposure", "run_id"}
    assert doc["run_id"] == "b8-run"
    assert doc["has_exposure"] is False


def test_safe_mode_alert_persists(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    class _Eng:
        model_label = "b8b"
        assumptions = ()

        def poll(self):
            return []

        def open_orders(self):
            return []

    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    session = Session(load_config(cfg_path),
                      RunStore(tmp_path / "runs" / "cryptobot.db"),
                      tmp_path / "run", "b8b-run", engine=_Eng())
    out = session.enter_safe_mode("triage")
    assert out["flatten_ok"] is True  # flat: nothing to do
    alerts = (session.workdir / "alerts.jsonl").read_text().splitlines()
    assert any("triage" in line for line in alerts), alerts
