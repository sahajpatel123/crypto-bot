"""Debug: why does the ref tape end INCOMPLETE after the lifecycle fix?"""
import sys, tempfile, sqlite3, json
sys.path.insert(0, "/tmp/cryto-bot-w1-ready/src")
sys.path.insert(0, "/tmp/cryto-bot-w1-ready/tests/unit")
from pathlib import Path
from test_bench_restart_equivalence import _write_tape, _run_case

root = Path(tempfile.mkdtemp())
tape = _write_tape(root)
rc, rep = _run_case(root, "ref", *tape)
print("rc:", rc, "status:", rep.get("status"))
db = sqlite3.connect(str(root / "ref" / "ck" / "store.db"))
try:
    cps = db.execute(
        "SELECT kind, payload FROM checkpoints ORDER BY id").fetchall()
finally:
    db.close()
from collections import Counter
print("checkpoint kinds:", Counter(k for k, _ in cps))
for k, p in cps:
    if k in ("protection-emergency", "flatten", "admit", "exposure-noted",
             "executable-narrowed", "filters-synced", "protection-partial"):
        print(" ", k, p[:220])
