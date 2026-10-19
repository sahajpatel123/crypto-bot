"""Z1.3: map decoded holdout chunks into the pre-analysis seal.

Reads vault chunk manifests (hashes and paths only). Does not open a
zip and does not decode HOLDOUT.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cryptobot.research.holdout_reconcile import decode_census, membership_by_kind, reconcile_chunks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", default="data/vault")
    parser.add_argument("--parent", default="chunk-2a22e52c3c8f50db")
    parser.add_argument("--child", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    vault = Path(args.vault)
    parent = vault / "chunks" / f"{args.parent}.json"
    children = [vault / "chunks" / f"{name}.json" for name in args.child]
    subset = reconcile_chunks(parent, children)
    kinds = [membership_by_kind(parent, child) for child in children]
    # Drop the long suffix lists from the summary; the script can reprint
    # them. Keep counts so the committed proof stays readable.
    for row in kinds:
        row["outside_suffix_count"] = len(row.pop("outside_suffixes"))
    report = {
        "incident": "INC-1",
        "parent_chunk": args.parent,
        "parent_files": subset["parent_files"],
        "subset_ok": subset["ok"],
        "children": [
            {
                "chunk": row["chunk"],
                "files": row["files"],
                "mapped": next(
                    c["mapped"] for c in subset["children"]
                    if c["chunk"] == row["chunk"]),
                "missing_sha_count": len(next(
                    c["missing"] for c in subset["children"]
                    if c["chunk"] == row["chunk"])),
                "inside": row["inside"],
                "outside": row["outside"],
            }
            for row in kinds
        ],
        "decodes": decode_census(vault / "access_log.json"),
        "rule": (
            "B4 holdout was decoded three times. The exactly-once rule "
            "was broken for B4 only. Those decodes are void (D-042)."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"subset_ok": report["subset_ok"],
                      "parent_files": report["parent_files"],
                      "decodes": len(report["decodes"])},
                     sort_keys=True))
    return 0 if report["decodes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
