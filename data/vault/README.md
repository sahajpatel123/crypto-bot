# Sealed data vault (F3.5)

Hash-chained, token-gated store that separates pre-freeze **DEV** data
(free to read) from post-freeze **CONFIRM** data (verdict-only, one-shot
tokens). Code: `src/cryptobot/vault/`. Tests: `tests/unit/test_vault_*.py`.

## Layout

```
data/vault/
  README.md            this file
  registry.json        {"version": 1, "entries": [...]} — hash-chained chunk records
  chunks/<chunk_id>    sealed chunk bytes (chunk_id = source file name)
  tokens.json          one-shot verdict tokens
  access.log.jsonl     hash-chained log of every load attempt (granted/refused)
```

A registry record:

```json
{
  "chunk_id": "btcusdt-2026-02.parquet",
  "sha256": "<hex of sealed bytes>",
  "bytes": 12345,
  "time_range": {"start": "<iso>", "end": "<iso>"},
  "provenance": "OBSERVED",
  "sealed_utc": "<iso>",
  "prev_hash": "<entry_hash of previous record, or 64 zeros at genesis>",
  "entry_hash": "sha256(canonical_json(record minus entry_hash))"
}
```

## Seal flow

1. Autopilot writes a chunk file, then calls
   `seal_chunk(path, time_start_utc=..., time_end_utc=..., provenance=...)`.
2. The vault copies the bytes to `chunks/<chunk_id>`, hashes them, stamps
   `sealed_utc`, chains `prev_hash -> entry_hash`, and rewrites
   `registry.json` atomically (temp file + fsync + `os.replace` + dir fsync).
3. Re-sealing an existing `chunk_id` is rejected: the registry is append-only.

## Classify flow

`Registry.classify(chunk_id, hypothesis, freeze_record)` returns `DEV` or
`CONFIRM`. `freeze_record` is the autopilot-written
`research/freeze/<X>.json` mapping
`{hypothesis, config_hash, frozen_commit, frozen_utc}`.

* `CONFIRM` iff `sealed_utc > frozen_utc` (strictly after) **and**
  provenance is not `SYNTHETIC`.
* Everything else is `DEV`. Synthetic data is **never** CONFIRM, no matter
  when it was sealed. Equal timestamps are DEV.

## Token flow (verdict only)

1. The verdict path mints a token bound to one hypothesis and one exact
   chunk set: `mint_verdict_token(hypothesis, chunk_ids) -> token`
   (128-bit random, recorded in `tokens.json` with `redeemed: []`).
2. `load_chunk(root, chunk_id, hypothesis=H, token=t)` redeems the single
   `(token, chunk)` pair. Any repeat redeem, wrong hypothesis, or chunk
   outside the bound set fails and the load is refused.
3. Raw tokens are never written to the access log (only a 16-hex-char
   fingerprint).

## Load policy (`load_chunk`, fail closed)

| Call | Chunk class | Result |
|---|---|---|
| `hypothesis=None` | DEV vs **every** known freeze record | granted, logged |
| `hypothesis=None` | CONFIRM for **any** freeze record | refused |
| `hypothesis=H` (freeze record exists) | DEV for H | granted, logged |
| `hypothesis=H` (freeze record exists) | CONFIRM for H + valid unredeemed token | granted (token consumed), logged |
| `hypothesis=H` (freeze record exists) | CONFIRM for H, no/bad/used token | refused, logged |
| `hypothesis=H` (no freeze record) | any | refused (bogus names can't downgrade) |
| unknown chunk / missing bytes / sha mismatch | — | refused, logged |

## Provenance rule (verdict/gate MUST enforce)

Every synthetic chunk is stamped `provenance="SYNTHETIC"` at seal time.
`check_provenance(record)` raises `VaultSynthetic` when provenance is
`SYNTHETIC` (any case) **or missing** (fail closed). The verdict and gate
paths must call `check_provenance` on every record they consume and abort
on `VaultSynthetic`. The owner wires this call into
`src/cryptobot/research/verdict.py` and the gate; this package only
provides the helper.

## Threat model

Detected (tamper-evident):

* Editing / reordering / deleting a `registry.json` entry -> `verify_chain()`
  returns False (entry hash covers the record plus `prev_hash`).
* Editing / reordering / deleting / truncating `access.log.jsonl` ->
  `verify_access_log()` returns False (per-line chain plus monotonic `seq`).
* Modifying sealed chunk bytes after sealing -> `load_chunk` refuses
  (`chunk-hash-mismatch`; bytes are re-hashed on every load).
* Token replay / sharing across hypotheses or chunks -> redeem fails
  (single-use per `(token, chunk)`, hypothesis-bound, chunk-set-bound).
* CONFIRM access without a token, with a bogus hypothesis name, or via an
  anonymous (`hypothesis=None`) load -> refused and logged.
* Synthetic data reaching verdict/gate -> `check_provenance` raises.

NOT detected / out of scope (operator + code-review controls):

* Seal-time lies: sealing synthetic bytes stamped `OBSERVED`, or sealing
  with a falsified `time_start/end` or backdated clock. Mitigation:
  sealing is done by the audited autopilot path; `sealed_utc` comes from
  the vault clock (`now_utc` is injectable only for tests).
* Whole-file deletion of `registry.json`/`tokens.json`/`access.log.jsonl`
  followed by re-creation: the new files self-verify, but the loss of
  history is visible only via backups/offline copies. Mitigation: back up
  `data/vault/` (or ship log hashes out of band).
* Direct filesystem reads of `chunks/` bypassing `load_chunk`: the vault
  is a software gate, not encryption. Mitigation: the import-lint test
  (`tests/unit/test_vault_import_lint.py`) fails CI if any module outside
  `src/cryptobot/vault/`, `src/cryptobot/research/verdict.py`, or `tests/`
  references `load_chunk`/`CONFIRM`; filesystem permissions restrict
  `data/vault/` to the research runtime user.
* `research/freeze/*.json` integrity: the vault trusts freeze records
  (they bind a hypothesis to its frozen commit/time). Mitigation: freeze
  files are committed to git; the recorded `frozen_commit` can be
  cross-checked against the repo history.
* Cross-hypothesis nuance: a chunk sealed between H2's freeze and H's
  freeze is CONFIRM-for-H2 but DEV-for-H; loading it under H is granted
  (it genuinely predates H's freeze). Review multi-hypothesis analyses
  for holdout leakage through this path.
