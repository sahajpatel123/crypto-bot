"""Finding 2: minute close published at minute open (Worker 5, OP-001).

Directive section 2: datasets/prepare_benchmark_30d.py:_convert_marks
pairs open_time with close. A closing value available at 60999ms is
emitted at 1000ms in the probe.

Required: publish values no earlier than actual availability; preserve
open/close/availability times. Version and rebuild affected derived
data while retaining raw archives.

These probes FAIL on the 01487ac base (bug reproduced) and PASS once
the causal fix lands. No src/ edits in OP-001.
"""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

PREP = Path(__file__).resolve().parents[2] / "datasets" / "prepare_benchmark_30d.py"


def _load_prep():
    spec = importlib.util.spec_from_file_location("prepare_benchmark_30d", PREP)
    assert spec is not None and spec.loader is not None, f"cannot load {PREP}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows():
    header = ["open_time", "open", "high", "low", "close", "volume",
              "close_time", "quote_volume", "count",
              "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
    body = ["1000", "49000", "51000", "48900", "50000", "12.5",
            "60999", "625000", "150", "6.0", "300000", "0"]
    return [header, body]


def test_close_not_published_at_open():
    """Close available at 60999ms must not be emitted at 1000ms."""
    prep = _load_prep()
    marks = prep._convert_marks(_rows())
    assert len(marks) == 1, f"expected one mark, got {marks}"
    item = marks[0]
    if isinstance(item, dict):
        ts = int(item.get("ts_ms", item.get("close_time_ms", -1)))
        avail = int(item.get("available_ms", item.get("close_time_ms", 60999)))
    elif isinstance(item, (tuple, list)) and len(item) >= 3:
        # Fixed shape carries availability explicitly; ts is first.
        ts = int(item[0])
        avail = int(item[2]) if len(item) >= 3 else 60999
    else:
        ts, _ = item[0], item[1]
        ts = int(ts)
        avail = 60999
    assert ts >= avail, (
        f"close emitted at {ts}ms, available no earlier than {avail}ms")
    assert ts != 1000 or avail <= 1000, (
        "close paired with minute open_time (1000ms), "
        f"available at {avail}ms")


def test_open_close_availability_preserved():
    """Fixed transform must preserve open/close/availability, not one ts."""
    prep = _load_prep()
    marks = prep._convert_marks(_rows())
    assert len(marks) == 1
    item = marks[0]
    if isinstance(item, dict):
        keys = {k.lower() for k in item}
        has_open = any("open" in k for k in keys)
        has_close = any("close" in k for k in keys)
        has_avail = any(a in k for k in keys
                        for a in ("avail", "close_time", "close_ms"))
        assert has_open and has_close and has_avail, (
            f"mark dict must preserve open/close/availability, got {sorted(item)}")
        return
    if isinstance(item, (tuple, list)):
        assert len(item) >= 3, (
            f"mark tuple must carry (ts, mark, availability...) "
            f"not just (open_time, close); got {item!r}")
        return
    raise AssertionError(f"unexpected mark shape: {item!r}")


def test_joined_marks_preserve_availability(tmp_path):
    """Parquet marks must not stamp the close at the open; keep availability."""
    prep = _load_prep()
    marks = prep._convert_marks(_rows())
    dest = tmp_path / "markPrice" / "part.parquet"
    n, ts_min, ts_max, _ = prep._join_marks(marks, [], dest)
    assert n == 1, f"expected one joined row, got {n}"
    assert ts_min >= 60999, (
        f"joined mark ts {ts_min}ms precedes availability 60999ms")
    import pyarrow.parquet as pq
    table = pq.read_table(str(dest))
    cols = set(table.column_names)
    assert "ts_ms" in cols and "mark" in cols, f"columns: {sorted(cols)}"
    has_avail = any(a in c for c in cols
                    for a in ("avail", "open_ts", "close_ts", "open_ms",
                              "close_ms", "open_time", "close_time"))
    assert has_avail, (
        f"mark parquet must preserve open/close/availability columns, "
        f"got {sorted(cols)}")
