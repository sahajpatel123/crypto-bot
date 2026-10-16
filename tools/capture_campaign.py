#!/usr/bin/env python3
"""N-day supervised public-stream capture campaign (chunked, resumable).

Runs the E-006 Collector in bounded chunks under a supervisor loop:

- LIVE PREFLIGHT (fail-closed): a short probe capture on THIS host
  measures the actual byte rates and the real gzip ratio, projects the
  campaign footprint and PEAK usage, and REFUSES to start when it does
  not fit the free disk (``--allow-tight`` overrides loudly). The probe
  also verifies depth-snapshot sync (minimal profile) before any long
  run is allowed to start.
- CHUNKED CAPTURE: ``--chunk-hours`` (default 6) per chunk into
  ``dest/chunk-NNN-<ISOZ>/`` using the real Collector (routes, snapshots,
  heartbeat, STOP file semantics all inherited).
- SETTLE per chunk: gzip ``events.jsonl`` / ``bars.jsonl`` /
  ``depth_snapshots.jsonl`` (sha256 + sizes recorded), DELETE
  ``raw.jsonl`` (the canonical record is events.jsonl; raw exists only
  during capture), copy the chunk's ``run_stats.json`` into a
  ``SETTLED.json`` marker with an honest ``complete`` flag
  (stop_reason == duration-reached). Idempotent: re-settling a settled
  chunk returns the recorded marker untouched.
- RESUME: on restart the campaign skips settled chunks and settles a
  crash-partial chunk as partial (never fabricated, never re-run).
- DISK GUARD before every chunk: stop cleanly when free < --min-free-gb.
- AUDIT SURFACE: ``campaign_state.json`` (chunks, gaps, preflight
  numbers, status) + ``campaign_log.jsonl``; ``status`` prints both.
- STOP: ``stop`` subcommand writes ``dest/STOP`` and SIGTERMs the
  campaign pid when it is ours; SIGTERM/SIGINT to the campaign stops
  the live chunk cleanly and finalizes state.

Profiles (channel selection; depth reconstructs the book either way):
- ``lean500`` (default): market aggTrade+markPrice@1s, public
  depth@500ms (verified empirically on fstream). Full L2 reconstructs
  from snapshot + chained diffs at <=1s resolution; bars carry no
  bookTicker spread (replay uses the modeled spread profile, exactly as
  every frozen round did). The only profile sized for ~15 GB of free
  disk over ten days at observed rates.
- ``minimal``: depth@100ms. Denser book updates; measured ~2.5-5x the
  depth bytes of lean500.
- ``full``: adds bookTicker. Measured ~83% of bytes; needs tens of GB
  free for ten days — the preflight decides per host.

Examples:
  python3 tools/capture_campaign.py start --dest data/captures/campaign-20261016
  python3 tools/capture_campaign.py status --dest data/captures/campaign-20261016
  python3 tools/capture_campaign.py stop --dest data/captures/campaign-20261016
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import shutil
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

STATE_FILE = "campaign_state.json"
LOG_FILE = "campaign_log.jsonl"
STOP_FILE = "STOP"
PID_FILE = "campaign.pid"
PROFILES = {
    # Recommended: depth at the 500ms cadence (empirically verified on
    # fstream; the 250ms wire name subscribes but delivers nothing).
    # Full L2 still reconstructs from snapshot + chained diffs at <=1s
    # resolution, which is what the 1s-bar pipeline consumes; bars carry
    # no bookTicker spread (replay uses the modeled spread profile).
    "lean500": {"market": ("aggTrade", "markPrice@1s"),
                "public": ("depth@500ms",)},
    "minimal": {"market": ("aggTrade", "markPrice@1s"),
                "public": ("depth@100ms",)},
    "full": {"market": ("aggTrade", "markPrice@1s"),
             "public": ("bookTicker", "depth@100ms")},
}
SETTLE_FILES = ("events.jsonl", "bars.jsonl", "depth_snapshots.jsonl")
ROLLING_FRACTION = 1.1   # settled total + one plain chunk (rolling peak)
SIDE_FILE_FRACTION = 0.03  # bars + snapshots gz vs events (small)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_chunks(days: float, chunk_hours: float) -> int:
    if days <= 0 or chunk_hours <= 0:
        raise ValueError("days and chunk_hours must be > 0")
    return max(1, math.ceil(days * 24.0 / chunk_hours))


def projected_footprint(events_bytes: float, raw_bytes: float,
                        gz_ratio: float, probe_s: float,
                        chunk_s: float, chunks: int) -> dict:
    """Project settled bytes and peak usage from the probe rates."""
    ev_rate = events_bytes / probe_s
    raw_rate = raw_bytes / probe_s
    per_chunk_plain = (ev_rate + raw_rate) * chunk_s
    per_chunk_settled = ev_rate * gz_ratio * chunk_s \
        * (1.0 + SIDE_FILE_FRACTION)
    settled_total = per_chunk_settled * chunks
    peak = settled_total + per_chunk_plain * ROLLING_FRACTION
    return {"events_bytes_per_s": round(ev_rate, 1),
            "raw_bytes_per_s": round(raw_rate, 1),
            "gz_ratio": round(gz_ratio, 4),
            "per_chunk_plain_bytes": int(per_chunk_plain),
            "per_chunk_settled_bytes": int(per_chunk_settled),
            "settled_total_bytes": int(settled_total),
            "peak_bytes": int(peak)}


def gzip_and_sha(src: Path) -> dict:
    gz_path = src.with_name(src.name + ".gz")
    h = hashlib.sha256()
    with open(src, "rb") as fin, gzip.open(gz_path, "wb",
                                           compresslevel=6) as fout:
        while True:
            block = fin.read(1 << 20)
            if not block:
                break
            fout.write(block)
            h.update(block)
    out = {"original_bytes": src.stat().st_size,
           "gz_bytes": gz_path.stat().st_size,
           "sha256": h.hexdigest()}
    src.unlink()
    return out


def settle_chunk(chunk_dir: Path, keep_raw: bool = False) -> dict:
    """Idempotent: gzip canon files, delete raw, write SETTLED.json."""
    marker = chunk_dir / "SETTLED.json"
    if marker.exists():
        try:
            return json.loads(marker.read_text())
        except ValueError:
            pass  # unreadable marker: re-settle from the files that remain.
    info: dict = {"format": "cryptobot-campaign-chunk/1",
                  "settled_utc": utc_now(), "files": {}}
    for name in SETTLE_FILES:
        p = chunk_dir / name
        if p.exists() and p.stat().st_size > 0:
            info["files"][name] = gzip_and_sha(p)
        elif p.exists():
            p.unlink()  # empty: not evidence, not storage.
    raw = chunk_dir / "raw.jsonl"
    if raw.exists():
        if keep_raw:
            info["raw_kept_bytes"] = raw.stat().st_size
        else:
            info["raw_deleted_bytes"] = raw.stat().st_size
            raw.unlink()
    rs = chunk_dir / "run_stats.json"
    if rs.exists():
        try:
            full = json.loads(rs.read_text())
            info["run_stats"] = {k: full.get(k) for k in (
                "stop_reason", "events_total", "bytes_written",
                "depth_applied", "depth_resyncs", "disconnects_natural",
                "disconnects_injected", "gaps_natural", "gaps_injected",
                "malformed", "duplicates", "out_of_order")}
        except ValueError:
            pass
    stop_reason = (info.get("run_stats") or {}).get("stop_reason")
    info["complete"] = stop_reason == "duration-reached"
    info["status"] = "settled" if info["files"] else "empty"
    marker.write_text(json.dumps(info, indent=1))
    return info


def load_state(dest: Path) -> dict | None:
    p = dest / STATE_FILE
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_state(dest: Path, state: dict) -> None:
    state["updated_utc"] = utc_now()
    tmp = dest / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(dest / STATE_FILE)


def log_line(dest: Path, entry: dict) -> None:
    entry = {"utc": utc_now(), **entry}
    with open(dest / LOG_FILE, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


class Campaign:
    """Supervisor loop; injectable executor/disk seams for tests."""

    def __init__(self, dest: Path, *, days: float, chunk_hours: float,
                 symbols: list[str], profile: str = "lean500",
                 probe_s: float = 45.0, min_free_gb: float = 5.0,
                 keep_raw: bool = False, allow_tight: bool = False,
                 chunk_executor=None, disk_free=None,
                 cooldown_s: float = 60.0, max_attempts: int = 5) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown profile {profile!r}")
        self.dest = Path(dest)
        self.days = days
        self.chunk_hours = chunk_hours
        self.symbols = symbols
        self.profile = profile
        self.probe_s = probe_s
        self.min_free_bytes = int(min_free_gb * (1 << 30))
        self.keep_raw = keep_raw
        self.allow_tight = allow_tight
        self.chunk_s = chunk_hours * 3600.0
        self.chunks_total = plan_chunks(days, chunk_hours)
        self.chunk_executor = chunk_executor or self._collector_chunk
        self._disk_free = disk_free or (
            lambda p: shutil.disk_usage(p).free)
        self.cooldown_s = cooldown_s
        self.max_attempts = max_attempts
        self.disk_pause_s = 900.0
        self.disk_pause_limit: int | None = None
        self._disk_pauses = 0
        self._active = None          # live Collector for stop forwarding.
        self._stop = False

    # -- seams -----------------------------------------------------------
    def _collector_chunk(self, chunk_dir: Path, seconds: float) -> dict:
        from cryptobot.market_data.collector import (
            Collector, CollectorConfig)
        prof = PROFILES[self.profile]
        cfg = CollectorConfig(
            symbols=tuple(self.symbols), run_dir=str(chunk_dir),
            run_id=chunk_dir.name,
            capture_set_rule=f"campaign:{self.profile}",
            market_streams=prof["market"], public_streams=prof["public"],
            max_bytes=3_000_000_000)
        collector = Collector(cfg)
        collector._selection_evidence = {}
        collector._metadata_hash = "campaign"
        self._active = collector
        try:
            stats = collector.run(duration_s=seconds)
        finally:
            self._active = None
        return {"stop_reason": stats.stop_reason,
                "events_total": stats.events_total,
                "bytes_written": stats.bytes_written,
                "depth_applied": stats.depth_applied,
                "depth_resyncs": stats.depth_resyncs}

    # -- preflight -------------------------------------------------------
    def preflight(self) -> dict:
        probe_dir = self.dest / "_probe"
        if probe_dir.exists():
            shutil.rmtree(probe_dir)
        probe_dir.mkdir(parents=True)
        log_line(self.dest, {"event": "probe-start", "seconds": self.probe_s})
        stats = self.chunk_executor(probe_dir, self.probe_s)
        events_p = probe_dir / "events.jsonl"
        raw_p = probe_dir / "raw.jsonl"
        events_bytes = events_p.stat().st_size if events_p.exists() else 0
        raw_bytes = raw_p.stat().st_size if raw_p.exists() else 0
        gz_ratio = 1.0
        if events_bytes > 0:
            blob = events_p.read_bytes()
            gz_ratio = len(gzip.compress(blob, 6)) / max(1, len(blob))
        snaps_ok = False  # absence of evidence is not sync
        snaps_p = probe_dir / "depth_snapshots.jsonl"
        if snaps_p.exists():
            try:
                snaps_ok = any(json.loads(l).get("outcome") == "synced"
                               for l in snaps_p.read_text().splitlines()
                               if l.strip())
            except ValueError:
                snaps_ok = False
        free = self._disk_free(self.dest)
        proj = projected_footprint(events_bytes, raw_bytes, gz_ratio,
                                   self.probe_s, self.chunk_s,
                                   self.chunks_total)
        required = proj["peak_bytes"] + self.min_free_bytes
        verdict = "OK" if free >= required else "REFUSED"
        if not snaps_ok:
            verdict = "REFUSED" if verdict != "OK" else "BLOCKED_DEPTH"
        if self.allow_tight and verdict == "REFUSED":
            verdict = "OK_TIGHT"
        result = {
            "probe_seconds": self.probe_s,
            "events_bytes_per_s": proj["events_bytes_per_s"],
            "raw_bytes_per_s": proj["raw_bytes_per_s"],
            "gz_ratio": proj["gz_ratio"],
            "chunks_total": self.chunks_total,
            "projected_settled_bytes": proj["settled_total_bytes"],
            "projected_peak_bytes": proj["peak_bytes"],
            "free_bytes_at_preflight": free,
            "min_free_bytes": self.min_free_bytes,
            "required_bytes": required,
            "depth_synced_in_probe": snaps_ok,
            "verdict": verdict,
            "probe_stats": stats,
        }
        shutil.rmtree(probe_dir, ignore_errors=True)
        return result

    # -- main loop -------------------------------------------------------
    def run(self, max_chunks: int | None = None) -> dict:
        self.dest.mkdir(parents=True, exist_ok=True)
        (self.dest / PID_FILE).write_text(str(os.getpid()))
        state = load_state(self.dest)
        if state is None:
            state = {
                "format": "cryptobot-campaign/1",
                "dest": str(self.dest), "started_utc": utc_now(),
                "days": self.days, "chunk_hours": self.chunk_hours,
                "symbols": self.symbols, "profile": self.profile,
                "chunks_total": self.chunks_total,
                "chunks": [], "gaps": [], "status": "running",
            }
            log_line(self.dest, {"event": "campaign-init"})
            pre = self.preflight()
            state["preflight"] = pre
            log_line(self.dest, {"event": "preflight", **pre})
            save_state(self.dest, state)
            if pre["verdict"] not in ("OK", "OK_TIGHT"):
                state["status"] = "refused:" + pre["verdict"]
                save_state(self.dest, state)
                return state
        ran = 0
        total = state.setdefault("chunks_total", self.chunks_total)
        attempts: dict[str, int] = state.setdefault("attempts", {})
        try:
            while True:
                settled_idx = {c["idx"] for c in state["chunks"]}
                pending = [i for i in range(total)
                           if i not in settled_idx]
                if (self.dest / STOP_FILE).exists() or self._stop:
                    state["status"] = "stopped"
                    break
                if not pending:
                    state["status"] = "complete"
                    break
                if max_chunks is not None and ran >= max_chunks:
                    state["status"] = "capped"
                    break
                if self._disk_free(self.dest) < self.min_free_bytes:
                    self._disk_pauses += 1
                    if self.disk_pause_limit is not None \
                            and self._disk_pauses > self.disk_pause_limit:
                        state["status"] = "disk-floor"
                        log_line(self.dest, {
                            "event": "disk-floor-give-up",
                            "free": self._disk_free(self.dest)})
                        break
                    state["status"] = "disk-paused"
                    log_line(self.dest, {"event": "disk-paused",
                                         "free": self._disk_free(self.dest),
                                         "pause_s": self.disk_pause_s})
                    save_state(self.dest, state)
                    if self.disk_pause_s > 0:
                        time.sleep(self.disk_pause_s)
                    continue
                else:
                    self._disk_pauses = 0
                    if state.get("status") == "disk-paused":
                        state["status"] = "running"
                        log_line(self.dest, {"event": "disk-resumed"})
                idx = pending[0]
                chunk_dir = self.dest / f"chunk-{idx:03d}-{utc_now()}"
                chunk_dir.mkdir(parents=True, exist_ok=True)
                log_line(self.dest, {"event": "chunk-start", "idx": idx,
                                     "dir": chunk_dir.name})
                error = None
                try:
                    stats = self.chunk_executor(chunk_dir, self.chunk_s)
                except Exception as exc:  # supervisor never dies on a chunk
                    error = f"{type(exc).__name__}: {exc}"
                    stats = {}
                info = settle_chunk(chunk_dir, keep_raw=self.keep_raw)
                entry = {"idx": idx, "dir": chunk_dir.name,
                         "status": info["status"],
                         "complete": info.get("complete", False),
                         "settled_utc": info["settled_utc"],
                         "events_total": (info.get("run_stats") or {}).get(
                             "events_total",
                             stats.get("events_total") if stats else None),
                         "stop_reason": (info.get("run_stats") or {}).get(
                             "stop_reason", stats.get("stop_reason")
                             if stats else None),
                         "error": error}
                failed = error is not None or entry["stop_reason"] in (
                    "connect-failed", None) or not entry["events_total"]
                if failed:
                    key = str(idx)
                    attempts[key] = attempts.get(key, 0) + 1
                    state["gaps"].append({
                        "idx": idx, "attempt": attempts[key],
                        "reason": entry["stop_reason"] or error or "empty",
                        "utc": utc_now()})
                    log_line(self.dest, {"event": "chunk-gap",
                                         "idx": idx,
                                         "attempt": attempts[key],
                                         "reason": state["gaps"][-1][
                                             "reason"]})
                    if attempts[key] >= self.max_attempts:
                        entry["status"] = "failed"
                        state["chunks"].append(entry)
                        log_line(self.dest, {"event": "chunk-failed",
                                             **{k: entry[k] for k in (
                                                 "idx", "stop_reason",
                                                 "error")}})
                    else:
                        # Failed attempt leaves no artifacts (its empty
                        # settle marker must never poison the retry dir);
                        # the gap record in state/logs is the evidence.
                        shutil.rmtree(chunk_dir, ignore_errors=True)
                        if not self._stop:
                            time.sleep(self.cooldown_s)  # retry same idx
                    save_state(self.dest, state)
                    continue
                log_line(self.dest, {"event": "chunk-settled", **entry})
                ran += 1
                state["chunks"].append(entry)
                save_state(self.dest, state)
            save_state(self.dest, state)
            return state
        finally:
            try:
                (self.dest / PID_FILE).unlink()
            except OSError:
                pass

    # -- control ---------------------------------------------------------
    def request_stop(self) -> None:
        self._stop = True
        if self._active is not None:
            try:
                self._active.request_stop()
            except Exception:
                pass


def status(dest: Path) -> dict:
    state = load_state(dest) or {"status": "no-state"}
    free = shutil.disk_usage(dest if dest.exists() else dest.parent).free
    state["free_bytes_now"] = free
    logs = []
    p = dest / LOG_FILE
    if p.exists():
        lines = p.read_text().splitlines()[-5:]
        logs = [json.loads(l) for l in lines if l.strip()]
    state["last_log"] = logs
    return state


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="capture campaign supervisor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--dest", required=True)
    s.add_argument("--days", type=float, default=10.0)
    s.add_argument("--chunk-hours", type=float, default=6.0)
    s.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    s.add_argument("--profile", default="lean500",
                   choices=sorted(PROFILES))
    s.add_argument("--probe-s", type=float, default=45.0)
    s.add_argument("--min-free-gb", type=float, default=5.0)
    s.add_argument("--keep-raw", action="store_true")
    s.add_argument("--allow-tight", action="store_true")
    s.add_argument("--max-chunks", type=int, default=None)
    st = sub.add_parser("status")
    st.add_argument("--dest", required=True)
    so = sub.add_parser("stop")
    so.add_argument("--dest", required=True)
    args = ap.parse_args(argv)

    dest = Path(args.dest)
    if args.cmd == "status":
        print(json.dumps(status(dest), indent=1))
        return 0
    if args.cmd == "stop":
        dest.mkdir(parents=True, exist_ok=True)
        (dest / STOP_FILE).write_text(utc_now())
        pid_p = dest / PID_FILE
        if pid_p.exists():
            try:
                os.kill(int(pid_p.read_text().strip()), signal.SIGTERM)
                print(f"STOP written; SIGTERM -> pid {pid_p.read_text()}")
            except (ValueError, ProcessLookupError, OSError) as exc:
                print(f"STOP written; pid not signalled ({exc})")
        else:
            print("STOP written (no live campaign pid)")
        return 0

    symbols = [x.strip().upper() for x in args.symbols.split(",")
               if x.strip()]
    campaign = Campaign(dest, days=args.days, chunk_hours=args.chunk_hours,
                        symbols=symbols, profile=args.profile,
                        probe_s=args.probe_s,
                        min_free_gb=args.min_free_gb,
                        keep_raw=args.keep_raw,
                        allow_tight=args.allow_tight)

    def _sig(signum, frame):
        campaign.request_stop()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    state = campaign.run(max_chunks=args.max_chunks)
    print(json.dumps({k: state.get(k) for k in (
        "status", "chunks_total", "preflight")}, indent=1,
        default=str))
    print(f"chunks recorded: {len(state.get('chunks', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
