"""Copy the netguard core block from the library into the standalone shim.

    python tools/netshim/sync_core.py          # rewrite sitecustomize.py
    python tools/netshim/sync_core.py --check  # exit 1 when they differ

Stdlib only; the core is the text between the "netguard core" / "end netguard core" markers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "src" / "cryptobot" / "netguard.py"
STANDALONE = Path(__file__).resolve().parent / "sitecustomize.py"
CORE = re.compile(r"^# --- netguard core:.*?^# --- end netguard core [^\n]*\n", re.S | re.M)


def core_of(text: str) -> str:
    found = CORE.search(text)
    if found is None:
        raise SystemExit("netguard core markers not found")
    return found.group(0)


def main(argv: list[str]) -> int:
    library = LIBRARY.read_text(encoding="utf-8")
    standalone = STANDALONE.read_text(encoding="utf-8")
    wanted = core_of(library)
    if core_of(standalone) == wanted:
        return 0
    if "--check" in argv:
        print("netshim core differs from src/cryptobot/netguard.py", file=sys.stderr)
        return 1
    STANDALONE.write_text(CORE.sub(lambda _m: wanted, standalone, count=1), encoding="utf-8")
    print("netshim core synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
