#!/usr/bin/env python3
"""Binance Vision (data.binance.vision) S3 inventory tool — stdlib only.

Lists USD-M futures datasets via the public S3 listing API. No bulk
downloads: only delimiter/prefix listings plus a few tiny probe downloads
(<5 MB total) to document file formats.

Usage:
    python tools/vision_inventory.py --out /tmp/vision-inventory.json

Output: JSON with dataset names, symbol lists, per-symbol start/end dates,
interval coverage, metrics enumeration, spot-leg check, probe column
formats, and size estimates.
"""
import argparse
import datetime
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

S3_BASE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
HTTP_BASE = "https://data.binance.vision"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
DATE_RE = re.compile(r"(\d{4}-\d{2}(?:-\d{2})?)")
REQUEST_DELAY = 0.25
TIMEOUT = 30
MAX_RETRIES = 4
PROBE_BUDGET_BYTES = 5 * 1024 * 1024

_last_req_ts = [0.0]
_probe_bytes = [0]


def log(msg):
    print(f"[vision_inventory] {msg}", file=sys.stderr, flush=True)


def polite_wait(delay):
    dt = time.time() - _last_req_ts[0]
    if dt < delay:
        time.sleep(delay - dt)


def http_get(url, timeout=TIMEOUT, delay=REQUEST_DELAY, extra_headers=None):
    """GET with rate limiting + retry/backoff. Returns (bytes, headers)."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        polite_wait(delay)
        _last_req_ts[0] = time.time()
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "cryto-bot-edge-vision-inventory/1.0",
                              **(extra_headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), dict(resp.headers)
        except Exception as e:  # noqa: BLE001 - retry any transient failure
            last_err = e
            backoff = min(2 ** attempt, 8)
            log(f"GET failed (attempt {attempt+1}/{MAX_RETRIES}): {e}; "
                f"sleep {backoff}s: {url[:120]}")
            time.sleep(backoff)
    raise RuntimeError(f"GET failed after {MAX_RETRIES} tries: {url}: {last_err}")


def s3_list_page(prefix, delimiter=None, max_keys=1000,
                 continuation=None, start_after=None):
    params = {"list-type": "2", "prefix": prefix, "max-keys": str(max_keys)}
    if delimiter is not None:
        params["delimiter"] = delimiter
    if continuation:
        params["continuation-token"] = continuation
    if start_after:
        params["start-after"] = start_after
    url = S3_BASE + "?" + urllib.parse.urlencode(params)
    body, _ = http_get(url)
    root = ET.fromstring(body)
    prefixes = [e.find(NS + "Prefix").text
                for e in root.findall(NS + "CommonPrefixes")]
    contents = []
    for e in root.findall(NS + "Contents"):
        key = e.find(NS + "Key").text
        size = int(e.find(NS + "Size").text)
        lm = e.find(NS + "LastModified").text
        contents.append({"key": key, "size": size, "last_modified": lm})
    truncated = (root.find(NS + "IsTruncated") is not None
                 and root.find(NS + "IsTruncated").text == "true")
    token_el = root.find(NS + "NextContinuationToken")
    token = token_el.text if token_el is not None else None
    return prefixes, contents, truncated, token


def s3_list_all(prefix, delimiter=None, max_keys=1000, start_after=None,
                max_pages=20000):
    """Paginated listing. Returns (common_prefixes, contents)."""
    all_prefixes, all_contents = [], []
    token = None
    pages = 0
    while True:
        prefixes, contents, truncated, token = s3_list_page(
            prefix, delimiter, max_keys, token, start_after if pages == 0 else None)
        all_prefixes.extend(prefixes)
        all_contents.extend(contents)
        pages += 1
        if not truncated or pages >= max_pages:
            break
    if pages >= max_pages:
        log(f"WARNING: hit max_pages for prefix {prefix}")
    return all_prefixes, all_contents


def s3_list_single(prefix, delimiter=None, max_keys=1000, start_after=None):
    """Single page (no pagination-follow). Returns (prefixes, contents, truncated, token)."""
    return s3_list_page(prefix, delimiter, max_keys, None, start_after)


def basename(p):
    return p.rstrip("/").rsplit("/", 1)[-1]


def parse_date_from_key(key):
    m = DATE_RE.search(basename(key))
    return m.group(1) if m else None


def is_checksum(key):
    return key.endswith(".CHECKSUM")


def is_zip(key):
    return key.endswith(".zip") and not key.endswith(".CHECKSUM")


def summarize_files(contents):
    """Summarize .zip files: count, bytes, min/max date, first/last key."""
    zips = [c for c in contents if is_zip(c["key"])]
    n_ck = sum(1 for c in contents if is_checksum(c["key"]))
    if not zips:
        return {"zip_files": 0, "zip_bytes": 0, "checksum_files": n_ck,
                "start": None, "end": None, "first_key": None, "last_key": None}
    dated = [(parse_date_from_key(c["key"]), c) for c in zips]
    dated_valid = [(d, c) for d, c in dated if d]
    zips_sorted = sorted(zips, key=lambda c: c["key"])
    total = sum(c["size"] for c in zips)
    if dated_valid:
        dated_valid.sort(key=lambda t: t[0])
        start, end = dated_valid[0][0], dated_valid[-1][0]
    else:
        start = end = None
    return {"zip_files": len(zips), "zip_bytes": total, "checksum_files": n_ck,
            "start": start, "end": end,
            "first_key": zips_sorted[0]["key"], "last_key": zips_sorted[-1]["key"]}


def main():
    ap = argparse.ArgumentParser(description="Binance Vision S3 inventory (UM futures)")
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--delay", type=float, default=0.25, help="min seconds between requests")
    ap.add_argument("--sample", type=int, default=10, help="sample symbols per non-klines dataset")
    ap.add_argument("--skip-probes", action="store_true", help="skip tiny probe downloads")
    args = ap.parse_args()
    global REQUEST_DELAY
    REQUEST_DELAY = args.delay

    out = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "s3_base": S3_BASE, "http_base": HTTP_BASE,
           "notes": []}
    t0 = time.time()

    # ---- 1. monthly/daily dataset names ----
    log("listing UM monthly/daily dataset names")
    monthly_pf, _ = s3_list_all("data/futures/um/monthly/", delimiter="/")
    daily_pf, _ = s3_list_all("data/futures/um/daily/", delimiter="/")
    monthly_ds = sorted(basename(p) for p in monthly_pf)
    daily_ds = sorted(basename(p) for p in daily_pf)
    out["um_monthly_datasets"] = monthly_ds
    out["um_daily_datasets"] = daily_ds
    log(f"monthly datasets ({len(monthly_ds)}): {monthly_ds}")
    log(f"daily datasets ({len(daily_ds)}): {daily_ds}")

    # ---- 2. per-dataset L1 listing + structure detection ----
    dataset_info = {}
    kline_like = set()
    for ds in monthly_ds:
        pf, _ = s3_list_all(f"data/futures/um/monthly/{ds}/", delimiter="/")
        l1 = sorted(basename(p) for p in pf)
        info = {"l1_count": len(l1), "l1_sample": l1[:15], "l1_all": l1}
        # probe first L1 to detect structure
        if l1:
            first = l1[0]
            sub_pf, sub_contents = s3_list_all(
                f"data/futures/um/monthly/{ds}/{first}/", delimiter="/")
            sub = sorted(basename(p) for p in sub_pf)
            info["l2_sample_for_" + first] = sub[:20]
            files = summarize_files(sub_contents)
            info["l2_files_for_" + first] = files
            interval_like = [s for s in sub if re.fullmatch(r"\d+[mhdwM]", s)]
            if interval_like and len(interval_like) >= 2:
                info["structure"] = "symbols/interval/files (kline-like)"
                kline_like.add(ds)
            elif sub and not files["zip_files"]:
                # L2 are subfolders, not files -> L1 may be metric names
                info["structure"] = "group/symbols/... (metrics-like?)"
            elif files["zip_files"]:
                info["structure"] = "symbols/files"
            else:
                info["structure"] = "unknown/empty"
        dataset_info[ds] = info
        log(f"{ds}: L1={len(l1)} structure={info.get('structure')}")
    out["dataset_info"] = {k: {kk: vv for kk, vv in v.items() if kk != "l1_all"}
                           for k, v in dataset_info.items()}
    out["kline_like_datasets"] = sorted(kline_like)
    # keep full symbol lists for key datasets in output (may be large but fine)
    out["symbol_lists"] = {ds: dataset_info[ds]["l1_all"] for ds in monthly_ds
                           if dataset_info[ds].get("structure") in (
                               "symbols/interval/files (kline-like)", "symbols/files")}

    # ---- 3. klines monthly per-symbol (all intervals in one listing per symbol) ----
    klines_symbols = dataset_info.get("klines", {}).get("l1_all", [])
    out["klines_monthly_symbol_count"] = len(klines_symbols)
    per_symbol = {}  # sym -> {interval -> summary}
    interval_counts = {}
    interval_bytes = {}
    log(f"listing monthly klines per symbol for {len(klines_symbols)} symbols")
    for i, sym in enumerate(klines_symbols):
        pf, contents = s3_list_all(f"data/futures/um/monthly/klines/{sym}/")
        # group zips by interval (path segment after symbol)
        by_iv = {}
        for c in contents:
            if not is_zip(c["key"]):
                continue
            parts = c["key"].split("/")
            # .../klines/<SYM>/<interval>/<file>
            try:
                ki = parts.index("klines")
                iv = parts[ki + 2]
            except (ValueError, IndexError):
                iv = "?"
            by_iv.setdefault(iv, []).append(c)
        sym_entry = {}
        for iv, files in by_iv.items():
            s = summarize_files(files)
            sym_entry[iv] = s
            interval_counts[iv] = interval_counts.get(iv, 0) + 1
            interval_bytes[iv] = interval_bytes.get(iv, 0) + s["zip_bytes"]
        per_symbol[sym] = sym_entry
        if (i + 1) % 100 == 0:
            log(f"  klines monthly {i+1}/{len(klines_symbols)}")
    out["klines_intervals"] = {iv: {"symbols": n, "monthly_zip_bytes": interval_bytes.get(iv, 0)}
                               for iv, n in sorted(interval_counts.items())}

    def start_end_table(interval):
        rows = []
        for sym, entry in per_symbol.items():
            if interval in entry:
                s = entry[interval]
                rows.append({"symbol": sym, "start": s["start"], "end": s["end"],
                             "files": s["zip_files"], "bytes": s["zip_bytes"]})
        rows.sort(key=lambda r: (r["start"] or "", r["symbol"]))
        return rows

    for iv in ("1d", "1h", "1m"):
        rows = start_end_table(iv)
        out[f"klines_{iv}_per_symbol"] = rows
        if rows:
            starts = [r for r in rows if r["start"]]
            ends = sorted(rows, key=lambda r: (r["end"] or ""))
            out[f"klines_{iv}_oldest10_start"] = starts[:10]
            out[f"klines_{iv}_newest10_start"] = starts[-10:][::-1]
            out[f"klines_{iv}_stalest10_end"] = ends[:10]
            out[f"klines_{iv}_total_bytes"] = sum(r["bytes"] for r in rows)
            out[f"klines_{iv}_total_files"] = sum(r["files"] for r in rows)

    # ---- 4. daily extension check ----
    # Full daily listing for BTC+ETH 1d/1h/1m; StartAfter probe for all other 1d symbols.
    daily_info = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        for iv in ("1d", "1h", "1m"):
            pf, contents = s3_list_all(f"data/futures/um/daily/klines/{sym}/{iv}/")
            daily_info[f"{sym}_{iv}"] = summarize_files(contents)
            log(f"daily klines {sym} {iv}: {daily_info[f'{sym}_{iv}']['zip_files']} files")
    out["daily_btc_eth"] = daily_info
    # extension probes for 1d all symbols
    ext = {}
    monthly_1d = {r["symbol"]: r for r in out.get("klines_1d_per_symbol", [])}
    log(f"daily-extension probes for {len(monthly_1d)} 1d symbols")
    for sym, mrow in monthly_1d.items():
        if sym in ("BTCUSDT", "ETHUSDT"):
            btc = daily_info.get(f"{sym}_1d", {})
            ext[sym] = {"monthly_end": mrow["end"],
                        "daily_end": btc.get("end"),
                        "extends": (btc.get("end") or "") > (mrow["end"] or "z"),
                        "daily_files": btc.get("zip_files"),
                        "daily_bytes": btc.get("zip_bytes")}
            continue
        mend = mrow["end"] or "2000-01"
        # any daily file after monthly end month? StartAfter at month boundary
        start_after = (f"data/futures/um/daily/klines/{sym}/1d/"
                       f"{sym}-1d-{mend}-99")
        _, contents, truncated, _ = s3_list_single(
            f"data/futures/um/daily/klines/{sym}/1d/", max_keys=3,
            start_after=start_after)
        zips = [c for c in contents if is_zip(c["key"])]
        if zips:
            first_new = sorted(zips, key=lambda c: c["key"])[0]
            ext[sym] = {"monthly_end": mrow["end"], "extends": True,
                        "first_beyond": parse_date_from_key(first_new["key"]),
                        "first_beyond_key": first_new["key"]}
        else:
            # check whether any daily files exist at all
            _, c2, _, _ = s3_list_single(
                f"data/futures/um/daily/klines/{sym}/1d/", max_keys=2)
            z2 = [c for c in c2 if is_zip(c["key"])]
            ext[sym] = {"monthly_end": mrow["end"], "extends": False,
                        "has_daily": len(z2) > 0}
    out["daily_extension_1d"] = ext
    n_ext = sum(1 for v in ext.values() if v.get("extends"))
    out["daily_extension_summary"] = {"symbols": len(ext), "extending_beyond_monthly": n_ext}

    # ---- 5. other UM datasets: symbol counts + sampled sizes ----
    sampled = {}
    for ds in monthly_ds:
        if ds in ("klines",):
            continue
        info = dataset_info.get(ds, {})
        struct = info.get("structure", "")
        l1 = info.get("l1_all", [])
        entry = {"structure": struct, "l1_count": len(l1)}
        if struct == "symbols/interval/files (kline-like)":
            entry["symbol_count"] = len(l1)
            # sample symbols incl BTC
            cands = [s for s in ("BTCUSDT", "ETHUSDT") if s in l1]
            rest = [s for s in l1 if s not in cands]
            step = max(1, len(rest) // max(1, (args.sample - len(cands))))
            sample_syms = cands + rest[::step][:args.sample - len(cands)]
            tot_b, tot_f = 0, 0
            btc_entry = None
            for s in sample_syms:
                _, contents = s3_list_all(f"data/futures/um/monthly/{ds}/{s}/")
                sm = summarize_files(contents)
                tot_b += sm["zip_bytes"]
                tot_f += sm["zip_files"]
                if s == "BTCUSDT":
                    btc_entry = sm
            entry["sample_symbols"] = sample_syms
            entry["sample_bytes"] = tot_b
            entry["sample_files"] = tot_f
            if sample_syms:
                avg = tot_b / len(sample_syms)
                entry["est_total_monthly_bytes"] = int(avg * len(l1))
                entry["est_method"] = (f"mean(sample_bytes, n={len(sample_syms)}) * {len(l1)} symbols")
            entry["btc_monthly"] = btc_entry
        elif struct == "symbols/files":
            entry["symbol_count"] = len(l1)
            cands = [s for s in ("BTCUSDT", "ETHUSDT") if s in l1]
            rest = [s for s in l1 if s not in cands]
            step = max(1, len(rest) // max(1, (args.sample - len(cands))))
            sample_syms = cands + rest[::step][:args.sample - len(cands)]
            tot_b, tot_f = 0, 0
            btc_entry = None
            per = {}
            for s in sample_syms:
                _, contents = s3_list_all(f"data/futures/um/monthly/{ds}/{s}/")
                sm = summarize_files(contents)
                per[s] = sm
                tot_b += sm["zip_bytes"]
                tot_f += sm["zip_files"]
                if s == "BTCUSDT":
                    btc_entry = sm
            entry["sample_symbols"] = sample_syms
            entry["sample_detail"] = per
            entry["sample_bytes"] = tot_b
            entry["sample_files"] = tot_f
            if sample_syms:
                avg = tot_b / len(sample_syms)
                entry["est_total_monthly_bytes"] = int(avg * len(l1))
                entry["est_method"] = (f"mean(sample_bytes, n={len(sample_syms)}) * {len(l1)} symbols")
            entry["btc_monthly"] = btc_entry
        else:
            # metrics-like or unknown: enumerate L2 per L1 group
            groups = {}
            for g in l1:
                pf2, c2 = s3_list_all(f"data/futures/um/monthly/{ds}/{g}/", delimiter="/")
                l2 = sorted(basename(p) for p in pf2)
                ginfo = {"l2_count": len(l2), "l2_sample": l2[:10]}
                if l2:
                    # probe first L2 member for files
                    _, c3 = s3_list_all(f"data/futures/um/monthly/{ds}/{g}/{l2[0]}/",
                                        delimiter="/")
                    # c3 with delimiter gives files directly under; also list files
                    _, fall = s3_list_all(f"data/futures/um/monthly/{ds}/{g}/{l2[0]}/")
                    ginfo["first_member_files"] = summarize_files(fall)
                    # check for interval sublevel
                    pf3, _ = s3_list_all(
                        f"data/futures/um/monthly/{ds}/{g}/{l2[0]}/", delimiter="/")
                    ginfo["l3_sample"] = sorted(basename(p) for p in pf3)[:15]
                # count symbols if L2 are symbols: sample BTC file summary
                if "BTCUSDT" in l2 or l2:
                    probe_sym = "BTCUSDT" if "BTCUSDT" in l2 else l2[0]
                    # if L3 exists (periods?), list them
                    pf4, _ = s3_list_all(
                        f"data/futures/um/monthly/{ds}/{g}/{probe_sym}/", delimiter="/")
                    l3 = sorted(basename(p) for p in pf4)
                    ginfo["periods_or_intervals"] = l3[:20]
                    _, fall2 = s3_list_all(
                        f"data/futures/um/monthly/{ds}/{g}/{probe_sym}/")
                    ginfo["probe_symbol_files"] = summarize_files(fall2)
                    ginfo["probe_symbol"] = probe_sym
                groups[g] = ginfo
                log(f"  {ds}/{g}: L2={len(l2)}")
            entry["groups"] = groups
        sampled[ds] = entry
        log(f"sampled {ds}: {json.dumps({k: v for k, v in entry.items() if k in ('symbol_count','l1_count','est_total_monthly_bytes','structure')})}")
    out["other_datasets"] = sampled

    # daily symbol counts for non-klines datasets (cheap delimiter listings)
    daily_counts = {}
    for ds in daily_ds:
        pf, _ = s3_list_all(f"data/futures/um/daily/{ds}/", delimiter="/")
        daily_counts[ds] = len(pf)
    out["daily_symbol_counts"] = daily_counts

    # ---- 5b. daily-only datasets (metrics, bookDepth): structure + sampled sizes ----
    # metrics and bookDepth exist ONLY under daily/ (no monthly leg). Layout is
    # daily/<ds>/<SYM>/<SYM>-<ds>-YYYY-MM-DD.zip (files directly under symbol).
    daily_only = {}
    for ds in sorted(set(daily_ds) - set(monthly_ds)):
        pf, _ = s3_list_all(f"data/futures/um/daily/{ds}/", delimiter="/")
        syms = sorted(basename(p) for p in pf)
        entry = {"symbol_count": len(syms), "cadence": "daily-only"}
        # probe BTCUSDT layout: sublevels?
        sub_pf, _ = s3_list_all(f"data/futures/um/daily/{ds}/BTCUSDT/", delimiter="/")
        entry["btc_sublevels"] = sorted(basename(p) for p in sub_pf)
        _, btc_all = s3_list_all(f"data/futures/um/daily/{ds}/BTCUSDT/")
        entry["btc_daily"] = summarize_files(btc_all)
        # sample a few symbols for size estimate
        sample_syms = [s for s in ("BTCUSDT", "ETHUSDT", "DOGEUSDT") if s in syms]
        tot_b = 0
        for s in sample_syms:
            if s == "BTCUSDT":
                tot_b += entry["btc_daily"]["zip_bytes"]
            else:
                _, fc = s3_list_all(f"data/futures/um/daily/{ds}/{s}/")
                tot_b += summarize_files(fc)["zip_bytes"]
        entry["sample_symbols"] = sample_syms
        if sample_syms:
            entry["est_total_daily_bytes"] = int(tot_b / len(sample_syms) * len(syms))
            entry["est_method"] = (f"mean(sample_bytes, n={len(sample_syms)}) * {len(syms)} symbols")
        daily_only[ds] = entry
        log(f"daily-only {ds}: symbols={len(syms)} btc={entry['btc_daily']['zip_files']} files")
    out["daily_only_datasets"] = daily_only

    # ---- 6. spot-leg check (BTC/ETH 1d monthly only) ----
    spot = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        _, contents = s3_list_all(f"data/spot/monthly/klines/{sym}/1d/")
        spot[sym] = summarize_files(contents)
    # also list spot monthly datasets + spot klines intervals for BTC
    try:
        spf, _ = s3_list_all("data/spot/monthly/", delimiter="/")
        spot["spot_monthly_datasets"] = sorted(basename(p) for p in spf)
    except Exception as e:  # noqa: BLE001
        spot["spot_monthly_datasets"] = [f"ERROR: {e}"]
    try:
        ipf, _ = s3_list_all("data/spot/monthly/klines/BTCUSDT/", delimiter="/")
        spot["btc_intervals"] = sorted(basename(p) for p in ipf)
    except Exception as e:  # noqa: BLE001
        spot["btc_intervals"] = [f"ERROR: {e}"]
    out["spot_check"] = spot
    log(f"spot check: {json.dumps({k: v for k, v in spot.items() if k in ('BTCUSDT','ETHUSDT')}, default=str)[:300]}")

    # ---- 7. tiny probes (<5MB): checksum + funding + metrics columns ----
    probes = {"budget_bytes": PROBE_BUDGET_BYTES, "used_bytes": 0, "files": []}

    def probe_download(url, max_bytes=1_000_000):
        if probes["used_bytes"] >= PROBE_BUDGET_BYTES:
            raise RuntimeError("probe budget exhausted")
        body, _ = http_get(url)
        probes["used_bytes"] += len(body)
        if probes["used_bytes"] > PROBE_BUDGET_BYTES:
            raise RuntimeError("probe budget exceeded")
        return body

    if not args.skip_probes:
        # 7a. one CHECKSUM sibling for a klines file
        try:
            first_1d = None
            for r in out.get("klines_1d_per_symbol", []):
                if r["symbol"] == "BTCUSDT":
                    first_1d = r
                    break
            # find an actual key: list BTC 1d monthly (already know pattern; list to be exact)
            _, btc1d = s3_list_all("data/futures/um/monthly/klines/BTCUSDT/1d/")
            zkeys = sorted(c["key"] for c in btc1d if is_zip(c["key"]))
            if zkeys:
                ck_url = f"{HTTP_BASE}/{zkeys[0]}.CHECKSUM"
                ck_body = probe_download(ck_url)
                probes["files"].append({"url": ck_url, "bytes": len(ck_body),
                                        "text": ck_body.decode("utf-8", "replace")[:300]})
        except Exception as e:  # noqa: BLE001
            probes["files"].append({"url": "klines-checksum", "error": str(e)})

        # 7b. one fundingRate zip (pick smallest BTC monthly file)
        try:
            _, fcontents = s3_list_all("data/futures/um/monthly/fundingRate/BTCUSDT/")
            fz = sorted([c for c in fcontents if is_zip(c["key"])],
                        key=lambda c: c["size"])
            if fz:
                fkey = fz[0]["key"]
                fbody = probe_download(f"{HTTP_BASE}/{fkey}")
                with zipfile.ZipFile(io.BytesIO(fbody)) as zf:
                    names = zf.namelist()
                    txt = zf.read(names[0]).decode("utf-8", "replace")
                lines = txt.splitlines()
                probes["files"].append({"url": f"{HTTP_BASE}/{fkey}",
                                        "zip_bytes": len(fbody),
                                        "inner_file": names[0],
                                        "columns": lines[0] if lines else None,
                                        "sample_rows": lines[1:3]})
        except Exception as e:  # noqa: BLE001
            probes["files"].append({"url": "funding-probe", "error": str(e)})

        # 7c. one metrics zip (metrics is DAILY-only: daily/metrics/<SYM>/)
        try:
            _, mcontents = s3_list_all("data/futures/um/daily/metrics/BTCUSDT/")
            mz = sorted([c for c in mcontents if is_zip(c["key"])],
                        key=lambda c: c["size"])
            if mz:
                mkey = mz[0]["key"]
                mbody = probe_download(f"{HTTP_BASE}/{mkey}")
                with zipfile.ZipFile(io.BytesIO(mbody)) as zf:
                    names = zf.namelist()
                    txt = zf.read(names[0]).decode("utf-8", "replace")
                lines = txt.splitlines()
                probes["files"].append(
                    {"url": f"{HTTP_BASE}/{mkey}", "metric": "metrics",
                     "zip_bytes": len(mbody), "inner_file": names[0],
                     "columns": lines[0] if lines else None,
                     "sample_rows": lines[1:4]})
            else:
                probes["files"].append({"url": "metrics-probe", "error": "no zips found"})
        except Exception as e:  # noqa: BLE001
            probes["files"].append({"url": "metrics-probe", "error": str(e)})
        # 7d. first KB (Range) of one klines zip to show it's binary zip (tiny)
        try:
            _, btc1h = s3_list_all("data/futures/um/monthly/klines/BTCUSDT/1h/")
            zh = sorted(c["key"] for c in btc1h if is_zip(c["key"]))
            if zh:
                req = urllib.request.Request(
                    f"{HTTP_BASE}/{zh[0]}",
                    headers={"User-Agent": "cryto-bot-edge-vision-inventory/1.0",
                             "Range": "bytes=0-1023"})
                polite_wait(REQUEST_DELAY)
                _last_req_ts[0] = time.time()
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    head = resp.read()
                probes["used_bytes"] += len(head)
                probes["files"].append({"url": f"{HTTP_BASE}/{zh[0]} (Range 0-1023)",
                                        "bytes": len(head),
                                        "magic": head[:4].hex(),
                                        "is_zip_magic": head[:2] == b"PK"})
        except Exception as e:  # noqa: BLE001
            probes["files"].append({"url": "klines-range-probe", "error": str(e)})
    out["probes"] = probes
    log(f"probe bytes used: {probes['used_bytes']} / {PROBE_BUDGET_BYTES}")

    # ---- 8. size estimates ----
    est = {}
    for iv in ("1d", "1h", "1m"):
        est[f"klines_{iv}_monthly_exact_bytes"] = out.get(f"klines_{iv}_total_bytes", 0)
        est[f"klines_{iv}_monthly_exact_files"] = out.get(f"klines_{iv}_total_files", 0)
    # 1m top-20 by 1d monthly bytes (activity proxy)
    rows_1d = {r["symbol"]: r for r in out.get("klines_1d_per_symbol", [])}
    rows_1m = {r["symbol"]: r for r in out.get("klines_1m_per_symbol", [])}
    ranked = sorted(rows_1d.values(), key=lambda r: r["bytes"], reverse=True)
    top20 = [r["symbol"] for r in ranked[:20]]
    top20_bytes = sum(rows_1m[s]["bytes"] for s in top20 if s in rows_1m)
    top20_files = sum(rows_1m[s]["files"] for s in top20 if s in rows_1m)
    est["klines_1m_top20_symbols"] = top20
    est["klines_1m_top20_monthly_bytes"] = top20_bytes
    est["klines_1m_top20_monthly_files"] = top20_files
    est["klines_1m_top20_method"] = "top-20 by 1d monthly zip bytes (activity proxy)"
    for ds, entry in sampled.items():
        if "est_total_monthly_bytes" in entry:
            est[f"{ds}_monthly_est_bytes"] = entry["est_total_monthly_bytes"]
            est[f"{ds}_monthly_est_method"] = entry.get("est_method")
    # daily estimates from BTC/ETH samples
    for k, v in daily_info.items():
        est[f"daily_{k}_bytes"] = v.get("zip_bytes")
        est[f"daily_{k}_files"] = v.get("zip_files")
    out["size_estimates"] = est

    out["elapsed_seconds"] = round(time.time() - t0, 1)
    out["command"] = ("cd /Users/sahajpatel/Code/cryto-bot-edge && "
                      "/Users/sahajpatel/Code/cryto-bot/.venv/bin/python "
                      "tools/vision_inventory.py --out /tmp/vision-inventory.json")

    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    log(f"wrote {args.out} in {out['elapsed_seconds']}s")
    # headline summary to stdout
    print(json.dumps({
        "monthly_datasets": monthly_ds,
        "daily_datasets": daily_ds,
        "klines_symbols": len(klines_symbols),
        "klines_intervals": out["klines_intervals"],
        "elapsed_s": out["elapsed_seconds"],
    }, indent=1))


if __name__ == "__main__":
    main()
