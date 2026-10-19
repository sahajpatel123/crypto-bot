"""Journal the ref tape: flatten/settle/cancel calls + end state."""
import sys, tempfile, json
sys.path.insert(0, "/tmp/cryto-bot-w1-ready/src")
sys.path.insert(0, "/tmp/cryto-bot-w1-ready/tests/unit")
from pathlib import Path
from test_bench_restart_equivalence import _write_tape, _run_case
from cryptobot.app.session import Session

J = {"flatten": [], "settle": [], "cancel": [], "ensure": []}
_orig_flat = Session._flatten
_orig_settle = Session._settle_leg_terminals
_orig_ensure = Session._ensure_protection

def flat(self, reason):
    J["flatten"].append({"reason": reason,
                         "net": self.ledger.position_qty()})
    return _orig_flat(self, reason)

def settle(self, pos, statuses):
    before = {k: list(pos.get(k) or []) for k in ("legs", "retired")}
    out = _orig_settle(self, pos, statuses)
    after = {k: list(pos.get(k) or []) for k in ("legs", "retired")}
    if before != after or True:
        J["settle"].append({"before": before, "after": after,
                            "live": sorted(
                                c for c, s in statuses.items()
                                if s.state in ("open", "partial"))})
    return out

def ensure(self, pos):
    J["ensure"].append({"legs": list(pos.get("legs") or []),
                        "protected": pos.get("protected")})
    return _orig_ensure(self, pos)

Session._flatten = flat
Session._settle_leg_terminals = settle
Session._ensure_protection = ensure
# also capture engine cancels
from cryptobot.adapters.paper_engine import NautilusPaperEngine
_oc = NautilusPaperEngine.cancel
def cancel(self, cid, reason):
    J["cancel"].append({"id": cid, "reason": reason})
    return _oc(self, cid, reason)
NautilusPaperEngine.cancel = cancel

root = Path(tempfile.mkdtemp()); tape = _write_tape(root)
rc, rep = _run_case(root, "ref", *tape)
print("rc:", rc, rep.get("status"))
print("flatten calls:", len(J["flatten"]), J["flatten"][:6])
print("ensure calls:", len(J["ensure"]))
print("cancels:", J["cancel"])
print("last settles:")
for s in J["settle"][-4:]:
    print("  ", json.dumps(s)[:300])
