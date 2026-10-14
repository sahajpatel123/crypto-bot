"""REL-W3-DATA (5): suitability table coarse screen."""
import importlib.util
import json
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools" / "suitability_table.py"


def _tool():
    spec = importlib.util.spec_from_file_location("suitability_table", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(root, name, *, malformed=0, injected=0, drop_trades=()):
    cap = root / name
    cap.mkdir()
    (cap / "manifest.json").write_text(json.dumps({
        "run_id": name, "input_class": "observed-public",
        "started_utc": "2026-10-11T21:43:58+00:00",
        "ended_utc": "2026-10-11T22:13:59+00:00",
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "capture_set_rule": "top-2 by test rule"}), encoding="utf-8")
    per_channel = {"market/aggTrade/BTCUSDT": 10,
                   "public/bookTicker/BTCUSDT": 20,
                   "market/markPrice/BTCUSDT": 5,
                   "public/depth/BTCUSDT": 8,
                   "market/aggTrade/ETHUSDT": 11,
                   "public/bookTicker/ETHUSDT": 21,
                   "market/markPrice/ETHUSDT": 5,
                   "public/depth/ETHUSDT": 9}
    for key in drop_trades:
        per_channel.pop(key, None)
    (cap / "run_stats.json").write_text(json.dumps({
        "run_id": name, "events_total": sum(per_channel.values()),
        "malformed": malformed, "per_channel": per_channel,
        "duplicates": 0, "out_of_order": 0,
        "depth_applied": 17, "depth_resyncs": 0,
        "gaps": {"natural": 0, "injected": injected}}), encoding="utf-8")
    return cap


def test_ok_row_and_markdown(tmp_path):
    tool = _tool()
    root = tmp_path / "captures"
    root.mkdir()
    _capture(root, "cap-ok")
    out = tmp_path / "table.md"
    assert tool.main([str(root), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "| cap-ok | BTCUSDT,ETHUSDT |" in text
    assert "2026-10-12" in text  # IST day (UTC+5:30 rolls the date)
    assert "funding" in text and "absent" in text
    row = next(line for line in text.splitlines()
               if line.startswith("| cap-ok |"))
    assert row.endswith("| OK |")


def test_deficient_capture_fails_loud_with_reasons(tmp_path):
    tool = _tool()
    root = tmp_path / "captures"
    root.mkdir()
    _capture(root, "cap-bad", malformed=2, injected=1,
             drop_trades=("market/aggTrade/ETHUSDT",))
    (root / "cap-empty").mkdir()
    out = tmp_path / "table.md"
    assert tool.main([str(root), "--out", str(out)]) == 3
    text = out.read_text(encoding="utf-8")
    assert "NO-TRADES:ETHUSDT" in text
    assert "MALFORMED=2" in text
    assert "INJECTED-GAPS=1" in text
    assert "UNUSABLE" in text
