"""Prove decoded holdout chunks are subsets of the pre-analysis seal.

Matching is by file sha256. A path suffix after ``holdout_raw/`` is
reported so a relocated worktree still identifies the same object.
The script never opens a zip and never returns a price.
"""
from __future__ import annotations

import json
from pathlib import Path


def _files(doc: dict) -> list[dict]:
    files = doc.get("files")
    if not isinstance(files, list):
        raise ValueError("chunk has no files list")
    return files


def _suffix(path: str) -> str:
    marker = "holdout_raw/"
    if marker in path:
        return path.split(marker, 1)[1]
    return path


def reconcile_chunks(parent: str | Path, children: list[str | Path]) -> dict:
    parent_doc = json.loads(Path(parent).read_text(encoding="utf-8"))
    parent_files = _files(parent_doc)
    by_sha: dict[str, str] = {}
    for item in parent_files:
        by_sha[str(item["sha256"])] = _suffix(str(item.get("path", "")))
    rows = []
    ok = True
    for child in children:
        doc = json.loads(Path(child).read_text(encoding="utf-8"))
        missing = []
        mapped = []
        for item in _files(doc):
            sha = str(item["sha256"])
            if sha not in by_sha:
                missing.append(sha)
                continue
            mapped.append({
                "sha256": sha,
                "child_suffix": _suffix(str(item.get("path", ""))),
                "parent_suffix": by_sha[sha],
            })
        if missing:
            ok = False
        rows.append({
            "chunk": Path(child).name,
            "files": len(_files(doc)),
            "mapped": len(mapped),
            "missing": missing,
        })
    return {
        "ok": ok,
        "parent": Path(parent).name,
        "parent_files": len(parent_files),
        "parent_unique_sha256": len(by_sha),
        "children": rows,
    }


def path_kind(path: str) -> str:
    suffix = _suffix(path)
    if suffix.startswith("spot/"):
        return "spot"
    if suffix.startswith("rest_tail/"):
        return "rest_tail"
    if "/klines/" in f"/{suffix}" or suffix.startswith("klines/"):
        return "klines"
    if suffix.startswith("fundingRate/") or "/funding" in suffix:
        return "funding"
    return "other"


def membership_by_kind(parent: str | Path, child: str | Path) -> dict:
    """Count child files inside and outside the parent, by path kind."""
    parent_doc = json.loads(Path(parent).read_text(encoding="utf-8"))
    child_doc = json.loads(Path(child).read_text(encoding="utf-8"))
    parent_sha = {str(item["sha256"]) for item in _files(parent_doc)}
    inside: dict[str, int] = {}
    outside: dict[str, int] = {}
    outside_suffixes: list[str] = []
    for item in _files(child_doc):
        kind = path_kind(str(item.get("path", "")))
        if str(item["sha256"]) in parent_sha:
            inside[kind] = inside.get(kind, 0) + 1
        else:
            outside[kind] = outside.get(kind, 0) + 1
            outside_suffixes.append(_suffix(str(item.get("path", ""))))
    return {
        "chunk": Path(child).name,
        "files": len(_files(child_doc)),
        "inside": inside,
        "outside": outside,
        "outside_suffixes": outside_suffixes,
    }


def decode_census(access_log: str | Path) -> list[dict]:
    doc = json.loads(Path(access_log).read_text(encoding="utf-8"))
    out = []
    for entry in doc.get("entries", []):
        if entry.get("action") != "decode":
            continue
        out.append({
            "who": "verdict",
            "when": entry.get("ts_utc"),
            "hypothesis": entry.get("hypothesis"),
            "chunk_id": entry.get("chunk_id"),
            "token_sha256": entry.get("token_sha256"),
            "files": entry.get("files"),
        })
    return out


__all__ = ["decode_census", "reconcile_chunks"]
